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
        const nextRun = s.next_run ? relTime(s.next_run) : '—';
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
  'LLM': ['ollama_host','ollama_model','ollama_model_light','ollama_model_heavy','ollama_num_ctx','ollama_num_ctx_extended','llm_max_retries','llm_provider_classify','llm_provider_action','llm_provider_content','llm_provider_scheduled','cli_provider','cli_daily_token_budget'],
  'Pfade': ['obsidian_vault_path','workspace_path'],
  'Persönlichkeit': ['soul_prompt'],
  'API Keys': ['brave_api_key'],
  'Allgemein': ['obsidian_enabled','obsidian_auto_knowledge'],
};
const TEXTAREA_KEYS = new Set(['soul_prompt']);
const PASSWORD_KEYS = new Set(['brave_api_key']);

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
        if (TEXTAREA_KEYS.has(key)) html += `<textarea data-key="${esc(key)}" rows="4">${esc(val)}</textarea>`;
        else if (PASSWORD_KEYS.has(key)) html += `<input type="password" data-key="${esc(key)}" value="${esc(val)}">`;
        else html += `<input type="text" data-key="${esc(key)}" value="${esc(val)}">`;
        html += `</div>`;
      });
      html += `<div class="config-actions"><button class="btn btn-primary btn-sm" onclick="saveConfigGroup(this)">Speichern</button></div></div>`;
    }
    container.innerHTML = html || '<p class="text-muted">Keine Konfiguration</p>';
  } catch (e) { console.error('Config load error:', e); }
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
    document.getElementById('siri-token').textContent = data.api_token || '(kein Token konfiguriert)';
    document.getElementById('siri-url').textContent = data.server_url || 'http://localhost:8800';
    document.getElementById('siri-telegram-url').textContent = data.telegram_api_url || '';
    const body = { chat_id: data.telegram_chat_id, text: '[Diktierter Text]' };
    document.getElementById('siri-telegram-body').textContent = JSON.stringify(body, null, 2);
    const apiExample = `URL: ${data.server_url}/api/admin/tasks/submit\nMethode: POST\nHeader:\n  Content-Type: application/json\n  Authorization: Bearer ${data.api_token || 'DEIN_TOKEN'}\nBody:\n  {"text": "[Diktierter Text]"}`;
    document.getElementById('siri-api-example').textContent = apiExample;
  } catch (e) { console.error('Siri load error:', e); }
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
    } catch (_) {}
  };
}

// ── Chat ────────────────────────────────────────────────────────────
let chatLoaded = false;

async function loadChat() {
  if (chatLoaded) return;
  chatLoaded = true;
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
  return `<div class="chat-msg ${cls}"><div class="chat-msg-header"><strong>${label}</strong><span class="activity-time">${relTime(time)}</span></div><div class="chat-msg-body">${esc(content)}</div></div>`;
}

async function sendChat() {
  const input = document.getElementById('chat-input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';

  const el = document.getElementById('chat-messages');
  const emptyMsg = el.querySelector('.chat-empty');
  if (emptyMsg) emptyMsg.remove();
  el.innerHTML += chatBubble('user', text, new Date().toISOString());
  el.scrollTop = el.scrollHeight;

  try {
    await api('/tasks/submit', { method: 'POST', body: JSON.stringify({ text }) });
    el.innerHTML += chatBubble('assistant', 'Wird bearbeitet...', new Date().toISOString());
    el.scrollTop = el.scrollHeight;
  } catch (e) { console.error('Chat send error:', e); }
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
    _memoryData = data.facts || [];
    renderMemory(_memoryData);
  } catch (e) { console.error('Memory load error:', e); }
}

function filterMemory() {
  const q = document.getElementById('memory-search').value.toLowerCase();
  const filtered = q ? _memoryData.filter(f => f.content.toLowerCase().includes(q) || f.category.toLowerCase().includes(q)) : _memoryData;
  renderMemory(filtered);
}

function renderMemory(facts) {
  const el = document.getElementById('memory-list');
  if (facts.length === 0) { el.innerHTML = '<span class="text-muted">Keine Einträge</span>'; return; }

  const byCategory = {};
  for (const f of facts) {
    const cat = f.category || 'Allgemein';
    if (!byCategory[cat]) byCategory[cat] = [];
    byCategory[cat].push(f);
  }

  let html = '';
  for (const [cat, items] of Object.entries(byCategory)) {
    html += `<div class="memory-group"><h3>${esc(cat)} <span class="text-muted">(${items.length})</span></h3>`;
    for (const f of items) {
      html += `<div class="memory-item"><div class="memory-content">${esc(f.content)}</div><div class="memory-meta"><span class="text-muted">${esc(f.source || '')}</span><button class="btn btn-sm btn-danger" onclick="deleteMemory(${f.id})">×</button></div></div>`;
    }
    html += `</div>`;
  }
  el.innerHTML = html;
}

async function deleteMemory(id) {
  if (!confirm('Memory löschen?')) return;
  try {
    await api('/memory/' + id, { method: 'DELETE' });
    loadMemory();
  } catch (e) { console.error('Delete memory error:', e); }
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
        return `<div class="file-item" onclick="loadFiles('${esc(f.path)}')"><span class="${icon}"></span><span>${esc(f.name)}</span><span class="activity-time">${size}</span></div>`;
      } else {
        return `<div class="file-item" onclick="openFile('${esc(f.path)}')"><span class="${icon}"></span><span>${esc(f.name)}</span><span class="activity-time">${size}</span></div>`;
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

// Init
loadDashboard();
connectWS();
