# 微信支付【官方 V2 仿真测试系统】客户端（XML + MD5）。
#
# 与本地自建沙箱（core/payment.py）相互独立：PAYMENT_MODE=v2sandbox 时启用本模块，
# 真实请求 https://api.mch.weixin.qq.com/sandboxnew/... 接口，校验真实商户号/密钥签名。
#
# 官方 V2 仿真环境接口（均为 XML POST，签名类型 MD5）：
#   1. 获取沙箱密钥  /sandboxnew/pay/getsignkey   （用真实 mch_id + 真实 APIv2 密钥签名）
#   2. 统一下单      /sandboxnew/pay/unifiedorder （用沙箱密钥签名，返回沙箱 prepay_id）
#   3. 查询订单      /sandboxnew/pay/orderquery
#   4. 关闭订单      /sandboxnew/pay/closeorder
#
# 注意：
#   - 仿真系统只验证后端报文/签名/订单状态机，不会真正扣款，也无法在小程序里调起真实收银台。
#   - JSAPI 支付在仿真环境没有“模拟付款成功”的官方触发入口；支付成功以 orderquery 轮询为准
#     （官方仿真测试用例里部分场景可通过用例规则触发，普通商户联调主要用 orderquery/关单验证）。
#   - 上线请走 V3（JSON + RSA + 平台证书 + AES-GCM），本模块仅用于后端对接联调/答辩演示真实报文。
from __future__ import annotations

import hashlib
import html
import logging
import re
import threading
import time

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

SANDBOX_BASE = "https://api.mch.weixin.qq.com/sandboxnew"
GETSIGNKEY_URL = f"{SANDBOX_BASE}/pay/getsignkey"
UNIFIEDORDER_URL = f"{SANDBOX_BASE}/pay/unifiedorder"
ORDERQUERY_URL = f"{SANDBOX_BASE}/pay/orderquery"
CLOSEORDER_URL = f"{SANDBOX_BASE}/pay/closeorder"

# 微信通信成功标识
RETURN_SUCCESS = "SUCCESS"
RESULT_SUCCESS = "SUCCESS"


