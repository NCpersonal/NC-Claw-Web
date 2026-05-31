/* global fetch, AbortSignal, localStorage, document, navigator, requestAnimationFrame */

// ━━━ State ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

var gatewayUrl = localStorage.getItem('claw_gw_url') || 'http://localhost:8765';
var connMode = localStorage.getItem('claw_mode') || 'stream';
var reqTimeout = parseInt(localStorage.getItem('claw_timeout') || '120');
var isConnected = false;
var isStreaming = false;
var currentMode = localStorage.getItem('claw_current_mode') || 'default';
var currentTarget = localStorage.getItem('claw_current_target') || '';
var convHistory = {};
var agents = {};
var groups = {};
var logs = [];
var consoleHistory = [];
var consoleHistIdx = -1;
var lastAgentHash = '';

var agentModalMode = 'create';
var agentModalTarget = '';
var groupModalMode = 'create';
var groupModalTarget = '';

var AVATAR_COLORS = { 0: '#00ff88', 1: '#4488ff', 2: '#ff44cc', 3: '#ffb800', 4: '#ff3355', 5: '#00d4ff' };

// ━━━ History Persistence ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function saveConvHistory() {
  try {
    var toSave = {};
    Object.keys(convHistory).forEach(function (key) {
      var conv = convHistory[key];
      if (conv.length > 200) conv = conv.slice(-200);
      toSave[key] = conv;
    });
    localStorage.setItem('claw_conv_history', JSON.stringify(toSave));
  } catch (e) {
    // localStorage full — trim more aggressively
    try {
      var trimmed = {};
      Object.keys(convHistory).forEach(function (key) {
        trimmed[key] = convHistory[key].slice(-50);
      });
      localStorage.setItem('claw_conv_history', JSON.stringify(trimmed));
    } catch (e2) {
      localStorage.removeItem('claw_conv_history');
    }
  }
}

function loadConvHistory() {
  try {
    var saved = localStorage.getItem('claw_conv_history');
    if (saved) {
      var parsed = JSON.parse(saved);
      Object.keys(parsed).forEach(function (key) {
        convHistory[key] = parsed[key];
      });
    }
  } catch (e) {
    convHistory = {};
  }
}

function saveCurrentChat() {
  localStorage.setItem('claw_current_mode', currentMode);
  localStorage.setItem('claw_current_target', currentTarget);
}

// ━━━ Init ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

document.addEventListener('DOMContentLoaded', function () {
  loadConvHistory();
  loadSettings();
  renderMessages();
  checkHealth();

  var ta = document.getElementById('userInput');
  ta.addEventListener('input', function () {
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 150) + 'px';
  });
  ta.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });

  var ci = document.getElementById('consoleInput');
  ci.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') { runConsoleCommand(); return; }
    if (e.key === 'ArrowUp') {
      if (consoleHistIdx < consoleHistory.length - 1) {
        consoleHistIdx++;
        ci.value = consoleHistory[consoleHistory.length - 1 - consoleHistIdx];
      }
      e.preventDefault();
    }
    if (e.key === 'ArrowDown') {
      if (consoleHistIdx > 0) { consoleHistIdx--; ci.value = consoleHistory[consoleHistory.length - 1 - consoleHistIdx]; }
      else { consoleHistIdx = -1; ci.value = ''; }
      e.preventDefault();
    }
  });

  ['settingsModal', 'agentModal', 'groupModal'].forEach(function (id) {
    document.getElementById(id).addEventListener('click', function (e) {
      if (e.target === e.currentTarget) { e.target.classList.remove('open'); }
    });
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      ['settingsModal', 'agentModal', 'groupModal'].forEach(function (id) {
        document.getElementById(id).classList.remove('open');
      });
    }
  });

  addLog('info', 'Claw Chat initialized');

  // Periodic auto-refresh sidebar
  setInterval(function () {
    if (isConnected) refreshSidebar();
  }, 10000);
});

// ━━━ Settings ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function loadSettings() {
  document.getElementById('cfgUrl').value = gatewayUrl;
  document.getElementById('cfgMode').value = connMode;
  document.getElementById('cfgTimeout').value = reqTimeout;
}

function openSettings() { loadSettings(); document.getElementById('settingsModal').classList.add('open'); }
function closeSettings() { document.getElementById('settingsModal').classList.remove('open'); }
function saveSettings() {
  gatewayUrl = document.getElementById('cfgUrl').value.replace(/\/+$/, '');
  connMode = document.getElementById('cfgMode').value;
  reqTimeout = parseInt(document.getElementById('cfgTimeout').value) || 120;
  localStorage.setItem('claw_gw_url', gatewayUrl);
  localStorage.setItem('claw_mode', connMode);
  localStorage.setItem('claw_timeout', reqTimeout);
  closeSettings();
  addLog('info', 'Settings saved: ' + gatewayUrl);
  checkHealth();
}
function setSudoPassword() {
  var pw = document.getElementById('cfgSudo').value;
  if (!pw) return;
  fetch(gatewayUrl + '/api/sudo', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password: pw })
  }).then(function (r) { return r.json(); })
    .then(function (data) {
      if (data.ok) {
        document.getElementById('cfgSudo').value = '';
        addLog('info', 'Sudo password set');
      }
    }).catch(function (e) { addLog('error', e.message); });
}

