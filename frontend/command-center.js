'use strict';

// ============================================
// Falkenstein Command Center — JavaScript
// ============================================

const API = '/api/admin';
let ws = null;
let wsReconnectTimer = null;
let tasksOffset = 0;
const TASKS_LIMIT = 50;
const activityLog = [];
let _searchTimer = null;
let currentMemTab = 'short';
let taskViewMode = 'table';

// ============================================
// Utilities
// ============================================

function esc(str) {
  const d = document.createElement('div');
  d.textContent = String(str ?? '');
  return d.innerHTML;
}

function badge(status) {
  const cls = {
    open: 'badge-amber', in_progress: 'badge-amber', done: 'badge-green',
    failed: 'badge-red', active: 'badge-green', inactive: 'badge-red',
    error: 'badge-red', ok: 'badge-green', running: 'badge-green',
    stopped: 'badge-red', connected: 'badge-green',
  }[status] || 'badge-amber';
  return `<span class="badge ${cls}">${esc(status)}</span>`;
}

function agentBadge(type) {
  if (!type) return '';
  const cls = { coder: 'badge-coder', researcher: 'badge-researcher', writer: 'badge-writer', ops: 'badge-ops' }[type] || 'badge-accent';
  return `<span class="badge ${cls}">${esc(type)}</span>`;
}

function relTime(dateStr) {
  if (!dateStr) return '\u2014';
  // Handle Unix timestamps in seconds (e.g. from Python stat.st_mtime)
  let d;
  if (typeof dateStr === 'number' || (typeof dateStr === 'string' && /^\d+(\.\d+)?$/.test(dateStr))) {
    const ts = parseFloat(dateStr);
    // If value looks like seconds (< year 3000 in ms), multiply to get ms
    d = new Date(ts < 1e12 ? ts * 1000 : ts);
  } else {
    d = new Date(dateStr);
  }
  if (isNaN(d.getTime())) return '\u2014';
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return 'gerade eben';
  if (diff < 3600) return Math.floor(diff / 60) + ' Min';
  if (diff < 86400) return Math.floor(diff / 3600) + ' Std';
  return d.toLocaleDateString('de');
}

function relTimeFuture(dateStr) {
  if (!dateStr) return '\u2014';
  const d = new Date(dateStr);
  const diff = (d.getTime() - Date.now()) / 1000;
  if (diff <= 0) return 'faellig';
  if (diff < 60) return 'in ' + Math.ceil(diff) + ' Sek';
  if (diff < 3600) return 'in ' + Math.ceil(diff / 60) + ' Min';
  if (diff < 86400) return 'in ' + Math.floor(diff / 3600) + ' Std';
  return d.toLocaleDateString('de') + ' ' + d.toLocaleTimeString('de', { hour: '2-digit', minute: '2-digit' });
}

async function api(path, opts = {}) {
  const token = localStorage.getItem('falkenstein_token') || '';
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  if (token) headers['Authorization'] = 'Bearer ' + token;
  const res = await fetch(API + path, { ...opts, headers });
  if (res.status === 401) {
    const newToken = prompt('API Token eingeben:');
    if (newToken) {
      localStorage.setItem('falkenstein_token', newToken);
      return api(path, opts);
    }
  }
  return res.json();
}

function debouncedLoadTasks() {
  clearTimeout(_searchTimer);
  _searchTimer = setTimeout(() => { tasksOffset = 0; loadTasks(); }, 300);
}

// ============================================
// Theme
// ============================================

function toggleTheme() {
  const html = document.documentElement;
  const isDark = html.getAttribute('data-theme') === 'dark';
  html.setAttribute('data-theme', isDark ? 'light' : 'dark');
  localStorage.setItem('falkenstein_theme', isDark ? 'light' : 'dark');
  updateThemeIcon();
}

function updateThemeIcon() {
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  const icon = document.getElementById('theme-icon');
  if (!icon) return;
  if (isDark) {
    // Moon icon
    icon.innerHTML = '<path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/>';
  } else {
    // Sun icon
    icon.innerHTML = '<circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>';
  }
}

// Restore theme on load
(function restoreTheme() {
  const saved = localStorage.getItem('falkenstein_theme');
  if (saved) document.documentElement.setAttribute('data-theme', saved);
})();

document.getElementById('theme-toggle')?.addEventListener('click', toggleTheme);

// ============================================
// Navigation
// ============================================

const sectionTitles = {
  dashboard: 'Dashboard', agents: 'Agents', chat: 'Chat', tasks: 'Tasks',
  mcp: 'MCP Server', schedules: 'Schedules', memory: 'Memory',
  obsidian: 'Obsidian', system: 'System', settings: 'Einstellungen',
};

document.querySelectorAll('.sidebar-btn[data-section]').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.sidebar-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    btn.classList.add('active');
    const section = document.getElementById('section-' + btn.dataset.section);
    if (section) section.classList.add('active');
    const title = document.getElementById('topbar-title');
    if (title) title.textContent = sectionTitles[btn.dataset.section] || btn.dataset.section;

    const s = btn.dataset.section;
    if (s === 'dashboard') loadDashboard();
    else if (s === 'agents') loadAgents();
    else if (s === 'chat') loadChat();
    else if (s === 'tasks') loadTasks();
    else if (s === 'mcp') loadMCP();
    else if (s === 'schedules') loadSchedules();
    else if (s === 'memory') loadMemory();
    else if (s === 'obsidian') loadObsidian();
    else if (s === 'system') {
      loadSystem();
      if (!window._systemInterval) {
        window._systemInterval = setInterval(() => {
          if (document.getElementById('section-system')?.classList.contains('active')) loadSystem();
        }, 5000);
      }
    }
    else if (s === 'settings') loadConfig();
  });
});

// ============================================
// WebSocket
// ============================================

