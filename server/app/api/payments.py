# 微信支付（沙箱）API：统一下单、沙箱收银台完成支付、订单查询、关单与异步回调。
#
# 与真实微信支付的接口对应关系：
#   POST /payments/prepay            ← 商户后端「统一下单 v3」，返回 wx.requestPayment 参数
#   POST /payments/sandbox/complete  ← 沙箱专用：模拟用户在微信收银台输密码后的结果
#   POST /payments/notify/wechat     ← 微信服务器「支付结果通知」（HMAC 签名，生产替换为 v3 验密）
#   GET  /payments/by-order/{id}     ← 商户后端「查询订单」
#   POST /payments/by-order/{id}/close ← 商户后端「关闭订单」
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..core import payment_v2
from ..core.payment import (
    build_jsapi_pay_params,
    close_unpaid_order,
    expire_payment_if_needed,
    fulfill_payment_success,
    verify_notify_sign,
)
from ..db import get_db
from ..models import Order, PaymentOrder, User
from ..schemas import (
    NotifyRequest,
    PaymentStatusOut,
    PrepayRequest,
    SandboxCompleteRequest,
)
from .deps import get_current_user

_V2_XML_OK = "<xml><return_code><![CDATA[SUCCESS]]></return_code></xml>"
_V2_XML_FAIL = (
    "<xml><return_code><![CDATA[FAIL]]></return_code>"
    "<return_msg><![CDATA[{msg}]]></return_msg></xml>"
)

router = APIRouter(prefix="/payments", tags=["payments"])

_ORDER_STATUS = {
    "SUCCESS": "paid",
    "CLOSED": "cancelled",
    "NOTPAY": "unpaid",
    "USERPAYING": "unpaid",
    "PAYERROR": "unpaid",
}


async def _load_payment(
    db: AsyncSession, *, out_trade_no: str = "", order_id: str = ""
) -> PaymentOrder:
    stmt = select(PaymentOrder)
    if out_trade_no:
        stmt = stmt.where(PaymentOrder.out_trade_no == out_trade_no)
    elif order_id:
        stmt = stmt.where(PaymentOrder.order_id == order_id).order_by(PaymentOrder.id.desc())
    else:
        raise HTTPException(status_code=400, detail="缺少订单号")
    payment = (await db.scalars(stmt)).first()
    if payment is None:
        raise HTTPException(status_code=404, detail="支付单不存在")
    return payment


def _status_out(payment: PaymentOrder, order: Order | None, include_params: bool = False) -> PaymentStatusOut:
    status = (order.status if order else _ORDER_STATUS.get(payment.trade_state, "unpaid")) or "unpaid"
    return PaymentStatusOut(
        out_trade_no=payment.out_trade_no,
        order_id=payment.order_id,
        trade_state=payment.trade_state,
        status=status,
        amount_fen=payment.amount_fen,
        amount=payment.amount_fen / 100,
        transaction_id=payment.transaction_id,
        paid_at=payment.paid_at,
        expires_at=payment.expires_at,
        pay_params=build_jsapi_pay_params(payment) if include_params else None,
        payer_result=payment.payer_result,
        fail_reason=payment.fail_reason,
    )


