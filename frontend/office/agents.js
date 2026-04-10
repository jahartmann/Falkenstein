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
  typing:       'sit',
  reading:      'phone',
  thinking:     'idle_anim',
  running:      'run',
  // MCP tool animations
  mcp_reminder: 'phone',
  mcp_calendar: 'phone',
  mcp_music:    'idle_anim',
  mcp_homekit:  'sit',
  mcp_notes:    'sit',
  mcp_shell:    'sit',
  mcp_default:  'idle_anim',
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

// Weighted break activities for NPCs
const BREAK_ACTIVITIES = [
  { type: 'coffee',     weight: 3 },
  { type: 'chat',       weight: 2 },
  { type: 'stretch',    weight: 4 },
  { type: 'whiteboard', weight: 1 },
  { type: 'wander',     weight: 2 },
  { type: 'phone',      weight: 1 },
];

// Random idle thoughts shown in speech bubbles
const NPC_THOUGHTS = [
  'Hmm...', 'Interessant...', 'Fast fertig...',
  'Kurze Pause...', 'Noch ein Task...', 'Läuft gut!',
  'Coffee time ☕', 'Fokus...', 'Check!',
  'Fast da...', 'Gute Idee!', '...',
];

const STATUS_COLORS = {
  arriving: '#8ec5ff',
  working: '#44ff88',
  progress: '#8fe6ff',
  break: '#ffd36e',
  done: '#7cffc2',
  error: '#ff8f8f',
  leaving: '#c8ccd8',
  npc: '#d9d9d9',
};

export class AgentManager {
  constructor(scene, tilemapManager) {
    this.scene = scene;
    this.tm = tilemapManager;
    this.agents = new Map();
    this.occupiedTiles = new Set();
    this.bubbleManager = null; // set via setBubbleManager() after creation
  }

