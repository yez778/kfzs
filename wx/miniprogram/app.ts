// app.ts 应用入口：全局数据 + 全局请求函数
// 后端 FastAPI：http://localhost:8000/api/v1（真机预览需改为 HTTPS 域名并在小程序后台配置合法域名）
const API_BASE = 'http://localhost:8000/api/v1';

App<IAppOption>({
  globalData: {
    apiBase: API_BASE,
    token: '',
    userInfo: null,
    localKey: '',
  },

  onLaunch() {
    // 恢复登录态
    this.globalData.token = (wx.getStorageSync('token') as string) || '';
    this.globalData.userInfo = (wx.getStorageSync('user_info') as IUserProfile) || null;
    // 开发者工具无 AppSecret 时：本地 key 记住同一用户（后端 openid = dev:{local_key}）
    const saved = (wx.getStorageSync('local_key') as string) || '';
    if (saved) {
      this.globalData.localKey = saved;
    } else {
      const key = 'dev_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
      this.globalData.localKey = key;
      wx.setStorageSync('local_key', key);
    }
  },

  request<T>(path: string, options: IRequestOptions = {}): Promise<T> {
    const token = this.globalData.token;
    return new Promise<T>((resolve, reject) => {
      wx.request({
        url: this.globalData.apiBase + path,
        method: options.method || 'GET',
        data: options.data,
        header: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: 'Bearer ' + token } : {}),
        },
        success: (res) => {
          if (res.statusCode >= 200 && res.statusCode < 300) {
            resolve(res.data as T);
            return;
          }
          // 401：token 失效，清登录态
          if (res.statusCode === 401) {
            this.clearLogin();
            reject(new Error('登录已失效，请重新登录'));
            return;
          }
          const body = (res.data || {}) as Record<string, any>;
          const detail = body.detail || body.message || `请求失败（${res.statusCode}）`;
          reject(new Error(typeof detail === 'string' ? detail : '请求失败'));
        },
        fail: (err) => {
          reject(new Error('网络错误：' + err.errMsg));
        },
      });
    });
  },

  mediaUrl(url: string): string {
    if (!url) return '';
    if (/^https?:\/\//i.test(url)) return url;
    if (url.startsWith('/api/')) return this.globalData.apiBase + url;
    if (url.startsWith('/uploads/')) return this.globalData.apiBase + url;
    return url;
  },

  isLoggedIn(): boolean {
    return !!this.globalData.token;
  },

  saveLogin(token: string, user: IUserProfile): void {
    this.globalData.token = token;
    this.globalData.userInfo = user;
    wx.setStorageSync('token', token);
    wx.setStorageSync('user_info', user);
  },

  clearLogin(): void {
    this.globalData.token = '';
    this.globalData.userInfo = null;
    wx.removeStorageSync('token');
    wx.removeStorageSync('user_info');
  },
});
