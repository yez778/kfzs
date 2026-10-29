# 星途客服小程序 · TypeScript 版实现说明

按**微信开发者工具「TS-基础模板」**结构重写的小程序端，覆盖商城核心链路：
**首页 → 商品详情 → 购物车下单 → 微信支付（沙箱收银台）→ 订单履约（发货/收货/退款）→ 我的（微信登录）**。

## 一、目录结构与模板对应关系

```
weixin/
├─ project.config.json            # 小程序项目配置（微信开发者工具读取）
├─ project.private.config.json    # 个人本地配置（编译选项、预览设置等，不提交 git）
├─ tsconfig.json                  # TypeScript 编译配置
├─ package.json                   # npm 包描述（开发依赖：miniprogram-api-typings / typescript）
├─ typings/                       # TypeScript 类型声明
│  ├─ index.d.ts                  # 应用自定义全局类型（IAppOption / 接口响应类型 / 定时器）
│  └─ types/
│     └─ wx/
│        └─ index.d.ts            # wx.* API 精简类型声明（覆盖本工程所用 API）
└─ miniprogram/                   # 小程序实际代码根（开发者工具只编译此目录）
   ├─ app.ts                      # 应用入口：全局数据 + 全局请求函数（request/mediaUrl/登录态）
   ├─ app.json                    # 全局配置：6 个页面注册、窗口样式、tabBar（首页/购物车/订单/我的）
   ├─ app.less                    # 全局样式：通用卡片、价格色、按钮、状态标签、表单
   ├─ sitemap.json                # 小程序索引配置（允许所有页面被微信搜索收录）
   └─ pages/                      # 每页 4 个文件：.ts / .wxml / .less / .json
      ├─ index/                   # 首页：搜索 + 分类筛选 + 商品瀑布流（双列）
      ├─ detail/                  # 商品详情：轮播大图、规格选择、数量、加购/立即购买
      ├─ cart/                    # 购物车：数量增删、收货信息表单、结算下单
      ├─ cashier/                 # 微信支付（沙箱）收银台：成功/支付中/失败三分支（模板基础上新增）
      ├─ orders/                  # 订单列表：状态标签、去支付、取消订单、确认收货、物流
      └─ mine/                    # 我的：微信登录、退出、钱包展示、快捷入口
```

> 说明：在模板 5 页基础上**新增 `pages/cashier/` 收银台页**——开发者工具无真实商户，
> `wx.requestPayment` 必然失败，因此用独立页面模拟微信收银台三分支，走通完整支付闭环。

## 二、页面功能清单

| 页面 | 功能 | 后端接口 |
|---|---|---|
| index 首页 | 搜索、分类筛选、双列瀑布流、下拉刷新/触底加载、快捷加购 | `GET /shop/products`、`GET /shop/categories` |
| detail 详情 | 轮播大图、SKU 规格单选、数量步进、加入购物车、立即购买（下单跳收银台） | `GET /shop/products/{id}`、`POST /shop/checkout` |
| cart 购物车 | 本地购物车（storage）、数量增删、收货人/手机/地址表单、合计、去结算 | `POST /shop/checkout` |
| cashier 收银台 | 微信绿收银台 UI；**模拟支付成功 / 支付中 / 失败（余额不足）**；失败可重试；真实模式自动走 `wx.requestPayment` | `POST /payments/sandbox/complete`、`GET /payments/by-order/{id}` |
| chat AI客服 | 气泡对话（商品卡片/引用/转人工）、新会话、进入会话历史 | `POST /chat`、`GET/POST /sessions` |
| history 会话历史 | 历史会话列表（标题/最后消息/条数/时间）、删除会话、点击回到对话并加载完整历史 | `GET /sessions`、`GET /sessions/{id}/messages`、`DELETE /sessions/{id}` |
| orders 订单 | 六种状态标签、待支付→去支付/取消订单、已发货→物流+确认收货、退款单展示、下拉刷新 | `GET /auth/me/orders`、`POST /payments/by-order/{id}/close`、`POST /orders/{id}/receive` |
| mine 我的 | 微信一键登录（`wx.login` + `getUserProfile`）、退出、钱包余额展示、快捷入口 | `POST /auth/wechat`、`GET /auth/me` |

## 三、支付链路（与后端沙箱对齐）

1. **下单**：`POST /shop/checkout`（items + customer）→ 后端原子预占库存、生成待支付订单
   （`unpaid`）+ 微信支付单，返回 `order_id / out_trade_no / total_amount / pay_params`。
