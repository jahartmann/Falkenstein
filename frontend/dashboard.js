'use strict';

const API = '/api/admin';
let ws = null;
let tasksOffset = 0;
const TASKS_LIMIT = 50;
const activityLog = [];
let _searchTimer = null;

function esc(str) {
  const d = document.createElement('div');
  d.textContent = String(str ?? '');
  return d.innerHTML;
}

function badge(status) {
  const cls = {
    open: 'badge-open', in_progress: 'badge-in_progress', done: 'badge-done',
    failed: 'badge-failed', active: 'badge-active', inactive: 'badge-inactive',
    error: 'badge-error', ok: 'badge-ok',
  }[status] || 'badge-open';
  return `<span class="badge ${cls}">${esc(status)}</span>`;
}

function agentBadge(agent) {
  if (!agent) return '';
  const cls = { coder: 'badge-coder', researcher: 'badge-researcher', writer: 'badge-writer', ops: 'badge-ops' }[agent] || '';
  return `<span class="badge ${cls}">${esc(agent)}</span>`;
}

function relTime(dateStr) {
  if (!dateStr) return '—';
  const d = new Date(dateStr);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return 'gerade eben';
  if (diff < 3600) return Math.floor(diff / 60) + ' Min';
  if (diff < 86400) return Math.floor(diff / 3600) + ' Std';
  return d.toLocaleDateString('de');
}

function relTimeFuture(dateStr) {
  if (!dateStr) return '—';
  const d = new Date(dateStr);
  const diff = (d.getTime() - Date.now()) / 1000;
  if (diff <= 0) return 'fällig';
  if (diff < 60) return 'in ' + Math.ceil(diff) + ' Sek';
  if (diff < 3600) return 'in ' + Math.ceil(diff / 60) + ' Min';
  if (diff < 86400) return 'in ' + Math.floor(diff / 3600) + ' Std';
  return d.toLocaleDateString('de') + ' ' + d.toLocaleTimeString('de', {hour:'2-digit', minute:'2-digit'});
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

// Navigation
document.querySelectorAll('.sidebar-btn[data-section]').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.sidebar-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    btn.classList.add('active');
    const section = document.getElementById('section-' + btn.dataset.section);
    if (section) section.classList.add('active');
    const s = btn.dataset.section;
    if (s === 'dashboard') loadDashboard();
    else if (s === 'tasks') loadTasks();
    else if (s === 'schedules') loadSchedules();
    else if (s === 'config') loadConfig();
    else if (s === 'siri') loadSiri();
    else if (s === 'chat') loadChat();
    else if (s === 'timeline') loadTimeline();
    else if (s === 'memory') loadMemory();
    else if (s === 'reminders') loadReminders();
    else if (s === 'toollog') loadToolLog();
    else if (s === 'obsidian') loadObsidian();
    else if (s === 'health') loadHealth();
    else if (s === 'files') loadFiles('');
  });
});

// Dashboard
async function loadDashboard() {
  try {
    const data = await api('/dashboard');
    document.getElementById('stat-agents').textContent = data.active_agents ? data.active_agents.length : 0;
    document.getElementById('stat-tasks').textContent = data.open_tasks_count || 0;
    try {
      const sData = await api('/schedules');
      document.getElementById('stat-schedules').textContent = (sData.tasks || []).filter(s => s.active).length;
    } catch (_) {}
    try {
      const errData = await api('/tasks?status=failed&limit=100');
      const today = new Date().toISOString().slice(0, 10);
      document.getElementById('stat-errors').textContent = (errData.tasks || []).filter(t => (t.created_at || '').startsWith(today)).length;
    } catch (_) {}
    const agentsList = document.getElementById('agents-list');
    if (data.active_agents && data.active_agents.length > 0) {
      agentsList.innerHTML = data.active_agents.map(a => {
        const task = a.task || a.name || 'agent';
        const type = a.type || '';
        return `<div class="agent-chip" data-agent-id="${esc(a.agent_id || '')}" onclick="showAgentLog('${esc(a.agent_id || '')}')" style="cursor:pointer"><div class="agent-pulse"></div><span>${esc(task)}</span><span class="agent-type">${esc(type)}</span><span class="agent-tool-status"></span></div>`;
      }).join('');
    } else {
      agentsList.innerHTML = '<span class="text-muted">Keine aktiven Agents</span>';
    }
    renderActivity();
  } catch (e) { console.error('Dashboard load error:', e); }
}

// Activity Feed
function addActivity(type, text) {
  const colors = { agent_spawned: 'var(--blue)', agent_done: 'var(--green)', agent_error: 'var(--red)', task_created: 'var(--cyan)', schedule_fired: 'var(--purple)', agent_progress: 'var(--amber)' };
  activityLog.unshift({ type, text, color: colors[type] || 'var(--text-muted)', time: new Date() });
  if (activityLog.length > 20) activityLog.length = 20;
  if (document.getElementById('section-dashboard').classList.contains('active')) renderActivity();
}

function renderActivity() {
  const el = document.getElementById('activity-feed');
  if (activityLog.length === 0) { el.innerHTML = '<span class="text-muted">Keine Aktivität</span>'; return; }
  el.innerHTML = activityLog.map(a =>
    `<div class="activity-item"><div class="activity-icon" style="background:${a.color}"></div><span>${esc(a.text)}</span><span class="activity-time">${relTime(a.time)}</span></div>`
  ).join('');
}

// Agent Log
async function showAgentLog(agentId) {
  if (!agentId) return;
  const panel = document.getElementById('agent-log-panel');
  document.getElementById('agent-log-title').textContent = agentId.slice(-8);
  panel.dataset.agentId = agentId;
  try {
    const data = await api('/agents/' + agentId + '/log');
    const logEl = document.getElementById('agent-log');
    const logs = data.logs || [];
    if (logs.length > 0) {
      logEl.innerHTML = logs.map(l => {
        const icon = l.success ? 'var(--green)' : 'var(--red)';
        const preview = l.output ? l.output.slice(0, 100) : '';
        return `<div class="activity-item">
          <div class="activity-icon" style="background:${icon}"></div>
          <span><strong>${esc(l.tool)}</strong> ${esc(preview)}</span>
          <span class="activity-time">${relTime(l.time)}</span>
        </div>`;
      }).join('');
    } else {
      logEl.innerHTML = '<span class="text-muted">Kein Log vorhanden</span>';
    }
    panel.style.display = 'block';
  } catch (e) { console.error('Agent log error:', e); }
}

function closeAgentLog() {
  document.getElementById('agent-log-panel').style.display = 'none';
}

// Tasks
async function loadTasks() {
  try {
    const status = document.getElementById('filter-status').value;
    const agent = document.getElementById('filter-agent').value;
    const search = document.getElementById('filter-search').value.trim();
    const params = new URLSearchParams({ limit: TASKS_LIMIT, offset: tasksOffset });
    if (status) params.set('status', status);
    if (agent) params.set('agent', agent);
    if (search) params.set('search', search);
    const data = await api('/tasks?' + params);
    const tbody = document.getElementById('tasks-table');
    const tasks = data.tasks || [];
    if (tasks.length > 0) {
      tbody.innerHTML = tasks.map(t => {
        const preview = t.result ? t.result.slice(0, 80) + (t.result.length > 80 ? '...' : '') : '';
        return `<tr class="expandable" onclick="toggleTaskRow(this, ${t.id})">
          <td>#${t.id}</td><td>${esc(t.title)}</td><td>${badge(t.status)}</td>
          <td>${agentBadge(t.agent)}</td><td>${relTime(t.created_at)}</td>
          <td class="text-muted" style="font-size:12px">${esc(preview)}</td>
          <td><button class="btn btn-sm btn-danger" onclick="event.stopPropagation();deleteTask(${t.id})">×</button></td>
        </tr>`;
      }).join('');
    } else {
      tbody.innerHTML = '<tr><td colspan="7" class="text-muted" style="text-align:center;padding:24px">Keine Tasks</td></tr>';
    }
    const pag = document.getElementById('tasks-pagination');
    if (data.total > TASKS_LIMIT) {
      const hasMore = tasksOffset + TASKS_LIMIT < data.total;
      const hasPrev = tasksOffset > 0;
      pag.innerHTML = `${hasPrev ? '<button class="btn btn-sm" onclick="tasksOffset -= ' + TASKS_LIMIT + '; loadTasks()">← Zurück</button>' : ''}
        <span class="text-muted" style="font-size:12px">${tasksOffset + 1}–${Math.min(tasksOffset + TASKS_LIMIT, data.total)} von ${data.total}</span>
        ${hasMore ? '<button class="btn btn-sm" onclick="tasksOffset += ' + TASKS_LIMIT + '; loadTasks()">Weiter →</button>' : ''}`;
    } else { pag.innerHTML = ''; }
  } catch (e) { console.error('Tasks load error:', e); }
}

