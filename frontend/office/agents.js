import { findPath, findEntrance } from './pathfinding.js';

// All available character sprite names
const SPRITE_NAMES = ['Adam', 'Alex', 'Amelia', 'Bob'];

// CrewAI crew type -> character sprite mapping
const CREW_SKINS = {
  coder:      'Adam',
  researcher: 'Alex',
  writer:     'Amelia',
  ops:        'Bob',
  web_design: 'Adam',
  swift:      'Alex',
  ki_expert:  'Bob',
  analyst:    'Amelia',
  premium:    'Adam',
};

// Abstract animation name -> sprite animation key suffix
const ANIMATION_MAP = {
  typing:   'sit',
  reading:  'phone',
  thinking: 'idle_anim',
  running:  'run',
};

// Real agent type -> sprite + room mapping
const AGENT_TYPE_CONFIG = {
  coder:      { sprite: 'Adam',   room: 'Team Büro' },
  researcher: { sprite: 'Alex',   room: 'Deep-Dive 1' },
  writer:     { sprite: 'Amelia', room: 'Fokus-Büro' },
  ops:        { sprite: 'Bob',    room: 'Teamleitung' },
  web_design: { sprite: 'Adam',   room: 'Team Büro' },
  swift:      { sprite: 'Alex',   room: 'Deep-Dive 1' },
  ki_expert:  { sprite: 'Bob',    room: 'Teamleitung' },
  analyst:    { sprite: 'Amelia', room: 'Fokus-Büro' },
  premium:    { sprite: 'Adam',   room: 'Team Büro' },
};

// NPC employees for office liveliness
const NPC_EMPLOYEES = [
  { id: 'npc-max',    name: 'Max',    sprite: 'Adam',   room: 'Team Büro',       role: 'Developer' },
  { id: 'npc-sophie', name: 'Sophie', sprite: 'Amelia', room: 'Fokus-Büro',      role: 'Designerin' },
  { id: 'npc-tom',    name: 'Tom',    sprite: 'Bob',    room: 'Deep-Dive 1',     role: 'Analyst' },
  { id: 'npc-lena',   name: 'Lena',   sprite: 'Alex',   room: 'Teamleitung',     role: 'Projektleiterin' },
  { id: 'npc-felix',  name: 'Felix',  sprite: 'Adam',   room: 'Team Büro',       role: 'Backend Dev' },
  { id: 'npc-anna',   name: 'Anna',   sprite: 'Alex',   room: 'Gemeinschaftsraum', role: 'UX Research' },
];