function connectWS() {
  const token = localStorage.getItem('falkenstein_token') || '';
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const url = `${proto}://${location.host}/ws?token=${encodeURIComponent(token)}`;

  try { ws = new WebSocket(url); } catch (e) { console.error('WS connect error:', e); scheduleReconnect(); return; }

  ws.onopen = () => {
    console.log('WS verbunden');
    const dot = document.getElementById('ws-dot');
    if (dot) { dot.classList.add('online', 'pulse'); }
    clearTimeout(wsReconnectTimer);
  };

  ws.onclose = () => {
    console.log('WS getrennt');
    const dot = document.getElementById('ws-dot');
    if (dot) { dot.classList.remove('online', 'pulse'); }
    scheduleReconnect();
  };

  ws.onerror = (e) => { console.error('WS Fehler:', e); };

  ws.onmessage = (evt) => {
    try {
      const data = JSON.parse(evt.data);
      handleWSMessage(data);
    } catch (e) { console.error('WS parse error:', e); }
  };
}

function scheduleReconnect() {
  clearTimeout(wsReconnectTimer);
  wsReconnectTimer = setTimeout(connectWS, 3000);
}

function handleWSMessage(data) {
  const t = data.type || data.event;

  if (t === 'agent_spawn' || t === 'agent_spawned') {
    addActivity('agent_spawned', `Agent gestartet: ${data.task || data.agent_id || ''}`);
    if (document.getElementById('section-dashboard')?.classList.contains('active')) loadDashboard();
    if (document.getElementById('section-agents')?.classList.contains('active')) loadAgents();
  }
  else if (t === 'agent_done') {
    addActivity('agent_done', `Agent fertig: ${data.task || data.agent_id || ''}`);
    if (document.getElementById('section-dashboard')?.classList.contains('active')) loadDashboard();
    if (document.getElementById('section-agents')?.classList.contains('active')) loadAgents();
  }
  else if (t === 'agent_error') {
    addActivity('agent_error', `Agent Fehler: ${data.error || data.agent_id || ''}`);
    showToast('Agent Fehler: ' + (data.error || 'Unbekannt'));
  }
  else if (t === 'chat_reply') {
    appendChatMessage('assistant', data.content || data.text || '');
  }
  else if (t === 'task_created') {
    addActivity('task_created', `Task erstellt: ${data.description || data.task || ''}`);
    if (document.getElementById('section-tasks')?.classList.contains('active')) loadTasks();
  }
  else if (t === 'tool_use') {
    addActivity('agent_progress', `Tool: ${data.tool || ''} ${data.success ? '\u2713' : '\u2717'}`);
  }
  else if (t === 'schedule_fired') {
    addActivity('schedule_fired', `Schedule ausgefuehrt: ${data.task || ''}`);
  }
  else if (t === 'agent_progress') {
    addActivity('agent_progress', `Agent: ${data.text || data.step || ''}`);
  }
}

// ============================================
// Toast
// ============================================

function showToast(message) {
  const existing = document.querySelector('.toast');
  if (existing) existing.remove();
  const el = document.createElement('div');
  el.className = 'toast';
  el.textContent = message;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

// ============================================
// Quick Chat
// ============================================

async function sendQuickChat() {
  const input = document.getElementById('quickchat-input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  showToast('Gesendet: ' + text.slice(0, 60));
  try {
    await api('/tasks/submit', {
      method: 'POST',
      body: JSON.stringify({ description: text }),
    });
  } catch (e) {
    showToast('Fehler beim Senden');
    console.error('Quick chat error:', e);
  }
}

document.getElementById('quickchat-input')?.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendQuickChat(); }
});

// ============================================
// Dashboard
// ============================================

async function loadDashboard() {
  try {
    const data = await api('/dashboard');
    document.getElementById('stat-agents').textContent = data.active_agents ? data.active_agents.length : 0;
    document.getElementById('stat-tasks').textContent = data.open_tasks_count || 0;

    // Agents mini
    const agentsEl = document.getElementById('dash-agents');
    if (data.active_agents && data.active_agents.length > 0) {
      agentsEl.innerHTML = data.active_agents.map(a =>
        `<div class="activity-item">
          <div class="status-dot online pulse"></div>
          <span>${esc(a.task || a.name || a.agent_id)}</span>
          ${agentBadge(a.type)}
        </div>`
      ).join('');
    } else {
      agentsEl.innerHTML = '<span class="text-muted">Keine aktiven Agents</span>';
    }

    renderActivity();
  } catch (e) { console.error('Dashboard load error:', e); }

  // Update Ollama dot from /health
  try {
    const health = await api('/health');
    const ollamaDot = document.getElementById('ollama-dot');
    if (ollamaDot) {
      ollamaDot.classList.toggle('online', (health.ollama?.status || '') === 'online');
    }
  } catch (_) {}

  loadDashboardSchedules();
  loadDashboardMCP();
  loadDashboardSystem();
}

async function loadDashboardSchedules() {
  try {
    const sData = await api('/schedules');
    const schedules = sData.tasks || sData.schedules || [];
    document.getElementById('stat-schedules').textContent = schedules.filter(s => s.active).length;

    const upEl = document.getElementById('dash-upcoming');
    const active = schedules.filter(s => s.active).slice(0, 5);
    if (active.length > 0) {
      upEl.innerHTML = active.map(s =>
        `<div class="activity-item"><span>${esc(s.task || s.description || '')}</span><span class="activity-time">${esc(s.cron || '')}</span></div>`
      ).join('');
    } else {
      upEl.innerHTML = '<span class="text-muted">Keine aktiven Schedules</span>';
    }
  } catch (_) {}

  // Error count
  try {
    const errData = await api('/tasks?status=failed&limit=100');
    const today = new Date().toISOString().slice(0, 10);
    document.getElementById('stat-errors').textContent = (errData.tasks || []).filter(t => (t.created_at || '').startsWith(today)).length;
  } catch (_) {}
}