async function toggleTaskRow(tr, taskId) {
  const existing = tr.nextElementSibling;
  if (existing && existing.classList.contains('task-expanded-row')) { existing.remove(); return; }
  document.querySelectorAll('.task-expanded-row').forEach(r => r.remove());
  try {
    const t = await api('/tasks/' + taskId);
    if (t.error) return;
    const expandedRow = document.createElement('tr');
    expandedRow.className = 'task-expanded-row';
    expandedRow.innerHTML = `<td colspan="7"><div class="task-expanded">
      <div class="meta">Erstellt: ${esc(t.created_at)} | Aktualisiert: ${esc(t.updated_at)} ${t.project ? '| Projekt: ' + esc(t.project) : ''}</div>
      ${t.description ? '<div class="meta"><strong>Beschreibung:</strong> ' + esc(t.description) + '</div>' : ''}
      ${t.result ? '<pre>' + esc(t.result) + '</pre>' : '<span class="text-muted">Kein Ergebnis</span>'}
      <div class="task-actions">
        <select onchange="patchTaskStatus(${t.id}, this.value)" style="width:auto;min-width:120px">
          ${['open','in_progress','done','failed'].map(s => '<option value="' + s + '"' + (s === t.status ? ' selected' : '') + '>' + s + '</option>').join('')}
        </select>
      </div>
    </div></td>`;
    tr.after(expandedRow);
  } catch (e) { console.error('Task detail error:', e); }
}

async function patchTaskStatus(id, status) {
  try { await api('/tasks/' + id, { method: 'PATCH', body: JSON.stringify({ status }) }); loadTasks(); } catch (e) { console.error('Patch task error:', e); }
}

async function deleteTask(id) {
  if (!confirm('Task löschen?')) return;
  try { await api('/tasks/' + id, { method: 'DELETE' }); loadTasks(); } catch (e) { console.error('Delete task error:', e); }
}

async function submitTask() {
  const text = document.getElementById('task-text').value.trim();
  if (!text) return;
  try {
    await api('/tasks/submit', { method: 'POST', body: JSON.stringify({ text }) });
    document.getElementById('task-text').value = '';
    closeModal('modal-task');
    setTimeout(loadTasks, 1000);
    loadDashboard();
  } catch (e) { console.error('Submit task error:', e); }
}

// Schedules
async function loadSchedules() {
  try {
    const data = await api('/schedules');
    const tbody = document.getElementById('schedules-table');
    const tasks = data.tasks || [];
    if (tasks.length > 0) {
      tbody.innerHTML = tasks.map(s => {
        const active = s.active === 1 || s.active === true;
        const lastRun = s.last_run ? relTime(s.last_run) : 'Nie';
        const nextRun = s.next_run ? relTimeFuture(s.next_run) : '—';
        const resultBadge = s.last_status ? badge(s.last_status) : '<span class="text-muted">—</span>';
        return `<tr class="expandable" onclick="toggleScheduleRow(this, ${s.id})">
          <td><strong>${esc(s.name)}</strong></td>
          <td class="text-muted">${esc(s.schedule || '')}</td>
          <td>${agentBadge(s.agent_type)}</td>
          <td><label class="toggle" onclick="event.stopPropagation()"><input type="checkbox" ${active ? 'checked' : ''} onchange="toggleSchedule(${s.id})"><span class="toggle-slider"></span></label></td>
          <td class="text-muted">${lastRun}</td>
          <td class="text-muted">${nextRun}</td>
          <td>${resultBadge}</td>
          <td><div class="btn-group" onclick="event.stopPropagation()">
            <button class="btn btn-sm" onclick="editSchedule(${s.id})">Edit</button>
            <button class="btn btn-sm" onclick="runSchedule(${s.id})">Run</button>
            <button class="btn btn-sm btn-danger" onclick="deleteSchedule(${s.id})">×</button>
          </div></td>
        </tr>`;
      }).join('');
    } else {
      tbody.innerHTML = '<tr><td colspan="8" class="text-muted" style="text-align:center;padding:24px">Keine Schedules</td></tr>';
    }
  } catch (e) { console.error('Schedules load error:', e); }
}

async function toggleScheduleRow(tr, scheduleId) {
  const existing = tr.nextElementSibling;
  if (existing && existing.classList.contains('schedule-expanded-row')) { existing.remove(); return; }
  document.querySelectorAll('.schedule-expanded-row').forEach(r => r.remove());
  try {
    const s = await api('/schedules/' + scheduleId);
    if (s.error) return;
    const preview = (s.next_runs_preview || []).map(r => new Date(r).toLocaleString('de')).join('<br>');
    const expandedRow = document.createElement('tr');
    expandedRow.className = 'schedule-expanded-row';
    expandedRow.innerHTML = `<td colspan="8"><div class="task-expanded">
      <div class="meta"><strong>Prompt:</strong></div>
      <pre>${esc(s.prompt)}</pre>
      ${s.active_hours ? '<div class="meta">Aktive Stunden: ' + esc(s.active_hours) + '</div>' : ''}
      ${s.last_error ? '<div class="meta" style="color:var(--red)">Letzter Fehler: ' + esc(s.last_error) + '</div>' : ''}
      ${preview ? '<div class="meta"><strong>Nächste Ausführungen:</strong><br>' + preview + '</div>' : ''}
    </div></td>`;
    tr.after(expandedRow);
  } catch (e) { console.error('Schedule detail error:', e); }
}

function openScheduleModal(id) {
  document.getElementById('schedule-edit-id').value = id || '';
  document.getElementById('schedule-modal-title').textContent = id ? 'Schedule bearbeiten' : 'Neuer Schedule';
  document.getElementById('sched-name').value = '';
  document.getElementById('sched-schedule').value = '';
  document.getElementById('sched-agent-type').value = 'researcher';
  document.getElementById('sched-active-hours').value = '';
  document.getElementById('sched-prompt').value = '';
  document.getElementById('schedule-preview').classList.remove('visible');
  openModal('modal-schedule');
}

async function editSchedule(id) {
  try {
    const data = await api('/schedules/' + id);
    if (data.error) { alert(data.error); return; }
    document.getElementById('schedule-edit-id').value = id;
    document.getElementById('schedule-modal-title').textContent = 'Schedule bearbeiten';
    document.getElementById('sched-name').value = data.name || '';
    document.getElementById('sched-schedule').value = data.schedule || '';
    document.getElementById('sched-agent-type').value = data.agent_type || 'researcher';
    document.getElementById('sched-active-hours').value = data.active_hours || '';
    document.getElementById('sched-prompt').value = data.prompt || '';
    if (data.next_runs_preview && data.next_runs_preview.length) {
      const el = document.getElementById('schedule-preview');
      el.innerHTML = '<strong>Nächste Ausführungen:</strong><br>' + data.next_runs_preview.map(r => new Date(r).toLocaleString('de')).join('<br>');
      el.classList.add('visible');
    }
    openModal('modal-schedule');
  } catch (e) { console.error('Edit schedule error:', e); }
}

async function saveSchedule() {
  const editId = document.getElementById('schedule-edit-id').value;
  const payload = {
    name: document.getElementById('sched-name').value.trim(),
    schedule: document.getElementById('sched-schedule').value.trim(),
    agent_type: document.getElementById('sched-agent-type').value,
    prompt: document.getElementById('sched-prompt').value.trim(),
    active: true,
    active_hours: document.getElementById('sched-active-hours').value.trim() || null,
  };
  if (!payload.name || !payload.prompt) { alert('Name und Prompt sind Pflichtfelder'); return; }
  try {
    if (editId) { await api('/schedules/' + editId, { method: 'PUT', body: JSON.stringify(payload) }); }
    else { await api('/schedules', { method: 'POST', body: JSON.stringify(payload) }); }
    closeModal('modal-schedule');
    loadSchedules();
  } catch (e) { console.error('Save schedule error:', e); }
}

async function toggleSchedule(id) {
  try { await api('/schedules/' + id + '/toggle', { method: 'POST' }); loadSchedules(); } catch (e) { console.error('Toggle error:', e); }
}

async function runSchedule(id) {
  try {
    const res = await api('/schedules/' + id + '/run', { method: 'POST' });
    if (res.error) alert(res.error);
    else { loadSchedules(); loadDashboard(); }
  } catch (e) { console.error('Run error:', e); }
}

async function deleteSchedule(id) {
  if (!confirm('Schedule wirklich löschen?')) return;
  try { await api('/schedules/' + id, { method: 'DELETE' }); loadSchedules(); } catch (e) { console.error('Delete error:', e); }
}

