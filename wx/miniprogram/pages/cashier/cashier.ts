export {};
// 微信支付（沙箱）收银台：模拟微信原生收银台三分支（成功 / 支付中 / 失败可重试）
// 说明：开发者工具无真实商户，wx.requestPayment 会失败，故用本页模拟；
// 接入真实微信商户后（后端 PAYMENT_MODE=wechat，pay_params 含 timeStamp 等），自动走 wx.requestPayment。
const app = getApp<IAppOption>();

Page({
  data: {
    orderId: '',
    outTradeNo: '',
    amount: 0,
    status: 'unpaid',
    tradeState: 'NOTPAY',
    payParams: null as Record<string, any> | null,
    // view: 'cashier' 收银台主界面 / 'paying' 支付中 / 'success' 支付成功 / 'fail' 支付失败
    view: 'cashier',
    failReason: '',
    busy: false,
  },

  onLoad(options: any) {
    const orderId = (options && options.order_id) || '';
    const outTradeNo = (options && options.out_trade_no) || '';
    const amount = Number(options && options.amount) || 0;
    this.setData({ orderId, outTradeNo, amount });
    if (orderId) this.queryStatus();
  },

  // 查询支付单状态
  async queryStatus() {
    try {
      const st = await app.request<IPaymentStatus>(
        `/payments/by-order/${encodeURIComponent(this.data.orderId)}`
      );
      this.setData({
        status: st.status,
        tradeState: st.trade_state,
        amount: st.amount || this.data.amount,
        outTradeNo: st.out_trade_no || this.data.outTradeNo,
        payParams: st.pay_params || null,
        failReason: st.fail_reason || '',
      });
      return st;
    } catch (e: any) {
      wx.showToast({ title: e.message || '查询失败', icon: 'none' });
      return null;
    }
  },

  // 模拟支付成功
  async paySuccess() {
    await this.submitResult('SUCCESS');
  },

  // 模拟支付中（后端订单保持 unpaid，支付单回显 USERPAYING）
  async payPaying() {
    if (this.data.busy) return;
    this.setData({ busy: true, view: 'paying' });
    try {
      await app.request<IPaymentStatus>('/payments/sandbox/complete', {
        method: 'POST',
        data: { out_trade_no: this.data.outTradeNo, result: 'USERPAYING' },
      });
      this.setData({ view: 'paying', busy: false });
    } catch (e: any) {
      this.setData({ busy: false });
      wx.showToast({ title: e.message || '操作失败', icon: 'none' });
    }
  },

  // 模拟支付失败（余额不足）
  async payFail() {
    if (this.data.busy) return;
    this.setData({ busy: true });
    try {
      await app.request<IPaymentStatus>('/payments/sandbox/complete', {
        method: 'POST',
        data: { out_trade_no: this.data.outTradeNo, result: 'PAYERROR', fail_reason: 'NOTENOUGH' },
      });
      this.setData({ view: 'fail', failReason: '余额不足（NOTENOUGH）', busy: false });
    } catch (e: any) {
      this.setData({ busy: false });
      wx.showToast({ title: e.message || '操作失败', icon: 'none' });
    }
  },

  async submitResult(result: string) {
    if (this.data.busy) return;
    this.setData({ busy: true });
    try {
      const st = await app.request<IPaymentStatus>('/payments/sandbox/complete', {
        method: 'POST',
        data: { out_trade_no: this.data.outTradeNo, result },
      });
      this.setData({
        status: st.status,
        tradeState: st.trade_state,
        busy: false,
      });
      if (st.status === 'paid') {
        this.setData({ view: 'success' });
        wx.showToast({ title: '支付成功', icon: 'success' });
        setTimeout(() => wx.redirectTo({ url: '/pages/orders/orders' }), 1500);
      } else {
        // 后端返回了其他状态（如 USERPAYING / PAYERROR）
        this.setData({ view: st.trade_state === 'USERPAYING' ? 'paying' : 'fail' });
      }
    } catch (e: any) {
      this.setData({ busy: false });
      wx.showToast({ title: e.message || '支付失败', icon: 'none' });
    }
  },

  // 支付中状态轮询查询
  async recheck() {
    wx.showLoading({ title: '查询中' });
    const st = await this.queryStatus();
    wx.hideLoading();
    if (st && st.status === 'paid') {
      this.setData({ view: 'success' });
      setTimeout(() => wx.redirectTo({ url: '/pages/orders/orders' }), 1200);
    } else {
      wx.showToast({ title: '仍未支付完成', icon: 'none' });
    }
  },

  // 支付失败后重新支付：回到收银台主界面（订单仍 unpaid，不重复预占库存）
  retry() {
    this.setData({ view: 'cashier', failReason: '' });
  },

  // 稍后再付：回订单列表（订单保持 unpaid，可在订单页继续支付）
  later() {
    wx.redirectTo({ url: '/pages/orders/orders' });
  },

  // 真实微信支付模式：用后端返回的 JSAPI 参数拉起微信收银台
  realPay() {
    const p = this.data.payParams;
    if (!p || !p.timeStamp) return;
    wx.requestPayment({
      timeStamp: String(p.timeStamp),
      nonceStr: String(p.nonceStr),
      package: String(p.package),
      signType: String(p.signType || 'RSA'),
      paySign: String(p.paySign),
      success: () => {
        this.recheck();
      },
      fail: () => {
        wx.showToast({ title: '已取消支付', icon: 'none' });
      },
    });
  },

  goOrders() {
    wx.redirectTo({ url: '/pages/orders/orders' });
  },
});