async function loadDashboardMCP() {
  try {
    const data = await api('/mcp/servers');
    const servers = Array.isArray(data) ? data : (data.servers || []);
    const el = document.getElementById('dash-mcp');
    if (Array.isArray(servers) && servers.length > 0) {
      el.innerHTML = servers.map(s =>
        `<div class="activity-item">
          <div class="status-dot ${s.status === 'connected' || s.enabled ? 'online' : ''}"></div>
          <span>${esc(s.name || s.id)}</span>
          <span class="activity-time">${s.tools_count || 0} Tools</span>
        </div>`
      ).join('');
    } else {
      el.innerHTML = '<span class="text-muted">Keine MCP Server</span>';
    }
    // Ollama dot
    // Ollama dot is updated via /health in loadDashboard, not MCP servers
  } catch (e) {
    document.getElementById('dash-mcp').innerHTML = '<span class="text-muted">MCP nicht erreichbar</span>';
  }
}

async function loadDashboardSystem() {
  try {
    const data = await api('/system/metrics');
    const el = document.getElementById('dash-system');
    const cpu = data.cpu_percent ?? data.cpu ?? 0;
    const ram = data.ram_percent ?? data.memory ?? 0;
    el.innerHTML = `
      <div class="activity-item"><span>CPU</span><span class="activity-time">${cpu}%</span></div>
      <div class="activity-item"><span>RAM</span><span class="activity-time">${ram}%</span></div>
      ${data.gpu_percent != null ? `<div class="activity-item"><span>GPU</span><span class="activity-time">${data.gpu_percent}%</span></div>` : ''}
      ${data.temp != null ? `<div class="activity-item"><span>Temp</span><span class="activity-time">${data.temp}\u00b0C</span></div>` : ''}
    `;
  } catch (e) {
    document.getElementById('dash-system').innerHTML = '<span class="text-muted">System nicht erreichbar</span>';
  }
}

// Activity Feed
function addActivity(type, text) {
  const colors = {
    agent_spawned: 'var(--accent)', agent_done: 'var(--green)', agent_error: 'var(--red)',
    task_created: 'var(--accent)', schedule_fired: 'var(--purple)', agent_progress: 'var(--amber)',
  };
  activityLog.unshift({ type, text, color: colors[type] || 'var(--text-muted)', time: new Date() });
  if (activityLog.length > 20) activityLog.length = 20;
  if (document.getElementById('section-dashboard')?.classList.contains('active')) renderActivity();
}

function renderActivity() {
  const el = document.getElementById('activity-feed');
  if (!el) return;
  if (activityLog.length === 0) { el.innerHTML = '<span class="text-muted">Keine Aktivitaet</span>'; return; }
  el.innerHTML = activityLog.map(a =>
    `<div class="activity-item"><div class="activity-icon" style="background:${a.color}"></div><span>${esc(a.text)}</span><span class="activity-time">${relTime(a.time)}</span></div>`
  ).join('');
}

// ============================================
// Agents
// ============================================

async function loadAgents() {
  try {
    const data = await api('/dashboard');
    const grid = document.getElementById('agents-grid');
    const agents = data.active_agents || [];
    if (agents.length === 0) {
      grid.innerHTML = '<div class="card" style="grid-column:1/-1"><span class="text-muted">Keine aktiven Agents</span></div>';
      return;
    }
    grid.innerHTML = agents.map(a => `
      <div class="card">
        <div class="card-header">
          <div style="display:flex;align-items:center;gap:8px">
            <div class="status-dot online pulse"></div>
            ${esc(a.agent_id ? a.agent_id.slice(-8) : 'Agent')}
          </div>
          ${agentBadge(a.type)}
        </div>
        <div style="font-size:13px;color:var(--text-muted);margin-bottom:8px">${esc(a.task || a.name || '')}</div>
        ${a.model ? `<div style="font-size:12px;color:var(--text-muted)">Modell: ${esc(a.model)}</div>` : ''}
        ${a.started_at ? `<div style="font-size:12px;color:var(--text-muted)">Gestartet: ${relTime(a.started_at)}</div>` : ''}
        ${a.current_tool ? `<div class="mt-16"><span class="badge badge-accent">Tool: ${esc(a.current_tool)}</span></div>` : ''}
      </div>
    `).join('');
  } catch (e) {
    document.getElementById('agents-grid').innerHTML = '<div class="card"><span class="text-muted">Fehler beim Laden</span></div>';
    console.error('Agents load error:', e);
  }
}

// ============================================
// Chat
// ============================================

async function loadChat() {
  try {
    const data = await api('/chat-history?limit=50');
    const area = document.getElementById('chat-area');
    const messages = data.messages || data || [];
    area.innerHTML = '';
    messages.forEach(m => {
      appendChatMessage(m.role || m.sender || 'user', m.content || m.text || '');
    });
    area.scrollTop = area.scrollHeight;
  } catch (e) {
    console.error('Chat load error:', e);
  }
}

function appendChatMessage(role, content) {
  const area = document.getElementById('chat-area');
  if (!area) return;
  // Remove thinking indicator
  const thinking = area.querySelector('.thinking');
  if (thinking) thinking.remove();

  const bubble = document.createElement('div');
  const isUser = role === 'user' || role === 'human';
  bubble.className = 'chat-bubble ' + (isUser ? 'user' : 'assistant');
  bubble.innerHTML = esc(content) + `<div class="chat-meta">${isUser ? 'Du' : 'Assistent'} \u00b7 ${relTime(new Date())}</div>`;
  area.appendChild(bubble);
  area.scrollTop = area.scrollHeight;
}

function showThinking() {
  const area = document.getElementById('chat-area');
  if (!area) return;
  const el = document.createElement('div');
  el.className = 'chat-bubble assistant thinking';
  el.textContent = 'Denkt nach...';
  area.appendChild(el);
  area.scrollTop = area.scrollHeight;
}

async function sendChat() {
  const input = document.getElementById('chat-input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  appendChatMessage('user', text);
  showThinking();
  try {
    const data = await api('/tasks/submit', {
      method: 'POST',
      body: JSON.stringify({ description: text }),
    });
    // If immediate response, show it
    if (data.reply || data.response) {
      appendChatMessage('assistant', data.reply || data.response);
    }
  } catch (e) {
    appendChatMessage('assistant', 'Fehler beim Senden: ' + e.message);
  }
}

document.getElementById('chat-input')?.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
});

