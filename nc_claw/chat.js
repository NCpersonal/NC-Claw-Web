var API_BASE = '';
var currentMode = 'default';
var currentTarget = '';
var streaming = false;
var tokenTotal = 0;
var markedReady = false;
var hljsReady = false;
var commandConfirm = true;  // default on

var COLOR_NAMES = ['green', 'blue', 'magenta', 'yellow', 'red', 'cyan'];

function colorClass(idx) {
    return COLOR_NAMES[(idx || 0) % COLOR_NAMES.length];
}

// ━━━ Markdown ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function setupMarked() {
    if (typeof marked === 'undefined') { return false; }
    try {
        marked.setOptions({ breaks: true, gfm: true, headerIds: false, mangle: false });
        markedReady = true;
        return true;
    } catch (e) { return false; }
}

function setupHighlight() {
    if (typeof hljs === 'undefined') return false;
    hljsReady = true;
    return true;
}

function renderMarkdown(text) {
    if (!text) return '';
    if (markedReady) {
        try { return marked.parse(text); } catch (e) { /* fall through */ }
    }
    return fallbackMarkdown(text);
}

function fallbackMarkdown(text) {
    var h = escapeHtml(text);
    h = h.replace(/```(\w*)\n([\s\S]*?)```/g, function(m, l, c) { return '<pre><code>' + c.trim() + '</code></pre>'; });
    h = h.replace(/`([^`\n]+)`/g, '<code>$1</code>');
    h = h.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    h = h.replace(/\*(.+?)\*/g, '<em>$1</em>');
    h = h.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    h = h.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    h = h.replace(/^# (.+)$/gm, '<h1>$1</h1>');
    h = h.replace(/\n/g, '<br>');
    return h;
}

function highlightCodeBlocks(container) {
    if (!hljsReady) return;
    try {
        container.querySelectorAll('pre code').forEach(function(block) {
            if (!block.dataset.highlighted) {
                hljs.highlightElement(block);
                block.dataset.highlighted = 'true';
            }
        });
    } catch (e) { /* ignore */ }
}

// ━━━ Init ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

window.addEventListener('DOMContentLoaded', function() {
    setupMarked();
    setupHighlight();
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

// ━━━ API ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

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

function loadConfig() {
    fetch(API_BASE + '/api/config')
        .then(function(r) { return r.json(); })
        .then(function(d) {
            if (d.command_confirm !== undefined) {
                commandConfirm = d.command_confirm;
            }
        })
        .catch(function() {});
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
        .catch(function() {});
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
                    '<span class="entity-role">' + (g.members ? g.members.length : 0) + '</span>';
                div.addEventListener('click', function() { selectGroup(g.name, div); });
                list.appendChild(div);
            });
        })
        .catch(function() {});
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
                tag.setAttribute('aria-label', (s.loaded ? 'Unload ' : 'Load ') + s.name);
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
        .catch(function() {});
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
        .catch(function() {});
}

// ━━━ Mode Switching ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

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
    if (currentMode === 'agent' && currentTarget) el.textContent = '@' + currentTarget;
    else if (currentMode === 'group' && currentTarget) el.textContent = '#' + currentTarget;
    else el.textContent = 'Claw';
}

// ━━━ Chat ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

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
    streamChat({ message: msg, mode: currentMode, target: currentTarget, confirm: commandConfirm });
}

function streamChat(body) {
    streaming = true;
    document.getElementById('send-btn').disabled = true;

    var welcome = document.querySelector('.welcome');
    if (welcome) welcome.remove();

    var msgDiv = createAssistantBubble();
    var bodyEl = msgDiv.querySelector('.msg-body');
    var nameEl = msgDiv.querySelector('.msg-name');
    var avatarEl = msgDiv.querySelector('.msg-avatar');
    var fullText = '';
    var started = false;

    // Tool call tracking
    var currentToolBubble = null;
    var currentToolBody = null;
    var toolCount = 0;
    var pendingCommands = [];

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

        function pump() {
            return reader.read().then(function(result) {
                if (result.done) {
                    finishStream(bodyEl, fullText);
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
                            highlightCodeBlocks(bodyEl);
                            scrollToBottom();
                        }

                        if (evt.type === 'commands') {
                            var cmds = evt.commands || [];
                            var needConfirm = evt.need_confirm || false;
                            if (cmds.length > 0) {
                                pendingCommands = cmds;
                                currentToolBubble = createToolBubble();
                                currentToolBody = currentToolBubble.querySelector('.tool-body');
                                toolCount = 0;
                                for (var j = 0; j < cmds.length; j++) {
                                    toolCount++;
                                    var item = document.createElement('div');
                                    item.className = 'tool-item';
                                    item.innerHTML =
                                        '<div class="tool-cmd">' +
                                            '<span class="tool-cmd-type">$ ' + escapeHtml(cmds[j].type) + '</span>' +
                                            '<span class="tool-cmd-args">' + escapeHtml(cmds[j].args) + '</span>' +
                                        '</div>';
                                    item.setAttribute('data-index', j);
                                    currentToolBody.appendChild(item);
                                }
                                updateToolCount(currentToolBubble, toolCount);

                                // Show confirm bar if needed
                                if (needConfirm) {
                                    showConfirmBar(currentToolBubble, pendingCommands);
                                }

                                scrollToBottom();
                            }
                        }

                        if (evt.type === 'result') {
                            if (currentToolBody) {
                                var items = currentToolBody.querySelectorAll('.tool-item');
                                var targetItem = items[evt.index] || items[items.length - 1];
                                if (targetItem) {
                                    appendToolResult(targetItem, evt.content);
                                }
                                scrollToBottom();
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

                    } catch (e) { /* skip malformed */ }
                }

                return pump();
            });
        }

        return pump();
    })
    .catch(function(e) {
        bodyEl.innerHTML = '<span class="error">Connection error: ' + escapeHtml(e.message) + '</span>';
        streaming = false;
        document.getElementById('send-btn').disabled = false;
        scrollToBottom();
    });
}

function finishStream(bodyEl, fullText) {
    if (fullText) {
        bodyEl.innerHTML = renderMarkdown(fullText);
        highlightCodeBlocks(bodyEl);
    }
    streaming = false;
    document.getElementById('send-btn').disabled = false;
    scrollToBottom();
}

// ━━━ Tool Bubble ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function createToolBubble() {
    var container = document.getElementById('messages');
    var div = document.createElement('div');
    div.className = 'msg system-tool';
    div.innerHTML =
        '<div class="tool-container">' +
            '<div class="tool-header" onclick="toggleToolBody(this)">' +
                '<span class="tool-icon">&#9881;</span>' +
                '<span>System Tool Call</span>' +
                '<span class="tool-count"></span>' +
                '<span class="tool-toggle">&#9660;</span>' +
            '</div>' +
            '<div class="tool-body"></div>' +
        '</div>';
    container.appendChild(div);
    return div;
}

function updateToolCount(bubble, count) {
    var el = bubble.querySelector('.tool-count');
    if (el) {
        el.textContent = count + (count === 1 ? ' command' : ' commands');
    }
}

function toggleToolBody(header) {
    var body = header.nextElementSibling;
    body.classList.toggle('collapsed');
    header.classList.toggle('collapsed');
}

function appendToolResult(targetItem, content) {
    var isError = content.indexOf('[Error') === 0 ||
                  content.indexOf('[BLOCKED') === 0 ||
                  content.indexOf('[Not found') === 0;
    var resultDiv = document.createElement('div');
    resultDiv.className = 'tool-result' + (isError ? ' has-error' : '');
    resultDiv.textContent = content;
    targetItem.appendChild(resultDiv);
}

// ━━━ Confirm Bar ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function showConfirmBar(bubble, commands) {
    var container = bubble.querySelector('.tool-container');
    var bar = document.createElement('div');
    bar.className = 'tool-confirm-bar';
    bar.innerHTML =
        '<span class="confirm-info">Execute ' + commands.length +
        (commands.length === 1 ? ' command' : ' commands') + '?</span>' +
        '<button class="confirm-btn skip" onclick="cancelCommands(this)" title="Skip commands" aria-label="Skip commands">Skip</button>' +
        '<button class="confirm-btn run" onclick="confirmCommands(this)" title="Run commands" aria-label="Run commands">Run</button>';
    container.appendChild(bar);
    scrollToBottom();
}

function confirmCommands(btn) {
    var bar = btn.closest('.tool-confirm-bar');
    var bubble = btn.closest('.system-tool');
    var toolBody = bubble.querySelector('.tool-body');
    var items = toolBody.querySelectorAll('.tool-item');
    var commands = [];

    // Collect commands from DOM
    items.forEach(function(item) {
        var type = item.querySelector('.tool-cmd-type');
        var args = item.querySelector('.tool-cmd-args');
        if (type && args) {
            commands.push({
                type: type.textContent.replace('$ ', ''),
                args: args.textContent
            });
        }
    });

    // Disable buttons
    bar.querySelectorAll('.confirm-btn').forEach(function(b) { b.disabled = true; });
    btn.textContent = 'Running...';

    // Execute via API
    fetch(API_BASE + '/api/exec-batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ commands: commands })
    })
    .then(function(r) { return r.json(); })
    .then(function(d) {
        // Remove confirm bar
        bar.remove();

        // Show results
        var results = d.results || [];
        for (var i = 0; i < results.length; i++) {
            var targetItem = items[i] || items[items.length - 1];
            if (targetItem) {
                appendToolResult(targetItem, results[i].result);
            }
        }

        // Show status
        var status = document.createElement('div');
        status.className = 'tool-status executed';
        status.textContent = 'Executed at ' + timeNow();
        bubble.querySelector('.tool-container').appendChild(status);

        // Continue conversation with results
        var resultText = '[Command results]\n';
        for (var j = 0; j < results.length; j++) {
            resultText += '[' + results[j].type + ':' + results[j].args + '] -> ' + results[j].result + '\n';
        }

        scrollToBottom();

        // Send results back as continuation
        streamChat({
            message: resultText,
            mode: currentMode,
            target: currentTarget,
            confirm: commandConfirm
        });
    })
    .catch(function(e) {
        bar.remove();
        var status = document.createElement('div');
        status.className = 'tool-status skipped';
        status.textContent = 'Execution failed: ' + e.message;
        bubble.querySelector('.tool-container').appendChild(status);
        streaming = false;
        document.getElementById('send-btn').disabled = false;
        scrollToBottom();
    });
}

function cancelCommands(btn) {
    var bar = btn.closest('.tool-confirm-bar');
    var bubble = btn.closest('.system-tool');

    // Remove confirm bar
    bar.remove();

    // Show cancelled status
    var status = document.createElement('div');
    status.className = 'tool-status skipped';
    status.textContent = 'Skipped by user at ' + timeNow();
    bubble.querySelector('.tool-container').appendChild(status);

    // Continue AI without command results
    var resultText = '[User cancelled command execution. Please continue without running commands.]';
    streamChat({
        message: resultText,
        mode: currentMode,
        target: currentTarget,
        confirm: commandConfirm
    });
}

// ━━━ Message DOM ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

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
            '<div class="msg-body">' + escapeHtml(content) + '</div>';
    } else {
        div.innerHTML =
            '<div class="msg-header">' +
                '<div class="msg-avatar avatar-green">C</div>' +
                '<span class="msg-name agent-name-green">Claw</span>' +
                '<span class="msg-time">' + timeNow() + '</span>' +
            '</div>' +
            '<div class="msg-body">' + renderMarkdown(content) + '</div>';
        highlightCodeBlocks(div);
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

// ━━━ Helpers ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function scrollToBottom() {
    var el = document.getElementById('messages');
    requestAnimationFrame(function() { el.scrollTop = el.scrollHeight; });
}

function clearChat() {
    fetch(API_BASE + '/api/clear', { method: 'POST' });
    var container = document.getElementById('messages');
    container.innerHTML =
        '<div class="welcome">' +
            '<div class="welcome-icon">&#128062;</div>' +
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
    return String(now.getHours()).padStart(2, '0') + ':' + String(now.getMinutes()).padStart(2, '0');
}
