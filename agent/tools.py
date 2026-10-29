# 工具层：AI 客服可调用的业务工具（当前支持查订单/物流）。
# 通过 server 的 /internal/orders/{order_id} 接口取真实数据，需配置 SERVER_API_BASE + SERVICE_TOKEN。
import os
import re

ORDER_PATTERN = re.compile(
    r"\b(\d{4}\.\d{1,2}\.\d{1,2}\.\d{1,2}\.\d{1,2}\.\d{1,2}|\d{4,10})\b"
)
STATUS_TEXT = {
    "unpaid": "待支付",
    "paid": "待发货",
    "refunded": "已退款",
    "cancelled": "已取消",
    "completed": "已完成",
    "shipped": "待收货",
    "refunding": "退款中",
}


def extract_order_id(text: str) -> str:
    """从用户消息里提取订单号（形如 2026.10.29.16.9.48）"""
    match = ORDER_PATTERN.search(text or "")
    return match.group(1) if match else ""


def _server_config() -> tuple[str, str]:
    base = (os.getenv("SERVER_API_BASE") or "http://127.0.0.1:8000/api/v1").rstrip("/")
    token = (os.getenv("SERVICE_TOKEN") or "").strip()
    return base, token


def query_order(order_id: str) -> dict | None:
    """查询订单详情；未配置 SERVICE_TOKEN 或查询失败时返回 None（降级为普通问答）"""
    if not order_id:
        return None
    base, token = _server_config()
    if not token:
        return None
    try:
        import httpx

        resp = httpx.get(
            f"{base}/internal/orders/{order_id}",
            headers={"X-Service-Token": token},
            timeout=8.0,
        )
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None


def describe_order(info: dict) -> str:
    """把订单数据转成客服话术"""
    status = STATUS_TEXT.get(str(info.get("status") or ""), str(info.get("status") or "未知"))
    lines = [
        f"已为您查到订单 {info.get('order_id')}：",
        f"· 商品：{info.get('product')}",
        f"· 金额：¥{float(info.get('amount') or 0):.2f}",
        f"· 状态：{status}",
    ]
    if info.get("logistics_code"):
        company = info.get("ship_company_name") or info.get("ship_company") or "物流"
        lines.append(f"· 物流：{company} {info['logistics_code']}")
        if info.get("shipped_at"):
            lines.append(f"· 发货时间：{info['shipped_at'][:19].replace('T', ' ')}")
    if info.get("refund_no"):
        lines.append(f"· 退款单号：{info['refund_no']}（1-3 个工作日原路退回）")
    if info.get("status") == "unpaid":
        lines.append("· 提示：订单还未支付，可在「订单」页点「去支付」继续付款。")
    elif info.get("status") == "shipped":
        lines.append("· 提示：已为您安排发货，收到货后可在订单页点「确认收货」。")
    return "\n".join(lines)


def try_answer_with_tools(message: str) -> str:
    """订单/物流类问题优先走工具，命中真实订单则直接返回答案；否则返回空串"""
    order_id = extract_order_id(message)
    if not order_id:
        return ""
    info = query_order(order_id)
    if not info:
        return ""
    return describe_order(info)


def tools_status() -> dict:
    """健康检查用：工具是否可用"""
    base, token = _server_config()
    return {
        "order_query": bool(token),
        "server_api_base": base,
        "service_token_configured": bool(token),
    }