// ============================================
// Tasks
// ============================================

async function loadTasks() {
  try {
    const status = document.getElementById('task-status-filter')?.value || '';
    const search = document.getElementById('task-search')?.value || '';
    let url = `/tasks?limit=${TASKS_LIMIT}&offset=${tasksOffset}`;
    if (status) url += '&status=' + encodeURIComponent(status);
    if (search) url += '&search=' + encodeURIComponent(search);
    const data = await api(url);
    const tasks = data.tasks || [];

    const tbody = document.getElementById('tasks-tbody');
    if (tasks.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" class="text-muted">Keine Tasks gefunden</td></tr>';
    } else {
      tbody.innerHTML = tasks.map(t => `
        <tr>
          <td>${esc(t.description || t.task || '')}</td>
          <td>${badge(t.status || 'open')}</td>
          <td>${agentBadge(t.agent_type)} ${esc(t.agent_id ? t.agent_id.slice(-8) : '')}</td>
          <td>${relTime(t.created_at)}</td>
          <td>
            ${t.status === 'open' ? `<button class="btn btn-sm" onclick="patchTaskStatus('${esc(t.id)}','in_progress')">Starten</button>` : ''}
            ${t.status === 'in_progress' ? `<button class="btn btn-sm" onclick="patchTaskStatus('${esc(t.id)}','done')">Fertig</button>` : ''}
            <button class="btn btn-sm btn-danger" onclick="deleteTask('${esc(t.id)}')">X</button>
          </td>
        </tr>
      `).join('');
    }

    // Pagination
    const total = data.total || tasks.length;
    const pagEl = document.getElementById('tasks-pagination');
    if (total > TASKS_LIMIT) {
      const page = Math.floor(tasksOffset / TASKS_LIMIT) + 1;
      const pages = Math.ceil(total / TASKS_LIMIT);
      pagEl.innerHTML = `
        <button class="btn btn-sm" onclick="tasksOffset=Math.max(0,tasksOffset-${TASKS_LIMIT});loadTasks()" ${page <= 1 ? 'disabled' : ''}>Zurueck</button>
        <span>Seite ${page} von ${pages}</span>
        <button class="btn btn-sm" onclick="tasksOffset+=${TASKS_LIMIT};loadTasks()" ${page >= pages ? 'disabled' : ''}>Weiter</button>
      `;
    } else {
      pagEl.innerHTML = '';
    }
  } catch (e) {
    console.error('Tasks load error:', e);
    document.getElementById('tasks-tbody').innerHTML = '<tr><td colspan="5" class="text-muted">Fehler beim Laden</td></tr>';
  }
}

function toggleTaskView() {
  taskViewMode = taskViewMode === 'table' ? 'kanban' : 'table';
  document.getElementById('tasks-table-view').classList.toggle('hidden', taskViewMode !== 'table');
  document.getElementById('tasks-kanban-view').classList.toggle('hidden', taskViewMode !== 'kanban');
  if (taskViewMode === 'kanban') loadKanban();
}

async function loadKanban() {
  try {
    const data = await api('/tasks?limit=200');
    const tasks = data.tasks || [];
    const cols = { open: [], in_progress: [], done: [], failed: [] };
    tasks.forEach(t => {
      const s = t.status || 'open';
      if (cols[s]) cols[s].push(t); else cols.open.push(t);
    });
    const labels = { open: 'Offen', in_progress: 'In Arbeit', done: 'Erledigt', failed: 'Fehlgeschlagen' };
    const el = document.getElementById('tasks-kanban-view');
    el.innerHTML = '<div class="kanban">' + Object.entries(cols).map(([key, items]) => `
      <div class="kanban-col">
        <h4>${labels[key]} (${items.length})</h4>
        ${items.map(t => `
          <div class="kanban-card" onclick="patchTaskStatus('${esc(t.id)}','${key === 'open' ? 'in_progress' : key === 'in_progress' ? 'done' : key}')">
            <div>${esc(t.description || t.task || '')}</div>
            <div style="font-size:11px;color:var(--text-muted);margin-top:4px">${relTime(t.created_at)}</div>
          </div>
        `).join('')}
      </div>
    `).join('') + '</div>';
  } catch (e) { console.error('Kanban load error:', e); }
}

async function patchTaskStatus(id, status) {
  try {
    await api('/tasks/' + id, { method: 'PATCH', body: JSON.stringify({ status }) });
    showToast('Task aktualisiert');
    if (taskViewMode === 'kanban') loadKanban(); else loadTasks();
  } catch (e) { showToast('Fehler: ' + e.message); }
}

async function deleteTask(id) {
  if (!confirm('Task wirklich loeschen?')) return;
  try {
    await api('/tasks/' + id, { method: 'DELETE' });
    showToast('Task geloescht');
    loadTasks();
  } catch (e) { showToast('Fehler: ' + e.message); }
}

async function submitTask() {
  const desc = document.getElementById('task-modal-desc')?.value?.trim();
  const prio = document.getElementById('task-modal-priority')?.value || 'normal';
  if (!desc) { showToast('Beschreibung fehlt'); return; }
  try {
    await api('/tasks/submit', {
      method: 'POST',
      body: JSON.stringify({ description: desc, priority: prio }),
    });
    showToast('Task erstellt');
    closeModal('task-modal');
    document.getElementById('task-modal-desc').value = '';
    loadTasks();
  } catch (e) { showToast('Fehler: ' + e.message); }
}

// ============================================
// MCP
// ============================================