async function aiCreateSchedule() {
  const desc = document.getElementById('ai-sched-desc').value.trim();
  if (!desc) return;
  try {
    const res = await api('/schedules/ai-create', { method: 'POST', body: JSON.stringify({ description: desc }) });
    if (res.created) { document.getElementById('ai-sched-desc').value = ''; closeModal('modal-ai-schedule'); loadSchedules(); }
    else if (res.error) { alert(res.error); }
  } catch (e) { console.error('AI create error:', e); }
}

// Config
const CONFIG_CATEGORIES = {
  'Server': ['api_token','telegram_bot_token','telegram_chat_id','telegram_allowed_chat_ids','port'],
  'LLM': ['ollama_host','ollama_model','ollama_model_light','ollama_model_heavy','ollama_num_ctx','ollama_num_ctx_extended','llm_max_retries','llm_provider_classify','llm_provider_action','llm_provider_content','llm_provider_scheduled','cli_provider','cli_daily_token_budget'],
  'Pfade': ['obsidian_vault_path','workspace_path'],
  'Persönlichkeit': ['soul_prompt'],
  'API Keys': ['brave_api_key'],
  'Allgemein': ['obsidian_enabled','obsidian_auto_knowledge'],
};
const TEXTAREA_KEYS = new Set(['soul_prompt']);
const PASSWORD_KEYS = new Set(['brave_api_key', 'api_token', 'telegram_bot_token']);
const PATH_KEYS = new Set(['obsidian_vault_path', 'workspace_path']);

async function loadConfig() {
  try {
    const data = await api('/config');
    const container = document.getElementById('config-container');
    const items = data.config || [];
    const configMap = {};
    items.forEach(item => { const key = item.key || ''; const value = item.value || ''; if (key) configMap[key] = value; });
    const assigned = new Set();
    const groups = {};
    for (const [cat, keys] of Object.entries(CONFIG_CATEGORIES)) {
      groups[cat] = {};
      keys.forEach(k => { if (k in configMap) { groups[cat][k] = configMap[k]; assigned.add(k); } });
    }
    for (const k of Object.keys(configMap)) { if (!assigned.has(k)) groups['Allgemein'][k] = configMap[k]; }
    let html = '';
    for (const [cat, entries] of Object.entries(groups)) {
      const keys = Object.keys(entries);
      if (keys.length === 0) continue;
      html += `<div class="config-group"><h3>${esc(cat)}</h3>`;
      keys.forEach(key => {
        const val = entries[key];
        html += `<div class="config-row"><label>${esc(key)}</label>`;
        if (TEXTAREA_KEYS.has(key)) {
          html += `<textarea data-key="${esc(key)}" rows="4">${esc(val)}</textarea>`;
        } else if (PASSWORD_KEYS.has(key)) {
          html += `<input type="password" data-key="${esc(key)}" value="${esc(val)}">`;
        } else if (PATH_KEYS.has(key)) {
          html += `<div style="display:flex;gap:6px;flex:1"><input type="text" data-key="${esc(key)}" value="${esc(val)}" style="flex:1"><button class="btn btn-sm" onclick="openFilePicker('${esc(key)}')">Durchsuchen</button></div>`;
        } else {
          html += `<input type="text" data-key="${esc(key)}" value="${esc(val)}">`;
        }
        html += `</div>`;
      });
      html += `<div class="config-actions"><button class="btn btn-primary btn-sm" onclick="saveConfigGroup(this)">Speichern</button></div></div>`;
    }
    container.innerHTML = html || '<p class="text-muted">Keine Konfiguration</p>';
  } catch (e) { console.error('Config load error:', e); }
}

async function restartServer() {
  if (!confirm('Server wirklich neustarten? Alle laufenden Agents werden gestoppt.')) return;
  try {
    await api('/restart', { method: 'POST' });
    document.getElementById('ws-dot').classList.remove('connected');
    // Show countdown and reconnect
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.8);z-index:999;display:flex;align-items:center;justify-content:center;color:#fff;font-size:18px;font-family:monospace';
    overlay.innerHTML = '<div style="text-align:center"><div>Server startet neu...</div><div id="restart-countdown" style="margin-top:12px;font-size:14px;color:var(--text-muted)">Verbinde in 5s...</div></div>';
    document.body.appendChild(overlay);
    let seconds = 5;
    const iv = setInterval(() => {
      seconds--;
      const el = document.getElementById('restart-countdown');
      if (el) el.textContent = `Verbinde in ${seconds}s...`;
      if (seconds <= 0) {
        clearInterval(iv);
        location.reload();
      }
    }, 1000);
  } catch (e) { console.error('Restart error:', e); }
}

async function saveConfigGroup(btn) {
  const group = btn.closest('.config-group');
  const inputs = group.querySelectorAll('[data-key]');
  const updates = {};
  inputs.forEach(el => { updates[el.dataset.key] = el.value; });
  try {
    const res = await api('/config', { method: 'PUT', body: JSON.stringify({ updates }) });
    if (res.saved) { btn.textContent = '✓ Gespeichert'; setTimeout(() => { btn.textContent = 'Speichern'; }, 1500); }
  } catch (e) { console.error('Save config error:', e); }
}

// Siri
async function loadSiri() {
  try {
    const data = await api('/siri-info');
    const token = data.api_token || '';
    const serverUrl = data.server_url || 'http://localhost:8800';
    const botUsername = data.bot_username || '';
    document.getElementById('siri-token').textContent = token || '(kein Token konfiguriert)';
    document.getElementById('siri-url').textContent = serverUrl;

    // Telegram deep link for the shortcut
    if (botUsername) {
      document.getElementById('siri-tg-deeplink').textContent = `https://t.me/${botUsername}?text=[Diktierter Text]`;
    } else {
      document.getElementById('siri-tg-deeplink').textContent = '(Bot-Username nicht verfügbar — Telegram Token prüfen)';
    }

    // Full URL with token for local API access
    const fullUrl = `${serverUrl}/api/admin/tasks/submit?token=${token}`;
    document.getElementById('siri-full-url').textContent = fullUrl;

    // API example for local network
    document.getElementById('siri-api-example').textContent = `URL: ${fullUrl}\nMethode: POST\nHeader: Content-Type: application/json\nBody: {"text": "[Diktierter Text]"}`;
  } catch (e) { console.error('Siri load error:', e); }
}

function copySiriFullUrl() {
  const url = document.getElementById('siri-full-url').textContent;
  navigator.clipboard.writeText(url).then(() => {
    const btn = event.target;
    if (btn) { const orig = btn.textContent; btn.textContent = 'Kopiert'; setTimeout(() => { btn.textContent = orig; }, 1500); }
  });
}

function copySiriToken() {
  const token = document.getElementById('siri-token').textContent;
  navigator.clipboard.writeText(token).then(() => {
    const btn = event.target;
    if (btn) { const orig = btn.textContent; btn.textContent = '✓ Kopiert'; setTimeout(() => { btn.textContent = orig; }, 1500); }
  });
}

// Modals
function openModal(id) { document.getElementById(id).classList.add('open'); }
function closeModal(id) { document.getElementById(id).classList.remove('open'); }
function closeModalOverlay(e) { if (e.target === e.currentTarget) e.target.classList.remove('open'); }

// WebSocket
function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const token = localStorage.getItem('falkenstein_token') || '';
  const url = proto + '//' + location.host + '/ws' + (token ? '?token=' + encodeURIComponent(token) : '');
  ws = new WebSocket(url);
  ws.onopen = () => { document.getElementById('ws-dot').classList.add('connected'); document.getElementById('ws-status').textContent = 'Verbunden'; };
  ws.onclose = () => { document.getElementById('ws-dot').classList.remove('connected'); document.getElementById('ws-status').textContent = 'Getrennt'; setTimeout(connectWS, 3000); };
  ws.onerror = () => ws.close();
  ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data);
      const type = msg.type || '';
      const labels = {
        agent_spawned: 'Agent gestartet: ' + (msg.task || msg.agent_type || ''),
        agent_done: 'Agent fertig: ' + (msg.task || ''),
        agent_error: 'Agent Fehler: ' + (msg.error || msg.task || ''),
        task_created: 'Task erstellt: ' + (msg.title || ''),
        schedule_fired: 'Schedule ausgeführt: ' + (msg.name || ''),
      };
      if (labels[type]) addActivity(type, labels[type]);
      // Feed timeline
      if (type === 'agent_spawned') addTimelineEvent(msg.agent_id || '', 'spawned', msg.task || 'Gestartet', msg.agent_type || '');
      if (type === 'agent_done') addTimelineEvent(msg.agent_id || '', 'done', 'Fertig', '');
      if (type === 'agent_error') addTimelineEvent(msg.agent_id || '', 'error', msg.error || 'Fehler', '');
      if (type === 'agent_progress') {
        addTimelineEvent(msg.agent_id || '', 'progress', msg.label || msg.tool || '...', '');
        addActivity('agent_progress', (msg.label || msg.tool) + ' (' + (msg.agent_id || '').slice(-8) + ')');
        // Live-update log panel if showing this agent
        const panel = document.getElementById('agent-log-panel');
        if (panel.style.display !== 'none' && panel.dataset.agentId === msg.agent_id) {
          const logEl = document.getElementById('agent-log');
          const item = document.createElement('div');
          item.className = 'activity-item';
          item.innerHTML = `<div class="activity-icon" style="background:var(--blue)"></div>
            <span><strong>${esc(msg.tool)}</strong> ${esc(msg.label)}</span>
            <span class="activity-time">jetzt</span>`;
          logEl.appendChild(item);
          logEl.scrollTop = logEl.scrollHeight;
        }
      }
      if (['agent_spawned','agent_done','agent_error','task_created'].includes(type)) {
        loadDashboard();
        if (document.getElementById('section-tasks').classList.contains('active')) loadTasks();
      }
      if (['schedule_fired','agent_done'].includes(type)) {
        if (document.getElementById('section-schedules').classList.contains('active')) loadSchedules();
      }
      // Chat replies via WS
      if (type === 'chat_reply' && msg.content) {
        appendChatMessage(msg.role || 'assistant', msg.content);
      }
    } catch (_) {}
  };
}

