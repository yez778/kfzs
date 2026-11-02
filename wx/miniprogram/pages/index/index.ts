/* ============================================================
 * 电商首页 · 极简风格
 * 顶部搜索 / 横向分类导航 / 双列商品网格（flex-wrap）
 * ============================================================ */
const app = getApp<IAppOption>();

/* ---------- 类型定义 ---------- */

/** 列表接口返回结构（/shop/products） */
interface IProductsResponse {
  items: IProductItem[];
  total: number;
  page: number;
  size: number;
}

/** 商品卡片视图模型：在后端模型上补充展示用字段 */
interface IProductVM extends IProductItem {
  /** 销量展示文案，如 "4100" / "1.2万" */
  sales_text: string;
}

/** 页面 data 类型 */
interface IHomeData {
  keyword: string;
  categories: ICategoryItem[];
  activeCategory: string;
  products: IProductVM[];
  page: number;
  size: number;
  hasMore: boolean;
  loading: boolean;
}

/** 内置兜底分类（接口失败时使用） */
const FALLBACK_CATEGORIES: ICategoryItem[] = [
  { code: '', name: '全部' },
  { code: 'post', name: '柱头灯' },
  { code: 'wall', name: '户外壁灯' },
  { code: 'solar', name: '太阳能庭院灯' },
];

/** 内置兜底商品（接口失败时保证页面有内容；封面用包内本地 JPEG） */
const FALLBACK_PRODUCTS: IProductVM[] = [
  { product_id: 'P10009', title: '太阳能柱头灯户外防水现代简约LED庭院灯方形围墙灯', subtitle: '', category: '', category_code: 'post', price: 350, original_price: 399, sales_count: 4100, cover: '/assets/products/P10009.jpg', sales_text: '4100' },
  { product_id: 'P10016', title: '太阳能柱头灯户外防水别墅庭院灯中式围墙门柱氛围景观灯', subtitle: '', category: '', category_code: 'solar', price: 180, original_price: 220, sales_count: 12600, cover: '/assets/products/P10016.jpg', sales_text: '1.2万' },
  { product_id: 'P10017', title: '现代简约LED壁灯户外防水 IP65 玻璃灯罩 3000K', subtitle: '', category: '', category_code: 'wall', price: 100, original_price: 0, sales_count: 1820, cover: '/assets/products/P10017.jpg', sales_text: '1820' },
  { product_id: 'P10020', title: '太阳能壁灯户外防水别墅庭院门口灯人体感应壁灯', subtitle: '', category: '', category_code: 'wall', price: 145, original_price: 0, sales_count: 860, cover: '/assets/products/P10020.jpg', sales_text: '860' },
];

/* ---------- 工具函数 ---------- */

/** 销量格式化：>=10000 显示「x.x万」 */
function formatSales(n: number): string {
  if (n >= 10000) return (n / 10000).toFixed(1).replace(/\.0$/, '') + '万';
  return String(n || 0);
}

/** 后端商品 -> 卡片视图模型（封面优先包内本地 JPEG + 销量文案） */
function toViewModel(it: IProductItem): IProductVM {
  return {
    ...it,
    cover: app.productImage(it.product_id, it.cover || ''),
    sales_text: formatSales(it.sales_count),
  };
}

/* ---------- 页面 ---------- */

Page<IHomeData, any>({
  data: {
    keyword: '',
    categories: [{ code: '', name: '全部' }],
    activeCategory: '',
    products: [],
    page: 1,
    size: 20,
    hasMore: true,
    loading: false,
  },

  onLoad() {
    this.loadCategories();
    this.loadProducts(true);
  },

  onPullDownRefresh() {
    this.loadProducts(true).finally(() => wx.stopPullDownRefresh());
  },

  onReachBottom() {
    if (this.data.hasMore && !this.data.loading) {
      this.loadProducts(false);
    }
  },

  /* ---------- 分类 ---------- */
  async loadCategories() {
    try {
      const cats = (await app.request<ICategoryItem[]>('/shop/categories')) || [];
      const list = cats.some((c) => c.code === '')
        ? cats
        : [{ code: '', name: '全部' }, ...cats];
      this.setData({ categories: list });
    } catch {
      this.setData({ categories: FALLBACK_CATEGORIES });
    }
  },

  onCategoryTap(e: any) {
    const code = (e.currentTarget.dataset.code as string) || '';
    if (code === this.data.activeCategory) return;
    this.setData({ activeCategory: code });
    this.loadProducts(true);
  },

  /* ---------- 搜索 ---------- */
  onSearchInput(e: any) {
    this.setData({ keyword: e.detail.value });
  },

  onSearchConfirm() {
    this.loadProducts(true);
  },

  onClearSearch() {
    this.setData({ keyword: '' });
    this.loadProducts(true);
  },

  /* ---------- 商品列表 ---------- */
  async loadProducts(reset: boolean): Promise<void> {
    if (this.data.loading) return;
    const page = reset ? 1 : this.data.page;
    this.setData({ loading: true });

    try {
      const res = await app.request<IProductsResponse>(
        `/shop/products?q=${encodeURIComponent(this.data.keyword)}` +
          `&category=${encodeURIComponent(this.data.activeCategory)}` +
          `&page=${page}&size=${this.data.size}`
      );
      const items = ((res && res.items) || []).map(toViewModel);
      const products = reset
        ? items
        : this.data.products.concat(items);

      this.setData({
        products,
        page: page + 1,
        hasMore: items.length >= this.data.size,
      });
    } catch (err) {
      // 离线 / 接口异常：首屏用兜底数据，避免空白
      if (reset) this.setData({ products: FALLBACK_PRODUCTS, hasMore: false });
    } finally {
      this.setData({ loading: false });
    }
  },

  /* ---------- 跳转 ---------- */
  onProductTap(e: any) {
    const id = e.currentTarget.dataset.id as string;
    if (!id) return;
    wx.navigateTo({ url: `/pages/detail/detail?id=${encodeURIComponent(id)}` });
  },
});
