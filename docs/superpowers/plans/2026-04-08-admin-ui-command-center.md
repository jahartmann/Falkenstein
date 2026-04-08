# Admin UI Command Center — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current dark-only dashboard with a clean, card-based Command Center featuring light/dark mode, MCP server panel, better agent visualization, and a persistent quick-chat input.

**Architecture:** Complete rewrite of `dashboard.html`, `dashboard.css`, `dashboard.js` into `command-center.html`, `command-center.css`, `command-center.js`. Vanilla HTML/CSS/JS (no framework). All existing API calls and WebSocket handling are preserved — only the visual layer changes. The Pixel-Büro remains a separate page (`/office`).

**Tech Stack:** Vanilla HTML5, CSS3 (Custom Properties for theming), ES6+ JavaScript, WebSocket API, HTML5 Audio API.

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `frontend/command-center.html` | New UI structure: top bar, sidebar, main content, quick-chat |
| `frontend/command-center.css` | Complete CSS with light/dark theme system |
| `frontend/command-center.js` | All JS — API calls, WS, rendering (migrated + new MCP) |

### Modified Files

| File | Changes |
|------|---------|
| `backend/main.py` | Change `GET /` to serve `command-center.html` instead of `dashboard.html` |

### Preserved Files (no changes)

| File | Reason |
|------|--------|
| `frontend/dashboard.html/css/js` | Keep as fallback, remove later |
| `frontend/office/` | Pixel-Büro is separate, unchanged in this plan |

---

## Design System

### CSS Custom Properties — Two Themes

```css
/* Light (default) */
:root {
  --bg: #f8f9fa;
  --bg-secondary: #ffffff;
  --bg-tertiary: #f1f3f5;
  --border: #e2e8f0;
  --shadow: 0 1px 3px rgba(0,0,0,0.08);
  --shadow-lg: 0 4px 12px rgba(0,0,0,0.1);
  --text: #1a202c;
  --text-secondary: #4a5568;
  --text-muted: #a0aec0;
  --accent: #0ea5e9;
  --accent-hover: #0284c7;
  --accent-light: #e0f2fe;
  --green: #10b981;
  --green-light: #d1fae5;
  --red: #ef4444;
  --red-light: #fee2e2;
  --amber: #f59e0b;
  --amber-light: #fef3c7;
  --purple: #8b5cf6;
  --radius: 8px;
  --radius-lg: 12px;
  --sidebar-width: 220px;
  --topbar-height: 56px;
  --quickchat-height: 60px;
}

/* Dark */
[data-theme="dark"] {
  --bg: #0f172a;
  --bg-secondary: #1e293b;
  --bg-tertiary: #334155;
  --border: #475569;
  --shadow: 0 1px 3px rgba(0,0,0,0.3);
  --shadow-lg: 0 4px 12px rgba(0,0,0,0.4);
  --text: #f1f5f9;
  --text-secondary: #cbd5e1;
  --text-muted: #64748b;
  --accent: #38bdf8;
  --accent-hover: #7dd3fc;
  --accent-light: #0c4a6e;
  --green: #34d399;
  --green-light: #064e3b;
  --red: #f87171;
  --red-light: #7f1d1d;
  --amber: #fbbf24;
  --amber-light: #78350f;
  --purple: #a78bfa;
}
```

### Card Component

```css
.card {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 20px;
  box-shadow: var(--shadow);
}
.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  font-weight: 600;
  color: var(--text);
}
.card-header .icon {
  width: 20px;
  height: 20px;
  color: var(--accent);
}
```

---

## Task 1: CSS Theme System + Base Layout

**Files:**
- Create: `frontend/command-center.css`

- [ ] **Step 1: Create CSS file with theme variables**

Create `frontend/command-center.css` with all CSS custom properties for both light and dark themes (as specified in the Design System section above).

- [ ] **Step 2: Add base layout styles**

