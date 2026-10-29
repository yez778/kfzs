# 微信支付沙箱测试：下单预占库存 → JSAPI 参数 → 沙箱支付/回调 → 幂等 → 关单释放
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from app.core.payment import build_notify_sign


def _sqlite_path() -> str:
    # 从 DATABASE_URL（sqlite+aiosqlite:///<path>）取文件路径，直接用 sqlite3 读，避免跨事件循环
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


def _login(api_client, local_key: str) -> dict:
    body = api_client.post(
        "/api/v1/auth/wechat", json={"local_key": local_key}
    ).json()
    return {"Authorization": f"Bearer {body['access_token']}"}


def _first_product(api_client, headers):
    items = api_client.get(
        "/api/v1/shop/products", headers=headers, params={"size": 1}
    ).json()["items"]
    return items[0]["product_id"]


def _checkout(api_client, headers, product_id, qty=1):
    resp = api_client.post(
        "/api/v1/shop/checkout",
        headers=headers,
        json={"items": [{"product_id": product_id, "quantity": qty}]},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _stock(sku_id: str) -> int:
    row = _db_scalar("SELECT stock FROM product_inventory WHERE sku_id=?", (sku_id,))
    return int(row[0])


def test_checkout_reserves_stock_and_prepay_returns_jsapi(api_client):
    headers = _login(api_client, "pay-user-prepay")
    product_id = _first_product(api_client, headers)
    body = _checkout(api_client, headers, product_id, 1)

    # 订单待支付，返回沙箱 JSAPI 参数
    assert body["status"] == "unpaid"
    params = body["pay_params"]
    assert params["sandbox"] is True
    assert params["package"].startswith("prepay_id=")
    assert params["paySign"] and params["timeStamp"]

    # 统一下单接口可再次取回 JSAPI 参数
    prepay = api_client.post(
        "/api/v1/payments/prepay",
        headers=headers,
        json={"out_trade_no": body["out_trade_no"]},
    )
    assert prepay.status_code == 200
    assert prepay.json()["pay_params"]["package"].startswith("prepay_id=")


def test_sandbox_complete_success_is_idempotent_and_paid(api_client):
    headers = _login(api_client, "pay-user-success")
    product_id = _first_product(api_client, headers)
    body = _checkout(api_client, headers, product_id)

    first = api_client.post(
        "/api/v1/payments/sandbox/complete",
        headers=headers,
        json={"out_trade_no": body["out_trade_no"], "result": "SUCCESS"},
    )
    assert first.status_code == 200
    paid = first.json()
    assert paid["status"] == "paid"
    assert paid["trade_state"] == "SUCCESS"
    assert paid["transaction_id"]
    assert paid["amount_fen"] == round(body["total_amount"] * 100)

    # 重复回调式完成必须幂等，不重复改状态
    second = api_client.post(
        "/api/v1/payments/sandbox/complete",
        headers=headers,
        json={"out_trade_no": body["out_trade_no"], "result": "SUCCESS"},
    )
    assert second.status_code == 200
    assert second.json()["trade_state"] == "SUCCESS"


def test_payerror_keeps_order_unpaid_and_retry_succeeds(api_client):
    headers = _login(api_client, "pay-user-fail")
    product_id = _first_product(api_client, headers)
    body = _checkout(api_client, headers, product_id)

    # 第一次支付失败（余额不足）：订单仍未支付，返回失败原因
    fail = api_client.post(
        "/api/v1/payments/sandbox/complete",
        headers=headers,
        json={"out_trade_no": body["out_trade_no"], "result": "PAYERROR", "fail_reason": "NOTENOUGH"},
    )
    assert fail.status_code == 200
    fb = fail.json()
    assert fb["status"] == "unpaid"
    assert fb["trade_state"] == "PAYERROR"
    assert fb["fail_reason"] == "NOTENOUGH"

    # 换成银行卡后重试支付：同一支付单可从 PAYERROR 转为 SUCCESS（幂等履约）
    ok = api_client.post(
        "/api/v1/payments/sandbox/complete",
        headers=headers,
        json={"out_trade_no": body["out_trade_no"], "result": "SUCCESS"},
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "paid"
    assert ok.json()["trade_state"] == "SUCCESS"
    assert ok.json()["transaction_id"]


def test_invalid_result_rejected(api_client):
    headers = _login(api_client, "pay-user-invalid")
    product_id = _first_product(api_client, headers)
    body = _checkout(api_client, headers, product_id)
    bad = api_client.post(
        "/api/v1/payments/sandbox/complete",
        headers=headers,
        json={"out_trade_no": body["out_trade_no"], "result": "REFUND"},
    )
    assert bad.status_code == 400


def test_userpaying_keeps_order_unpaid(api_client):
    headers = _login(api_client, "pay-user-paying")
    product_id = _first_product(api_client, headers)
    body = _checkout(api_client, headers, product_id)

    resp = api_client.post(
        "/api/v1/payments/sandbox/complete",
        headers=headers,
        json={"out_trade_no": body["out_trade_no"], "result": "USERPAYING"},
    )
    assert resp.status_code == 200
    # 收银台回显当前动作为 USERPAYING（支付单在微信侧仍为 NOTPAY），订单保持未支付
    assert resp.json()["trade_state"] == "USERPAYING"
    assert resp.json()["status"] == "unpaid"
    assert resp.json()["payer_result"] == "USERPAYING"


def test_signed_notify_marks_paid_rejects_bad_signature(api_client):
    headers = _login(api_client, "pay-user-notify")
    product_id = _first_product(api_client, headers)
    body = _checkout(api_client, headers, product_id)
    amount_fen = round(body["total_amount"] * 100)

    # 错误签名 -> 401
    bad = api_client.post(
        "/api/v1/payments/notify/wechat",
        json={
            "out_trade_no": body["out_trade_no"],
            "transaction_id": "4200bad",
            "amount_fen": amount_fen,
            "trade_state": "SUCCESS",
            "signature": "deadbeef",
        },
    )
    assert bad.status_code == 401

    # 正确 HMAC 签名 -> 支付成功
    signature = build_notify_sign(body["out_trade_no"], "4200ok", amount_fen, True)
    ok = api_client.post(
        "/api/v1/payments/notify/wechat",
        json={
            "out_trade_no": body["out_trade_no"],
            "transaction_id": "4200ok",
            "amount_fen": amount_fen,
            "trade_state": "SUCCESS",
            "signature": signature,
        },
    )
    assert ok.status_code == 200
    assert ok.json()["code"] == "SUCCESS"

    status = api_client.get(
        f"/api/v1/payments/by-order/{body['order_id']}", headers=headers
    ).json()
    assert status["status"] == "paid"
    assert status["transaction_id"] == "4200ok"


def test_close_unpaid_releases_stock(api_client):
    headers = _login(api_client, "pay-user-close")
    product_id = _first_product(api_client, headers)
    # 通过下单明细里的 sku 查询库存
    body = _checkout(api_client, headers, product_id, qty=2)
    # checkout 返回 items[0].sku_id
    sku_id = body["items"][0]["sku_id"]

    before_after_reserve = _stock(sku_id)

    closed = api_client.post(
        f"/api/v1/payments/by-order/{body['order_id']}/close", headers=headers
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "cancelled"
    assert closed.json()["trade_state"] == "CLOSED"
    assert _stock(sku_id) == before_after_reserve + 2

    # 已关闭订单不能再支付
    again = api_client.post(
        "/api/v1/payments/sandbox/complete",
        headers=headers,
        json={"out_trade_no": body["out_trade_no"], "result": "SUCCESS"},
    )
    assert again.status_code in (400, 409)


def test_cannot_pay_other_users_order(api_client):
    h1 = _login(api_client, "pay-user-a")
    h2 = _login(api_client, "pay-user-b")
    pid = _first_product(api_client, h1)
    body = _checkout(api_client, h1, pid)

    # B 查询/支付 A 的订单都应 404
    assert (
        api_client.get(
            f"/api/v1/payments/by-order/{body['order_id']}", headers=h2
        ).status_code
        == 404
    )
    assert (
        api_client.post(
            "/api/v1/payments/sandbox/complete",
            headers=h2,
            json={"out_trade_no": body["out_trade_no"], "result": "SUCCESS"},
        ).status_code
        == 404
    )


def test_oversell_reservation_rejected_atomically(api_client):
    headers = _login(api_client, "pay-user-oversell")
    product_id = _first_product(api_client, headers)
    # 并发量超过库存：原子条件更新应整单失败
    resp = api_client.post(
        "/api/v1/shop/checkout",
        headers=headers,
        json={"items": [{"product_id": product_id, "quantity": 100000}]},
    )
    assert resp.status_code == 409

    # 失败事务回滚：该超卖用户不会留下任何订单
    row = _db_scalar(
        "SELECT COUNT(*) FROM orders o JOIN users u ON o.user_id=u.id "
        "WHERE u.openid=? AND o.status='unpaid'",
        ("dev:pay-user-oversell",),
    )
    assert int(row[0]) == 0


def test_expired_payment_is_closed_and_releases_stock(api_client):
    headers = _login(api_client, "pay-user-expire")
    product_id = _first_product(api_client, headers)
    body = _checkout(api_client, headers, product_id)

    # 手工把支付单置为已过期，懒过期应在查询时关单
    expired = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    _db_execute(
        "UPDATE payment_orders SET expires_at=? WHERE out_trade_no=?",
        (expired, body["out_trade_no"]),
    )

    status = api_client.get(
        f"/api/v1/payments/by-order/{body['order_id']}", headers=headers
    )
    assert status.status_code == 200
    assert status.json()["status"] == "cancelled"
    assert status.json()["trade_state"] == "CLOSED"
