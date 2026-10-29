// 微信小程序 wx.* API 精简类型声明
// 覆盖本工程用到的 API；完整声明请参考 miniprogram-api-typings（npm i 后由 package.json devDependencies 提供）
declare namespace wx {
  interface RequestSuccessCallbackResult<T = any> {
    data: T;
    statusCode: number;
    header: Record<string, string>;
  }
  interface RequestFailCallbackResult {
    errMsg: string;
  }
  interface RequestOption<T = any> {
    url: string;
    method?: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH' | 'OPTIONS' | 'HEAD';
    data?: any;
    header?: Record<string, string>;
    timeout?: number;
    success?: (res: RequestSuccessCallbackResult<T>) => void;
    fail?: (err: RequestFailCallbackResult) => void;
    complete?: (res: any) => void;
  }
  function request<T = any>(option: RequestOption<T>): void;

  interface LoginSuccessCallbackResult {
    code: string;
    errMsg: string;
  }
  function login(options: { success?: (res: LoginSuccessCallbackResult) => void; fail?: (err: any) => void }): void;

  interface GetUserProfileSuccessResult {
    userInfo: {
      nickName: string;
      avatarUrl: string;
      gender?: number;
    };
  }
  function getUserProfile(options: {
    desc: string;
    success?: (res: GetUserProfileSuccessResult) => void;
    fail?: (err: any) => void;
  }): void;

  function showToast(options: {
    title: string;
    icon?: 'success' | 'error' | 'loading' | 'none';
    duration?: number;
    mask?: boolean;
  }): void;
  function showLoading(options: { title: string; mask?: boolean }): void;
  function hideLoading(): void;
  function showModal(options: {
    title: string;
    content: string;
    showCancel?: boolean;
    confirmText?: string;
    confirmColor?: string;
    success?: (res: { confirm: boolean; cancel: boolean }) => void;
  }): void;
  function showActionSheet(options: {
    itemList: string[];
    success?: (res: { tapIndex: number }) => void;
  }): void;

  function navigateTo(options: { url: string; events?: any; success?: () => void; fail?: (err: any) => void }): void;
  function redirectTo(options: { url: string }): void;
  function switchTab(options: { url: string }): void;
  function navigateBack(options?: { delta?: number }): void;
  function reLaunch(options: { url: string }): void;

  function setStorageSync(key: string, data: any): void;
  function getStorageSync(key: string): any;
  function removeStorageSync(key: string): void;
  function clearStorageSync(): void;

  function previewImage(options: { current?: string; urls: string[] }): void;

  function startPullDownRefresh(): void;
  function stopPullDownRefresh(): void;

  function requestPayment(options: {
    timeStamp: string;
    nonceStr: string;
    package: string;
    signType: string;
    paySign: string;
    success?: () => void;
    fail?: (err: any) => void;
  }): void;

  function setNavigationBarTitle(options: { title: string }): void;

  function setClipboardData(options: { data: string; success?: () => void; fail?: (err: any) => void }): void;
  function getClipboardData(options: {
    success?: (res: { data: string }) => void;
    fail?: (err: any) => void;
  }): void;
}

declare function App<T = any>(options: T): void;
declare function getApp<T = any>(): T;
declare function Page<TData = any, TCustom = any>(options: any): void;
declare function Component(options: any): void;
