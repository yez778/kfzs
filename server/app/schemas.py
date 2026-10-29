# Pydantic 请求/响应模型：定义 API 出入参结构、默认值与字段校验
import json
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str = "customer"
    username: str = ""
    avatar_url: str = ""
    wallet_balance: float = 2000
    user_id: int = 0


class WechatLoginRequest(BaseModel):
    # code 来自 wx.login；local_key 用于开发者工具在无 AppSecret 时记住同一用户
    code: str = ""
    local_key: str = ""
    username: str | None = None
    avatar_url: str | None = None


class ProfileOut(BaseModel):
    id: int
    username: str
    role: str
    avatar_url: str = ""
    wallet_balance: float = 2000
    login_type: str = "password"


class ProfileUpdate(BaseModel):
    username: str | None = None
    avatar_url: str | None = None


class CartSaveRequest(BaseModel):
    items: list[dict] = []


class CartOut(BaseModel):
    items: list[dict] = []


class MyOrderItemOut(BaseModel):
    product_id: str
    title: str
    price: float
    quantity: int

    @field_validator("price", mode="before")
    @classmethod
    def _to_float(cls, value: object) -> object:
        if isinstance(value, Decimal):
            return float(value)
        return value


class MyOrderOut(BaseModel):
    order_id: str
    customer: str
    product: str
    amount: float
    status: str
    created_at: datetime
    pay_method: str = ""
    ship_company: str = ""
    ship_company_name: str = ""
    logistics_code: str = ""
    shipped_at: datetime | None = None
    received_at: datetime | None = None
    refund_no: str = ""
    refunded_at: datetime | None = None
    items: list[MyOrderItemOut] = []

    @field_validator("amount", mode="before")
    @classmethod
    def decimal_to_float(cls, value: object) -> object:
        if isinstance(value, Decimal):
            return float(value)
        return value


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str


class ChatStep(BaseModel):
    type: str
    label: str
    detail: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    message_id: int
    response: str
    citations: list[str] = []
    needs_human: bool = False
    human_task_id: str | None = None
    steps: list[ChatStep] = []
    citations_detail: list[dict] = []
    route: dict = {}
    safety_blocked: bool = False
    # RAG 归一化相关性分数与附带的商品卡片（标题、价格、真实链接）
    relevance_score: float = 0.0
    product_cards: list[dict] = []


# 创建会话请求体（title 可选，缺省使用默认标题）
class SessionCreate(BaseModel):
    title: str | None = None


# 会话概要信息，直接由 ORM 对象转换
class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    created_at: datetime
    handoff_status: str = "none"


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: str
    role: str
    content: str
    citations: list[str] = []
    product_cards: list[dict] = []
    created_at: datetime

    @field_validator("citations", "product_cards", mode="before")
    @classmethod
    def parse_json_list(cls, value: object) -> object:
        if isinstance(value, str):
            try:
                return json.loads(value or "[]")
            except json.JSONDecodeError:
                return []
        return value or []


# 订单信息，amount 由数据库 Decimal 转为 float 便于 JSON 序列化
class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    order_id: str
    customer: str
    product: str
    amount: float
    status: str
    created_at: datetime
    updated_at: datetime | None = None

    # 金额字段校验：Decimal 转为 float，保证响应可 JSON 序列化
    @field_validator("amount", mode="before")
    @classmethod
    def decimal_to_float(cls, value: object) -> object:
        if isinstance(value, Decimal):
            return float(value)
        return value


class HumanTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_type: str
    payload: dict = {}
    status: str
    reason: str | None = None
    created_at: datetime
    reviewed_at: datetime | None = None

    @field_validator("payload", mode="before")
    @classmethod
    def parse_payload(cls, value: object) -> object:
        if isinstance(value, str):
            try:
                return json.loads(value or "{}")
            except json.JSONDecodeError:
                return {}
        return value or {}


# 人工审批任务的审批请求体，reason 为审批意见（可选）
class TaskReviewRequest(BaseModel):
    reason: str | None = None
    # 回复审核通过时员工编辑后的回复内容（仅 reply_review 类型使用）
    edited_response: str | None = None


# 仪表盘统计信息响应
class StatsOut(BaseModel):
    today_conversations: int
    auto_resolution_rate: float
    avg_response_secs: float
    pending_tasks: int


class InventoryAlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku_id: str
    sku_name: str
    current_stock: int
    threshold: int
    handled: bool
    created_at: datetime


# 员工新增商品请求体：specs/skus/services/tags 为可读的结构化列表
class ProductCreate(BaseModel):
    title: str
    subtitle: str = ""
    category: str = "柱头灯"
    category_code: str = "post"
    price: float
    original_price: float | None = None
    sales_count: int = 0
    cover: str = ""
    cover_color: str = "#E5E7EB"
    description: str = ""
    gallery: list[str] = []
    specs: list[dict] = []
    skus: list[dict] = []
    services: list[str] = []
    tags: list[str] = []
    status: str = "on_sale"
    source_url: str = ""


class ProductUpdate(BaseModel):
    title: str | None = None
    subtitle: str | None = None
    category: str | None = None
    category_code: str | None = None
    price: float | None = None
    original_price: float | None = None
    cover: str | None = None
    description: str | None = None
    status: str | None = None
    gallery: list[str] | None = None


