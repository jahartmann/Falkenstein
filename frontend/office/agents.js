import { findPath, findEntrance } from './pathfinding.js';

const AGENT_CONFIG = {
  coder:      { sprite: 'Adam',   room: 'Team Büro' },
  researcher: { sprite: 'Alex',   room: 'Deep-Dive 1' },
  writer:     { sprite: 'Amelia', room: 'Fokus-Büro' },
  ops:        { sprite: 'Bob',    room: 'Teamleitung' },
};

const WALK_SPEED = 120; // ms per tile
const PAUSE_ROOMS = ['Küche', 'Lounge', 'Gemeinschaftsraum'];

export class AgentManager {
  constructor(scene, tilemapManager) {
    this.scene = scene;
    this.tm = tilemapManager;
    this.agents = new Map();
    this.occupiedTiles = new Set();
  }

  create() {
    this._createAnimations();
    return this;
  }

  _createAnimations() {
    const anims = this.scene.anims;
    for (const [type, cfg] of Object.entries(AGENT_CONFIG)) {
      const name = cfg.sprite;
      const directions = ['down', 'left', 'right', 'up'];
      for (let d = 0; d < 4; d++) {
        const dir = directions[d];
        const idleStart = d * 3;
        if (!anims.exists(`${type}_idle_${dir}`)) {
          anims.create({
            key: `${type}_idle_${dir}`,
            frames: anims.generateFrameNumbers(`${name}_idle_anim`, { start: idleStart, end: idleStart + 2 }),
            frameRate: 6, repeat: -1
          });
        }
        if (!anims.exists(`${type}_walk_${dir}`)) {
          anims.create({
            key: `${type}_walk_${dir}`,
            frames: anims.generateFrameNumbers(`${name}_run`, { start: idleStart, end: idleStart + 2 }),
            frameRate: 8, repeat: -1
          });
        }
      }
      if (!anims.exists(`${type}_sit`)) {
        anims.create({
          key: `${type}_sit`,
          frames: [{ key: `${name}_sit`, frame: 0 }],
          frameRate: 1, repeat: 0
        });
      }
      if (!anims.exists(`${type}_phone`)) {
        anims.create({
          key: `${type}_phone`,
          frames: anims.generateFrameNumbers(`${name}_phone`, { start: 0, end: 3 }),
          frameRate: 4, repeat: -1
        });
      }
    }
  }

  spawnAgent(agentId, agentType, taskText) {
    if (this.agents.has(agentId)) return;
    const cfg = AGENT_CONFIG[agentType] || AGENT_CONFIG.coder;

    const spawnTile = this._findEntrance();
    const desk = this._findFreeDesk(cfg.room);
    if (!desk) {
      console.warn(`No free desk for ${agentType} in ${cfg.room}`);
      return;
    }

    desk.occupied = true;
    desk.agentId = agentId;

    const pos = this.tm.tileToWorld(spawnTile.x, spawnTile.y);
    const sprite = this.scene.add.sprite(pos.x, pos.y, `${cfg.sprite}_idle_anim`, 0);
    sprite.setScale(3);
    sprite.setDepth(10);

    const agent = {
      id: agentId, type: agentType, task: taskText || '',
      sprite, config: cfg, desk,
      tileX: spawnTile.x, tileY: spawnTile.y,
      state: 'walking_to_desk',
      path: null, pathIndex: 0, tweenActive: false,
      pauseTimer: null, breakCount: 0,
    };

    this.agents.set(agentId, agent);
    this._walkTo(agent, desk.tileX, desk.tileY, () => {
      this._sitDown(agent);
    });
  }

  removeAgent(agentId) {
    const agent = this.agents.get(agentId);
    if (!agent) return;

    if (agent.desk) {
      agent.desk.occupied = false;
      agent.desk.agentId = null;
    }
    if (agent.pauseTimer) clearTimeout(agent.pauseTimer);

    agent.state = 'leaving';
    this.scene.tweens.killTweensOf(agent.sprite);
    const entrance = this._findEntrance();
    this._walkTo(agent, entrance.x, entrance.y, () => {
      agent.sprite.destroy();
      this.agents.delete(agentId);
      this.occupiedTiles.delete(this._tileKey(agent.tileX, agent.tileY));
    });
  }

  _sitDown(agent) {
    agent.state = 'working';
    agent.sprite.anims.play(`${agent.type}_sit`, true);
    this._schedulePause(agent);
  }

