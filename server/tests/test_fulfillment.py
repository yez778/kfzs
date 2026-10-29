# 订单履约测试：支付成功后 发货 → 物流 → 确认收货 → 退款回补库存 的完整状态机
import os
import sqlite3

from app.core.payment import build_notify_sign


def _sqlite_path() -> str:
    url = os.environ["DATABASE_URL"]
    return url.split("///", 1)[1]


def _db_scalar(sql: str, params=()):
    conn = sqlite3.connect(_sqlite_path())
    try:
        return conn.execute(sql, params).fetchone()
    finally:
        conn.close()


def _db_execute(sql: str, params=()) -> None:
    conn = sqlite3.connect(_sqlite_path())
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def _login(api_client, username: str, password: str) -> dict:
    body = api_client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    ).json()
    return {"Authorization": f"Bearer {body['access_token']}"}


def _customer(api_client):
    return _login(api_client, "customer", "Customer@123")


def _staff(api_client):
    return _login(api_client, "staff", "Staff@123456")


def _admin(api_client):
    return _login(api_client, "admin", "Admin@123456")


def _first_product(api_client, headers, index=0):
    items = api_client.get(
        "/api/v1/shop/products", headers=headers, params={"size": 5}
    ).json()["items"]
    pid = items[index]["product_id"]
    detail = api_client.get(f"/api/v1/shop/products/{pid}", headers=headers).json()
    return pid, detail["skus"][0]["sku_id"]


def _paid_order(api_client, customer, qty=1, index=0):
    """下单并支付成功，返回 (订单号, sku_id)"""
    product_id, sku_id = _first_product(api_client, customer, index=index)
    co = api_client.post(
        "/api/v1/shop/checkout",
        headers=customer,
        json={"items": [{"product_id": product_id, "quantity": qty}]},
    )
    assert co.status_code == 200, co.text
    body = co.json()
    paid = api_client.post(
        "/api/v1/payments/sandbox/complete",
        headers=customer,
        json={"out_trade_no": body["out_trade_no"], "result": "SUCCESS"},
    )
    assert paid.status_code == 200 and paid.json()["status"] == "paid"
    return body["order_id"], sku_id


def _stock(sku_id: str) -> int:
    row = _db_scalar("SELECT stock FROM product_inventory WHERE sku_id=?", (sku_id,))
    return int(row[0]) if row else -1


def test_full_fulfillment_flow(api_client):
    customer = _customer(api_client)
    staff = _staff(api_client)
    order_id, sku = _paid_order(api_client, customer, index=0)
    before = _stock(sku)

    # 1) 待发货(paid) -> 发货(shipped)
    ship = api_client.post(
        f"/api/v1/admin/orders/{order_id}/ship",
        headers=staff,
        json={"company_code": "SF", "logistics_code": "SF1234567890"},
    )
    assert ship.status_code == 200, ship.text
    s = ship.json()
    assert s["status"] == "shipped"
    assert s["ship_company"] == "SF"
    assert s["ship_company_name"] == "顺丰速运"
    assert s["logistics_code"] == "SF1234567890"
    assert s["shipped_at"]

    # 2) 买家确认收货 -> completed
    recv = api_client.post(f"/api/v1/orders/{order_id}/receive", headers=customer)
    assert recv.status_code == 200, recv.text
    assert recv.json()["status"] == "completed"
    assert recv.json()["received_at"]

    # 我的订单能看到物流信息
    mine = api_client.get("/api/v1/auth/me/orders", headers=customer).json()
    top = mine[0]
    assert top["order_id"] == order_id
    assert top["status"] == "completed"
    assert top["logistics_code"] == "SF1234567890"
    assert top["ship_company_name"] == "顺丰速运"

    # 库存：预占后不再回补（正常履约不还库存）
    assert _stock(sku) == before


def test_ship_idempotent_and_conflict(api_client):
    customer = _customer(api_client)
    staff = _staff(api_client)
    order_id, _ = _paid_order(api_client, customer, index=1)

    # 同一物流单重复发货：幂等成功
    for _ in range(2):
        r = api_client.post(
            f"/api/v1/admin/orders/{order_id}/ship",
            headers=staff,
            json={"company_code": "SF", "logistics_code": "SF111"},
        )
        assert r.status_code == 200

    # 已发货再填不同物流单：409
    r = api_client.post(
        f"/api/v1/admin/orders/{order_id}/ship",
        headers=staff,
        json={"company_code": "YTO", "logistics_code": "YT999"},
    )
    assert r.status_code == 409

    # 重复确认收货：幂等
    for _ in range(2):
        r = api_client.post(f"/api/v1/orders/{order_id}/receive", headers=customer)
        assert r.status_code == 200 and r.json()["status"] == "completed"


