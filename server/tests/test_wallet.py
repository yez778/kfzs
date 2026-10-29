import re
from datetime import datetime

from app.core.order_ids import build_order_id


def _customer(api_client):
    login = api_client.post(
        "/api/v1/auth/login",
        json={"username": "customer", "password": "Customer@123"},
    )
    assert login.status_code == 200
    body = login.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body


def test_password_accounts_keep_wallet(api_client):
    headers, body = _customer(api_client)
    assert body["wallet_balance"] == 2000
    me = api_client.get("/api/v1/auth/me", headers=headers).json()
    assert me["username"] == "customer"
    assert me["wallet_balance"] == 2000
    assert me["login_type"] == "password"

    admin = api_client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "Admin@123456"},
    )
    assert admin.status_code == 200
    assert admin.json()["role"] == "admin"
    assert admin.json()["wallet_balance"] == 2000


def test_wechat_login_remembers_same_local_key(api_client):
    first = api_client.post(
        "/api/v1/auth/wechat",
        json={"local_key": "dev-user-aaa", "username": "小明"},
    )
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["role"] == "customer"
    assert first_body["username"] == "小明"
    assert first_body["wallet_balance"] == 2000

    second = api_client.post(
        "/api/v1/auth/wechat",
        json={"local_key": "dev-user-aaa"},
    )
    assert second.status_code == 200
    second_me = api_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {second.json()['access_token']}"},
    ).json()
    first_me = api_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {first_body['access_token']}"},
    ).json()
    assert second_me["id"] == first_me["id"]
    assert second_me["username"] == "小明"


def test_wechat_users_are_isolated(api_client):
    a = api_client.post("/api/v1/auth/wechat", json={"local_key": "dev-user-a"}).json()
    b = api_client.post("/api/v1/auth/wechat", json={"local_key": "dev-user-b"}).json()
    me_a = api_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {a['access_token']}"}).json()
    me_b = api_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {b['access_token']}"}).json()
    assert me_a["id"] != me_b["id"]


def test_update_username_and_reject_conflict(api_client):
    login = api_client.post("/api/v1/auth/wechat", json={"local_key": "rename-user"}).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    updated = api_client.patch("/api/v1/auth/me", headers=headers, json={"username": "星途买家"})
    assert updated.status_code == 200
    assert updated.json()["username"] == "星途买家"

    conflict = api_client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"username": "customer"},
    )
    assert conflict.status_code == 409


def test_update_avatar_url_accepts_cloud_file(api_client):
    login = api_client.post("/api/v1/auth/wechat", json={"local_key": "avatar-cloud"}).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    updated = api_client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"avatar_url": "cloud://cloud1-demo/avatars/a.jpg"},
    )
    assert updated.status_code == 200
    assert updated.json()["avatar_url"].startswith("cloud://")

    rejected = api_client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"avatar_url": "javascript:alert(1)"},
    )
    assert rejected.status_code == 400


def test_checkout_creates_unpaid_order_and_sandbox_payment_makes_paid(api_client):
    headers, _ = _customer(api_client)
    products = api_client.get("/api/v1/shop/products", headers=headers, params={"size": 1}).json()
    product_id = products["items"][0]["product_id"]
    price = products["items"][0]["price"]

    # 1) 下单只生成待支付订单并预占库存，钱包不扣款
    response = api_client.post(
        "/api/v1/shop/checkout",
        headers=headers,
        json={"items": [{"product_id": product_id, "quantity": 1}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert re.match(r"^\d{4}\.\d{1,2}\.\d{1,2}\.\d{1,2}\.\d{1,2}\.\d{1,2}(\.\d+)?$", body["order_id"])
    assert body["status"] == "unpaid"
    assert body["pay_method"] == "wxpay_sandbox"
    assert body["out_trade_no"]
    assert body["pay_params"]["package"].startswith("prepay_id=")
    assert body["pay_params"]["paySign"]
    # 微信支付不扣虚拟钱包
    assert body["remaining_balance"] == 2000

    orders = api_client.get("/api/v1/auth/me/orders", headers=headers).json()
    assert orders[0]["order_id"] == body["order_id"]
    assert orders[0]["status"] == "unpaid"

    # 2) 沙箱收银台“支付成功”后订单置 paid
    paid = api_client.post(
        "/api/v1/payments/sandbox/complete",
        headers=headers,
        json={"out_trade_no": body["out_trade_no"], "result": "SUCCESS"},
    )
    assert paid.status_code == 200
    assert paid.json()["status"] == "paid"
    assert paid.json()["trade_state"] == "SUCCESS"

    orders = api_client.get("/api/v1/auth/me/orders", headers=headers).json()
    assert orders[0]["status"] == "paid"
    assert orders[0]["items"][0]["product_id"] == product_id
    me = api_client.get("/api/v1/auth/me", headers=headers).json()
    assert me["wallet_balance"] == 2000


def test_checkout_rejects_insufficient_stock(api_client):
    login = api_client.post("/api/v1/auth/wechat", json={"local_key": "poor-stock-user"}).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    products = api_client.get("/api/v1/shop/products", headers=headers, params={"size": 1}).json()
    product_id = products["items"][0]["product_id"]
    # 远超任何 SKU 库存的数量，预占阶段必须失败，且不能产生订单
    response = api_client.post(
        "/api/v1/shop/checkout",
        headers=headers,
        json={"items": [{"product_id": product_id, "quantity": 1_000_000}]},
    )
    assert response.status_code in (400, 409)
    orders = api_client.get("/api/v1/auth/me/orders", headers=headers).json()
    assert not any(o["status"] == "unpaid" for o in orders)


def test_build_order_id_matches_example_format():
    stamp = datetime(2024, 12, 3, 8, 23, 12)
    assert build_order_id(stamp) == "2024.12.3.8.23.12"
    assert build_order_id(stamp, 2) == "2024.12.3.8.23.12.2"