function clearSudoPassword() {
  fetch(gatewayUrl + '/api/sudo', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ clear: true })
  }).then(function (r) { return r.json(); })
    .then(function (data) {
      document.getElementById('cfgSudo').value = '';
      addLog('info', 'Sudo password cleared');
    }).catch(function (e) { addLog('error', e.message); });
}


// ━━━ Health ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function checkHealth() {
  var dot = document.getElementById('statusDot');
  var text = document.getElementById('statusText');
  fetch(gatewayUrl + '/api/health', { signal: AbortSignal.timeout(5000) })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      var wasConnected = isConnected;
      isConnected = true;
      dot.className = 'status-dot online';
      text.textContent = 'connected \u00b7 ' + data.model;
      hideError();
      if (!wasConnected) {
        addLog('success', 'Connected (' + data.model + ')');
      }
      refreshSidebar();
    })
    .catch(function () {
      isConnected = false;
      dot.className = 'status-dot offline';
      text.textContent = 'disconnected';
      showError('Cannot connect to ' + gatewayUrl);
    });
}

// ━━━ Log ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function addLog(type, msg) {
  logs.push({ time: new Date(), type: type, message: msg });
  if (logs.length > 500) logs = logs.slice(-300);
  var container = document.getElementById('logOutput');
  if (!container) return;
  var el = document.createElement('div');
  el.className = 'log-line ' + type;
  el.innerHTML = '<span class="log-time">' + formatTime() + '</span><span class="log-msg">' + escapeHtml(msg) + '</span>';
  container.appendChild(el);
  container.scrollTop = container.scrollHeight;
}

// ━━━ Console ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function toggleConsole() {
  var panel = document.getElementById('consolePanel');
  var btn = document.getElementById('consoleToggleBtn');
  panel.classList.toggle('open');
  btn.classList.toggle('active', panel.classList.contains('open'));
}

function switchConsoleTab(tab, btn) {
  document.querySelectorAll('.console-tab').forEach(function (t) { t.classList.remove('active'); });
  document.querySelectorAll('.console-view').forEach(function (v) { v.classList.remove('active'); });
  btn.classList.add('active');
  document.getElementById(tab === 'exec' ? 'consoleViewExec' : 'consoleViewLog').classList.add('active');
}

function appendConsoleLine(type, text) {
  var out = document.getElementById('consoleOutput');
  var el = document.createElement('div');
  el.className = 'console-line ' + type;
  el.innerHTML = '<span class="time">' + formatTime() + '</span>' + escapeHtml(text);
  out.appendChild(el);
  out.scrollTop = out.scrollHeight;
}

function runConsoleCommand() {
  var input = document.getElementById('consoleInput');
  var cmd = input.value.trim();
  if (!cmd) return;
  input.value = '';
  consoleHistory.push(cmd);
  consoleHistIdx = -1;
  appendConsoleLine('cmd', '$ ' + cmd);
  addLog('command', cmd);
  if (!isConnected) { appendConsoleLine('error', 'Not connected'); return; }
  appendConsoleLine('result', 'Running...');
  fetch(gatewayUrl + '/api/exec', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ command: cmd }), signal: AbortSignal.timeout(60000)
  })
  .then(function (r) { return r.json(); })
  .then(function (data) {
    var out = document.getElementById('consoleOutput');
    if (out.lastChild) out.removeChild(out.lastChild);
    if (data.error) { appendConsoleLine('error', 'Error: ' + data.error); }
    else { appendConsoleLine('result', data.result || '(no output)'); }
  })
  .catch(function (e) {
    var out = document.getElementById('consoleOutput');
    if (out.lastChild) out.removeChild(out.lastChild);
    appendConsoleLine('error', 'Error: ' + e.message);
  });
}

