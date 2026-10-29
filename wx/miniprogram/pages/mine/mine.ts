export {};
// 我的：微信登录、退出、钱包展示、快捷入口
const app = getApp<IAppOption>();

Page({
  data: {
    logged: false,
    user: null as IUserProfile | null,
    logging: false,
    avatarUrl: '',
  },

  onShow() {
    this.refresh();
  },

  refresh() {
    const logged = app.isLoggedIn();
    this.setData({ logged });
    if (logged) {
      this.loadProfile();
    } else {
      this.setData({ user: null });
    }
  },

  async loadProfile() {
    try {
      const me = await app.request<IUserProfile>('/auth/me');
      this.setData({
        user: me,
        avatarUrl: me.avatar_url ? app.mediaUrl(me.avatar_url) : '',
      });
    } catch (e: any) {
      // token 失效等情况已在 request 里清登录态
      this.refresh();
    }
  },

  // 微信登录：wx.login 拿 code；开发者工具无 AppSecret 时后端用 local_key 兜底
  async wxLogin() {
    if (this.data.logging) return;
    this.setData({ logging: true });
    try {
      // 先尝试获取用户资料（授权可跳过）
      let nickName = '';
      let avatarUrl = '';
      try {
        const profile = await new Promise<{ nickName: string; avatarUrl: string }>((resolve, reject) => {
          wx.getUserProfile({
            desc: '用于完善会员资料',
            success: (res) => resolve({ nickName: res.userInfo.nickName, avatarUrl: res.userInfo.avatarUrl }),
            fail: reject,
          });
        });
        nickName = profile.nickName;
        avatarUrl = profile.avatarUrl;
      } catch {
        // 用户拒绝授权：仍可用 wx.login 静默登录
      }

      const code = await new Promise<string>((resolve, reject) => {
        wx.login({ success: (res) => resolve(res.code), fail: reject });
      });

      const data = await app.request<{ access_token: string; role: string; username: string }>(
        '/auth/wechat',
        {
          method: 'POST',
          data: {
            code,
            local_key: app.globalData.localKey,
            username: nickName || '',
            avatar_url: avatarUrl || '',
          },
        }
      );
      app.saveLogin(data.access_token, {
        id: 0,
        username: data.username,
        role: data.role,
        avatar_url: avatarUrl || '',
        wallet_balance: 0,
        login_type: 'wechat',
      });
      wx.showToast({ title: '登录成功', icon: 'success' });
      this.loadProfile();
      this.setData({ logged: true, avatarUrl: avatarUrl ? app.mediaUrl(avatarUrl) : '' });
    } catch (e: any) {
      wx.showToast({ title: e.message || '登录失败', icon: 'none' });
    } finally {
      this.setData({ logging: false });
    }
  },

  logout() {
    wx.showModal({
      title: '退出登录',
      content: '确定退出当前账号吗？',
      success: (res) => {
        if (res.confirm) {
          app.clearLogin();
          this.setData({ logged: false, user: null, avatarUrl: '' });
          wx.showToast({ title: '已退出', icon: 'none' });
        }
      },
    });
  },

  goChat() {
    wx.switchTab({ url: '/pages/chat/chat' });
  },

  goOrders() {
    wx.switchTab({ url: '/pages/orders/orders' });
  },

  goCart() {
    wx.switchTab({ url: '/pages/cart/cart' });
  },

  goHome() {
    wx.switchTab({ url: '/pages/index/index' });
  },

  copyBackend() {
    wx.setClipboardData({ data: app.globalData.apiBase });
  },
});