// ── Chat ────────────────────────────────────────────────────────────

async function loadChat() {
  try {
    const data = await api('/chat-history?limit=50');
    const el = document.getElementById('chat-messages');
    const msgs = data.messages || [];
    if (msgs.length > 0) {
      el.innerHTML = msgs.map(m => chatBubble(m.role, m.content, m.time)).join('');
    } else {
      el.innerHTML = '<div class="chat-empty">Noch keine Nachrichten. Schreib Falki!</div>';
    }
    el.scrollTop = el.scrollHeight;
  } catch (e) { console.error('Chat load error:', e); }
}

function chatBubble(role, content, time) {
  const cls = role === 'user' ? 'chat-msg-user' : 'chat-msg-assistant';
  const label = role === 'user' ? 'Du' : 'Falki';
  let body = esc(content);
  // Render file attachments
  const fileMatch = content.match(/\[Datei: (.+?)\]/);
  if (fileMatch) {
    const filePath = fileMatch[1];
    const fileName = filePath.split('/').pop();
    body = body.replace(
      esc('[Datei: ' + filePath + ']'),
      `<div class="chat-file-attachment" onclick="openChatFile('${esc(filePath.replace(/'/g, "\\'"))}')"><span class="file-icon-file"></span> <strong>${esc(fileName)}</strong><span class="text-muted" style="font-size:10px;margin-left:8px">Klicken zum Öffnen</span></div>`
    );
  }
  return `<div class="chat-msg ${cls}"><div class="chat-msg-header"><strong>${label}</strong><span class="activity-time">${relTime(time)}</span></div><div class="chat-msg-body">${body}</div></div>`;
}

function appendChatMessage(role, content) {
  const el = document.getElementById('chat-messages');
  if (!el) return;
  const empty = el.querySelector('.chat-empty');
  if (empty) empty.remove();
  const pending = el.querySelector('.chat-msg-pending');
  if (pending) pending.remove();
  el.innerHTML += chatBubble(role, content, new Date().toISOString());
  el.scrollTop = el.scrollHeight;
}

