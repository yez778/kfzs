# 微信支付 V2 协议网关（本地实现）：官方 sandboxnew 环境已于 2021 年后下线（接口返回 404），
# 本路由用**官方公开测试商户号/AppID** + **与官方完全一致的 XML/MD5 报文协议**提供
# getsignkey / unifiedorder / orderquery / closeorder，供后端 V2 链路与小程序收银台联调演示。
#
# 协议要点（与官方 V2 文档一致）：
#   - 请求/响应均为 XML（<xml><key>value</key>...</xml>）
#   - 签名：参数按 key 字典序拼 k=v&...&key=API密钥，MD5 后大写
#   - getsignkey 用 APIv2 密钥签名；其余接口用沙箱密钥签名
#   - 业务失败返回 return_code=SUCCESS + result_code=FAIL + err_code
#
# 安全说明：生产接入真实商户请把 PAYMENT_SANDBOX_BASE 指回官方地址（或自行实现代理）。
from __future__ import annotations

import hashlib
import threading
import uuid

from fastapi import APIRouter, Request, Response

from ..config import settings

router = APIRouter(prefix="/sandbox/v2", tags=["sandbox-v2-gateway"])

RETURN_SUCCESS = "SUCCESS"
RETURN_FAIL = "FAIL"
RESULT_SUCCESS = "SUCCESS"
RESULT_FAIL = "FAIL"

_lock = threading.Lock()
# out_trade_no -> 订单记录（进程内，重启清空；仅用于本地联调）
_ORDERS: dict[str, dict] = {}


# ---------------------------- XML / 签名工具 ----------------------------


def _xml_escape(value: object) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def to_xml(data: dict) -> str:
    body = "".join(f"<{k}>{_xml_escape(v)}</{k}>" for k, v in data.items() if v is not None)
    return f"<xml>{body}</xml>"


def from_xml(raw: str) -> dict:
    """解析官方 V2 XML（一层 <xml><k>v</k></xml>，支持 CDATA），正则实现避免 XXE。"""
    import html as _html
    import re

    pairs = re.findall(
        r"<([A-Za-z0-9_]+)>\s*(?:<!\[CDATA\[(.*?)\]\]>|([^<]*?))\s*</\1>",
        raw or "",
        flags=re.DOTALL,
    )
    fields: dict[str, str] = {}
    for key, cdata, plain in pairs:
        # 根节点 <xml> 的内容含尖括号，正则不会匹配，天然被跳过
        fields[key] = cdata if cdata else _html.unescape((plain or "").strip())
    return fields


def sign_md5(params: dict, key: str) -> str:
    items = sorted(
        (k, v) for k, v in params.items() if k != "sign" and v is not None and str(v) != ""
    )
    raw = "&".join(f"{k}={v}" for k, v in items) + f"&key={key}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()


def verify(params: dict, key: str) -> bool:
    return bool(params.get("sign")) and sign_md5(params, key) == params["sign"].upper()


def sandbox_key() -> str:
    """沙箱密钥：由 APIv2 密钥 + 商户号派生，保证同一商户重复获取结果一致。"""
    seed = f"{settings.payment_mch_id}:{settings.payment_api_v2_key}:sandbox"
    return hashlib.md5(seed.encode("utf-8")).hexdigest()


def _api_v2_key() -> str:
    return (settings.payment_api_v2_key or "").strip() or settings.payment_mch_key


def _fail(return_msg: str = "", err_code: str = "", err_code_des: str = "") -> Response:
    data = {"return_code": RETURN_FAIL, "return_msg": return_msg or "FAIL"}
    if err_code:
        data.update(
            {
                "return_code": RETURN_SUCCESS,
                "result_code": RESULT_FAIL,
                "err_code": err_code,
                "err_code_des": err_code_des or err_code,
            }
        )
    return Response(content=to_xml(data), media_type="application/xml; charset=utf-8")


def _ok(data: dict) -> Response:
    payload = {"return_code": RETURN_SUCCESS, "return_msg": "OK", **data}
    return Response(content=to_xml(payload), media_type="application/xml; charset=utf-8")


# ---------------------------- 官方 V2 四个接口 ----------------------------


@router.post("/pay/getsignkey")
async def getsignkey(request: Request) -> Response:
    """用 APIv2 密钥签名换取沙箱密钥（官方协议的引导步骤）"""
    body = from_xml((await request.body()).decode("utf-8", "ignore"))
    if not verify(body, _api_v2_key()):
        return _fail("签名错误", "SIGNERROR", "APIv2 密钥签名校验失败")
    if body.get("mch_id") != settings.payment_mch_id:
        return _fail("商户号不匹配", "MCHID_MISMATCH", "mch_id 与本地配置不一致")
    return _ok({"mch_id": settings.payment_mch_id, "sandbox_signkey": sandbox_key()})


