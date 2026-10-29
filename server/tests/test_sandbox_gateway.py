# 本地 V2 协议网关测试：XML 解析/签名/四个官方接口/模拟付款
import hashlib

import pytest
from fastapi.testclient import TestClient

from app.api import sandbox_gateway as gw
from app.config import settings
from app.main import app

client = TestClient(app)


def _api_key() -> str:
    return (settings.payment_api_v2_key or "").strip() or settings.payment_mch_key


def _post_xml(path: str, params: dict, key: str) -> dict:
    body = dict(params)
    body["sign"] = gw.sign_md5(body, key)
    res = client.post(path, content=gw.to_xml(body), headers={"Content-Type": "application/xml"})
    assert res.status_code == 200
    return gw.from_xml(res.text)


def test_xml_roundtrip_with_special_chars():
    data = {"a": "x&y", "b": "中文 值", "c": "https://x.com/n?a=1&b=2"}
    assert gw.from_xml(gw.to_xml(data)) == data


def test_getsignkey_requires_valid_api_key_signature():
    ok = _post_xml("/api/v1/sandbox/v2/pay/getsignkey", {"mch_id": settings.payment_mch_id}, _api_key())
    assert ok["return_code"] == "SUCCESS"
    assert ok["sandbox_signkey"] == gw.sandbox_key()

    bad = _post_xml("/api/v1/sandbox/v2/pay/getsignkey", {"mch_id": settings.payment_mch_id}, "wrong-key")
    assert bad.get("err_code") == "SIGNERROR"


def test_unifiedorder_query_mockpay_close_flow():
    out_trade_no = "T20260101000001"
    unified = _post_xml(
        "/api/v1/sandbox/v2/pay/unifiedorder",
        {
            "appid": settings.payment_appid or settings.wechat_appid,
            "mch_id": settings.payment_mch_id,
            "nonce_str": "abc1234567890",
            "body": "测试商品",
            "out_trade_no": out_trade_no,
            "total_fee": 100,
            "trade_type": "JSAPI",
            "openid": "oTestOpenid0001",
        },
        gw.sandbox_key(),
    )
    assert unified["result_code"] == "SUCCESS"
    prepay_id = unified["prepay_id"]
    assert prepay_id

    query = _post_xml(
        "/api/v1/sandbox/v2/pay/orderquery",
        {"appid": "wx_test", "mch_id": settings.payment_mch_id, "out_trade_no": out_trade_no, "nonce_str": "n1"},
        gw.sandbox_key(),
    )
    assert query["trade_state"] == "NOTPAY"

    paid = _post_xml(
        "/api/v1/sandbox/v2/pay/mockpay", {"out_trade_no": out_trade_no, "nonce_str": "n2"}, gw.sandbox_key()
    )
    assert paid["trade_state"] == "SUCCESS"
    assert paid["transaction_id"]

    query2 = _post_xml(
        "/api/v1/sandbox/v2/pay/orderquery",
        {"appid": "wx_test", "mch_id": settings.payment_mch_id, "out_trade_no": out_trade_no, "nonce_str": "n3"},
        gw.sandbox_key(),
    )
    assert query2["trade_state"] == "SUCCESS"
    assert query2["transaction_id"] == paid["transaction_id"]

    # 已支付订单不可关闭
    close = _post_xml(
        "/api/v1/sandbox/v2/pay/closeorder",
        {"out_trade_no": out_trade_no, "nonce_str": "n4"},
        gw.sandbox_key(),
    )
    assert close.get("err_code") == "ORDERPAID"


def test_unifiedorder_rejects_bad_signature():
    res = _post_xml(
        "/api/v1/sandbox/v2/pay/unifiedorder",
        {
            "appid": "wx_test",
            "mch_id": settings.payment_mch_id,
            "nonce_str": "x",
            "out_trade_no": "T-BAD-SIGN",
            "total_fee": 1,
            "trade_type": "JSAPI",
            "openid": "o1",
        },
        "wrong-sandbox-key",
    )
    assert res.get("err_code") == "SIGNERROR"


def test_orderquery_unknown_order():
    res = _post_xml(
        "/api/v1/sandbox/v2/pay/orderquery",
        {"out_trade_no": "NOT-EXIST-ORDER", "nonce_str": "n"},
        gw.sandbox_key(),
    )
    assert res.get("err_code") == "ORDERNOTEXIST"