```css
* { margin: 0; padding: 0; box-sizing: border-box; }

body {
  font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', sans-serif;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  transition: background 0.2s, color 0.2s;
}

.app {
  display: flex;
  min-height: 100vh;
}

/* Top Bar */
.topbar {
  position: fixed;
  top: 0;
  left: var(--sidebar-width);
  right: 0;
  height: var(--topbar-height);
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  z-index: 100;
}
.topbar-left { display: flex; align-items: center; gap: 12px; }
.topbar-title { font-size: 18px; font-weight: 700; color: var(--text); }
.topbar-right { display: flex; align-items: center; gap: 16px; }

/* Theme toggle button */
.theme-toggle {
  background: none;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 6px 8px;
  cursor: pointer;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
}

/* Sidebar */
.sidebar {
  position: fixed;
  top: 0;
  left: 0;
  width: var(--sidebar-width);
  height: 100vh;
  background: var(--bg-secondary);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  z-index: 200;
  overflow-y: auto;
}
.sidebar-logo {
  height: var(--topbar-height);
  display: flex;
  align-items: center;
  padding: 0 20px;
  font-size: 20px;
  font-weight: 800;
  color: var(--accent);
  border-bottom: 1px solid var(--border);
}
.sidebar-nav { flex: 1; padding: 8px; }
.sidebar-btn {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 10px 12px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 14px;
  cursor: pointer;
  border-radius: var(--radius);
  transition: all 0.15s;
}
.sidebar-btn:hover { background: var(--bg-tertiary); color: var(--text); }
.sidebar-btn.active {
  background: var(--accent-light);
  color: var(--accent);
  font-weight: 600;
}
.sidebar-btn .icon { width: 18px; height: 18px; flex-shrink: 0; }
.sidebar-footer {
  padding: 12px;
  border-top: 1px solid var(--border);
}

/* Main Content */
.content {
  margin-left: var(--sidebar-width);
  margin-top: var(--topbar-height);
  margin-bottom: var(--quickchat-height);
  padding: 24px;
  flex: 1;
  min-height: calc(100vh - var(--topbar-height) - var(--quickchat-height));
}

/* Quick Chat */
.quickchat {
  position: fixed;
  bottom: 0;
  left: var(--sidebar-width);
  right: 0;
  height: var(--quickchat-height);
  background: var(--bg-secondary);
  border-top: 1px solid var(--border);
  display: flex;
  align-items: center;
  padding: 0 24px;
  gap: 12px;
  z-index: 100;
}
.quickchat input {
  flex: 1;
  padding: 10px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg);
  color: var(--text);
  font-size: 14px;
  outline: none;
}
.quickchat input:focus { border-color: var(--accent); }
.quickchat button {
  padding: 10px 20px;
  border: none;
  border-radius: var(--radius);
  background: var(--accent);
  color: white;
  font-weight: 600;
  cursor: pointer;
}

/* Section visibility */
.section { display: none; }
.section.active { display: block; }
```

- [ ] **Step 3: Add card, badge, button, and grid component styles**

```css
/* Cards */
.card { /* as defined in Design System above */ }
.card-header { /* as above */ }

/* Card Grid */
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}
.card-grid-3 { grid-template-columns: repeat(3, 1fr); }
.card-grid-4 { grid-template-columns: repeat(4, 1fr); }

/* Stat Cards (small) */
.stat-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 16px 20px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.stat-card .stat-icon {
  width: 40px;
  height: 40px;
  border-radius: var(--radius);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
}
.stat-card .stat-value { font-size: 24px; font-weight: 700; }
.stat-card .stat-label { font-size: 13px; color: var(--text-muted); }

/* Badges */
.badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
}
.badge-green { background: var(--green-light); color: var(--green); }
.badge-red { background: var(--red-light); color: var(--red); }
.badge-amber { background: var(--amber-light); color: var(--amber); }
.badge-accent { background: var(--accent-light); color: var(--accent); }

/* Status Dot */
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text-muted);
}
.status-dot.online { background: var(--green); }
.status-dot.error { background: var(--red); }
.status-dot.pulse {
  animation: pulse 2s infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

/* Buttons */
.btn {
  padding: 8px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-secondary);
  color: var(--text);
  cursor: pointer;
  font-size: 14px;
  transition: all 0.15s;
}
.btn:hover { background: var(--bg-tertiary); }
.btn-primary { background: var(--accent); color: white; border-color: var(--accent); }
.btn-primary:hover { background: var(--accent-hover); }
.btn-danger { background: var(--red); color: white; border-color: var(--red); }
.btn-sm { padding: 4px 10px; font-size: 12px; }

/* Tables */
table { width: 100%; border-collapse: collapse; }
th { text-align: left; font-weight: 600; color: var(--text-muted); font-size: 13px; padding: 8px 12px; border-bottom: 1px solid var(--border); }
td { padding: 10px 12px; border-bottom: 1px solid var(--border); font-size: 14px; }
tr:hover { background: var(--bg-tertiary); }

/* Gauges */
.gauge-ring {
  width: 80px;
  height: 80px;
  border-radius: 50%;
  background: conic-gradient(var(--accent) var(--pct), var(--border) 0);
  display: flex;
  align-items: center;
  justify-content: center;
}
.gauge-inner {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: var(--bg-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  font-weight: 700;
}

/* Chat */
.chat-area { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 8px; }
.chat-bubble { max-width: 70%; padding: 10px 14px; border-radius: 12px; font-size: 14px; line-height: 1.5; }
.chat-bubble.user { align-self: flex-end; background: var(--accent); color: white; border-bottom-right-radius: 4px; }
.chat-bubble.assistant { align-self: flex-start; background: var(--bg-tertiary); color: var(--text); border-bottom-left-radius: 4px; }

/* Toast notifications */
.toast {
  position: fixed;
  top: 72px;
  right: 24px;
  padding: 12px 20px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-lg);
  z-index: 1000;
  animation: slideIn 0.3s ease;
}
@keyframes slideIn {
  from { transform: translateX(100%); opacity: 0; }
  to { transform: translateX(0); opacity: 1; }
}

/* Responsive */
@media (max-width: 900px) {
  .sidebar { width: 60px; }
  .sidebar .sidebar-btn span { display: none; }
  .sidebar-logo span { display: none; }
  .content, .topbar, .quickchat { left: 60px; margin-left: 60px; }
  .card-grid-3, .card-grid-4 { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 600px) {
  .card-grid-3, .card-grid-4, .card-grid { grid-template-columns: 1fr; }
}
```

