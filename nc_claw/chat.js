// ━━━ Config ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const API_BASE = '';
let currentMode = 'default';
let currentTarget = '';
let streaming = false;
let tokenTotal = 0;

// ━━━ Marked Config ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

marked.setOptions({
    highlight: function(code, lang) {
        if (lang && hljs.getLanguage(lang)) {
            try { return hljs.highlight(code, { language: lang }).value; }
            catch (e) { /* ignore */ }
        }
        try { return hljs.highlightAuto(code).value; }
        catch (e) { /* ignore */ }
        return code;
    },
    breaks: true,
    gfm: true,
    headerIds: false,
    mangle: false
});

function renderMarkdown(text) {
    if (!text) return '';
    try {
        return marked.parse(text);
    } catch (e) {
        return text.replace(/</g, '&lt;').replace(/\n/g, '<br>');
    }
}

// ━━━ Color Utilities ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const COLOR_NAMES = ['green', 'blue', 'magenta', 'yellow', 'red', 'cyan'];

function colorClass(idx) {
    return COLOR_NAMES[(idx || 0) % COLOR_NAMES.length];
}

// ━━━ Init ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

window.addEventListener('DOMContentLoaded', function() {
    loadHealth();
    loadAgents();
    loadGroups();
    loadSkills();
    loadHistory();
    autoResize();
});

function autoResize() {
    var el = document.getElementById('input');
    el.addEventListener('input', function() {
        el.style.height = 'auto';
        el.style.height = Math.min(el.scrollHeight, 150) + 'px';
    });
}

// ━━━ API Calls ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function loadHealth() {
    fetch(API_BASE + '/api/health')
        .then(function(r) { return r.json(); })
        .then(function(d) {
            document.getElementById('version').textContent = 'v' + d.version;
            document.getElementById('status-dot').classList.add('ok');
            document.getElementById('status-text').textContent = d.model;
            tokenTotal = d.token_usage ? d.token_usage.total : 0;
            document.getElementById('token-usage').textContent = tokenTotal + ' tokens';
        })
        .catch(function() {
            document.getElementById('status-text').textContent = 'Offline';
        });
}

function loadAgents() {
    fetch(API_BASE + '/api/agents')
        .then(function(r) { return r.json(); })
        .then(function(d) {
            var list = document.getElementById('agent-list');
            list.innerHTML = '';
            (d.agents || []).forEach(function(a) {
                var cn = colorClass(a.color_idx);
                var div = document.createElement('div');
                div.className = 'entity-item' + (currentMode === 'agent' && currentTarget === a.name ? ' active' : '');
                div.setAttribute('role', 'button');
                div.setAttribute('tabindex', '0');
                div.setAttribute('aria-label', 'Select agent ' + a.display_name);
                div.innerHTML =
                    '<span class="entity-dot avatar-' + cn + '"></span>' +
                    '<span class="entity-name">' + escapeHtml(a.display_name) + '</span>' +
                    '<span class="entity-role">' + escapeHtml(a.effective_model || '') + '</span>';
                div.addEventListener('click', function() { selectAgent(a.name, div); });
                list.appendChild(div);
            });
        })
        .catch(function() { /* ignore */ });
}

function loadGroups() {
    fetch(API_BASE + '/api/groups')
        .then(function(r) { return r.json(); })
        .then(function(d) {
            var list = document.getElementById('group-list');
            list.innerHTML = '';
            (d.groups || []).forEach(function(g) {
                var div = document.createElement('div');
                div.className = 'entity-item' + (currentMode === 'group' && currentTarget === g.name ? ' active' : '');
                div.setAttribute('role', 'button');
                div.setAttribute('tabindex', '0');
                div.setAttribute('aria-label', 'Select group ' + g.name);
                div.innerHTML =
                    '<span class="entity-dot avatar-green"></span>' +
                    '<span class="entity-name">' + escapeHtml(g.name) + '</span>' +
                    '<span class="entity-role">' + (g.members ? g.members.length : 0) + ' members</span>';
                div.addEventListener('click', function() { selectGroup(g.name, div); });
                list.appendChild(div);
            });
        })
        .catch(function() { /* ignore */ });
}

function loadSkills() {
    fetch(API_BASE + '/api/skills')
        .then(function(r) { return r.json(); })
        .then(function(d) {
            var list = document.getElementById('skill-list');
            list.innerHTML = '';
            (d.skills || []).forEach(function(s) {
                var tag = document.createElement('span');
                tag.className = 'skill-tag' + (s.loaded ? ' loaded' : '');
                tag.textContent = s.name;
                tag.title = s.desc;
                tag.setAttribute('role', 'button');
                tag.setAttribute('tabindex', '0');
                tag.setAttribute('aria-label', (s.loaded ? 'Unload ' : 'Load ') + 'skill ' + s.name);
                tag.addEventListener('click', function() {
                    fetch(API_BASE + '/api/skills', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ action: s.loaded ? 'unload' : 'load', id: s.id })
                    }).then(function() { loadSkills(); });
                });
                list.appendChild(tag);
            });
        })
        .catch(function() { /* ignore */ });
}