async function loadMCP() {
  try {
    const data = await api('/mcp/servers');
    // Support both {servers: [...], bridge_initialized: bool} and legacy bare array
    const servers = Array.isArray(data) ? data : (data.servers || []);
    const bridgeInitialized = Array.isArray(data) ? true : (data.bridge_initialized !== false);
    const grid = document.getElementById('mcp-grid');
    if (!Array.isArray(servers) || servers.length === 0) {
      const msg = !bridgeInitialized
        ? 'MCP Bridge nicht initialisiert (MCP_SERVERS in .env leer?)'
        : 'Keine MCP Server konfiguriert';
      grid.innerHTML = `<div class="card" style="grid-column:1/-1"><span class="text-muted">${msg}</span></div>`;
      return;
    }
    grid.innerHTML = servers.map(s => `
      <div class="card" id="mcp-card-${esc(s.id || s.name)}">
        <div class="card-header">
          <div style="display:flex;align-items:center;gap:8px">
            <div class="status-dot ${s.status === 'connected' || s.enabled ? 'online' : ''}"></div>
            ${esc(s.name || s.id)}
          </div>
          ${badge(s.status || (s.enabled ? 'active' : 'inactive'))}
        </div>
        <div style="font-size:13px;color:var(--text-muted);margin-bottom:8px">${s.tools_count || 0} Tools verfuegbar</div>
        ${s.command ? `<div style="font-size:12px;color:var(--text-muted)">Cmd: ${esc(s.command)}</div>` : ''}
        <div class="mt-16" style="display:flex;gap:6px;flex-wrap:wrap">
          <button class="btn btn-sm" onclick="loadMCPTools('${esc(s.id || s.name)}')">Tools anzeigen</button>
          <button class="btn btn-sm" onclick="restartMCPServer('${esc(s.id || s.name)}')">Neustart</button>
          <button class="btn btn-sm" onclick="toggleMCPServer('${esc(s.id || s.name)}', ${!s.enabled})">${s.enabled ? 'Deaktivieren' : 'Aktivieren'}</button>
        </div>
        <div id="mcp-tools-${esc(s.id || s.name)}" class="mt-16 hidden"></div>
      </div>
    `).join('');
  } catch (e) {
    document.getElementById('mcp-grid').innerHTML = '<div class="card"><span class="text-muted">MCP nicht erreichbar</span></div>';
    console.error('MCP load error:', e);
  }
}

async function loadMCPTools(serverId) {
  const el = document.getElementById('mcp-tools-' + serverId);
  if (!el) return;
  if (!el.classList.contains('hidden')) { el.classList.add('hidden'); return; }
  try {
    const data = await api('/mcp/servers/' + encodeURIComponent(serverId) + '/tools');
    const tools = data.tools || data || [];
    el.innerHTML = tools.length > 0
      ? '<table><thead><tr><th>Tool</th><th>Beschreibung</th></tr></thead><tbody>' +
        tools.map(t => `<tr><td><strong>${esc(t.name)}</strong></td><td style="font-size:12px">${esc(t.description || '')}</td></tr>`).join('') +
        '</tbody></table>'
      : '<span class="text-muted">Keine Tools</span>';
    el.classList.remove('hidden');
  } catch (e) {
    el.innerHTML = '<span class="text-muted">Fehler beim Laden</span>';
    el.classList.remove('hidden');
  }
}

async function restartMCPServer(serverId) {
  try {
    await api('/mcp/servers/' + encodeURIComponent(serverId) + '/restart', { method: 'POST' });
    showToast('MCP Server wird neu gestartet');
    setTimeout(loadMCP, 2000);
  } catch (e) { showToast('Fehler: ' + e.message); }
}

async function toggleMCPServer(serverId, enabled) {
  try {
    await api('/mcp/servers/' + encodeURIComponent(serverId) + '/toggle', {
      method: 'POST',
      body: JSON.stringify({ enabled }),
    });
    showToast(enabled ? 'Server aktiviert' : 'Server deaktiviert');
    loadMCP();
  } catch (e) { showToast('Fehler: ' + e.message); }
}

// ============================================
// Schedules
// ============================================

async function loadSchedules() {
  try {
    const data = await api('/schedules');
    const schedules = data.tasks || data.schedules || [];
    const grid = document.getElementById('schedules-grid');
    if (schedules.length === 0) {
      grid.innerHTML = '<div class="card" style="grid-column:1/-1"><span class="text-muted">Keine Schedules</span></div>';
      return;
    }
    grid.innerHTML = schedules.map(s => `
      <div class="card">
        <div class="card-header">
          <div style="display:flex;align-items:center;gap:8px">
            <div class="status-dot ${s.active ? 'online' : ''}"></div>
            ${esc(s.task || s.description || 'Schedule')}
          </div>
          ${badge(s.active ? 'active' : 'inactive')}
        </div>
        <div style="font-size:13px;color:var(--text-muted)">Cron: <code>${esc(s.cron || '')}</code></div>
        ${s.next_run ? `<div style="font-size:12px;color:var(--text-muted);margin-top:4px">Naechste: ${relTimeFuture(s.next_run)}</div>` : ''}
        ${s.last_run ? `<div style="font-size:12px;color:var(--text-muted)">Letzte: ${relTime(s.last_run)}</div>` : ''}
        <div class="mt-16" style="display:flex;gap:6px">
          <button class="btn btn-sm btn-primary" onclick="runSchedule('${esc(s.id)}')">Jetzt ausfuehren</button>
          <button class="btn btn-sm" onclick="toggleSchedule('${esc(s.id)}')">${s.active ? 'Pausieren' : 'Aktivieren'}</button>
          <button class="btn btn-sm btn-danger" onclick="deleteSchedule('${esc(s.id)}')">Loeschen</button>
        </div>
      </div>
    `).join('');
  } catch (e) {
    document.getElementById('schedules-grid').innerHTML = '<div class="card"><span class="text-muted">Fehler beim Laden</span></div>';
    console.error('Schedules load error:', e);
  }
}

async function runSchedule(id) {
  try {
    await api('/schedules/' + id + '/run', { method: 'POST' });
    showToast('Schedule wird ausgefuehrt');
  } catch (e) { showToast('Fehler: ' + e.message); }
}

async function toggleSchedule(id) {
  try {
    await api('/schedules/' + id + '/toggle', { method: 'POST' });
    showToast('Schedule aktualisiert');
    loadSchedules();
  } catch (e) { showToast('Fehler: ' + e.message); }
}

