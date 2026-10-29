export {};
// 首页：搜索 + 分类筛选 + 商品瀑布流
const app = getApp<IAppOption>();

Page({
  data: {
    keyword: '',
    categories: [] as ICategoryItem[],
    activeCategory: '',
    products: [] as IProductItem[],
    leftCol: [] as IProductItem[],
    rightCol: [] as IProductItem[],
    page: 1,
    size: 20,
    hasMore: true,
    loading: false,
    cartCount: 0,
  },

  onLoad() {
    this.loadCategories();
    this.loadProducts(true);
    this.refreshCartCount();
  },

  onShow() {
    this.refreshCartCount();
  },

  onPullDownRefresh() {
    this.loadProducts(true).finally(() => wx.stopPullDownRefresh());
  },

  onReachBottom() {
    if (this.data.hasMore && !this.data.loading) {
      this.loadProducts(false);
    }
  },

  refreshCartCount() {
    const items = (wx.getStorageSync('cart_items') || []) as ICartItem[];
    const count = items.reduce((sum, it) => sum + it.quantity, 0);
    this.setData({ cartCount: count });
  },

  async loadCategories() {
    try {
      const cats = (await app.request<ICategoryItem[]>('/shop/categories')) || [];
      this.setData({ categories: cats });
    } catch {
      // 分类拉取失败时用内置兜底
      this.setData({
        categories: [
          { code: '', name: '全部' },
          { code: 'post', name: '柱头灯' },
          { code: 'wall', name: '户外壁灯' },
          { code: 'solar', name: '太阳能庭院灯' },
        ],
      });
    }
  },

  async loadProducts(reset: boolean) {
    if (this.data.loading) return;
    const page = reset ? 1 : this.data.page;
    this.setData({ loading: true });
    try {
      const res = await app.request<{
        items: IProductItem[];
        total: number;
        page: number;
        size: number;
      }>(`/shop/products?q=${encodeURIComponent(this.data.keyword)}&category=${encodeURIComponent(this.data.activeCategory)}&page=${page}&size=${this.data.size}`);
      const items = ((res && res.items) || []).map((it) => ({
        ...it,
        cover: app.mediaUrl(it.cover || ''),
      }));
      const merged = reset ? items : this.data.products.concat(items);
      this.setData({
        products: merged,
        page: page + 1,
        hasMore: items.length >= this.data.size,
      });
      this.splitColumns();
    } catch (e: any) {
      wx.showToast({ title: e.message || '加载失败', icon: 'none' });
    } finally {
      this.setData({ loading: false });
    }
  },

  // 简单瀑布流：左右两列交替分配
  splitColumns() {
    const left: IProductItem[] = [];
    const right: IProductItem[] = [];
    this.data.products.forEach((p, i) => {
      if (i % 2 === 0) left.push(p);
      else right.push(p);
    });
    this.setData({ leftCol: left, rightCol: right });
  },

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

  onCategoryTap(e: any) {
    const code = e.currentTarget.dataset.code;
    this.setData({ activeCategory: code });
    this.loadProducts(true);
  },

  onProductTap(e: any) {
    const id = e.currentTarget.dataset.id;
    wx.navigateTo({ url: `/pages/detail/detail?id=${encodeURIComponent(id)}` });
  },

  addCart(e: any) {
    const item = this.data.products.find((p) => p.product_id === e.currentTarget.dataset.id);
    if (!item) return;
    const items = (wx.getStorageSync('cart_items') || []) as ICartItem[];
    const found = items.find((it) => it.product_id === item!.product_id);
    if (found) {
      found.quantity += 1;
    } else {
      items.push({
        product_id: item.product_id,
        sku_id: '',
        title: item.title,
        price: item.price,
        cover: item.cover,
        quantity: 1,
      });
    }
    wx.setStorageSync('cart_items', items);
    this.refreshCartCount();
    wx.showToast({ title: '已加入购物车', icon: 'success' });
  },

  goCart() {
    wx.switchTab({ url: '/pages/cart/cart' });
  },
});