- [ ] **Step 4: Commit**

```bash
git add frontend/command-center.css
git commit -m "feat(ui): add command center CSS with light/dark theme system"
```

---

## Task 2: HTML Structure

**Files:**
- Create: `frontend/command-center.html`

- [ ] **Step 1: Create the HTML file with full structure**

Create `frontend/command-center.html`. The structure must include:

**Head:** charset, viewport, title "Falkenstein", link to `command-center.css`, lang="de"

**Body layout:**
```html
<div class="app">
  <!-- Sidebar -->
  <nav class="sidebar">
    <div class="sidebar-logo">
      <span>Falkenstein</span>
    </div>
    <div class="sidebar-nav">
      <!-- 11 nav buttons, each with SVG icon + text label -->
      <button class="sidebar-btn active" data-section="dashboard">
        <svg class="icon">...</svg><span>Dashboard</span>
      </button>
      <!-- dashboard, agents, chat, tasks, mcp, schedules, memory, obsidian, system, settings -->
    </div>
    <div class="sidebar-footer">
      <button class="sidebar-btn" onclick="window.open('/office','_blank')">
        <svg class="icon">...</svg><span>Pixel-Büro</span>
      </button>
      <div class="status-dots">
        <span class="status-dot" id="ws-dot" title="WebSocket"></span>
        <span class="status-dot" id="ollama-dot" title="Ollama"></span>
      </div>
    </div>
  </nav>

  <!-- Top Bar -->
  <header class="topbar">
    <div class="topbar-left">
      <h1 class="topbar-title">Dashboard</h1>
    </div>
    <div class="topbar-right">
      <button class="theme-toggle" onclick="toggleTheme()" title="Theme wechseln">
        <svg id="theme-icon">...</svg>
      </button>
    </div>
  </header>

  <!-- Main Content (all sections) -->
  <main class="content">
    <!-- Section: Dashboard -->
    <section class="section active" id="section-dashboard">
      <div class="card-grid-4" id="stats-row">
        <!-- 4 stat cards: injected by JS -->
      </div>
      <div class="card-grid" style="margin-top:16px">
        <div class="card" id="agents-card">
          <div class="card-header"><svg class="icon">...</svg> Aktive Agents</div>
          <div id="agents-list"></div>
        </div>
        <div class="card" id="mcp-card">
          <div class="card-header"><svg class="icon">...</svg> MCP Server</div>
          <div id="mcp-status-list"></div>
        </div>
        <div class="card" id="system-card">
          <div class="card-header"><svg class="icon">...</svg> System</div>
          <div id="system-mini"></div>
        </div>
      </div>
      <div class="card-grid" style="margin-top:16px">
        <div class="card" id="activity-card">
          <div class="card-header"><svg class="icon">...</svg> Letzte Aktivitäten</div>
          <div id="activity-feed"></div>
        </div>
        <div class="card" id="upcoming-card">
          <div class="card-header"><svg class="icon">...</svg> Nächste Termine</div>
          <div id="upcoming-list"></div>
        </div>
      </div>
    </section>

    <!-- Section: Agents -->
    <section class="section" id="section-agents">
      <div class="card-grid" id="agent-cards"></div>
    </section>

    <!-- Section: Chat -->
    <section class="section" id="section-chat">
      <div class="card" style="height:calc(100vh - 180px);display:flex;flex-direction:column">
        <div class="card-header"><svg class="icon">...</svg> Chat mit Falki</div>
        <div class="chat-area" id="chat-messages"></div>
        <div class="chat-input-bar">
          <textarea id="chat-input" placeholder="Nachricht..." rows="1"></textarea>
          <button class="btn btn-primary" onclick="sendChat()">Senden</button>
        </div>
      </div>
    </section>

    <!-- Section: Tasks -->
    <section class="section" id="section-tasks">
      <div class="section-header">
        <div class="filter-bar">
          <select id="task-status-filter"><option value="">Alle Status</option>...</select>
          <input type="text" id="task-search" placeholder="Suchen...">
          <button class="btn btn-sm" onclick="toggleTaskView()">Kanban</button>
          <button class="btn btn-primary btn-sm" onclick="openTaskModal()">+ Neue Aufgabe</button>
        </div>
      </div>
      <div id="tasks-table-container">
        <table><thead><tr><th>Status</th><th>Titel</th><th>Agent</th><th>Erstellt</th><th></th></tr></thead>
        <tbody id="tasks-body"></tbody></table>
        <div id="tasks-pagination"></div>
      </div>
      <div id="kanban-board" class="kanban-board" style="display:none">
        <!-- 4 kanban columns injected by JS -->
      </div>
    </section>

    <!-- Section: MCP Servers -->
    <section class="section" id="section-mcp">
      <div class="card-grid" id="mcp-server-cards"></div>
    </section>

    <!-- Section: Schedules -->
    <section class="section" id="section-schedules">
      <div class="section-header">
        <button class="btn btn-primary btn-sm" onclick="openScheduleModal()">+ Neuer Schedule</button>
      </div>
      <div class="card-grid" id="schedule-cards"></div>
    </section>

    <!-- Section: Memory -->
    <section class="section" id="section-memory">
      <div class="card">
        <div class="card-header"><svg class="icon">...</svg> Soul Memory</div>
        <div class="memory-tabs">
          <button class="btn btn-sm active" data-layer="user">User</button>
          <button class="btn btn-sm" data-layer="self">Self</button>
          <button class="btn btn-sm" data-layer="relationship">Relationship</button>
        </div>
        <div id="memory-content"></div>
      </div>
    </section>

    <!-- Section: Obsidian -->
    <section class="section" id="section-obsidian">
      <div style="display:grid;grid-template-columns:300px 1fr;gap:16px;height:calc(100vh - 180px)">
        <div class="card" style="overflow-y:auto">
          <div class="card-header">Vault</div>
          <div id="obsidian-list"></div>
        </div>
        <div class="card" style="overflow-y:auto">
          <div class="card-header" id="obsidian-note-title">Keine Notiz ausgewählt</div>
          <pre id="obsidian-note-content" style="white-space:pre-wrap;font-size:14px"></pre>
        </div>
      </div>
    </section>

    <!-- Section: System -->
    <section class="section" id="section-system">
      <div class="card-grid-4" id="system-gauges"></div>
      <div class="card-grid" style="margin-top:16px">
        <div class="card">
          <div class="card-header">Ollama Modelle</div>
          <div id="ollama-models"></div>
        </div>
        <div class="card">
          <div class="card-header">Datenbank</div>
          <div id="db-stats"></div>
        </div>
      </div>
    </section>

    <!-- Section: Settings -->
    <section class="section" id="section-settings">
      <div id="config-container"></div>
    </section>
  </main>

  <!-- Quick Chat (always visible) -->
  <div class="quickchat">
    <input type="text" id="quickchat-input" placeholder="Falki etwas sagen... (/ für Befehle)"
           onkeydown="if(event.key==='Enter')sendQuickChat()">
    <button class="btn btn-primary" onclick="sendQuickChat()">Senden</button>
  </div>
</div>

<!-- Modals (hidden) -->
<div class="modal-overlay" id="modal-task" style="display:none">...</div>
<div class="modal-overlay" id="modal-schedule" style="display:none">...</div>
<div class="modal-overlay" id="modal-command" style="display:none">...</div>

<script src="/static/command-center.js"></script>
```

