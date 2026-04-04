// ── Falki Dashboard JS ──────────────────────────────────────────────
'use strict';

const API = '/api/admin';
let ws = null;

// ── Helpers ─────────────────────────────────────────────────────────

function esc(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

function badgeClass(status) {
  const map = {
    active: 'badge-active', inactive: 'badge-inactive',
    open: 'badge-open', done: 'badge-done',
    in_progress: 'badge-in_progress', error: 'badge-error',
  };
  return map[status] || 'badge-open';
}

function badge(status) {
  return `<span class="badge ${badgeClass(status)}">${esc(status)}</span>`;
}

async function api(path, opts = {}) {
  const res = await fetch(API + path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  return res.json();
}

// ── Tabs ────────────────────────────────────────────────────────────

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(btn.dataset.tab).classList.add('active');

    // Load data for active tab
    const tab = btn.dataset.tab;
    if (tab === 'tab-dashboard') loadDashboard();
    else if (tab === 'tab-tasks') loadTasks();
    else if (tab === 'tab-schedules') loadSchedules();
    else if (tab === 'tab-config') loadConfig();
  });
});

// ── Dashboard Tab ───────────────────────────────────────────────────

async function loadDashboard() {
  try {
    const data = await api('/dashboard');

    document.getElementById('stat-agents').textContent = data.active_agents ? data.active_agents.length : 0;
    document.getElementById('stat-tasks').textContent = data.open_tasks_count || 0;

    if (data.budget && data.budget.budget) {
      const pct = Math.round((data.budget.remaining / data.budget.budget) * 100);
      document.getElementById('stat-budget').textContent = pct + '%';
    } else {
      document.getElementById('stat-budget').textContent = '--';
    }

    document.getElementById('stat-ollama').textContent = data.ollama_status || '--';

    // Active agents
    const agentsList = document.getElementById('agents-list');
    if (data.active_agents && data.active_agents.length > 0) {
      agentsList.innerHTML = data.active_agents.map(a => {
        const name = typeof a === 'string' ? a : (a.name || a.type || 'agent');
        const type = typeof a === 'string' ? '' : (a.type || '');
        return `<div class="agent-chip"><div class="agent-pulse"></div>${esc(name)}${type ? ' <span style="color:var(--text-muted)">(' + esc(type) + ')</span>' : ''}</div>`;
      }).join('');
    } else {
      agentsList.innerHTML = '<span class="no-agents">Keine aktiven Agents</span>';
    }

    // Recent tasks
    const tbody = document.getElementById('recent-tasks');
    if (data.recent_tasks && data.recent_tasks.length > 0) {
      tbody.innerHTML = data.recent_tasks.map(t =>
        `<tr><td>${esc(String(t.id))}</td><td>${esc(t.title)}</td><td>${badge(t.status)}</td><td>${esc(t.agent)}</td></tr>`
      ).join('');
    } else {
      tbody.innerHTML = '<tr><td colspan="4" style="color:var(--text-muted)">Keine Tasks</td></tr>';
    }
  } catch (e) {
    console.error('Dashboard load error:', e);
  }
}

// ── Tasks Tab ───────────────────────────────────────────────────────

async function loadTasks() {
  try {
    const data = await api('/tasks');
    const tbody = document.getElementById('tasks-table');

    if (data.tasks && data.tasks.length > 0) {
      tbody.innerHTML = data.tasks.map(t => {
        const created = t.created_at ? t.created_at.slice(0, 16).replace('T', ' ') : '';
        const hasResult = t.result && t.result.trim().length > 0;
        return `<tr>
          <td>${esc(String(t.id))}</td>
          <td>${esc(t.title)}</td>
          <td>${badge(t.status)}</td>
          <td>${esc(t.agent)}</td>
          <td>${esc(created)}</td>
          <td>${hasResult ? '<button class="btn btn-sm" onclick="showResult(this)" data-result="' + esc(t.result).replace(/"/g, '&quot;') + '">Ergebnis</button>' : ''}</td>
        </tr>`;
      }).join('');
    } else {
      tbody.innerHTML = '<tr><td colspan="6" style="color:var(--text-muted)">Keine Tasks</td></tr>';
    }
  } catch (e) {
    console.error('Tasks load error:', e);
  }
}

function showResult(btn) {
  const result = btn.getAttribute('data-result');
  alert(result);
}