def test_refund_returns_stock_and_is_idempotent(api_client):
    customer = _customer(api_client)
    admin = _admin(api_client)
    # 用第 3 个商品，避免与其他用例共享同一 SKU；下单前采样库存
    product_id, sku = _first_product(api_client, customer, index=2)
    initial = _stock(sku)
    co = api_client.post(
        "/api/v1/shop/checkout",
        headers=customer,
        json={"items": [{"product_id": product_id, "quantity": 2}]},
    ).json()
    api_client.post(
        "/api/v1/payments/sandbox/complete",
        headers=customer,
        json={"out_trade_no": co["out_trade_no"], "result": "SUCCESS"},
    )
    assert _stock(sku) == initial - 2  # 预占 2
    order_id = co["order_id"]

    # 发货后退款（paid/shipped 均可退）
    api_client.post(
        f"/api/v1/admin/orders/{order_id}/ship",
        headers=admin,
        json={"company_code": "ZTO", "logistics_code": "ZTO88"},
    )
    refund = api_client.post(
        f"/api/v1/admin/orders/{order_id}/refund", headers=admin, json={"reason": "质量问题"}
    )
    assert refund.status_code == 200, refund.text
    r = refund.json()
    assert r["status"] == "refunded"
    assert r["refund_no"].startswith("RFD")
    assert r["refunded_at"]
    # 退款回补预占库存
    assert _stock(sku) == initial

    # 重复退款：幂等返回同一退款单号，库存不重复回补
    again = api_client.post(
        f"/api/v1/admin/orders/{order_id}/refund", headers=admin, json={}
    )
    assert again.status_code == 200
    assert again.json()["refund_no"] == r["refund_no"]
    assert _stock(sku) == initial


def test_fulfillment_state_guard(api_client):
    customer = _customer(api_client)
    staff = _staff(api_client)
    product_id, _ = _first_product(api_client, customer, index=3)

    # 未支付订单不能发货 / 退款
    co = api_client.post(
        "/api/v1/shop/checkout",
        headers=customer,
        json={"items": [{"product_id": product_id, "quantity": 1}]},
    ).json()
    ship = api_client.post(
        f"/api/v1/admin/orders/{co['order_id']}/ship",
        headers=staff,
        json={"company_code": "SF", "logistics_code": "SF1"},
    )
    assert ship.status_code == 409
    refund = api_client.post(
        f"/api/v1/admin/orders/{co['order_id']}/refund", headers=staff, json={}
    )
    assert refund.status_code == 409

    # 未发货订单不能确认收货
    recv = api_client.post(f"/api/v1/orders/{co['order_id']}/receive", headers=customer)
    assert recv.status_code == 409


def test_receive_checks_ownership(api_client):
    # 用户 A 不能确认用户 B 的订单
    customer_a = _customer(api_client)
    # 创建另一个真实用户（wechat 登录会按 local_key 新建独立账号）
    other = api_client.post(
        "/api/v1/auth/wechat", json={"local_key": "other-buyer"}
    ).json()
    customer_b = {"Authorization": f"Bearer {other['access_token']}"}

    order_id, _ = _paid_order(api_client, customer_a, index=4)
    api_client.post(
        f"/api/v1/admin/orders/{order_id}/ship",
        headers=_staff(api_client),
        json={"company_code": "SF", "logistics_code": "SF2"},
    )
    # 用户 B 试图确认 A 的订单：404（不泄露订单存在）
    resp = api_client.post(f"/api/v1/orders/{order_id}/receive", headers=customer_b)
    assert resp.status_code == 404
    # 订单归属 A：A 仍可正常确认
    ok = api_client.post(f"/api/v1/orders/{order_id}/receive", headers=customer_a)
    assert ok.status_code == 200 and ok.json()["status"] == "completed"


def test_ship_rejects_unknown_company(api_client):
    customer = _customer(api_client)
    staff = _staff(api_client)
    order_id, _ = _paid_order(api_client, customer, index=0)
    r = api_client.post(
        f"/api/v1/admin/orders/{order_id}/ship",
        headers=staff,
        json={"company_code": "XXX", "logistics_code": "SF1"},
    )
    assert r.status_code == 422


def test_shipping_companies_list(api_client):
    staff = _staff(api_client)
    companies = api_client.get("/api/v1/shipping/companies", headers=staff)
    assert companies.status_code == 200
    codes = {c["code"] for c in companies.json()}
    assert {"SF", "ZTO", "YTO"} <= codes