# 商品管理列表项：金额转 float 便于前端展示
class ProductManageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: str
    title: str
    subtitle: str
    category: str
    category_code: str
    price: float
    original_price: float
    sales_count: int
    cover: str
    status: str
    tags: list[str] = []
    source_url: str = ""
    created_at: datetime

    @field_validator("price", "original_price", mode="before")
    @classmethod
    def _to_float(cls, value: object) -> object:
        if isinstance(value, Decimal):
            return float(value)
        return value

    @field_validator("tags", mode="before")
    @classmethod
    def _parse_tags(cls, value: object) -> object:
        if isinstance(value, str):
            try:
                return json.loads(value or "[]")
            except json.JSONDecodeError:
                return []
        return value or []


# 人工客服会话队列项：含顾客名、转人工状态与最近一条消息摘要
class HandoffSessionOut(BaseModel):
    id: str
    title: str
    customer: str
    handoff_status: str
    created_at: datetime
    last_message: str = ""
    last_role: str = ""
    avatar_url: str = ""
    user_id: int | None = None
    can_chat: bool = False


class AdminCustomerOut(BaseModel):
    user_id: int
    username: str
    avatar_url: str = ""
    session_id: str | None = None
    handoff_status: str = "none"
    last_message: str = ""
    can_chat: bool = False


class AdminOrderOut(BaseModel):
    order_id: str
    customer: str
    display_name: str
    product: str
    amount: float
    status: str
    created_at: datetime
    user_id: int | None = None
    # 履约扩展字段（支付方式、物流、退款单号），供管理端订单页展示
    pay_method: str = ""
    ship_company: str = ""
    ship_company_name: str = ""
    logistics_code: str = ""
    shipped_at: datetime | None = None
    received_at: datetime | None = None
    refund_no: str = ""
    refunded_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("amount", mode="before")
    @classmethod
    def _amount_float(cls, value: object) -> object:
        if isinstance(value, Decimal):
            return float(value)
        return value


# ---- 下单（Checkout）请求/响应模型 ----

class CheckoutItemRequest(BaseModel):
    # 下单商品项：前端传 product_id 与数量即可，后端自动查找对应 SKU
    product_id: str
    quantity: int = 1


class CheckoutRequest(BaseModel):
    # 下单请求体：包含商品列表与下单人名称
    items: list[CheckoutItemRequest]
    customer: str = "顾客"


class CheckoutItemOut(BaseModel):
    # 下单响应中的商品明细项
    product_id: str
    sku_id: str
    title: str
    price: float
    quantity: int

    @field_validator("price", mode="before")
    @classmethod
    def _to_float(cls, value: object) -> object:
        if isinstance(value, Decimal):
            return float(value)
        return value


class CheckoutResponse(BaseModel):
    # 下单成功响应：生成待支付订单，返回订单号、商户支付单号、金额与 JSAPI 调起参数
    order_id: str
    status: str
    total_amount: float
    remaining_balance: float = 0
    items: list[CheckoutItemOut]
    created_at: datetime
    # 微信支付沙箱字段
    out_trade_no: str = ""
    pay_method: str = ""
    # 支付模式：sandbox（本地模拟）/ v2sandbox（微信官方 V2 沙箱）/ wechat（真实）
    pay_mode: str = ""
    pay_params: dict = {}
    expires_at: datetime | None = None


class PrepayRequest(BaseModel):
    # 统一下单：传商城订单号或商户支付单号均可
    order_id: str = ""
    out_trade_no: str = ""


class ShipRequest(BaseModel):
    # 商家发货：物流公司编码（SF/YTO/ZTO/...）+ 物流单号
    company_code: str = "SF"
    logistics_code: str


class RefundRequest(BaseModel):
    # 后台对已支付订单发起退款（沙箱直接成功并回补库存）
    reason: str = ""


class FulfillmentResultOut(BaseModel):
    order_id: str
    status: str
    ship_company: str = ""
    ship_company_name: str = ""
    logistics_code: str = ""
    shipped_at: datetime | None = None
    received_at: datetime | None = None
    refund_no: str = ""
    refunded_at: datetime | None = None


class ShippingCompanyOut(BaseModel):
    code: str
    name: str


class SandboxCompleteRequest(BaseModel):
    # 沙箱收银台：模拟用户输密码后的支付结果（默认成功，可演示失败/支付中）
    out_trade_no: str
    result: str = "SUCCESS"  # SUCCESS / USERPAYING / PAYERROR
    fail_reason: str = ""  # result=PAYERROR 时的失败原因（如 NOTENOUGH 余额不足）


class PaymentStatusOut(BaseModel):
    out_trade_no: str
    order_id: str
    trade_state: str
    status: str = "unpaid"
    amount_fen: int
    amount: float
    transaction_id: str | None = None
    paid_at: datetime | None = None
    expires_at: datetime | None = None
    pay_params: dict | None = None
    payer_result: str | None = None  # 最近一次收银台结果：SUCCESS/USERPAYING/PAYERROR
    fail_reason: str | None = None
    pay_mode: str = ""  # sandbox / v2sandbox / wechat


class NotifyRequest(BaseModel):
    # 沙箱异步回调报文（真实微信 v3 为 AES-GCM 加密，沙箱用 HMAC 签名明文模拟）
    out_trade_no: str
    transaction_id: str = ""
    amount_fen: int
    trade_state: str = "SUCCESS"
    signature: str = ""
