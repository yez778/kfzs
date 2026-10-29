# 微信支付（沙箱）核心：模拟 JSAPI 统一下单 / 支付结果 / 异步回调的完整生命周期。
#
# 设计上与真实微信支付 v3 的关键概念一一对应，方便将来只替换“网关调用”而不改业务：
#   out_trade_no  商户订单号（纯数字字母，区别于给用户展示的 2024.12.3.x.x.x 订单号）
#   prepay_id     统一下单返回的预支付单
#   JSAPI 参数     wx.requestPayment 所需的 timeStamp/nonceStr/package/paySign
#   transaction_id 微信支付订单号
#   异步回调       支付成功后微信服务器回调 /payments/notify/wechat
#
# 沙箱不真正扣款：收银台调用 /payments/sandbox/complete 模拟用户输密码完成支付，
# 也可由外部用 HMAC 签名回调 /payments/notify/wechat 模拟微信服务器通知。
# 支付成功与异步回调共用同一个幂等履约函数 fulfill_payment_success。
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Order, OrderItem, PaymentOrder, ProductInventory

PAY_METHOD = "wxpay_sandbox"


class PaymentError(Exception):
    """支付业务错误：code 为建议的 HTTP 状态码，message 为可展示信息。"""

    def __init__(self, message: str, code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def now_utc() -> datetime:
    # 全库时间统一为“去时区的 UTC naive”，与 models._utcnow 保持一致
    return datetime.now(timezone.utc).replace(tzinfo=None)


def yuan_to_fen(amount: Decimal | float | int | str) -> int:
    # 微信金额单位是分；Decimal 量化后取整，避免浮点误差
    value = Decimal(str(amount)).quantize(Decimal("0.01"))
    return int(value * 100)


def generate_out_trade_no() -> str:
    # 20 位订单号：时间戳 + 随机串，仅含数字字母，符合微信 out_trade_no 规范
    return time.strftime("%Y%m%d%H%M%S", time.localtime()) + secrets.token_hex(3)


def generate_transaction_id() -> str:
    # 模拟微信支付订单号：4200 开头（微信交易号常见前缀）
    return "4200" + time.strftime("%Y%m%d%H%M%S", time.localtime()) + secrets.token_hex(6)


def _hmac_sha256(message: str) -> str:
    key = settings.payment_mch_key.encode("utf-8")
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).hexdigest()


def build_jsapi_pay_params(payment: PaymentOrder) -> dict:
    # 构造 wx.requestPayment 所需参数。真实微信 paySign 是商户私钥 RSA-SHA256；
    # 沙箱改用商户密钥 HMAC-SHA256，签名串结构与微信文档保持一致。
    appid = settings.payment_appid or settings.wechat_appid
    time_stamp = str(int(time.time()))
    nonce_str = secrets.token_hex(16)
    package = f"prepay_id={payment.prepay_id}"
    sign_str = f"{appid}\n{time_stamp}\n{nonce_str}\n{package}\n"
    pay_sign = _hmac_sha256(sign_str).upper()
    return {
        "sandbox": True,
        "timeStamp": time_stamp,
        "nonceStr": nonce_str,
        "package": package,
        "signType": "HMAC-SHA256",
        "paySign": pay_sign,
        "appId": appid,
        "mchId": settings.payment_mch_id,
        "outTradeNo": payment.out_trade_no,
        "description": payment.description,
        "amountFen": payment.amount_fen,
    }


def build_notify_sign(out_trade_no: str, transaction_id: str, amount_fen: int, success: bool) -> str:
    # 沙箱回调签名：HMAC-SHA256(商户密钥, 关键字段拼接)。真实微信为平台证书 + AES-GCM 报文。
    message = f"{out_trade_no}:{transaction_id}:{amount_fen}:{'SUCCESS' if success else 'FAIL'}"
    return _hmac_sha256(message)


def verify_notify_sign(
    out_trade_no: str,
    transaction_id: str,
    amount_fen: int,
    success: bool,
    signature: str,
) -> bool:
    expected = build_notify_sign(out_trade_no, transaction_id, amount_fen, success)
    return hmac.compare_digest(expected, str(signature or ""))


async def reserve_stock(session: AsyncSession, sku_quantities: dict[str, int]) -> None:
    # 下单时原子预占库存：UPDATE ... WHERE stock >= qty，靠数据库行条件杜绝超卖。
    # 支付成功不再扣库存（预占即占用）；关单/超时会把预占量归还。
    for sku_id, quantity in sku_quantities.items():
        result = await session.execute(
            update(ProductInventory)
            .where(ProductInventory.sku_id == sku_id, ProductInventory.stock >= quantity)
            .values(stock=ProductInventory.stock - quantity)
        )
        if (result.rowcount or 0) == 0:
            inv = await session.scalar(
                select(ProductInventory).where(ProductInventory.sku_id == sku_id)
            )
            remain = inv.stock if inv else 0
            raise PaymentError(f"商品库存不足（剩余 {remain}，需要 {quantity}）", code=409)