async function submitTask() {
  const text = document.getElementById('task-text').value.trim();
  if (!text) return;
  try {
    await api('/tasks/submit', {
      method: 'POST',
      body: JSON.stringify({ text }),
    });
    document.getElementById('task-text').value = '';
    closeModal('modal-task');
    loadTasks();
    loadDashboard();
  } catch (e) {
    console.error('Submit task error:', e);
  }
}

// ── Schedules Tab ───────────────────────────────────────────────────

async function loadSchedules() {
  try {
    const data = await api('/schedules');
    const tbody = document.getElementById('schedules-table');
    const tasks = data.tasks || [];

    if (tasks.length > 0) {
      tbody.innerHTML = tasks.map(s => {
        const active = s.active === 1 || s.active === true;
        const statusBadge = active ? badge('active') : badge('inactive');
        const lastRun = s.last_run || '--';
        return `<tr>
          <td>${esc(s.name)}</td>
          <td>${esc(s.schedule || '')}</td>
          <td>${esc(s.agent_type || '')}</td>
          <td>${statusBadge}</td>
          <td>${esc(lastRun)}</td>
          <td>
            <div class="btn-group">
              <button class="btn btn-sm" onclick="toggleSchedule(${s.id})">${active ? 'Pause' : 'Aktiv'}</button>
              <button class="btn btn-sm" onclick="editSchedule(${s.id})">Edit</button>
              <button class="btn btn-sm" onclick="runSchedule(${s.id})">Run</button>
              <button class="btn btn-sm btn-danger" onclick="deleteSchedule(${s.id})">Del</button>
            </div>
          </td>
        </tr>`;
      }).join('');
    } else {
      tbody.innerHTML = '<tr><td colspan="6" style="color:var(--text-muted)">Keine Schedules</td></tr>';
    }
  } catch (e) {
    console.error('Schedules load error:', e);
  }
}

function openScheduleModal(id) {
  document.getElementById('schedule-edit-id').value = id || '';
  document.getElementById('schedule-modal-title').textContent = id ? 'Schedule bearbeiten' : 'Neuer Schedule';
  document.getElementById('sched-name').value = '';
  document.getElementById('sched-schedule').value = '';
  document.getElementById('sched-agent-type').value = 'researcher';
  document.getElementById('sched-active-hours').value = '';
  document.getElementById('sched-prompt').value = '';
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
    openModal('modal-schedule');
  } catch (e) {
    console.error('Edit schedule error:', e);
  }
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

  if (!payload.name || !payload.prompt) {
    alert('Name und Prompt sind Pflichtfelder');
    return;
  }

  try {
    if (editId) {
      await api('/schedules/' + editId, { method: 'PUT', body: JSON.stringify(payload) });
    } else {
      await api('/schedules', { method: 'POST', body: JSON.stringify(payload) });
    }
    closeModal('modal-schedule');
    loadSchedules();
  } catch (e) {
    console.error('Save schedule error:', e);
  }
}

async function toggleSchedule(id) {
  try {
    await api('/schedules/' + id + '/toggle', { method: 'POST' });
    loadSchedules();
  } catch (e) {
    console.error('Toggle error:', e);
  }
}

async function runSchedule(id) {
  try {
    const res = await api('/schedules/' + id + '/run', { method: 'POST' });
    if (res.triggered) {
      loadDashboard();
    } else if (res.error) {
      alert(res.error);
    }
  } catch (e) {
    console.error('Run error:', e);
  }
}

async function deleteSchedule(id) {
  if (!confirm('Schedule wirklich löschen?')) return;
  try {
    await api('/schedules/' + id, { method: 'DELETE' });
    loadSchedules();
  } catch (e) {
    console.error('Delete error:', e);
  }
}

async function aiCreateSchedule() {
  const desc = document.getElementById('ai-sched-desc').value.trim();
  if (!desc) return;
  try {
    const res = await api('/schedules/ai-create', {
      method: 'POST',
      body: JSON.stringify({ description: desc }),
    });
    if (res.created) {
      document.getElementById('ai-sched-desc').value = '';
      closeModal('modal-ai-schedule');
      loadSchedules();
    } else if (res.error) {
      alert(res.error);
    }
  } catch (e) {
    console.error('AI create error:', e);
  }
}

// ── Config Tab ──────────────────────────────────────────────────────

const CONFIG_CATEGORIES = {
  'LLM': ['ollama_host', 'ollama_model', 'llm_timeout'],
  'Pfade': ['obsidian_vault', 'schedule_dir'],
  'Persönlichkeit': ['soul_prompt'],
  'API Keys': ['telegram_token', 'brave_api_key', 'gemini_api_key'],
  'Allgemein': [],
};

