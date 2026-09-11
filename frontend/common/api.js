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
  function notify(msg) { $('chatError').textContent = msg; }
  function showPanel(which) {
    $('registerPanel').classList.toggle('hidden', which !== 'register');
    $('chatPanel').classList.toggle('hidden', which !== 'chat');
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
      var body = { age: n, guardian_contact_available: false, dependency_tendency: false };
      if (n < 18) { body.guardian_contact_available = gb.checked; }
      fetch(BASE + '/api/register', f()).
      then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); }).
      then(function (res) {
        if (!res.ok) { notify(res.j && res.j.detail ? res.j.detail : '注册未完成'); return; }
        state.key = res.j.profile_key;
        try { localStorage.setItem(KEY, state.key); } catch (e2) {}
        setMinorFlag(n < 18);
        showPanel('chat');
        addMsg('你好，我是 CloudMaster 陪伴助手。感觉怎么样？','ai');
        notify('');
      });
    });
    refresh();
  }
  function f() { return { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '' }; }

  /* ---- chat ---- */
  function setupChat() {
    var input = $('input'), send = $('sendBtn');
    function go() {
      var text = input.value.trim();
      if (!text) return;
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
      catch(function () { bubble.textContent = '（连接失败，请确认后端已启动）'; setTyping(false); }).
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

  function init() {
    try { state.key = localStorage.getItem(KEY); } catch (e) {}
    if (state.key) {
      var savedMin = document.body.dataset.minor;
      showPanel('chat');
      addMsg('欢迎回来，我可以继续陪你聊聊。','ai');
    } else {
      showPanel('register');
    }
    setupRegister();
    setupChat();
    updateCrisis();
    setupDisclosure();
  }
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); }
  else { init(); }
})();