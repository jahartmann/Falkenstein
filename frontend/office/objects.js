import { findEntrance } from './pathfinding.js';

const INTERACT_RADIUS = 2;

export class ObjectManager {
  constructor(scene, tilemapManager, panelManager, agentManager) {
    this.scene = scene;
    this.tm = tilemapManager;
    this.pm = panelManager;
    this.am = agentManager;
    this.objects = [];
    this.nearestObject = null;
    this.hintEl = document.getElementById('interact-hint');
  }

  create() {
    this._registerObjects();

    this.scene.input.on('pointerdown', (pointer) => {
      if (this.pm.isOpen()) return;
      const cam = this.scene.cameras.main;
      if (cam.zoom >= 0.8) return;
      const world = cam.getWorldPoint(pointer.x, pointer.y);
      const tile = this.tm.worldToTile(world.x, world.y);
      const obj = this._findObjectAt(tile.x, tile.y, 2);
      if (obj) obj.onInteract();
    });

    return this;
  }

  _registerObjects() {
    const gemRoom = this.tm.rooms.find(r => r.name === 'Gemeinschaftsraum');
    if (gemRoom) {
      this.objects.push({
        name: 'Whiteboard', tileX: gemRoom.centerX, tileY: gemRoom.centerY,
        type: 'whiteboard', onInteract: () => this._openWhiteboard()
      });
    }

    const entrance = this._findEntrance();
    this.objects.push({
      name: 'Schedule-Tafel', tileX: entrance.x + 2, tileY: entrance.y - 1,
      type: 'schedule', onInteract: () => this._openScheduleBoard()
    });

    const kitchen = this.tm.rooms.find(r => r.name === 'Küche');
    if (kitchen) {
      this.objects.push({
        name: 'Kaffeemaschine', tileX: kitchen.centerX, tileY: kitchen.centerY,
        type: 'coffee', onInteract: () => this._openCoffee()
      });
    }

    this.objects.push({
      name: 'Briefkasten', tileX: entrance.x - 2, tileY: entrance.y - 1,
      type: 'telegram', onInteract: () => this._openTelegram()
    });
  }

  _findObjectAt(tileX, tileY, radius) {
    for (const obj of this.objects) {
      const dist = Math.abs(obj.tileX - tileX) + Math.abs(obj.tileY - tileY);
      if (dist <= radius) return obj;
    }
    return null;
  }

  update(playerTileX, playerTileY) {
    this.nearestObject = null;
    let bestDist = INTERACT_RADIUS + 1;

    for (const obj of this.objects) {
      const dist = Math.abs(obj.tileX - playerTileX) + Math.abs(obj.tileY - playerTileY);
      if (dist <= INTERACT_RADIUS && dist < bestDist) {
        bestDist = dist;
        this.nearestObject = obj;
      }
    }

    const playerWorld = this.tm.tileToWorld(playerTileX, playerTileY);
    const nearAgent = this.am.getAgentNear(playerWorld.x, playerWorld.y, INTERACT_RADIUS * 48);
    if (nearAgent && (!this.nearestObject || bestDist > 1)) {
      this.nearestObject = {
        name: `Monitor: ${nearAgent.name || nearAgent.type || 'Agent'}`,
        type: 'monitor',
        onInteract: () => this._openMonitor(nearAgent)
      };
    }

    if (this.nearestObject && !this.pm.isOpen()) {
      this.hintEl.textContent = `[E] ${this.nearestObject.name}`;
      this.hintEl.classList.remove('hidden');
    } else {
      this.hintEl.classList.add('hidden');
    }
  }

  interact() {
    if (this.nearestObject && !this.pm.isOpen()) {
      this.nearestObject.onInteract();
    }
  }

  async _openWhiteboard() {
    this.pm.open('Kanban Board', '<p style="color:#888">Laden...</p>');
    try {
      const res = await fetch('/api/admin/tasks?limit=50');
      const data = await res.json();
      const tasks = data.tasks || [];

      const cols = { open: [], in_progress: [], done: [], failed: [] };
      for (const t of tasks) {
        const status = t.status || 'open';
        if (cols[status]) cols[status].push(t);
      }

      let html = '<div class="kanban">';
      for (const [status, label] of [['open','Open'],['in_progress','In Progress'],['done','Done'],['failed','Failed']]) {
        html += `<div class="kanban-col"><h3>${label} (${cols[status].length})</h3>`;
        for (const t of cols[status].slice(0, 10)) {
          html += `<div class="kanban-card status-${status}">
            <div class="card-title">${this._esc(t.title || t.description || '—')}</div>
            <div class="card-agent">${t.agent_type || ''} · #${t.id}</div>
          </div>`;
        }
        html += '</div>';
      }
      html += '</div>';
      this.pm.open('Kanban Board', html);
    } catch (e) {
      this.pm.open('Kanban Board', `<p style="color:#f66">Fehler: ${e.message}</p>`);
    }
  }

