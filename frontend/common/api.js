/* CloudMaster 前端共享逻辑
   - 年龄门(<14 强拒 / 未成年需监护人信号)
   - chat 调用 /api/chat（返回 reply + risk_level + next_agent + escalation，驱动危机横幅）
   - 打字机流式观感（prefers-reduced-motion 时直接显示）
   - 危机(L2)→人工审核横幅（不放任何真实热线号码；高风险时展示受理编号）
   - AI 内容标识 + 匿名隐私说明
   - 情绪自评（只回区间与建议动作，绝不展示分数/诊断）
   - 隐私保留期（7/30/90 天）与一键本地导出
   - 转介资源 + 已人工审核热线条目（默认空；号码仅在审核后下发）
   合规红线：不索要真名/照片/联系方式，不展示真实热线；动效支持 reduce-motion。 */
(function () {
  'use strict';
  var BASE = (window.CM_API_BASE || '').replace(/\/+$/, '');
  var KEY = 'cm_profile_key';
  var MINOR_KEY = 'cm_is_minor';
  var state = { key: null, risk: 'none', ticket: null };
  var resourcesReq = null; // 共享 /api/resources 请求，避免重复拉取

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
    if (typeof last === 'string') {
      if (last === 'email') { return '邮箱'; }
      if (last === 'guardian_contact_available') { return '监护人可用信号'; }
      if (last === 'dependency_tendency') { return '依赖倾向'; }
      return last;
    }
    return '字段';
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

  /* ---- 头像逻辑：注册年龄门 + 注册邮箱（报告投递地址） ---- */
  function setupRegister() {
    var age = $('age'), gu = $('guardianRow'), gb = $('guardianBox'), rej = $('ageReject'), btn = $('regBtn');
    var mail = $('email'), mailErr = $('emailErr');
    function emailOk(v) {
      return /^[A-Za-z0-9._%+\-]+@[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?)*\.[A-Za-z]{2,}$/.test(v);
    }
    function refresh() {
      var n = parseInt(age.value, 10);
      var under14 = n && n < 14;
      var minor = n >= 14 && n < 18;
      gu.classList.toggle('hidden', !minor);
      rej.classList.toggle('hidden', !under14);
      var badMail = mail ? (mail.value.trim() !== '' && !emailOk(mail.value.trim())) : false;
      if (mailErr) { mailErr.classList.toggle('hidden', !badMail); }
      var noMail = mail ? mail.value.trim() === '' : true;
      btn.disabled = !!under14 || (minor && !gb.checked) || badMail || noMail;
    }
    age.addEventListener('input', refresh);
    gb.addEventListener('change', refresh);
    if (mail) { mail.addEventListener('input', refresh); }
    btn.addEventListener('click', function () {
      var n = parseInt(age.value, 10);
      if (!n || n < 14) { notify('年龄不足 14 岁无法使用：本产品不处理 <14 岁数据。'); return; }
      var addr = mail ? mail.value.trim() : '';
      if (!emailOk(addr)) { notify('请填写正确的邮箱：疏导报告需要投递地址。'); return; }
      var payload = {
        age: n, email: addr, guardian_contact_available: false, dependency_tendency: false
      };
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
        setupPrivacy();
        setupReport();
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
        state.risk = j.risk_level || 'none';
        if (j.held_for_review) {
          // 挂起态（L2 待人工审核）：自动回复已暂停，安全提示立即整段呈现，不做逐字动画。
          bubble.textContent = j.reply || '';
          setTyping(false);
        } else {
          typewriter(bubble, j.reply || '', function () { setTyping(false); });
        }
        // 高风险时后端会登记审核台并回传受理编号；仅用于横幅展示，不做任何跳转。
        state.ticket = (j.escalation && j.escalation.ticket_id) ? j.escalation.ticket_id : null;
        updateCrisis();
      }).
      catch(function () { bubble.textContent = toText('（连接失败，请确认后端已启动）'); setTyping(false); }).
      finally(function () { send.disabled = false; });
    }
    send.addEventListener('click', go);
    input.addEventListener('keydown', function (e) { if (e.key === 'Enter') go(); });
  }

  /* ---- 危机横幅（不放任何真实热线号码） ---- */
  function updateCrisis(escalation) {
    var ticket = null;
    if (escalation && escalation.ticket_id) { ticket = escalation.ticket_id; }
    else if (state.ticket) { ticket = state.ticket; }
    state.ticket = ticket;
    var b = $('crisisBanner');
    if (!b) { return; }
    if (state.risk === 'high') {
      b.classList.remove('hidden');
      $('crisisTitle').textContent = '已升级至人工审核';
      var line = '你的表达可能涉及高风险。我们已把对话升级给审核台跟进；请与信任的人或监护人谈谈。本页面不提供任何热线号码。';
      if (ticket) { line += '受理编号 ' + ticket + '，人工审核台会跟进。'; }
      $('crisisText').textContent = line;
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

  /* ---- 共享 /api/resources（设置面板与热线条目共用同一次请求） ---- */
  function loadResources() {
    if (resourcesReq) { return resourcesReq; }
    resourcesReq = fetch(BASE + '/api/resources').
    then(function (r) { return r.json(); }).
    catch(function () { return null; }); // 资源加载失败不阻断对话
    return resourcesReq;
  }

  /* ---- 转介资源渲染：entries（原有）+ 已审核 hotlines（可为空数组，空即不渲染） ---- */
  function renderResources(j) {
    if (!j) { return; }
    var ul = $('resourceList');
    if (ul) {
      ul.innerHTML = '';
      if (j.entries) {
        j.entries.forEach(function (e) {
          var li = el('li');
          li.appendChild(el('strong', null, (e.title || '') + '：'));
          li.appendChild(document.createTextNode(e.detail || ''));
          ul.appendChild(li);
        });
      }
      if (j.hotlines && j.hotlines.length) {
        j.hotlines.forEach(function (h) {
          var li2 = el('li');
          li2.appendChild(el('strong', null, (h.title || '') + '：'));
          li2.appendChild(document.createTextNode(h.detail || ''));
          if (h.tel) { li2.appendChild(el('span', 'hotline-tel', h.tel)); }
          ul.appendChild(li2);
        });
      }
    }
    var sel = $('appealKind');
    if (sel && j.appeals && j.appeals.kinds) {
      sel.innerHTML = '';
      Object.keys(j.appeals.kinds).forEach(function (k) {
        var o = el('option', null, j.appeals.kinds[k]);
        o.value = k;
        sel.appendChild(o);
      });
    }
  }

  /* ---- 已审核热线条目（与设置面板共享同一次 /api/resources 请求） ---- */
  function setupHotlines() {
    loadResources().then(renderResources);
  }

  /* ---- 情绪自评（3.1.3-7）：只呈现区间与建议动作，绝不展示分数 ---- */
  function setupAssessment() {
    var host = $('assessmentForm');
    if (!host) { return; }
    var res = $('assessmentResult');
    var disc = $('assessmentDisclaimer');
    // 请求失败时表单保持隐藏，不影响页面其余部分（自评是可选入口）。
    fetch(BASE + '/api/assessment/items').
    then(function (r) { return r.json(); }).
    then(function (j) {
      if (!j || !j.items || !j.items.length) { return; }
      var choices = j.choices || [];
      var selects = {};
      var form = el('div', 'assessment-items');
      j.items.forEach(function (it) {
        var label = el('label', 'field small');
        label.appendChild(document.createTextNode(it.text || ''));
        var sel = el('select');
        choices.forEach(function (c) {
          var o = el('option', null, c.label);
          o.value = c.value;
          sel.appendChild(o);
        });
        label.appendChild(sel);
        form.appendChild(label);
        selects[it.id] = sel;
      });
      var btn = el('button', 'primary compact', '提交自评');
      var err = el('p', 'privacy micro');
      host.innerHTML = '';
      host.appendChild(form);
      host.appendChild(btn);
      host.appendChild(err);
      if (disc) { disc.textContent = j.disclaimer || ''; }
      btn.addEventListener('click', function () {
        if (!res) { return; }
        var answers = {};
        Object.keys(selects).forEach(function (id) { answers[id] = selects[id].value; });
        btn.disabled = true;
        err.textContent = '提交中…';
        fetch(BASE + '/api/assessment', { method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ answers: answers }) }).
        then(function (r) { return r.json().then(function (j2) { return { ok: r.ok, j: j2 }; }); }).
        then(function (out) {
          var k = out.j || {};
          if (!out.ok) {
            err.textContent = toText(k.detail || k.message || '自评未完成，请稍后重试。');
            return;
          }
          err.textContent = '';
          // 只用 band + advice + disclaimer 三段文字，绝不渲染任何分数。
          res.className = 'assessment-result';
          res.innerHTML = '';
          res.appendChild(el('span', 'band', '自评区间：' + (k.band || '')));
          res.appendChild(el('p', null, k.advice || ''));
          if (k.disclaimer) { res.appendChild(el('p', 'disclaimer', k.disclaimer)); }
          if (k.urgent === true) {
            res.classList.add('urgent');
            if (k.urgent_message) { res.appendChild(el('p', 'urgent-note', k.urgent_message)); }
            if (k.entry) {
              res.appendChild(el('p', 'entry-note', '可打开「求助与转介资源」查看可用的转介入口（本页不会自动跳转）。'));
            }
          }
        }).
        catch(function () { err.textContent = '无法连接后端，请确认服务已启动。'; }).
        finally(function () { btn.disabled = false; });
      });
    }).
    catch(function () { /* 自评加载失败：保持隐藏，不阻断对话 */ });
  }

  /* ---- 隐私：保留期（7/30/90 天）+ 一键本地导出（数据只回传本人） ---- */
  function setupPrivacy() {
    var sel = $('retentionDays'), exp = $('exportBtn');
    var rMsg = $('retentionMsg'), eMsg = $('exportMsg');
    if (!state.key) {
      if (sel) { sel.disabled = true; }
      if (exp) { exp.disabled = true; }
      if (rMsg) { rMsg.textContent = '完成年龄注册后可设置会话保留期。'; }
      return;
    }
    var key = encodeURIComponent(state.key);
    if (sel) {
      var current = null;
      var allowChange = false; // 仅在初始化完成后才响应 change，避免填充选项触发误提交
      sel.addEventListener('change', function () {
        if (!allowChange) { return; }
        var prev = current;
        var days = parseInt(sel.value, 10);
        if (isNaN(days)) { return; }
        sel.disabled = true;
        if (rMsg) { rMsg.textContent = '正在保存…'; }
        fetch(BASE + '/api/privacy/' + key + '/retention', { method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ days: days }) }).
        then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); }).
        then(function (out) {
          var k = out.j || {};
          if (!out.ok) {
            if (rMsg) { rMsg.textContent = toText(k.detail || k.message || '保留期未更新'); }
            sel.value = (prev === null ? '' : String(prev)); // 失败回退到原值
            return;
          }
          var rec = k.retention || {};
          current = rec.retention_days || days;
          sel.value = String(current);
          var when = k.purge && k.purge.delete_after ? k.purge.delete_after : '';
          if (rMsg) {
            rMsg.textContent = '保留期已设为 ' + current + ' 天' + (when ? ('，到期删除时间 ' + when) : '');
          }
        }).
        catch(function () {
          if (rMsg) { rMsg.textContent = '无法连接后端，请确认服务已启动。'; }
          sel.value = (prev === null ? '' : String(prev));
        }).
        finally(function () { sel.disabled = false; });
      });
      fetch(BASE + '/api/privacy/' + key).
      then(function (r) { return r.json(); }).
      then(function (j) {
        var choices = (j && j.choices && j.choices.length) ? j.choices : [7, 30, 90];
        var initial = (j && j.retention && j.retention.retention_days) || choices[0];
        sel.innerHTML = '';
        choices.forEach(function (d) {
          var o = el('option', null, d + ' 天');
          o.value = String(d);
          sel.appendChild(o);
        });
        // 先落到首项，再设为目标值：即使目标值不在 choices 中也能正确回退
        sel.value = String(choices[0]);
        sel.value = String(initial);
        current = parseInt(sel.value, 10);
        if (isNaN(current)) { current = choices[0]; }
        allowChange = true;
      }).
      catch(function () {
        if (rMsg) { rMsg.textContent = '无法读取保留期设置。'; }
        sel.disabled = true;
      });
    }
    if (exp) exp.addEventListener('click', function () {
      // 导出：只在本地生成文件下载，内容不发给任何人。
      exp.disabled = true;
      if (eMsg) { eMsg.textContent = '正在生成导出文件…'; }
      fetch(BASE + '/api/privacy/' + key + '/export').
      then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); }).
      then(function (out) {
        var k = out.j || {};
        if (!out.ok) {
          if (eMsg) { eMsg.textContent = toText(k.detail || k.message || '导出失败，请稍后重试。'); }
          return;
        }
        try {
          var blob = new Blob([JSON.stringify(k, null, 2)], { type: 'application/json' });
          var url = URL.createObjectURL(blob);
          var a = document.createElement('a');
          a.href = url;
          a.download = 'cloudmaster-export.json';
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          setTimeout(function () { URL.revokeObjectURL(url); }, 0);
          var n = (k && typeof k.message_count === 'number') ? k.message_count : 0;
          if (eMsg) { eMsg.textContent = '导出已开始下载（cloudmaster-export.json），共 ' + n + ' 条会话记录。'; }
        } catch (e3) {
          if (eMsg) { eMsg.textContent = '浏览器不支持本地导出，请更换浏览器后重试。'; }
        }
      }).
      catch(function () { if (eMsg) { eMsg.textContent = '无法连接后端，请确认服务已启动。'; } }).
      finally(function () { exp.disabled = false; });
    });
  }

  /* ---- 设置与资源：转介资源 / 申诉与投诉举报 / 一键删除退出 ---- */
  function setupSettings() {
    var open = $('openSettings'), close = $('closeSettings');
    if (open) open.addEventListener('click', function () { showSettings(true); });
    if (close) close.addEventListener('click', function () { showSettings(false); });

    // 资源与申诉类型（后端下发；红线：不含任何真实热线号码）
    loadResources().then(renderResources);

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
        state.ticket = null;
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

  /* ---- 疏导报告：生成预览 → 用户确认 → 发送（产品级 HITL，绝不自动发送） ---- */
  function setupReport() {
    var btn = $('reportBtn'), sendBtn = $('reportSendBtn');
    var prev = $('reportPreview'), msg = $('reportMsg');
    if (!btn) { return; }
    if (!state.key) {
      btn.disabled = true;
      if (msg) { msg.textContent = '完成年龄注册后可生成并接收疏导报告。'; }
      return;
    }
    var draft = null;
    function render(p) {
      var lines = [];
      if (p.recipient) { lines.push('投递邮箱：' + p.recipient); }
      lines.push('会话概况：你的发言 ' + p.user_turns + ' 次 / 陪伴回复 ' + p.ai_turns + ' 次');
      lines.push('当前风险分级：' + (p.risk_label || '平稳'));
      lines.push('');
      lines.push(p.body || '');
      return lines.join('\n');
    }
    btn.addEventListener('click', function () {
      btn.disabled = true;
      if (msg) { msg.textContent = '正在生成预览…'; }
      if (prev) { prev.classList.add('hidden'); }
      if (sendBtn) { sendBtn.classList.add('hidden'); }
      fetch(BASE + '/api/report/' + encodeURIComponent(state.key)).
      then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); }).
      then(function (res) {
        if (!res.ok) {
          if (msg) { msg.textContent = toText((res.j && (res.j.detail || res.j.message)) || '生成失败'); }
          return;
        }
        draft = res.j;
        if (prev) { prev.textContent = render(draft); prev.classList.remove('hidden'); }
        if (!draft.opt_in) {
          if (msg) { msg.textContent = '你已退订报告；如需接收请先重新开启。'; }
          return;
        }
        if (sendBtn) { sendBtn.classList.remove('hidden'); }
        if (msg) {
          msg.textContent = draft.mail_channel_ready
            ? '请先阅读上面的预览；确认无误后再点下方按钮发送。'
            : '提示：后端未配置邮件通道（SMTP），当前无法发送。';
        }
      }).
      catch(function () { if (msg) { msg.textContent = '无法连接后端，请确认服务已启动。'; } }).
      finally(function () { btn.disabled = false; });
    });
    if (sendBtn) sendBtn.addEventListener('click', function () {
      if (!draft) { return; }
      // 二次确认：明确告知将要发送到哪个邮箱，避免误发。
      if (!window.confirm('确认把这份报告发送到 ' + (draft.recipient || '你的注册邮箱') + ' 吗？')) return;
      sendBtn.disabled = true;
      if (msg) { msg.textContent = '正在发送…'; }
      fetch(BASE + '/api/report/send', { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ report_id: draft.report_id, confirm_token: draft.confirm_token }) }).
      then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); }).
      then(function (res) {
        var j = res.j || {};
        if (!res.ok) {
          if (msg) { msg.textContent = toText(j.detail || j.message || '发送失败'); }
          return;
        }
        if (j.sent) {
          if (msg) { msg.textContent = '已发送到 ' + (j.delivery && j.delivery.to ? j.delivery.to : draft.recipient) + '。'; }
          sendBtn.classList.add('hidden');
          draft = null;
        } else {
          if (msg) { msg.textContent = j.reason || '未发送。'; }
        }
      }).
      catch(function () { if (msg) { msg.textContent = '无法连接后端，请确认服务已启动。'; } }).
      finally(function () { sendBtn.disabled = false; });
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
    setupAssessment();
    setupPrivacy();
    setupReport();
    setupHotlines();
  }
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); }
  else { init(); }
})();