function loadHistory() {
    fetch(API_BASE + '/api/history')
        .then(function(r) { return r.json(); })
        .then(function(d) {
            var container = document.getElementById('messages');
            container.innerHTML = '';
            (d.messages || []).forEach(function(m) {
                appendMessage(m.role === 'user' ? 'user' : 'assistant', m.content);
            });
            scrollToBottom();
        })
        .catch(function() { /* ignore */ });
}

// ━━━ Mode Switching ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function switchMode(mode) {
    currentMode = mode;
    currentTarget = '';
    document.querySelectorAll('.mode-tab').forEach(function(t) {
        t.classList.toggle('active', t.dataset.mode === mode);
    });
    document.getElementById('agent-list-section').style.display = mode === 'agent' ? '' : 'none';
    document.getElementById('group-list-section').style.display = mode === 'group' ? '' : 'none';
    clearActiveItems();
    updateTitle();
}

function selectAgent(name, el) {
    currentMode = 'agent';
    currentTarget = name;
    document.querySelectorAll('.mode-tab').forEach(function(t) {
        t.classList.toggle('active', t.dataset.mode === 'agent');
    });
    document.getElementById('agent-list-section').style.display = '';
    clearActiveItems();
    if (el) el.classList.add('active');
    updateTitle();
}

function selectGroup(name, el) {
    currentMode = 'group';
    currentTarget = name;
    document.querySelectorAll('.mode-tab').forEach(function(t) {
        t.classList.toggle('active', t.dataset.mode === 'group');
    });
    document.getElementById('group-list-section').style.display = '';
    clearActiveItems();
    if (el) el.classList.add('active');
    updateTitle();
}

function clearActiveItems() {
    document.querySelectorAll('.entity-item').forEach(function(el) {
        el.classList.remove('active');
    });
}

function updateTitle() {
    var el = document.getElementById('chat-title');
    if (currentMode === 'agent' && currentTarget) {
        el.textContent = '@' + currentTarget;
    } else if (currentMode === 'group' && currentTarget) {
        el.textContent = '#' + currentTarget;
    } else {
        el.textContent = 'Claw';
    }
}

// ━━━ Chat ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function handleKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
}

function sendMessage() {
    var input = document.getElementById('input');
    var msg = input.value.trim();
    if (!msg || streaming) return;

    input.value = '';
    input.style.height = 'auto';

    appendMessage('user', msg);
    scrollToBottom();

    var body = { message: msg, mode: currentMode, target: currentTarget };
    streamChat(body);
}