// ━━━ Sidebar ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function refreshSidebar() {
  if (!isConnected) return;

  Promise.all([
    fetch(gatewayUrl + '/api/agents').then(function (r) { return r.json(); }).catch(function () { return {}; }),
    fetch(gatewayUrl + '/api/groups').then(function (r) { return r.json(); }).catch(function () { return {}; })
  ]).then(function (results) {
    var newAgents = {};
    if (results[0].agents) results[0].agents.forEach(function (a) { newAgents[a.name] = a; });
    var newGroups = {};
    if (results[1].groups) results[1].groups.forEach(function (g) { newGroups[g.name] = g; });

    agents = newAgents;
    groups = newGroups;

    // If current target no longer exists, reset to default
    if (currentMode === 'agent' && currentTarget && !agents[currentTarget]) {
      currentMode = 'default'; currentTarget = ''; saveCurrentChat(); renderMessages();
    }
    if (currentMode === 'group' && currentTarget && !groups[currentTarget]) {
      currentMode = 'default'; currentTarget = ''; saveCurrentChat(); renderMessages();
    }

    renderSidebarList();
  });
}

function renderSidebarList() {
  var list = document.getElementById('sidebarList');
  var html = '<div class="chat-item ' + (currentMode === 'default' ? 'active' : '') + '" data-mode="default" data-target="" onclick="switchChat(this)"><span class="icon">\ud83d\udcac</span><span class="name">Claw (Default)</span></div>';

  Object.keys(agents).forEach(function (name) {
    var a = agents[name];
    var color = AVATAR_COLORS[(a.color_idx || 0) % 6] || '#00ff88';
    var active = currentMode === 'agent' && currentTarget === name;
    var model = (a.effective_api && a.effective_api.model) || '';
    html += '<div class="chat-item ' + (active ? 'active' : '') + '" data-mode="agent" data-target="' + name + '" onclick="switchChat(this)" title="' + escapeHtml(a.role || '') + '\n' + escapeHtml(model) + '">' +
      '<span class="color-dot" style="background:' + color + '"></span>' +
      '<span class="name">' + escapeHtml(a.display_name || name) + '</span>' +
      '<div class="item-actions">' +
      '<button class="item-action-btn" onclick="event.stopPropagation();openEditAgent(\'' + name + '\')">\u2699</button>' +
      '<button class="item-action-btn danger" onclick="event.stopPropagation();deleteAgent(\'' + name + '\')">\u2715</button>' +
      '</div></div>';
  });

  Object.keys(groups).forEach(function (name) {
    var g = groups[name];
    var active = currentMode === 'group' && currentTarget === name;
    html += '<div class="chat-item ' + (active ? 'active' : '') + '" data-mode="group" data-target="' + name + '" onclick="switchChat(this)">' +
      '<span class="icon">\ud83d\udc65</span>' +
      '<span class="name">' + escapeHtml(name) + '</span>' +
      '<span class="badge">' + (g.members || []).length + '</span>' +
      '<div class="item-actions">' +
      '<button class="item-action-btn" onclick="event.stopPropagation();openEditGroup(\'' + name + '\')">\u2699</button>' +
      '<button class="item-action-btn danger" onclick="event.stopPropagation();deleteGroup(\'' + name + '\')">\u2715</button>' +
      '</div></div>';
  });

  list.innerHTML = html;

  // Update topbar to match current mode
  updateTopbar();
}

function updateTopbar() {
  var title = document.getElementById('chatTitle');
  var meta = document.getElementById('chatMeta');
  if (currentMode === 'default') {
    title.textContent = '\ud83d\udc3e Claw (Default)';
    meta.textContent = 'Default mode \u00b7 Global API';
  } else if (currentMode === 'agent') {
    var a = agents[currentTarget];
    title.textContent = a ? a.display_name : currentTarget;
    meta.textContent = 'Agent: @' + currentTarget;
  } else if (currentMode === 'group') {
    title.textContent = '\ud83d\udc65 ' + currentTarget;
    var g = groups[currentTarget];
    meta.textContent = 'Group \u00b7 ' + (g ? (g.members || []).map(function (m) { return '@' + m; }).join(' ') : '');
  }
}

function switchChat(el) {
  document.querySelectorAll('.chat-item').forEach(function (c) { c.classList.remove('active'); });
  el.classList.add('active');
  currentMode = el.dataset.mode;
  currentTarget = el.dataset.target;
  saveCurrentChat();
  updateTopbar();
  renderMessages();
}

// ━━━ Agent Modal ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function openAgentModal() {
  agentModalMode = 'create'; agentModalTarget = '';
  document.getElementById('agentModalTitle').textContent = 'Create Agent';
  document.getElementById('agentModalSaveBtn').textContent = 'Create';
  document.getElementById('agentId').value = ''; document.getElementById('agentId').disabled = false;
  document.getElementById('agentDisplayName').value = '';
  document.getElementById('agentRole').value = '';
  document.getElementById('agentApiKey').value = '';
  document.getElementById('agentApiBase').value = '';
  document.getElementById('agentModel').value = '';
  document.getElementById('agentModal').classList.add('open');
  document.getElementById('agentId').focus();
}