async function sendChat() {
  const input = document.getElementById('chat-input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  input.style.height = 'auto';

  const el = document.getElementById('chat-messages');
  const emptyMsg = el.querySelector('.chat-empty');
  if (emptyMsg) emptyMsg.remove();
  el.innerHTML += chatBubble('user', text, new Date().toISOString());
  el.innerHTML += `<div class="chat-msg chat-msg-assistant chat-msg-pending"><div class="chat-msg-header"><strong>Falki</strong><span class="activity-time">jetzt</span></div><div class="chat-msg-body"><span class="typing-indicator">Denkt nach...</span></div></div>`;
  el.scrollTop = el.scrollHeight;

  try {
    await api('/tasks/submit', { method: 'POST', body: JSON.stringify({ text }) });
  } catch (e) {
    const pending = el.querySelector('.chat-msg-pending');
    if (pending) pending.remove();
    appendChatMessage('assistant', 'Fehler beim Senden.');
    console.error('Chat send error:', e);
  }
}

function shareFileInChat(filePath) {
  const el = document.getElementById('chat-messages');
  if (!el) return;
  navTo('chat');
  setTimeout(async () => {
    const text = `Schau dir diese Datei an: ${filePath}`;
    el.innerHTML += chatBubble('user', `[Datei: ${filePath}]`, new Date().toISOString());
    el.scrollTop = el.scrollHeight;
    try {
      await api('/tasks/submit', { method: 'POST', body: JSON.stringify({ text }) });
    } catch (e) { console.error('Share file error:', e); }
  }, 100);
}

function openChatFile(path) {
  navTo('files');
  setTimeout(() => openFile(path), 200);
}

// ── Timeline ────────────────────────────────────────────────────────
const timelineEvents = [];

function addTimelineEvent(agentId, type, label, agentType) {
  timelineEvents.push({ agentId, type, label, agentType, time: new Date() });
  if (timelineEvents.length > 200) timelineEvents.splice(0, 50);
  if (document.getElementById('section-timeline').classList.contains('active')) renderTimeline();
}

function loadTimeline() { renderTimeline(); }

function renderTimeline() {
  const el = document.getElementById('timeline-container');
  if (timelineEvents.length === 0) { el.innerHTML = '<span class="text-muted">Noch keine Agent-Aktivität in dieser Session</span>'; return; }

  const byAgent = {};
  for (const ev of timelineEvents) {
    if (!byAgent[ev.agentId]) byAgent[ev.agentId] = { type: ev.agentType, events: [] };
    byAgent[ev.agentId].events.push(ev);
  }

  let html = '';
  for (const [agentId, info] of Object.entries(byAgent)) {
    const shortId = agentId.slice(-8);
    const lastEvent = info.events[info.events.length - 1];
    const statusCls = lastEvent.type === 'done' ? 'tl-done' : lastEvent.type === 'error' ? 'tl-error' : 'tl-active';
    html += `<div class="tl-agent ${statusCls}">`;
    html += `<div class="tl-agent-header">${agentBadge(info.type)} <span class="text-muted">${shortId}</span></div>`;
    html += `<div class="tl-steps">`;
    for (const ev of info.events) {
      const icon = ev.type === 'spawned' ? 'var(--blue)' : ev.type === 'done' ? 'var(--green)' : ev.type === 'error' ? 'var(--red)' : 'var(--amber)';
      html += `<div class="tl-step"><div class="tl-dot" style="background:${icon}"></div><span>${esc(ev.label)}</span><span class="activity-time">${relTime(ev.time)}</span></div>`;
    }
    html += `</div></div>`;
  }
  el.innerHTML = html;
}

// ── Memory ──────────────────────────────────────────────────────────
let _memoryData = [];

async function loadMemory() {
  try {
    const data = await api('/memory');
    _memoryData = data.memories || [];
    renderMemory(_memoryData);
  } catch (e) { console.error('Memory load error:', e); }
}

function filterMemory() {
  const q = document.getElementById('memory-search').value.toLowerCase();
  const filtered = q ? _memoryData.filter(m =>
    (m.value || '').toLowerCase().includes(q) ||
    (m.category || '').toLowerCase().includes(q) ||
    (m.key || '').toLowerCase().includes(q) ||
    (m.layer || '').toLowerCase().includes(q)
  ) : _memoryData;
  renderMemory(filtered);
}

function renderMemory(memories) {
  const el = document.getElementById('memory-list');
  if (memories.length === 0) { el.innerHTML = '<span class="text-muted">Keine Einträge</span>'; return; }

  const layerLabels = { user: 'User', self: 'Self', relationship: 'Relationship' };
  const byLayer = {};
  for (const m of memories) {
    const layer = m.layer || 'user';
    if (!byLayer[layer]) byLayer[layer] = {};
    const cat = m.category || 'general';
    if (!byLayer[layer][cat]) byLayer[layer][cat] = [];
    byLayer[layer][cat].push(m);
  }

  let html = '';
  for (const [layer, cats] of Object.entries(byLayer)) {
    const total = Object.values(cats).reduce((a, b) => a + b.length, 0);
    html += `<div class="memory-group"><h3>${esc(layerLabels[layer] || layer)} <span class="text-muted">(${total})</span></h3>`;
    for (const [cat, items] of Object.entries(cats)) {
      html += `<div style="margin-left:12px;margin-bottom:8px"><h4 style="font-size:12px;color:var(--text-muted);margin-bottom:4px">${esc(cat)}</h4>`;
      for (const m of items) {
        const keyStr = m.key ? `<strong>${esc(m.key)}:</strong> ` : '';
        html += `<div class="memory-item"><div class="memory-content">${keyStr}${esc(m.value)}</div><div class="memory-meta"><span class="text-muted">${esc(m.source || '')}</span><button class="btn btn-sm btn-danger" onclick="deleteMemory(${m.id})">×</button></div></div>`;
      }
      html += `</div>`;
    }
    html += `</div>`;
  }
  el.innerHTML = html;
}

async function addMemory() {
  const layer = document.getElementById('memory-new-layer').value;
  const category = document.getElementById('memory-new-category').value.trim();
  const key = document.getElementById('memory-new-key').value.trim();
  const value = document.getElementById('memory-new-value').value.trim();
  if (!value) { alert('Bitte einen Wert eingeben'); return; }
  try {
    await api('/memory', { method: 'POST', body: JSON.stringify({ layer, category: category || 'general', key, value }) });
    document.getElementById('memory-new-category').value = '';
    document.getElementById('memory-new-key').value = '';
    document.getElementById('memory-new-value').value = '';
    loadMemory();
  } catch (e) { console.error('Add memory error:', e); }
}

async function deleteMemory(id) {
  if (!confirm('Memory löschen?')) return;
  try {
    await api('/memory/' + id, { method: 'DELETE' });
    loadMemory();
  } catch (e) { console.error('Delete memory error:', e); }
}

// ── Reminders ───────────────────────────────────────────────────────

async function loadReminders() {
  try {
    const data = await api('/reminders');
    const reminders = data.reminders || [];
    const el = document.getElementById('reminders-list');
    if (reminders.length === 0) { el.innerHTML = '<span class="text-muted">Keine Erinnerungen</span>'; return; }

    el.innerHTML = reminders.map(r => {
      // due_at is local time string from DB, compare as strings
      const dueStr = r.due_at || '';
      const due = new Date(dueStr.replace(' ', 'T'));
      const now = new Date();
      const isPast = due < now;
      const statusColor = r.delivered ? 'var(--green)' : isPast ? 'var(--red)' : 'var(--amber)';
      const statusText = r.delivered ? 'Zugestellt' : isPast ? 'Überfällig' : 'Ausstehend';
      return `<div class="activity-item" style="border-left:3px solid ${statusColor};padding-left:12px;margin-bottom:8px">
        <div style="flex:1">
          <div><strong>${esc(r.text)}</strong></div>
          <div class="text-muted" style="font-size:11px">Fällig: ${due.toLocaleString('de-DE')} — ${statusText}</div>
        </div>
        <button class="btn btn-sm btn-danger" onclick="deleteReminder(${r.id})">×</button>
      </div>`;
    }).join('');
  } catch (e) { console.error('Reminders error:', e); }
}

async function addReminder() {
  const text = document.getElementById('reminder-new-text').value.trim();
  const dueInput = document.getElementById('reminder-new-due').value;
  if (!text || !dueInput) { alert('Text und Datum sind Pflicht'); return; }
  // Send local time as-is (backend uses local datetime.now() for comparison)
  const due_at = dueInput.replace('T', ' ') + ':00';
  try {
    await api('/reminders', { method: 'POST', body: JSON.stringify({ text, due_at }) });
    document.getElementById('reminder-new-text').value = '';
    document.getElementById('reminder-new-due').value = '';
    loadReminders();
  } catch (e) { console.error('Add reminder error:', e); }
}

async function deleteReminder(id) {
  if (!confirm('Erinnerung löschen?')) return;
  try {
    await api('/reminders/' + id, { method: 'DELETE' });
    loadReminders();
  } catch (e) { console.error('Delete reminder error:', e); }
}

// ── Tool Log ────────────────────────────────────────────────────────
let toolLogOffset = 0;
const TOOLLOG_LIMIT = 50;
let _toolLogTimer = null;

function debouncedLoadToolLog() {
  clearTimeout(_toolLogTimer);
  _toolLogTimer = setTimeout(() => { toolLogOffset = 0; loadToolLog(); }, 300);
}

async function loadToolLog() {
  try {
    const agent = document.getElementById('toollog-filter-agent').value.trim();
    const tool = document.getElementById('toollog-filter-tool').value.trim();
    const success = document.getElementById('toollog-filter-success').value;
    const params = new URLSearchParams({ limit: TOOLLOG_LIMIT, offset: toolLogOffset });
    if (agent) params.set('agent_id', agent);
    if (tool) params.set('tool', tool);
    if (success !== '') params.set('success', success);

    const data = await api('/tool-log?' + params);
    const tbody = document.getElementById('toollog-table');
    const logs = data.logs || [];
    if (logs.length > 0) {
      tbody.innerHTML = logs.map(l => {
        const ok = l.success ? '<span style="color:var(--green)">OK</span>' : '<span style="color:var(--red)">Err</span>';
        return `<tr class="expandable" onclick="toggleToolLogRow(this,${l.id})">
          <td>#${l.id}</td><td class="text-muted" style="font-size:11px">${esc(l.agent_id.slice(-8))}</td>
          <td><strong>${esc(l.tool)}</strong></td>
          <td class="text-muted" style="font-size:11px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc((l.input||'').slice(0,80))}</td>
          <td class="text-muted" style="font-size:11px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc((l.output||'').slice(0,80))}</td>
          <td>${ok}</td><td class="text-muted" style="font-size:11px">${relTime(l.time)}</td>
        </tr>`;
      }).join('');
    } else {
      tbody.innerHTML = '<tr><td colspan="7" class="text-muted" style="text-align:center;padding:24px">Keine Logs</td></tr>';
    }

    const pag = document.getElementById('toollog-pagination');
    if (data.total > TOOLLOG_LIMIT) {
      const hasMore = toolLogOffset + TOOLLOG_LIMIT < data.total;
      const hasPrev = toolLogOffset > 0;
      pag.innerHTML = `${hasPrev ? '<button class="btn btn-sm" onclick="toolLogOffset-=' + TOOLLOG_LIMIT + ';loadToolLog()">← Zurück</button>' : ''}
        <span class="text-muted" style="font-size:12px">${toolLogOffset + 1}–${Math.min(toolLogOffset + TOOLLOG_LIMIT, data.total)} von ${data.total}</span>
        ${hasMore ? '<button class="btn btn-sm" onclick="toolLogOffset+=' + TOOLLOG_LIMIT + ';loadToolLog()">Weiter →</button>' : ''}`;
    } else { pag.innerHTML = ''; }
  } catch (e) { console.error('Tool log error:', e); }
}

function toggleToolLogRow(tr, logId) {
  const existing = tr.nextElementSibling;
  if (existing && existing.classList.contains('toollog-expanded-row')) { existing.remove(); return; }
  document.querySelectorAll('.toollog-expanded-row').forEach(r => r.remove());
  // Find log data from table cell content - re-fetch not needed, show full row content
  const cells = tr.querySelectorAll('td');
  const expanded = document.createElement('tr');
  expanded.className = 'toollog-expanded-row';
  expanded.innerHTML = `<td colspan="7"><div class="task-expanded">
    <div class="meta"><strong>Input:</strong></div><pre>${cells[3].textContent}</pre>
    <div class="meta"><strong>Output:</strong></div><pre>${cells[4].textContent}</pre>
  </div></td>`;
  tr.after(expanded);
}

// ── Obsidian ────────────────────────────────────────────────────────
async function loadObsidian() {
  try {
    const data = await api('/obsidian/recent?limit=30');
    const el = document.getElementById('obsidian-list');
    const notes = data.notes || [];
    if (notes.length === 0) { el.innerHTML = '<span class="text-muted">Keine Notizen gefunden</span>'; return; }

    el.innerHTML = notes.map(n => {
      const name = n.path.split('/').pop().replace('.md', '');
      const folder = n.path.includes('/') ? n.path.split('/').slice(0, -1).join('/') : '';
      return `<div class="obsidian-item" onclick="openNote('${esc(n.path.replace(/'/g, "\\'"))}')">
        <div class="obsidian-name">${esc(name)}</div>
        ${folder ? '<div class="text-muted" style="font-size:10px">' + esc(folder) + '</div>' : ''}
        <div class="text-muted" style="font-size:10px">${relTime(new Date(n.modified * 1000).toISOString())}</div>
      </div>`;
    }).join('');
  } catch (e) { console.error('Obsidian error:', e); }
}

async function openNote(path) {
  try {
    const data = await api('/obsidian/note?path=' + encodeURIComponent(path));
    if (data.error) { document.getElementById('obsidian-note-content').innerHTML = `<span class="text-muted">${esc(data.error)}</span>`; return; }
    const name = path.split('/').pop().replace('.md', '');
    document.getElementById('obsidian-note-title').textContent = name;
    document.getElementById('obsidian-note-content').innerHTML = `<pre class="obsidian-pre">${esc(data.content)}</pre>`;
  } catch (e) { console.error('Note load error:', e); }
}

// ── Health ───────────────────────────────────────────────────────────
async function loadHealth() {
  // Auto-refresh Systemmetriken alle 5 Sekunden wenn Sektion aktiv
  if (!window._healthMetricsInterval) {
    window._healthMetricsInterval = setInterval(() => {
      if (document.getElementById('section-health')?.classList.contains('active')) {
        loadHealthMetrics();
      }
    }, 5000);
  }
  try {
    const data = await api('/health');

    // Stats row
    const uptime = data.uptime_seconds || 0;
    const hours = Math.floor(uptime / 3600);
    const mins = Math.floor((uptime % 3600) / 60);
    document.getElementById('health-stats').innerHTML = `
      <div class="stat-card"><div class="stat-label">Uptime</div><div class="stat-value">${hours}h ${mins}m</div></div>
      <div class="stat-card"><div class="stat-label">Ollama</div><div class="stat-value" style="color:${data.ollama.status === 'online' ? 'var(--green)' : 'var(--red)'}">${data.ollama.status}</div></div>
      <div class="stat-card"><div class="stat-label">DB Einträge</div><div class="stat-value">${Object.values(data.db_stats || {}).reduce((a,b) => a + Math.max(0,b), 0)}</div></div>
      <div class="stat-card"><div class="stat-label">Budget Rest</div><div class="stat-value">${data.budget.remaining != null ? data.budget.remaining : '—'}</div></div>
    `;

    // Ollama models
    const models = data.ollama.models || [];
    document.getElementById('health-ollama').innerHTML = models.length > 0
      ? models.map(m => `<div class="activity-item"><div class="activity-icon" style="background:var(--green)"></div><span><strong>${esc(m.name)}</strong></span><span class="activity-time">${(m.size / 1e9).toFixed(1)} GB</span></div>`).join('')
      : '<span class="text-muted">Keine Modelle geladen</span>';

    // DB stats
    const dbStats = data.db_stats || {};
    document.getElementById('health-db').innerHTML = Object.entries(dbStats).map(([table, count]) =>
      `<div class="activity-item"><span>${esc(table)}</span><span class="activity-time">${count >= 0 ? count : 'err'}</span></div>`
    ).join('');

    // LLM Routing
    try {
      const routing = await api('/llm-routing');
      const r = routing.routing || {};
      const providers = routing.providers || [];
      document.getElementById('health-routing').innerHTML = Object.entries(r).map(([task, provider]) =>
        `<div class="config-row" style="margin-bottom:6px"><label>${esc(task)}</label><select data-route="${esc(task)}" onchange="updateRouting('${esc(task)}', this.value)">
          ${providers.map(p => `<option value="${p}"${p === provider ? ' selected' : ''}>${p}</option>`).join('')}
        </select></div>`
      ).join('') + '<div class="config-actions"><span class="text-muted" style="font-size:11px">Änderungen werden sofort gespeichert</span></div>';
    } catch (_) { document.getElementById('health-routing').innerHTML = '<span class="text-muted">Nicht verfügbar</span>'; }

    // Budget
    const b = data.budget || {};
    if (b.budget) {
      const pct = Math.round((b.used / b.budget) * 100);
      document.getElementById('health-budget').innerHTML = `
        <div style="margin-bottom:8px"><span class="text-muted">Verbraucht:</span> ${b.used} / ${b.budget} (${pct}%)</div>
        <div class="progress-bar"><div class="progress-fill" style="width:${pct}%;background:${pct > 80 ? 'var(--red)' : 'var(--green)'}"></div></div>
      `;
    } else {
      document.getElementById('health-budget').innerHTML = '<span class="text-muted">Kein Budget konfiguriert</span>';
    }
  } catch (e) { console.error('Health error:', e); }
  loadHealthMetrics();
}

function renderMetricBar(pct, color) {
  const c = color || (pct > 80 ? 'var(--red)' : pct > 60 ? '#f0a500' : 'var(--green)');
  return `<div style="width:80px;height:6px;background:var(--border);border-radius:3px;display:inline-block;vertical-align:middle;margin-left:4px">
    <div style="width:${Math.min(pct,100)}%;height:100%;background:${c};border-radius:3px"></div>
  </div>`;
}

async function loadHealthMetrics() {
  const el = document.getElementById('health-system-metrics');
  if (!el) return;
  try {
    const m = await api('/system/metrics');
    const fmt = (v, unit) => v != null ? `${v}${unit}` : '—';
    const tempColor = m.cpu_temp_c == null ? 'var(--text-muted)'
      : m.cpu_temp_c >= 85 ? 'var(--red)'
      : m.cpu_temp_c >= 70 ? '#f0a500'
      : 'var(--green)';
    el.innerHTML = `
      <div style="display:flex;align-items:center;gap:6px;font-size:13px">
        <span class="text-muted">CPU</span>
        <strong>${fmt(m.cpu_percent, '%')}</strong>
        ${m.cpu_percent != null ? renderMetricBar(m.cpu_percent) : ''}
      </div>
      <div style="display:flex;align-items:center;gap:6px;font-size:13px">
        <span class="text-muted">RAM</span>
        <strong>${m.ram_used_gb != null ? `${m.ram_used_gb}/${m.ram_total_gb} GB (${m.ram_percent}%)` : '—'}</strong>
        ${m.ram_percent != null ? renderMetricBar(m.ram_percent) : ''}
      </div>
      <div style="display:flex;align-items:center;gap:6px;font-size:13px">
        <span class="text-muted">Temp</span>
        <strong style="color:${tempColor}">${fmt(m.cpu_temp_c, '°C')}</strong>
      </div>
      <div style="display:flex;align-items:center;gap:6px;font-size:13px">
        <span class="text-muted">Watts</span>
        <strong>${fmt(m.cpu_watts, ' W')}</strong>
      </div>
      <div style="display:flex;align-items:center;gap:6px;font-size:13px">
        <span class="text-muted">GPU</span>
        <strong>${fmt(m.gpu_percent, '%')}</strong>
        ${m.gpu_percent != null ? renderMetricBar(m.gpu_percent) : ''}
      </div>
    `;
  } catch {
    el.innerHTML = '<span class="text-muted" style="font-size:12px">Metriken nicht verfügbar</span>';
  }
}

async function updateRouting(task, provider) {
  try { await api('/llm-routing', { method: 'PUT', body: JSON.stringify({ routing: { [task]: provider } }) }); } catch (e) { console.error('Routing update error:', e); }
}

// ── Files ────────────────────────────────────────────────────────────
let _currentFilePath = '';

async function loadFiles(path) {
  _currentFilePath = path;
  try {
    const data = await api('/files?path=' + encodeURIComponent(path));
    if (data.error) { document.getElementById('file-list').innerHTML = `<span class="text-muted">${esc(data.error)}</span>`; return; }

    // Breadcrumb
    const parts = path ? path.split('/') : [];
    let bc = '<a class="file-crumb" onclick="loadFiles(\'\')">workspace</a>';
    let accumulated = '';
    for (const part of parts) {
      accumulated += (accumulated ? '/' : '') + part;
      const p = accumulated;
      bc += ` / <a class="file-crumb" onclick="loadFiles('${esc(p)}')">${esc(part)}</a>`;
    }
    document.getElementById('file-breadcrumb').innerHTML = bc;

    // File list
    const items = data.items || [];
    const el = document.getElementById('file-list');
    if (items.length === 0) { el.innerHTML = '<span class="text-muted">Leer</span>'; return; }

    el.innerHTML = items.map(f => {
      const icon = f.is_dir ? 'file-icon-dir' : 'file-icon-file';
      const size = f.is_dir ? '' : formatSize(f.size);
      if (f.is_dir) {
        return `<div class="file-item" onclick="loadFiles('${esc(f.path)}')"><span class="${icon}"></span><span style="flex:1">${esc(f.name)}</span><span class="activity-time">${size}</span></div>`;
      } else {
        return `<div class="file-item"><span class="${icon}" onclick="openFile('${esc(f.path)}')"></span><span style="flex:1;cursor:pointer" onclick="openFile('${esc(f.path)}')">${esc(f.name)}</span><button class="btn btn-sm" onclick="event.stopPropagation();shareFileInChat('${esc(f.path)}')" title="Im Chat teilen" style="padding:2px 6px;font-size:11px">Teilen</button><span class="activity-time">${size}</span></div>`;
      }
    }).join('');
  } catch (e) { console.error('Files error:', e); }
}

async function openFile(path) {
  try {
    const data = await api('/files/read?path=' + encodeURIComponent(path));
    if (data.error) { document.getElementById('file-viewer-content').textContent = data.error; return; }
    const name = path.split('/').pop();
    document.getElementById('file-viewer-title').textContent = name;
    document.getElementById('file-viewer-content').textContent = data.content;
  } catch (e) { console.error('File read error:', e); }
}

function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1048576).toFixed(1) + ' MB';
}