const WALK_SPEED = 400; // ms per tile
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
    for (const name of SPRITE_NAMES) {
      const directions = ['down', 'left', 'right', 'up'];
      for (let d = 0; d < 4; d++) {
        const dir = directions[d];
        const idleStart = d * 3;
        if (!anims.exists(`${name}_idle_${dir}`)) {
          anims.create({
            key: `${name}_idle_${dir}`,
            frames: anims.generateFrameNumbers(`${name}_idle_anim`, { start: idleStart, end: idleStart + 2 }),
            frameRate: 6, repeat: -1
          });
        }
        if (!anims.exists(`${name}_walk_${dir}`)) {
          anims.create({
            key: `${name}_walk_${dir}`,
            frames: anims.generateFrameNumbers(`${name}_run`, { start: idleStart, end: idleStart + 2 }),
            frameRate: 8, repeat: -1
          });
        }
      }
      if (!anims.exists(`${name}_sit`)) {
        anims.create({
          key: `${name}_sit`,
          frames: [{ key: `${name}_sit`, frame: 0 }],
          frameRate: 1, repeat: 0
        });
      }
      if (!anims.exists(`${name}_phone`)) {
        anims.create({
          key: `${name}_phone`,
          frames: anims.generateFrameNumbers(`${name}_phone`, { start: 0, end: 3 }),
          frameRate: 4, repeat: -1
        });
      }
    }
  }

  /* ── NPC Simulation ── */

  spawnNPCs() {
    // Stagger NPC spawns so they don't all walk in at once
    for (let i = 0; i < NPC_EMPLOYEES.length; i++) {
      const npc = NPC_EMPLOYEES[i];
      setTimeout(() => this._spawnNPC(npc), i * 800 + Math.random() * 400);
    }
  }

  _spawnNPC(npcConfig) {
    if (this.agents.has(npcConfig.id)) return;

    const desk = this._findFreeDesk(npcConfig.room);
    if (!desk) return;

    desk.occupied = true;
    desk.agentId = npcConfig.id;

    // NPCs enter through the door like real agents
    const spawnTile = this._findEntrance();
    const pos = this.tm.tileToWorld(spawnTile.x, spawnTile.y);

    const sprite = this.scene.add.sprite(pos.x, pos.y, `${npcConfig.sprite}_idle_anim`, 0);
    sprite.setScale(3);
    sprite.setDepth(10);
    sprite.setOrigin(0.5, 0.75);

    // Name label
    const label = this._createLabel(pos.x, pos.y, npcConfig.name, '#cccccc');

    const agent = {
      id: npcConfig.id,
      name: npcConfig.name,
      spriteName: npcConfig.sprite,
      agentType: null,
      sprite, label,
      indicator: null,
      desk,
      role: npcConfig.role,
      task: npcConfig.role,
      tileX: spawnTile.x, tileY: spawnTile.y,
      state: 'walking_to_desk',
      path: null, pathIndex: 0, tweenActive: false,
      pauseTimer: null, breakCount: 0,
      isNPC: true,
    };

    this.agents.set(npcConfig.id, agent);
    this.occupiedTiles.add(this._tileKey(spawnTile.x, spawnTile.y));

    this._walkTo(agent, desk.tileX, desk.tileY, () => {
      this._sitDown(agent);
    });
  }

  /* ── Real Agent Spawn ── */

  spawnAgent(agentId, agentType, taskText) {
    if (this.agents.has(agentId)) return;
    const cfg = AGENT_TYPE_CONFIG[agentType] || AGENT_TYPE_CONFIG.coder;

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
    sprite.setOrigin(0.5, 0.75);

    // Pulsing green indicator for active real agents
    const indicator = this.scene.add.circle(pos.x, pos.y + 24, 5, 0x44ff88, 0.9);
    indicator.setDepth(11);
    this.scene.tweens.add({
      targets: indicator, alpha: 0.3, duration: 800,
      yoyo: true, repeat: -1, ease: 'Sine.easeInOut'
    });

    // Green label for real agents
    const displayName = agentType.charAt(0).toUpperCase() + agentType.slice(1);
    const label = this._createLabel(pos.x, pos.y, displayName, '#44ff88');

    const agent = {
      id: agentId,
      name: displayName,
      spriteName: cfg.sprite,
      agentType: agentType,
      sprite, label, indicator,
      desk,
      role: agentType,
      task: taskText || '',
      tileX: spawnTile.x, tileY: spawnTile.y,
      state: 'walking_to_desk',
      path: null, pathIndex: 0, tweenActive: false,
      pauseTimer: null, breakCount: 0,
      isNPC: false,
    };

    this.agents.set(agentId, agent);
    this._walkTo(agent, desk.tileX, desk.tileY, () => {
      this._sitDown(agent);
    });
  }

  removeAgent(agentId) {
    const agent = this.agents.get(agentId);
    if (!agent || agent.isNPC) return;

    if (agent.desk) {
      agent.desk.occupied = false;
      agent.desk.agentId = null;
    }
    if (agent.pauseTimer) clearTimeout(agent.pauseTimer);

    agent.state = 'leaving';
    this.scene.tweens.killTweensOf(agent.sprite);
    if (agent.indicator) this.scene.tweens.killTweensOf(agent.indicator);

    const entrance = this._findEntrance();
    this._walkTo(agent, entrance.x, entrance.y, () => {
      agent.sprite.destroy();
      if (agent.label) agent.label.destroy();
      if (agent.indicator) agent.indicator.destroy();
      this.agents.delete(agentId);
      this.occupiedTiles.delete(this._tileKey(agent.tileX, agent.tileY));
    });
  }

  /* ── Position Updates (call from scene update) ── */

  updatePositions() {
    for (const agent of this.agents.values()) {
      if (agent.label) {
        agent.label.setPosition(agent.sprite.x, agent.sprite.y - 32);
      }
      if (agent.indicator) {
        agent.indicator.setPosition(agent.sprite.x, agent.sprite.y + 24);
      }
    }
  }

  /* ── Break / Pause Logic ── */

  _sitDown(agent) {
    agent.state = 'working';
    agent.sprite.anims.play(`${agent.spriteName}_sit`, true);
    this._schedulePause(agent);
  }

  _schedulePause(agent) {
    if (agent.state !== 'working') return;
    const minDelay = agent.isNPC ? 12000 : 25000;
    const extraDelay = agent.isNPC ? 18000 : 20000;
    const delay = minDelay + Math.random() * extraDelay;
    agent.pauseTimer = setTimeout(() => {
      if (agent.state !== 'working') return;
      this._goOnBreak(agent);
    }, delay);
  }

  _goOnBreak(agent) {
    agent.state = 'on_break';
    agent.breakCount++;

    // Every 3rd break: phone call at desk
    if (agent.breakCount % 3 === 0) {
      agent.sprite.anims.play(`${agent.spriteName}_phone`, true);
      setTimeout(() => {
        if (agent.state !== 'on_break') return;
        this._sitDown(agent);
      }, 4000 + Math.random() * 6000);
      return;
    }

    // Walk to a break room
    const pauseRoom = PAUSE_ROOMS[Math.floor(Math.random() * PAUSE_ROOMS.length)];
    const room = this.tm.rooms.find(r => r.name === pauseRoom);
    if (!room) { this._sitDown(agent); return; }

    // Pick a random tile near room center (not exact center, for variety)
    const targetX = room.centerX + Math.floor(Math.random() * 3) - 1;
    const targetY = room.centerY + Math.floor(Math.random() * 3) - 1;

    this._walkTo(agent, targetX, targetY, () => {
      agent.sprite.anims.play(`${agent.spriteName}_idle_down`, true);
      const idleDuration = 4000 + Math.random() * 8000;
      setTimeout(() => {
        if (agent.state !== 'on_break') return;
        this._walkTo(agent, agent.desk.tileX, agent.desk.tileY, () => {
          this._sitDown(agent);
        });
      }, idleDuration);
    });
  }

  /* ── Pathfinding & Walking ── */

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

    agent.sprite.anims.play(`${agent.spriteName}_walk_${dir}`, true);
    agent.tweenActive = true;

    this.occupiedTiles.delete(this._tileKey(agent.tileX, agent.tileY));
    agent.tileX = next.x;
    agent.tileY = next.y;
    this.occupiedTiles.add(this._tileKey(next.x, next.y));

    this.scene.tweens.add({
      targets: agent.sprite,
      x: pos.x, y: pos.y,
      duration: WALK_SPEED,
      ease: 'Linear',
      onComplete: () => {
        agent.pathIndex++;
        this._walkNextTile(agent, onComplete);
      }
    });
  }

  /* ── Helpers ── */

  _createLabel(x, y, text, color) {
    const label = this.scene.add.text(x, y - 32, text, {
      fontSize: '10px', fontFamily: 'monospace',
      color: color, backgroundColor: '#000000aa',
      padding: { x: 3, y: 1 },
    });
    label.setOrigin(0.5, 1);
    label.setDepth(20);
    return label;
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

  /* ── CrewAI EventBus Handlers ── */

  onAgentSpawn(crewType, crewId, task) {
    // Map crew type to agent type config, falling back to coder
    const agentType = AGENT_TYPE_CONFIG[crewType] ? crewType : 'coder';
    this.spawnAgent(crewId, agentType, task);
  }

  onToolUse(agentName, toolName, animation, crewId) {
    const agent = this.agents.get(crewId);
    if (!agent || agent.state === 'leaving') return;

    // Map abstract animation name; fall back to sit (typing) if unknown
    const animKey = ANIMATION_MAP[animation] || 'sit';

    if (animKey === 'sit') {
      agent.sprite.anims.play(`${agent.spriteName}_sit`, true);
    } else if (animKey === 'phone') {
      agent.sprite.anims.play(`${agent.spriteName}_phone`, true);
    } else if (animKey === 'idle_anim') {
      agent.sprite.anims.play(`${agent.spriteName}_idle_down`, true);
    } else if (animKey === 'run') {
      // No specific destination — play walk animation in place facing down
      agent.sprite.anims.play(`${agent.spriteName}_walk_down`, true);
    }

    agent.task = toolName || task;
  }

  onAgentDone(crewType, crewId) {
    const agent = this.agents.get(crewId);
    if (!agent || agent.isNPC) return;

    // Play idle animation to signal completion, then remove after 5s
    agent.sprite.anims.play(`${agent.spriteName}_idle_down`, true);
    setTimeout(() => this.removeAgent(crewId), 5000);
  }

  onAgentError(crewType, crewId, error) {
    const agent = this.agents.get(crewId);
    if (!agent || agent.isNPC) return;

    // Keep current position; error bubble is shown via BubbleManager in ws.js
    // Remove after 8s to give the user time to read the bubble
    setTimeout(() => this.removeAgent(crewId), 8000);
  }
}
