# 官方 V2 仿真模式 API 集成测试：通过 monkeypatch 替换真实网关调用，验证模式分流与业务链路。
import pytest

from app.core import payment_v2


@pytest.fixture()
def v2_mode(monkeypatch):
    # 切到官方 V2 仿真，并提供可下单的真实 openid
    monkeypatch.setattr(
        "app.config.settings.payment_mode", "v2sandbox", raising=False
    )
    monkeypatch.setattr(
        "app.config.settings.payment_sandbox_openid", "oRealOpenidForTest", raising=False
    )
    # 沙箱密钥缓存
    payment_v2.sandbox_key_cache.set("unit-sandbox-key")
    yield
    payment_v2.sandbox_key_cache.reset()


def _login(api_client, key="v2-user"):
    tok = api_client.post("/api/v1/auth/wechat", json={"local_key": key}).json()
    return {"Authorization": f"Bearer {tok['access_token']}"}


def _first_product(api_client, headers):
    return api_client.get(
        "/api/v1/shop/products", headers=headers, params={"size": 1}
    ).json()["items"][0]["product_id"]


def test_v2_checkout_calls_official_unifiedorder(api_client, v2_mode, monkeypatch):
    calls = {}

    async def fake_unified(*, out_trade_no, amount_fen, description, openid, client_ip="127.0.0.1"):
        calls["out_trade_no"] = out_trade_no
        calls["amount_fen"] = amount_fen
        calls["openid"] = openid
        return {
            "prepay_id": "wx-sandbox-prepay-1",
            "jsapi_params": payment_v2.build_jsapi_params_v2(
                "wx-sandbox-prepay-1", sandbox_key="unit-sandbox-key"
            ),
            "raw": {},
        }

    monkeypatch.setattr(payment_v2, "unified_order_jsapi", fake_unified)

    headers = _login(api_client)
    pid = _first_product(api_client, headers)
    resp = api_client.post(
        "/api/v1/shop/checkout",
        headers=headers,
        json={"items": [{"product_id": pid, "quantity": 1}]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "unpaid"
    assert calls["out_trade_no"] == body["out_trade_no"]
    assert calls["amount_fen"] == round(body["total_amount"] * 100)
    # 真实网关函数内部会用 PAYMENT_SANDBOX_OPENID 覆盖 dev: openid（见纯函数测试）
    assert calls["openid"].startswith("dev:")
    # 返回的是官方 V2 风格 MD5 的 JSAPI 参数
    assert body["pay_params"]["signType"] == "MD5"
    assert body["pay_params"]["package"] == "prepay_id=wx-sandbox-prepay-1"
    assert body["pay_params"]["sandbox"] == "v2"


def test_v2_checkout_gateway_failure_closes_order_and_releases(api_client, v2_mode, monkeypatch):
    async def boom(**kwargs):
        raise payment_v2.V2PaymentError("getsignkey 无权限", code=400)

    monkeypatch.setattr(payment_v2, "unified_order_jsapi", boom)
    headers = _login(api_client, "v2-user-fail")
    pid = _first_product(api_client, headers)
    resp = api_client.post(
        "/api/v1/shop/checkout",
        headers=headers,
        json={"items": [{"product_id": pid, "quantity": 1}]},
    )
    assert resp.status_code == 400
    orders = api_client.get("/api/v1/auth/me/orders", headers=headers).json()
    # 下单失败：订单被取消（不会悬挂 unpaid）
    assert orders
    assert orders[0]["status"] == "cancelled"


def test_v2_complete_queries_official_order_and_marks_paid(api_client, v2_mode, monkeypatch):
    async def fake_unified(**kwargs):
        return {
            "prepay_id": "wx-pre",
            "jsapi_params": payment_v2.build_jsapi_params_v2(
                "wx-pre", sandbox_key="unit-sandbox-key"
            ),
            "raw": {},
        }

    monkeypatch.setattr(payment_v2, "unified_order_jsapi", fake_unified)

    async def fake_query(*, out_trade_no="", transaction_id=""):
        return {
            "out_trade_no": out_trade_no,
            "transaction_id": "4200-v2-txn",
            "trade_state": "SUCCESS",
            "trade_state_desc": "支付成功",
            "total_fee": 35000,
            "raw": {},
        }

    monkeypatch.setattr(payment_v2, "order_query", fake_query)

    headers = _login(api_client, "v2-user-paid")
    pid = _first_product(api_client, headers)
    co = api_client.post(
        "/api/v1/shop/checkout",
        headers=headers,
        json={"items": [{"product_id": pid, "quantity": 1}]},
    ).json()

    done = api_client.post(
        "/api/v1/payments/sandbox/complete",
        headers=headers,
        json={"out_trade_no": co["out_trade_no"], "result": "SUCCESS"},
    )
    assert done.status_code == 200
    assert done.json()["status"] == "paid"
    assert done.json()["trade_state"] == "SUCCESS"
    assert done.json()["transaction_id"] == "4200-v2-txn"


def test_v2_xml_notify_marks_paid(api_client, v2_mode, monkeypatch):
    async def fake_unified(**kwargs):
        return {
            "prepay_id": "wx-pre-xml",
            "jsapi_params": payment_v2.build_jsapi_params_v2(
                "wx-pre-xml", sandbox_key="unit-sandbox-key"
            ),
            "raw": {},
        }

    monkeypatch.setattr(payment_v2, "unified_order_jsapi", fake_unified)

    headers = _login(api_client, "v2-user-notify")
    pid = _first_product(api_client, headers)
    co = api_client.post(
        "/api/v1/shop/checkout",
        headers=headers,
        json={"items": [{"product_id": pid, "quantity": 1}]},
    ).json()

    amount_fen = round(co["total_amount"] * 100)
    notify = {
        "appid": "wxd930",
        "mch_id": "1900000109",
        "out_trade_no": co["out_trade_no"],
        "transaction_id": "4200-v2-callback",
        "result_code": "SUCCESS",
        "return_code": "SUCCESS",
        "total_fee": str(amount_fen),
    }
    notify["sign"] = payment_v2.sign_md5(notify, "unit-sandbox-key")
    xml = payment_v2.dict_to_xml(notify)

    resp = api_client.post(
        "/api/v1/payments/notify/wechat/v2",
        content=xml.encode("utf-8"),
        headers={"Content-Type": "application/xml"},
    )
    assert resp.status_code == 200
    assert "SUCCESS" in resp.text

    status = api_client.get(
        f"/api/v1/payments/by-order/{co['order_id']}", headers=headers
    ).json()
    assert status["status"] == "paid"
    assert status["transaction_id"] == "4200-v2-callback"


def test_v2_xml_notify_rejects_bad_signature(api_client, v2_mode, monkeypatch):
    async def fake_unified(**kwargs):
        return {
            "prepay_id": "wx-pre-bad",
            "jsapi_params": payment_v2.build_jsapi_params_v2(
                "wx-pre-bad", sandbox_key="unit-sandbox-key"
            ),
            "raw": {},
        }

    monkeypatch.setattr(payment_v2, "unified_order_jsapi", fake_unified)
    headers = _login(api_client, "v2-user-badsign")
    pid = _first_product(api_client, headers)
    co = api_client.post(
        "/api/v1/shop/checkout",
        headers=headers,
        json={"items": [{"product_id": pid, "quantity": 1}]},
    ).json()

    xml = (
        f"<xml><out_trade_no>{co['out_trade_no']}</out_trade_no>"
        "<total_fee>35000</total_fee>"
        "<result_code>SUCCESS</result_code><return_code>SUCCESS</return_code>"
        "<sign>DEADBEEF</sign></xml>"
    )
    resp = api_client.post(
        "/api/v1/payments/notify/wechat/v2",
        content=xml.encode("utf-8"),
        headers={"Content-Type": "application/xml"},
    )
    assert resp.status_code == 401
