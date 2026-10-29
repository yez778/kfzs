// 微信支付收银台：按后端返回的 pay_mode 渲染不同交互
//   sandbox   本地自建沙箱 → 提供三分支模拟按钮（成功/支付中/失败）
//   v2sandbox 微信官方 V2 沙箱 → 调起 wx.requestPayment（MD5 签名），结果以 orderquery 为准，不提供伪造成功
//   wechat    真实微信支付（V3/RSA）
export {};
const app = getApp<IAppOption>();

Page({
  data: {
    orderId: '',
    outTradeNo: '',
    amount: 0,
    status: 'unpaid',
    tradeState: 'NOTPAY',
    payMode: 'sandbox',
    prepayId: '',
    signType: 'MD5',
    payParams: null as Record<string, any> | null,
    // view: 'cashier' 主界面 / 'paying' 支付中 / 'success' 支付成功 / 'fail' 支付失败
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

  // 查询支付单状态（顺带同步支付模式）
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
        payMode: st.pay_mode || 'sandbox',
        failReason: st.fail_reason || '',
      });
      return st;
    } catch (e: any) {
      wx.showToast({ title: e.message || '查询失败', icon: 'none' });
      return null;
    }
  },

  /* ---------------- 官方 V2 沙箱 / 真实支付：调起微信收银台 ---------------- */

  async callWxPay() {
    // V2 沙箱需要真实 prepay_id：没有则先请求 prepay 拿参数
    let params = this.data.payParams;
    if (!params || !params.timeStamp) {
      try {
        const st = await app.request<IPaymentStatus>('/payments/prepay', {
          method: 'POST',
          data: { order_id: this.data.orderId, out_trade_no: this.data.outTradeNo },
        });
        params = st.pay_params || null;
        if (params) {
          this.setData({
            payParams: params,
            payMode: st.pay_mode || this.data.payMode,
            prepayId: (params.package || '').replace('prepay_id=', ''),
          });
        }
      } catch (e: any) {
        wx.showToast({ title: e.message || '获取支付参数失败', icon: 'none' });
        return;
      }
    }
    if (!params || !params.timeStamp) {
      wx.showToast({ title: '支付参数缺失，请检查后端 V2 沙箱配置', icon: 'none' });
      return;
    }
    wx.showLoading({ title: '调起微信支付', mask: true });
    wx.requestPayment({
      timeStamp: String(params.timeStamp),
      nonceStr: String(params.nonceStr),
      package: String(params.package),
      signType: String(params.signType || 'MD5'),
      paySign: String(params.paySign),
      success: () => {
        wx.hideLoading();
        // 支付结果以官方 orderquery 为准，前端主动查一次兜底
        this.verifyPaid();
      },
      fail: (err: any) => {
        wx.hideLoading();
        const msg = err && err.errMsg ? err.errMsg : '';
        if (msg.indexOf('cancel') >= 0) {
          this.setData({ view: 'cashier' });
          wx.showToast({ title: '已取消支付', icon: 'none' });
          return;
        }
        this.setData({
          view: 'fail',
          failReason: '调起微信支付失败：' + (msg || '请稍后重试'),
        });
      },
    });
  },

  // 本地 V2 协议网关模拟付款（官方 sandboxnew 已下线，无官方付款触发入口）
  async sandboxPay() {
    if (this.data.busy) return;
    this.setData({ busy: true });
    wx.showLoading({ title: '沙箱付款中', mask: true });
    try {
      const st = await app.request<IPaymentStatus>('/payments/sandbox/pay', {
        method: 'POST',
        data: { out_trade_no: this.data.outTradeNo },
      });
      wx.hideLoading();
      this.setData({ busy: false, status: st.status, tradeState: st.trade_state });
      if (st.status === 'paid') {
        this.setData({ view: 'success' });
        wx.showToast({ title: '支付成功', icon: 'success' });
        setTimeout(() => wx.redirectTo({ url: '/pages/orders/orders' }), 1500);
      } else {
        this.setData({ view: 'paying', failReason: st.trade_state || '' });
      }
    } catch (e: any) {
      wx.hideLoading();
      this.setData({ busy: false });
      wx.showToast({ title: e.message || '沙箱付款失败', icon: 'none' });
    }
  },

  // 主动查询支付结果（V2 沙箱：以 orderquery 返回为准同步订单状态）
  async verifyPaid() {
    wx.showLoading({ title: '查询支付结果', mask: true });
    try {
      await app.request<IPaymentStatus>('/payments/prepay', {
        method: 'POST',
        data: { order_id: this.data.orderId, out_trade_no: this.data.outTradeNo },
      });
      const st = await this.queryStatus();
      wx.hideLoading();
      if (st && st.status === 'paid') {
        this.setData({ view: 'success' });
        wx.showToast({ title: '支付成功', icon: 'success' });
        setTimeout(() => wx.redirectTo({ url: '/pages/orders/orders' }), 1500);
        return;
      }
      this.setData({
        view: 'paying',
        failReason: st && st.trade_state ? '当前状态：' + st.trade_state : '',
      });
      wx.showToast({ title: '暂未查询到支付成功', icon: 'none' });
    } catch (e: any) {
      wx.hideLoading();
      wx.showToast({ title: e.message || '查询失败', icon: 'none' });
    }
  },

  /* ---------------- 本地沙箱：三分支模拟 ---------------- */

  async paySuccess() {
    await this.submitResult('SUCCESS');
  },

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
        this.setData({ view: st.trade_state === 'USERPAYING' ? 'paying' : 'fail' });
      }
    } catch (e: any) {
      this.setData({ busy: false });
      wx.showToast({ title: e.message || '支付失败', icon: 'none' });
    }
  },

  // 支付中状态轮询查询（通用）
  async recheck() {
    const st = await this.queryStatus();
    if (st && st.status === 'paid') {
      this.setData({ view: 'success' });
      setTimeout(() => wx.redirectTo({ url: '/pages/orders/orders' }), 1200);
    } else {
      wx.showToast({ title: '仍未支付完成', icon: 'none' });
    }
  },

  retry() {
    this.setData({ view: 'cashier', failReason: '' });
  },

  later() {
    wx.redirectTo({ url: '/pages/orders/orders' });
  },

  goOrders() {
    wx.redirectTo({ url: '/pages/orders/orders' });
  },
});
