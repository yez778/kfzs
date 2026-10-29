# 商品橱窗 API：面向前端展示的友好接口，数据来自模拟抖店商品数据
import secrets
from decimal import Decimal
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from ..config import settings
from ..core import payment_v2
from ..core.doudian_sim import find_product, list_categories, product_detail, search_products
from ..core.order_ids import build_order_id, now_china
from ..core.payment import (
    PAY_METHOD,
    build_jsapi_pay_params,
    close_unpaid_order,
    generate_out_trade_no,
    payment_expires_at,
    reserve_stock,
    yuan_to_fen,
    PaymentError,
)
from ..core.product_media import is_proxied_image_url
from ..db import async_session_factory
from ..models import Order, OrderItem, PaymentOrder, User
from ..schemas import (
    CheckoutItemOut,
    CheckoutRequest,
    CheckoutResponse,
)
from .deps import get_current_user


router = APIRouter(prefix="/shop", tags=["shop"])


@router.get("/cover-proxy")
async def cover_proxy(u: str = Query(..., min_length=8, max_length=2000)):
    # 小程序无法稳定加载淘宝 CDN（防盗链、URL 含 !!），由后端带 Referer 转发
    if not is_proxied_image_url(u):
        raise HTTPException(status_code=400, detail="不支持的图片地址")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://item.taobao.com/",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=12.0) as client:
            upstream = await client.get(u, headers=headers)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="商品图片加载失败") from exc
    if upstream.status_code in (301, 302, 303, 307, 308):
        location = upstream.headers.get("location") or ""
        if not is_proxied_image_url(location):
            raise HTTPException(status_code=502, detail="商品图片加载失败")
        try:
            async with httpx.AsyncClient(follow_redirects=False, timeout=12.0) as client:
                upstream = await client.get(location, headers=headers)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="商品图片加载失败") from exc
    if upstream.status_code >= 400 or not upstream.content:
        raise HTTPException(status_code=502, detail="商品图片加载失败")
    content_type = (upstream.headers.get("content-type") or "image/jpeg").split(";")[0].strip()
    if not content_type.startswith("image/"):
        parsed = urlparse(u)
        if parsed.path.lower().endswith(".png"):
            content_type = "image/png"
        elif parsed.path.lower().endswith(".webp"):
            content_type = "image/webp"
        else:
            content_type = "image/jpeg"
    return StreamingResponse(iter([upstream.content]), media_type=content_type)


@router.get("/categories")
async def categories() -> list[dict]:
    # 商品分类与在售数量，供橱窗筛选栏展示（浏览不需要登录）
    return list_categories()


@router.get("/products")
async def products(
    q: str | None = None,
    category: str | None = None,
    page: int = 1,
    size: int = 20,
) -> dict:
    # 商品搜索：支持关键词、分类与分页，列表项不含详情大字段
    return search_products(keyword=q or "", category=category or "", page=page, size=size)


@router.get("/products/{product_id}")
async def product(
    product_id: str,
) -> dict:
    # 商品详情：返回图集、规格参数、SKU 与售后服务
    item = find_product(product_id)
    if item is None:
        raise HTTPException(status_code=404, detail="商品不存在")
    detail = product_detail(item)
    # 用库存表（product_inventory）的真实余量覆盖静态 SKU 快照，保证下单后库存可见
    inventory = {inv.sku_id: inv.stock for inv in await _load_inventory(product_id)}
    for sku in detail.get("skus") or []:
        sku_id = str(sku.get("sku_id") or "")
        if sku_id in inventory:
            sku["stock"] = int(inventory[sku_id])
    return detail


async def _load_inventory(product_id: str) -> list:
    from ..models import ProductInventory

    async with async_session_factory() as session:
        rows = await session.scalars(
            select(ProductInventory).where(ProductInventory.product_id == product_id)
        )
        return list(rows)