  _schedulePause(agent) {
    if (agent.state !== 'working') return;
    const delay = 15000 + Math.random() * 15000;
    agent.pauseTimer = setTimeout(() => {
      if (agent.state !== 'working') return;
      this._goOnBreak(agent);
    }, delay);
  }

  _goOnBreak(agent) {
    agent.state = 'on_break';
    agent.breakCount++;

    if (agent.breakCount % 3 === 0) {
      agent.sprite.anims.play(`${agent.type}_phone`, true);
      setTimeout(() => {
        if (agent.state !== 'on_break') return;
        this._sitDown(agent);
      }, 5000 + Math.random() * 5000);
      return;
    }

    const pauseRoom = PAUSE_ROOMS[Math.floor(Math.random() * PAUSE_ROOMS.length)];
    const room = this.tm.rooms.find(r => r.name === pauseRoom);
    if (!room) { this._sitDown(agent); return; }

    this._walkTo(agent, room.centerX, room.centerY, () => {
      agent.sprite.anims.play(`${agent.type}_idle_down`, true);
      setTimeout(() => {
        if (agent.state !== 'on_break') return;
        this._walkTo(agent, agent.desk.tileX, agent.desk.tileY, () => {
          this._sitDown(agent);
        });
      }, 5000 + Math.random() * 5000);
    });
  }

  _walkTo(agent, targetX, targetY, onComplete) {
    const path = findPath(
      this.tm.collisionGrid,
      agent.tileX, agent.tileY,
      targetX, targetY,
      this.occupiedTiles
    );

    if (!path || path.length < 2) {
      if (onComplete) onComplete();
      return;
    }

    agent.path = path;
    agent.pathIndex = 1;
    this._walkNextTile(agent, onComplete);
  }

  _walkNextTile(agent, onComplete) {
    if (agent.pathIndex >= agent.path.length) {
      agent.tweenActive = false;
      if (onComplete) onComplete();
      return;
    }

    const next = agent.path[agent.pathIndex];
    const pos = this.tm.tileToWorld(next.x, next.y);

    const dx = next.x - agent.tileX;
    const dy = next.y - agent.tileY;
    let dir = 'down';
    if (dx < 0) dir = 'left';
    else if (dx > 0) dir = 'right';
    else if (dy < 0) dir = 'up';

    agent.sprite.anims.play(`${agent.type}_walk_${dir}`, true);
    agent.tweenActive = true;

    this.occupiedTiles.delete(this._tileKey(agent.tileX, agent.tileY));
    agent.tileX = next.x;
    agent.tileY = next.y;
    this.occupiedTiles.add(this._tileKey(next.x, next.y));

    this.scene.tweens.add({
      targets: agent.sprite,
      x: pos.x,
      y: pos.y,
      duration: WALK_SPEED,
      ease: 'Linear',
      onComplete: () => {
        agent.pathIndex++;
        this._walkNextTile(agent, onComplete);
      }
    });
  }

  _findEntrance() {
    return findEntrance(this.tm.collisionGrid);
  }

  _findFreeDesk(roomName) {
    const room = this.tm.rooms.find(r => r.name === roomName);
    if (!room) return this.tm.desks.find(d => !d.occupied);

    const desk = this.tm.desks.find(d =>
      !d.occupied &&
      d.tileX >= room.x - 2 && d.tileX <= room.x + room.width + 2 &&
      d.tileY >= room.y - 2 && d.tileY <= room.y + room.height + 2
    );
    return desk || this.tm.desks.find(d => !d.occupied);
  }

  _tileKey(x, y) {
    return y * this.tm.collisionGrid[0].length + x;
  }

  getAgentAt(tileX, tileY) {
    for (const agent of this.agents.values()) {
      if (agent.tileX === tileX && agent.tileY === tileY) return agent;
    }
    return null;
  }

  getAgentNear(worldX, worldY, radius = 72) {
    let nearest = null;
    let bestDist = radius;
    for (const agent of this.agents.values()) {
      const dx = agent.sprite.x - worldX;
      const dy = agent.sprite.y - worldY;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < bestDist) {
        bestDist = dist;
        nearest = agent;
      }
    }
    return nearest;
  }

  updateAgentStatus(agentId, text) {
    const agent = this.agents.get(agentId);
    if (agent) agent.task = text;
  }
}