Use simple, clean SVG icons (16-20px) for sidebar buttons and card headers. Icons needed: home/dashboard, robot/agents, chat, clipboard/tasks, plug/mcp, clock/schedules, brain/memory, notebook/obsidian, monitor/system, gear/settings, gamepad/pixel-büro, sun, moon.

- [ ] **Step 2: Commit**

```bash
git add frontend/command-center.html
git commit -m "feat(ui): add command center HTML structure with all sections"
```

---

## Task 3: JavaScript — Core, Navigation, Theme, WebSocket

**Files:**
- Create: `frontend/command-center.js` (initial — core functions only)

- [ ] **Step 1: Create JS file with globals, utilities, navigation, theme, WebSocket**

The file must include these sections (migrate from existing `dashboard.js`):

**Globals:**
```javascript
const API = '/api/admin';
let ws = null;
let tasksOffset = 0;
const TASKS_LIMIT = 50;
const activityLog = [];
let kanbanView = false;
```

**Utility functions** (copy from dashboard.js, adapt to new DOM IDs):
- `esc(str)` — HTML escaping
- `badge(status)` — badge HTML with new CSS classes (badge-green, badge-red, etc.)
- `relTime(dateStr)` — relative time in German
- `api(path, opts)` — fetch wrapper with auth

**Theme toggle:**
```javascript
function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme');
  const next = current === 'dark' ? null : 'dark';
  if (next) document.documentElement.setAttribute('data-theme', 'dark');
  else document.documentElement.removeAttribute('data-theme');
  localStorage.setItem('theme', next || 'light');
  updateThemeIcon();
}
function updateThemeIcon() {
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  document.getElementById('theme-icon').innerHTML = isDark ? SUN_SVG : MOON_SVG;
}
// On load: restore from localStorage
const savedTheme = localStorage.getItem('theme');
if (savedTheme === 'dark') document.documentElement.setAttribute('data-theme', 'dark');
```

