/* 星途户外照明 · 商城管理后台（Vue 3，零构建）
 * 对接 FastAPI：/api/v1/auth/login、/api/v1/admin/products、/api/v1/shop/products/{id}
 * 订单：/api/v1/admin/orders、/api/v1/admin/orders/{id}/ship|refund、/api/v1/shipping/companies
 */
const { createApp, reactive, ref, computed, onMounted } = Vue;

// 兜底分类（接口未登录也可访问，拉取失败时使用）
const FALLBACK_CATEGORIES = [
  { code: 'post', name: '柱头灯' },
  { code: 'wall', name: '户外壁灯' },
  { code: 'solar', name: '太阳能庭院灯' },
];

// 订单状态中文
const ORDER_STATUS = {
  unpaid: '待支付',
  paid: '待发货',
  shipped: '待收货',
  completed: '已完成',
  refunded: '已退款',
  cancelled: '已取消',
};

createApp({
  setup() {
    /* ---------- 全局状态 ---------- */
    const token = ref(localStorage.getItem('admin_token') || '');
    const username = ref(localStorage.getItem('admin_username') || '');
    const role = ref(localStorage.getItem('admin_role') || '');
    const apiBase = ref(localStorage.getItem('admin_api_base') || 'http://localhost:8000');
    const activeTab = ref(localStorage.getItem('admin_tab') || 'products');

    const loginForm = reactive({ username: 'admin', password: '' });
    const logging = ref(false);
    const loginError = ref('');

    const toastMsg = ref('');
    const toastType = ref('ok');
    let toastTimer = null;

    /* ---------- 商品 ---------- */
    const products = ref([]);
    const categories = ref(FALLBACK_CATEGORIES);
    const loading = ref(false);
    const keyword = ref('');
    const statusFilter = ref('');
    const categoryFilter = ref('');
    const curPage = ref(1);
    const pageSize = 8;

    /* ---------- 订单 ---------- */
    const orders = ref([]);
    const ordersLoading = ref(false);
    const orderStatusFilter = ref('');
    const orderKeyword = ref('');
    const curOrderPage = ref(1);
    const orderPageSize = 10;
    const orderStatusMap = ORDER_STATUS;
    const shippingCompanies = ref([{ code: 'SF', name: '顺丰速运' }]);

    const dialog = reactive({ show: false, mode: 'create', saving: false, error: '', form: emptyForm() });
    const confirm = reactive({ show: false, target: null, busy: false });
    const shipDialog = reactive({ show: false, busy: false, error: '', order: null, companyCode: 'SF', logisticsCode: '' });
    const refundDialog = reactive({ show: false, busy: false, error: '', order: null, reason: '' });

    function emptyForm() {
      return {
        product_id: '', title: '', subtitle: '', category_code: 'post', price: 0,
        original_price: 0, sales_count: 0, cover: '', description: '', status: 'on_sale',
        tags: [], skus: [{ spec: '默认规格', price: 0, stock: 50, threshold: 5 }],
      };
    }

    /* ---------- 基础请求 ---------- */
    function saveSettings() {
      localStorage.setItem('admin_api_base', apiBase.value);
    }

    function showToast(msg, type = 'ok') {
      toastMsg.value = msg;
      toastType.value = type;
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => { toastMsg.value = ''; }, 2600);
    }

    async function api(path, options = {}) {
      const opts = Object.assign({ headers: {} }, options);
      opts.headers = Object.assign(
        { 'Content-Type': 'application/json' },
        token.value ? { Authorization: 'Bearer ' + token.value } : {},
        opts.headers || {}
      );
      let res;
      try {
        res = await fetch(apiBase.value + path, opts);
      } catch (e) {
        throw new Error('无法连接后端：' + apiBase.value + '（请确认 FastAPI 已启动）');
      }
      let data = null;
      const text = await res.text();
      if (text) {
        try { data = JSON.parse(text); } catch { data = { detail: text }; }
      }
      if (!res.ok) {
        if (res.status === 401) {
          logout(false);
          throw new Error('登录已失效，请重新登录');
        }
        const detail = (data && (data.detail || data.message)) || ('请求失败（' + res.status + '）');
        throw new Error(typeof detail === 'string' ? detail : '请求失败');
      }
      return data;
    }

    /* ---------- 登录 / 退出 ---------- */
    async function login() {
      loginError.value = '';
      if (!loginForm.username || !loginForm.password) {
        loginError.value = '请输入账号和密码';
        return;
      }
      logging.value = true;
      try {
        saveSettings();
        const data = await api('/api/v1/auth/login', {
          method: 'POST',
          body: JSON.stringify({ username: loginForm.username, password: loginForm.password }),
        });
        if (!['staff', 'admin'].includes(data.role)) {
          loginError.value = '该账号不是员工/管理员，无权管理';
          return;
        }
        token.value = data.access_token;
        username.value = data.username || loginForm.username;
        role.value = data.role;
        localStorage.setItem('admin_token', token.value);
        localStorage.setItem('admin_username', username.value);
        localStorage.setItem('admin_role', role.value);
        await bootAfterLogin();
      } catch (e) {
        loginError.value = e.message;
      } finally {
        logging.value = false;
      }
    }

    function logout(show = true) {
      token.value = '';
      username.value = '';
      role.value = '';
      localStorage.removeItem('admin_token');
      localStorage.removeItem('admin_username');
      localStorage.removeItem('admin_role');
      if (show) showToast('已退出登录');
    }

    function switchTab(tab) {
      activeTab.value = tab;
      localStorage.setItem('admin_tab', tab);
      if (tab === 'orders' && !orders.value.length) loadOrders();
    }

    /* ---------- 商品数据 ---------- */
    async function loadCategories() {
      try {
        const data = await api('/api/v1/shop/categories');
        if (Array.isArray(data) && data.length) {
          categories.value = data.map((c) => ({ code: c.code, name: c.name }));
        }
      } catch { /* 用兜底分类 */ }
    }

    async function loadProducts() {
      loading.value = true;
      try {
        products.value = await api('/api/v1/admin/products');
      } catch (e) {
        showToast(e.message, 'err');
      } finally {
        loading.value = false;
      }
    }

    async function bootAfterLogin() {
      await Promise.all([loadCategories(), loadProducts(), loadOrders(), loadShippingCompanies()]);
    }

    /* ---------- 订单数据 ---------- */
    async function loadOrders() {
      ordersLoading.value = true;
      try {
        orders.value = await api('/api/v1/admin/orders');
      } catch (e) {
        showToast(e.message, 'err');
      } finally {
        ordersLoading.value = false;
      }
    }

    async function loadShippingCompanies() {
      try {
        const data = await api('/api/v1/shipping/companies');
        if (Array.isArray(data) && data.length) shippingCompanies.value = data;
      } catch { /* 默认顺丰 */ }
    }

    const filteredOrders = computed(() => {
      const kw = orderKeyword.value.trim().toLowerCase();
      let list = orders.value;
      if (orderStatusFilter.value) {
        list = list.filter((o) => o.status === orderStatusFilter.value);
      }
      if (kw) {
        list = list.filter((o) =>
          [o.order_id, o.customer, o.product].join(' ').toLowerCase().includes(kw)
        );
      }
      return list;
    });
    const orderTotalPages = computed(() => Math.max(1, Math.ceil(filteredOrders.value.length / orderPageSize)));
    const pagedOrders = computed(() => {
      const start = (curOrderPage.value - 1) * orderPageSize;
      return filteredOrders.value.slice(start, start + orderPageSize);
    });
    function countOrders(status) {
      return orders.value.filter((o) => o.status === status).length;
    }
    function orderBadgeClass(status) {
      return {
        unpaid: 'badge-warn', paid: 'badge-blue', shipped: 'badge-green',
        completed: 'badge-gray', refunded: 'badge-red', cancelled: 'badge-gray',
      }[status] || 'badge-gray';
    }

    /* ---------- 发货 / 退款 ---------- */
    function openShip(order) {
      Object.assign(shipDialog, { show: true, busy: false, error: '', order, companyCode: 'SF', logisticsCode: '' });
    }
    async function doShip() {
      const code = shipDialog.logisticsCode.trim();
      if (!code) { shipDialog.error = '请填写物流单号'; return; }
      shipDialog.busy = true;
      try {
        await api('/api/v1/admin/orders/' + encodeURIComponent(shipDialog.order.order_id) + '/ship', {
          method: 'POST',
          body: JSON.stringify({ company_code: shipDialog.companyCode, logistics_code: code }),
        });
        shipDialog.show = false;
        showToast('发货成功：' + shipDialog.order.order_id);
        loadOrders();
      } catch (e) {
        shipDialog.error = e.message;
      } finally {
        shipDialog.busy = false;
      }
    }

    function openRefund(order) {
      Object.assign(refundDialog, { show: true, busy: false, error: '', order, reason: '' });
    }
    async function doRefund() {
      refundDialog.busy = true;
      try {
        await api('/api/v1/admin/orders/' + encodeURIComponent(refundDialog.order.order_id) + '/refund', {
          method: 'POST',
          body: JSON.stringify({ reason: refundDialog.reason || '顾客申请' }),
        });
        refundDialog.show = false;
        showToast('退款成功，库存已回补');
        loadOrders();
      } catch (e) {
        refundDialog.error = e.message;
      } finally {
        refundDialog.busy = false;
      }
    }

    /* ---------- 商品筛选 / 分页 ---------- */
    const filtered = computed(() => {
      const kw = keyword.value.trim().toLowerCase();
      return products.value.filter((p) => {
        if (statusFilter.value && p.status !== statusFilter.value) return false;
        if (categoryFilter.value && p.category_code !== categoryFilter.value) return false;
        if (kw) {
          const hay = [p.title, p.subtitle, p.product_id, p.category, (p.tags || []).join(' ')]
            .join(' ').toLowerCase();
          if (!hay.includes(kw)) return false;
        }
        return true;
      });
    });
    const totalPages = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize)));
    const paged = computed(() => {
      const start = (curPage.value - 1) * pageSize;
      return filtered.value.slice(start, start + pageSize);
    });
    function countByStatus(s) {
      return products.value.filter((p) => p.status === s).length;
    }

    /* ---------- 封面 URL ---------- */
    function mediaUrl(u) {
      if (!u) return '';
      if (/^https?:\/\//i.test(u)) return u;
      if (u.startsWith('/api/')) return apiBase.value + u;
      if (u.startsWith('/uploads/')) return apiBase.value + u;
      return u;
    }
    function coverUrl(p) { return mediaUrl(p && p.cover); }
    const dialogCoverUrl = computed(() => mediaUrl(dialog.form.cover));
    function onImgError(e) { e.target.style.display = 'none'; }

    /* ---------- 商品新增 / 编辑 ---------- */
    function onCategoryChange() {
      const cat = categories.value.find((c) => c.code === dialog.form.category_code);
      dialog.form._categoryName = cat ? cat.name : '';
    }
    function addSku() {
      dialog.form.skus.push({ spec: '', price: Number(dialog.form.price) || 0, stock: 50, threshold: 5 });
    }
    function openCreate() {
      Object.assign(dialog, { show: true, mode: 'create', saving: false, error: '' });
      dialog.form = emptyForm();
    }
    async function openEdit(p) {
      Object.assign(dialog, { show: true, mode: 'edit', saving: false, error: '' });
      dialog.form = Object.assign(emptyForm(), {
        product_id: p.product_id, title: p.title, subtitle: p.subtitle || '',
        category_code: p.category_code || 'post', price: p.price, original_price: p.original_price || p.price,
        sales_count: p.sales_count || 0, cover: p.cover || '', description: p.description || '',
        status: p.status || 'on_sale', tags: Array.isArray(p.tags) ? [...p.tags] : [], skus: [],
      });
      try {
        const detail = await api('/api/v1/shop/products/' + encodeURIComponent(p.product_id));
        dialog.form.skus = (detail.skus || []).map((s) => ({
          spec: s.spec || '', price: Number(s.price), stock: Number(s.stock || 0), threshold: Number(s.threshold || 0),
        }));
        if (!dialog.form.description && detail.description) dialog.form.description = detail.description;
        if (!dialog.form.tags.length && Array.isArray(detail.tags)) dialog.form.tags = [...detail.tags];
      } catch {
        dialog.form.skus = [{ spec: '默认规格', price: Number(p.price), stock: 0, threshold: 5 }];
      }
    }
    function closeDialog() { dialog.show = false; }

    async function uploadCover(e) {
      const file = e.target.files && e.target.files[0];
      if (!file) return;
      if (file.size > 5 * 1024 * 1024) { dialog.error = '图片不能超过 5MB'; return; }
      const fd = new FormData();
      fd.append('file', file);
      dialog.error = '';
      try {
        const data = await api('/api/v1/admin/products/cover', { method: 'POST', body: fd });
        if (data && data.cover) {
          dialog.form.cover = data.cover;
          showToast('封面已上传');
        }
      } catch (err) {
        dialog.error = err.message;
      } finally {
        e.target.value = '';
      }
    }

    function validateForm(f) {
      if (!f.title) return '请填写商品标题';
      if (!(Number(f.price) >= 0)) return '请填写正确的售价';
      if (f.original_price && Number(f.original_price) < Number(f.price)) return '划线价不能低于售价';
      return '';
    }

    async function saveProduct() {
      const f = dialog.form;
      dialog.error = validateForm(f);
      if (dialog.error) return;
      dialog.saving = true;
      try {
        if (dialog.mode === 'create') {
          const skus = f.skus.filter((s) => s.spec || s.price >= 0).map((s, i) => ({
            sku_id: 'SKU-NEW-' + Date.now() + '-' + i,
            spec: s.spec || '默认规格', price: Number(s.price),
            stock: Math.max(0, Number(s.stock) || 0), threshold: Math.max(0, Number(s.threshold) || 0),
          }));
          const body = {
            title: f.title, subtitle: f.subtitle,
            category: f._categoryName || categories.value.find((c) => c.code === f.category_code)?.name || '柱头灯',
            category_code: f.category_code, price: Number(f.price),
            original_price: Number(f.original_price || f.price),
            sales_count: Math.max(0, Number(f.sales_count) || 0),
            cover: f.cover, description: f.description, tags: f.tags, status: f.status,
            gallery: f.cover ? [f.cover] : [], skus,
          };
          await api('/api/v1/admin/products', { method: 'POST', body: JSON.stringify(body) });
          showToast('商品已创建');
        } else {
          const body = {
            title: f.title, subtitle: f.subtitle,
            category: categories.value.find((c) => c.code === f.category_code)?.name || '',
            category_code: f.category_code, price: Number(f.price),
            original_price: Number(f.original_price || f.price),
            cover: f.cover, description: f.description, status: f.status,
            gallery: f.cover ? [f.cover] : [],
          };
          await api('/api/v1/admin/products/' + encodeURIComponent(f.product_id), {
            method: 'PUT', body: JSON.stringify(body),
          });
          showToast('商品已保存');
        }
        dialog.show = false;
        await loadProducts();
      } catch (e) {
        dialog.error = e.message;
      } finally {
        dialog.saving = false;
      }
    }

    /* ---------- 上下架 / 删除 ---------- */
    async function toggleStatus(p) {
      const next = p.status === 'on_sale' ? 'off_shelf' : 'on_sale';
      try {
        await api('/api/v1/admin/products/' + encodeURIComponent(p.product_id) + '/status', {
          method: 'POST', body: JSON.stringify({ status: next }),
        });
        p.status = next;
        showToast('已' + (next === 'on_sale' ? '上架' : '下架') + '：' + p.title);
      } catch (e) {
        showToast(e.message, 'err');
      }
    }
    function askDelete(p) {
      confirm.target = p;
      confirm.busy = false;
      confirm.show = true;
    }
    async function doDelete() {
      const p = confirm.target;
      if (!p) return;
      confirm.busy = true;
      try {
        await api('/api/v1/admin/products/' + encodeURIComponent(p.product_id), { method: 'DELETE' });
        confirm.show = false;
        showToast('商品已删除');
        await loadProducts();
      } catch (e) {
        showToast(e.message, 'err');
      } finally {
        confirm.busy = false;
      }
    }

    /* ---------- 工具 ---------- */
    function fmt(n) {
      return (Number(n) || 0).toFixed(2);
    }

    onMounted(() => {
      if (token.value) bootAfterLogin();
    });

    return {
      // auth / tab
      token, username, role, apiBase, loginForm, logging, loginError,
      login, logout, saveSettings, activeTab, switchTab,
      // 商品
      products, categories, loading, keyword, statusFilter, categoryFilter,
      curPage, pageSize, filtered, paged, totalPages, countByStatus, loadProducts,
      coverUrl, dialogCoverUrl, onImgError,
      dialog, openCreate, openEdit, closeDialog, saveProduct, addSku, onCategoryChange, uploadCover,
      toggleStatus, askDelete, doDelete, confirm,
      // 订单
      orders, ordersLoading, orderStatusFilter, orderKeyword, curOrderPage,
      filteredOrders, pagedOrders, orderTotalPages, countOrders, orderStatusMap,
      orderBadgeClass, loadOrders, openShip, doShip, shipDialog,
      openRefund, doRefund, refundDialog, shippingCompanies,
      // misc
      fmt, toastMsg, toastType,
    };
  },
}).mount('#app');