async function deleteSchedule(id) {
  if (!confirm('Schedule wirklich loeschen?')) return;
  try {
    await api('/schedules/' + id, { method: 'DELETE' });
    showToast('Schedule geloescht');
    loadSchedules();
  } catch (e) { showToast('Fehler: ' + e.message); }
}

async function submitSchedule() {
  const task = document.getElementById('schedule-modal-task')?.value?.trim();
  const cron = document.getElementById('schedule-modal-cron')?.value?.trim();
  if (!task || !cron) { showToast('Felder ausfuellen'); return; }
  try {
    await api('/schedules', {
      method: 'POST',
      body: JSON.stringify({ task, cron }),
    });
    showToast('Schedule erstellt');
    closeModal('schedule-modal');
    document.getElementById('schedule-modal-task').value = '';
    document.getElementById('schedule-modal-cron').value = '';
    loadSchedules();
  } catch (e) { showToast('Fehler: ' + e.message); }
}

// ============================================
// Memory
// ============================================

function switchMemTab(tab) {
  currentMemTab = tab;
  document.querySelectorAll('[data-mem-tab]').forEach(b => {
    b.classList.toggle('btn-primary', b.dataset.memTab === tab);
  });
  loadMemory();
}

async function loadMemory() {
  try {
    const data = await api('/memory?layer=' + currentMemTab);
    const entries = data.entries || data.memories || data || [];
    const el = document.getElementById('memory-content');
    const labels = { short: 'Kurzzeit', long: 'Langzeit', entity: 'Entitaeten' };
    if (Array.isArray(entries) && entries.length > 0) {
      el.innerHTML = entries.map(m => `
        <div class="activity-item" style="padding:8px 0">
          <span style="flex:1">${esc(m.content || m.text || m.key || JSON.stringify(m))}</span>
          <span class="activity-time">${relTime(m.created_at || m.timestamp)}</span>
          <button class="btn-icon" onclick="deleteMemory('${esc(m.id || '')}')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
          </button>
        </div>
      `).join('');
    } else {
      el.innerHTML = `<span class="text-muted">Keine ${labels[currentMemTab] || ''} Eintraege</span>`;
    }
  } catch (e) {
    document.getElementById('memory-content').innerHTML = '<span class="text-muted">Memory nicht verfuegbar</span>';
    console.error('Memory load error:', e);
  }
}

async function addMemory() {
  const input = document.getElementById('memory-input');
  const text = input.value.trim();
  if (!text) return;
  try {
    await api('/memory', {
      method: 'POST',
      body: JSON.stringify({ content: text, layer: currentMemTab }),
    });
    input.value = '';
    showToast('Eintrag gespeichert');
    loadMemory();
  } catch (e) { showToast('Fehler: ' + e.message); }
}

async function deleteMemory(id) {
  if (!id) return;
  try {
    await api('/memory/' + id, { method: 'DELETE' });
    showToast('Eintrag geloescht');
    loadMemory();
  } catch (e) { showToast('Fehler: ' + e.message); }
}

// ============================================
// Obsidian
// ============================================

async function loadObsidian() {
  try {
    const data = await api('/obsidian/recent?limit=50');
    const notes = data.notes || data || [];
    const el = document.getElementById('obsidian-list');
    if (Array.isArray(notes) && notes.length > 0) {
      el.innerHTML = notes.map(n => `
        <div class="note-item" onclick="openNote('${esc(n.path || n.name || '')}')">
          <div>${esc(n.name || n.title || n.path || '')}</div>
          <div style="font-size:11px;color:var(--text-muted)">${relTime(n.modified || n.updated_at)}</div>
        </div>
      `).join('');
    } else {
      el.innerHTML = '<span class="text-muted">Keine Notizen gefunden</span>';
    }
  } catch (e) {
    document.getElementById('obsidian-list').innerHTML = '<span class="text-muted">Obsidian nicht verbunden</span>';
    console.error('Obsidian load error:', e);
  }
}

async function openNote(path) {
  if (!path) return;
  try {
    const data = await api('/obsidian/note?path=' + encodeURIComponent(path));
    document.getElementById('obsidian-note-title').textContent = data.name || data.title || path;
    document.getElementById('obsidian-viewer').textContent = data.content || data.text || '';
  } catch (e) {
    document.getElementById('obsidian-viewer').textContent = 'Fehler beim Laden der Notiz';
  }
}

// ============================================
// System
// ============================================

async function loadSystem() {
  try {
    const data = await api('/system/metrics');
    const gaugesEl = document.getElementById('system-gauges');

    const metrics = [
      { label: 'CPU', value: data.cpu_percent ?? data.cpu ?? 0, unit: '%', color: 'var(--accent)' },
      { label: 'RAM', value: data.ram_percent ?? data.memory ?? 0, unit: '%', color: 'var(--green)' },
    ];
    if (data.gpu_percent != null) metrics.push({ label: 'GPU', value: data.gpu_percent, unit: '%', color: 'var(--purple)' });
    if (data.temp != null) metrics.push({ label: 'Temperatur', value: data.temp, unit: '\u00b0C', color: 'var(--amber)', max: 100 });
    if (data.disk_percent != null) metrics.push({ label: 'Disk', value: data.disk_percent, unit: '%', color: 'var(--red)' });

    gaugesEl.innerHTML = metrics.map(m => {
      const pct = Math.min(100, Math.max(0, m.value));
      const deg = (pct / 100) * 360;
      return `
        <div class="card" style="text-align:center">
          <div class="gauge-ring" style="background:conic-gradient(${m.color} ${deg}deg, var(--border) ${deg}deg)">
            <div class="gauge-inner">${Math.round(m.value)}${m.unit}</div>
          </div>
          <div style="font-weight:600">${m.label}</div>
        </div>
      `;
    }).join('');

    // Ollama models
    try {
      const mData = await api('/ollama/models');
      const models = mData.models || mData || [];
      const modelsEl = document.getElementById('system-models');
      if (Array.isArray(models) && models.length > 0) {
        modelsEl.innerHTML = models.map(m => `
          <div class="activity-item">
            <span><strong>${esc(m.name || m.model || '')}</strong></span>
            <span class="activity-time">${m.size ? (m.size / 1e9).toFixed(1) + ' GB' : ''}</span>
          </div>
        `).join('');
      } else {
        modelsEl.innerHTML = '<span class="text-muted">Keine Modelle geladen</span>';
      }
    } catch (_) {
      document.getElementById('system-models').innerHTML = '<span class="text-muted">Ollama nicht erreichbar</span>';
    }

    // DB stats — fetched from /health endpoint
    try {
      const healthData = await api('/health');
      const dbStats = healthData.db_stats || {};
      const dbEl = document.getElementById('system-db');
      dbEl.innerHTML = `
        <div class="activity-item"><span>Tasks</span><span class="activity-time">${dbStats.tasks ?? '\u2014'}</span></div>
        <div class="activity-item"><span>Messages</span><span class="activity-time">${dbStats.messages ?? '\u2014'}</span></div>
        <div class="activity-item"><span>Tool Logs</span><span class="activity-time">${dbStats.tool_log ?? '\u2014'}</span></div>
        <div class="activity-item"><span>Schedules</span><span class="activity-time">${dbStats.schedules ?? '\u2014'}</span></div>
      `;
    } catch (_) {
      document.getElementById('system-db').innerHTML = '<span class="text-muted">DB Stats nicht verfuegbar</span>';
    }
  } catch (e) {
    document.getElementById('system-gauges').innerHTML = '<div class="card"><span class="text-muted">System nicht erreichbar</span></div>';
    console.error('System load error:', e);
  }
}

