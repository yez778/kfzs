# 订单履约核心：支付成功后的真实电商业务流转。
#
# 订单状态机（与小程序/抖店常见状态对齐）：
#   unpaid 待支付
#     └─支付成功─▶ paid 待发货（库存已预占）
#                   ├─商家发货─▶ shipped 待收货（记录物流单号/发货时间）
#                   │             └─买家确认收货─▶ completed 已完成
#                   └─售后退款─▶ refunded 已退款（回补库存）
#     └─关单/超时─▶ cancelled 已取消（回补库存，由 payment 模块处理）
#
# 所有状态迁移都做前置校验，非法流转抛 FulfillmentError，保证不会重复发货/重复退款。
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Order, PaymentOrder
from .payment import _release_stock_for_order


class FulfillmentError(Exception):
    """履约业务错误：code 为建议 HTTP 状态码，message 为可展示信息。"""

    def __init__(self, message: str, code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# 支持的物流公司：编码对齐常见快递，名称用于展示
SHIPPING_COMPANIES = {
    "SF": "顺丰速运",
    "YTO": "圆通速递",
    "ZTO": "中通快递",
    "STO": "申通快递",
    "YD": "韵达快递",
    "JD": "京东物流",
    "EMS": "EMS",
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def generate_refund_no() -> str:
    # 退款单号：退款业务前缀 + 日期 + 随机串（纯数字字母）
    return "RFD" + now_utc().strftime("%Y%m%d%H%M%S") + secrets.token_hex(4)


def normalize_company(company_code: str) -> tuple[str, str]:
    code = (company_code or "SF").strip().upper()
    name = SHIPPING_COMPANIES.get(code)
    if name is None:
        raise FulfillmentError(
            f"不支持的物流公司：{company_code}（可选 {', '.join(SHIPPING_COMPANIES)}）",
            code=422,
        )
    return code, name


async def get_order_or_404(session: AsyncSession, order_id: str) -> Order:
    order = await session.scalar(select(Order).where(Order.order_id == order_id))
    if order is None:
        raise FulfillmentError("订单不存在", code=404)
    return order


async def ship_order(
    session: AsyncSession,
    order: Order,
    company_code: str,
    logistics_code: str,
) -> Order:
    # 商家发货：仅 paid（待发货）订单可发货；幂等：已用同一物流单发货则直接返回
    tracking = (logistics_code or "").strip()
    if not tracking:
        raise FulfillmentError("物流单号不能为空", code=422)
    code, name = normalize_company(company_code)

    if order.status == "shipped":
        if order.logistics_code == tracking:
            return order  # 幂等：重复提交同一发货结果
        raise FulfillmentError("订单已发货，不能重复填写物流单号", code=409)
    if order.status != "paid":
        raise FulfillmentError(f"订单当前状态为 {order.status}，无法发货", code=409)

    order.status = "shipped"
    order.ship_company = code
    order.ship_company_name = name
    order.logistics_code = tracking
    order.shipped_at = now_utc()
    await session.commit()
    await session.refresh(order)
    return order


async def confirm_receipt(session: AsyncSession, order: Order) -> Order:
    # 买家确认收货：仅 shipped 可确认；幂等：已完成直接返回
    if order.status == "completed":
        return order
    if order.status != "shipped":
        raise FulfillmentError(f"订单当前状态为 {order.status}，无法确认收货", code=409)
    order.status = "completed"
    order.received_at = now_utc()
    await session.commit()
    await session.refresh(order)
    return order


async def refund_paid_order(session: AsyncSession, order: Order) -> tuple[Order, str]:
    # 售后退款（已支付未完成）：paid/shipped 可退，completed 默认走退货流程不在此处理。
    # 退款后置 refunded 并回补库存；幂等：已退款直接返回原退款单号。
    if order.status == "refunded":
        return order, order.refund_no or ""
    if order.status not in ("paid", "shipped"):
        raise FulfillmentError(f"订单当前状态为 {order.status}，无法退款", code=409)

    payment = await session.scalar(
        select(PaymentOrder)
        .where(PaymentOrder.order_id == order.order_id)
        .order_by(PaymentOrder.id.desc())
    )
    if payment is None or payment.trade_state != "SUCCESS":
        raise FulfillmentError("订单未找到成功支付记录，无法退款", code=409)

    refund_no = generate_refund_no()
    order.status = "refunded"
    order.refund_no = refund_no
    order.refunded_at = now_utc()
    # 真实微信退款会调用 secapi_pay/refund；沙箱直接标记成功并回补预占库存
    await _release_stock_for_order(session, order.id)
    await session.commit()
    await session.refresh(order)
    return order, refund_no