// ── Kanban ───────────────────────────────────────────────────────────
let kanbanView = false;

function toggleTaskView() {
  kanbanView = !kanbanView;
  const btn = document.getElementById('tasks-view-toggle');
  const kanban = document.getElementById('tasks-kanban');
  const table = kanban.nextElementSibling; // the .card div
  if (kanbanView) {
    btn.textContent = 'Tabelle';
    kanban.style.display = 'grid';
    table.style.display = 'none';
    loadKanban();
  } else {
    btn.textContent = 'Kanban';
    kanban.style.display = 'none';
    table.style.display = '';
    loadTasks();
  }
}

async function loadKanban() {
  try {
    const statuses = ['open', 'in_progress', 'done', 'failed'];
    for (const s of statuses) {
      const data = await api('/tasks?status=' + s + '&limit=50');
      const el = document.getElementById('kanban-' + s);
      const tasks = data.tasks || [];
      el.innerHTML = tasks.map(t =>
        `<div class="kanban-card" draggable="true" data-task-id="${t.id}" ondragstart="dragTask(event,${t.id})">
          <div class="kanban-card-title">#${t.id} ${esc(t.title)}</div>
          <div class="kanban-card-meta">${agentBadge(t.agent)} ${relTime(t.created_at)}</div>
        </div>`
      ).join('') || '<span class="text-muted" style="padding:8px;display:block">Keine</span>';
    }
    // Drop zones
    document.querySelectorAll('.kanban-cards').forEach(zone => {
      zone.ondragover = e => { e.preventDefault(); zone.classList.add('kanban-dragover'); };
      zone.ondragleave = () => zone.classList.remove('kanban-dragover');
      zone.ondrop = e => {
        e.preventDefault();
        zone.classList.remove('kanban-dragover');
        const taskId = e.dataTransfer.getData('text/plain');
        const newStatus = zone.id.replace('kanban-', '');
        dropTask(taskId, newStatus);
      };
    });
  } catch (e) { console.error('Kanban error:', e); }
}