// ============================================
// Settings / Config
// ============================================

const CONFIG_GROUPS = {
  'Allgemein': ['api_token', 'bot_name', 'language'],
  'LLM': ['ollama_host', 'ollama_model', 'ollama_model_heavy', 'ollama_num_ctx', 'ollama_keep_alive'],
  'Telegram': ['telegram_bot_token', 'telegram_admin_id'],
  'Obsidian': ['obsidian_vault_path'],
  'MCP Server': ['mcp_servers', 'mcp_apple_enabled', 'mcp_desktop_commander_enabled', 'mcp_obsidian_enabled', 'mcp_node_path', 'mcp_auto_restart'],
  'API Schluessel': ['serper_api_key', 'brave_api_key'],
};

const CONFIG_LABELS = {
  api_token: 'API Token',
  bot_name: 'Bot Name',
  language: 'Sprache',
  ollama_host: 'Ollama Host',
  ollama_model: 'Ollama Modell (Light)',
  ollama_model_heavy: 'Ollama Modell (Heavy)',
  premium_provider: 'Premium Provider',
  premium_model: 'Premium Modell',
  telegram_bot_token: 'Telegram Bot Token',
  telegram_admin_id: 'Telegram Admin ID',
  obsidian_vault_path: 'Vault Pfad',
  ollama_num_ctx: 'Kontext-Fenster',
  ollama_keep_alive: 'Keep Alive',
  serper_api_key: 'Serper API Key',
  brave_api_key: 'Brave API Key',
  mcp_servers: 'MCP Server (kommagetrennt)',
  mcp_apple_enabled: 'Apple MCP aktiv',
  mcp_desktop_commander_enabled: 'Desktop Commander aktiv',
  mcp_obsidian_enabled: 'Obsidian MCP aktiv',
  mcp_node_path: 'Node/NPX Pfad',
  mcp_auto_restart: 'Auto-Restart',
};

async function loadConfig() {
  try {
    const data = await api('/config');
    // Backend returns {config: [{key, value, category, description}, ...]}
    // Convert list → plain {key: value} map for easy lookup
    const rawConfig = data.config || data || {};
    let config = {};
    if (Array.isArray(rawConfig)) {
      rawConfig.forEach(entry => { if (entry.key) config[entry.key] = entry.value ?? ''; });
    } else if (typeof rawConfig === 'object') {
      config = rawConfig;
    }
    const container = document.getElementById('config-container');

    container.innerHTML = Object.entries(CONFIG_GROUPS).map(([group, keys]) => {
      const rows = keys.map(key => {
        const val = config[key] ?? '';
        const label = CONFIG_LABELS[key] || key;
        const isSecret = key.includes('token') || key.includes('key');
        return `<div class="config-row">
          <label>${esc(label)}</label>
          <input type="${isSecret ? 'password' : 'text'}" data-config-key="${esc(key)}" data-group="${esc(group)}" value="${esc(val)}">
        </div>`;
      }).join('');
      return `<div class="config-group">
        <h4>${esc(group)}</h4>
        ${rows}
        <button class="btn btn-sm btn-primary mt-16" onclick="saveConfigGroup(this, '${esc(group)}')">Speichern</button>
      </div>`;
    }).join('');

    // Server-Verwaltung: Update + Neustart
    container.innerHTML += `
      <div class="config-group" style="margin-top:24px">
        <h4>Server-Verwaltung</h4>
        <div style="display:flex;gap:12px;flex-wrap:wrap">
          <button class="btn btn-primary" onclick="runUpdate()">
            Git Pull + Update
          </button>
          <button class="btn btn-danger" onclick="restartServer()">
            Server neustarten
          </button>
        </div>
        <div id="update-output" style="display:none;margin-top:12px">
          <pre style="background:var(--bg-tertiary);padding:12px;border-radius:var(--radius);font-size:12px;max-height:300px;overflow-y:auto;white-space:pre-wrap"></pre>
        </div>
      </div>`;
  } catch (e) {
    document.getElementById('config-container').innerHTML = '<span class="text-muted">Konfiguration nicht ladbar</span>';
    console.error('Config load error:', e);
  }
}

async function saveConfigGroup(btn, group) {
  const inputs = document.querySelectorAll(`input[data-group="${group}"]`);
  const updates = {};
  inputs.forEach(inp => {
    updates[inp.dataset.configKey] = inp.value;
  });
  try {
    await api('/config', {
      method: 'PUT',
      body: JSON.stringify({ updates }),
    });
    showToast(group + ' gespeichert');
  } catch (e) { showToast('Fehler: ' + e.message); }
}

