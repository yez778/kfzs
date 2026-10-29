export {};
// 购物车：数量增删、结算、收货信息表单（数据存本地 storage；下单走后端 /shop/checkout）
const app = getApp<IAppOption>();

Page({
  data: {
    items: [] as ICartItem[],
    total: 0,
    contact: { name: '', phone: '', address: '' },
    submitting: false,
  },

  onShow() {
    this.refreshCart();
    const contact = (wx.getStorageSync('cart_contact') || {}) as {
      name: string;
      phone: string;
      address: string;
    };
    this.setData({ contact });
  },

  refreshCart() {
    const items = ((wx.getStorageSync('cart_items') || []) as ICartItem[]).map((it) => ({
      ...it,
      cover: app.mediaUrl(it.cover || ''),
    }));
    this.setData({
      items,
      total: items.reduce((sum, it) => sum + it.price * it.quantity, 0),
    });
  },

  minus(e: any) {
    const id = e.currentTarget.dataset.id;
    const items = this.data.items.map((it) =>
      it.product_id === id ? { ...it, quantity: Math.max(1, it.quantity - 1) } : it
    );
    this.saveItems(items);
  },

  plus(e: any) {
    const id = e.currentTarget.dataset.id;
    const items = this.data.items.map((it) =>
      it.product_id === id ? { ...it, quantity: it.quantity + 1 } : it
    );
    this.saveItems(items);
  },

  removeItem(e: any) {
    const id = e.currentTarget.dataset.id;
    const title = this.data.items.find((it) => it.product_id === id)?.title || '';
    wx.showModal({
      title: '移除商品',
      content: `确定移除「${title}」吗？`,
      success: (res) => {
        if (res.confirm) {
          this.saveItems(this.data.items.filter((it) => it.product_id !== id));
        }
      },
    });
  },

  saveItems(items: ICartItem[]) {
    // 存储时还原相对路径（避免 apiBase 变化后封面失效）
    const stored = items.map((it) => ({
      ...it,
      cover: it.cover.startsWith(app.globalData.apiBase)
        ? it.cover.slice(app.globalData.apiBase.length)
        : it.cover,
    }));
    wx.setStorageSync('cart_items', stored);
    this.refreshCart();
  },

  onContactInput(e: any) {
    const field = e.currentTarget.dataset.field;
    this.setData({ [`contact.${field}`]: e.detail.value });
  },

  saveContact() {
    wx.setStorageSync('cart_contact', this.data.contact);
  },

  // 去结算：登录检查 → 下单（预占库存、生成待支付订单）→ 跳收银台
  async checkout() {
    if (this.data.submitting) return;
    if (!this.data.items.length) {
      wx.showToast({ title: '购物车是空的', icon: 'none' });
      return;
    }
    if (!app.isLoggedIn()) {
      wx.showToast({ title: '请先登录', icon: 'none' });
      setTimeout(() => wx.switchTab({ url: '/pages/mine/mine' }), 600);
      return;
    }
    const { name, phone } = this.data.contact;
    if (!name.trim()) {
      wx.showToast({ title: '请填写收货人', icon: 'none' });
      return;
    }
    if (!/^1\d{10}$/.test(phone)) {
      wx.showToast({ title: '请填写正确的手机号', icon: 'none' });
      return;
    }
    this.saveContact();
    this.setData({ submitting: true });
    try {
      const result = await app.request<ICheckoutResult>('/shop/checkout', {
        method: 'POST',
        data: {
          items: this.data.items.map((it) => ({
            product_id: it.product_id,
            quantity: it.quantity,
          })),
          customer: name.trim(),
        },
      });
      // 下单成功即清空购物车（订单可在“订单”页待支付列表继续支付/取消）
      wx.setStorageSync('cart_items', []);
      this.refreshCart();
      wx.redirectTo({
        url: `/pages/cashier/cashier?order_id=${encodeURIComponent(result.order_id)}&out_trade_no=${encodeURIComponent(result.out_trade_no)}&amount=${result.total_amount}`,
      });
    } catch (e: any) {
      wx.showToast({ title: e.message || '下单失败', icon: 'none' });
    } finally {
      this.setData({ submitting: false });
    }
  },

  goShopping() {
    wx.switchTab({ url: '/pages/index/index' });
  },
});