function dragTask(e, taskId) {
  e.dataTransfer.setData('text/plain', taskId);
}

async function dropTask(taskId, newStatus) {
  try {
    await api('/tasks/' + taskId, { method: 'PATCH', body: JSON.stringify({ status: newStatus }) });
    loadKanban();
  } catch (e) { console.error('Drop task error:', e); }
}

// ── Command Palette (Ctrl+K) ────────────────────────────────────────
const COMMANDS = [
  { name: 'Neuer Task', action: () => openModal('modal-task'), section: 'tasks' },
  { name: 'Neuer Schedule', action: () => openScheduleModal(), section: 'schedules' },
  { name: 'KI-Schedule erstellen', action: () => openModal('modal-ai-schedule'), section: 'schedules' },
  { name: 'Dashboard', action: () => navTo('dashboard'), section: 'dashboard' },
  { name: 'Tasks', action: () => navTo('tasks'), section: 'tasks' },
  { name: 'Schedules', action: () => navTo('schedules'), section: 'schedules' },
  { name: 'Chat', action: () => navTo('chat'), section: 'chat' },
  { name: 'Timeline', action: () => navTo('timeline'), section: 'timeline' },
  { name: 'Memory', action: () => navTo('memory'), section: 'memory' },
  { name: 'Erinnerungen', action: () => navTo('reminders'), section: 'reminders' },
  { name: 'Tool Log', action: () => navTo('toollog'), section: 'toollog' },
  { name: 'Obsidian', action: () => navTo('obsidian'), section: 'obsidian' },
  { name: 'System Health', action: () => navTo('health'), section: 'health' },
  { name: 'Dateien', action: () => navTo('files'), section: 'files' },
  { name: 'Konfiguration', action: () => navTo('config'), section: 'config' },
  { name: 'Büro öffnen', action: () => window.open('/office', '_blank'), section: '' },
];

function navTo(section) {
  const btn = document.querySelector(`.sidebar-btn[data-section="${section}"]`);
  if (btn) btn.click();
}

document.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault();
    openModal('modal-command');
    setTimeout(() => document.getElementById('cmd-input').focus(), 50);
    filterCommands();
  }
  if (e.key === 'Escape') {
    closeModal('modal-command');
  }
});

function filterCommands() {
  const q = document.getElementById('cmd-input').value.toLowerCase();
  const filtered = q ? COMMANDS.filter(c => c.name.toLowerCase().includes(q)) : COMMANDS;
  const el = document.getElementById('cmd-list');
  el.innerHTML = filtered.map((c, i) =>
    `<div class="cmd-item${i === 0 ? ' cmd-active' : ''}" onclick="runCommand(${COMMANDS.indexOf(c)})">${esc(c.name)}</div>`
  ).join('');
}

function runCommand(idx) {
  closeModal('modal-command');
  document.getElementById('cmd-input').value = '';
  COMMANDS[idx].action();
}

// ── File Picker ─────────────────────────────────────────────────────
let _fpTargetKey = null;
let _fpCurrentPath = '';
let _fpWorkspace = '';

function openFilePicker(configKey) {
  _fpTargetKey = configKey;
  document.getElementById('file-picker-overlay').style.display = 'flex';
  document.getElementById('fp-selected-path').value = '';
  loadFilePicker('');
}

function closeFilePicker() {
  document.getElementById('file-picker-overlay').style.display = 'none';
  _fpTargetKey = null;
}

async function loadFilePicker(path) {
  _fpCurrentPath = path;
  try {
    const data = await api('/files?path=' + encodeURIComponent(path));
    if (data.error) { document.getElementById('fp-list').innerHTML = `<span class="text-muted">${esc(data.error)}</span>`; return; }
    _fpWorkspace = data.workspace || '';

    // Breadcrumb
    const parts = path ? path.split('/') : [];
    let bc = `<a class="file-crumb" onclick="loadFilePicker('')">workspace</a>`;
    let accumulated = '';
    for (const part of parts) {
      accumulated += (accumulated ? '/' : '') + part;
      const p = accumulated;
      bc += ` / <a class="file-crumb" onclick="loadFilePicker('${esc(p)}')">${esc(part)}</a>`;
    }
    document.getElementById('fp-breadcrumb').innerHTML = bc;

    // Update selected path to current directory
    const fullPath = _fpWorkspace + (path ? '/' + path : '');
    document.getElementById('fp-selected-path').value = fullPath;

    // Items
    const items = data.items || [];
    const el = document.getElementById('fp-list');
    if (items.length === 0) { el.innerHTML = '<span class="text-muted">Leer</span>'; return; }

    el.innerHTML = items.map(f => {
      const icon = f.is_dir ? 'file-icon-dir' : 'file-icon-file';
      if (f.is_dir) {
        return `<div class="file-item" onclick="loadFilePicker('${esc(f.path)}')" ondblclick="selectPickerPath('${esc(f.path)}', true)"><span class="${icon}"></span><span>${esc(f.name)}</span></div>`;
      } else {
        return `<div class="file-item" onclick="selectPickerPath('${esc(f.path)}', false)"><span class="${icon}"></span><span>${esc(f.name)}</span></div>`;
      }
    }).join('');
  } catch (e) { console.error('File picker error:', e); }
}

function selectPickerPath(relPath, isDir) {
  const fullPath = _fpWorkspace + '/' + relPath;
  document.getElementById('fp-selected-path').value = fullPath;
  if (isDir) loadFilePicker(relPath);
}

function confirmFilePicker() {
  const selected = document.getElementById('fp-selected-path').value;
  if (!selected) { closeFilePicker(); return; }
  if (_fpTargetKey === '__chat__') {
    closeFilePicker();
    shareFileInChat(selected);
    return;
  }
  if (_fpTargetKey) {
    const input = document.querySelector(`[data-key="${_fpTargetKey}"]`);
    if (input) input.value = selected;
  }
  closeFilePicker();
}

function openChatFilePicker() {
  _fpTargetKey = '__chat__';
  document.getElementById('file-picker-overlay').style.display = 'flex';
  document.getElementById('fp-selected-path').value = '';
  loadFilePicker('');
}