**Navigation:**
```javascript
document.querySelectorAll('.sidebar-btn[data-section]').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.sidebar-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    btn.classList.add('active');
    const sectionId = 'section-' + btn.dataset.section;
    document.getElementById(sectionId).classList.add('active');
    document.querySelector('.topbar-title').textContent = btn.querySelector('span').textContent;
    // Load section data
    const loaders = {
      dashboard: loadDashboard,
      agents: loadAgents,
      chat: loadChat,
      tasks: loadTasks,
      mcp: loadMCP,
      schedules: loadSchedules,
      memory: loadMemory,
      obsidian: loadObsidian,
      system: loadSystem,
      settings: loadConfig,
    };
    const loader = loaders[btn.dataset.section];
    if (loader) loader();
  });
});
```

**WebSocket** (migrate from dashboard.js, adapt event names to new rendering functions):
```javascript
function connectWS() {
  const token = localStorage.getItem('falkenstein_token');
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(`${proto}//${location.host}/ws?token=${token}`);
  ws.onopen = () => {
    document.getElementById('ws-dot').classList.add('online');
  };
  ws.onclose = () => {
    document.getElementById('ws-dot').classList.remove('online');
    setTimeout(connectWS, 3000);
  };
  ws.onmessage = (e) => {
    const data = JSON.parse(e.data);
    handleWSMessage(data);
  };
}
function handleWSMessage(data) {
  switch(data.type) {
    case 'agent_spawn':
    case 'agent_spawned':
      addActivity('agent', `${data.crew || data.agent_type} gestartet`);
      loadDashboard();
      break;
    case 'agent_done':
      addActivity('done', `${data.crew || data.agent_type} fertig`);
      loadDashboard();
      break;
    case 'agent_error':
      addActivity('error', `${data.crew || data.agent_type} Fehler`);
      loadDashboard();
      break;
    case 'chat_reply':
      appendChatMessage('assistant', data.content || data.text);
      showToast('Neue Antwort von Falki');
      break;
    case 'task_created':
      addActivity('task', 'Neue Aufgabe erstellt');
      break;
    case 'tool_use':
      addActivity('tool', `${data.tool_name}: ${(data.output || '').substring(0, 80)}`);
      break;
  }
}
```

**Quick Chat:**
```javascript
function sendQuickChat() {
  const input = document.getElementById('quickchat-input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  api('/tasks/submit', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({text}) });
  showToast('Nachricht gesendet');
}
```

**Toast notifications:**
```javascript
function showToast(message, duration = 3000) {
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), duration);
}
```

**Init:**
```javascript
updateThemeIcon();
loadDashboard();
connectWS();
```

- [ ] **Step 2: Commit**

```bash
git add frontend/command-center.js
git commit -m "feat(ui): add command center JS core — nav, theme, WebSocket, utils"
```

---

## Task 4: JavaScript — Dashboard Section

**Files:**
- Modify: `frontend/command-center.js`

- [ ] **Step 1: Add Dashboard rendering functions**

```javascript
async function loadDashboard() {
  const [dash, schedules] = await Promise.all([
    api('/dashboard').then(r => r.json()),
    api('/schedules').then(r => r.json()),
  ]);

  // Stat cards
  const statsRow = document.getElementById('stats-row');
  statsRow.innerHTML = `
    <div class="stat-card">
      <div class="stat-icon" style="background:var(--accent-light);color:var(--accent)">🤖</div>
      <div><div class="stat-value">${dash.active_agents || 0}</div><div class="stat-label">Aktive Agents</div></div>
    </div>
    <div class="stat-card">
      <div class="stat-icon" style="background:var(--amber-light);color:var(--amber)">📋</div>
      <div><div class="stat-value">${dash.open_tasks || 0}</div><div class="stat-label">Offene Tasks</div></div>
    </div>
    <div class="stat-card">
      <div class="stat-icon" style="background:var(--green-light);color:var(--green)">🔌</div>
      <div><div class="stat-value" id="mcp-count">-</div><div class="stat-label">MCP Server</div></div>
    </div>
    <div class="stat-card">
      <div class="stat-icon" style="background:var(--purple);color:white">⏰</div>
      <div><div class="stat-value">${schedules.length || 0}</div><div class="stat-label">Schedules</div></div>
    </div>
  `;

  // Load MCP status for dashboard mini-panel
  loadDashboardMCP();

  // System mini gauges
  loadDashboardSystem();

  // Activity feed
  renderActivity();
}

async function loadDashboardMCP() {
  try {
    const servers = await api('/mcp/servers').then(r => r.json());
    document.getElementById('mcp-count').textContent = servers.filter(s => s.status === 'running').length;
    const list = document.getElementById('mcp-status-list');
    list.innerHTML = servers.map(s => `
      <div style="display:flex;align-items:center;gap:8px;padding:6px 0">
        <span class="status-dot ${s.status === 'running' ? 'online' : 'error'}"></span>
        <span style="flex:1">${esc(s.name)}</span>
        <span class="badge ${s.status === 'running' ? 'badge-green' : 'badge-red'}">${s.tools_count} Tools</span>
      </div>
    `).join('');
  } catch { /* MCP not available */ }
}

