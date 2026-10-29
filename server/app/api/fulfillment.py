# 订单履约 API：支付成功后的发货、确认收货、退款业务流转
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import fulfillment
from ..db import get_db
from ..models import Order, User
from ..schemas import (
    FulfillmentResultOut,
    RefundRequest,
    ShipRequest,
    ShippingCompanyOut,
)
from .deps import get_current_staff, get_current_user


router = APIRouter(tags=["fulfillment"])


def _result(order: Order) -> FulfillmentResultOut:
    return FulfillmentResultOut(
        order_id=order.order_id,
        status=order.status,
        ship_company=order.ship_company or "",
        ship_company_name=order.ship_company_name or "",
        logistics_code=order.logistics_code or "",
        shipped_at=order.shipped_at,
        received_at=order.received_at,
        refund_no=order.refund_no or "",
        refunded_at=order.refunded_at,
    )


@router.get("/shipping/companies", response_model=list[ShippingCompanyOut])
async def list_shipping_companies() -> list[ShippingCompanyOut]:
    # 物流公司字典：供管理端发货下拉选择
    return [ShippingCompanyOut(code=code, name=name) for code, name in fulfillment.SHIPPING_COMPANIES.items()]


@router.post("/admin/orders/{order_id}/ship", response_model=FulfillmentResultOut)
async def admin_ship_order(
    order_id: str,
    payload: ShipRequest,
    db: AsyncSession = Depends(get_db),
    staff: User = Depends(get_current_staff),
) -> FulfillmentResultOut:
    # 商家发货：待发货(paid) -> 待收货(shipped)，写入物流公司与单号
    order = await fulfillment.get_order_or_404(db, order_id)
    try:
        order = await fulfillment.ship_order(db, order, payload.company_code, payload.logistics_code)
    except fulfillment.FulfillmentError as exc:
        raise HTTPException(status_code=exc.code, detail=exc.message) from None
    return _result(order)


@router.post("/admin/orders/{order_id}/refund", response_model=FulfillmentResultOut)
async def admin_refund_order(
    order_id: str,
    payload: RefundRequest | None = None,
    db: AsyncSession = Depends(get_db),
    staff: User = Depends(get_current_staff),
) -> FulfillmentResultOut:
    # 后台退款：paid/shipped -> refunded，沙箱直接成功并回补预占库存
    order = await fulfillment.get_order_or_404(db, order_id)
    try:
        order, _refund_no = await fulfillment.refund_paid_order(db, order)
    except fulfillment.FulfillmentError as exc:
        raise HTTPException(status_code=exc.code, detail=exc.message) from None
    return _result(order)


@router.post("/orders/{order_id}/receive", response_model=FulfillmentResultOut)
async def confirm_receive(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FulfillmentResultOut:
    # 买家确认收货：shipped -> completed。只能确认自己的订单。
    order = await fulfillment.get_order_or_404(db, order_id)
    if order.user_id is not None and order.user_id != user.id:
        raise HTTPException(status_code=404, detail="订单不存在")
    try:
        order = await fulfillment.confirm_receipt(db, order)
    except fulfillment.FulfillmentError as exc:
        raise HTTPException(status_code=exc.code, detail=exc.message) from None
    return _result(order)