class V2PaymentError(Exception):
    """官方 V2 沙箱调用异常。code 为建议 HTTP 状态码。"""

    def __init__(self, message: str, code: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------- 纯函数（便于单测，不依赖网络） ----------------------------


def nonce_str(length: int = 32) -> str:
    import secrets

    return secrets.token_hex(length // 2 + 1)[:length]


def _filter_for_sign(params: dict) -> dict:
    # 签名规则：剔除 sign 与空值；key 按 ASCII 字典序排序
    return {k: str(v) for k, v in params.items() if k != "sign" and v not in (None, "")}


def sign_md5(params: dict, key: str) -> str:
    # V2 签名：排序后的键值对串接后末尾拼 &key=API密钥，做 MD5（大写）
    filtered = _filter_for_sign(params)
    pairs = sorted(filtered.items(), key=lambda kv: kv[0])
    string_a = "&".join(f"{k}={v}" for k, v in pairs)
    string_sign_temp = f"{string_a}&key={key}"
    return hashlib.md5(string_sign_temp.encode("utf-8")).hexdigest().upper()


def dict_to_xml(params: dict) -> str:
    # 微信支付请求报文为 UTF-8 XML，使用明文标签并对特殊字符做 XML 转义（与官方 SDK 一致）
    parts = ["<xml>"]
    for key, value in params.items():
        escaped = html.escape(str(value), quote=True)
        parts.append(f"<{key}>{escaped}</{key}>")
    parts.append("</xml>")
    return "".join(parts)


def xml_to_dict(xml_text: str) -> dict:
    # 微信支付响应固定为 <xml><key>value</key>...</xml> 一层结构，不使用外部实体解析器，杜绝 XXE。
    pairs = re.findall(
        r"<([A-Za-z0-9_]+)>\s*(?:<!\[CDATA\[(.*?)\]\]>|([^<]*?))\s*</\1>",
        xml_text,
        flags=re.DOTALL,
    )
    flat: dict[str, str] = {}
    for key, cdata, plain in pairs:
        flat[key] = cdata if cdata else html.unescape((plain or "").strip())
    return flat


# 兼容别名
_flat_xml = xml_to_dict


# ---------------------------- 沙箱密钥缓存 ----------------------------


class SandboxKeyCache:
    """进程内缓存 getsignkey 得到的沙箱密钥（官方文档：同一商户获取的沙箱密钥保持不变）。"""

    def __init__(self) -> None:
        self._key: str = ""
        self._lock = threading.Lock()

    def get_cached(self) -> str:
        return self._key

    def set(self, key: str) -> None:
        with self._lock:
            self._key = key

    def reset(self) -> None:
        with self._lock:
            self._key = ""


sandbox_key_cache = SandboxKeyCache()


# ---------------------------- HTTP 客户端 ----------------------------


def _effective_appid() -> str:
    return settings.payment_appid or settings.wechat_appid


def _check_common_response(data: dict, action: str) -> dict:
    # 通信层面 return_code / 业务层面 result_code 都可能失败
    if data.get("return_code") != RETURN_SUCCESS:
        msg = data.get("return_msg", "通信失败")
        raise V2PaymentError(f"[{action}] 微信通信失败：{msg}", code=502)
    if data.get("result_code") != RESULT_SUCCESS:
        err_code = data.get("err_code", "")
        err_code_des = data.get("err_code_des", "")
        raise V2PaymentError(
            f"[{action}] 业务失败：{err_code} {err_code_des}".strip(),
            code=400 if err_code in ("ORDERPAID", "ORDERNOTEXIST", "ORDERCLOSED") else 502,
        )
    return data


async def _post_xml(url: str, body: dict, timeout: float = 15.0) -> dict:
    xml_body = dict_to_xml(body)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            url,
            content=xml_body.encode("utf-8"),
            headers={"Content-Type": "application/xml; charset=utf-8"},
        )
    if resp.status_code != 200:
        raise V2PaymentError(f"微信网关 HTTP {resp.status_code}: {resp.text[:200]}", code=502)
    data = _flat_xml(resp.text)
    if not data:
        raise V2PaymentError(f"微信返回为空或非法：{resp.text[:200]}", code=502)
    return data


async def get_sandbox_sign_key(*, force_refresh: bool = False) -> str:
    """用真实 mch_id + 真实 APIv2 密钥请求 getsignkey，换取沙箱专用密钥并缓存。"""
    cached = sandbox_key_cache.get_cached()
    if cached and not force_refresh:
        return cached

    mch_id = settings.payment_mch_id
    real_key = settings.payment_api_v2_key
    if not mch_id or mch_id == "1900000000":
        raise V2PaymentError("未配置真实微信支付商户号 PAYMENT_MCH_ID", code=400)
    if not real_key or real_key == settings.payment_mch_key:
        raise V2PaymentError(
            "V2 仿真环境必须配置真实 APIv2 密钥 PAYMENT_API_V2_KEY（商户平台-API安全-APIv2密钥）",
            code=400,
        )

    body = {
        "mch_id": mch_id,
        "nonce_str": nonce_str(),
    }
    body["sign"] = sign_md5(body, real_key)
    data = await _post_xml(GETSIGNKEY_URL, body)
    if data.get("return_code") != RETURN_SUCCESS:
        raise V2PaymentError(f"[getsignkey] {data.get('return_msg', '获取沙箱密钥失败')}", code=502)
    sandbox_key = data.get("sandbox_signkey") or ""
    if not sandbox_key:
        raise V2PaymentError(f"[getsignkey] 未返回 sandbox_signkey：{data}", code=502)
    sandbox_key_cache.set(sandbox_key)
    logger.info("wechat v2 sandbox sign key refreshed for mch_id=%s", mch_id)
    return sandbox_key


async def _signed_sandbox_post(url: str, params: dict, action: str) -> dict:
    # 仿真环境除 getsignkey 外，统一用沙箱密钥做 MD5 签名
    sandbox_key = await get_sandbox_sign_key()
    body = dict(params)
    body["sign"] = sign_md5(body, sandbox_key)
    data = await _post_xml(url, body)
    return _check_common_response(data, action)


# ---------------------------- 业务接口 ----------------------------


def resolve_jsapi_openid(payment_openid: str) -> str:
    # 仿真统一下单（trade_type=JSAPI）必须带真实 openid；本地 dev: 账号不是真实 openid
    override = settings.payment_sandbox_openid.strip()
    openid = override or payment_openid
    if not openid or openid.startswith("dev:"):
        raise V2PaymentError(
            "官方 V2 仿真统一下单需要真实微信 openid：请配置 PAYMENT_SANDBOX_OPENID，"
            "或用真实微信登录（WECHAT_SECRET）后再下单",
            code=400,
        )
    return openid


def missing_v2_config() -> list[str]:
    """检查官方 V2 沙箱所需配置，返回缺失项（供下单前一次性提示）"""
    issues: list[str] = []
    if not _effective_appid():
        issues.append("PAYMENT_APPID 或 WECHAT_APPID")
    mch_id = (settings.payment_mch_id or "").strip()
    if not mch_id or mch_id == "1900000000":
        issues.append("PAYMENT_MCH_ID（真实商户号）")
    if not (settings.payment_api_v2_key or "").strip():
        issues.append("PAYMENT_API_V2_KEY（商户平台 APIv2 密钥）")
    if not (settings.payment_sandbox_openid or "").strip():
        issues.append("PAYMENT_SANDBOX_OPENID（真实小程序用户 openid）")
    return issues


async def unified_order_jsapi(
    *,
    out_trade_no: str,
    amount_fen: int,
    description: str,
    openid: str,
    client_ip: str = "127.0.0.1",
) -> dict:
    # 统一下单：返回 {"prepay_id": ..., "jsapi_params": {...wx.requestPayment...}}
    missing = missing_v2_config()
    if missing:
        raise V2PaymentError(
            "微信官方 V2 沙箱配置不完整，缺少：" + "、".join(missing) + "（详见 GET /api/v1/payments/config）",
            code=400,
        )
    appid = _effective_appid()
    params = {
        "appid": appid,
        "mch_id": settings.payment_mch_id,
        "nonce_str": nonce_str(),
        "body": (description or "星途户外照明订单")[:128],
        "out_trade_no": out_trade_no,
        "total_fee": int(amount_fen),
        "spbill_create_ip": client_ip,
        "notify_url": settings.payment_notify_url or f"{SANDBOX_BASE}/pay/notifyurl",
        "trade_type": "JSAPI",
        "openid": resolve_jsapi_openid(openid),
    }
    data = await _signed_sandbox_post(UNIFIEDORDER_URL, params, "unifiedorder")
    prepay_id = data.get("prepay_id") or ""
    if not prepay_id:
        raise V2PaymentError("统一下单未返回 prepay_id", code=502)
    return {
        "prepay_id": prepay_id,
        "jsapi_params": build_jsapi_params_v2(prepay_id, sandbox_key=await get_sandbox_sign_key()),
        "raw": data,
    }


def build_jsapi_params_v2(prepay_id: str, *, sandbox_key: str) -> dict:
    # 小程序 wx.requestPayment（V2）：appId/timeStamp/nonceStr/package/signType=MD5/paySign
    appid = _effective_appid()
    time_stamp = str(int(time.time()))
    nonce = nonce_str()
    package = f"prepay_id={prepay_id}"
    sign_source = {
        "appId": appid,
        "timeStamp": time_stamp,
        "nonceStr": nonce,
        "package": package,
        "signType": "MD5",
    }
    # 调起支付签名仍按 V2 规则 MD5（key=沙箱密钥）
    pay_sign = sign_md5(sign_source, sandbox_key)
    return {
        "sandbox": "v2",
        "appId": appid,
        "timeStamp": time_stamp,
        "nonceStr": nonce,
        "package": package,
        "signType": "MD5",
        "paySign": pay_sign,
    }


async def order_query(*, out_trade_no: str = "", transaction_id: str = "") -> dict:
    # 查询订单：返回微信侧 trade_state（SUCCESS/NOTPAY/CLOSED/REVOKED/USERPAYING...）
    params = {
        "appid": _effective_appid(),
        "mch_id": settings.payment_mch_id,
        "nonce_str": nonce_str(),
    }
    if transaction_id:
        params["transaction_id"] = transaction_id
    elif out_trade_no:
        params["out_trade_no"] = out_trade_no
    else:
        raise V2PaymentError("orderquery 必须提供 out_trade_no 或 transaction_id", code=400)
    data = await _signed_sandbox_post(ORDERQUERY_URL, params, "orderquery")
    return {
        "out_trade_no": data.get("out_trade_no", out_trade_no),
        "transaction_id": data.get("transaction_id", ""),
        "trade_state": data.get("trade_state", ""),
        "trade_state_desc": data.get("trade_state_desc", ""),
        "total_fee": int(data.get("total_fee", "0") or 0),
        "raw": data,
    }


async def close_order(*, out_trade_no: str) -> dict:
    # 关闭订单：对未支付订单调用，释放微信侧预支付单（本地库存仍由 core.payment 归还）
    params = {
        "appid": _effective_appid(),
        "mch_id": settings.payment_mch_id,
        "out_trade_no": out_trade_no,
        "nonce_str": nonce_str(),
    }
    return await _signed_sandbox_post(CLOSEORDER_URL, params, "closeorder")


def verify_v2_notify(data: dict, *, sandbox_key: str | None = None) -> bool:
    """校验微信支付结果通知（XML 解析后的 dict）的 V2 MD5 签名。"""
    sign = str(data.get("sign", ""))
    if not sign:
        return False
    key = sandbox_key or sandbox_key_cache.get_cached()
    if not key:
        return False
    return sign_md5(data, key) == sign.upper()


async def _selfcheck() -> None:
    # 自检：仅验证能否用真实商户号/APIv2 密钥换到沙箱密钥，不下单、不扣款
    try:
        key = await get_sandbox_sign_key()
    except V2PaymentError as exc:
        print(f"[FAIL] {exc.message}")
        raise SystemExit(1)
    print(f"[OK] getsignkey 成功，沙箱密钥 sandbox_signkey={key}（mch_id={settings.payment_mch_id}）")


if __name__ == "__main__":
    import asyncio

    asyncio.run(_selfcheck())
