/* CloudMaster 人工审核台（值班前端）
   接口：GET /api/review/pending · GET /api/review/{ticket} · POST /api/review/decision
   鉴权（v2.0.0 P5）：令牌改走 Authorization: Bearer 头（不进 URL / 不进访问日志）。
   安全：令牌只放 sessionStorage（不进 localStorage）；所有服务端内容一律 textContent 渲染，
        绝不使用 innerHTML，避免上下文里的用户输入造成 XSS。
   回访待办：队列接口附带 followups（到期回访只读交付；回访为线下人工动作，不在系统留痕），
        匿名标识只显示前八位，不落明文。
   合规红线：本页不展示、不保存任何热线号码。 */
(function () {
  'use strict';
  var BASE = (window.CM_API_BASE || '').replace(/\/+$/, '');
  var TKEY = 'cm_review_token';
  var state = { token: '', ticket: null, decisions: null, contacts: null };

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (text !== undefined && text !== null) { n.textContent = String(text); }
    return n;
  }
  function show(id, on) { var n = $(id); if (n) { n.classList.toggle('hidden', !on); } }
  function setMsg(id, text) { var n = $(id); if (n) { n.textContent = text || ''; } }

  function api(path, init) {
    // v2.0.0 P5：令牌从 query 迁到 Authorization 头——query 会进网址栏、访问日志与浏览器历史。
    var opts = init || {};
    var headers = {};
    var k;
    for (k in opts.headers) {
      if (Object.prototype.hasOwnProperty.call(opts.headers, k)) { headers[k] = opts.headers[k]; }
    }
    headers.Authorization = 'Bearer ' + state.token;
    opts.headers = headers;
    return fetch(BASE + path, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        return { ok: r.ok, status: r.status, j: j };
      });
    });
  }
  function plainDetail(detail) {
    if (typeof detail === 'string') { return detail; }
    if (Array.isArray(detail)) {
      return detail.map(function (x) { return (x && x.msg) || ''; }).filter(Boolean).join('；');
    }
    return '';
  }
  function errText(res, fallback) {
    var d = plainDetail(res && res.j && res.j.detail);
    if (d) { return d; }
    if (res && res.status === 401) { return '审核台未授权：缺少或错误的令牌。'; }
    if (res && res.status === 403) { return '审核台未授权：令牌不正确，或服务端未配置审核令牌。'; }
    if (res && res.status === 409) { return '工单的中断态已失效，无法裁决。'; }
    if (res && res.status === 404) { return '工单不存在或已闭环。'; }
    return fallback;
  }

  function fmtTime(iso) {
    if (!iso) { return '—'; }
    var d = new Date(iso);
    if (isNaN(d.getTime())) { return String(iso); }
    var p = function (n) { return (n < 10 ? '0' : '') + n; };
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
  }
  function waited(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) { return '—'; }
    var min = Math.max(0, Math.round((Date.now() - d.getTime()) / 60000));
    if (min < 60) { return min + ' 分钟'; }
    return Math.floor(min / 60) + ' 小时 ' + (min % 60) + ' 分';
  }

  function fillSelect(id, options) {
    var sel = $(id);
    if (!sel || !options) { return; }
    var keys = Object.keys(options);
    if (!keys.length) { return; }
    if (sel.options.length === keys.length && sel.dataset.filled === keys.join(',')) { return; }
    var keep = sel.value;
    sel.textContent = '';
    keys.forEach(function (k) {
      var o = el('option', null, options[k]);
      o.value = k;
      sel.appendChild(o);
    });
    sel.dataset.filled = keys.join(',');
    if (keep) { sel.value = keep; }
  }

  /* ---------- 待审队列 ---------- */
  function renderQueue(data) {
    var ul = $('queueList');
    var list = (data && data.pending) || [];
    ul.textContent = '';
    $('queueCount').textContent = String((data && data.count) || list.length);
    list.forEach(function (c) {
      var li = el('li', 'q-item');
      var head = el('div', 'q-head');
      head.appendChild(el('code', null, c.ticket_id || ''));
      head.appendChild(el('span', 'pill risk-' + (c.risk_level || ''), c.risk_level || '—'));
      head.appendChild(el('span', 'pill', c.basis_level || '—'));
      li.appendChild(head);
      li.appendChild(el('p', 'q-basis', '判定依据：' + (c.basis_reason || '—')));
      li.appendChild(el('p', 'q-time', '登记 ' + fmtTime(c.opened_at) + '（已等待 ' + waited(c.opened_at) + '）'));
      var btn = el('button', 'primary small', '查看并裁决');
      btn.addEventListener('click', function () { openCase(c.ticket_id); });
      li.appendChild(btn);
      ul.appendChild(li);
    });
  }

  /* ---------- 回访待办（v2.0.0 P5）：到期回访只读交付，线下动作不在系统留痕 ---------- */
  function renderFollowups(list) {
    var ul = $('followupList');
    if (!ul) { return; }
    ul.textContent = '';
    if (!list || !list.length) {
      ul.appendChild(el('li', 'muted', '暂无到期回访。'));
      return;
    }
    list.forEach(function (f) {
      var li = el('li', 'q-item');
      li.appendChild(el('p', 'q-basis',
        (f.kind || '回访') + ' · 工单 ' + (f.ticket_id || '—') + ' · 计划 ' + fmtTime(f.scheduled_at)));
      // 匿名标识不渲染明文：仅显示前八位 + 省略号，够值班员核对又不过度暴露。
      var anon = String(f.anon_key || '');
      li.appendChild(el('p', 'q-time', '对象 ' + (anon ? anon.slice(0, 8) + '…' : '—')));
      ul.appendChild(li);
    });
  }

  function loadQueue() {
    setMsg('queueMsg', '加载中…');
    return api('/api/review/pending').then(function (res) {
      show('queuePanel', true);
      if (!res.ok) { setMsg('queueMsg', errText(res, '加载待审队列失败')); return; }
      state.decisions = res.j.decisions || null;
      state.contacts = res.j.contact_kinds || null;
      fillSelect('decision', state.decisions);
      fillSelect('contactKind', state.contacts);
      renderQueue(res.j);
      renderFollowups(res.j.followups);
      var n = ((res.j && res.j.pending) || []).length;
      setMsg('queueMsg', n ? '' : '当前没有待审工单。');
    }).catch(function () { show('queuePanel', true); setMsg('queueMsg', '无法连接后端，请确认服务已启动。'); });
  }

  /* ---------- 工单详情 ---------- */
  function renderContext(items) {
    var box = $('caseContext');
    box.textContent = '';
    if (!items.length) { box.appendChild(el('p', 'muted', '（无可展示的上下文）')); return; }
    items.forEach(function (m) {
      box.appendChild(el('div', 'ctx ' + (m.role === 'user' ? 'user' : 'ai'), m.text || ''));
    });
  }
  function renderReplies(items) {
    var ul = $('caseReplies');
    ul.textContent = '';
    if (!items.length) { ul.appendChild(el('li', 'muted', '（暂无用户回信）')); return; }
    items.forEach(function (r) {
      ul.appendChild(el('li', null, fmtTime(r.date || r.fetched_at) + '：' + (r.text || r.body || '')));
    });
  }

  function openCase(ticket) {
    state.ticket = ticket;
    setMsg('caseMsg', '');
    show('caseResult', false);
    show('casePanel', true);
    $('caseTicket').textContent = ticket;
    api('/api/review/' + encodeURIComponent(ticket)).then(function (res) {
      if (!res.ok) { setMsg('caseMsg', errText(res, '加载工单详情失败')); return; }
      var j = res.j || {};
      var c = j.case || {};
      $('caseTicket').textContent = c.ticket_id || ticket;
      $('caseRisk').textContent = c.risk_level || '—';
      $('caseBasis').textContent = (c.basis_level || '—') + ' · ' + (c.basis_reason || '—');
      $('caseOpened').textContent = fmtTime(c.opened_at) + '（已等待 ' + waited(c.opened_at) + '）';
      $('caseSummary').textContent = c.context_summary || '—';
      renderContext(j.context || []);
      renderReplies(j.replies || []);
      fillSelect('decision', j.decisions || state.decisions);
      fillSelect('contactKind', j.contact_kinds || state.contacts);
      window.scrollTo(0, 0);
    }).catch(function () { setMsg('caseMsg', '无法连接后端，请确认服务已启动。'); });
  }

  function submitDecision() {
    if (!state.ticket) { return; }
    var btn = $('submitBtn');
    btn.disabled = true;
    api('/api/review/decision', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ticket_id: state.ticket,
        decision: $('decision').value,
        contact_kind: $('contactKind').value,
        reviewer: $('reviewer').value.trim()
      })
    }).then(function (res) {
      if (!res.ok) { setMsg('caseMsg', errText(res, '提交结论失败')); return; }
      var j = res.j || {};
      setMsg('caseMsg', '');
      var pre = $('caseResult');
      pre.textContent = JSON.stringify({
        台账结论: j.review,
        审计留痕: j.audit_log,
        联络动作: j.contact_log,
        次日回访: j.next_followup,
        剩余待审: j.pending
      }, null, 2);
      show('caseResult', true);
      return loadQueue();
    }).catch(function () { setMsg('caseMsg', '无法连接后端，请确认服务已启动。'); }).
      then(function () { btn.disabled = false; });
  }

  /* ---------- 鉴权 ---------- */
  function signIn(silent) {
    var t = $('token').value.trim();
    if (!t) { setMsg('authMsg', '请填写审核令牌。'); return; }
    state.token = t;
    try { sessionStorage.setItem(TKEY, t); } catch (e) { /* 隐私模式忽略 */ }
    api('/api/review/pending').then(function (res) {
      if (!res.ok) {
        setMsg('authMsg', errText(res, '鉴权失败'));
        if (!silent) { show('authPanel', true); }
        return;
      }
      setMsg('authMsg', '');
      show('authPanel', false);
      loadQueue();
    }).catch(function () { setMsg('authMsg', '无法连接后端，请确认服务已启动。'); });
  }
  function signOut() {
    state.token = '';
    state.ticket = null;
    try { sessionStorage.removeItem(TKEY); } catch (e) { /* ignore */ }
    $('queueList').textContent = '';
    var fl = $('followupList');
    if (fl) { fl.textContent = ''; }
    show('queuePanel', false);
    show('casePanel', false);
    show('authPanel', true);
    $('token').value = '';
  }

  function init() {
    $('authBtn').addEventListener('click', function () { signIn(false); });
    $('token').addEventListener('keydown', function (e) { if (e.key === 'Enter') { signIn(false); } });
    $('refreshBtn').addEventListener('click', loadQueue);
    $('signOutBtn').addEventListener('click', signOut);
    $('submitBtn').addEventListener('click', submitDecision);
    $('closeCaseBtn').addEventListener('click', function () { show('casePanel', false); });
    try {
      var saved = sessionStorage.getItem(TKEY);
      if (saved) { $('token').value = saved; signIn(true); }
    } catch (e) { /* ignore */ }
  }
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); }
  else { init(); }
})();