function openEditAgent(name) {
  agentModalMode = 'edit'; agentModalTarget = name;
  var a = agents[name];
  document.getElementById('agentModalTitle').textContent = 'Edit: ' + name;
  document.getElementById('agentModalSaveBtn').textContent = 'Save';
  document.getElementById('agentId').value = name; document.getElementById('agentId').disabled = true;
  document.getElementById('agentDisplayName').value = a.display_name || '';
  document.getElementById('agentRole').value = a.role || '';
  document.getElementById('agentApiKey').value = '';
  document.getElementById('agentApiBase').value = '';
  document.getElementById('agentModel').value = '';
  document.getElementById('agentModal').classList.add('open');
}

function closeAgentModal() { document.getElementById('agentModal').classList.remove('open'); }

function saveAgent() {
  var name = document.getElementById('agentId').value.trim().toLowerCase();
  var dn = document.getElementById('agentDisplayName').value.trim();
  var role = document.getElementById('agentRole').value.trim();
  var key = document.getElementById('agentApiKey').value.trim();
  var base = document.getElementById('agentApiBase').value.trim();
  var model = document.getElementById('agentModel').value.trim();
  if (!name) { alert('Agent ID required'); return; }
  if (!/^[a-zA-Z]\w*$/.test(name)) { alert('Invalid ID'); return; }
  var body = { action: agentModalMode === 'create' ? 'create' : 'update', name: name,
    display_name: dn || name.charAt(0).toUpperCase() + name.slice(1),
    role: role || 'You are a helpful assistant.' };
  if (key) body.api_key = key;
  if (base) body.api_base = base;
  if (model) body.model = model;
  fetch(gatewayUrl + '/api/agents', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (data.error) { alert(data.error); return; }
      closeAgentModal();
      addLog('success', (agentModalMode === 'create' ? 'Created' : 'Updated') + ' agent: ' + name);
      refreshSidebar();
    })
    .catch(function (e) { alert(e.message); });
}

function deleteAgent(name) {
  if (!confirm('Delete "' + name + '"?')) return;
  fetch(gatewayUrl + '/api/agents', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'delete', name: name }) })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (data.error) { alert(data.error); return; }
      if (currentMode === 'agent' && currentTarget === name) {
        currentMode = 'default'; currentTarget = ''; saveCurrentChat(); renderMessages();
      }
      delete convHistory['agent:' + name];
      saveConvHistory();
      addLog('warn', 'Deleted agent: ' + name);
      refreshSidebar();
    })
    .catch(function (e) { alert(e.message); });
}

// ━━━ Group Modal ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function openGroupModal() {
  groupModalMode = 'create'; groupModalTarget = '';
  document.getElementById('groupModalTitle').textContent = 'Create Group';
  document.getElementById('groupModalSaveBtn').textContent = 'Create';
  document.getElementById('groupId').value = ''; document.getElementById('groupId').disabled = false;
  document.getElementById('groupDesc').value = '';
  renderGroupMembers([]);
  document.getElementById('groupModal').classList.add('open');
  document.getElementById('groupId').focus();
}

function openEditGroup(name) {
  groupModalMode = 'edit'; groupModalTarget = name;
  var g = groups[name];
  document.getElementById('groupModalTitle').textContent = 'Edit: ' + name;
  document.getElementById('groupModalSaveBtn').textContent = 'Save';
  document.getElementById('groupId').value = name; document.getElementById('groupId').disabled = true;
  document.getElementById('groupDesc').value = g.desc || '';
  renderGroupMembers(g.members || []);
  document.getElementById('groupModal').classList.add('open');
}

function closeGroupModal() { document.getElementById('groupModal').classList.remove('open'); }

function renderGroupMembers(selected) {
  var c = document.getElementById('groupMembersList');
  var names = Object.keys(agents);
  if (!names.length) { c.innerHTML = '<div style="color:var(--text4);font-size:0.8rem;padding:0.5rem;">No agents. Create agents first.</div>'; return; }
  var html = '';
  names.forEach(function (name) {
    var a = agents[name];
    var color = AVATAR_COLORS[(a.color_idx || 0) % 6] || '#00ff88';
    var checked = selected.indexOf(name) >= 0 ? 'checked' : '';
    html += '<label class="member-checkbox"><input type="checkbox" name="gm" value="' + name + '" ' + checked + '><span class="color-dot" style="background:' + color + ';width:8px;height:8px;border-radius:50%;flex-shrink:0;"></span><span class="cb-name">' + escapeHtml(a.display_name || name) + '</span></label>';
  });
  c.innerHTML = html;
}

