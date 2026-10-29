# 内部服务接口：供 agent（AI 客服）等内部服务查询业务数据，使用共享 SERVICE_TOKEN 鉴权。
# 不对外暴露：未配置 SERVICE_TOKEN 时一律拒绝，避免订单信息被匿名读取。
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..models import Order, OrderItem


router = APIRouter(prefix="/internal", tags=["internal"])


def _verify_service_token(x_service_token: str | None) -> None:
    expected = (settings.service_token or "").strip()
    if not expected:
        raise HTTPException(status_code=403, detail="内部接口未启用（未配置 SERVICE_TOKEN）")
    if (x_service_token or "").strip() != expected:
        raise HTTPException(status_code=401, detail="服务令牌无效")


@router.get("/orders/{order_id}")
async def internal_get_order(
    order_id: str,
    x_service_token: str | None = Header(default=None, alias="X-Service-Token"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # 供 AI 客服查询订单状态与物流信息（只读，仅返回必要字段）
    _verify_service_token(x_service_token)
    order = await db.scalar(select(Order).where(Order.order_id == order_id))
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    items = (
        await db.scalars(
            select(OrderItem).where(OrderItem.order_db_id == order.id).order_by(OrderItem.id)
        )
    ).all()
    return {
        "order_id": order.order_id,
        "customer": order.customer,
        "product": order.product,
        "amount": float(order.amount or 0),
        "status": order.status,
        "pay_method": order.pay_method or "",
        "ship_company": order.ship_company or "",
        "ship_company_name": order.ship_company_name or "",
        "logistics_code": order.logistics_code or "",
        "shipped_at": order.shipped_at.isoformat() if order.shipped_at else None,
        "received_at": order.received_at.isoformat() if order.received_at else None,
        "refund_no": order.refund_no or "",
        "refunded_at": order.refunded_at.isoformat() if order.refunded_at else None,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "items": [
            {
                "title": it.title,
                "price": float(it.price or 0),
                "quantity": it.quantity,
                "sku_id": it.sku_id,
            }
            for it in items
        ],
    }