async function loadDashboardSystem() {
  try {
    const metrics = await api('/system/metrics').then(r => r.json());
    document.getElementById('system-mini').innerHTML = `
      <div style="display:flex;gap:16px">
        <div>CPU <strong>${metrics.cpu_percent || 0}%</strong></div>
        <div>RAM <strong>${metrics.ram_percent || 0}%</strong></div>
        <div>GPU <strong>${metrics.gpu_percent || '-'}%</strong></div>
      </div>
    `;
  } catch {}
}

function addActivity(type, text) {
  const icons = { agent: '🤖', done: '✅', error: '❌', task: '📋', tool: '🔧' };
  activityLog.unshift({ type, text, time: new Date().toLocaleTimeString('de-DE') });
  if (activityLog.length > 20) activityLog.pop();
  renderActivity();
}

function renderActivity() {
  const feed = document.getElementById('activity-feed');
  if (!feed) return;
  feed.innerHTML = activityLog.map(a => `
    <div style="display:flex;gap:8px;padding:6px 0;font-size:13px;border-bottom:1px solid var(--border)">
      <span>${{agent:'🤖',done:'✅',error:'❌',task:'📋',tool:'🔧'}[a.type] || '📌'}</span>
      <span style="flex:1;color:var(--text-secondary)">${esc(a.text)}</span>
      <span style="color:var(--text-muted)">${a.time}</span>
    </div>
  `).join('');
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/command-center.js
git commit -m "feat(ui): add dashboard section rendering with MCP and system cards"
```

---

## Task 5: JavaScript — MCP Section

**Files:**
- Modify: `frontend/command-center.js`

- [ ] **Step 1: Add MCP server management functions**

```javascript
async function loadMCP() {
  const servers = await api('/mcp/servers').then(r => r.json());
  const container = document.getElementById('mcp-server-cards');
  container.innerHTML = servers.map(s => `
    <div class="card">
      <div class="card-header">
        <span class="status-dot ${s.status === 'running' ? 'online pulse' : s.status === 'error' ? 'error' : ''}"></span>
        ${esc(s.name)}
        <span style="margin-left:auto" class="badge ${s.enabled ? 'badge-green' : 'badge-red'}">
          ${s.enabled ? 'Aktiv' : 'Deaktiviert'}
        </span>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:13px;color:var(--text-secondary)">
        <div>Status: <strong>${s.status}</strong></div>
        <div>Tools: <strong>${s.tools_count}</strong></div>
        <div>Uptime: <strong>${Math.round(s.uptime_seconds / 60)} min</strong></div>
        <div>Letzter Call: <strong>${s.last_call ? relTime(s.last_call) : '-'}</strong></div>
      </div>
      ${s.last_error ? `<div style="margin-top:8px;color:var(--red);font-size:12px">${esc(s.last_error)}</div>` : ''}
      <div id="mcp-tools-${s.id}" style="margin-top:12px"></div>
      <div style="margin-top:12px;display:flex;gap:8px">
        <button class="btn btn-sm" onclick="loadMCPTools('${s.id}')">Tools anzeigen</button>
        <button class="btn btn-sm" onclick="restartMCPServer('${s.id}')">Neustart</button>
        <button class="btn btn-sm ${s.enabled ? 'btn-danger' : 'btn-primary'}"
                onclick="toggleMCPServer('${s.id}', ${!s.enabled})">
          ${s.enabled ? 'Deaktivieren' : 'Aktivieren'}
        </button>
      </div>
    </div>
  `).join('');
}

async function loadMCPTools(serverId) {
  const tools = await api(`/mcp/servers/${serverId}/tools`).then(r => r.json());
  const container = document.getElementById(`mcp-tools-${serverId}`);
  container.innerHTML = `
    <div style="font-size:13px;color:var(--text-secondary)">
      ${tools.map(t => `
        <div style="padding:4px 0;border-bottom:1px solid var(--border)">
          <strong>${esc(t.name)}</strong> — ${esc(t.description)}
        </div>
      `).join('')}
    </div>
  `;
}

async function restartMCPServer(serverId) {
  await api(`/mcp/servers/${serverId}/restart`, { method: 'POST' });
  showToast('Server wird neugestartet...');
  setTimeout(loadMCP, 2000);
}

async function toggleMCPServer(serverId, enabled) {
  await api(`/mcp/servers/${serverId}/toggle`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ enabled }),
  });
  showToast(enabled ? 'Server aktiviert' : 'Server deaktiviert');
  loadMCP();
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/command-center.js
git commit -m "feat(ui): add MCP server management section"
```

---

## Task 6: JavaScript — Agents, Chat, Tasks Sections

**Files:**
- Modify: `frontend/command-center.js`

- [ ] **Step 1: Add Agents section**

Migrate agent display from dashboard.js but render as cards instead of chips:

```javascript
async function loadAgents() {
  const dash = await api('/dashboard').then(r => r.json());
  const container = document.getElementById('agent-cards');
  const agents = dash.agents || [];

  if (agents.length === 0) {
    container.innerHTML = '<div class="card"><div style="text-align:center;color:var(--text-muted);padding:40px">Keine aktiven Agents</div></div>';
    return;
  }

  container.innerHTML = agents.map(a => `
    <div class="card" style="border-left:3px solid ${a.status === 'error' ? 'var(--red)' : 'var(--green)'}">
      <div class="card-header">
        <span class="status-dot ${a.status === 'active' ? 'online pulse' : a.status === 'done' ? 'online' : 'error'}"></span>
        ${esc(a.name || a.crew_type || 'Agent')}
        ${badge(a.status || 'active')}
      </div>
      <div style="font-size:13px;color:var(--text-secondary)">
        <div>Typ: <strong>${esc(a.crew_type || '-')}</strong></div>
        <div>Task: ${esc(a.task || '-')}</div>
        ${a.duration ? `<div>Laufzeit: ${a.duration}s</div>` : ''}
      </div>
    </div>
  `).join('');
}
```

- [ ] **Step 2: Add Chat section**

Migrate from dashboard.js with new bubble styles:

```javascript
async function loadChat() {
  const history = await api('/chat-history?limit=50').then(r => r.json());
  const area = document.getElementById('chat-messages');
  area.innerHTML = (history || []).map(m =>
    `<div class="chat-bubble ${m.role === 'user' ? 'user' : 'assistant'}">${esc(m.content)}</div>`
  ).join('');
  area.scrollTop = area.scrollHeight;
}

