export class HUD {
  constructor(scene, tilemapManager, agentManager) {
    this.scene = scene;
    this.tm = tilemapManager;
    this.am = agentManager;
    this.minimapCanvas = document.getElementById('minimap-canvas');
    this.minimapCtx = this.minimapCanvas ? this.minimapCanvas.getContext('2d') : null;
    this.wsConnected = false;
  }

  create() {
    const minimapEl = document.getElementById('minimap');
    if (minimapEl) {
      minimapEl.addEventListener('click', (e) => {
        const rect = minimapEl.getBoundingClientRect();
        const rx = (e.clientX - rect.left) / rect.width;
        const ry = (e.clientY - rect.top) / rect.height;
        const bounds = this.tm.getWorldBounds();
        const worldX = rx * bounds.width;
        const worldY = ry * bounds.height;
        this.scene.cameras.main.pan(worldX, worldY, 400, 'Sine.easeInOut');
      });
    }

    this._drawMinimapBase();
    return this;
  }

  update(playerWorldX, playerWorldY) {
    this._updateStats();
    this._drawMinimap(playerWorldX, playerWorldY);
  }

  setWSConnected(connected) {
    this.wsConnected = connected;
    const dot = document.getElementById('hud-ws');
    if (dot) {
      dot.classList.toggle('connected', connected);
      dot.title = connected ? 'WebSocket verbunden' : 'WebSocket getrennt';
    }
  }

  updateTaskCount(count) {
    document.getElementById('hud-tasks').textContent = count;
  }

  updateScheduleCount(count) {
    document.getElementById('hud-schedules').textContent = count;
  }

  _updateStats() {
    const agents = [...this.am.agents.values()];
    const agentCount = agents.length;
    const workingCount = agents.filter(agent => agent.state === 'working').length;
    const breakCount = agents.filter(agent => agent.state === 'on_break').length;
    document.getElementById('hud-agents').textContent = agentCount;
    const workingEl = document.getElementById('hud-working');
    const breakEl = document.getElementById('hud-break');
    if (workingEl) workingEl.textContent = workingCount;
    if (breakEl) breakEl.textContent = breakCount;
  }

  _drawMinimapBase() {
    if (!this.minimapCtx) return;
    const ctx = this.minimapCtx;
    const grid = this.tm.collisionGrid;
    const h = grid.length;
    const w = grid[0].length;
    const sx = 180 / w;
    const sy = 144 / h;

    ctx.fillStyle = '#1a1a2e';
    ctx.fillRect(0, 0, 180, 144);

    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        if (grid[y][x] === 0) {
          ctx.fillStyle = '#2a2a4a';
        } else {
          ctx.fillStyle = '#1a1a2e';
        }
        ctx.fillRect(x * sx, y * sy, Math.ceil(sx), Math.ceil(sy));
      }
    }

    this._minimapBase = ctx.getImageData(0, 0, 180, 144);
  }

  _drawMinimap(playerX, playerY) {
    if (!this.minimapCtx || !this._minimapBase) return;
    const ctx = this.minimapCtx;
    const grid = this.tm.collisionGrid;
    const w = grid[0].length;
    const h = grid.length;
    const sx = 180 / w;
    const sy = 144 / h;

    ctx.putImageData(this._minimapBase, 0, 0);

    const realColors = { coder: '#44aaff', researcher: '#ffaa44', writer: '#aa44ff', ops: '#44ff88' };
    for (const agent of this.am.agents.values()) {
      if (agent.isNPC) {
        ctx.fillStyle = '#888888';
        ctx.fillRect(agent.tileX * sx - 1, agent.tileY * sy - 1, 2, 2);
      } else {
        ctx.fillStyle = realColors[agent.agentType] || '#44ff88';
        ctx.fillRect(agent.tileX * sx - 1, agent.tileY * sy - 1, 3, 3);
      }
    }

    const pt = this.tm.worldToTile(playerX, playerY);
    ctx.fillStyle = '#4488ff';
    ctx.fillRect(pt.x * sx - 2, pt.y * sy - 2, 5, 5);
  }
}
