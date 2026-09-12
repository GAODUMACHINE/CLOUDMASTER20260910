/* CloudMaster 前端共享逻辑
   - 年龄门(<14 强拒 / 未成年需监护人信号)
   - chat 调用 /api/chat（返回 reply + risk_level + next_agent，驱动危机横幅）
   - 打字机流式观感（prefers-reduced-motion 时直接显示）
   - 危机(L2)→人工审核横幅（不放任何真实热线号码）
   - AI 内容标识 + 匿名隐私说明
   合规红线：不索要真名/照片/联系方式，不展示真实热线；动效支持 reduce-motion。 */
(function () {
  'use strict';
  var BASE = (window.CM_API_BASE || '').replace(/\/+$/, '');
  var KEY = 'cm_profile_key';
  var MINOR_KEY = 'cm_is_minor';
  var state = { key: null, risk: 'none' };

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function prefersReduced() {
    return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }
  function addMsg(text, who) {
    var m = $('chatMessages');
    var b = el('div', 'bubble ' + who);
    b.textContent = text;
    m.appendChild(b);
    m.scrollTop = m.scrollHeight;
    return b;
  }
  function typewriter(bubble, full, done) {
    if (prefersReduced()) { bubble.textContent = full; if (done) done(); return; }
    var i = 0;
    (function step() {
      i += 1;
      bubble.textContent = full.slice(0, i);
      if (i < full.length) { setTimeout(step, 8); } else if (done) { done(); }
    })();
  }
  function setTyping(on) {
    var t = $('typing');
    if (t) t.classList.toggle('show', !!on);
  }
  function setMinorFlag(isMinor) {
    document.body.dataset.minor = isMinor ? 'true' : 'false';
  }
  // 可靠文本化：后端返回 400/422 的 detail 可能是数组/对象，绝不当对象直塞 textContent（避免 [object Object]）
  function toText(v) {
    if (typeof v === 'string') { return v; }
    if (Array.isArray(v)) {
      return v.filter(Boolean).map(function (it) { return itemText(it); }).join('；');
    }
    if (v && typeof v === 'object') {
      if (v.detail) { return toText(v.detail); }
      if (v.message) { return v.message; }
      try { return JSON.stringify(v); } catch (e2) { return String(v); }
    }
    return String(v);
  }
  function fieldName(it) {
    var loc = it && it.loc;
    var last = loc && loc.length ? loc[loc.length - 1] : '';
    return (typeof last === 'string') ? last : '字段';
  }
  function itemText(it) {
    if (it && it.msg) {
      var name = fieldName(it), m = it.msg;
      if (m.indexOf('Field required') !== -1) { return '缺少必填字段：' + name; }
      if (m.toLowerCase().indexOf('integer') !== -1) { return name + ' 必须是整数'; }
      if (m.toLowerCase().indexOf('bool') !== -1) { return name + ' 必须是布尔值'; }
      return name + '：' + m;
    }
    return String(it);
  }
  function notify(msg) { var t = $('chatError'); if (t) { t.textContent = toText(msg); } }
  function showPanel(which) {
    $('registerPanel').classList.toggle('hidden', which !== 'register');
    $('chatPanel').classList.toggle('hidden', which !== 'chat');
  }
  /* ---- 设置与资源面板（申诉入口 / 一键退出 / 转介资源） ---- */
  function showSettings(on) {
    var panel = $('settingsPanel');
    if (!panel) return;
    panel.classList.toggle('hidden', !on);
    if (on) {
      $('chatPanel').classList.add('hidden');
      $('registerPanel').classList.add('hidden');
    } else {
      showPanel(state.key ? 'chat' : 'register');
    }
  }

  /* ---- 头像逻辑：注册年龄门 ---- */
  function setupRegister() {
    var age = $('age'), gu = $('guardianRow'), gb = $('guardianBox'), rej = $('ageReject'), btn = $('regBtn');
    function refresh() {
      var n = parseInt(age.value, 10);
      var under14 = n && n < 14;
      var minor = n >= 14 && n < 18;
      gu.classList.toggle('hidden', !minor);
      rej.classList.toggle('hidden', !under14);
      btn.disabled = !!under14 || (minor && !gb.checked);
    }
    age.addEventListener('input', refresh);
    gb.addEventListener('change', refresh);
    btn.addEventListener('click', function () {
      var n = parseInt(age.value, 10);
      if (!n || n < 14) { notify('年龄不足 14 岁无法使用：本产品不处理 <14 岁数据。'); return; }
      var payload = { age: n, guardian_contact_available: false, dependency_tendency: false };
      if (n < 18) { payload.guardian_contact_available = gb.checked; }
      fetch(BASE + '/api/register', { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }).
      then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); }).
      then(function (res) {
        if (!res.ok) {
          notify(res.j && (res.j.detail || res.j.message) ? (res.j.detail || res.j.message) : '注册未完成');
          return;
        }
        state.key = res.j.profile_key;
        try { localStorage.setItem(KEY, state.key); } catch (e2) {}
        try { localStorage.setItem(MINOR_KEY, n < 18 ? '1' : '0'); } catch (e3) {}
        setMinorFlag(n < 18);
        showPanel('chat');
        addMsg('你好，我是 CloudMaster 陪伴助手。感觉怎么样？','ai');
        notify('');
      }).
      catch(function () { notify('无法连接后端，请确认服务已启动。'); });
    });
    refresh();
  }

  /* ---- chat ---- */
  function setupChat() {
    var input = $('input'), send = $('sendBtn');
    function go() {
      var text = input.value.trim();
      if (!text) return;
      if (!state.key) { notify('请先完成年龄注册再开始对话。'); showPanel('register'); return; }
      input.value = '';
      send.disabled = true;
      setTyping(true);
      addMsg(text, 'user');
      var bubble = el('div', 'bubble ai typing');
      $('chatMessages').appendChild(bubble);
      fetch(BASE + '/api/chat', { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profile_key: state.key, text: text }) }).
      then(function (r) { return r.json(); }).
      then(function (j) {
        bubble.className = 'bubble ai';
        typewriter(bubble, j.reply || '', function () { setTyping(false); });
        state.risk = j.risk_level || 'none';
        updateCrisis();
      }).
      catch(function () { bubble.textContent = toText('（连接失败，请确认后端已启动）'); setTyping(false); }).
      finally(function () { send.disabled = false; });
    }
    send.addEventListener('click', go);
    input.addEventListener('keydown', function (e) { if (e.key === 'Enter') go(); });
  }

  /* ---- 危机横幅（不放任何真实热线号码） ---- */
  function updateCrisis() {
    var b = $('crisisBanner');
    if (state.risk === 'high') {
      b.classList.remove('hidden');
      $('crisisTitle').textContent = '已升级至人工审核';
      $('crisisText').textContent = '你的表达可能涉及高风险。我们已把对话升级给审核台跟进；请与信任的人或监护人谈谈。本页面不提供任何热线号码。';
    } else if (state.risk === 'low') {
      b.classList.remove('hidden');
      $('crisisTitle').textContent = '我们可以一起慢慢说';
      $('crisisText').textContent = '听起来你有些低落或压力。先深呼吸，再随时继续。';
    } else {
      b.classList.add('hidden');
    }
  }

  /* ---- AI 标识 + 隐私（必现、可关） ---- */
  function setupDisclosure() {
    var d = $('disclosure');
    var dismissed = false;
    try { dismissed = sessionStorage.getItem('cm_ai_disclosure') === '1'; } catch (e2) {}
    if (!dismissed) {
      d.classList.remove('hidden');
      var ok = $('disclosureOk');
      if (ok) ok.addEventListener('click', function () {
        d.classList.add('hidden');
        try { sessionStorage.setItem('cm_ai_disclosure', '1'); } catch (e3) {}
      });
    }
  }

  /* ---- 设置与资源：转介资源 / 申诉与投诉举报 / 一键删除退出 ---- */
  function setupSettings() {
    var open = $('openSettings'), close = $('closeSettings');
    if (open) open.addEventListener('click', function () { showSettings(true); });
    if (close) close.addEventListener('click', function () { showSettings(false); });

    // 资源与申诉类型（后端下发；红线：不含任何真实热线号码）
    fetch(BASE + '/api/resources').
    then(function (r) { return r.json(); }).
    then(function (j) {
      var ul = $('resourceList');
      if (ul && j && j.entries) {
        ul.innerHTML = '';
        j.entries.forEach(function (e) {
          var li = el('li');
          li.appendChild(el('strong', null, e.title + '：'));
          li.appendChild(document.createTextNode(e.detail || ''));
          ul.appendChild(li);
        });
      }
      var sel = $('appealKind');
      if (sel && j && j.appeals && j.appeals.kinds) {
        sel.innerHTML = '';
        Object.keys(j.appeals.kinds).forEach(function (k) {
          var o = el('option', null, j.appeals.kinds[k]);
          o.value = k;
          sel.appendChild(o);
        });
      }
    }).
    catch(function () { /* 资源加载失败不阻断对话 */ });

    var ab = $('appealBtn');
    if (ab) ab.addEventListener('click', function () {
      var msg = $('appealMsg'), text = $('appealText').value.trim();
      if (!text) { msg.textContent = '请先填写申诉说明。'; return; }
      ab.disabled = true;
      fetch(BASE + '/api/appeal', { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind: $('appealKind').value, text: text, profile_key: state.key || '' }) }).
      then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); }).
      then(function (res) {
        if (!res.ok) {
          msg.textContent = toText((res.j && (res.j.detail || res.j.message)) || '提交失败');
          return;
        }
        $('appealText').value = '';
        msg.textContent = '已受理，工单号 ' + res.j.ticket_id + '；我们会按流程跟进。';
      }).
      catch(function () { msg.textContent = '无法连接后端，请确认服务已启动。'; }).
      finally(function () { ab.disabled = false; });
    });

    var db = $('deleteBtn');
    if (db) db.addEventListener('click', function () {
      var msg = $('deleteMsg');
      if (!state.key) { msg.textContent = '当前没有可删除的匿名数据。'; return; }
      if (!window.confirm('确定删除你的匿名画像与本机会话数据吗？该操作不可恢复。')) return;
      db.disabled = true;
      fetch(BASE + '/api/profile/' + encodeURIComponent(state.key), { method: 'DELETE' }).
      then(function (r) { return r.json(); }).
      then(function () {
        try { localStorage.removeItem(KEY); } catch (e2) {}
        try { localStorage.removeItem(MINOR_KEY); } catch (e3) {}
        state.key = null;
        state.risk = 'none';
        $('chatMessages').innerHTML = '';
        setMinorFlag(false);
        updateCrisis();
        msg.textContent = '已删除，你已退出。';
        showSettings(false);
      }).
      catch(function () { msg.textContent = '删除失败，请稍后重试。'; }).
      finally(function () { db.disabled = false; });
    });
  }

  function init() {
    try { state.key = localStorage.getItem(KEY); } catch (e) {}
    if (state.key) {
      var minor = '0';
      try { minor = localStorage.getItem(MINOR_KEY) || '0'; } catch (e2) {}
      setMinorFlag(minor === '1');
      showPanel('chat');
      addMsg('欢迎回来，我可以继续陪你聊聊。','ai');
    } else {
      showPanel('register');
    }
    setupRegister();
    setupChat();
    updateCrisis();
    setupDisclosure();
    setupSettings();
  }
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); }
  else { init(); }
})();