  setBubbleManager(bm) {
    this.bubbleManager = bm;
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
    const statusLabel = this._createStatusLabel(pos.x, pos.y, 'kommt an', STATUS_COLORS.arriving);

    const agent = {
      id: npcConfig.id,
      name: npcConfig.name,
      spriteName: npcConfig.sprite,
      agentType: null,
      sprite, label, statusLabel,
      indicator: null,
      desk,
      role: npcConfig.role,
      task: npcConfig.role,
      statusText: 'kommt an',
      tileX: spawnTile.x, tileY: spawnTile.y,
      state: 'walking_to_desk',
      path: null, pathIndex: 0, tweenActive: false,
      pauseTimer: null, breakCount: 0,
      thoughtTimer: null,
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
    const statusLabel = this._createStatusLabel(pos.x, pos.y, 'wartet', STATUS_COLORS.arriving);

    const agent = {
      id: agentId,
      name: displayName,
      spriteName: cfg.sprite,
      agentType: agentType,
      sprite, label, statusLabel, indicator,
      desk,
      role: agentType,
      task: taskText || '',
      statusText: 'wartet',
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
    this._setAgentStatus(agent, 'geht', STATUS_COLORS.leaving);
    this.scene.tweens.killTweensOf(agent.sprite);
    if (agent.indicator) this.scene.tweens.killTweensOf(agent.indicator);

    const entrance = this._findEntrance();
    this._walkTo(agent, entrance.x, entrance.y, () => {
      agent.sprite.destroy();
      if (agent.label) agent.label.destroy();
      if (agent.statusLabel) agent.statusLabel.destroy();
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
      if (agent.statusLabel) {
        agent.statusLabel.setPosition(agent.sprite.x, agent.sprite.y - 18);
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
    this._setAgentStatus(agent, 'arbeitet', STATUS_COLORS.working);
    // Occasionally show a "back to work" bubble
    if (agent.isNPC && Math.random() < 0.3) {
      const lines = ['Los geht\'s!', 'Back to work', 'Weiter...', 'Ok, los!'];
      this._showBubble(agent, lines[Math.floor(Math.random() * lines.length)], 2500);
    }
    this._schedulePause(agent);
    if (agent.isNPC) this._scheduleRandomThought(agent);
  }

  _schedulePause(agent) {
    if (agent.state !== 'working') return;
    let minDelay, extraDelay;
    if (agent.isNPC) {
      const hour = this._getSimHour();
      if (hour >= 8 && hour < 12) {
        // Morning: focused, longer gaps
        minDelay = 20000; extraDelay = 20000;
      } else if (hour >= 12 && hour < 14) {
        // Lunch: frequent short breaks
        minDelay = 8000; extraDelay = 17000;
      } else if (hour >= 17) {
        // Evening: winding down
        minDelay = 5000; extraDelay = 10000;
      } else {
        minDelay = 12000; extraDelay = 18000;
      }
    } else {
      minDelay = 25000; extraDelay = 20000;
    }
    const delay = minDelay + Math.random() * extraDelay;
    agent.pauseTimer = setTimeout(() => {
      if (agent.state !== 'working') return;
      this._goOnBreak(agent);
    }, delay);
  }

  _getSimHour() {
    // Map real time of day to a simulated office hour (8:00-22:00 range)
    return new Date().getHours();
  }

  _chooseBreakActivity() {
    const total = BREAK_ACTIVITIES.reduce((s, a) => s + a.weight, 0);
    let r = Math.random() * total;
    for (const a of BREAK_ACTIVITIES) {
      r -= a.weight;
      if (r <= 0) return a.type;
    }
    return 'stretch';
  }

  _goOnBreak(agent) {
    agent.state = 'on_break';
    agent.breakCount++;
    this._setAgentStatus(agent, 'pause', STATUS_COLORS.break);
    // Cancel random-thought timer while on break
    if (agent.thoughtTimer) { clearTimeout(agent.thoughtTimer); agent.thoughtTimer = null; }

    const activity = this._chooseBreakActivity();

    if (activity === 'stretch') {
      // Stand and stretch at desk — no walking
      agent.sprite.anims.play(`${agent.spriteName}_idle_down`, true);
      this._setAgentStatus(agent, 'stretch', STATUS_COLORS.break);
      this._showBubble(agent, 'Kurze Pause...', 3000);
      const dur = 3000 + Math.random() * 2000;
      setTimeout(() => {
        if (agent.state !== 'on_break') return;
        this._sitDown(agent);
      }, dur);
      return;
    }

    if (activity === 'phone') {
      // Phone call at desk
      agent.sprite.anims.play(`${agent.spriteName}_phone`, true);
      this._setAgentStatus(agent, 'telefoniert', STATUS_COLORS.break);
      this._showBubble(agent, 'Moment bitte...', 4000);
      setTimeout(() => {
        if (agent.state !== 'on_break') return;
        this._sitDown(agent);
      }, 4000 + Math.random() * 6000);
      return;
    }

    if (activity === 'chat') {
      // Walk to a colleague's desk and chat
      const colleague = this._findNearbyColleague(agent);
      if (colleague) {
        const offX = Math.floor(Math.random() * 3) - 1;
        const offY = Math.floor(Math.random() * 3) - 1;
        const tx = colleague.desk.tileX + offX;
        const ty = colleague.desk.tileY + offY;
        this._walkTo(agent, tx, ty, () => {
          agent.sprite.anims.play(`${agent.spriteName}_idle_down`, true);
          this._setAgentStatus(agent, 'kurzer Austausch', STATUS_COLORS.break);
          const chatLines = ['Kurze Frage...', 'Hast du kurz?', 'Hey!', 'Mal kurz...'];
          this._showBubble(agent, chatLines[Math.floor(Math.random() * chatLines.length)], 5000);
          // Colleague reacts
          if (colleague.state === 'working') {
            const replyLines = ['Klar!', 'Ja, kurz.', 'Gleich!'];
            setTimeout(() => {
              this._showBubble(colleague, replyLines[Math.floor(Math.random() * replyLines.length)], 3000);
            }, 1200);
          }
          const idleDur = 8000 + Math.random() * 7000;
          setTimeout(() => {
            if (agent.state !== 'on_break') return;
            this._walkTo(agent, agent.desk.tileX, agent.desk.tileY, () => {
              this._sitDown(agent);
            });
          }, idleDur);
        });
        return;
      }
      // No colleague found — fall through to wander
    }

    if (activity === 'coffee') {
      const room = this.tm.rooms.find(r => r.name === 'Küche');
      if (room) {
        const tx = room.centerX + Math.floor(Math.random() * 3) - 1;
        const ty = room.centerY + Math.floor(Math.random() * 3) - 1;
        this._walkTo(agent, tx, ty, () => {
          agent.sprite.anims.play(`${agent.spriteName}_idle_down`, true);
          this._setAgentStatus(agent, 'holt Kaffee', STATUS_COLORS.break);
          this._showBubble(agent, 'Erstmal Kaffee...', 4000);
          // Check for colleagues also in the kitchen and chat
          const buddy = this._findAgentInRoom(agent, 'Küche');
          if (buddy) {
            setTimeout(() => {
              this._showBubble(buddy, 'Auch Kaffee? ☕', 3000);
            }, 1500);
          }
          const dur = 6000 + Math.random() * 4000;
          setTimeout(() => {
            if (agent.state !== 'on_break') return;
            this._walkTo(agent, agent.desk.tileX, agent.desk.tileY, () => {
              this._sitDown(agent);
            });
          }, dur);
        });
        return;
      }
    }

    if (activity === 'whiteboard') {
      const room = this.tm.rooms.find(r => r.name === 'Gemeinschaftsraum');
      if (room) {
        const tx = room.centerX + Math.floor(Math.random() * 3) - 1;
        const ty = room.centerY + Math.floor(Math.random() * 3) - 1;
        this._walkTo(agent, tx, ty, () => {
          agent.sprite.anims.play(`${agent.spriteName}_idle_up`, true);
          this._setAgentStatus(agent, 'am Whiteboard', STATUS_COLORS.break);
          this._showBubble(agent, 'Hmm...', 3000);
          const dur = 5000 + Math.random() * 3000;
          setTimeout(() => {
            if (agent.state !== 'on_break') return;
            this._walkTo(agent, agent.desk.tileX, agent.desk.tileY, () => {
              this._sitDown(agent);
            });
          }, dur);
        });
        return;
      }
    }

    // 'wander' (and fallback for any failed activity above)
    const pauseRoom = PAUSE_ROOMS[Math.floor(Math.random() * PAUSE_ROOMS.length)];
    const room = this.tm.rooms.find(r => r.name === pauseRoom);
    if (!room) { this._sitDown(agent); return; }

    const targetX = room.centerX + Math.floor(Math.random() * 3) - 1;
    const targetY = room.centerY + Math.floor(Math.random() * 3) - 1;

    this._walkTo(agent, targetX, targetY, () => {
      agent.sprite.anims.play(`${agent.spriteName}_idle_down`, true);
      this._setAgentStatus(agent, 'dreht eine Runde', STATUS_COLORS.break);
      const idleDuration = 4000 + Math.random() * 8000;
      setTimeout(() => {
        if (agent.state !== 'on_break') return;
        this._walkTo(agent, agent.desk.tileX, agent.desk.tileY, () => {
          this._sitDown(agent);
        });
      }, idleDuration);
    });
  }

  /* ── NPC Thought Bubbles ── */

  _scheduleRandomThought(agent) {
    if (!agent.isNPC) return;
    if (agent.thoughtTimer) { clearTimeout(agent.thoughtTimer); agent.thoughtTimer = null; }
    const delay = 30000 + Math.random() * 30000;
    agent.thoughtTimer = setTimeout(() => {
      if (agent.state !== 'working') return;
      const thought = NPC_THOUGHTS[Math.floor(Math.random() * NPC_THOUGHTS.length)];
      this._showBubble(agent, thought, 3000);
      this._scheduleRandomThought(agent); // schedule next thought
    }, delay);
  }

  _showBubble(agent, message, duration) {
    if (!this.bubbleManager) return;
    this.bubbleManager.showBubble(agent.id, message);
    // Override the default 5s duration if shorter
    if (duration && duration < 5000) {
      const bubble = this.bubbleManager.bubbles.get(agent.id);
      if (bubble && bubble.timer) {
        bubble.timer.remove();
        bubble.timer = this.scene.time.delayedCall(duration, () => {
          this.bubbleManager.hideBubble(agent.id);
        });
      }
    }
  }

  /* ── NPC Colleague Helpers ── */

  _findNearbyColleague(agent) {
    // Find another NPC that is currently working (seated at their desk)
    for (const other of this.agents.values()) {
      if (other === agent || !other.isNPC) continue;
      if (other.state !== 'working') continue;
      if (other.desk) return other;
    }
    return null;
  }

  _findAgentInRoom(agent, roomName) {
    const room = this.tm.rooms.find(r => r.name === roomName);
    if (!room) return null;
    for (const other of this.agents.values()) {
      if (other === agent) continue;
      if (other.state !== 'on_break') continue;
      // Check if other is inside the room bounds
      if (
        other.tileX >= room.x - 1 && other.tileX <= room.x + room.width + 1 &&
        other.tileY >= room.y - 1 && other.tileY <= room.y + room.height + 1
      ) {
        return other;
      }
    }
    return null;
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

  _createStatusLabel(x, y, text, color) {
    const label = this.scene.add.text(x, y - 18, text, {
      fontSize: '8px', fontFamily: 'monospace',
      color: color, backgroundColor: '#00000099',
      padding: { x: 3, y: 1 },
    });
    label.setOrigin(0.5, 1);
    label.setDepth(19);
    return label;
  }

  _setAgentStatus(agent, text, color) {
    agent.statusText = text;
    if (agent.statusLabel) {
      agent.statusLabel.setText(text);
      agent.statusLabel.setColor(color);
    }
    if (agent.indicator) {
      const fill = Number.parseInt(String(color).replace('#', '0x'), 16);
      if (!Number.isNaN(fill)) {
        agent.indicator.setFillStyle(fill, 0.95);
      }
    }
  }

  _formatToolLabel(toolName) {
    const raw = String(toolName || '').replace(/^mcp_/, '').replace(/_/g, ' ').trim();
    if (!raw) return 'arbeitet';
    return raw.length > 20 ? raw.slice(0, 20) + '…' : raw;
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
    if (!agent) return;
    agent.task = text;
    this._setAgentStatus(agent, text, agent.isNPC ? STATUS_COLORS.npc : STATUS_COLORS.progress);
  }

  /* ── CrewAI EventBus Handlers ── */

  onAgentSpawn(crewType, crewId, task) {
    // Map crew type to agent type config, falling back to coder
    const agentType = AGENT_TYPE_CONFIG[crewType] ? crewType : 'coder';
    this.spawnAgent(crewId, agentType, task);
  }

  onToolUse(agentName, toolName, animation, crewId, statusLabel = '') {
    const agent = this.agents.get(crewId);
    if (!agent || agent.state === 'leaving') return;

    // MCP tool detection: override animHint with specific mcp key
    let animKey = animation;
    if (toolName && toolName.startsWith('mcp_')) {
      if (toolName.includes('reminder') || toolName.includes('calendar')) animKey = 'mcp_reminder';
      else if (toolName.includes('music')) animKey = 'mcp_music';
      else if (toolName.includes('homekit') || toolName.includes('light')) animKey = 'mcp_homekit';
      else if (toolName.includes('note')) animKey = 'mcp_notes';
      else if (toolName.includes('shell') || toolName.includes('command')) animKey = 'mcp_shell';
      else animKey = 'mcp_default';
    }

    // Map abstract animation name; fall back to sit (typing) if unknown
    const resolvedAnimKey = ANIMATION_MAP[animKey] || 'sit';

    if (resolvedAnimKey === 'sit') {
      agent.sprite.anims.play(`${agent.spriteName}_sit`, true);
    } else if (resolvedAnimKey === 'phone') {
      agent.sprite.anims.play(`${agent.spriteName}_phone`, true);
    } else if (resolvedAnimKey === 'idle_anim') {
      agent.sprite.anims.play(`${agent.spriteName}_idle_down`, true);
    } else if (resolvedAnimKey === 'run') {
      // No specific destination — play walk animation in place facing down
      agent.sprite.anims.play(`${agent.spriteName}_walk_down`, true);
    }

    agent.task = toolName || '';
    this._setAgentStatus(
      agent,
      statusLabel || this._formatToolLabel(toolName),
      STATUS_COLORS.progress,
    );
  }

  onAgentDone(crewType, crewId) {
    const agent = this.agents.get(crewId);
    if (!agent || agent.isNPC) return;

    // Play idle animation to signal completion, then remove after 5s
    agent.sprite.anims.play(`${agent.spriteName}_idle_down`, true);
    this._setAgentStatus(agent, 'fertig', STATUS_COLORS.done);
    setTimeout(() => this.removeAgent(crewId), 5000);
  }

  onAgentError(crewType, crewId, error) {
    const agent = this.agents.get(crewId);
    if (!agent || agent.isNPC) return;

    // Keep current position; error bubble is shown via BubbleManager in ws.js
    // Remove after 8s to give the user time to read the bubble
    this._setAgentStatus(agent, 'fehler', STATUS_COLORS.error);
    setTimeout(() => this.removeAgent(crewId), 8000);
  }
}