async def _release_stock_for_order(session: AsyncSession, order_db_id: int) -> None:
    # 关单/超时：按订单明细把预占库存归还（同一 SKU 多行先合并数量）
    rows = (
        await session.scalars(
            select(OrderItem).where(OrderItem.order_db_id == order_db_id)
        )
    ).all()
    grouped: dict[str, int] = {}
    for row in rows:
        grouped[row.sku_id] = grouped.get(row.sku_id, 0) + row.quantity
    for sku_id, quantity in grouped.items():
        await session.execute(
            update(ProductInventory)
            .where(ProductInventory.sku_id == sku_id)
            .values(stock=ProductInventory.stock + quantity)
        )


async def expire_payment_if_needed(session: AsyncSession, payment: PaymentOrder) -> bool:
    # 懒过期：未支付且已超过 expires_at，则关单并归还库存。返回支付单是否仍有效。
    if payment.trade_state != "NOTPAY":
        return True
    if now_utc() < payment.expires_at.replace(tzinfo=None):
        return True
    order = await session.scalar(select(Order).where(Order.order_id == payment.order_id))
    if order is not None and order.status == "unpaid":
        order.status = "cancelled"
        payment.trade_state = "CLOSED"
        await _release_stock_for_order(session, order.id)
        await session.commit()
    return False


async def fulfill_payment_success(
    session: AsyncSession,
    payment: PaymentOrder,
    transaction_id: str | None = None,
) -> Order:
    # 支付成功的统一履约入口（沙箱收银台与异步回调共用），必须幂等。
    if payment.trade_state == "SUCCESS":
        order = await session.scalar(select(Order).where(Order.order_id == payment.order_id))
        if order is None:
            raise PaymentError("订单不存在", code=404)
        return order

    if not await expire_payment_if_needed(session, payment):
        raise PaymentError("订单已超时关闭，请重新下单", code=400)

    order = await session.scalar(select(Order).where(Order.order_id == payment.order_id))
    if order is None:
        raise PaymentError("订单不存在", code=404)
    if order.status != "unpaid":
        raise PaymentError(f"订单当前状态为 {order.status}，无法支付", code=409)

    txn_id = (transaction_id or payment.transaction_id or generate_transaction_id())
    payment.trade_state = "SUCCESS"
    payment.transaction_id = txn_id
    payment.payer_result = "SUCCESS"
    payment.paid_at = now_utc()

    order.status = "paid"
    order.pay_method = PAY_METHOD
    await session.commit()
    await session.refresh(order)
    await session.refresh(payment)
    return order


async def close_unpaid_order(session: AsyncSession, order: Order) -> PaymentOrder | None:
    # 顾客主动取消待支付订单：关支付单 + 订单置 cancelled + 归还预占库存
    payment = await session.scalar(
        select(PaymentOrder)
        .where(PaymentOrder.order_id == order.order_id)
        .order_by(PaymentOrder.id.desc())
    )
    if payment is not None and payment.trade_state == "SUCCESS":
        raise PaymentError("订单已支付，无法取消", code=409)
    if payment is not None:
        payment.trade_state = "CLOSED"
    order.status = "cancelled"
    await _release_stock_for_order(session, order.id)
    await session.commit()
    return payment


async def sweep_expired_payments() -> int:
    # 定时任务：关闭所有超时未支付订单并归还库存。返回关闭数量。
    from ..db import async_session_factory

    closed = 0
    async with async_session_factory() as session:
        expired = (
            await session.scalars(
                select(PaymentOrder)
                .where(
                    PaymentOrder.trade_state == "NOTPAY",
                    PaymentOrder.expires_at <= now_utc(),
                )
                .order_by(PaymentOrder.id.asc())
            )
        ).all()
        for payment in expired:
            order = await session.scalar(select(Order).where(Order.order_id == payment.order_id))
            if order is not None and order.status == "unpaid":
                payment.trade_state = "CLOSED"
                order.status = "cancelled"
                await _release_stock_for_order(session, order.id)
                closed += 1
        if closed:
            await session.commit()
    return closed


def payment_expires_at() -> datetime:
    return now_utc() + timedelta(minutes=settings.payment_order_expire_minutes)
