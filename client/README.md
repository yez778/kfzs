# 星途商品管理后台（Vue 3）

用 **Vue 3** 重写的后端商品信息管理界面，零构建、零 npm 依赖，直接对接 FastAPI 商品管理接口。

## 技术栈

- **Vue 3.4**（Options/Composition API，本项目用 Composition API + `ref/reactive/computed`）
- 运行时已下载到本地 `vendor/vue.global.prod.min.js`（含模板编译器，**离线可用**，无需 CDN）
- 原生 CSS（`css/admin.css`），无 UI 框架
- 纯静态文件，`python -m http.server` 即可托管
- 后端：FastAPI，商品接口 `/api/v1/admin/products`（需 staff / admin 角色）

> 选型说明：这是**浏览器直接引入的完整 Vue 3（global build）**，模板写在 `index.html`，逻辑在 `js/app.js`，方便答辩演示与讲解 Vue 的数据驱动、双向绑定、计算属性、列表渲染。正式工程化可平滑迁移到 Vite + SFC（`.vue` 单文件组件）。

## 目录

```
admin-vue/
├─ index.html                     # 页面结构 + Vue 模板（v-for/v-model/@click…）
├─ js/app.js                      # Vue 应用：登录 / 商品 CRUD / 上下架 / 上传 / SKU
├─ css/admin.css                  # 后台样式
├─ vendor/vue.global.prod.min.js  # Vue 3 运行时（本地化，离线可用）
└─ 启动管理后台.bat
```

## 启动

1. 启动后端（端口 8000）：
   ```bash
   cd backend
   python -m uvicorn app.main:app --port 8000
   ```
2. 启动管理台（端口 3000，已在后端 CORS 白名单）：
   ```bash
   cd admin-vue
   python -m http.server 3000
   ```
   或双击 `启动管理后台.bat`，浏览器打开 <http://localhost:3000>。
3. 用员工/管理员账号登录：
   - `admin` / `Admin@123456`
   - `staff` / `Staff@123456`
   - 顾客账号无法进入商品管理（后端 403）。

## 功能

- 账号密码登录，JWT 存 `localStorage`，401 自动回登录页；可在页面顶部修改后端地址
- 商品**列表**：图片、编号、标题/副标题/标签、分类、售价/划线价、销量、在售状态
- **搜索**（标题/编号/分类/标签）、按**状态**与**分类**筛选、分页、统计卡片
- **新增商品**：标题、分类、售价/划线价、销量、状态、封面 URL/本地上传、详情、标签、可编辑多条 **SKU（规格/价格/库存/预警阈值）**
- **编辑商品**：拉取详情补全 SKU（只读展示，库存由库存模块管理）；可改标题、价格、封面、详情、状态等
- **上架 / 下架**切换、**删除**（二次确认弹窗）
- 封面图支持本地上传（`POST /admin/products/cover`，≤5MB）与外部 URL（alicdn 走后端代理）
- Toast 操作反馈、错误提示、加载态、响应式布局

## 对接的后端接口

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/v1/auth/login` | 账号密码登录拿 JWT |
| GET | `/api/v1/shop/categories` | 分类字典 |
| GET | `/api/v1/admin/products` | 管理列表（含下架商品） |
| POST | `/api/v1/admin/products` | 新增（含 skus/gallery/tags） |
| PUT | `/api/v1/admin/products/{id}` | 编辑 |
| POST | `/api/v1/admin/products/{id}/status` | 上下架 `on_sale/off_shelf` |
| DELETE | `/api/v1/admin/products/{id}` | 删除 |
| POST | `/api/v1/admin/products/cover` | 封面上传（multipart） |
| GET | `/api/v1/shop/products/{id}` | 详情（取 SKU/库存） |

## Vue 知识点对应（答辩可讲）

- `v-model` 双向绑定：登录表单、搜索框、新增/编辑表单、SKU 行
- `v-for` + `:key`：商品表格、标签、SKU 列表、分类下拉
- `computed`：`filtered`（搜索+筛选）、`paged`/`totalPages`（分页）、`dialogCoverUrl`
- `@click` / `@submit.prevent` / `@change`：事件处理与方法
- `v-if` / 登录态与弹窗条件渲染、`<transition>` Toast 动画
- 组件化数据驱动：改 `products` 数组 → 视图自动更新，无需手动操作 DOM