const TEXTAREA_KEYS = new Set(['soul_prompt']);
const PASSWORD_KEYS = new Set(['telegram_token', 'brave_api_key', 'gemini_api_key']);

async function loadConfig() {
  try {
    const data = await api('/config');
    const container = document.getElementById('config-container');
    const items = data.config || [];

    // Build map
    const configMap = {};
    items.forEach(item => {
      const key = typeof item === 'string' ? item : (item.key || item.name || '');
      const value = typeof item === 'string' ? '' : (item.value || '');
      if (key) configMap[key] = value;
    });

    // Assign keys to categories
    const assigned = new Set();
    const groups = {};
    for (const [cat, keys] of Object.entries(CONFIG_CATEGORIES)) {
      groups[cat] = {};
      keys.forEach(k => {
        if (k in configMap) {
          groups[cat][k] = configMap[k];
          assigned.add(k);
        }
      });
    }
    // Remaining go to Allgemein
    for (const k of Object.keys(configMap)) {
      if (!assigned.has(k)) {
        groups['Allgemein'][k] = configMap[k];
      }
    }

    let html = '';
    for (const [cat, entries] of Object.entries(groups)) {
      const keys = Object.keys(entries);
      if (keys.length === 0) continue;

      html += `<div class="config-group" data-category="${esc(cat)}">`;
      html += `<h3>${esc(cat)}</h3>`;

      keys.forEach(key => {
        const val = entries[key];
        html += `<div class="config-row">`;
        html += `<label>${esc(key)}</label>`;
        if (TEXTAREA_KEYS.has(key)) {
          html += `<textarea data-key="${esc(key)}" rows="4">${esc(val)}</textarea>`;
        } else if (PASSWORD_KEYS.has(key)) {
          html += `<input type="password" data-key="${esc(key)}" value="${esc(val)}">`;
        } else {
          html += `<input type="text" data-key="${esc(key)}" value="${esc(val)}">`;
        }
        html += `</div>`;
      });

      html += `<div class="config-actions"><button class="btn btn-primary btn-sm" onclick="saveConfigGroup(this)">Speichern</button></div>`;
      html += `</div>`;
    }

    container.innerHTML = html || '<p style="color:var(--text-muted)">Keine Konfiguration verfügbar</p>';
  } catch (e) {
    console.error('Config load error:', e);
  }
}

async function saveConfigGroup(btn) {
  const group = btn.closest('.config-group');
  const inputs = group.querySelectorAll('[data-key]');
  const updates = {};
  inputs.forEach(el => {
    updates[el.dataset.key] = el.value;
  });

  try {
    const res = await api('/config', {
      method: 'PUT',
      body: JSON.stringify({ updates }),
    });
    if (res.saved) {
      btn.textContent = 'Gespeichert!';
      setTimeout(() => { btn.textContent = 'Speichern'; }, 1500);
    }
  } catch (e) {
    console.error('Save config error:', e);
  }
}

// ── Modals ──────────────────────────────────────────────────────────

function openModal(id) {
  document.getElementById(id).classList.add('open');
}

function closeModal(id) {
  document.getElementById(id).classList.remove('open');
}

function closeModalOverlay(e) {
  if (e.target === e.currentTarget) {
    e.target.classList.remove('open');
  }
}

// ── WebSocket ───────────────────────────────────────────────────────

function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(proto + '//' + location.host + '/ws');

  ws.onopen = () => {
    document.getElementById('ws-dot').classList.add('connected');
    document.getElementById('ws-status').textContent = 'Verbunden';
  };

  ws.onclose = () => {
    document.getElementById('ws-dot').classList.remove('connected');
    document.getElementById('ws-status').textContent = 'Getrennt';
    setTimeout(connectWS, 3000);
  };

  ws.onerror = () => {
    ws.close();
  };

  ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data);
      const type = msg.type || msg.event || '';
      if (['agent_spawned', 'agent_done', 'agent_error'].includes(type)) {
        loadDashboard();
        // Also refresh tasks if on tasks tab
        const tasksTab = document.getElementById('tab-tasks');
        if (tasksTab.classList.contains('active')) {
          loadTasks();
        }
      }
    } catch (_) {
      // ignore non-JSON messages
    }
  };
}

// ── Init ────────────────────────────────────────────────────────────

loadDashboard();
connectWS();
