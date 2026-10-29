// 应用自定义全局类型：IAppOption 等
// 完整微信 API 类型声明位于 typings/types/wx/（精简版，覆盖本工程所用 API）

interface IAppOption {
  onLaunch?: () => void;
  globalData: {
    /** 后端 FastAPI 基地址（含 /api/v1） */
    apiBase: string;
    /** JWT token，登录后写入，请求自动附带 Authorization */
    token: string;
    /** 当前用户信息（未登录为 null） */
    userInfo: IUserProfile | null;
    /** 开发者工具无 AppSecret 时用本地 key 记住同一用户 */
    localKey: string;
  };
  /** 统一请求封装：自动拼 base、带 token、解析错误 */
  request<T>(path: string, options?: IRequestOptions): Promise<T>;
  /** 商品图片地址转绝对地址（相对路径拼 apiBase） */
  mediaUrl(url: string): string;
  /** 登录态是否有效 */
  isLoggedIn(): boolean;
  /** 保存登录态（token + 用户信息） */
  saveLogin(token: string, user: IUserProfile): void;
  /** 清除登录态 */
  clearLogin(): void;
}

interface IRequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  data?: Record<string, any>;
}

/** 后端 /auth/me 返回的用户信息 */
interface IUserProfile {
  id: number;
  username: string;
  role: string;
  avatar_url: string;
  wallet_balance: number;
  login_type: string;
}

/** 购物车本地条目 */
interface ICartItem {
  product_id: string;
  sku_id: string;
  title: string;
  price: number;
  cover: string;
  quantity: number;
}

/** 小程序全局定时器（来自宿主环境，非标准 ES lib） */
declare function setTimeout(callback: (...args: any[]) => void, timeout?: number): number;
declare function clearTimeout(handle: number): void;
declare function setInterval(callback: (...args: any[]) => void, timeout?: number): number;
declare function clearInterval(handle: number): void;

/** 商品列表项（/shop/products 返回） */
interface IProductItem {
  product_id: string;
  title: string;
  subtitle: string;
  category: string;
  category_code: string;
  price: number;
  original_price: number;
  sales_count: number;
  cover: string;
  cover_color?: string;
  tags?: string[];
}

/** 商品详情（/shop/products/{id} 返回） */
interface IProductDetail extends IProductItem {
  description: string;
  gallery: string[];
  specs: { label: string; value: string }[];
  skus: {
    sku_id: string;
    spec: string;
    price: number;
    stock: number;
    threshold: number;
  }[];
  services: string[];
  status: string;
  source_url?: string;
}

/** 下单响应（/shop/checkout 返回） */
interface ICheckoutResult {
  order_id: string;
  status: string;
  total_amount: number;
  remaining_balance: number;
  items: {
    product_id: string;
    sku_id: string;
    title: string;
    price: number;
    quantity: number;
  }[];
  created_at: string;
  out_trade_no: string;
  pay_method: string;
  pay_params: Record<string, any>;
  expires_at: string | null;
}

/** 支付状态（/payments/* 返回） */
interface IPaymentStatus {
  out_trade_no: string;
  order_id: string;
  trade_state: string;
  status: string;
  amount_fen: number;
  amount: number;
  transaction_id: string | null;
  paid_at: string | null;
  expires_at: string | null;
  pay_params: Record<string, any> | null;
  payer_result: string | null;
  fail_reason: string | null;
}

/** 我的订单（/auth/me/orders 返回） */
interface IMyOrder {
  order_id: string;
  customer: string;
  product: string;
  amount: number;
  status: string;
  created_at: string;
  pay_method: string;
  ship_company: string;
  ship_company_name: string;
  logistics_code: string;
  shipped_at: string | null;
  received_at: string | null;
  refund_no: string;
  refunded_at: string | null;
  items: {
    product_id: string;
    title: string;
    price: number;
    quantity: number;
  }[];
}

/** 分类项（/shop/categories 返回） */
interface ICategoryItem {
  code: string;
  name: string;
  count?: number;
}