  async _openScheduleBoard() {
    this.pm.open('Schedule-Tafel', '<p style="color:#888">Laden...</p>');
    try {
      const res = await fetch('/api/admin/schedules');
      const data = await res.json();
      const scheds = (data.tasks || []).filter(s => s.active);

      let html = '<ul class="schedule-list">';
      if (scheds.length === 0) {
        html += '<li style="color:#888">Keine aktiven Schedules</li>';
      }
      for (const s of scheds) {
        html += `<li>
          <span class="sched-name">${this._esc(s.name)}</span>
          <span class="sched-agent">${s.agent_type || '—'}</span>
          <span class="sched-time">${s.schedule || '—'}</span>
        </li>`;
      }
      html += '</ul>';
      this.pm.open('Schedule-Tafel', html);
    } catch (e) {
      this.pm.open('Schedule-Tafel', `<p style="color:#f66">Fehler: ${e.message}</p>`);
    }
  }

  async _openCoffee() {
    this.pm.open('Kaffeemaschine', '<p style="color:#888">Brühe Kaffee... ☕</p>');
    await new Promise(r => setTimeout(r, 2000));
    try {
      const res = await fetch('/api/admin/dashboard');
      const data = await res.json();
      const html = `<div class="coffee-receipt">
        <h3>☕ Kaffee-Bon</h3>
        <hr>
        <div class="receipt-line"><span>Uptime</span><span>${Math.floor((data.uptime_seconds || 0) / 60)} Min</span></div>
        <div class="receipt-line"><span>Aktive Agents</span><span>${(data.active_agents || []).length}</span></div>
        <div class="receipt-line"><span>Offene Tasks</span><span>${data.open_tasks_count || 0}</span></div>
        <div class="receipt-line"><span>Ollama</span><span>${data.ollama_status || '—'}</span></div>
        <hr>
        <p style="font-size:11px;margin-top:8px">Danke für deinen Besuch!</p>
      </div>`;
      this.pm.open('Kaffeemaschine', html);
    } catch (e) {
      this.pm.open('Kaffeemaschine', `<p style="color:#f66">Maschine defekt: ${e.message}</p>`);
    }
  }

  async _openTelegram() {
    this.pm.open('Briefkasten', '<p style="color:#888">Prüfe Post...</p>');
    try {
      const res = await fetch('/api/admin/tasks?limit=10');
      const data = await res.json();
      let html = '<div style="max-height:400px;overflow-y:auto">';
      html += '<p style="color:#888;font-size:11px;margin-bottom:12px">Letzte Aktivitäten</p>';
      for (const t of (data.tasks || [])) {
        const status = t.status || 'open';
        html += `<div style="padding:6px 0;border-bottom:1px solid #2a2a4a">
          <span style="color:#e0e0ff">${this._esc(t.title || t.description || '—')}</span>
          <span style="color:#888;font-size:11px;margin-left:8px">${status}</span>
        </div>`;
      }
      html += '</div>';
      this.pm.open('Briefkasten', html);
    } catch (e) {
      this.pm.open('Briefkasten', `<p style="color:#f66">Fehler: ${e.message}</p>`);
    }
  }

  _openMonitor(agent) {
    const html = `
      <div style="margin-bottom:12px">
        <span style="color:#888">Name:</span> <span style="color:#e0e0ff">${agent.name}</span>
        <span style="color:#888;margin-left:16px">Rolle:</span> <span style="color:#e0e0ff">${agent.role || agent.agentType || '—'}</span>
        <span style="color:#888;margin-left:16px">Status:</span> <span style="color:#44ff88">${agent.state}</span>
      </div>
      <div style="margin-bottom:12px">
        <span style="color:#888">Task:</span>
        <div style="color:#e0e0ff;margin-top:4px;background:#2a2a4a;padding:8px;border-radius:4px">${this._esc(agent.task || '—')}</div>
      </div>
      <div style="color:#888;font-size:11px">Agent ID: ${agent.id}</div>
    `;
    this.pm.open(`Monitor — ${agent.name}`, html);
  }

  _findEntrance() {
    return findEntrance(this.tm.collisionGrid);
  }

  _esc(str) {
    const d = document.createElement('div');
    d.textContent = String(str ?? '');
    return d.innerHTML;
  }
}
