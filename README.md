# 星途户外照明 · 微信小程序商城系统

微信小程序商城 + FastAPI 后端 + Vue3 管理后台 + AI 智能客服，四端一体。

## 目录结构（三个主目录）

```
wx/       微信小程序端（TypeScript 基础模板，微信开发者工具导入）
server/   FastAPI 商城后端（商品 / 订单 / 支付沙箱 / 履约 / AI 客服）
client/   Vue3 管理后台（商品管理、订单管理：发货 / 退款）
```

```
wx（微信小程序）──▶ server（商城后端，AI 客服为内置 LangGraph 编排）
client（Vue 管理后台）──────┘
```

## 技术栈

| 端 | 技术 |
|---|---|
| wx | 微信原生小程序 + TypeScript（wx.login 微信官方登录，沙箱微信支付） |
| server | Python 3.12 + FastAPI + SQLAlchemy（SQLite 本机 / MySQL 8 生产），内置 LangGraph AI 客服 |
| client | Vue 3（Composition API，零构建，本地化运行时离线可用） |

## 快速启动

```bash
# 1. 商城后端（端口 8000，内含 AI 智能客服）
cd server && python -m uvicorn app.main:app --port 8000

# 2. Vue 管理后台（端口 3000）
cd client && python -m http.server 3000
# 浏览器打开 http://localhost:3000，账号 admin / Admin@123456（staff / Staff@123456）

# 3. 小程序：微信开发者工具导入 wx/ 目录（TS 编译已启用；本地调试勾选“不校验合法域名”）
```

Windows 一键脚本：`启动后端.bat`、`client/启动管理后台.bat`。

## 功能清单

- **微信小程序（wx）**：首页瀑布流 / 搜索分类、商品详情、购物车结算（收货信息）、
  微信支付沙箱收银台（成功 / 支付中 / 失败三分支）、订单列表（去支付 / 取消 / 确认收货 / 物流）、
  AI 客服聊天、我的（微信登录 / 钱包）。
- **商城后端（server）**：商品橱窗与搜索、微信登录（code / local_key 兜底）、JWT 鉴权、
  下单原子预占库存、沙箱支付状态机（unpaid→paid→shipped→completed / refunded / cancelled）、
  管理端接口（商品 CRUD、订单列表、发货、退款）、聊天会话 / 转人工 / 记忆 / RAG。
- **管理后台（client）**：商品管理（增删改查、上下架、封面上传、SKU）、
  订单管理（状态筛选、发货填物流、退款回补库存）、客服配置说明页。
- **AI 智能客服（内置）**：意图识别（商品 / 订单 / 物流 / 售后 / 库存 / 投诉 / 转人工）、
  RAG 接地校验、商品推荐卡、长期记忆、人工坐席接管；知识库向量检索 + LLM 生成，
  `LLM_PROVIDER=mock` 本地可跑（规则模式），配 `LLM_API_KEY` 即切换 DeepSeek。

## 支付（模拟）

- `PAYMENT_MODE=sandbox`（默认）：本地沙箱收银台，不触达微信、不真实扣款；
  支持 `SUCCESS / USERPAYING / PAYERROR` 三分支演示与失败重试。
- `PAYMENT_MODE=v2sandbox`：微信官方 V2 仿真测试系统（真实请求 sandboxnew 接口，仅后端联调）。
- 接真实商户后切 `wechat`：收银台自动改调 `wx.requestPayment` 拉起微信官方收银台。

## 数据库（MySQL 8）

- 建表与测试数据：`server/sql/schema.sql`（16 张表，utf8mb4）+ `server/sql/seed_data.sql`
- 由 SQLAlchemy 模型自动生成（`server/sql/generate_sql.py`），结构见 `server/app/models.py`
- server 配置 `MYSQL_ADDRESS / MYSQL_USERNAME / MYSQL_PASSWORD / MYSQL_DATABASE` 后自动切 MySQL；
  本机未配置时用 SQLite（`server/doudian.db`）

## 测试

```bash
cd server && python -m pytest tests -q      # 支付 / 履约 / 钱包 / 推荐等（关键链路全绿）
cd wx && npx tsc -p tsconfig.json --noEmit  # 小程序 TypeScript 类型检查
```

## 文档

- `server/微信支付沙箱.md`、`server/微信支付官方V2仿真.md`：支付链路说明
- `wx/weixin-analysis.md`：小程序端实现说明
- `项目架构文档-星途客服小程序.md`、`项目答辩问题-星途客服小程序.md`：答辩资料
