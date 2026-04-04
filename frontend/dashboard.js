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
  const res = await fetch(API + path, { headers: { 'Content-Type': 'application/json' }, ...opts });
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

// Modals
function openModal(id) { document.getElementById(id).classList.add('open'); }
function closeModal(id) { document.getElementById(id).classList.remove('open'); }
function closeModalOverlay(e) { if (e.target === e.currentTarget) e.target.classList.remove('open'); }

// WebSocket
function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(proto + '//' + location.host + '/ws');
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
      if (type === 'agent_progress') {
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

// Init
loadDashboard();
connectWS();