@router.post("/prepay", response_model=PaymentStatusOut)
async def prepay(
    payload: PrepayRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaymentStatusOut:
    # 统一下单：拿到待支付订单后，生成/刷新 wx.requestPayment 所需 JSAPI 参数
    payment = await _load_payment(db, out_trade_no=payload.out_trade_no, order_id=payload.order_id)
    order = await db.scalar(select(Order).where(Order.order_id == payment.order_id))
    if order is None or order.user_id != user.id:
        raise HTTPException(status_code=404, detail="订单不存在")

    if payment.trade_state == "SUCCESS":
        return _status_out(payment, order)

    if not await expire_payment_if_needed(db, payment):
        raise HTTPException(status_code=400, detail="订单已超时关闭，请重新下单")
    await db.refresh(payment)

    # 官方 V2 仿真：重新请求统一下单拿到沙箱 prepay_id 与 MD5 调起参数
    if settings.payment_is_v2_sandbox:
        try:
            result = await payment_v2.unified_order_jsapi(
                out_trade_no=payment.out_trade_no,
                amount_fen=payment.amount_fen,
                description=payment.description,
                openid=payment.openid,
            )
        except payment_v2.V2PaymentError as exc:
            raise HTTPException(status_code=exc.code, detail=exc.message) from None
        payment.prepay_id = result["prepay_id"]
        await db.commit()
        out = _status_out(payment, order)
        out.pay_params = result["jsapi_params"]
        return out

    return _status_out(payment, order, include_params=True)


@router.post("/sandbox/complete", response_model=PaymentStatusOut)
async def sandbox_complete(
    payload: SandboxCompleteRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaymentStatusOut:
    # 沙箱收银台：result=SUCCESS 模拟支付成功（触发与异步回调相同的幂等履约）；
    # result=USERPAYING 模拟用户还在输密码/支付中，订单保持未支付。
    payment = await _load_payment(db, out_trade_no=payload.out_trade_no)
    order = await db.scalar(select(Order).where(Order.order_id == payment.order_id))
    if order is None or order.user_id != user.id:
        raise HTTPException(status_code=404, detail="订单不存在")

    # 官方 V2 仿真：JSAPI 没有“一键模拟付款成功”，complete 改为向微信查单并同步真实状态
    if settings.payment_is_v2_sandbox:
        try:
            query = await payment_v2.order_query(out_trade_no=payment.out_trade_no)
        except payment_v2.V2PaymentError as exc:
            raise HTTPException(status_code=exc.code, detail=exc.message) from None
        state = (query["trade_state"] or "").upper()
        if state == "SUCCESS":
            order = await fulfill_payment_success(
                db, payment, transaction_id=query["transaction_id"] or None
            )
            await db.refresh(payment)
            return _status_out(payment, order)
        # NOTPAY / USERPAYING / PAYERROR 等：原样返回当前状态，不伪造成功
        await db.refresh(payment)
        out = _status_out(payment, order)
        out.trade_state = state or payment.trade_state
        return out

    # 本地自建沙箱：result=SUCCESS 成功 / USERPAYING 支付中 / PAYERROR 支付失败（可重试）
    result = (payload.result or "SUCCESS").upper()
    if result not in ("SUCCESS", "USERPAYING", "PAYERROR"):
        raise HTTPException(status_code=400, detail="沙箱仅支持 SUCCESS / USERPAYING / PAYERROR 结果")

    if result == "USERPAYING":
        if payment.trade_state == "NOTPAY" and await expire_payment_if_needed(db, payment):
            payment.payer_result = "USERPAYING"
            payment.fail_reason = ""
            await db.commit()
            await db.refresh(payment)
        # 支付单本身仍为 NOTPAY（微信侧语义），但向收银台回显当前动作 USERPAYING
        out = _status_out(payment, order)
        out.trade_state = "USERPAYING"
        return out

    if result == "PAYERROR":
        # 支付失败（如零钱余额不足、银行卡扣款失败）：订单保持未支付，允许稍后重新发起支付
        if not await expire_payment_if_needed(db, payment):
            raise HTTPException(status_code=400, detail="订单已超时关闭，请重新下单")
        reason = (payload.fail_reason or "NOTENOUGH").strip().upper()[:64]
        payment.trade_state = "PAYERROR"
        payment.payer_result = "PAYERROR"
        payment.fail_reason = reason
        await db.commit()
        await db.refresh(payment)
        out = _status_out(payment, order)
        out.fail_reason = reason
        return out

    try:
        order = await fulfill_payment_success(db, payment)
    except Exception as exc:  # PaymentError -> 对外信息
        status = getattr(exc, "code", 400)
        raise HTTPException(status_code=status, detail=str(getattr(exc, "message", exc))) from None
    await db.refresh(payment)
    return _status_out(payment, order)


@router.get("/by-order/{order_id}", response_model=PaymentStatusOut)
async def payment_status(
    order_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaymentStatusOut:
    # 按商城订单号查询支付状态（前端轮询备用，主链路以回调/沙箱完成返回为准）
    payment = await _load_payment(db, order_id=order_id)
    order = await db.scalar(select(Order).where(Order.order_id == payment.order_id))
    if order is None or order.user_id != user.id:
        raise HTTPException(status_code=404, detail="订单不存在")
    await expire_payment_if_needed(db, payment)
    await db.refresh(payment)
    return _status_out(payment, order)


@router.post("/by-order/{order_id}/close", response_model=PaymentStatusOut)
async def payment_close(
    order_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaymentStatusOut:
    # 关闭待支付订单：归还预占库存，支付单置 CLOSED
    order = await db.scalar(select(Order).where(Order.order_id == order_id))
    if order is None or order.user_id != user.id:
        raise HTTPException(status_code=404, detail="订单不存在")
    # 官方 V2 仿真：先通知微信关单，再做本地取消/库存归还
    if settings.payment_is_v2_sandbox:
        latest = (await db.scalars(
            select(PaymentOrder)
            .where(PaymentOrder.order_id == order_id)
            .order_by(PaymentOrder.id.desc())
        )).first()
        if latest is not None and latest.trade_state == "NOTPAY":
            try:
                await payment_v2.close_order(out_trade_no=latest.out_trade_no)
            except payment_v2.V2PaymentError as exc:
                raise HTTPException(status_code=exc.code, detail=exc.message) from None
    try:
        payment = await close_unpaid_order(db, order)
    except Exception as exc:
        status = getattr(exc, "code", 400)
        raise HTTPException(status_code=status, detail=str(getattr(exc, "message", exc))) from None
    if payment is None:
        payment = await _load_payment(db, order_id=order_id)
    return _status_out(payment, order)


@router.post("/notify/wechat")
async def wechat_notify(payload: NotifyRequest, db: AsyncSession = Depends(get_db)) -> dict:
    # 微信支付结果通知（沙箱）：校验 HMAC 签名与金额后触发幂等履约。
    # 真实接入：此处改为微信支付平台证书验签 + AES-GCM 解密 resource，业务履约函数可直接复用。
    success = (payload.trade_state or "SUCCESS").upper() == "SUCCESS"
    valid = verify_notify_sign(
        payload.out_trade_no,
        payload.transaction_id,
        payload.amount_fen,
        success,
        payload.signature,
    )
    if not valid:
        raise HTTPException(status_code=401, detail="回调签名校验失败")

    payment = await _load_payment(db, out_trade_no=payload.out_trade_no)
    if payment.amount_fen != payload.amount_fen:
        raise HTTPException(status_code=400, detail="回调金额与支付单不一致")

    if success:
        try:
            await fulfill_payment_success(db, payment, transaction_id=payload.transaction_id or None)
        except Exception as exc:
            status = getattr(exc, "code", 400)
            raise HTTPException(status_code=status, detail=str(getattr(exc, "message", exc))) from None
        return {"code": "SUCCESS", "message": "成功"}

    # 支付失败/撤销：关单并归还库存
    order = await db.scalar(select(Order).where(Order.order_id == payment.order_id))
    if order is not None and order.status == "unpaid":
        await close_unpaid_order(db, order)
    return {"code": "SUCCESS", "message": "成功"}


@router.post("/notify/wechat/v2")
async def wechat_notify_v2(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    # 官方 V2 仿真支付结果通知：原始 XML 报文 + MD5 签名，返回也必须是 XML。
    # 微信要求处理成功返回 <return_code>SUCCESS</return_code>，失败返回 FAIL（会重试）。
    raw = (await request.body()).decode("utf-8", errors="ignore")
    data = payment_v2.xml_to_dict(raw)
    if not data:
        return Response(content=_V2_XML_FAIL.format(msg="empty"), media_type="application/xml")

    # 确保已拿到沙箱密钥（首次回调时可能尚未缓存）
    try:
        sandbox_key = await payment_v2.get_sandbox_sign_key()
    except payment_v2.V2PaymentError:
        sandbox_key = payment_v2.sandbox_key_cache.get_cached()
    if not payment_v2.verify_v2_notify(data, sandbox_key=sandbox_key):
        return Response(
            content=_V2_XML_FAIL.format(msg="sign verify fail"),
            media_type="application/xml",
            status_code=401,
        )

    out_trade_no = data.get("out_trade_no", "")
    try:
        payment = await _load_payment(db, out_trade_no=out_trade_no)
    except HTTPException:
        return Response(
            content=_V2_XML_FAIL.format(msg="order not exist"), media_type="application/xml"
        )

    total_fee = int(data.get("total_fee", "0") or 0)
    if total_fee and total_fee != payment.amount_fen:
        return Response(
            content=_V2_XML_FAIL.format(msg="amount mismatch"), media_type="application/xml"
        )

    is_success = data.get("result_code") == "SUCCESS" and data.get("return_code") == "SUCCESS"
    try:
        if is_success:
            await fulfill_payment_success(
                db, payment, transaction_id=data.get("transaction_id") or None
            )
        else:
            order = await db.scalar(select(Order).where(Order.order_id == payment.order_id))
            if order is not None and order.status == "unpaid":
                await close_unpaid_order(db, order)
    except Exception as exc:  # 履约异常时让微信重试
        msg = str(getattr(exc, "message", exc))[:100]
        return Response(content=_V2_XML_FAIL.format(msg=msg), media_type="application/xml")

    return Response(content=_V2_XML_OK, media_type="application/xml")
