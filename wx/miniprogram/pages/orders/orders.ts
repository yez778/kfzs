export {};
// 订单列表：状态标签、去支付、取消订单、确认收货、物流信息
const app = getApp<IAppOption>();

const STATUS_TEXT: Record<string, string> = {
  unpaid: '待支付',
  paid: '待发货',
  shipped: '待收货',
  completed: '已完成',
  refunded: '已退款',
  cancelled: '已取消',
};

const STATUS_CLASS: Record<string, string> = {
  unpaid: 'status-unpaid',
  paid: 'status-paid',
  shipped: 'status-shipped',
  completed: 'status-completed',
  refunded: 'status-refunded',
  cancelled: 'status-cancelled',
};

Page({
  data: {
    orders: [] as IMyOrder[],
    loading: false,
    logged: false,
    statusText: STATUS_TEXT,
    statusClass: STATUS_CLASS,
  },

  onShow() {
    const logged = app.isLoggedIn();
    this.setData({ logged });
    if (!logged) {
      this.setData({ orders: [] });
      return;
    }
    this.loadOrders();
  },

  onPullDownRefresh() {
    this.loadOrders().finally(() => wx.stopPullDownRefresh());
  },

  async loadOrders() {
    if (this.data.loading) return;
    this.setData({ loading: true });
    try {
      const list = (await app.request<IMyOrder[]>('/auth/me/orders')) || [];
      this.setData({ orders: list, logged: app.isLoggedIn() });
    } catch (e: any) {
      if (!app.isLoggedIn()) this.setData({ orders: [], logged: false });
      else wx.showToast({ title: e.message || '订单加载失败', icon: 'none' });
    } finally {
      this.setData({ loading: false });
    }
  },

  goDetail(e: any) {
    wx.navigateTo({ url: `/pages/detail/detail?id=${encodeURIComponent(e.currentTarget.dataset.id)}` });
  },

  // 去支付（待支付订单）：跳收银台，cashier 页用 order_id 查询补全 out_trade_no
  pay(e: any) {
    const order = this.data.orders.find((o) => o.order_id === e.currentTarget.dataset.id);
    if (!order) return;
    wx.navigateTo({
      url: `/pages/cashier/cashier?order_id=${encodeURIComponent(order.order_id)}&amount=${order.amount}`,
    });
  },

  // 取消订单（关单并归还预占库存）
  cancel(e: any) {
    const orderId = e.currentTarget.dataset.id;
    wx.showModal({
      title: '取消订单',
      content: '确定取消该订单吗？预占库存将释放。',
      success: async (res) => {
        if (!res.confirm) return;
        wx.showLoading({ title: '处理中' });
        try {
          await app.request(`/payments/by-order/${encodeURIComponent(orderId)}/close`, {
            method: 'POST',
          });
          wx.hideLoading();
          wx.showToast({ title: '订单已取消', icon: 'success' });
          this.loadOrders();
        } catch (e2: any) {
          wx.hideLoading();
          wx.showToast({ title: e2.message || '取消失败', icon: 'none' });
        }
      },
    });
  },

  // 确认收货（shipped → completed）
  receive(e: any) {
    const orderId = e.currentTarget.dataset.id;
    wx.showModal({
      title: '确认收货',
      content: '确认已收到商品？',
      success: async (res) => {
        if (!res.confirm) return;
        wx.showLoading({ title: '处理中' });
        try {
          await app.request(`/orders/${encodeURIComponent(orderId)}/receive`, {
            method: 'POST',
          });
          wx.hideLoading();
          wx.showToast({ title: '已确认收货', icon: 'success' });
          this.loadOrders();
        } catch (e2: any) {
          wx.hideLoading();
          wx.showToast({ title: e2.message || '操作失败', icon: 'none' });
        }
      },
    });
  },

  // 申请售后：带到售后页（订单号/商品/金额）
  goAftersale(e: any) {
    const d = e.currentTarget.dataset;
    wx.navigateTo({
      url:
        '/pages/aftersale/aftersale?order_id=' +
        encodeURIComponent(d.id) +
        '&product=' +
        encodeURIComponent(d.product || '') +
        '&amount=' +
        (d.amount || 0),
    });
  },

  goLogin() {
    wx.switchTab({ url: '/pages/mine/mine' });
  },
});