function saveGroup() {
  var name = document.getElementById('groupId').value.trim().toLowerCase();
  var desc = document.getElementById('groupDesc').value.trim();
  var cbs = document.querySelectorAll('#groupMembersList input[name="gm"]:checked');
  var members = []; cbs.forEach(function (cb) { members.push(cb.value); });
  if (!name) { alert('Name required'); return; }
  if (!members.length) { alert('Select members'); return; }
  var body = { action: groupModalMode === 'create' ? 'create' : 'update', name: name, description: desc, members: members };
  fetch(gatewayUrl + '/api/groups', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (data.error) { alert(data.error); return; }
      closeGroupModal();
      addLog('success', (groupModalMode === 'create' ? 'Created' : 'Updated') + ' group: ' + name);
      refreshSidebar();
    })
    .catch(function (e) { alert(e.message); });
}

function deleteGroup(name) {
  if (!confirm('Delete "' + name + '"?')) return;
  fetch(gatewayUrl + '/api/groups', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'delete', name: name }) })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (data.error) { alert(data.error); return; }
      if (currentMode === 'group' && currentTarget === name) {
        currentMode = 'default'; currentTarget = ''; saveCurrentChat(); renderMessages();
      }
      delete convHistory['group:' + name];
      saveConvHistory();
      addLog('warn', 'Deleted group: ' + name);
      refreshSidebar();
    })
    .catch(function (e) { alert(e.message); });
}

// ━━━ Content Formatting ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function escapeHtml(text) {
  var d = document.createElement('div');
  d.textContent = text;
  return d.innerHTML;
}

var LANG_MAP = { 'python': 'Python', 'py': 'Python', 'javascript': 'JavaScript', 'js': 'JavaScript', 'typescript': 'TypeScript', 'bash': 'Bash', 'sh': 'Shell', 'html': 'HTML', 'css': 'CSS', 'json': 'JSON', 'yaml': 'YAML', 'sql': 'SQL', 'java': 'Java', 'go': 'Go', 'rust': 'Rust' };