async function runUpdate() {
  const output = document.getElementById('update-output');
  const pre = output.querySelector('pre');
  output.style.display = 'block';
  pre.textContent = 'Update wird gestartet...\n';
  try {
    const resp = await fetch(API + '/update', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + localStorage.getItem('falkenstein_token') },
    });
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      pre.textContent += decoder.decode(value);
      pre.scrollTop = pre.scrollHeight;
    }
    pre.textContent += '\n--- Update abgeschlossen ---\n';
    showToast('Update abgeschlossen — Server startet neu...');
    setTimeout(() => location.reload(), 5000);
  } catch (e) {
    pre.textContent += '\nFehler: ' + e.message;
    showToast('Update fehlgeschlagen');
  }
}

function restartServer() {
  if (!confirm('Server wirklich neustarten?')) return;
  fetch(API + '/restart', {
    method: 'POST',
    headers: { 'Authorization': 'Bearer ' + localStorage.getItem('falkenstein_token') },
  }).then(() => {
    showToast('Server startet neu...');
    // Countdown overlay
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.8);display:flex;align-items:center;justify-content:center;z-index:9999;color:white;font-size:24px;font-family:monospace';
    overlay.textContent = 'Neustart... Seite lädt in 5s neu';
    document.body.appendChild(overlay);
    setTimeout(() => location.reload(), 5000);
  }).catch(e => showToast('Fehler: ' + e.message));
}

// ============================================
// Modals
// ============================================

function openModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add('open');
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove('open');
}

// Close modals on overlay click
document.querySelectorAll('.modal-overlay').forEach(overlay => {
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) overlay.classList.remove('open');
  });
});

// ============================================
// Command Palette
// ============================================

const COMMANDS = [
  { name: 'Dashboard oeffnen', key: 'dashboard', shortcut: '1', action: () => navigateTo('dashboard') },
  { name: 'Agents anzeigen', key: 'agents', shortcut: '2', action: () => navigateTo('agents') },
  { name: 'Chat oeffnen', key: 'chat', shortcut: '3', action: () => navigateTo('chat') },
  { name: 'Tasks anzeigen', key: 'tasks', shortcut: '4', action: () => navigateTo('tasks') },
  { name: 'MCP Server', key: 'mcp', shortcut: '5', action: () => navigateTo('mcp') },
  { name: 'Schedules', key: 'schedules', shortcut: '6', action: () => navigateTo('schedules') },
  { name: 'Memory', key: 'memory', shortcut: '7', action: () => navigateTo('memory') },
  { name: 'Obsidian', key: 'obsidian', shortcut: '8', action: () => navigateTo('obsidian') },
  { name: 'System', key: 'system', shortcut: '9', action: () => navigateTo('system') },
  { name: 'Einstellungen', key: 'settings', shortcut: '0', action: () => navigateTo('settings') },
  { name: 'Theme wechseln', key: 'theme', action: toggleTheme },
  { name: 'Neuer Task', key: 'newtask', action: () => openModal('task-modal') },
  { name: 'Neuer Schedule', key: 'newschedule', action: () => openModal('schedule-modal') },
  { name: 'Pixel-Buero oeffnen', key: 'pixelbuero', action: () => window.open('/static/office.html', '_blank') },
];

function navigateTo(section) {
  const btn = document.querySelector(`.sidebar-btn[data-section="${section}"]`);
  if (btn) btn.click();
}

function openCommandPalette() {
  openModal('cmd-palette');
  const input = document.getElementById('cmd-search');
  if (input) { input.value = ''; input.focus(); }
  renderCommands(COMMANDS);
}

function filterCommands() {
  const q = (document.getElementById('cmd-search')?.value || '').toLowerCase();
  const filtered = COMMANDS.filter(c => c.name.toLowerCase().includes(q) || c.key.includes(q));
  renderCommands(filtered);
}

function renderCommands(cmds) {
  const el = document.getElementById('cmd-list');
  if (!el) return;
  el.innerHTML = cmds.map((c, i) => `
    <div class="cmd-item ${i === 0 ? 'selected' : ''}" onclick="executeCommand(${COMMANDS.indexOf(c)})">
      <span>${esc(c.name)}</span>
      ${c.shortcut ? `<kbd>${c.shortcut}</kbd>` : ''}
    </div>
  `).join('');
}

function executeCommand(idx) {
  closeModal('cmd-palette');
  if (COMMANDS[idx]) COMMANDS[idx].action();
}

// Command palette keyboard navigation
document.getElementById('cmd-search')?.addEventListener('keydown', (e) => {
  const items = document.querySelectorAll('.cmd-item');
  const selected = document.querySelector('.cmd-item.selected');
  const idx = Array.from(items).indexOf(selected);

  if (e.key === 'ArrowDown') {
    e.preventDefault();
    if (selected) selected.classList.remove('selected');
    const next = items[Math.min(idx + 1, items.length - 1)];
    if (next) next.classList.add('selected');
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    if (selected) selected.classList.remove('selected');
    const prev = items[Math.max(idx - 1, 0)];
    if (prev) prev.classList.add('selected');
  } else if (e.key === 'Enter') {
    e.preventDefault();
    if (selected) selected.click();
  }
});

// ============================================
// Keyboard Shortcuts
// ============================================

document.addEventListener('keydown', (e) => {
  // Ctrl+K / Cmd+K → command palette
  if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
    e.preventDefault();
    openCommandPalette();
    return;
  }
  // Escape → close modals
  if (e.key === 'Escape') {
    document.querySelectorAll('.modal-overlay.open').forEach(m => m.classList.remove('open'));
    return;
  }
  // / → focus quick chat (only if not in input)
  if (e.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) {
    e.preventDefault();
    document.getElementById('quickchat-input')?.focus();
  }
});

// ============================================
// Init
// ============================================

updateThemeIcon();
loadDashboard();
connectWS();