// ── Ollama Model Browser ──────────────────────────────────────────────

async function loadOllamaModels() {
  try {
    const data = await api('/ollama/models');
    return data.models || [];
  } catch {
    return [];
  }
}

function renderOllamaModal(models) {
  const rows = models.map(m => `
    <tr>
      <td><code>${esc(m.name)}</code></td>
      <td>${m.size_gb} GB</td>
      <td>${m.modified_at ? new Date(m.modified_at).toLocaleDateString('de') : '—'}</td>
      <td><button class="btn-danger btn-sm" data-model="${esc(m.name)}" onclick="deleteOllamaModel(this.getAttribute('data-model'))">🗑</button></td>
    </tr>`).join('');
  return `
  <div id="ollama-modal" class="modal-overlay" onclick="if(event.target===this)closeOllamaModal()">
    <div class="modal-box">
      <h3>Modell-Manager</h3>
      <table class="ollama-table">
        <thead><tr><th>Modell</th><th>Größe</th><th>Datum</th><th></th></tr></thead>
        <tbody>${rows || '<tr><td colspan="4">Keine Modelle gefunden</td></tr>'}</tbody>
      </table>
      <div class="pull-row" style="margin-top:12px;display:flex;gap:8px;">
        <input id="pull-model-input" type="text" placeholder="z.B. gemma3:4b" style="flex:1">
        <button onclick="pullOllamaModel()">⬇ Pullen</button>
      </div>
      <div id="pull-progress" style="margin-top:8px;min-height:20px;font-size:0.9em;color:#666"></div>
      <button onclick="closeOllamaModal()" style="margin-top:12px">Schließen</button>
    </div>
  </div>`;
}

async function openOllamaModal() {
  const models = await loadOllamaModels();
  document.body.insertAdjacentHTML('beforeend', renderOllamaModal(models));
}

function closeOllamaModal() {
  document.getElementById('ollama-modal')?.remove();
}

async function deleteOllamaModel(name) {
  if (!confirm(`Modell "${name}" löschen?`)) return;
  const result = await api(`/ollama/models/${encodeURIComponent(name)}`, { method: 'DELETE' });
  if (result.status === 'deleted') {
    closeOllamaModal();
    await openOllamaModal();
  } else {
    alert('Fehler: ' + (result.detail || 'Unbekannt'));
  }
}

async function pullOllamaModel() {
  const input = document.getElementById('pull-model-input');
  const modelName = input?.value?.trim();
  if (!modelName) return;
  const progressEl = document.getElementById('pull-progress');
  if (progressEl) progressEl.textContent = 'Starte Download...';

  const token = localStorage.getItem('falkenstein_token') || '';
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = 'Bearer ' + token;

  try {
    const resp = await fetch('/api/admin/ollama/pull', {
      method: 'POST',
      headers,
      body: JSON.stringify({ model: modelName }),
    });
    if (!resp.body) throw new Error('Kein Response-Body');
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const text = decoder.decode(value);
      const lines = text.split('\n').filter(l => l.startsWith('data: '));
      for (const line of lines) {
        try {
          const data = JSON.parse(line.slice(6));
          if (!progressEl) continue;
          if (data.status === 'success') {
            progressEl.textContent = '✅ Download abgeschlossen';
            closeOllamaModal();
            await openOllamaModal();
          } else if (data.error) {
            progressEl.textContent = '❌ Fehler: ' + data.error;
          } else {
            const pct = data.completed && data.total
              ? Math.round(data.completed / data.total * 100) + '%'
              : data.status || '';
            progressEl.textContent = pct;
          }
        } catch {}
      }
    }
  } catch (err) {
    if (progressEl) progressEl.textContent = '❌ Verbindungsfehler: ' + err.message;
  }
}

// ── Workspace-Kontext-Anhang ──────────────────────────────────────────────

async function initWorkspaceButton() {
  const chatForm = document.getElementById('chat-form') || document.querySelector('.chat-input-row');
  if (!chatForm) return;

  const btn = document.createElement('button');
  btn.type = 'button';
  btn.id = 'workspace-btn';
  btn.title = 'Workspace anhängen';
  btn.textContent = '+';
  btn.onclick = toggleWorkspaceMenu;
  chatForm.prepend(btn);

  await refreshWorkspaceBadge();
}

async function refreshWorkspaceBadge() {
  const existing = document.getElementById('workspace-badge');
  if (existing) existing.remove();

  try {
    const token = localStorage.getItem('falkenstein_token') || '';
    const resp = await fetch('/api/workspace/current', {
      headers: token ? { 'Authorization': 'Bearer ' + token } : {},
    });
    if (!resp.ok) return;
    const data = await resp.json();
    if (!data.active) return;

    const badge = document.createElement('div');
    badge.id = 'workspace-badge';
    badge.style.cssText = 'padding:4px 8px;background:#e8f4f8;border-radius:4px;font-size:0.85em;display:flex;align-items:center;gap:8px;margin-top:4px;';
    badge.innerHTML = `📁 ${esc(data.path)} <span style="cursor:pointer;font-weight:bold;" onclick="clearWorkspace()">✕</span>`;
    const chatInput = document.getElementById('chat-input') || document.querySelector('textarea');
    if (chatInput) chatInput.parentNode.insertBefore(badge, chatInput.nextSibling);
  } catch {}
}

function toggleWorkspaceMenu() {
  const existing = document.getElementById('workspace-menu');
  if (existing) { existing.remove(); return; }

  const menu = document.createElement('div');
  menu.id = 'workspace-menu';
  menu.style.cssText = 'position:absolute;background:white;border:1px solid #ddd;border-radius:6px;padding:4px;z-index:1000;display:flex;flex-direction:column;gap:4px;min-width:200px;box-shadow:0 2px 8px rgba(0,0,0,0.15);';
  menu.innerHTML = `
    <button onclick="pickWorkspaceFile()">📄 Datei hochladen</button>
    <button onclick="pickWorkspaceFolder()">📁 Ordner hochladen</button>
    <button onclick="pickWorkspaceDirectory()">📂 Verzeichnis wählen</button>
  `;
  const btn = document.getElementById('workspace-btn');
  if (btn) btn.after(menu);
  setTimeout(() => {
    document.addEventListener('click', function closeMenu(e) {
      if (!menu.contains(e.target) && e.target.id !== 'workspace-btn') {
        menu.remove();
        document.removeEventListener('click', closeMenu);
      }
    });
  }, 10);
}

function pickWorkspaceFile() {
  document.getElementById('workspace-menu')?.remove();
  const input = document.createElement('input');
  input.type = 'file';
  input.onchange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const form = new FormData();
    form.append('file', file);
    const token = localStorage.getItem('falkenstein_token') || '';
    await fetch('/api/workspace/upload', {
      method: 'POST',
      headers: token ? { 'Authorization': 'Bearer ' + token } : {},
      body: form,
    });
    await refreshWorkspaceBadge();
  };
  input.click();
}

function pickWorkspaceFolder() {
  document.getElementById('workspace-menu')?.remove();
  const input = document.createElement('input');
  input.type = 'file';
  input.webkitdirectory = true;
  input.onchange = async (e) => {
    const files = Array.from(e.target.files);
    if (!files.length) return;
    const form = new FormData();
    form.append('file', files[0]);
    const token = localStorage.getItem('falkenstein_token') || '';
    await fetch('/api/workspace/upload', {
      method: 'POST',
      headers: token ? { 'Authorization': 'Bearer ' + token } : {},
      body: form,
    });
    await refreshWorkspaceBadge();
  };
  input.click();
}

async function pickWorkspaceDirectory() {
  document.getElementById('workspace-menu')?.remove();
  if (!window.showDirectoryPicker) {
    const path = prompt('Verzeichnis-Pfad eingeben (showDirectoryPicker nicht unterstützt):');
    if (path) await setWorkspacePath(path);
    return;
  }
  try {
    const dirHandle = await window.showDirectoryPicker();
    await setWorkspacePath(dirHandle.name);
  } catch (e) {
    if (e.name !== 'AbortError') console.error(e);
  }
}

async function setWorkspacePath(path) {
  const token = localStorage.getItem('falkenstein_token') || '';
  await fetch('/api/workspace/path', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(token ? { 'Authorization': 'Bearer ' + token } : {}) },
    body: JSON.stringify({ path }),
  });
  await refreshWorkspaceBadge();
}

async function clearWorkspace() {
  const token = localStorage.getItem('falkenstein_token') || '';
  await fetch('/api/workspace/current', {
    method: 'DELETE',
    headers: token ? { 'Authorization': 'Bearer ' + token } : {},
  });
  document.getElementById('workspace-badge')?.remove();
}

// Init
loadDashboard();
connectWS();
initWorkspaceButton();