function highlightCode(code, lang) {
  var h = escapeHtml(code);
  if (!lang || ['text', 'plain', 'txt'].indexOf(lang) >= 0) return h;
  h = h.replace(/(\/\/.*$|#.*$)/gm, '<span class="cm">$1</span>');
  h = h.replace(/(\/\*[\s\S]*?\*\/)/g, '<span class="cm">$1</span>');
  h = h.replace(/(&quot;[^&]*?&quot;|&#39;[^&]*?&#39;|"[^"]*?"|'[^']*?')/g, '<span class="str">$1</span>');
  var kw = 'function|def|class|if|else|elif|for|while|return|import|from|export|const|let|var|try|catch|finally|async|await|yield|new|this|self|None|null|undefined|true|false|print|len|range|type|with|as|in|not|and|or|interface|struct|enum|match|case|switch|break|continue|pass|raise|assert';
  h = h.replace(new RegExp('\\b(' + kw + ')\\b'), '<span class="kw">$1</span>');
  h = h.replace(/\b(\d+\.?\d*)\b/g, '<span class="num">$1</span>');
  h = h.replace(/\b([a-zA-Z_]\w*)\s*\(/g, '<span class="fn">$1</span>(');
  return h;
}

function formatContent(text) {
  if (!text) return '';
  var cbs = []; var ph = '\x00CB_';
  var p = text.replace(/```(\w*)\n([\s\S]*?)```/g, function (_, l, c) { var i = cbs.length; cbs.push({ lang: l, code: c.replace(/\n$/, '') }); return ph + i + '\x00'; });
  p = escapeHtml(p);
  p = p.replace(/`([^`\x00]+?)`/g, '<code>$1</code>');
  p = p.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  for (var i = 0; i < cbs.length; i++) {
    var b = cbs[i]; var ll = LANG_MAP[b.lang.toLowerCase()] || b.lang || 'Code';
    p = p.replace(ph + i + '\x00', '<div class="code-block"><div class="code-header"><span class="lang">' + escapeHtml(ll) + '</span><button class="copy-btn" onclick="copyCode(this)" data-code="' + escapeHtml(b.code).replace(/"/g, '&quot;') + '">Copy</button></div><pre>' + highlightCode(b.code, b.lang) + '</pre></div>');
  }
  return p;
}

function formatContentLite(text) {
  if (!text) return '';
  var h = escapeHtml(text);
  h = h.replace(/`([^`]+?)`/g, '<code>$1</code>');
  h = h.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  return h;
}

function copyCode(btn) {
  var code = btn.getAttribute('data-code').replace(/&quot;/g, '"');
  var ta = document.createElement('textarea'); ta.innerHTML = code;
  navigator.clipboard.writeText(ta.value).then(function () {
    btn.textContent = 'Copied!'; btn.classList.add('copied');
    setTimeout(function () { btn.textContent = 'Copy'; btn.classList.remove('copied'); }, 2000);
  });
}

// ━━━ Messages ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function getConvKey() {
  if (currentMode === 'agent') return 'agent:' + currentTarget;
  if (currentMode === 'group') return 'group:' + currentTarget;
  return 'default';
}

function getConv() {
  var k = getConvKey();
  if (!convHistory[k]) convHistory[k] = [];
  return convHistory[k];
}

function buildMsgHtml(m, animate) {
  var isUser = m.role === 'user';
  var agentKey = m.agent || '';
  var sender = isUser ? 'You' : (agentKey && agents[agentKey] ? agents[agentKey].display_name : (agentKey || 'Claw'));
  var avColor = isUser ? '#4488ff' : '#00ff88';
  var avBg = isUser ? 'rgba(68,136,255,0.1)' : 'var(--green-dim)';
  if (!isUser && agentKey && agents[agentKey]) {
    var ci = (agents[agentKey].color_idx || 0) % 6;
    avColor = AVATAR_COLORS[ci] || '#00ff88';
    avBg = avColor + '15';
  }
  var avLetter = isUser ? 'Y' : (agentKey ? agentKey[0].toUpperCase() : '\ud83d\udc3e');
  var cls = 'msg' + (animate ? ' msg-enter' : '') + (isUser ? ' user' : '');
  var html = '<div class="' + cls + '"><div class="avatar" style="background:' + avBg + ';color:' + avColor + ';">' + avLetter + '</div><div class="body"><div class="sender">' + escapeHtml(sender) + (m.time ? ' <span class="time">' + m.time + '</span>' : '') + '</div><div class="bubble">' + formatContent(m.content);
  if (m.commands && m.commands.length) {
    html += '<div class="commands">';
    m.commands.forEach(function (c) {
      var ct = c.command ? c.command.type : (c.type || '');
      var ca = c.command ? (c.command.args || '') : (c.args || '');
      html += '<div class="cmd-item"><div class="cmd-header"><span class="cmd-type">' + escapeHtml(ct) + '</span><span class="cmd-args">' + escapeHtml(ca).substring(0, 120) + '</span></div><div class="cmd-result">' + escapeHtml(c.result || '') + '</div></div>';
    });
    html += '</div>';
  }
  html += '</div>';
  if (m.usage) html += '<div class="usage"><span>p:' + m.usage.prompt + '</span><span>c:' + m.usage.completion + '</span><span>t:' + m.usage.total + '</span>' + (m.usage.time ? '<span>' + m.usage.time + 's</span>' : '') + '</div>';
  html += '</div></div>';
  return html;
}

function renderMessages() {
  var container = document.getElementById('messages');
  var conv = getConv();
  if (!conv.length) {
    var t = currentMode === 'agent' ? '@' + currentTarget : (currentMode === 'group' ? currentTarget : 'Claw');
    container.innerHTML = '<div class="msg"><div class="avatar avatar-welcome">\ud83d\udc3e</div><div class="body"><div class="sender">Claw</div><div class="bubble">\u5f00\u59cb\u5bf9\u8bdd\u5427\uff01\u53d1\u9001\u6d88\u606f\u7ed9 ' + escapeHtml(t) + '\u3002</div></div></div>';
    return;
  }
  var html = '';
  conv.forEach(function (m) { html += buildMsgHtml(m, false); });
  container.innerHTML = html;
  container.scrollTop = container.scrollHeight;
}

function appendMessage(role, content, extra) {
  var conv = getConv();
  var msg = { role: role, content: content };
  if (extra) Object.keys(extra).forEach(function (k) { msg[k] = extra[k]; });
  conv.push(msg);
  saveConvHistory();
  var container = document.getElementById('messages');
  var w = document.createElement('div');
  w.innerHTML = buildMsgHtml(msg, true);
  container.appendChild(w.firstChild);
  container.scrollTop = container.scrollHeight;
}

// ── Streaming helpers ──
var _streamBubbleEl = null;
var _streamRenderPending = false;
var _streamMsgIndex = -1;

function createStreamingMsgForAgent(agentKey) {
  var conv = getConv();
  var msg = { role: 'assistant', content: '', agent: agentKey, commands: [], usage: null, time: formatTime() };
  conv.push(msg);
  _streamMsgIndex = conv.length - 1;
  var container = document.getElementById('messages');
  var w = document.createElement('div');
  w.innerHTML = buildMsgHtml(msg, true);
  var el = w.firstChild;
  container.appendChild(el);
  _streamBubbleEl = el;
  container.scrollTop = container.scrollHeight;
}

function finalizeCurrentStream() {
  if (!_streamBubbleEl) return;
  var conv = getConv();
  var msg = conv[_streamMsgIndex];
  if (!msg) return;
  var bubble = _streamBubbleEl.querySelector('.bubble');
  if (bubble) {
    var html = formatContent(msg.content);
    if (msg.commands && msg.commands.length) {
      html += '<div class="commands">';
      msg.commands.forEach(function (c) {
        var ct = c.command ? c.command.type : (c.type || '');
        var ca = c.command ? (c.command.args || '') : (c.args || '');
        html += '<div class="cmd-item"><div class="cmd-header"><span class="cmd-type">' + escapeHtml(ct) + '</span><span class="cmd-args">' + escapeHtml(ca).substring(0, 120) + '</span></div><div class="cmd-result">' + escapeHtml(c.result || '') + '</div></div>';
      });
      html += '</div>';
    }
    bubble.innerHTML = html;
  }
  if (msg.usage) {
    var body = _streamBubbleEl.querySelector('.body');
    var eu = _streamBubbleEl.querySelector('.usage');
    if (eu) eu.remove();
    var ud = document.createElement('div');
    ud.className = 'usage';
    ud.innerHTML = '<span>p:' + msg.usage.prompt + '</span><span>c:' + msg.usage.completion + '</span><span>t:' + msg.usage.total + '</span>' + (msg.usage.time ? '<span>' + msg.usage.time + 's</span>' : '');
    body.appendChild(ud);
  }
  _streamBubbleEl = null;
  _streamMsgIndex = -1;
  saveConvHistory();
  document.getElementById('messages').scrollTop = document.getElementById('messages').scrollHeight;
}

function scheduleStreamRender() {
  if (_streamRenderPending) return;
  _streamRenderPending = true;
  requestAnimationFrame(function () {
    _streamRenderPending = false;
    if (!_streamBubbleEl) return;
    var conv = getConv();
    var msg = conv[_streamMsgIndex];
    if (!msg) return;
    var bubble = _streamBubbleEl.querySelector('.bubble');
    if (!bubble) return;
    var html = formatContentLite(msg.content);
    if (msg.commands && msg.commands.length) {
      html += '<div class="commands">';
      msg.commands.forEach(function (c) {
        var ct = c.command ? c.command.type : (c.type || '');
        var ca = c.command ? (c.command.args || '') : (c.args || '');
        html += '<div class="cmd-item"><div class="cmd-header"><span class="cmd-type">' + escapeHtml(ct) + '</span><span class="cmd-args">' + escapeHtml(ca).substring(0, 120) + '</span></div><div class="cmd-result">' + escapeHtml(c.result || '') + '</div></div>';
      });
      html += '</div>';
    }
    bubble.innerHTML = html;
    var c = document.getElementById('messages');
    c.scrollTop = c.scrollHeight;
  });
}

function showTyping() {
  var c = document.getElementById('messages');
  var d = document.createElement('div'); d.id = 'typingIndicator';
  d.innerHTML = '<div class="msg"><div class="avatar avatar-welcome">\ud83d\udc3e</div><div class="body"><div class="typing"><span></span><span></span><span></span></div></div></div>';
  c.appendChild(d); c.scrollTop = c.scrollHeight;
}
function hideTyping() { var el = document.getElementById('typingIndicator'); if (el) el.remove(); }
function formatTime() { var n = new Date(); return ('0' + n.getHours()).slice(-2) + ':' + ('0' + n.getMinutes()).slice(-2); }

// ━━━ Send ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function sendMessage() {
  var input = document.getElementById('userInput');
  var text = input.value.trim();
  if (!text || isStreaming) return;
  input.value = '';
  input.style.height = 'auto';
  if (!isConnected) { showError('Not connected'); return; }
  appendMessage('user', text);
  addLog('info', (currentMode !== 'default' ? '[' + currentMode + ':' + currentTarget + '] ' : '') + 'Sent: ' + text.substring(0, 80));
  if (connMode === 'stream') sendStreaming(text);
  else sendSync(text);
}

// ━━━ Streaming ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function sendStreaming(text) {
  isStreaming = true;
  document.getElementById('sendBtn').disabled = true;
  showTyping();

  var controller = new AbortController();
  var tid = setTimeout(function () { controller.abort(); }, reqTimeout * 1000);

  fetch(gatewayUrl + '/api/chat', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: text, mode: currentMode, target: currentTarget }),
    signal: controller.signal
  })
  .then(function (resp) {
    clearTimeout(tid);
    if (!resp.ok) {
      return resp.json().catch(function () { return { error: 'HTTP ' + resp.status }; }).then(function (err) {
        hideTyping(); appendMessage('assistant', 'Error: ' + (err.error || resp.statusText));
        addLog('error', err.error || resp.statusText);
        isStreaming = false; document.getElementById('sendBtn').disabled = false;
      });
    }

    var reader = resp.body.getReader(), decoder = new TextDecoder();
    var buffer = '', commands = [];
    hideTyping();
    var conv = getConv();

    function readChunk() {
      reader.read().then(function (result) {
        if (result.done) { finish(); return; }
        buffer += decoder.decode(result.value, { stream: true });
        var lines = buffer.split('\n');
        buffer = lines.pop();
        for (var li = 0; li < lines.length; li++) {
          var line = lines[li].trim();
          if (!line) continue;
          try {
            var evt = JSON.parse(line);
            if (evt.type === 'agent_start') {
              finalizeCurrentStream();
              createStreamingMsgForAgent(evt.agent);
              commands = [];
            }
            else if (evt.type === 'agent_end') {
              finalizeCurrentStream();
            }
            else if (evt.type === 'token') {
              if (_streamMsgIndex >= 0 && conv[_streamMsgIndex]) {
                conv[_streamMsgIndex].content += evt.content;
                scheduleStreamRender();
              }
            }
            else if (evt.type === 'commands') {
              commands = evt.commands || [];
              if (_streamMsgIndex >= 0 && conv[_streamMsgIndex]) {
                conv[_streamMsgIndex].commands = commands.map(function (c) { return { command: c, result: null }; });
                scheduleStreamRender();
              }
            }
            else if (evt.type === 'result') {
              if (_streamMsgIndex >= 0 && conv[_streamMsgIndex] && evt.index < commands.length) {
                conv[_streamMsgIndex].commands[evt.index].result = evt.content;
                scheduleStreamRender();
              }
            }
            else if (evt.type === 'usage') {
              if (_streamMsgIndex >= 0 && conv[_streamMsgIndex]) {
                conv[_streamMsgIndex].usage = evt.usage;
              }
              if (evt.usage) {
                document.getElementById('usageHint').textContent =
                  'p:' + evt.usage.prompt + ' c:' + evt.usage.completion + ' t:' + evt.usage.total +
                  (evt.usage.time ? ' \u00b7 ' + evt.usage.time + 's' : '');
              }
            }
            else if (evt.type === 'error') {
              if (_streamMsgIndex >= 0 && conv[_streamMsgIndex]) {
                conv[_streamMsgIndex].content += '\n\nError: ' + evt.content;
                scheduleStreamRender();
              } else {
                appendMessage('assistant', 'Error: ' + evt.content);
              }
            }
          } catch (e) {}
        }
        readChunk();
      }).catch(function () { finish(); });
    }

    function finish() {
      isStreaming = false;
      document.getElementById('sendBtn').disabled = false;
      finalizeCurrentStream();
      addLog('info', 'Reply received');
    }
    readChunk();
  })
  .catch(function (e) {
    clearTimeout(tid); hideTyping();
    if (e.name === 'AbortError') appendMessage('assistant', 'Timed out.');
    else { showError('Error: ' + e.message); addLog('error', e.message); }
    isStreaming = false; document.getElementById('sendBtn').disabled = false;
  });
}

