export {};
// 商品详情：大图、规格、数量选择、加购 / 立即购买（立即购买 → 下单 → 收银台）
const app = getApp<IAppOption>();

Page({
  data: {
    product: null as IProductDetail | null,
    gallery: [] as string[],
    skuIndex: 0,
    quantity: 1,
    specs: [] as { label: string; value: string }[],
    services: [] as string[],
    loading: true,
    submitting: false,
  },

  onLoad(options: any) {
    const id = options && options.id ? decodeURIComponent(options.id) : '';
    if (!id) {
      wx.showToast({ title: '缺少商品参数', icon: 'none' });
      setTimeout(() => wx.navigateBack(), 800);
      return;
    }
    this.loadDetail(id);
  },

  async loadDetail(id: string) {
    this.setData({ loading: true });
    try {
      const detail = await app.request<IProductDetail>(`/shop/products/${encodeURIComponent(id)}`);
      this.setData({
        product: detail,
        // 轮播一律用包内本地图（主图 + 实景图），避免外链 webp 在小程序里空白
        gallery: app.productGallery(detail.product_id),
        specs: detail.specs || [],
        services: detail.services || [],
        skuIndex: 0,
        quantity: 1,
      });
    } catch (e: any) {
      wx.showToast({ title: e.message || '商品加载失败', icon: 'none' });
      setTimeout(() => wx.navigateBack(), 800);
    } finally {
      this.setData({ loading: false });
    }
  },

  onSkuTap(e: any) {
    const index = Number(e.currentTarget.dataset.index);
    const product = this.data.product;
    if (!product || !product.skus[index]) return;
    this.setData({ skuIndex: index });
  },

  onPreview(e: any) {
    const current = e.currentTarget.dataset.src;
    wx.previewImage({ current, urls: this.data.gallery });
  },

  minus() {
    if (this.data.quantity <= 1) return;
    this.setData({ quantity: this.data.quantity - 1 });
  },

  plus() {
    const product = this.data.product;
    const max = product && product.skus[this.data.skuIndex]
      ? product.skus[this.data.skuIndex].stock
      : 99;
    if (this.data.quantity >= max) {
      wx.showToast({ title: '已达库存上限', icon: 'none' });
      return;
    }
    this.setData({ quantity: this.data.quantity + 1 });
  },

  // 加入购物车（本地存储）
  addCart() {
    const product = this.data.product;
    if (!product) return;
    const sku = product.skus[this.data.skuIndex] || product.skus[0];
    const items = (wx.getStorageSync('cart_items') || []) as ICartItem[];
    const found = items.find((it) => it.product_id === product!.product_id);
    if (found) {
      found.quantity += this.data.quantity;
    } else {
      items.push({
        product_id: product.product_id,
        sku_id: sku ? sku.sku_id : '',
        title: product.title,
        price: sku ? sku.price : product.price,
        cover: app.productImage(product.product_id, product.cover),
        quantity: this.data.quantity,
      });
    }
    wx.setStorageSync('cart_items', items);
    wx.showToast({ title: '已加入购物车', icon: 'success' });
  },

  // 立即购买：下单 → 跳收银台
  async buyNow() {
    if (this.data.submitting) return;
    const product = this.data.product;
    if (!product) return;
    if (!app.isLoggedIn()) {
      wx.showToast({ title: '请先登录', icon: 'none' });
      setTimeout(() => wx.switchTab({ url: '/pages/mine/mine' }), 600);
      return;
    }
    this.setData({ submitting: true });
    try {
      const result = await app.request<ICheckoutResult>('/shop/checkout', {
        method: 'POST',
        data: { items: [{ product_id: product.product_id, quantity: this.data.quantity }] },
      });
      wx.redirectTo({
        url: `/pages/cashier/cashier?order_id=${encodeURIComponent(result.order_id)}&out_trade_no=${encodeURIComponent(result.out_trade_no)}&amount=${result.total_amount}`,
      });
    } catch (e: any) {
      wx.showToast({ title: e.message || '下单失败', icon: 'none' });
    } finally {
      this.setData({ submitting: false });
    }
  },
});