function appendChatMessage(role, content) {
  const area = document.getElementById('chat-messages');
  if (!area) return;
  // Remove thinking indicator
  const thinking = area.querySelector('.thinking');
  if (thinking) thinking.remove();
  area.innerHTML += `<div class="chat-bubble ${role}">${esc(content)}</div>`;
  area.scrollTop = area.scrollHeight;
}

async function sendChat() {
  const input = document.getElementById('chat-input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  appendChatMessage('user', text);
  const area = document.getElementById('chat-messages');
  area.innerHTML += '<div class="chat-bubble assistant thinking" style="opacity:0.5">Denkt nach...</div>';
  area.scrollTop = area.scrollHeight;
  await api('/tasks/submit', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({text}) });
}
```

- [ ] **Step 3: Add Tasks section**

Migrate tasks table and kanban from dashboard.js, adapted to new DOM structure. Key functions:
- `loadTasks()` — paginated table with filters
- `toggleTaskView()` — table/kanban switch
- `loadKanban()` — 4 column kanban
- `submitTask()` — new task modal
- `patchTaskStatus()`, `deleteTask()`

Copy the logic from dashboard.js lines ~260-450 but adapt element IDs to match new HTML.

- [ ] **Step 4: Commit**

```bash
git add frontend/command-center.js
git commit -m "feat(ui): add agents, chat, and tasks sections"
```

---

## Task 7: JavaScript — Remaining Sections

**Files:**
- Modify: `frontend/command-center.js`

- [ ] **Step 1: Add Schedules section**

Migrate from dashboard.js. Render as cards instead of table rows:

```javascript
async function loadSchedules() {
  const schedules = await api('/schedules').then(r => r.json());
  const container = document.getElementById('schedule-cards');
  container.innerHTML = schedules.map(s => `
    <div class="card">
      <div class="card-header">
        ${esc(s.name)}
        <span style="margin-left:auto" class="badge ${s.active ? 'badge-green' : 'badge-red'}">
          ${s.active ? 'Aktiv' : 'Inaktiv'}
        </span>
      </div>
      <div style="font-size:13px;color:var(--text-secondary)">
        <div>Zeitplan: <code>${esc(s.schedule || s.cron)}</code></div>
        <div>Nächste Ausführung: ${s.next_run ? relTime(s.next_run) : '-'}</div>
      </div>
      <div style="margin-top:8px;display:flex;gap:8px">
        <button class="btn btn-sm" onclick="runSchedule('${s.id}')">Jetzt ausführen</button>
        <button class="btn btn-sm" onclick="toggleSchedule('${s.id}')">${s.active ? 'Deaktivieren' : 'Aktivieren'}</button>
        <button class="btn btn-sm btn-danger" onclick="deleteSchedule('${s.id}')">Löschen</button>
      </div>
    </div>
  `).join('');
}
```

Migrate `runSchedule()`, `toggleSchedule()`, `deleteSchedule()`, `openScheduleModal()`, `saveSchedule()` from dashboard.js.

- [ ] **Step 2: Add Memory section**

Migrate from dashboard.js with tab switching for the 3 layers.

- [ ] **Step 3: Add Obsidian section**

Migrate from dashboard.js — two-pane layout with note list and viewer.

- [ ] **Step 4: Add System section with gauge rings**

```javascript
async function loadSystem() {
  const metrics = await api('/system/metrics').then(r => r.json());
  const gauges = document.getElementById('system-gauges');
  const items = [
    { label: 'CPU', value: metrics.cpu_percent, color: 'var(--accent)' },
    { label: 'RAM', value: metrics.ram_percent, color: 'var(--purple)' },
    { label: 'GPU', value: metrics.gpu_percent || 0, color: 'var(--green)' },
    { label: 'Temp', value: metrics.temperature || 0, color: 'var(--amber)', max: 100 },
  ];
  gauges.innerHTML = items.map(i => `
    <div class="card" style="display:flex;flex-direction:column;align-items:center">
      <div class="gauge-ring" style="--pct:${i.value}%">
        <div class="gauge-inner">${Math.round(i.value)}${i.label === 'Temp' ? '°' : '%'}</div>
      </div>
      <div style="margin-top:8px;font-weight:600">${i.label}</div>
    </div>
  `).join('');

  // Ollama models
  loadOllamaModels();
}
```

- [ ] **Step 5: Add Settings/Config section**

Migrate `loadConfig()` and `saveConfigGroup()` from dashboard.js. Organize into tabbed categories.

- [ ] **Step 6: Commit**

```bash
git add frontend/command-center.js
git commit -m "feat(ui): add schedules, memory, obsidian, system, and settings sections"
```

---

## Task 8: Wire Up in Backend + Modals

**Files:**
- Modify: `backend/main.py`
- Modify: `frontend/command-center.html` (add modals)
- Modify: `frontend/command-center.js` (add modal + command palette logic)

- [ ] **Step 1: Update `backend/main.py` to serve new UI**

Find the route that serves `dashboard.html` at `GET /` and change it to serve `command-center.html`:

```python
# Change: dashboard.html → command-center.html
@app.get("/", response_class=HTMLResponse)
async def root():
    path = FRONTEND_DIR / "command-center.html"
    if not path.exists():
        path = FRONTEND_DIR / "dashboard.html"  # fallback
    return HTMLResponse(path.read_text())