// ━━━ Sync ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function sendSync(text) {
  isStreaming = true;
  document.getElementById('sendBtn').disabled = true;
  showTyping();
  var controller = new AbortController();
  var tid = setTimeout(function () { controller.abort(); }, reqTimeout * 1000);

  fetch(gatewayUrl + '/api/chat/sync', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: text, mode: currentMode, target: currentTarget }),
    signal: controller.signal
  })
  .then(function (resp) { clearTimeout(tid); hideTyping();
    if (!resp.ok) return resp.json().catch(function () { return { error: 'HTTP ' + resp.status }; }).then(function (e) { appendMessage('assistant', 'Error: ' + (e.error || resp.statusText)); });
    return resp.json().then(function (data) {
      if (data.agents && data.agents.length) {
        data.agents.forEach(function (a) {
          appendMessage('assistant', data.reply || '(no response)', { agent: a.name, usage: data.usage });
        });
      } else {
        var extra = { time: formatTime() };
        if (data.commands) extra.commands = data.commands;
        if (data.usage) extra.usage = data.usage;
        appendMessage('assistant', data.reply || '(no response)', extra);
      }
      addLog('info', 'Sync reply');
    });
  })
  .catch(function (e) { clearTimeout(tid); hideTyping();
    if (e.name === 'AbortError') appendMessage('assistant', 'Timed out.');
    else { showError('Error: ' + e.message); addLog('error', e.message); }
  })
  .finally(function () { isStreaming = false; document.getElementById('sendBtn').disabled = false; });
}

// ━━━ Utils ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function clearChat() {
  convHistory[getConvKey()] = [];
  _streamBubbleEl = null; _streamMsgIndex = -1;
  saveConvHistory();
  if (isConnected) fetch(gatewayUrl + '/api/clear', { method: 'POST' }).catch(function () {});
  renderMessages();
  addLog('info', 'Chat cleared');
}
function showError(msg) { document.getElementById('errorText').textContent = msg; document.getElementById('errorBanner').classList.add('show'); }
function hideError() { document.getElementById('errorBanner').classList.remove('show'); }
