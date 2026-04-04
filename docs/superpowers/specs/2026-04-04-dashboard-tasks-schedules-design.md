# Falkenstein Dashboard, Tasks & Schedules Overhaul

**Date:** 2026-04-04
**Status:** Approved

## Goal

Rebuild the dashboard as a sidebar-navigated control center with robust task management (filterable table with expandable rows), reliable schedule execution, and a clean Tailwind-dark UI. Fix underlying backend issues (missing CRUD, scheduler timing bugs, dead fields).

## Design Decisions

- **Style:** Clean Dark Theme (Tailwind gray palette: gray-900 bg, gray-800 cards, gray-700 borders, colored status badges)
- **Layout:** Icon-sidebar (48px) left, content area right. Four sections: Dashboard, Tasks, Schedules, Config (drawer overlay)
- **Tasks:** Filterable/sortable table with expandable rows for full result. Manual status changes and deletion supported.
- **Schedules:** Table with inline editing, toggle switches, two creation modes (manual + AI), next-run preview
- **Primary use case:** Monitoring what Falki does, with secondary manual task creation

## Frontend Architecture

Single-page app in `dashboard.html` + `dashboard.js`. No framework — vanilla JS with CSS custom properties for theming.

### Sidebar (48px wide, fixed left)

| Icon | Section | Shortcut |
|------|---------|----------|
| Grid (4 squares) | Dashboard | — |
| Checkbox | Tasks | — |
| Clock | Schedules | — |
| Gear | Config | Opens drawer overlay |

- Active item: left accent stripe (indigo-500) + lighter background (gray-800)
- Bottom: Ollama status dot (green/red) + uptime text (small)

### Dashboard Section

**Stats Bar (top):**
4 compact cards in a row:
- Aktive Agents (count, indigo accent)
- Offene Tasks (count, blue accent)
- Aktive Schedules (count, cyan accent)
- Fehler heute (count, red accent — 0 = green)

**Active Agents Panel:**
- Live list: Agent-ID (monospace), Typ-Badge (coder=purple, researcher=blue, writer=green, ops=orange), Task title, elapsed time counter
- Empty state: "Keine aktiven Agents" centered, muted text
- Updated via WebSocket events

**Recent Activity Panel:**
- Timeline of last 10 events: agent_spawned, agent_done, agent_error, task_created, schedule_run
- Each entry: icon, description, relative timestamp ("vor 3 Min")
- Auto-scrolls, updates via WebSocket

### Tasks Section

**Filter Bar:**
- Status dropdown: All / Open / In Progress / Done / Failed
- Agent dropdown: All / coder / researcher / writer / ops
- Search input (free text, searches title + description)
- Date range not needed initially — keep it simple

**Table Columns:**
| Column | Width | Content |
|--------|-------|---------|
| ID | 50px | `#123` |
| Titel | flex | Task title, truncated |
| Status | 100px | Badge: open=gray, in_progress=blue, done=green, failed=red |
| Agent | 100px | Badge with agent type |
| Erstellt | 120px | Relative timestamp |
| Ergebnis | 150px | First 80 chars, muted text |
| Aktionen | 80px | Expand button, delete button |

**Expandable Row (on click):**
- Full result text (pre-formatted, scrollable, max-height 400px)
- Full description
- Timestamps: created_at, updated_at
- Status-change dropdown (manual override)
- Project field (if set)

**Actions:**
- "Neuer Task" button top-right → modal with textarea, submits via MainAgent.handle_message
- Delete: confirmation prompt, then DELETE endpoint
- Status change: dropdown in expanded row, PATCH endpoint

**Pagination:** 50 per page, "Mehr laden" button at bottom (offset-based).

### Schedules Section