2. **收银台**：`pages/cashier` 查询支付状态（`GET /payments/by-order/{id}`），提供三个沙箱按钮：
   - ✅ **模拟支付成功** → `POST /payments/sandbox/complete {result: SUCCESS}` → 订单 `paid`，跳订单页
   - ⏳ **模拟支付中** → `result: USERPAYING` → 订单保持 `unpaid`（支付单回显 USERPAYING），可查询
   - ⚠️ **模拟支付失败（余额不足）** → `result: PAYERROR, fail_reason: NOTENOUGH` → 订单保持 `unpaid`、
     库存仍预占，**重新支付不重复预占**，可稍后在订单页继续
3. **真实微信支付**：接入真实商户后，后端切 `PAYMENT_MODE=wechat`，`pay_params` 将包含
   `timeStamp/nonceStr/package/signType/paySign`，收银台页自动改调 `wx.requestPayment` 拉起微信官方收银台
   （`cashier.ts → realPay()`），支付结果以后端异步通知为准，前端再查询兜底。
4. **履约闭环**：订单 `unpaid → paid → shipped → completed`；商家后台发货（物流单号），买家在订单页
   「确认收货」；退款订单展示退款单号（`refund_no`）。

## 四、登录说明（开发者工具可用）

- 真实环境：`wx.login()` 拿 code → `POST /auth/wechat {code}` → 后端 `code2Session` 换 openid。
- **开发者工具 / 无 AppSecret**：后端未配置时，用 `local_key` 兜底生成 `dev:{local_key}` 用户，
  保证同一工具同一手机可记住登录态。`app.ts onLaunch` 自动生成并持久化本地 key。
- 登录态：JWT 存 `wx.setStorageSync('token')`，全局 `request()` 自动附带 `Authorization`，
  401 自动清登录态。

## 五、启动与开发

1. 微信开发者工具 → 导入项目 → 选择 `weixin/` 目录（已含 `project.config.json`，appid 为测试号
   `touristappid`，可替换为自己的 AppID）。
2. 工具会自动启用 **TypeScript 编译**（`project.config.json` 中 `useCompilerPlugins: ["typescript"]`）。
3. 本地调试：启动后端 `python -m uvicorn app.main:app --port 8000`（见根 README）；
   详情-右上角-「详情」→ 本地设置勾选 **「不校验合法域名」**（默认已通过
   `project.private.config.json` 的 `urlCheck: false` 关闭校验）。
4. 后端地址默认 `http://localhost:8000/api/v1`（`miniprogram/app.ts` 顶部 `API_BASE`）；
   真机预览需改为 **HTTPS 域名** 并在小程序后台配置 request 合法域名。
5. 可选：`cd weixin && npm install` 安装 `typescript` 与 `miniprogram-api-typings` 后
   `npm run compile` 做类型检查（本仓库已内置精简 `typings`，不安装也能编译）。

## 六、类型体系

- `typings/index.d.ts`：`IAppOption`（全局数据 + 请求函数）、`IUserProfile / ICartItem /
  IProductItem / IProductDetail / ICheckoutResult / IPaymentStatus / IMyOrder / ICategoryItem`
  等与后端接口一一对应的响应类型，以及宿主环境 `setTimeout` 等全局声明。
- `typings/types/wx/index.d.ts`：**精简版** wx.* API 声明（覆盖所用 API）。需要完整声明的
  场景可 `npm i miniprogram-api-typings`，tsconfig 已按 `typeRoots: ["./typings"]` 解析。
- 页面均为 `export {};` 模块化写法，避免多页面顶层 `const app` 全局冲突；已通过
  `tsc --noEmit` 全量类型检查（0 错误）。

## 七、注意事项

- 商品封面图为淘宝 CDN 或后端代理地址：`app.ts → mediaUrl()` 统一把相对路径
  （`/api/v1/shop/cover-proxy?u=...`、`/uploads/...`）拼上后端地址；代理地址需后端在线。
- 微信开发者工具模拟器**不支持** `wx.getUserProfile` 时自动跳过（静默登录兜底）。
- 购物车数据在本地 `cart_items`；下单成功即清空（订单进入「待支付」列表，可继续支付/取消）。
- 退款由**后台管理端**发起（`POST /admin/orders/{id}/refund`），小程序端仅展示退款单号。