@router.post("/pay/unifiedorder")
async def unifiedorder(request: Request) -> Response:
    """统一下单（JSAPI）：用沙箱密钥验签，返回 prepay_id"""
    body = from_xml((await request.body()).decode("utf-8", "ignore"))
    if not verify(body, sandbox_key()):
        return _fail("签名错误", "SIGNERROR", "沙箱密钥签名校验失败")
    if body.get("trade_type") != "JSAPI":
        return _fail("", "PARAM_ERROR", "本网关仅支持 JSAPI")
    openid = body.get("openid") or ""
    if not openid:
        return _fail("", "PARAM_ERROR", "JSAPI 必须传 openid")
    try:
        total_fee = int(body.get("total_fee") or 0)
    except ValueError:
        return _fail("", "PARAM_ERROR", "total_fee 非法")
    if total_fee <= 0:
        return _fail("", "PARAM_ERROR", "total_fee 必须大于 0")

    out_trade_no = body.get("out_trade_no") or ""
    if not out_trade_no:
        return _fail("", "PARAM_ERROR", "out_trade_no 不能为空")

    with _lock:
        existed = _ORDERS.get(out_trade_no)
        if existed and existed["trade_state"] == "SUCCESS":
            return _fail("", "ORDERPAID", "订单已支付")
        prepay_id = (existed or {}).get("prepay_id") or f"wx{hashlib.md5(out_trade_no.encode()).hexdigest()[:28]}"
        _ORDERS[out_trade_no] = {
            "out_trade_no": out_trade_no,
            "prepay_id": prepay_id,
            "total_fee": total_fee,
            "openid": openid,
            "trade_state": (existed or {}).get("trade_state", "NOTPAY"),
            "transaction_id": (existed or {}).get("transaction_id", ""),
            "body": body.get("body", ""),
        }
    return _ok(
        {
            "appid": body.get("appid", ""),
            "mch_id": settings.payment_mch_id,
            "nonce_str": uuid.uuid4().hex[:32],
            "prepay_id": prepay_id,
            "trade_type": "JSAPI",
            "result_code": RESULT_SUCCESS,
        }
    )


@router.post("/pay/orderquery")
async def orderquery(request: Request) -> Response:
    """查询订单：返回 trade_state（SUCCESS/NOTPAY/CLOSED）"""
    body = from_xml((await request.body()).decode("utf-8", "ignore"))
    if not verify(body, sandbox_key()):
        return _fail("签名错误", "SIGNERROR", "沙箱密钥签名校验失败")
    out_trade_no = body.get("out_trade_no") or ""
    with _lock:
        record = _ORDERS.get(out_trade_no)
        if not record:
            return _fail("", "ORDERNOTEXIST", "订单不存在")
        snapshot = dict(record)
    data = {
        "appid": body.get("appid", ""),
        "mch_id": settings.payment_mch_id,
        "nonce_str": uuid.uuid4().hex[:32],
        "out_trade_no": snapshot["out_trade_no"],
        "total_fee": snapshot["total_fee"],
        "trade_state": snapshot["trade_state"],
        "result_code": RESULT_SUCCESS,
        "openid": snapshot["openid"],
    }
    if snapshot["trade_state"] == "SUCCESS":
        data["transaction_id"] = snapshot["transaction_id"]
        data["time_end"] = snapshot.get("time_end", "")
    return _ok(data)


@router.post("/pay/closeorder")
async def closeorder(request: Request) -> Response:
    """关闭订单"""
    body = from_xml((await request.body()).decode("utf-8", "ignore"))
    if not verify(body, sandbox_key()):
        return _fail("签名错误", "SIGNERROR", "沙箱密钥签名校验失败")
    out_trade_no = body.get("out_trade_no") or ""
    with _lock:
        record = _ORDERS.get(out_trade_no)
        if not record:
            return _fail("", "ORDERNOTEXIST", "订单不存在")
        if record["trade_state"] == "SUCCESS":
            return _fail("", "ORDERPAID", "订单已支付，无法关闭")
        record["trade_state"] = "CLOSED"
    return _ok({"out_trade_no": out_trade_no, "result_code": RESULT_SUCCESS})


# ---------------------------- 本地网关专用：模拟沙箱用户付款 ----------------------------


@router.post("/pay/mockpay")
async def mockpay(request: Request) -> Response:
    """本地网关专用：模拟用户在沙箱收银台完成付款（官方沙箱已下线，无官方触发入口）。

    与真实 V2 一致：付款后订单 trade_state=SUCCESS，业务侧仍需通过 orderquery 同步状态。
    """
    body = from_xml((await request.body()).decode("utf-8", "ignore"))
    if not verify(body, sandbox_key()):
        return _fail("签名错误", "SIGNERROR", "沙箱密钥签名校验失败")
    out_trade_no = body.get("out_trade_no") or ""
    import datetime

    with _lock:
        record = _ORDERS.get(out_trade_no)
        if not record:
            return _fail("", "ORDERNOTEXIST", "订单不存在")
        if record["trade_state"] == "CLOSED":
            return _fail("", "ORDERCLOSED", "订单已关闭")
        record["trade_state"] = "SUCCESS"
        if not record["transaction_id"]:
            record["transaction_id"] = "42000" + uuid.uuid4().hex[:19].upper()
        record["time_end"] = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        snapshot = dict(record)
    return _ok(
        {
            "out_trade_no": out_trade_no,
            "trade_state": snapshot["trade_state"],
            "transaction_id": snapshot["transaction_id"],
            "result_code": RESULT_SUCCESS,
        }
    )


@router.get("/orders")
async def list_local_orders() -> dict:
    """调试：查看本地网关内存中的订单（联调用，不含敏感信息）"""
    with _lock:
        return {
            "count": len(_ORDERS),
            "orders": [
                {
                    "out_trade_no": o["out_trade_no"],
                    "trade_state": o["trade_state"],
                    "total_fee": o["total_fee"],
                    "transaction_id": o["transaction_id"],
                }
                for o in _ORDERS.values()
            ],
        }