```

- [ ] **Step 2: Add modals to HTML**

Add task creation modal, schedule modal, and command palette modal (Ctrl+K) to `command-center.html`. Migrate from dashboard.html.

- [ ] **Step 3: Add modal and command palette JS**

Migrate from dashboard.js:
- `openTaskModal()` / `submitTask()`
- `openScheduleModal()` / `saveSchedule()`
- Command palette (Ctrl+K): `COMMANDS` array, `filterCommands()`, `runCommand()`

- [ ] **Step 4: Add Ctrl+K shortcut and / focus shortcut**

```javascript
document.addEventListener('keydown', (e) => {
  if (e.key === 'k' && (e.metaKey || e.ctrlKey)) {
    e.preventDefault();
    toggleCommandPalette();
  }
  if (e.key === '/' && !['INPUT','TEXTAREA'].includes(document.activeElement.tagName)) {
    e.preventDefault();
    document.getElementById('quickchat-input').focus();
  }
});
```

- [ ] **Step 5: Verify the new UI loads correctly**

Run: `source venv312/bin/activate && python -m backend.main`
Open: `http://localhost:8800`
Verify: Light theme loads, sidebar works, dashboard shows cards, theme toggle switches to dark.

- [ ] **Step 6: Commit**

```bash
git add backend/main.py frontend/command-center.html frontend/command-center.js
git commit -m "feat(ui): wire up command center, add modals and shortcuts"
```

---

## Task 9: Final Polish + Responsive

**Files:**
- Modify: `frontend/command-center.css`
- Modify: `frontend/command-center.js`

- [ ] **Step 1: Add remaining CSS refinements**

- Kanban board styles (4 columns, drag-and-drop)
- Modal overlay styles
- Config form styles (groups, inputs, save buttons)
- Memory section tab styles
- Smooth transitions on theme change
- Better scroll behavior

- [ ] **Step 2: Test responsive breakpoints**

Verify at 1400px, 900px, 600px widths:
- Sidebar collapses to icons at 900px
- Cards stack at 600px
- Quick chat remains usable

- [ ] **Step 3: Final verification**

Test all sections work:
- [ ] Dashboard loads with stat cards + MCP status + system mini
- [ ] Agents section shows cards
- [ ] Chat works (send/receive)
- [ ] Tasks table + kanban toggle
- [ ] MCP section shows servers with restart/toggle
- [ ] Schedules as cards
- [ ] Memory with tab switching
- [ ] Obsidian two-pane
- [ ] System gauges
- [ ] Settings/Config form
- [ ] Theme toggle persists
- [ ] Quick chat sends messages
- [ ] Ctrl+K command palette
- [ ] WebSocket reconnects

- [ ] **Step 4: Commit**

```bash
git add frontend/command-center.css frontend/command-center.js
git commit -m "feat(ui): polish responsive layout and verify all sections"
```
