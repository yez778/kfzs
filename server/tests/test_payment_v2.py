# 官方 V2 仿真客户端纯函数测试：MD5 签名、XML 互转、通知验签、openid 解析。
# 不发起任何真实网络请求（网关调用在接入时用 python -m app.core.payment_v2 自检）。
import pytest

from app.core import payment_v2
from app.core.payment_v2 import (
    dict_to_xml,
    sign_md5,
    verify_v2_notify,
    xml_to_dict,
)


def test_sign_md5_implements_wechat_v2_rule():
    # 微信 V2 规则：非空参数按 key 的 ASCII 字典序拼成 a=1&b=2，末尾拼 &key=K，再 MD5 大写。
    # 这里的期望值由 stringSignTemp 直接 MD5 独立计算得到（确定性回归向量），
    # 防止排序/过滤/拼接逻辑被误改：
    #   stringA = appid=...&body=test&mch_id=...&nonce_str=...&total_fee=1
    params = {
        "appid": "wxd930ea5d5a258f4f",
        "mch_id": "10000100",
        "body": "test",
        "nonce_str": "ibuaiVcKqpZPlyT7",
        "total_fee": 1,
    }
    assert sign_md5(params, "192006250b4c09247ec02edce69f6a2d") == (
        "E4929744121A576268AEE8250C343AC2"
    )


def test_sign_ignores_empty_and_sign_field():
    base = {"appid": "wx123", "mch_id": "m1", "nonce_str": "abc"}
    with_empty = dict(base)
    with_empty["empty"] = ""
    with_empty["sign"] = "SHOULD-BE-IGNORED"
    assert sign_md5(with_empty, "key") == sign_md5(base, "key")


def test_dict_xml_roundtrip_escapes_special_chars():
    params = {
        "appid": "wxd930",
        "return_msg": "OK",
        "body": "太阳能柱头灯 350.00 元 & 包邮",
    }
    xml = dict_to_xml(params)
    assert xml.startswith("<xml>") and xml.endswith("</xml>")
    assert "&amp;" in xml  # & 被 XML 转义
    parsed = xml_to_dict(xml)
    assert parsed["appid"] == "wxd930"
    assert parsed["body"] == "太阳能柱头灯 350.00 元 & 包邮"


def test_xml_parse_plain_and_cdata_values():
    xml = (
        "<xml>"
        "<return_code><![CDATA[SUCCESS]]></return_code>"
        "<total_fee>35000</total_fee>"
        "<prepay_id><![CDATA[wx201410272009395522657a690389285100]]></prepay_id>"
        "</xml>"
    )
    data = xml_to_dict(xml)
    assert data["return_code"] == "SUCCESS"
    assert data["total_fee"] == "35000"
    assert data["prepay_id"].startswith("wx2014")


def test_xml_parse_rejects_external_entity_payload():
    # 不使用通用 XML 实体解析器：外部实体声明不会被解析，只会得到空/普通字段
    malicious = (
        "<!DOCTYPE foo [<!ENTITY xxe SYSTEM \"file:///etc/passwd\">]>"
        "<xml><return_code>&xxe;</return_code></xml>"
    )
    data = xml_to_dict(malicious)
    assert "passwd" not in str(data)
    assert data.get("return_code", "") in ("", "&xxe;")


def test_jsapi_params_v2_signed_with_md5():
    params = payment_v2.build_jsapi_params_v2("wx-prepay-123", sandbox_key="sandboxkey")
    assert params["signType"] == "MD5"
    assert params["package"] == "prepay_id=wx-prepay-123"
    # 用相同密钥重算应一致
    expected = sign_md5(
        {
            "appId": params["appId"],
            "timeStamp": params["timeStamp"],
            "nonceStr": params["nonceStr"],
            "package": params["package"],
            "signType": "MD5",
        },
        "sandboxkey",
    )
    assert params["paySign"] == expected


def test_verify_v2_notify_valid_and_invalid():
    notify = {
        "appid": "wx123",
        "mch_id": "1900000109",
        "out_trade_no": "20240101001",
        "transaction_id": "42000001",
        "result_code": "SUCCESS",
        "return_code": "SUCCESS",
        "total_fee": "35000",
    }
    notify["sign"] = sign_md5(notify, "realsandboxkey")
    assert verify_v2_notify(notify, sandbox_key="realsandboxkey") is True
    # 篡改金额后验签失败
    tampered = dict(notify)
    tampered["total_fee"] = "1"
    assert verify_v2_notify(tampered, sandbox_key="realsandboxkey") is False
    # 错误密钥失败
    assert verify_v2_notify(notify, sandbox_key="wrongkey") is False


def test_verify_v2_notify_without_cached_key_returns_false():
    payment_v2.sandbox_key_cache.reset()
    assert verify_v2_notify({"sign": "x"}) is False


def test_resolve_jsapi_openid(monkeypatch):
    # dev: 本地账号不是真实 openid，未配置覆盖时应拒绝
    monkeypatch.setattr(payment_v2.settings, "payment_sandbox_openid", "", raising=False)
    with pytest.raises(payment_v2.V2PaymentError):
        payment_v2.resolve_jsapi_openid("dev:abc123")
    # 配置了真实测试 openid 时优先生效
    monkeypatch.setattr(
        payment_v2.settings, "payment_sandbox_openid", "oRealOpenid0001", raising=False
    )
    assert payment_v2.resolve_jsapi_openid("dev:abc") == "oRealOpenid0001"