**Table Columns:**
| Column | Width | Content |
|--------|-------|---------|
| Name | flex | Schedule name |
| Zeitplan | 160px | Human-readable schedule string |
| Agent | 90px | Agent type badge |
| Aktiv | 70px | Toggle switch (green/gray) |
| Letzter Lauf | 120px | Relative timestamp or "—" |
| Nächster Lauf | 120px | Relative timestamp |
| Ergebnis | 90px | Badge: ok=green, done=blue, error=red |
| Aktionen | 120px | Edit, Run Now, Delete |

**Expandable Row (on click or Edit):**
- Full prompt (textarea, editable)
- Name (input, editable)
- Schedule (input, editable)
- Agent type (dropdown, editable)
- Active hours (input, optional)
- Save/Cancel buttons
- **Next Runs Preview:** Shows next 3 computed execution times

**Creation:**
- "Neuer Schedule" button → modal with two tabs:
  - "Manuell": form with name, schedule, agent_type, prompt, active_hours
  - "KI-Beschreibung": single textarea, AI generates schedule fields
- After AI generation: show preview of generated fields, user confirms before saving

### Config Section

Opens as a slide-in drawer (right side, 400px wide) over current content. Not a separate page.
- Grouped by category (LLM, Pfade, API Keys, Persönlichkeit, Allgemein)
- Collapsible groups
- Save per group
- Close button or click-outside to dismiss

## Backend Changes

### Database (`database.py`)

New methods:
```python
async def get_all_tasks(self, limit=50, offset=0, status=None, agent=None, search=None) -> list[TaskData]
async def get_task_count(self, status=None, agent=None, search=None) -> int
async def delete_task(self, task_id: int) -> bool
async def update_task_status_manual(self, task_id: int, status: TaskStatus) -> bool
```

### Admin API (`admin_api.py`)

Updated endpoints:
```
GET  /api/admin/tasks?status=&agent=&search=&limit=50&offset=0
     → Returns: {tasks: [...], total: int, limit: int, offset: int}
     → Full result text (no truncation), all fields
GET  /api/admin/tasks/{id}
     → Single task with full result
PATCH /api/admin/tasks/{id}  body: {status: "done"}
     → Manual status change
DELETE /api/admin/tasks/{id}
     → Delete task

GET  /api/admin/schedules/{id}
     → Add next_run and next_runs_preview (next 3 times) to response

GET  /api/admin/activity
     → Returns last 20 events (from a new activity_log table or from existing data)
```

### Scheduler (`scheduler.py`)

Fixes:
1. **`reload_tasks()` preserves timing:** When reloading, keep existing `_next_run` for tasks that haven't changed. Only recompute for new/modified tasks.
2. **`get_all_tasks_info()` returns full prompt** instead of `prompt_preview`.
3. **`get_next_runs(schedule, count=3)`:** New method that computes the next N run times for a schedule — used by the API for the preview.
4. **Cron warning:** When `cron:` prefix is detected, set `last_error = "Cron-Syntax nicht unterstützt, verwende deutsche Zeitangaben"` and `active = 0` instead of silent hourly fallback.

### WebSocket Events

New event types for richer activity feed:
```json
{"type": "task_created", "task_id": 123, "title": "..."}
{"type": "task_status_changed", "task_id": 123, "status": "done"}
{"type": "schedule_fired", "schedule_id": 1, "name": "..."}
```

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `frontend/dashboard.html` | Rewrite | Sidebar layout, new HTML structure |
| `frontend/dashboard.js` | Rewrite | All section logic, filters, expandable rows, WS handling |
| `backend/database.py` | Modify | Add task CRUD methods |
| `backend/admin_api.py` | Modify | New/updated task endpoints, schedule preview |
| `backend/scheduler.py` | Modify | Timing fix, cron warning, next-runs preview |
| `backend/main_agent.py` | Modify | Emit new WS events (task_created, schedule_fired) |

## Out of Scope

- Task subtask/hierarchy UI (DB supports it, but UI doesn't need it yet)
- Drag-and-drop reordering
- Task assignment to specific agents (auto-assigned by MainAgent)
- Real cron expression support (croniter integration) — just warn instead of silent fallback
- `light_context` DB field — remains unused, no UI exposure