@router.post("/checkout", response_model=CheckoutResponse)
async def checkout(
    payload: CheckoutRequest,
    user: User = Depends(get_current_user),
) -> CheckoutResponse:
    # 微信支付沙箱下单：校验商品 → 原子预占库存 → 生成待支付订单与支付单（JSAPI 参数）。
    # 此时不扣款：订单 status=unpaid，支付成功回调后才置 paid；超时/取消会归还预占库存。
    if not settings.payment_enabled:
        raise HTTPException(status_code=403, detail="支付功能未开启")
    if not payload.items:
        raise HTTPException(status_code=400, detail="购物车不能为空")

    # 1. 根据前端传入的 product_id 从内存商品数据查找商品信息与 SKU
    checkout_lines: list[dict] = []
    for req_item in payload.items:
        product = find_product(req_item.product_id)
        if product is None:
            raise HTTPException(status_code=404, detail=f"商品 {req_item.product_id} 不存在")
        if product.get("status") != "on_sale":
            raise HTTPException(status_code=400, detail=f"商品 {product['title']} 已下架")
        if req_item.quantity <= 0:
            raise HTTPException(status_code=400, detail="商品数量必须大于 0")
        skus = product.get("skus") or []
        if not skus:
            raise HTTPException(status_code=400, detail=f"商品 {product['title']} 暂无规格，无法下单")
        sku = skus[0]
        checkout_lines.append({
            "product_id": req_item.product_id,
            "sku_id": sku["sku_id"],
            "title": product["title"],
            "price": sku["price"],
            "quantity": req_item.quantity,
        })

    product_names = "、".join(line["title"] for line in checkout_lines)
    total_amount = sum(Decimal(str(line["price"])) * line["quantity"] for line in checkout_lines)

    # 2. 同一事务内：预占库存 → 创建待支付订单/明细/支付单
    async with async_session_factory() as session:
        db_user = await session.get(User, user.id)
        if db_user is None:
            raise HTTPException(status_code=401, detail="用户不存在")

        # 2a. 合并同一 SKU 数量后原子预占库存（UPDATE ... WHERE stock>=qty，防止超卖）
        sku_quantities: dict[str, int] = {}
        for line in checkout_lines:
            sku_quantities[line["sku_id"]] = sku_quantities.get(line["sku_id"], 0) + line["quantity"]
        try:
            await reserve_stock(session, sku_quantities)
        except PaymentError as exc:
            raise HTTPException(status_code=exc.code, detail=exc.message) from None

        # 2b. 展示用订单号为当前时间，例如 2024.12.3.8.23.12；同一秒冲突追加序号
        stamp = now_china()
        order_id = build_order_id(stamp)
        seq = 1
        while await session.scalar(select(Order).where(Order.order_id == order_id)):
            order_id = build_order_id(stamp, seq)
            seq += 1

        # 2c. 创建待支付订单主记录
        order = Order(
            order_id=order_id,
            user_id=db_user.id,
            customer=db_user.username,
            product=product_names,
            amount=total_amount,
            status="unpaid",
            pay_method=PAY_METHOD,
        )
        session.add(order)
        await session.flush()  # 获取 order.id

        # 2d. 创建订单明细项
        for line in checkout_lines:
            session.add(
                OrderItem(
                    order_db_id=order.id,
                    product_id=line["product_id"],
                    sku_id=line["sku_id"],
                    title=line["title"],
                    price=line["price"],
                    quantity=line["quantity"],
                )
            )

        # 2e. 创建微信支付单（商户单号 + prepay_id 占位），与订单一一对应
        out_trade_no = generate_out_trade_no()
        while await session.scalar(
            select(PaymentOrder).where(PaymentOrder.out_trade_no == out_trade_no)
        ):
            out_trade_no = generate_out_trade_no()
        expires_at = payment_expires_at()
        payment = PaymentOrder(
            out_trade_no=out_trade_no,
            order_id=order_id,
            user_id=db_user.id,
            amount_fen=yuan_to_fen(total_amount),
            description=f"星途户外照明-{product_names}"[:255],
            openid=(db_user.openid or ""),
            prepay_id="pending" if settings.payment_is_v2_sandbox else "wx" + secrets.token_hex(14),
            trade_state="NOTPAY",
            expires_at=expires_at,
        )
        session.add(payment)
        await session.commit()
        await session.refresh(order)
        await session.refresh(payment)
        remaining_balance = float(db_user.wallet_balance or 0)

    # 2f. 按支付模式生成 wx.requestPayment 参数
    if settings.payment_is_v2_sandbox:
        # 官方 V2 仿真：真实调用 sandboxnew/pay/unifiedorder；失败则关单并归还预占库存
        try:
            result = await payment_v2.unified_order_jsapi(
                out_trade_no=out_trade_no,
                amount_fen=yuan_to_fen(total_amount),
                description=f"星途户外照明-{product_names}"[:120],
                openid=payment.openid,
            )
        except payment_v2.V2PaymentError as exc:
            async with async_session_factory() as cancel_session:
                cancel_order = await cancel_session.scalar(
                    select(Order).where(Order.order_id == order_id)
                )
                if cancel_order is not None and cancel_order.status == "unpaid":
                    await close_unpaid_order(cancel_session, cancel_order)
            raise HTTPException(status_code=exc.code, detail=exc.message) from None
        pay_params = result["jsapi_params"]
        async with async_session_factory() as update_session:
            await update_session.execute(
                PaymentOrder.__table__.update()
                .where(PaymentOrder.out_trade_no == out_trade_no)
                .values(prepay_id=result["prepay_id"])
            )
            await update_session.commit()
    else:
        pay_params = build_jsapi_pay_params(payment)

    # 3. 返回待支付订单与 JSAPI 调起参数（前端 wx.requestPayment 或沙箱收银台使用）
    return CheckoutResponse(
        order_id=order_id,
        status="unpaid",
        total_amount=float(total_amount),
        remaining_balance=remaining_balance,
        items=[
            CheckoutItemOut(
                product_id=line["product_id"],
                sku_id=line["sku_id"],
                title=line["title"],
                price=line["price"],
                quantity=line["quantity"],
            )
            for line in checkout_lines
        ],
        created_at=order.created_at,
        out_trade_no=out_trade_no,
        pay_method=PAY_METHOD,
        pay_mode=(settings.payment_mode or "sandbox").strip().lower(),
        pay_params=pay_params,
        expires_at=expires_at,
    )
