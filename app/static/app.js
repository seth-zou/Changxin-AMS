(() => {
  const state = {
    user: null,
    menu: [],
    caches: new Map(),
    route: null,
  };

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  function esc(value) {
    if (value === null || value === undefined) return '';
    return String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function toast(message, type = 'success') {
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = message;
    $('#toast-root').appendChild(el);
    setTimeout(() => el.remove(), 3200);
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      headers: options.body ? { 'Content-Type': 'application/json' } : {},
      credentials: 'same-origin',
      ...options,
      body: options.body ? JSON.stringify(options.body) : undefined,
    });
    const text = await response.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch { data = text; }
    if (!response.ok) {
      const detail = typeof data === 'object' && data?.detail ? data.detail : `${response.status} ${response.statusText}`;
      throw new Error(detail);
    }
    return data;
  }

  async function cachedResource(resource, params = {}) {
    const query = new URLSearchParams({limit: 1000, ...params}).toString();
    const key = `${resource}?${query}`;
    if (!state.caches.has(key)) state.caches.set(key, api(`/api/resources/${resource}?${query}`));
    return state.caches.get(key);
  }

  function clearCaches() { state.caches.clear(); }

  function primaryKey(row) {
    return Object.keys(row).find(k => k.endsWith('_KEY')) || 'ID';
  }

  function fmt(value) {
    if (value === null || value === undefined || value === '') return '';
    if (typeof value === 'boolean') return value ? 'Y' : 'N';
    return value;
  }

  function csvValue(value) {
    const s = value === null || value === undefined ? '' : String(value).replace(/"/g, '""');
    return `"${s}"`;
  }

  function exportCsv(filename, rows, columns) {
    if (!rows.length) { toast('沒有可匯出的資料', 'error'); return; }
    const headers = columns || Object.keys(rows[0]);
    const lines = [headers.map(csvValue).join(',')].concat(rows.map(r => headers.map(h => csvValue(r[h])).join(',')));
    const blob = new Blob([`\ufeff${lines.join('\n')}`], {type: 'text/csv;charset=utf-8'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${filename}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function closeModal() { $('#modal-root').innerHTML = ''; }
  function modalError(message) {
    let box = $('#modal-error');
    if (!box) {
      box = document.createElement('div');
      box.id = 'modal-error';
      box.style.cssText = 'margin:0 0 14px;padding:10px 12px;border-radius:6px;background:#fff1f0;color:#a12622;border:1px solid #f5c2c0;';
      const body = $('#modal-root .modal-body');
      if (body) body.prepend(box);
    }
    box.textContent = message;
  }

  function modal(title, bodyHtml, footHtml = '') {
    $('#modal-root').innerHTML = `
      <div class="modal-backdrop">
        <div class="modal">
          <div class="modal-head">
            <div class="modal-title">${esc(title)}</div>
            <button data-close>關閉</button>
          </div>
          <div class="modal-body">${bodyHtml}</div>
          <div class="modal-foot">${footHtml}</div>
        </div>
      </div>`;
    $('[data-close]').addEventListener('click', closeModal);
    return $('#modal-root');
  }

  // ---------------------------------------------------------------------
  // Login / shell
  // ---------------------------------------------------------------------
  function renderLogin() {
    $('#app').innerHTML = `
      <div class="login-page">
        <div class="login-card">
          <div class="login-brand">AMS</div>
          <div class="login-sub">Alarm Management System · 警報管理系統</div>
          <form id="login-form">
            <label>使用者代碼<input name="user_id" autocomplete="username" required /></label>
            <div style="height:12px"></div>
            <label>密碼<input name="password" type="password" autocomplete="current-password" required /></label>
            <div style="height:18px"></div>
            <button class="primary" style="width:100%" type="submit">登入</button>
          </form>
          <div class="login-sub" style="margin-top:18px">Version 3.0.0 · Local prototype</div>
        </div>
      </div>`;
    $('#login-form').addEventListener('submit', async ev => {
      ev.preventDefault();
      const fd = new FormData(ev.target);
      try {
        await api('/api/auth/login', {method: 'POST', body: {user_id: fd.get('user_id'), password: fd.get('password')}});
        state.user = await api('/api/auth/me');
        state.menu = await api('/api/menu');
        clearCaches();
        renderShell();
        navigate(location.hash.replace('#', '') || '/alarm-summary');
      } catch (err) { toast(err.message, 'error'); }
    });
  }

  function renderShell() {
    $('#app').innerHTML = `
      <div class="workspace">
        <aside class="sidebar">
          <div class="brand"><span class="brand-mark"></span><span class="brand-word">AMS 警報管理</span></div>
          <nav class="menu" id="sidebar-menu"></nav>
        </aside>
        <div class="main">
          <header class="topbar">
            <div>
              <div class="page-title" id="page-title">AMS</div>
              <div class="page-code" id="page-code">Alarm Management System</div>
            </div>
            <div class="user-info">
              <span>使用者：${esc(state.user.USER_NAME)}（${esc(state.user.USER_ID)}）</span>
              <span>登入時間：${esc(new Date().toLocaleString('zh-TW', {hour12: false}))}</span>
              <span>Version 3.0.0</span>
              <button id="logout-btn">登出</button>
            </div>
          </header>
          <main class="content" id="page-content"></main>
          <footer class="footer">AMS Restoration Prototype · FastAPI + SQLite · 非生產環境</footer>
        </div>
      </div>`;
    $('#logout-btn').addEventListener('click', async () => {
      await api('/api/auth/logout', {method: 'POST'});
      location.hash = '';
      renderLogin();
    });
    renderSidebar();
  }

  function renderSidebar() {
    const items = state.menu || [];
    const byParent = new Map();
    items.forEach(item => {
      const key = item.PARENT_KEY || null;
      if (!byParent.has(key)) byParent.set(key, []);
      byParent.get(key).push(item);
    });
    const roots = byParent.get(null) || [];
    const html = roots.map(root => {
      const children = byParent.get(root.FUNCTION_KEY) || [];
      const links = children.map(item => item.PATH_NAME ? `<a class="menu-item" data-route="${esc(item.PATH_NAME)}" href="#${esc(item.PATH_NAME)}">${esc(item.FUNCTION_NAME)}</a>` : '').join('');
      return `<div class="menu-section">
        ${root.PATH_NAME ? `<a class="menu-item menu-root" data-route="${esc(root.PATH_NAME)}" href="#${esc(root.PATH_NAME)}">${esc(root.FUNCTION_NAME)}</a>` : `<div class="menu-group">${esc(root.FUNCTION_NAME)}</div>`}
        ${links}
      </div>`;
    }).join('');
    const sidebar = $('#sidebar-menu');
    if (!sidebar) return;
    sidebar.innerHTML = html;
  }

  const REF_LABELS = {
    FACTORY_KEY: '廠別', SUB_SYS_KEY: '子系統', EQP_KEY: '機台', EVENT_KEY: '通知事件',
    EVENT_GROUP_KEY: '事件通知人員群組', USER_KEY: '使用者', ALARM_INFO_KEY: '警報代碼',
  };

  const ROUTE_TITLES = {
    '/event-groups': ['事件通知人員群組設定', 'AVMA006'],
    '/events': ['事件通知設定', 'AVMA007'],
    '/equipment-group-members': ['機台群組與機台對應設定', 'SBRM_EQP_GROUP_EQP'],
    '/user-group-members': ['群組使用者對應設定', 'SBRM_USER_GROUP_USER'],
    '/factory-sub-systems': ['廠別子系統對應設定', 'AVMA004'],
    '/equipment-type-status-map': ['特定機台區域特定機況不發警報設定', 'CVMA011'],
    '/chamber-alarm-mapping': ['子機台與警報對應設定', 'CBRM_CHAMBER_ALARM_MAPPING'],
    '/alarm-conditions': ['警報觸發條件設定', 'AVMA010'],
  };

  function setActiveRoute(route) {
    $$('#sidebar-menu .menu-item').forEach(a => a.classList.toggle('active', a.dataset.route === route));
    const page = findMenuPage(route);
    const fallback = ROUTE_TITLES[route];
    $('#page-title').textContent = page?.FUNCTION_NAME || fallback?.[0] || route;
    $('#page-code').textContent = page?.FUNCTION_DESC && /^[A-Z0-9_]+$/.test(page.FUNCTION_DESC) ? page.FUNCTION_DESC : (fallback?.[1] || page?.FUNCTION_DESC || '');
  }

  function findMenuPage(route) {
    return (state.menu || []).find(item => item.PATH_NAME === route);
  }

  function navigate(route) {
    if (!route || route === '/') route = '/alarm-summary';
    state.route = route;
    setActiveRoute(route);
    renderRoute(route);
  }

  window.addEventListener('hashchange', () => {
    if (state.user) navigate(location.hash.replace('#', '') || '/alarm-summary');
  });

  async function renderRoute(route) {
    const content = $('#page-content');
    content.innerHTML = `<div class="panel"><div class="panel-body"><div class="empty">載入中…</div></div></div>`;
    try {
      const page = await api(`/api/pages${route}`);
      if (page.kind === 'mapping') return renderMappingPage(page);
      if (page.kind === 'master-detail') return renderMasterDetailPage(page);
      if (page.kind === 'service-config') return renderServiceConfigPage(page);
      if (page.kind === 'custom') {
        const custom = CUSTOM_ROUTES[route];
        if (!custom) throw new Error(`找不到頁面 ${route}`);
        return await custom();
      }
      return renderNormalPage(page);
    } catch (err) {
      content.innerHTML = `<div class="panel"><div class="panel-body"><div class="empty">${esc(err.message)}</div></div></div>`;
    }
  }

  // ---------------------------------------------------------------------
  // Generic normal pages
  // ---------------------------------------------------------------------
  async function loadReferenceChoices(form = []) {
    const resources = new Set(form.filter(f => f.type === 'reference').map(f => f.resource));
    const map = {};
    for (const resource of resources) map[resource] = await cachedResource(resource);
    return map;
  }

  function renderNormalRows(page, rows, choices = {}, selectedKey = '') {
    const columns = page.columns || Object.keys(rows[0] || {}).filter(k => !k.endsWith('_KEY'));
    if (!rows.length) return '<div class="empty">沒有資料</div>';
    const heads = columns.map(c => `<th>${esc((page.fields || []).find(f => f.name === c)?.label || REF_LABELS[c] || c)}</th>`).join('');
    const body = rows.map(row => {
      const key = row[primaryKey(row)];
      const tds = columns.map(col => {
        let value = row[col];
        const ref = (page.form || []).find(f => f.name === col && f.type === 'reference');
        if (ref && value && choices[ref.resource]) {
          const match = choices[ref.resource].find(r => r[primaryKey(r)] === value);
          if (match) value = match[ref.display] || value;
        }
        if (col === 'STATUS') value = `<span class="badge ${esc(value)}">${esc(value)}</span>`;
        if (col === 'DEVICE_STATUS') value = `<span class="badge ${esc(value)}">${esc(value)}</span>`;
        return `<td>${esc(value)}</td>`;
      }).join('');
      return `<tr class="clickable ${key === selectedKey ? 'selected' : ''}" data-key="${esc(key)}"><td>${tds}</td></tr>`;
    }).join('');
    return `<table class="grid"><thead><tr>${heads}</tr></thead><tbody>${body}</tbody></table>`;
  }

  async function renderNormalPage(page) {
    const content = $('#page-content');
    content.innerHTML = `
      <div class="panel">
        <div class="panel-head">
          <div class="panel-title">${esc(page.title)}（${esc(page.code)}）</div>
          <div class="toolbar">
            <button data-action="add">新增</button>
            <button data-action="copy">複製</button>
            <button data-action="modify">修改</button>
            <button data-action="hide">隱藏</button>
            <button data-action="show">取消隱藏</button>
            <button data-action="refresh">重新整理</button>
            <button data-action="export">匯出</button>
            <button data-action="logs">履歷</button>
            <div class="spacer"></div>
            <input id="filter-input" placeholder="過濾..." style="width:180px" />
            <label class="inline-check"><input type="checkbox" id="show-inactive" /><span>顯示已隱藏</span></label>
          </div>
        </div>
        <div class="panel-body" id="data-table"></div>
      </div>`;
    let rows = [];
    let selectedKey = '';
    let choices = await loadReferenceChoices(page.form || []);

    async function refresh() {
      const showInactive = $('#show-inactive').checked ? 1 : 0;
      rows = await api(`/api/resources/${page.resource}?show_inactive=${showInactive}`);
      choices = await loadReferenceChoices(page.form || []);
      renderRows();
    }

    function renderRows() {
      const q = $('#filter-input').value.trim().toLowerCase();
      const filtered = q ? rows.filter(r => Object.values(r).some(v => String(v ?? '').toLowerCase().includes(q))) : rows;
      $('#data-table').innerHTML = renderNormalRows(page, filtered, choices, selectedKey);
      $$('#data-table tr[data-key]').forEach(tr => tr.addEventListener('click', () => {
        selectedKey = tr.dataset.key;
        $$('#data-table tr').forEach(x => x.classList.remove('selected'));
        tr.classList.add('selected');
      }));
    }

    function selectedRow() {
      return rows.find(r => r[primaryKey(r)] === selectedKey);
    }

    $('#filter-input').addEventListener('input', renderRows);
    $('#show-inactive').addEventListener('change', refresh);
    $$('[data-action]').forEach(btn => btn.addEventListener('click', async () => {
      const action = btn.dataset.action;
      const row = selectedRow();
      try {
        if (action === 'add') openNormalEditor(page, 'AddNew');
        else if (action === 'copy') {
          if (!row) throw new Error('請先選擇資料');
          openNormalEditor(page, 'Copy', row);
        } else if (action === 'modify') {
          if (!row) throw new Error('請先選擇資料');
          openNormalEditor(page, 'Modify', row);
        } else if (action === 'hide' || action === 'show') {
          if (!row) throw new Error('請先選擇資料');
          const mode = action === 'hide' ? 'hide' : 'show';
          await api(`/api/resources/${page.resource}/${row[primaryKey(row)]}/${mode}`, {method: 'POST'});
          toast(action === 'hide' ? '已隱藏' : '已恢復');
          await refresh();
        } else if (action === 'refresh') { await refresh(); toast('已重新整理'); }
        else if (action === 'export') exportCsv(page.code, rows, page.columns);
        else if (action === 'logs') {
          if (!row) throw new Error('請先選擇資料');
          const logs = await api(`/api/resources/${page.resource}/${row[primaryKey(row)]}/logs`);
          modal(`${page.title} 履歷`, logs.length ? `<table class="grid"><thead><tr><th>交易類別</th><th>資料狀態</th><th>修改時間</th><th>修改人員</th><th>IP</th><th>電腦名稱</th></tr></thead><tbody>${logs.map(l => `<tr><td>${esc(l.TRX_MODE)}</td><td>${esc(l.DATA_STATUS)}</td><td>${esc(l.UPDATED_AT)}</td><td>${esc(l.UPDATED_BY)}</td><td>${esc(l.UPDATED_IP)}</td><td>${esc(l.HOST_NAME)}</td></tr>`).join('')}</tbody></table>` : '<div class="empty">沒有履歷</div>');
        }
      } catch (err) { toast(err.message, 'error'); }
    }));

    function fieldHtml(field, value, mode) {
      const readonly = field.readonly_on_modify && mode === 'Modify';
      if (field.type === 'fixed') return '';
      if (field.type === 'textarea') return `<label>${esc(field.label)}${field.required ? ' *' : ''}<textarea name="${esc(field.name)}" ${readonly ? 'readonly' : ''}>${esc(value ?? '')}</textarea></label>`;
      if (field.type === 'reference') {
        const choicesRows = choices[field.resource] || [];
        const options = choicesRows.map(r => `<option value="${esc(r[primaryKey(r)])}" ${r[primaryKey(r)] === value ? 'selected' : ''}>${esc(r[field.display] || r[primaryKey(r)])}</option>`).join('');
        return `<label>${esc(field.label)}${field.required ? ' *' : ''}<select name="${esc(field.name)}" ${readonly ? 'disabled' : ''}><option value="">--</option>${options}</select></label>`;
      }
      if (field.type === 'select') {
        const options = field.options.map(o => `<option value="${esc(o.value)}" ${o.value === value ? 'selected' : ''}>${esc(o.label)}</option>`).join('');
        return `<label>${esc(field.label)}${field.required ? ' *' : ''}<select name="${esc(field.name)}" ${readonly ? 'disabled' : ''}>${options}</select></label>`;
      }
      if (field.type === 'multiselect') {
        const selected = String(value || '').split(';').filter(Boolean);
        return `<label>${esc(field.label)}${field.required ? ' *' : ''}<div class="chip-list">${field.options.map(o => `<label class="inline-check"><input type="checkbox" name="${esc(field.name)}" value="${esc(o.value)}" ${selected.includes(o.value) ? 'checked' : ''} /><span>${esc(o.label)}</span></label>`).join('')}</div></label>`;
      }
      const inputType = field.type === 'number' ? 'number' : field.type === 'email' ? 'email' : field.type === 'datetime' ? 'datetime-local' : 'text';
      return `<label>${esc(field.label)}${field.required ? ' *' : ''}<input name="${esc(field.name)}" type="${inputType}" value="${esc(value ?? '')}" ${readonly ? 'readonly' : ''} /></label>`;
    }

    function openNormalEditor(page, mode, row = {}) {
      const isEdit = mode === 'Modify';
      const fields = (page.form || []).filter(f => f.type !== 'fixed').map(f => `<div>${fieldHtml(f, row[f.name], mode)}</div>`).join('');
      modal(`${page.title} · ${mode}`, `<form id="normal-editor"><div class="form-grid">${fields}</div></form>`, `
        <button data-cancel>取消</button>
        <button class="primary" data-save>儲存</button>`);
      $('[data-cancel]').addEventListener('click', closeModal);
      $('[data-save]').addEventListener('click', async ev => {
        ev.preventDefault();
        const form = $('#normal-editor');
        const fd = new FormData(form);
        const payload = {};
        (page.form || []).forEach(f => {
          if (f.type === 'multiselect') payload[f.name] = $$(`input[name="${f.name}"]:checked`, form).map(x => x.value).join(';');
          else payload[f.name] = fd.get(f.name);
          if (f.type === 'fixed') payload[f.name] = f.value;
        });
        try {
          const key = row[primaryKey(row)];
          const saved = isEdit && key
            ? await api(`/api/resources/${page.resource}/${key}`, {method: 'PUT', body: payload})
            : await api(`/api/resources/${page.resource}`, {method: 'POST', body: payload});
          selectedKey = saved[primaryKey(saved)];
          closeModal();
          toast('儲存成功');
          await refresh();
        } catch (err) { modalError(err.message); toast(err.message, 'error'); }
      });
    }

    await refresh();
  }

  // ---------------------------------------------------------------------
  // Mapping pages
  // ---------------------------------------------------------------------
  async function renderMappingPage(page) {
    const content = $('#page-content');
    content.innerHTML = `
      <div class="panel">
        <div class="panel-head">
          <div class="panel-title">${esc(page.title)}（${esc(page.code)}）</div>
          <div class="toolbar">
            <button data-action="modify">修改</button>
            <button data-action="refresh">重新整理</button>
            <button data-action="export">匯出</button>
          </div>
        </div>
        <div class="panel-body">
          <div class="split">
            <div class="mapping-panel">
              <div class="mapping-head">${esc(page.masterResource)}</div>
              <div class="mapping-body" id="master-list"></div>
            </div>
            <div class="mapping-panel">
              <div class="mapping-head">${esc(page.rightTitle || '已選資料')}</div>
              <div class="mapping-body" id="mapping-list"></div>
            </div>
          </div>
        </div>
      </div>`;
    let masters = [], mappings = [], sources = [], selectedMaster = '';

    async function refresh() {
      [masters, mappings, sources] = await Promise.all([
        cachedResource(page.masterResource),
        cachedResource(page.mappingResource),
        cachedResource(page.sourceResource),
      ]);
      if (!selectedMaster && masters.length) selectedMaster = masters[0][primaryKey(masters[0])];
      renderLists();
    }

    function renderLists() {
      $('#master-list').innerHTML = masters.length ? `<table class="grid"><tbody>${masters.map(m => {
        const key = m[primaryKey(m)];
        return `<tr class="clickable ${key === selectedMaster ? 'selected' : ''}" data-key="${esc(key)}"><td>${esc(m[page.masterDisplay])}</td><td>${esc(m.EQP_GROUP_NAME || m.USER_GROUP_NAME || m.FACTORY_NAME || m.EQP_TYPE_NAME || '')}</td></tr>`;
      }).join('')}</tbody></table>` : '<div class="empty">沒有主檔資料</div>';
      const mappedRows = mappings.filter(m => m[page.masterKey] === selectedMaster && m.ACTIVE === 'Y');
      const mappedKeys = new Set(mappedRows.map(m => m[page.mappingKey]));
      const mappedSources = sources.filter(s => mappedKeys.has(s[primaryKey(s)]));
      $('#mapping-list').innerHTML = mappedSources.length ? `<table class="grid"><tbody>${mappedSources.map(s => `<tr><td>${esc(s[page.sourceDisplay])}</td><td>${esc(s.EQP_NAME || s.USER_NAME || s.SUB_SYS_NAME || s.EQP_STATUS_NAME || '')}</td></tr>`).join('')}</tbody></table>` : '<div class="empty">沒有對應資料</div>';
      $$('#master-list tr[data-key]').forEach(tr => tr.addEventListener('click', () => {
        selectedMaster = tr.dataset.key;
        renderLists();
      }));
    }

    $$('[data-action]').forEach(btn => btn.addEventListener('click', async () => {
      const action = btn.dataset.action;
      try {
        if (action === 'modify') openMappingEditor();
        else if (action === 'refresh') { clearCaches(); await refresh(); toast('已重新整理'); }
        else if (action === 'export') exportCsv(page.code, mappings);
      } catch (err) { toast(err.message, 'error'); }
    }));

    function openMappingEditor() {
      const masterRow = masters.find(m => m[primaryKey(m)] === selectedMaster);
      if (!masterRow) { toast('請先選擇主檔', 'error'); return; }
      const mapped = new Set(mappings.filter(m => m[page.masterKey] === selectedMaster && m.ACTIVE === 'Y').map(m => m[page.mappingKey]));
      modal(`${page.title} · Mapping`, `
        <label>主檔<input value="${esc(masterRow[page.masterDisplay])}" readonly /></label>
        <div style="height:14px"></div>
        <div class="split">
          <div class="mapping-panel"><div class="mapping-head">${esc(page.leftTitle || '未選資料')}</div><div class="mapping-body">${sources.map(s => `<label class="inline-check" style="padding:8px 12px"><input type="checkbox" class="mapping-source" data-key="${esc(s[primaryKey(s)])}" ${mapped.has(s[primaryKey(s)]) ? 'checked' : ''} /><span>${esc(s[page.sourceDisplay])}</span></label>`).join('')}</div></div>
          <div class="mapping-panel"><div class="mapping-head">說明</div><div class="mapping-body"><div style="padding:12px">勾選資料後按「儲存」；系統會自動建立對應、隱藏取消項目。</div></div></div>
        </div>`, `<button data-cancel>取消</button><button class="primary" data-save>儲存</button>`);
      $('[data-cancel]').addEventListener('click', closeModal);
      $('[data-save]').addEventListener('click', async () => {
        try {
          const checked = new Set($$('.mapping-source:checked').map(x => x.dataset.key));
          const existing = mappings.filter(m => m[page.masterKey] === selectedMaster);
          for (const source of sources) {
            const sourceKey = source[primaryKey(source)];
            const row = existing.find(m => m[page.mappingKey] === sourceKey);
            if (checked.has(sourceKey) && (!row || row.ACTIVE === 'N')) {
              const body = {[page.masterKey]: selectedMaster, [page.mappingKey]: sourceKey};
              await api(`/api/resources/${page.mappingResource}`, {method: 'POST', body});
            } else if (!checked.has(sourceKey) && row && row.ACTIVE === 'Y') {
              await api(`/api/resources/${page.mappingResource}/${row[primaryKey(row)]}/hide`, {method: 'POST'});
            }
          }
          clearCaches();
          closeModal();
          toast('對應已儲存');
          await refresh();
        } catch (err) { modalError(err.message); toast(err.message, 'error'); }
      });
    }

    await refresh();
  }

  // ---------------------------------------------------------------------
  // Master-detail pages
  // ---------------------------------------------------------------------
  async function renderMasterDetailPage(page) {
    await renderNormalPage({...page});
    // Replace generic CRUD handlers with master-detail editors for Add/Copy/Modify.
    ['add', 'copy', 'modify'].forEach(action => {
      const button = $$(`[data-action="${action}"]`).at(-1);
      if (!button) return;
      const clone = button.cloneNode(true);
      button.replaceWith(clone);
      clone.addEventListener('click', async () => {
        const selected = $('#data-table tr.selected');
        if (action !== 'add' && !selected) { toast('請先選擇資料', 'error'); return; }
        let row = null;
        if (action !== 'add') {
          const rows = await api(`/api/resources/${page.masterResource}`);
          row = rows.find(r => r[primaryKey(r)] === selected.dataset.key);
        }
        const mode = action === 'add' ? 'AddNew' : action === 'copy' ? 'Copy' : 'Modify';
        openMasterEditor(page, mode, row || {});
      });
    });
  }

  function openMasterEditor(page, mode, row = {}) {
    const masterFields = page.form.map(f => `<div>${genericFieldHtml(f, row[f.name], mode)}</div>`).join('');
    modal(`${page.title} · ${mode}`, `
      <form id="master-form"><div class="form-grid">${masterFields}</div></form>
      <div class="detail-block">
        <div class="panel-title">清單資訊</div>
        <div id="detail-container" style="margin-top:10px"></div>
      </div>`,
      `<button data-cancel>取消</button><button class="primary" data-save-master>儲存主檔</button>`);
    $('[data-cancel]').addEventListener('click', closeModal);
    $('[data-save-master]').addEventListener('click', async ev => {
      ev.preventDefault();
      const form = $('#master-form');
      const fd = new FormData(form);
      const payload = {};
      page.form.forEach(f => {
        if (f.type === 'multiselect') payload[f.name] = $$(`input[name="${f.name}"]:checked`, form).map(x => x.value).join(';');
        else payload[f.name] = fd.get(f.name);
      });
      try {
        const key = row[primaryKey(row)];
        const saved = mode === 'Modify' && key
          ? await api(`/api/resources/${page.masterResource}/${key}`, {method: 'PUT', body: payload})
          : await api(`/api/resources/${page.masterResource}`, {method: 'POST', body: payload});
        row = saved;
        toast('主檔已儲存');
        renderDetailArea();
      } catch (err) { modalError(err.message); toast(err.message, 'error'); }
    });

    async function renderDetailArea() {
      const container = $('#detail-container');
      if (!row[primaryKey(row)]) {
        container.innerHTML = '<div class="empty">請先儲存主檔後再新增明細</div>';
        return;
      }
      const details = await api(`/api/resources/${page.detailResource}?${page.detailKey}=${encodeURIComponent(row[primaryKey(row)])}&show_inactive=1`);
      const choiceRows = await cachedResource((page.detailForm[0].type === 'reference' ? page.detailForm[0].resource : 'users'));
      container.innerHTML = `
        <form id="detail-form" class="form-grid">${page.detailForm.map(f => `<div>${genericFieldHtml(f, '', 'AddNew')}</div>`).join('')}</form>
        <div style="height:12px"></div>
        <button class="primary" data-add-detail>新增明細</button>
        <div style="height:12px"></div>
        <div>${details.length ? `<table class="grid"><thead><tr>${page.detailColumns.map(c => `<th>${esc(c)}</th>`).join('')}<th></th></tr></thead><tbody>${details.map(d => `<tr><td>${page.detailColumns.map(c => {
          const f = page.detailForm.find(x => x.name === c);
          let val = d[c];
          if (f?.type === 'reference') {
            const match = choiceRows.find(r => r[primaryKey(r)] === val);
            if (match) val = match[f.display] || val;
          }
          return esc(val);
        }).join('</td><td>')}</td><td><button data-detail-key="${esc(d[primaryKey(d)])}" data-detail-active="${esc(d.ACTIVE)}">${d.ACTIVE === 'Y' ? '隱藏' : '恢復'}</button></td></tr>`).join('')}</tbody></table>` : '<div class="empty">沒有明細</div>'}</div>`;
      $('[data-add-detail]').addEventListener('click', async ev => {
        ev.preventDefault();
        const form = $('#detail-form');
        const fd = new FormData(form);
        const payload = {[page.detailKey]: row[primaryKey(row)]};
        page.detailForm.forEach(f => payload[f.name] = fd.get(f.name));
        try {
          await api(`/api/resources/${page.detailResource}`, {method: 'POST', body: payload});
          toast('明細已新增');
          renderDetailArea();
        } catch (err) { modalError(err.message); toast(err.message, 'error'); }
      });
      $$('[data-detail-key]').forEach(btn => btn.addEventListener('click', async () => {
        const mode = btn.dataset.detailActive === 'Y' ? 'hide' : 'show';
        try {
          await api(`/api/resources/${page.detailResource}/${btn.dataset.detailKey}/${mode}`, {method: 'POST'});
          renderDetailArea();
        } catch (err) { toast(err.message, 'error'); }
      }));
    }
    renderDetailArea();
  }

  function genericFieldHtml(field, value, mode) {
    const readonly = field.readonly_on_modify && mode === 'Modify';
    if (field.type === 'textarea') return `<label>${esc(field.label)}${field.required ? ' *' : ''}<textarea name="${esc(field.name)}" ${readonly ? 'readonly' : ''}>${esc(value ?? '')}</textarea></label>`;
    if (field.type === 'select') {
      return `<label>${esc(field.label)}${field.required ? ' *' : ''}<select name="${esc(field.name)}"><option value="">--</option>${field.options.map(o => `<option value="${esc(o.value)}" ${o.value === value ? 'selected' : ''}>${esc(o.label)}</option>`).join('')}</select></label>`;
    }
    if (field.type === 'multiselect') {
      const selected = String(value || '').split(';').filter(Boolean);
      return `<label>${esc(field.label)}${field.required ? ' *' : ''}<div class="chip-list">${field.options.map(o => `<label class="inline-check"><input type="checkbox" name="${esc(field.name)}" value="${esc(o.value)}" ${selected.includes(o.value) ? 'checked' : ''} /><span>${esc(o.label)}</span></label>`).join('')}</div></label>`;
    }
    const inputType = field.type === 'number' ? 'number' : field.type === 'email' ? 'email' : field.type === 'datetime' ? 'datetime-local' : 'text';
    return `<label>${esc(field.label)}${field.required ? ' *' : ''}<input name="${esc(field.name)}" type="${inputType}" value="${esc(value ?? '')}" ${readonly ? 'readonly' : ''} /></label>`;
  }

  async function renderServiceConfigPage(page) {
    const content = $('#page-content');
    content.innerHTML = `
      <div class="panel">
        <div class="panel-head"><div class="panel-title">${esc(page.title)}（${esc(page.code)}）</div><div class="toolbar"><button data-action="refresh">重新整理</button><button class="primary" data-action="save">儲存</button></div></div>
        <div class="panel-body" id="config-table"></div>
      </div>`;
    let rows = [];
    async function refresh() {
      rows = await api(`/api/resources/${page.resource}`);
      $('#config-table').innerHTML = rows.length ? `<table class="grid"><thead><tr><th>ENABLE</th>${page.columns.filter(c => c !== 'ENABLE').map(c => `<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${rows.map(r => `<tr><td><input type="checkbox" class="enable-check" data-key="${esc(r[primaryKey(r)])}" ${r.ENABLE === 'Y' ? 'checked' : ''} /></td>${page.columns.filter(c => c !== 'ENABLE').map(c => c === 'DEVICE_STATUS' ? `<td><span class="badge ${esc(r[c])}">${esc(r[c])}</span></td>` : `<td>${esc(r[c])}</td>`).join('')}</tr>`).join('')}</tbody></table>` : '<div class="empty">沒有資料</div>';
    }
    $$('[data-action]').forEach(btn => btn.addEventListener('click', async () => {
      if (btn.dataset.action === 'refresh') { await refresh(); return; }
      const boxes = $$('.enable-check');
      const updates = boxes.map(b => api(`/api/resources/${page.resource}/${b.dataset.key}`, {method: 'PUT', body: {ENABLE: b.checked ? 'Y' : 'N'}}));
      try { await Promise.all(updates); toast('儲存成功'); await refresh(); } catch (err) { toast(err.message, 'error'); }
    }));
    await refresh();
  }

  // ---------------------------------------------------------------------
  // Operation pages
  // ---------------------------------------------------------------------
  const CUSTOM_ROUTES = {
    '/alarm-manual-send': renderAlarmManualSend,
    '/alarm-send': renderAlarmSend,
    '/alarm-ack': renderAlarmAck,
    '/alarm-terminate': renderAlarmTerminate,
    '/alarm-summary': renderAlarmSummary,
    '/alarm-report': () => renderAlarmReportPage('alarm-report'),
    '/alarm-history': () => renderAlarmReportPage('alarm-history'),
    '/invalid-alarms': () => renderAlarmReportPage('invalid-alarms'),
    '/device-status-report': renderDeviceStatusReport,
    '/report-setting': renderReportSetting,
    '/batch-status-setting': renderBatchStatusSetting,
    '/batch-hide': renderBatchHide,
    '/chamber-alarm-mapping': renderChamberAlarmMapping,
  };

  async function baseOperationPage(title, code, bodyHtml) {
    $('#page-content').innerHTML = `
      <div class="panel">
        <div class="panel-head"><div class="panel-title">${esc(title)}（${esc(code)}）</div></div>
        <div class="panel-body">${bodyHtml}</div>
      </div>`;
  }

  async function renderAlarmManualSend() {
    const [factories, subsystems, users, sendTypes, subjects] = await Promise.all([
      cachedResource('factories'), cachedResource('sub-systems'), cachedResource('users'), api('/api/meta/send-types'), api('/api/alarms/subject-cache'),
    ]);
    await baseOperationPage('警報手動發送作業', 'AVPA002', `
      <div class="filter-grid">
        <label>廠別代碼<select id="manual-factory"><option value="">--</option>${factories.map(f => `<option value="${esc(f.FACTORY_KEY)}">${esc(f.FACTORY_ID)}</option>`).join('')}</select></label>
        <label>子系統代碼<select id="manual-subsys"><option value="">--</option>${subsystems.map(s => `<option value="${esc(s.SUB_SYS_KEY)}">${esc(s.SUB_SYS_ID)}</option>`).join('')}</select></label>
        <label>使用者代碼<select id="manual-users" multiple style="height:130px">${users.map(u => `<option value="${esc(u.USER_KEY)}">${esc(u.USER_ID)} / ${esc(u.USER_NAME)}</option>`).join('')}</select></label>
        <label>發送方式<div class="chip-list">${sendTypes.map(s => `<label class="inline-check"><input type="checkbox" class="manual-sendtype" value="${esc(s.value)}" /><span>${esc(s.label)}</span></label>`).join('')}</div></label>
        <label>警報標題<input id="manual-subject" /></label>
        <label>警報詳細內容<textarea id="manual-content"></textarea></label>
      </div>
      <div class="toolbar" style="margin-top:18px">
        <button class="primary" id="manual-send-btn">發送</button>
        <button id="manual-clear-btn">清除</button>
        <button id="manual-history-btn">歷史紀錄</button>
      </div>`);
    $('#manual-send-btn').addEventListener('click', async () => {
      try {
        await api('/api/alarms/manual-send', {method: 'POST', body: {
          FACTORY_KEY: $('#manual-factory').value,
          SUB_SYS_KEY: $('#manual-subsys').value,
          USER_KEYS: $$('#manual-users option:checked').map(o => o.value),
          SEND_TYPES: $$('.manual-sendtype:checked').map(x => x.value),
          SUBJECT: $('#manual-subject').value,
          CONTENT: $('#manual-content').value,
        }});
        toast('警報已發送');
        $('#manual-content').value = '';
      } catch (err) { toast(err.message, 'error'); }
    });
    $('#manual-clear-btn').addEventListener('click', () => {
      $('#manual-factory').value = ''; $('#manual-subsys').value = ''; $('#manual-subject').value = ''; $('#manual-content').value = '';
      $$('#manual-users option').forEach(o => o.selected = false); $$('.manual-sendtype').forEach(x => x.checked = false);
    });
    $('#manual-history-btn').addEventListener('click', () => {
      modal('警報標題歷史紀錄', subjects.length ? `<table class="grid"><thead><tr><th>標題</th><th>使用次數</th><th>最後使用時間</th></tr></thead><tbody>${subjects.map(s => `<tr class="clickable"><td>${esc(s.SUBJECT)}</td><td>${esc(s.USED_COUNT)}</td><td>${esc(s.LAST_USED_DT)}</td></tr>`).join('')}</tbody></table>` : '<div class="empty">沒有歷史紀錄</div>');
      $$('#modal-root tr[data-key], #modal-root tbody tr').forEach(tr => tr.addEventListener('click', () => {
        $('#manual-subject').value = tr.children[0]?.textContent || '';
        closeModal();
      }));
    });
  }

  async function renderAlarmSend() {
    const [factories, subsystems, equipment, alarmInfos] = await Promise.all([
      cachedResource('factories'), cachedResource('sub-systems'), cachedResource('equipment'), cachedResource('alarm-infos'),
    ]);
    await baseOperationPage('警報補登作業', 'AVPA009', `
      <div class="filter-grid">
        <label>廠別代碼<select id="send-factory"><option value="">--</option>${factories.map(f => `<option value="${esc(f.FACTORY_ID)}">${esc(f.FACTORY_ID)}</option>`).join('')}</select></label>
        <label>子系統代碼<select id="send-subsys"></select></label>
        <label>機台代碼<select id="send-eqp"></select></label>
        <label>警報代碼<select id="send-alarm"></select></label>
        <label>警報標題<input id="send-subject" /></label>
        <label>警報詳細內容<textarea id="send-content"></textarea></label>
      </div>
      <div class="toolbar" style="margin-top:18px"><button class="primary" id="send-btn">發送</button><button id="send-clear-btn">清除</button></div>`);
    function fillSubsys() {
      const factory = factories.find(f => f.FACTORY_ID === $('#send-factory').value);
      const options = subsystems.filter(s => {
        const map = factorySubMap.find(x => x.FACTORY_KEY === factory?.FACTORY_KEY && x.SUB_SYS_KEY === s.SUB_SYS_KEY);
        return map && map.ACTIVE === 'Y';
      });
      $('#send-subsys').innerHTML = '<option value="">--</option>' + options.map(s => `<option value="${esc(s.SUB_SYS_ID)}">${esc(s.SUB_SYS_ID)}</option>`).join('');
    }
    const factorySubMap = await cachedResource('factory-sub-systems');
    $('#send-factory').addEventListener('change', fillSubsys);
    $('#send-subsys').addEventListener('change', () => {
      const factory = factories.find(f => f.FACTORY_ID === $('#send-factory').value);
      const sub = subsystems.find(s => s.SUB_SYS_ID === $('#send-subsys').value);
      const eqps = equipment.filter(e => {
        const f = factory && e.FACTORY_KEY === factory.FACTORY_KEY;
        return f || true;
      });
      $('#send-eqp').innerHTML = '<option value="">--</option>' + equipment.map(e => `<option value="${esc(e.EQP_ID)}">${esc(e.EQP_ID)}</option>`).join('');
      fillAlarmInfos();
    });
    function fillAlarmInfos() {
      const factory = factories.find(f => f.FACTORY_ID === $('#send-factory').value);
      const sub = subsystems.find(s => s.SUB_SYS_ID === $('#send-subsys').value);
      const eqp = equipment.find(e => e.EQP_ID === $('#send-eqp').value);
      const options = alarmInfos.filter(a => (!factory || a.FACTORY_KEY === factory.FACTORY_KEY) && (!sub || a.SUB_SYS_KEY === sub.SUB_SYS_KEY) && (!eqp || a.EQP_KEY === eqp.EQP_KEY));
      $('#send-alarm').innerHTML = '<option value="">--</option>' + options.map(a => `<option value="${esc(a.ALARM_INFO_ID)}">${esc(a.ALARM_INFO_ID)}</option>`).join('');
    }
    $('#send-eqp').addEventListener('change', fillAlarmInfos);
    $('#send-btn').addEventListener('click', async () => {
      try {
        await api('/api/alarms/send', {method: 'POST', body: {
          FACTORY_ID: $('#send-factory').value,
          SUB_SYS_ID: $('#send-subsys').value,
          EQP_ID: $('#send-eqp').value,
          ALARM_INFO_ID: $('#send-alarm').value,
          SUBJECT: $('#send-subject').value,
          CONTENT: $('#send-content').value,
        }});
        toast('補登完成');
      } catch (err) { toast(err.message, 'error'); }
    });
    $('#send-clear-btn').addEventListener('click', () => {
      ['#send-factory', '#send-subsys', '#send-eqp', '#send-alarm', '#send-subject'].forEach(s => $(s).value = '');
      $('#send-content').value = '';
    });
  }

  async function renderAlarmAck() {
    await baseOperationPage('警報確認回報作業', 'AVPA003', `
      <div class="toolbar" style="margin-bottom:12px"><button class="primary" id="ack-refresh">更新</button><button id="ack-upgrade">執行層級升級</button><button class="success" id="ack-submit">確認</button></div>
      <div id="ack-table"></div>
      <label style="margin-top:14px">回應備註<input id="ack-comment" /></label>`);
    let rows = [];
    async function refresh() {
      rows = await api('/api/alarms/ack');
      $('#ack-table').innerHTML = rows.length ? `<table class="grid"><thead><tr><th>選擇</th><th>ALARM_GUID</th><th>警報標題</th><th>狀態</th><th>廠別</th><th>子系統</th><th>機台</th><th>事件</th><th>層級</th><th>需要ACK</th><th>已ACK</th></tr></thead><tbody>${rows.map(r => `<tr><td><input type="checkbox" class="ack-check" value="${esc(r.ALARM_KEY)}" /></td><td>${esc(r.ALARM_GUID)}</td><td>${esc(r.SUBJECT)}</td><td><span class="badge ${esc(r.STATUS)}">${esc(r.STATUS)}</span></td><td>${esc(r.FACTORY_ID)}</td><td>${esc(r.SUB_SYS_ID)}</td><td>${esc(r.EQP_ID)}</td><td>${esc(r.EVENT_ID)}</td><td>${esc(r.EVENT_LEVEL_ID)}</td><td>${esc(r.NUMBER_OF_ACK_USERS)}</td><td>${esc(r.ACK_USER_COUNT)}</td></tr>`).join('')}</tbody></table>` : '<div class="empty">沒有待確認警報</div>';
    }
    $('#ack-refresh').addEventListener('click', refresh);
    $('#ack-upgrade').addEventListener('click', async () => { await api('/api/alarms/upgrade', {method: 'POST'}); refresh(); toast('已處理層級升級'); });
    $('#ack-submit').addEventListener('click', async () => {
      const keys = $$('.ack-check:checked').map(x => x.value);
      if (!keys.length) { toast('請選擇警報', 'error'); return; }
      try {
        await api('/api/alarms/ack', {method: 'POST', body: {ALARM_KEYS: keys, COMMENT: $('#ack-comment').value}});
        toast('確認完成');
        $('#ack-comment').value = '';
        refresh();
      } catch (err) { toast(err.message, 'error'); }
    });
    await refresh();
  }

  async function renderAlarmTerminate() {
    await baseOperationPage('警報強制中斷作業', 'AVPA006', `
      <div class="toolbar" style="margin-bottom:12px"><button class="primary" id="term-refresh">查詢</button><button class="danger" id="term-submit">確認中斷</button></div>
      <div id="term-table"></div>
      <label style="margin-top:14px">中斷備註<input id="term-comment" /></label>`);
    let rows = [];
    async function refresh() {
      rows = await api('/api/alarms/process');
      $('#term-table').innerHTML = rows.length ? `<table class="grid"><thead><tr><th>選擇</th><th>ALARM_GUID</th><th>警報標題</th><th>狀態</th><th>廠別</th><th>子系統</th><th>機台</th><th>事件</th><th>層級</th></tr></thead><tbody>${rows.map(r => `<tr><td><input type="checkbox" class="term-check" value="${esc(r.ALARM_KEY)}" /></td><td>${esc(r.ALARM_GUID)}</td><td>${esc(r.SUBJECT)}</td><td><span class="badge ${esc(r.STATUS)}">${esc(r.STATUS)}</span></td><td>${esc(r.FACTORY_ID)}</td><td>${esc(r.SUB_SYS_ID)}</td><td>${esc(r.EQP_ID)}</td><td>${esc(r.EVENT_ID)}</td><td>${esc(r.EVENT_LEVEL_ID)}</td></tr>`).join('')}</tbody></table>` : '<div class="empty">沒有處理中警報</div>';
    }
    $('#term-refresh').addEventListener('click', refresh);
    $('#term-submit').addEventListener('click', async () => {
      const keys = $$('.term-check:checked').map(x => x.value);
      if (!keys.length) { toast('請選擇警報', 'error'); return; }
      try {
        await api('/api/alarms/terminate', {method: 'POST', body: {ALARM_KEYS: keys, COMMENT: $('#term-comment').value}});
        toast('中斷完成');
        $('#term-comment').value = '';
        refresh();
      } catch (err) { toast(err.message, 'error'); }
    });
    await refresh();
  }

  async function renderAlarmSummary() {
    let detailMode = false;
    let current = null;
    let timer = null;
    await baseOperationPage('即時警報彙整', 'AVPA013', `
      <div class="toolbar" style="margin-bottom:12px"><button id="summary-refresh">重新整理</button><button id="summary-back">回上層</button><div class="spacer"></div><span id="summary-countdown">10</span></div>
      <div id="summary-table"></div>`);
    async function refresh() {
      const rows = detailMode ? await api(`/api/reports/alarm-summary/detail?factory_id=${encodeURIComponent(current.FACTORY_ID)}&sub_sys_id=${encodeURIComponent(current.SUB_SYS_ID)}`) : await api('/api/reports/alarm-summary');
      const columns = detailMode ? ['FACTORY_ID', 'FACTORY_NAME', 'SUB_SYS_ID', 'SUB_SYS_NAME', 'EQP_ID', 'ALARM_COUNT'] : ['FACTORY_ID', 'FACTORY_NAME', 'SUB_SYS_ID', 'SUB_SYS_NAME', 'ALARM_COUNT'];
      $('#summary-table').innerHTML = rows.length ? `<table class="grid"><thead><tr>${columns.map(c => `<th>${esc(c)}</th>`).join('')}${detailMode ? '' : '<th>按鍵</th>'}</tr></thead><tbody>${rows.map(r => `<tr>${columns.map(c => `<td>${esc(r[c])}</td>`).join('')}${detailMode ? '' : `<td><button class="summary-select" data-factory="${esc(r.FACTORY_ID)}" data-subsys="${esc(r.SUB_SYS_ID)}">選擇</button></td>`}</tr>`).join('')}</tbody></table>` : '<div class="empty">沒有資料</div>';
      if (!detailMode) $$('.summary-select').forEach(btn => btn.addEventListener('click', () => {
        detailMode = true;
        current = {FACTORY_ID: btn.dataset.factory, SUB_SYS_ID: btn.dataset.subsys};
        refresh();
      }));
    }
    $('#summary-refresh').addEventListener('click', refresh);
    $('#summary-back').addEventListener('click', () => { detailMode = false; current = null; refresh(); });
    clearInterval(timer);
    let countdown = 10;
    timer = setInterval(() => {
      countdown--;
      if (countdown <= 0) { countdown = 10; refresh(); }
      $('#summary-countdown').textContent = countdown;
    }, 1000);
    await refresh();
  }

  async function renderAlarmReportPage(report) {
    const titles = {'alarm-report': ['警報處理查詢', 'AVPA004'], 'alarm-history': ['歷史紀錄查詢', 'AVPA007'], 'invalid-alarms': ['無效警報查詢', 'AVPA005']};
    const [title, code] = titles[report];
    const groups = await cachedResource('equipment-groups');
    await baseOperationPage(title, code, `
      <div class="filter-grid">
        <label class="inline-check"><input type="checkbox" id="chk-from" checked /><span>資料新增時間</span></label>
        <label>起始時間<input id="from-date" type="date" value="${new Date(Date.now() - (report === 'alarm-history' ? 3 : 7) * 86400000).toISOString().slice(0, 10)}" /></label>
        <label>結束時間<input id="to-date" type="date" value="${new Date().toISOString().slice(0, 10)}" /></label>
        <label class="inline-check"><input type="checkbox" id="chk-group" /><span>機台群組</span></label>
        <label>群組<select id="eqp-group"><option value="">--</option>${groups.map(g => `<option value="${esc(g.EQP_GROUP_KEY)}">${esc(g.EQP_GROUP_ID)}</option>`).join('')}</select></label>
        <label class="inline-check"><input type="checkbox" id="chk-eqp" /><span>機台代碼</span></label>
        <label>機台<input id="eqp-id" /></label>
        <label class="inline-check"><input type="checkbox" id="chk-subsys" /><span>子系統代碼</span></label>
        <label>子系統<input id="subsys-id" /></label>
        <label>狀態<select id="status-filter"><option value="">全部</option><option>Process</option><option>Completed</option><option>NoNextLevel</option><option>Terminated</option></select></label>
      </div>
      <div class="toolbar" style="margin-top:14px"><button class="primary" id="report-query">查詢</button><button id="report-export">匯出Excel</button></div>
      <div id="report-table" style="margin-top:14px"></div>`);
    let rows = [];
    async function query() {
      const params = new URLSearchParams();
      if ($('#chk-from').checked) { params.set('from', $('#from-date').value); params.set('to', $('#to-date').value); }
      if ($('#chk-group').checked) params.set('eqp_group_key', $('#eqp-group').value);
      if ($('#chk-eqp').checked) params.set('eqp_id', $('#eqp-id').value);
      if ($('#chk-subsys').checked) params.set('sub_sys_id', $('#subsys-id').value);
      if ($('#status-filter').value) params.set('status', $('#status-filter').value);
      const endpoint = report === 'alarm-report' ? '/api/reports/alarms' : report === 'alarm-history' ? '/api/reports/history' : '/api/reports/invalid-alarms';
      rows = await api(`${endpoint}?${params.toString()}`);
      const columns = rows.length ? Object.keys(rows[0]).filter(k => !k.endsWith('_KEY')).slice(0, 22) : [];
      $('#report-table').innerHTML = rows.length ? `<div style="overflow:auto"><table class="grid"><thead><tr>${columns.map(c => `<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${rows.map(r => `<tr>${columns.map(c => c === 'STATUS' ? `<td><span class="badge ${esc(r[c])}">${esc(r[c])}</span></td>` : `<td>${esc(r[c])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>` : '<div class="empty">沒有資料</div>';
    }
    $('#report-query').addEventListener('click', query);
    $('#report-export').addEventListener('click', () => exportCsv(code, rows));
    await query();
  }

  async function renderDeviceStatusReport() {
    await baseOperationPage('系統裝置狀態查詢', 'AVPA008', `
      <div class="toolbar" style="margin-bottom:12px"><button class="primary" id="device-query">查詢</button><button id="device-export">匯出Excel</button></div><div id="device-table"></div>`);
    let rows = [];
    async function refresh() {
      rows = await api('/api/reports/device-status');
      const columns = Object.keys(rows[0] || {}).filter(k => !k.endsWith('_KEY'));
      $('#device-table').innerHTML = rows.length ? `<table class="grid"><thead><tr>${columns.map(c => `<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${rows.map(r => `<tr>${columns.map(c => c === 'DEVICE_STATUS' ? `<td><span class="badge ${esc(r[c])}">${esc(r[c])}</span></td>` : `<td>${esc(r[c])}</td>`).join('')}</tr>`).join('')}</tbody></table>` : '<div class="empty">沒有資料</div>';
    }
    $('#device-query').addEventListener('click', refresh);
    $('#device-export').addEventListener('click', () => exportCsv('AVPA008', rows));
    await refresh();
  }

  async function renderReportSetting() {
    await baseOperationPage('報表設定', 'RPTSET001', `<div class="empty">報表設定提供報表資訊、查詢條件、欄位、圖表與樞紐定義。此原型以既有 API 報表驅動，完整設計器可在後續版本擴充。</div>`);
  }


  async function renderBatchHide() {
    const [factories, subsystems, equipment, groups, events] = await Promise.all([
      cachedResource('factories'), cachedResource('sub-systems'), cachedResource('equipment'), cachedResource('equipment-groups'), cachedResource('events'),
    ]);
    await baseOperationPage('警報通知設定批次隱藏', 'CVMA014', `
      <div class="filter-grid">
        <label>警報代碼<input id="batch-alarm-id" /></label>
        <label>廠別<select id="batch-factory"><option value="">全部</option>${factories.map(f => `<option value="${esc(f.FACTORY_KEY)}">${esc(f.FACTORY_ID)}</option>`).join('')}</select></label>
        <label>子系統<select id="batch-subsys"><option value="">全部</option>${subsystems.map(s => `<option value="${esc(s.SUB_SYS_KEY)}">${esc(s.SUB_SYS_ID)}</option>`).join('')}</select></label>
        <label>機台群組<select id="batch-group"><option value="">全部</option>${groups.map(g => `<option value="${esc(g.EQP_GROUP_KEY)}">${esc(g.EQP_GROUP_ID)}</option>`).join('')}</select></label>
        <label>機台<select id="batch-eqp"><option value="">全部</option>${equipment.map(e => `<option value="${esc(e.EQP_KEY)}">${esc(e.EQP_ID)}</option>`).join('')}</select></label>
        <label>通知事件<select id="batch-event"><option value="">全部</option>${events.map(e => `<option value="${esc(e.EVENT_KEY)}">${esc(e.EVENT_ID)}</option>`).join('')}</select></label>
      </div>
      <div class="toolbar" style="margin-top:14px"><button class="primary" id="batch-query">查詢</button><button id="batch-clear">清除</button><button class="danger" id="batch-hide-btn">隱藏</button><button class="success" id="batch-show-btn">取消隱藏</button></div>
      <div id="batch-table" style="margin-top:14px"></div>`);
    let rows = [];
    async function query() {
      const params = new URLSearchParams({show_inactive: '1'});
      if ($('#batch-alarm-id').value) params.set('ALARM_INFO_ID', $('#batch-alarm-id').value);
      if ($('#batch-factory').value) params.set('FACTORY_KEY', $('#batch-factory').value);
      if ($('#batch-subsys').value) params.set('SUB_SYS_KEY', $('#batch-subsys').value);
      if ($('#batch-eqp').value) params.set('EQP_KEY', $('#batch-eqp').value);
      if ($('#batch-event').value) params.set('EVENT_KEY', $('#batch-event').value);
      rows = await api(`/api/resources/alarm-infos?${params}`);
      $('#batch-table').innerHTML = rows.length ? `<table class="grid"><thead><tr><th>選擇</th><th>警報代碼</th><th>警報說明</th><th>廠別</th><th>子系統</th><th>機台</th><th>事件</th><th>狀態</th></tr></thead><tbody>${rows.map(r => `<tr><td><input type="checkbox" class="batch-check" value="${esc(r.ALARM_INFO_KEY)}" /></td><td>${esc(r.ALARM_INFO_ID)}</td><td>${esc(r.ALARM_ID_DESC)}</td><td>${esc(r.FACTORY_KEY)}</td><td>${esc(r.SUB_SYS_KEY)}</td><td>${esc(r.EQP_KEY)}</td><td>${esc(r.EVENT_KEY)}</td><td>${r.ACTIVE === 'Y' ? '啟用' : '隱藏'}</td></tr>`).join('')}</tbody></table>` : '<div class="empty">沒有資料</div>';
    }
    $('#batch-query').addEventListener('click', query);
    $('#batch-clear').addEventListener('click', () => { $$('#page-content input').forEach(i => { if (i.type !== 'checkbox') i.value = ''; }); $$('#page-content select').forEach(s => s.value = ''); query(); });
    async function change(show) {
      const keys = $$('.batch-check:checked').map(x => x.value);
      if (!keys.length) { toast('請選擇資料', 'error'); return; }
      await api(`/api/resources/alarm-infos/bulk-${show ? 'show' : 'hide'}`, {method: 'POST', body: {keys}});
      toast(show ? '已取消隱藏' : '已隱藏');
      query();
    }
    $('#batch-hide-btn').addEventListener('click', () => change(false).catch(e => toast(e.message, 'error')));
    $('#batch-show-btn').addEventListener('click', () => change(true).catch(e => toast(e.message, 'error')));
    await query();
  }

  async function renderBatchStatusSetting() {
    await baseOperationPage('批次狀態變更設定', 'MCMS051', `<div class="empty">此頁面保留批次狀態變更設定入口，完整規則設定需依原系統 SQL 對應規則再行擴充。</div>`);
  }

  async function renderChamberAlarmMapping() {
    await renderMappingPage({
      title: '子機台與警報對應設定', code: 'CBRM_CHAMBER_ALARM_MAPPING', kind: 'mapping',
      masterResource: 'equipment', mappingResource: 'alarm-infos', sourceResource: 'alarm-infos',
      masterKey: 'EQP_KEY', mappingKey: 'ALARM_INFO_KEY', masterDisplay: 'EQP_ID', sourceDisplay: 'ALARM_INFO_ID',
      leftTitle: '未選警報', rightTitle: '已對應警報',
    });
  }

  // ---------------------------------------------------------------------
  // Startup
  // ---------------------------------------------------------------------
  async function bootstrap() {
    try {
      state.user = await api('/api/auth/me');
      state.menu = await api('/api/menu');
      renderShell();
      navigate(location.hash.replace('#', '') || '/alarm-summary');
    } catch {
      renderLogin();
    }
  }
  bootstrap();
})();
