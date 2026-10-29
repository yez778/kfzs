// 客服会话历史：列出历史会话（标题/最后消息/时间），支持删除；点击进入 chat 页查看完整对话
export {};
const app = getApp<IAppOption>();

interface ISessionItem {
  id: string;
  title: string;
  created_at: string;
  handoff_status: string;
}

interface IHistoryItem extends ISessionItem {
  last: string;
  msgCount: number;
  timeText: string;
}

Page({
  data: {
    items: [] as IHistoryItem[],
    loading: false,
  },

  onShow() {
    if (!app.isLoggedIn()) {
      this.setData({ items: [] });
      wx.showToast({ title: '请先登录', icon: 'none' });
      return;
    }
    this.loadSessions();
  },

  async loadSessions() {
    this.setData({ loading: true });
    try {
      const list = (await app.request<ISessionItem[]>('/sessions')) || [];
      // 并行取每个会话的最后一条消息作为摘要
      const withMeta = await Promise.all(
        list.map(async (s) => {
          let last = '';
          let msgCount = 0;
          try {
            const msgs = await app.request<any[]>(`/sessions/${encodeURIComponent(s.id)}/messages`);
            if (Array.isArray(msgs)) {
              msgCount = msgs.length;
              const tail = msgs[msgs.length - 1];
              if (tail && tail.content) last = tail.content;
            }
          } catch {
            // 单个会话读取失败不影响列表
          }
          return {
            ...s,
            last,
            msgCount,
            timeText: this.formatTime(s.created_at),
          } as IHistoryItem;
        })
      );
      this.setData({ items: withMeta });
    } catch (e: any) {
      wx.showToast({ title: e.message || '加载失败', icon: 'none' });
    } finally {
      this.setData({ loading: false });
    }
  },

  onItemTap(e: any) {
    const id = e.currentTarget.dataset.id;
    // chat 是 tabBar 页：switchTab 无法传参，用 storage 中转会话 id
    wx.setStorageSync('pending_session_id', id);
    wx.switchTab({ url: '/pages/chat/chat' });
  },

  onDelete(e: any) {
    const id = e.currentTarget.dataset.id;
    const item = this.data.items.find((it) => it.id === id);
    wx.showModal({
      title: '删除会话',
      content: '确定删除会话「' + (item ? item.title : '') + '」及其全部消息吗？',
      success: async (res) => {
        if (!res.confirm) return;
        try {
          await app.request(`/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' });
          wx.showToast({ title: '已删除', icon: 'success' });
          this.loadSessions();
        } catch (e2: any) {
          wx.showToast({ title: e2.message || '删除失败', icon: 'none' });
        }
      },
    });
  },

  newSession() {
    // 新建会话：清掉待加载历史，直接切到聊天 tab
    wx.removeStorageSync('pending_session_id');
    wx.switchTab({ url: '/pages/chat/chat' });
  },

  goChat() {
    wx.switchTab({ url: '/pages/chat/chat' });
  },

  formatTime(iso: string): string {
    if (!iso) return '';
    const d = new Date(iso.replace('T', ' ').replace(/-/g, '/').slice(0, 19));
    if (isNaN(d.getTime())) return '';
    const now = new Date();
    const pad = (n: number) => (n < 10 ? '0' + n : '' + n);
    if (d.toDateString() === now.toDateString()) {
      return '今天 ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
    }
    return d.getMonth() + 1 + '月' + d.getDate() + '日 ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  },
});