function streamChat(body) {
    streaming = true;
    document.getElementById('send-btn').disabled = true;

    // Remove welcome
    var welcome = document.querySelector('.welcome');
    if (welcome) welcome.remove();

    var msgDiv = createAssistantBubble();
    var bodyEl = msgDiv.querySelector('.msg-body');
    var nameEl = msgDiv.querySelector('.msg-name');
    var avatarEl = msgDiv.querySelector('.msg-avatar');
    var fullText = '';
    var started = false;

    // Typing indicator
    bodyEl.innerHTML = '<span class="thinking">Thinking...</span>';

    fetch(API_BASE + '/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    })
    .then(function(resp) {
        var reader = resp.body.getReader();
        var decoder = new TextDecoder();
        var buffer = '';

        function read() {
            return reader.read().then(function(result) {
                if (result.done) {
                    // Final render
                    if (fullText) {
                        bodyEl.innerHTML = renderMarkdown(fullText);
                        bodyEl.querySelectorAll('pre code').forEach(function(block) {
                            hljs.highlightElement(block);
                        });
                    }
                    streaming = false;
                    document.getElementById('send-btn').disabled = false;
                    scrollToBottom();
                    return;
                }

                buffer += decoder.decode(result.value, { stream: true });

                var lines = buffer.split('\n');
                buffer = lines.pop() || '';

                for (var i = 0; i < lines.length; i++) {
                    var line = lines[i].trim();
                    if (!line) continue;
                    try {
                        var evt = JSON.parse(line);

                        if (evt.type === 'agent_start') {
                            var agentName = evt.display_name || evt.agent || 'Claw';
                            var cn = colorClass(evt.color_idx);
                            nameEl.textContent = agentName;
                            nameEl.className = 'msg-name agent-name-' + cn;
                            avatarEl.className = 'msg-avatar avatar-' + cn;
                            avatarEl.textContent = agentName[0].toUpperCase();
                        }

                        if (evt.type === 'token') {
                            if (!started) {
                                started = true;
                                bodyEl.innerHTML = '';
                            }
                            fullText += evt.content;
                            bodyEl.innerHTML = renderMarkdown(fullText);
                            scrollToBottom();
                        }

                        if (evt.type === 'commands') {
                            var cmds = evt.commands || [];
                            for (var j = 0; j < cmds.length; j++) {
                                var block = document.createElement('div');
                                block.className = 'cmd-block';
                                block.innerHTML =
                                    '<span class="cmd-type">$ ' + escapeHtml(cmds[j].type) + '</span> ' +
                                    escapeHtml(cmds[j].args);
                                bodyEl.appendChild(block);
                            }
                        }

                        if (evt.type === 'result') {
                            var lastCmd = bodyEl.querySelector('.cmd-block:last-child');
                            if (lastCmd) {
                                var isError = evt.content.indexOf('[Error') === 0 || evt.content.indexOf('[BLOCKED') === 0;
                                var spanClass = isError ? 'cmd-error' : 'cmd-result';
                                var newline = document.createTextNode('\n');
                                var span = document.createElement('span');
                                span.className = spanClass;
                                span.textContent = evt.content;
                                lastCmd.appendChild(newline);
                                lastCmd.appendChild(span);
                            }
                        }

                        if (evt.type === 'usage') {
                            tokenTotal += (evt.usage && evt.usage.total) ? evt.usage.total : 0;
                            document.getElementById('token-usage').textContent = tokenTotal + ' tokens';
                        }

                        if (evt.type === 'error') {
                            bodyEl.innerHTML = '<span class="error">' + escapeHtml(evt.content) + '</span>';
                        }

                        if (evt.type === 'done') break;

                    } catch (e) { /* skip malformed lines */ }
                }

                return read();
            });
        }

        return read();
    })
    .catch(function(e) {
        bodyEl.innerHTML = '<span class="error">Connection error: ' + escapeHtml(e.message) + '</span>';
        streaming = false;
        document.getElementById('send-btn').disabled = false;
        scrollToBottom();
    });
}

// ━━━ Message DOM ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function appendMessage(role, content) {
    var container = document.getElementById('messages');
    var welcome = document.querySelector('.welcome');
    if (welcome) welcome.remove();

    var div = document.createElement('div');
    div.className = 'msg';

    if (role === 'user') {
        div.innerHTML =
            '<div class="msg-header">' +
                '<div class="msg-avatar avatar-blue">U</div>' +
                '<span class="msg-name agent-name-blue">You</span>' +
                '<span class="msg-time">' + timeNow() + '</span>' +
            '</div>' +
            '<div class="msg-body user-msg">' + escapeHtml(content) + '</div>';
    } else {
        div.innerHTML =
            '<div class="msg-header">' +
                '<div class="msg-avatar avatar-green">C</div>' +
                '<span class="msg-name agent-name-green">Claw</span>' +
                '<span class="msg-time">' + timeNow() + '</span>' +
            '</div>' +
            '<div class="msg-body">' + renderMarkdown(content) + '</div>';
        // Highlight code blocks in history
        div.querySelectorAll('pre code').forEach(function(block) {
            hljs.highlightElement(block);
        });
    }

    container.appendChild(div);
    return div;
}

function createAssistantBubble() {
    var container = document.getElementById('messages');
    var div = document.createElement('div');
    div.className = 'msg';
    div.innerHTML =
        '<div class="msg-header">' +
            '<div class="msg-avatar avatar-green">C</div>' +
            '<span class="msg-name agent-name-green">Claw</span>' +
            '<span class="msg-time">' + timeNow() + '</span>' +
        '</div>' +
        '<div class="msg-body"></div>';
    container.appendChild(div);
    return div;
}

// ━━━ Helpers ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function scrollToBottom() {
    var el = document.getElementById('messages');
    requestAnimationFrame(function() { el.scrollTop = el.scrollHeight; });
}

function clearChat() {
    fetch(API_BASE + '/api/clear', { method: 'POST' });
    var container = document.getElementById('messages');
    container.innerHTML =
        '<div class="welcome">' +
            '<div class="welcome-icon">🐾</div>' +
            '<div class="welcome-title">Claw Terminal AI</div>' +
            '<div class="welcome-sub">Multi-Agent · Group Chat · Commands</div>' +
        '</div>';
}

function toggleSidebar() {
    document.getElementById('sidebar').classList.toggle('open');
}

function escapeHtml(text) {
    if (!text) return '';
    var d = document.createElement('div');
    d.textContent = text;
    return d.innerHTML;
}

function timeNow() {
    var now = new Date();
    var h = String(now.getHours()).padStart(2, '0');
    var m = String(now.getMinutes()).padStart(2, '0');
    return h + ':' + m;
}
