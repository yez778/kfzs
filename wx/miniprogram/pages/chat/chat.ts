// AI 智能客服：与商城后端 /chat 对话（server 集成 agent 客服链路）
// 会话自动复用最近一次（不带 session_id 时后端自动关联）；可手动新建会话。
// 从「会话历史」页进入时通过 storage(pending_session_id) 携带会话 id，onShow 加载历史。
export {};
const app = getApp<IAppOption>();

interface IChatMsg {
  role: 'user' | 'assistant';
  content: string;
  citations?: string[];
  cards?: { title: string; price: number; link?: string; product_id?: string }[];
  needsHuman?: boolean;
}

Page({
  data: {
    messages: [] as IChatMsg[],
    input: '',
    sending: false,
    sessionId: '',
    loading: false,
    scrollTop: 0,
  },

  onLoad() {
    this.pushWelcome();
  },

  onShow() {
    // 从「会话历史」页跳转过来：加载指定会话
    const pending = (wx.getStorageSync('pending_session_id') as string) || '';
    if (pending) {
      wx.removeStorageSync('pending_session_id');
      this.setData({ sessionId: pending });
      this.loadHistory(pending);
    }
  },

  pushWelcome() {
    this.setData({
      messages: [
        {
          role: 'assistant',
          content:
            '你好，我是星途 AI 智能客服 🤖\n可以为你解答：\n· 商品咨询（柱头灯 / 壁灯 / 太阳能庭院灯）\n· 订单进度、物流、发货\n· 退换货政策与售后\n· 支付与优惠问题',
        },
      ],
    });
  },

  // 加载指定会话的完整历史
  async loadHistory(sessionId: string) {
    this.setData({ loading: true });
    try {
      const msgs = (await app.request<any[]>(
        `/sessions/${encodeURIComponent(sessionId)}/messages`
      )) || [];
      const items: IChatMsg[] = [];
      for (const m of msgs) {
        if (m.role !== 'user' && m.role !== 'assistant') continue;
        const cards = (m.product_cards || []).map((c: any) => ({
          ...c,
          product_id: c.link ? c.link.split('id=')[1] : '',
        }));
        items.push({
          role: m.role,
          content: m.content || '',
          citations: m.citations || [],
          cards: cards.length ? cards : undefined,
        });
      }
      this.setData({
        messages: items.length ? items : [{ role: 'assistant', content: '（该会话暂无消息）' }],
        loading: false,
      });
    } catch (e: any) {
      this.setData({
        messages: [{ role: 'assistant', content: '加载会话历史失败：' + (e.message || '请稍后再试') }],
        loading: false,
      });
    }
    this.scrollBottom();
  },

  onInput(e: any) {
    this.setData({ input: e.detail.value });
  },

  onSend() {
    const text = this.data.input.trim();
    if (!text || this.data.sending) return;
    this.setData({
      input: '',
      messages: this.data.messages.concat([{ role: 'user', content: text }]),
      sending: true,
    });
    this.scrollBottom();
    this.requestAnswer(text);
  },

  async requestAnswer(text: string) {
    try {
      const res = await app.request<{
        session_id: string;
        response: string;
        citations?: string[];
        citations_detail?: { title?: string; url?: string }[];
        product_cards?: { title: string; price: number; link?: string }[];
        needs_human?: boolean;
      }>('/chat', {
        method: 'POST',
        data: { session_id: this.data.sessionId || undefined, message: text },
      });
      const cards = (res.product_cards || []).map((c) => ({
        ...c,
        product_id: c.link ? c.link.split('id=')[1] : '',
      }));
      this.setData({
        sessionId: res.session_id || this.data.sessionId,
        messages: this.data.messages.concat([
          {
            role: 'assistant',
            content: res.response,
            citations: res.citations || [],
            cards,
            needsHuman: !!res.needs_human,
          },
        ]),
        sending: false,
      });
    } catch (e: any) {
      this.setData({
        messages: this.data.messages.concat([
          {
            role: 'assistant',
            content: '（抱歉，连接客服服务失败：' + (e.message || '请稍后再试）'),
          },
        ]),
        sending: false,
      });
    }
    this.scrollBottom();
  },

  // 新建会话
  async newSession() {
    if (this.data.sending) return;
    if (!app.isLoggedIn()) {
      wx.showToast({ title: '请先登录', icon: 'none' });
      setTimeout(() => wx.switchTab({ url: '/pages/mine/mine' }), 600);
      return;
    }
    try {
      const session = await app.request<{ id: string }>('/sessions', { method: 'POST' });
      this.setData({ sessionId: session.id });
    } catch {
      this.setData({ sessionId: '' });
    }
    this.pushWelcome();
    this.scrollBottom();
  },

  // 打开会话历史页
  goHistory() {
    wx.navigateTo({ url: '/pages/history/history' });
  },

  onCardTap(e: any) {
    const id = e.currentTarget.dataset.id;
    if (id) wx.navigateTo({ url: '/pages/detail/detail?id=' + encodeURIComponent(id) });
  },

  scrollBottom() {
    this.setData({ scrollTop: 99999 });
  },

  goLogin() {
    wx.switchTab({ url: '/pages/mine/mine' });
  },
});
