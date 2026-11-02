// 售后申请：选择售后类型 + 填写原因 → 生成预览 → 确认提交（转人工审批）
// 对接 server：POST /aftersales/preview、POST /aftersales/confirm、GET /aftersales/previews
export {};
const app = getApp<IAppOption>();

const ACTIONS = [
  { code: 'refund_only', name: '仅退款', desc: '未收到货 / 协商退款' },
  { code: 'return_refund', name: '退货退款', desc: '收到货但不想要 / 有质量问题' },
  { code: 'exchange', name: '换货', desc: '质量问题需更换同款' },
];

interface IPreviewRecord {
  id: string;
  order_id: string;
  action: string;
  reason: string;
  amount: number;
  status: string;
  created_at: string;
}

Page({
  data: {
    orderId: '',
    product: '',
    amount: 0,
    actions: ACTIONS,
    actionIndex: 0,
    reason: '',
    submitting: false,
    records: [] as IPreviewRecord[],
    statusText: {
      pending: '待确认',
      submitted: '已提交（待商家审核）',
      expired: '已过期',
    } as Record<string, string>,
    actionText: {
      refund_only: '仅退款',
      return_refund: '退货退款',
      exchange: '换货',
    } as Record<string, string>,
  },

  onLoad(options: any) {
    this.setData({
      orderId: (options && options.order_id) || '',
      product: (options && decodeURIComponent(options.product || '')) || '',
      amount: Number(options && options.amount) || 0,
    });
  },

  onShow() {
    if (app.isLoggedIn()) this.loadRecords();
  },

  async loadRecords() {
    try {
      const list = (await app.request<IPreviewRecord[]>('/aftersales/previews')) || [];
      this.setData({ records: list.slice().reverse().slice(0, 10) });
    } catch {
      // 记录加载失败不影响申请
    }
  },

  onActionTap(e: any) {
    this.setData({ actionIndex: Number(e.currentTarget.dataset.index) });
  },

  onReasonInput(e: any) {
    this.setData({ reason: e.detail.value });
  },

  // 快速选择常见原因
  onQuickReason(e: any) {
    this.setData({ reason: e.currentTarget.dataset.text });
  },

  // 生成 8-128 位幂等键
  genKey(): string {
    return 'as-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 12);
  },

  async submit() {
    if (this.data.submitting) return;
    if (!app.isLoggedIn()) {
      wx.showToast({ title: '请先登录', icon: 'none' });
      return;
    }
    if (!this.data.orderId) {
      wx.showToast({ title: '缺少订单信息', icon: 'none' });
      return;
    }
    const reason = this.data.reason.trim();
    if (reason.length < 2) {
      wx.showToast({ title: '请填写售后原因（至少 2 个字）', icon: 'none' });
      return;
    }
    const action = ACTIONS[this.data.actionIndex].code;

    this.setData({ submitting: true });
    try {
      // 1. 生成售后预览（后端校验订单 + 计算退款金额）
      const preview = await app.request<{
        preview_id: string;
        amount: number;
        requires_confirmation: boolean;
      }>('/aftersales/preview', {
        method: 'POST',
        data: { order_id: this.data.orderId, action, reason },
      });
      // 2. 让用户确认（金额/类型/原因）
      const confirmed = await new Promise<boolean>((resolve) => {
        wx.showModal({
          title: '确认售后申请',
          content:
            '订单：' +
            this.data.orderId +
            '\n类型：' +
            ACTIONS[this.data.actionIndex].name +
            '\n金额：¥' +
            preview.amount +
            '\n原因：' +
            reason,
          confirmText: '确认提交',
          confirmColor: '#ff6a00',
          success: (res) => resolve(!!res.confirm),
          fail: () => resolve(false),
        });
      });
      if (!confirmed) {
        this.setData({ submitting: false });
        return;
      }
      // 3. 提交（幂等键防重复）
      const result = await app.request<{ after_sales_id: string; status: string }>(
        '/aftersales/confirm',
        {
          method: 'POST',
          data: { preview_id: preview.preview_id, idempotency_key: this.genKey() },
        }
      );
      wx.showToast({ title: '已提交售后', icon: 'success' });
      this.setData({ reason: '' });
      await this.loadRecords();
      setTimeout(() => {
        wx.showModal({
          title: '提交成功',
          content:
            '售后单号：' + (result.after_sales_id || '—') + '\n商家会尽快审核，审核通过后 1-3 个工作日退款。',
          showCancel: false,
          success: () => wx.navigateBack(),
        });
      }, 600);
    } catch (e: any) {
      wx.showToast({ title: e.message || '提交失败', icon: 'none' });
    } finally {
      this.setData({ submitting: false });
    }
  },
});
