# Pixel-Büro Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Interactive Phaser.js pixel office that visualizes agents as characters walking through a Tiled office map, with interactive objects (whiteboard, monitors, schedule board, etc.) showing live backend data.

**Architecture:** Single-page Phaser 3 app (`office.html`) loaded in a new tab via dashboard sidebar button. Phaser renders the Tiled map with multiple layers, player character with hybrid controls (WASD + zoom), and NPC agents managed via WebSocket events. UI overlays (HUD, popups) are DOM-based in a parallel Phaser scene. A* pathfinding on the Blocked layer drives agent movement.

**Tech Stack:** Phaser 3.80 (CDN), vanilla JS (ES modules), existing FastAPI backend + WebSocket `/ws`, existing Tiled assets (48px tiles, 16×16 character sprites)

**Spec:** `docs/superpowers/specs/2026-04-04-pixel-office-design.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `frontend/office.html` | Standalone HTML page, loads Phaser CDN + all JS modules, HUD/panel DOM |
| `frontend/office/boot.js` | BootScene: preloads all assets (tilesets, spritesheets, map JSON) |
| `frontend/office/tilemap.js` | TilemapManager: creates layers from TMJ, extracts collision grid + room/desk data |
| `frontend/office/player.js` | PlayerEntity: sprite, WASD input, camera follow, interaction proximity |
| `frontend/office/camera.js` | CameraManager: hybrid zoom (scroll wheel), click-to-move in zoomed-out mode |
| `frontend/office/pathfinding.js` | A* implementation on tile grid, path caching |
| `frontend/office/agents.js` | AgentManager: spawn/remove agents, assign desks, drive walk + sit + pause behavior |
| `frontend/office/bubbles.js` | BubbleManager: speech bubbles above agent sprites |
| `frontend/office/objects.js` | ObjectManager: interactive object registry, proximity detection, highlight |
| `frontend/office/panels.js` | PanelManager: DOM-based popup panels (open/close, content rendering) |
| `frontend/office/hud.js` | HUD bar + minimap rendering |
| `frontend/office/ws.js` | WebSocket connection, event dispatch to managers |
| `frontend/office/main.js` | Game config, scene creation, wiring everything together |
| `frontend/office.css` | All HUD, panel, bubble styling |
| `backend/main.py` | Add `GET /office` route (1 line) |
| `frontend/dashboard.html` | Add sidebar button that opens `/office` in new tab |
| `frontend/dashboard.js` | (No changes needed — sidebar button is pure HTML) |

---

## Task 1: Project Scaffolding — HTML, CSS, Game Shell

**Files:**
- Create: `frontend/office.html`
- Create: `frontend/office.css`
- Create: `frontend/office/main.js`
- Modify: `backend/main.py:180-189` (add `/office` route)
- Modify: `frontend/dashboard.html:21-31` (add sidebar button)

- [ ] **Step 1: Add `/office` route in backend**

In `backend/main.py`, add a new route before the root route (before line 180):

```python
@app.get("/office")
async def office():
    office_path = frontend_dir / "office.html"
    if office_path.exists():
        return FileResponse(office_path)
    return {"error": "office.html not found"}
```

- [ ] **Step 2: Add sidebar button in dashboard.html**

In `frontend/dashboard.html`, after the schedules button (after line 30, before `</div><!-- sidebar-top -->`), add:

```html
<button class="sidebar-btn" title="Büro" onclick="window.open('/office','_blank')">
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5">
    <rect x="2" y="4" width="16" height="13" rx="1.5"/><path d="M6 4V2h8v2"/><circle cx="10" cy="10" r="2"/>
  </svg>
</button>
```

- [ ] **Step 3: Create office.css**

Create `frontend/office.css`:

```css
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { width: 100%; height: 100%; overflow: hidden; background: #1a1a2e; }

#game-container { width: 100%; height: 100%; position: relative; }
#game-container canvas { display: block; }

/* HUD top bar */
.hud-bar {
  position: fixed; top: 0; left: 0; right: 0; height: 36px; z-index: 100;
  background: rgba(16,16,32,0.85); border-bottom: 2px solid #2a2a4a;
  display: flex; align-items: center; padding: 0 16px; gap: 24px;
  font-family: 'Courier New', monospace; font-size: 13px; color: #c8c8e0;
  pointer-events: auto;
}
.hud-bar .hud-label { color: #8888aa; font-size: 11px; text-transform: uppercase; margin-right: 4px; }
.hud-bar .hud-value { color: #e0e0ff; font-weight: bold; }
.hud-bar .hud-title { font-weight: bold; color: #7b7bff; font-size: 14px; margin-right: 16px; }
.hud-bar .hud-spacer { flex: 1; }
.hud-dot { width: 8px; height: 8px; border-radius: 50%; background: #ff4444; display: inline-block; margin-right: 4px; }
.hud-dot.connected { background: #44ff88; }

/* Minimap */
.minimap {
  position: fixed; bottom: 12px; right: 12px; z-index: 100;
  width: 180px; height: 144px;
  background: rgba(16,16,32,0.9); border: 2px solid #2a2a4a; border-radius: 4px;
  pointer-events: auto; cursor: pointer;
}
.minimap canvas { width: 100%; height: 100%; image-rendering: pixelated; }

/* Popup panels */
.panel-overlay {
  position: fixed; inset: 0; z-index: 200;
  background: rgba(0,0,0,0.5);
  display: flex; align-items: center; justify-content: center;
  pointer-events: auto;
}
.panel-overlay.hidden { display: none; }
.panel-box {
  background: #1e1e3a; border: 3px solid #4a4a7a; border-radius: 8px;
  min-width: 400px; max-width: 700px; max-height: 80vh; overflow-y: auto;
  padding: 20px; color: #c8c8e0; font-family: 'Courier New', monospace; font-size: 13px;
  image-rendering: pixelated;
}
.panel-box h2 { color: #9b9bff; font-size: 16px; margin-bottom: 12px; border-bottom: 1px solid #3a3a5a; padding-bottom: 8px; }
.panel-close {
  position: absolute; top: 8px; right: 12px; background: none; border: none;
  color: #8888aa; font-size: 20px; cursor: pointer;
}
.panel-close:hover { color: #ff6666; }

/* Kanban board */
.kanban { display: flex; gap: 12px; }
.kanban-col { flex: 1; min-width: 0; }
.kanban-col h3 { font-size: 12px; color: #8888aa; text-transform: uppercase; margin-bottom: 8px; }
.kanban-card {
  background: #2a2a4a; border-left: 3px solid #4a4a7a; border-radius: 4px;
  padding: 8px; margin-bottom: 6px; font-size: 12px;
}
.kanban-card.status-open { border-left-color: #6688ff; }
.kanban-card.status-in_progress { border-left-color: #ffaa44; }
.kanban-card.status-done { border-left-color: #44ff88; }
.kanban-card.status-failed { border-left-color: #ff4444; }
.kanban-card .card-title { color: #e0e0ff; margin-bottom: 4px; }
.kanban-card .card-agent { color: #8888aa; font-size: 11px; }

/* Schedule board */
.schedule-list { list-style: none; }
.schedule-list li {
  display: flex; justify-content: space-between; align-items: center;
  padding: 8px; border-bottom: 1px solid #2a2a4a;
}
.schedule-list .sched-name { color: #e0e0ff; }
.schedule-list .sched-time { color: #ffaa44; font-size: 12px; }
.schedule-list .sched-agent { color: #8888aa; font-size: 11px; }

/* Coffee receipt */
.coffee-receipt {
  font-family: 'Courier New', monospace; background: #f5f0e0; color: #333;
  padding: 16px; border-radius: 2px; text-align: center; max-width: 260px; margin: 0 auto;
}
.coffee-receipt h3 { font-size: 14px; margin-bottom: 8px; }
.coffee-receipt .receipt-line { display: flex; justify-content: space-between; padding: 2px 0; font-size: 12px; }
.coffee-receipt hr { border: none; border-top: 1px dashed #999; margin: 8px 0; }

/* Interaction hint */
.interact-hint {
  position: fixed; bottom: 48px; left: 50%; transform: translateX(-50%); z-index: 100;
  background: rgba(16,16,32,0.9); border: 1px solid #4a4a7a; border-radius: 4px;
  padding: 6px 16px; color: #c8c8e0; font-family: 'Courier New', monospace; font-size: 12px;
  pointer-events: none; transition: opacity 0.2s;
}
.interact-hint.hidden { opacity: 0; }
```

- [ ] **Step 4: Create office.html**

Create `frontend/office.html`:

```html
<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Falkenstein — Büro</title>
  <link rel="stylesheet" href="/static/office.css">
</head>
<body>
  <div id="game-container"></div>

  <!-- HUD -->
  <div class="hud-bar">
    <span class="hud-title">Falkenstein Büro</span>
    <span class="hud-label">Agents</span><span class="hud-value" id="hud-agents">0</span>
    <span class="hud-label">Tasks</span><span class="hud-value" id="hud-tasks">0</span>
    <span class="hud-label">Schedules</span><span class="hud-value" id="hud-schedules">0</span>
    <span class="hud-spacer"></span>
    <span class="hud-label">Zoom</span><span class="hud-value" id="hud-zoom">1.0x</span>
    <span class="hud-dot" id="hud-ws" title="WebSocket"></span>
  </div>

  <!-- Minimap -->
  <div class="minimap" id="minimap">
    <canvas id="minimap-canvas" width="180" height="144"></canvas>
  </div>

  <!-- Panel overlay -->
  <div class="panel-overlay hidden" id="panel-overlay" onclick="if(event.target===this)window.panelManager?.close()">
    <div class="panel-box" id="panel-content" style="position:relative;"></div>
  </div>

  <!-- Interaction hint -->
  <div class="interact-hint hidden" id="interact-hint">[E] Interagieren</div>

  <script src="https://cdn.jsdelivr.net/npm/phaser@3.80.1/dist/phaser.min.js"></script>
  <script type="module" src="/static/office/main.js"></script>
</body>
</html>
```

- [ ] **Step 5: Create main.js game shell**

Create `frontend/office/main.js`:

```javascript
// Pixel Office — Main entry point
import { BootScene } from './boot.js';
import { OfficeScene } from './tilemap.js';

const config = {
  type: Phaser.CANVAS,
  parent: 'game-container',
  width: window.innerWidth,
  height: window.innerHeight,
  pixelArt: true,
  roundPixels: true,
  backgroundColor: '#1a1a2e',
  physics: {
    default: 'arcade',
    arcade: { gravity: { y: 0 }, debug: false }
  },
  scene: [BootScene, OfficeScene],
  scale: {
    mode: Phaser.Scale.RESIZE,
    autoCenter: Phaser.Scale.CENTER_BOTH
  }
};

const game = new Phaser.Game(config);

window.addEventListener('resize', () => {
  game.scale.resize(window.innerWidth, window.innerHeight);
});
```

- [ ] **Step 6: Create placeholder BootScene and OfficeScene so the game starts**

Create `frontend/office/boot.js`:

```javascript
export class BootScene extends Phaser.Scene {
  constructor() { super('Boot'); }

  preload() {
    // Assets loaded in later tasks
    this.load.on('complete', () => this.scene.start('Office'));
  }

  create() {
    // If no assets to load, start immediately
    if (this.load.totalComplete === this.load.totalToLoad) {
      this.scene.start('Office');
    }
  }
}
```

Create initial `frontend/office/tilemap.js` (placeholder OfficeScene):

```javascript
export class OfficeScene extends Phaser.Scene {
  constructor() { super('Office'); }

  create() {
    this.add.text(400, 300, 'Falkenstein Büro', {
      fontSize: '24px', color: '#9b9bff', fontFamily: 'Courier New'
    }).setOrigin(0.5);
  }
}
```

- [ ] **Step 7: Verify the game loads**

Open `http://localhost:8080/office` in browser. Should see dark background with "Falkenstein Büro" text and the HUD bar on top.

- [ ] **Step 8: Commit**

```bash
git add frontend/office.html frontend/office.css frontend/office/main.js frontend/office/boot.js frontend/office/tilemap.js backend/main.py frontend/dashboard.html
git commit -m "feat(office): scaffold pixel office with Phaser shell, route, sidebar button"
```

---

## Task 2: Tilemap Loading & Rendering

**Files:**
- Modify: `frontend/office/boot.js` (load tilesets + map JSON)
- Rewrite: `frontend/office/tilemap.js` (full TilemapManager + OfficeScene)

- [ ] **Step 1: Update BootScene to load all tileset images and the map JSON**

Replace `frontend/office/boot.js`:

```javascript
const TILESETS = [
  { key: 'tiles_room', url: '/static/assets/Room_Builder_Office_48x48.png' },
  { key: 'tiles_shadow', url: '/static/assets/Modern_Office_Black_Shadow.png' },
  { key: 'tiles_shadow48', url: '/static/assets/Modern_Office_Black_Shadow_48x48.png' },
];

const CHARACTERS = ['Adam', 'Alex', 'Amelia', 'Bob'];
const CHAR_ANIMS = ['idle_anim', 'run', 'sit', 'phone'];

export class BootScene extends Phaser.Scene {
  constructor() { super('Boot'); }

  preload() {
    // Progress bar
    const bar = this.add.rectangle(
      this.scale.width / 2, this.scale.height / 2, 300, 20, 0x2a2a4a
    );
    const fill = this.add.rectangle(
      this.scale.width / 2 - 148, this.scale.height / 2, 4, 16, 0x7b7bff
    ).setOrigin(0, 0.5);
    this.load.on('progress', (v) => { fill.width = 296 * v; });

    // Map JSON
    this.load.json('office-map', '/static/assets/office.tmj');

    // Tilesets
    for (const ts of TILESETS) {
      this.load.image(ts.key, ts.url);
    }

    // Character spritesheets (16x16 frames)
    for (const name of CHARACTERS) {
      for (const anim of CHAR_ANIMS) {
        const key = `${name}_${anim}`;
        const url = `/static/assets/characters/${name}_${anim}_16x16.png`;
        const fw = 16, fh = 16;
        this.load.spritesheet(key, url, { frameWidth: fw, frameHeight: fh });
      }
    }

    // Generic char sheets (7 cols x 6 rows, 16x16)
    for (let i = 0; i <= 5; i++) {
      this.load.spritesheet(`char_${i}`, `/static/assets/characters/char_${i}.png`, {
        frameWidth: 16, frameHeight: 16
      });
    }
  }

  create() {
    this.scene.start('Office');
  }
}
```

- [ ] **Step 2: Write TilemapManager and OfficeScene to render the map**

Replace `frontend/office/tilemap.js`:

```javascript
// TMJ tileset name → loaded image key
const TILESET_MAP = {
  'Room_Builder_Office_48x48': 'tiles_room',
  'Modern_Office_Black_Shadow': 'tiles_shadow',
  'Modern_Office_Black_Shadow_48x48': 'tiles_shadow48',
};

const TILE_LAYERS = ['Walkable', 'Blocked', 'Furniture', 'WalkableFurniture', 'Stühle'];

export class TilemapManager {
  constructor(scene) {
    this.scene = scene;
    this.map = null;
    this.layers = {};
    this.collisionGrid = null; // 2D array for pathfinding: 0=walkable, 1=blocked
    this.rooms = [];           // {name, x, y, width, height} from "Benamung" layer
    this.desks = [];           // {x, y, width, height} from "Arbeitsplätze" layer
  }

  create() {
    const mapData = this.scene.cache.json.get('office-map');

    // Create tilemap from JSON data
    this.map = this.scene.make.tilemap({ key: 'office-map-parsed', data: null });

    // We need to manually build the map since TMJ paths don't match
    this.map = this.scene.make.tilemap({
      tileWidth: 48, tileHeight: 48,
      width: mapData.width, height: mapData.height
    });

    // Actually, use Phaser's JSON map support by adding it properly
    // Parse the TMJ as a Tiled JSON map
    const parsed = Phaser.Tilemaps.Parsers.Tiled.ParseJSONTiled(
      'office-map', mapData, false
    );
    this.map = new Phaser.Tilemaps.Tilemap(this.scene, parsed);

    // Add tilesets with correct image keys
    for (const ts of mapData.tilesets) {
      const imageKey = TILESET_MAP[ts.name];
      if (imageKey) {
        this.map.addTilesetImage(ts.name, imageKey);
      }
    }

    const allTilesets = this.map.tilesets.map(t => t.name);

    // Create tile layers
    for (const name of TILE_LAYERS) {
      const layer = this.map.createLayer(name, allTilesets, 0, 0);
      if (layer) {
        this.layers[name] = layer;
        // Blocked layer gets collision
        if (name === 'Blocked') {
          layer.setCollisionByExclusion([-1, 0]);
        }
      }
    }

    // Extract collision grid for pathfinding
    this._buildCollisionGrid(mapData);

    // Extract rooms from "Benamung" object layer
    this._extractRooms(mapData);

    // Extract desk positions from "Arbeitsplätze" object layer
    this._extractDesks(mapData);

    return this;
  }

  _buildCollisionGrid(mapData) {
    const w = mapData.width;
    const h = mapData.height;
    this.collisionGrid = Array.from({ length: h }, () => new Uint8Array(w));

    // Find the Blocked layer data
    const blockedLayer = mapData.layers.find(l => l.name === 'Blocked');
    if (!blockedLayer) return;

    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const tileId = blockedLayer.data[y * w + x];
        if (tileId > 0) {
          this.collisionGrid[y][x] = 1;
        }
      }
    }

    // Also check Walkable layer — tiles with 0 are non-walkable (void)
    const walkLayer = mapData.layers.find(l => l.name === 'Walkable');
    if (walkLayer) {
      for (let y = 0; y < h; y++) {
        for (let x = 0; x < w; x++) {
          if (walkLayer.data[y * w + x] === 0 && this.collisionGrid[y][x] === 0) {
            // No walkable tile and no blocked tile = void/outside
            this.collisionGrid[y][x] = 1;
          }
        }
      }
    }
  }

  _extractRooms(mapData) {
    const layer = mapData.layers.find(l => l.name === 'Benamung');
    if (!layer || !layer.objects) return;
    this.rooms = layer.objects.map(obj => ({
      name: obj.name.trim(),
      x: Math.floor(obj.x / 48),
      y: Math.floor(obj.y / 48),
      width: Math.ceil(obj.width / 48),
      height: Math.ceil(obj.height / 48),
      centerX: Math.floor((obj.x + obj.width / 2) / 48),
      centerY: Math.floor((obj.y + obj.height / 2) / 48),
    }));
  }

  _extractDesks(mapData) {
    const layer = mapData.layers.find(l => l.name === 'Arbeitsplätze');
    if (!layer || !layer.objects) return;
    this.desks = layer.objects.map(obj => ({
      tileX: Math.floor(obj.x / 48),
      tileY: Math.floor(obj.y / 48),
      occupied: false,
      agentId: null,
    }));
  }

  /** Get pixel coords for a tile position */
  tileToWorld(tileX, tileY) {
    return { x: tileX * 48 + 24, y: tileY * 48 + 24 };
  }

  /** Get tile coords from pixel position */
  worldToTile(worldX, worldY) {
    return { x: Math.floor(worldX / 48), y: Math.floor(worldY / 48) };
  }

  /** Get the world bounds in pixels */
  getWorldBounds() {
    return {
      width: this.map.widthInPixels,
      height: this.map.heightInPixels
    };
  }
}

export class OfficeScene extends Phaser.Scene {
  constructor() { super('Office'); }

  create() {
    // Create tilemap
    this.tilemap = new TilemapManager(this);
    this.tilemap.create();

    // Set world bounds
    const bounds = this.tilemap.getWorldBounds();
    this.physics.world.setBounds(0, 0, bounds.width, bounds.height);

    // Set camera bounds and initial position
    this.cameras.main.setBounds(0, 0, bounds.width, bounds.height);
    this.cameras.main.setZoom(1);

    // Center camera on map
    this.cameras.main.centerOn(bounds.width / 2, bounds.height / 2);
  }
}
```

- [ ] **Step 3: Verify tilemap renders**

Open `http://localhost:8080/office`. The full Tiled office map should render with all layers (floor, walls, furniture). Pan around by temporarily adding keyboard controls or just check the centered view shows the map.

- [ ] **Step 4: Commit**

```bash
git add frontend/office/boot.js frontend/office/tilemap.js
git commit -m "feat(office): load and render Tiled office map with all layers"
```

---

## Task 3: Player Character & WASD Movement

**Files:**
- Create: `frontend/office/player.js`
- Modify: `frontend/office/tilemap.js` (wire player into OfficeScene)

- [ ] **Step 1: Create PlayerEntity**

Create `frontend/office/player.js`:

```javascript
const SPEED = 160;

export class PlayerEntity {
  constructor(scene, tilemapManager) {
    this.scene = scene;
    this.tm = tilemapManager;
    this.sprite = null;
    this.cursors = null;
    this.wasd = null;
    this.interactKey = null;
    this.facing = 'down';
  }

  create(startTileX, startTileY) {
    const pos = this.tm.tileToWorld(startTileX, startTileY);

    // Create sprite using char_1 (player character)
    this.sprite = this.scene.physics.add.sprite(pos.x, pos.y, 'char_1', 0);
    this.sprite.setScale(3);
    this.sprite.setDepth(10);
    this.sprite.body.setSize(12, 12);
    this.sprite.body.setOffset(2, 4);
    this.sprite.setCollideWorldBounds(true);

    // Collide with Blocked layer
    const blockedLayer = this.tm.layers['Blocked'];
    if (blockedLayer) {
      this.scene.physics.add.collider(this.sprite, blockedLayer);
    }

    // Create animations from char_1 spritesheet (7 cols x 6 rows)
    // Row layout: down(0-2), left(7-9), right(14-16), up(21-23) + idle variants
    this._createAnimations();

    // Input
    this.cursors = this.scene.input.keyboard.createCursorKeys();
    this.wasd = this.scene.input.keyboard.addKeys({
      up: Phaser.Input.Keyboard.KeyCodes.W,
      down: Phaser.Input.Keyboard.KeyCodes.S,
      left: Phaser.Input.Keyboard.KeyCodes.A,
      right: Phaser.Input.Keyboard.KeyCodes.D,
    });
    this.interactKey = this.scene.input.keyboard.addKey(Phaser.Input.Keyboard.KeyCodes.E);

    // Camera follow
    this.scene.cameras.main.startFollow(this.sprite, true, 0.1, 0.1);

    return this;
  }

  _createAnimations() {
    const anims = this.scene.anims;
    // char_1 layout: 7 columns, 6 rows
    // Row 0: walk down (frames 0,1,2), Row 1: walk left, Row 2: walk right, Row 3: walk up
    // Idle = frame 1 of each direction (standing still middle frame)
    const directions = [
      { name: 'down', row: 0 },
      { name: 'left', row: 1 },
      { name: 'right', row: 2 },
      { name: 'up', row: 3 },
    ];

    for (const dir of directions) {
      const start = dir.row * 7;
      if (!anims.exists(`player_walk_${dir.name}`)) {
        anims.create({
          key: `player_walk_${dir.name}`,
          frames: anims.generateFrameNumbers('char_1', { start: start, end: start + 2 }),
          frameRate: 8,
          repeat: -1
        });
      }
      if (!anims.exists(`player_idle_${dir.name}`)) {
        anims.create({
          key: `player_idle_${dir.name}`,
          frames: [{ key: 'char_1', frame: start + 1 }],
          frameRate: 1,
          repeat: 0
        });
      }
    }
  }

  update() {
    if (!this.sprite || !this.sprite.body) return;

    const left = this.cursors.left.isDown || this.wasd.left.isDown;
    const right = this.cursors.right.isDown || this.wasd.right.isDown;
    const up = this.cursors.up.isDown || this.wasd.up.isDown;
    const down = this.cursors.down.isDown || this.wasd.down.isDown;

    let vx = 0, vy = 0;
    if (left) { vx = -SPEED; this.facing = 'left'; }
    else if (right) { vx = SPEED; this.facing = 'right'; }
    if (up) { vy = -SPEED; this.facing = 'up'; }
    else if (down) { vy = SPEED; this.facing = 'down'; }

    // Normalize diagonal
    if (vx !== 0 && vy !== 0) {
      vx *= 0.707;
      vy *= 0.707;
    }

    this.sprite.body.setVelocity(vx, vy);

    if (vx !== 0 || vy !== 0) {
      this.sprite.anims.play(`player_walk_${this.facing}`, true);
    } else {
      this.sprite.anims.play(`player_idle_${this.facing}`, true);
    }
  }

  /** Check if E key was just pressed */
  justInteracted() {
    return Phaser.Input.Keyboard.JustDown(this.interactKey);
  }

  getTilePos() {
    return this.tm.worldToTile(this.sprite.x, this.sprite.y);
  }

  getWorldPos() {
    return { x: this.sprite.x, y: this.sprite.y };
  }
}
```

- [ ] **Step 2: Wire player into OfficeScene**

In `frontend/office/tilemap.js`, add at the top:

```javascript
import { PlayerEntity } from './player.js';
```

Update `OfficeScene.create()` to add after camera bounds setup:

```javascript
  create() {
    // Create tilemap
    this.tilemap = new TilemapManager(this);
    this.tilemap.create();

    // Set world bounds
    const bounds = this.tilemap.getWorldBounds();
    this.physics.world.setBounds(0, 0, bounds.width, bounds.height);
    this.cameras.main.setBounds(0, 0, bounds.width, bounds.height);
    this.cameras.main.setZoom(1);

    // Find a walkable spawn point (center of map or first room)
    const spawnRoom = this.tilemap.rooms.find(r => r.name === 'Gemeinschaftsraum')
      || this.tilemap.rooms[0];
    const spawnX = spawnRoom ? spawnRoom.centerX : 30;
    const spawnY = spawnRoom ? spawnRoom.centerY : 24;

    // Create player
    this.player = new PlayerEntity(this, this.tilemap);
    this.player.create(spawnX, spawnY);
  }

  update(time, delta) {
    if (this.player) this.player.update();
  }
```

- [ ] **Step 3: Verify player movement**

Open `/office`. Player character should appear and move with WASD/arrow keys. Camera follows. Player collides with walls.

- [ ] **Step 4: Commit**

```bash
git add frontend/office/player.js frontend/office/tilemap.js
git commit -m "feat(office): player character with WASD movement and wall collision"
```

---

## Task 4: Hybrid Camera — Zoom & Click-to-Move

**Files:**
- Create: `frontend/office/camera.js`
- Modify: `frontend/office/tilemap.js` (wire camera manager)

- [ ] **Step 1: Create CameraManager**

Create `frontend/office/camera.js`:

```javascript
const MIN_ZOOM = 0.4;
const MAX_ZOOM = 2.0;
const ZOOM_STEP = 0.1;
const CLICK_MODE_THRESHOLD = 0.8; // Below this zoom, click-to-move activates

export class CameraManager {
  constructor(scene, player) {
    this.scene = scene;
    this.player = player;
    this.zoom = 1.0;
    this.isFollowing = true;
  }

  create() {
    const cam = this.scene.cameras.main;

    // Mouse wheel zoom
    this.scene.input.on('wheel', (pointer, gameObjects, deltaX, deltaY) => {
      if (deltaY > 0) {
        this.zoom = Math.max(MIN_ZOOM, this.zoom - ZOOM_STEP);
      } else {
        this.zoom = Math.min(MAX_ZOOM, this.zoom + ZOOM_STEP);
      }
      cam.setZoom(this.zoom);
      this._updateFollowMode();
      this._updateHUD();
    });

    // Click-to-move camera in zoomed-out mode
    this.scene.input.on('pointerdown', (pointer) => {
      if (this.zoom >= CLICK_MODE_THRESHOLD) return;
      if (pointer.rightButtonDown()) return;

      // Convert screen coords to world coords
      const worldPoint = cam.getWorldPoint(pointer.x, pointer.y);

      // Pan camera to clicked position
      cam.stopFollow();
      this.isFollowing = false;
      cam.pan(worldPoint.x, worldPoint.y, 400, 'Sine.easeInOut', false, (cam, progress) => {
        if (progress === 1) {
          // Stay at position, user can click again or zoom in
        }
      });
    });

    // Double-click to re-center on player
    this.scene.input.on('pointerdown', (pointer) => {
      if (pointer.leftButtonDown() && Date.now() - (this._lastClick || 0) < 300) {
        this._snapToPlayer();
      }
      this._lastClick = Date.now();
    });

    // Space to snap back to player
    this.scene.input.keyboard.on('keydown-SPACE', () => {
      if (!this.isFollowing) {
        this._snapToPlayer();
      }
    });

    this._updateHUD();
    return this;
  }

  _snapToPlayer() {
    const cam = this.scene.cameras.main;
    const pos = this.player.getWorldPos();
    cam.pan(pos.x, pos.y, 300, 'Sine.easeInOut', false, () => {
      cam.startFollow(this.player.sprite, true, 0.1, 0.1);
      this.isFollowing = true;
    });
    this.zoom = 1.0;
    cam.zoomTo(1.0, 300);
    this._updateHUD();
  }

  _updateFollowMode() {
    const cam = this.scene.cameras.main;
    if (this.zoom >= CLICK_MODE_THRESHOLD && !this.isFollowing) {
      cam.startFollow(this.player.sprite, true, 0.1, 0.1);
      this.isFollowing = true;
    }
  }

  _updateHUD() {
    const el = document.getElementById('hud-zoom');
    if (el) el.textContent = this.zoom.toFixed(1) + 'x';
  }
}
```

- [ ] **Step 2: Wire CameraManager into OfficeScene**

In `frontend/office/tilemap.js`, add import:

```javascript
import { CameraManager } from './camera.js';
```

In `OfficeScene.create()`, after player creation:

```javascript
    // Camera manager (hybrid zoom)
    this.cameraManager = new CameraManager(this, this.player);
    this.cameraManager.create();
```

- [ ] **Step 3: Verify zoom and click-to-move**

Scroll mouse wheel to zoom out. Below 0.8x zoom, clicking pans the camera. Double-click or Space to snap back to player. Zoom in returns to follow mode.

- [ ] **Step 4: Commit**

```bash
git add frontend/office/camera.js frontend/office/tilemap.js
git commit -m "feat(office): hybrid camera with zoom, click-to-pan, snap-to-player"
```

---

## Task 5: A* Pathfinding

**Files:**
- Create: `frontend/office/pathfinding.js`

- [ ] **Step 1: Implement A* pathfinder**

Create `frontend/office/pathfinding.js`:

```javascript
/**
 * A* pathfinding on a 2D grid.
 * Grid: 0 = walkable, 1 = blocked.
 * Returns array of {x, y} tile positions from start to end (inclusive), or null if no path.
 */

class MinHeap {
  constructor() { this.data = []; }
  push(node) {
    this.data.push(node);
    this._bubbleUp(this.data.length - 1);
  }
  pop() {
    const top = this.data[0];
    const last = this.data.pop();
    if (this.data.length > 0) {
      this.data[0] = last;
      this._sinkDown(0);
    }
    return top;
  }
  get size() { return this.data.length; }
  _bubbleUp(i) {
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (this.data[i].f >= this.data[p].f) break;
      [this.data[i], this.data[p]] = [this.data[p], this.data[i]];
      i = p;
    }
  }
  _sinkDown(i) {
    const n = this.data.length;
    while (true) {
      let min = i;
      const l = 2 * i + 1, r = 2 * i + 2;
      if (l < n && this.data[l].f < this.data[min].f) min = l;
      if (r < n && this.data[r].f < this.data[min].f) min = r;
      if (min === i) break;
      [this.data[i], this.data[min]] = [this.data[min], this.data[i]];
      i = min;
    }
  }
}

const DIRS = [
  { dx: 0, dy: -1 }, { dx: 0, dy: 1 }, { dx: -1, dy: 0 }, { dx: 1, dy: 0 },
];

export function findPath(grid, startX, startY, endX, endY, dynamicBlocked = null) {
  const h = grid.length;
  const w = grid[0].length;

  if (startX < 0 || startX >= w || startY < 0 || startY >= h) return null;
  if (endX < 0 || endX >= w || endY < 0 || endY >= h) return null;
  if (grid[endY][endX] === 1) return null;

  const key = (x, y) => y * w + x;
  const heuristic = (x, y) => Math.abs(x - endX) + Math.abs(y - endY);

  const open = new MinHeap();
  const gScore = new Map();
  const cameFrom = new Map();

  const startKey = key(startX, startY);
  gScore.set(startKey, 0);
  open.push({ x: startX, y: startY, f: heuristic(startX, startY) });

  while (open.size > 0) {
    const curr = open.pop();
    const ck = key(curr.x, curr.y);

    if (curr.x === endX && curr.y === endY) {
      // Reconstruct path
      const path = [];
      let k = ck;
      while (k !== undefined) {
        const py = Math.floor(k / w);
        const px = k % w;
        path.unshift({ x: px, y: py });
        k = cameFrom.get(k);
      }
      return path;
    }

    const currG = gScore.get(ck);

    for (const dir of DIRS) {
      const nx = curr.x + dir.dx;
      const ny = curr.y + dir.dy;
      if (nx < 0 || nx >= w || ny < 0 || ny >= h) continue;
      if (grid[ny][nx] === 1) continue;

      const nk = key(nx, ny);
      // Check dynamic blocked tiles (other agents)
      if (dynamicBlocked && dynamicBlocked.has(nk) && nk !== key(endX, endY)) continue;

      const ng = currG + 1;
      if (!gScore.has(nk) || ng < gScore.get(nk)) {
        gScore.set(nk, ng);
        cameFrom.set(nk, ck);
        open.push({ x: nx, y: ny, f: ng + heuristic(nx, ny) });
      }
    }
  }

  return null; // No path found
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/office/pathfinding.js
git commit -m "feat(office): A* pathfinding on tile grid"
```

---

## Task 6: Agent Manager — Spawn, Walk, Sit

**Files:**
- Create: `frontend/office/agents.js`
- Modify: `frontend/office/tilemap.js` (wire agent manager)

- [ ] **Step 1: Create AgentManager**

Create `frontend/office/agents.js`:

```javascript
import { findPath } from './pathfinding.js';

// Agent type → character sprite, target room
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
    this.agents = new Map(); // agentId → AgentEntity
    this.occupiedTiles = new Set(); // tile keys for pathfinding avoidance
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
      // idle_anim: 384x32, 16x16 frames = 24 frames in 2 rows (12 per row)
      // We use first row (frames 0-11) — 3 frames per direction: down(0-2), left(3-5), right(6-8), up(9-11)
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
      // Sit animation (static frame)
      if (!anims.exists(`${type}_sit`)) {
        anims.create({
          key: `${type}_sit`,
          frames: [{ key: `${name}_sit`, frame: 0 }],
          frameRate: 1, repeat: 0
        });
      }
      // Phone animation
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

    // Find spawn point (bottom of map, a walkable tile near entrance)
    const spawnTile = this._findEntrance();

    // Find target desk
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
      id: agentId,
      type: agentType,
      task: taskText || '',
      sprite,
      config: cfg,
      desk,
      tileX: spawnTile.x,
      tileY: spawnTile.y,
      state: 'walking_to_desk', // walking_to_desk | working | on_break | leaving
      path: null,
      pathIndex: 0,
      tweenActive: false,
      pauseTimer: null,
      breakCount: 0,
    };

    this.agents.set(agentId, agent);
    this._walkTo(agent, desk.tileX, desk.tileY, () => {
      this._sitDown(agent);
    });
  }

  removeAgent(agentId) {
    const agent = this.agents.get(agentId);
    if (!agent) return;

    // Free desk
    if (agent.desk) {
      agent.desk.occupied = false;
      agent.desk.agentId = null;
    }

    // Clear pause timer
    if (agent.pauseTimer) clearTimeout(agent.pauseTimer);

    agent.state = 'leaving';
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
    const delay = 15000 + Math.random() * 15000; // 15-30 seconds
    agent.pauseTimer = setTimeout(() => {
      if (agent.state !== 'working') return;
      this._goOnBreak(agent);
    }, delay);
  }

  _goOnBreak(agent) {
    agent.state = 'on_break';
    agent.breakCount++;

    // Every 3rd break, just phone at desk instead
    if (agent.breakCount % 3 === 0) {
      agent.sprite.anims.play(`${agent.type}_phone`, true);
      setTimeout(() => {
        if (agent.state !== 'on_break') return;
        this._sitDown(agent);
      }, 5000 + Math.random() * 5000);
      return;
    }

    // Walk to a random pause room
    const pauseRoom = PAUSE_ROOMS[Math.floor(Math.random() * PAUSE_ROOMS.length)];
    const room = this.tm.rooms.find(r => r.name === pauseRoom);
    if (!room) { this._sitDown(agent); return; }

    this._walkTo(agent, room.centerX, room.centerY, () => {
      // Stand idle for a bit
      agent.sprite.anims.play(`${agent.type}_idle_down`, true);
      setTimeout(() => {
        if (agent.state !== 'on_break') return;
        // Walk back to desk
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
    agent.pathIndex = 1; // Skip start tile
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

    // Determine facing direction
    const dx = next.x - agent.tileX;
    const dy = next.y - agent.tileY;
    let dir = 'down';
    if (dx < 0) dir = 'left';
    else if (dx > 0) dir = 'right';
    else if (dy < 0) dir = 'up';

    agent.sprite.anims.play(`${agent.type}_walk_${dir}`, true);
    agent.tweenActive = true;

    // Update occupied tiles
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
    // Bottom-center of the map, find a walkable tile
    const grid = this.tm.collisionGrid;
    const midX = Math.floor(grid[0].length / 2);
    for (let y = grid.length - 1; y >= 0; y--) {
      for (let dx = 0; dx < 10; dx++) {
        if (grid[y][midX + dx] === 0) return { x: midX + dx, y };
        if (grid[y][midX - dx] === 0) return { x: midX - dx, y };
      }
    }
    return { x: midX, y: grid.length - 2 };
  }

  _findFreeDesk(roomName) {
    const room = this.tm.rooms.find(r => r.name === roomName);
    if (!room) {
      // Fallback: any free desk
      return this.tm.desks.find(d => !d.occupied);
    }

    // Find desks within/near this room
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

  /** Get agent at a specific tile position */
  getAgentAt(tileX, tileY) {
    for (const agent of this.agents.values()) {
      if (agent.tileX === tileX && agent.tileY === tileY) return agent;
    }
    return null;
  }

  /** Get agent nearest to a world position within radius */
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

  /** Update speech bubble text for an agent */
  updateAgentStatus(agentId, text) {
    const agent = this.agents.get(agentId);
    if (agent) agent.task = text;
  }
}
```

- [ ] **Step 2: Wire AgentManager into OfficeScene**

In `frontend/office/tilemap.js`, add import:

```javascript
import { AgentManager } from './agents.js';
```

In `OfficeScene.create()`, after camera manager:

```javascript
    // Agent manager
    this.agentManager = new AgentManager(this, this.tilemap);
    this.agentManager.create();

    // Also spawn MainAgent (always present)
    this.agentManager.spawnAgent('main-agent', 'ops', 'MainAgent — Koordination');
```

- [ ] **Step 3: Verify agents can spawn and walk**

Open browser console on `/office` and run:
```javascript
document.querySelector('canvas').__scene.agentManager.spawnAgent('test-1', 'coder', 'Test task');
```

Agent should appear at entrance and walk to a desk in Team Büro.

- [ ] **Step 4: Commit**

```bash
git add frontend/office/agents.js frontend/office/tilemap.js
git commit -m "feat(office): agent manager with spawn, pathfinding walk, sit, and break behavior"
```

---

## Task 7: Speech Bubbles

**Files:**
- Create: `frontend/office/bubbles.js`
- Modify: `frontend/office/tilemap.js` (wire bubble manager)

- [ ] **Step 1: Create BubbleManager**

Create `frontend/office/bubbles.js`:

```javascript
const BUBBLE_DURATION = 5000;
const MAX_TEXT_LEN = 30;

export class BubbleManager {
  constructor(scene, agentManager) {
    this.scene = scene;
    this.am = agentManager;
    this.bubbles = new Map(); // agentId → { bg, text, timer }
  }

  create() {
    return this;
  }

  showBubble(agentId, message) {
    const agent = this.am.agents.get(agentId);
    if (!agent) return;

    // Remove existing bubble
    this.hideBubble(agentId);

    const truncated = message.length > MAX_TEXT_LEN
      ? message.slice(0, MAX_TEXT_LEN - 1) + '…'
      : message;

    // Create text above agent sprite
    const textObj = this.scene.add.text(0, 0, truncated, {
      fontSize: '10px',
      fontFamily: 'Courier New',
      color: '#ffffff',
      backgroundColor: '#2a2a4a',
      padding: { x: 6, y: 3 },
      resolution: 2,
    }).setOrigin(0.5, 1).setDepth(20);

    // Small triangle below the bubble (using a graphics object)
    const arrow = this.scene.add.triangle(0, 0, 0, 0, 8, 0, 4, 6, 0x2a2a4a)
      .setOrigin(0.5, 0).setDepth(20);

    const bubble = { text: textObj, arrow, agentId };

    // Auto-hide after duration
    bubble.timer = this.scene.time.delayedCall(BUBBLE_DURATION, () => {
      this.hideBubble(agentId);
    });

    this.bubbles.set(agentId, bubble);
  }

  hideBubble(agentId) {
    const bubble = this.bubbles.get(agentId);
    if (!bubble) return;
    if (bubble.timer) bubble.timer.remove();
    bubble.text.destroy();
    bubble.arrow.destroy();
    this.bubbles.delete(agentId);
  }

  update() {
    // Position bubbles above their agent sprites
    for (const [agentId, bubble] of this.bubbles) {
      const agent = this.am.agents.get(agentId);
      if (!agent || !agent.sprite.active) {
        this.hideBubble(agentId);
        continue;
      }
      bubble.text.setPosition(agent.sprite.x, agent.sprite.y - 30);
      bubble.arrow.setPosition(agent.sprite.x, agent.sprite.y - 30);
    }
  }
}
```

- [ ] **Step 2: Wire into OfficeScene**

In `frontend/office/tilemap.js`, add import:

```javascript
import { BubbleManager } from './bubbles.js';
```

In `OfficeScene.create()`, after agentManager:

```javascript
    // Bubble manager
    this.bubbleManager = new BubbleManager(this, this.agentManager);
    this.bubbleManager.create();
```

In `OfficeScene.update()`:

```javascript
  update(time, delta) {
    if (this.player) this.player.update();
    if (this.bubbleManager) this.bubbleManager.update();
  }
```

- [ ] **Step 3: Commit**

```bash
git add frontend/office/bubbles.js frontend/office/tilemap.js
git commit -m "feat(office): speech bubbles above agents with auto-hide"
```

---

## Task 8: Interactive Objects & Popup Panels

**Files:**
- Create: `frontend/office/objects.js`
- Create: `frontend/office/panels.js`
- Modify: `frontend/office/tilemap.js` (wire managers)

- [ ] **Step 1: Create PanelManager (DOM-based popups)**

Create `frontend/office/panels.js`:

```javascript
export class PanelManager {
  constructor() {
    this.overlay = document.getElementById('panel-overlay');
    this.content = document.getElementById('panel-content');
    this.currentPanel = null;
    this._onKeydown = (e) => { if (e.key === 'Escape') this.close(); };
  }

  create() {
    document.addEventListener('keydown', this._onKeydown);
    window.panelManager = this; // for onclick in overlay
    return this;
  }

  open(title, htmlContent) {
    this.content.innerHTML = `
      <button class="panel-close" onclick="window.panelManager.close()">&times;</button>
      <h2>${title}</h2>
      ${htmlContent}
    `;
    this.overlay.classList.remove('hidden');
    this.currentPanel = title;
  }

  close() {
    this.overlay.classList.add('hidden');
    this.currentPanel = null;
  }

  isOpen() {
    return this.currentPanel !== null;
  }
}
```

- [ ] **Step 2: Create ObjectManager**

Create `frontend/office/objects.js`:

```javascript
const INTERACT_RADIUS = 2; // tiles

export class ObjectManager {
  constructor(scene, tilemapManager, panelManager, agentManager) {
    this.scene = scene;
    this.tm = tilemapManager;
    this.pm = panelManager;
    this.am = agentManager;
    this.objects = []; // { name, tileX, tileY, type, onInteract }
    this.nearestObject = null;
    this.hintEl = document.getElementById('interact-hint');
  }

  create() {
    this._registerObjects();

    // Click handler for zoomed-out interaction
    this.scene.input.on('pointerdown', (pointer) => {
      if (this.pm.isOpen()) return;
      const cam = this.scene.cameras.main;
      if (cam.zoom >= 0.8) return; // Only in zoomed-out mode
      const world = cam.getWorldPoint(pointer.x, pointer.y);
      const tile = this.tm.worldToTile(world.x, world.y);
      const obj = this._findObjectAt(tile.x, tile.y, 2);
      if (obj) obj.onInteract();
    });

    return this;
  }

  _registerObjects() {
    // Whiteboard — in Gemeinschaftsraum
    const gemRoom = this.tm.rooms.find(r => r.name === 'Gemeinschaftsraum');
    if (gemRoom) {
      this.objects.push({
        name: 'Whiteboard', tileX: gemRoom.centerX, tileY: gemRoom.centerY,
        type: 'whiteboard', onInteract: () => this._openWhiteboard()
      });
    }

    // Schedule board — near entrance
    const entrance = this._findEntrance();
    this.objects.push({
      name: 'Schedule-Tafel', tileX: entrance.x + 2, tileY: entrance.y - 1,
      type: 'schedule', onInteract: () => this._openScheduleBoard()
    });

    // Coffee machine — in Küche
    const kitchen = this.tm.rooms.find(r => r.name === 'Küche');
    if (kitchen) {
      this.objects.push({
        name: 'Kaffeemaschine', tileX: kitchen.centerX, tileY: kitchen.centerY,
        type: 'coffee', onInteract: () => this._openCoffee()
      });
    }

    // Telegram mailbox — at entrance
    this.objects.push({
      name: 'Briefkasten', tileX: entrance.x - 2, tileY: entrance.y - 1,
      type: 'telegram', onInteract: () => this._openTelegram()
    });
  }

  update(playerTileX, playerTileY) {
    // Find nearest interactable object
    this.nearestObject = null;
    let bestDist = INTERACT_RADIUS + 1;

    for (const obj of this.objects) {
      const dist = Math.abs(obj.tileX - playerTileX) + Math.abs(obj.tileY - playerTileY);
      if (dist <= INTERACT_RADIUS && dist < bestDist) {
        bestDist = dist;
        this.nearestObject = obj;
      }
    }

    // Also check agent monitors (any agent within radius)
    const playerWorld = this.tm.tileToWorld(playerTileX, playerTileY);
    const nearAgent = this.am.getAgentNear(playerWorld.x, playerWorld.y, INTERACT_RADIUS * 48);
    if (nearAgent && (!this.nearestObject || bestDist > 1)) {
      this.nearestObject = {
        name: `Monitor: ${nearAgent.type}`,
        type: 'monitor',
        onInteract: () => this._openMonitor(nearAgent)
      };
    }

    // Show/hide interaction hint
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
      // Use activity feed from dashboard as fallback
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
        <span style="color:#888">Typ:</span> <span style="color:#e0e0ff">${agent.type}</span>
        <span style="color:#888;margin-left:16px">Status:</span> <span style="color:#44ff88">${agent.state}</span>
      </div>
      <div style="margin-bottom:12px">
        <span style="color:#888">Task:</span>
        <div style="color:#e0e0ff;margin-top:4px;background:#2a2a4a;padding:8px;border-radius:4px">${this._esc(agent.task || '—')}</div>
      </div>
      <div style="color:#888;font-size:11px">Agent ID: ${agent.id}</div>
    `;
    this.pm.open(`Monitor — ${agent.type}`, html);
  }

  _findEntrance() {
    const grid = this.tm.collisionGrid;
    const midX = Math.floor(grid[0].length / 2);
    for (let y = grid.length - 1; y >= 0; y--) {
      if (grid[y][midX] === 0) return { x: midX, y };
    }
    return { x: midX, y: grid.length - 2 };
  }

  _esc(str) {
    const d = document.createElement('div');
    d.textContent = String(str ?? '');
    return d.innerHTML;
  }
}
```

- [ ] **Step 3: Wire into OfficeScene**

In `frontend/office/tilemap.js`, add imports:

```javascript
import { PanelManager } from './panels.js';
import { ObjectManager } from './objects.js';
```

In `OfficeScene.create()`, after bubbleManager:

```javascript
    // Panel manager (DOM popups)
    this.panelManager = new PanelManager();
    this.panelManager.create();

    // Object manager (interactive objects)
    this.objectManager = new ObjectManager(this, this.tilemap, this.panelManager, this.agentManager);
    this.objectManager.create();
```

In `OfficeScene.update()`, add:

```javascript
  update(time, delta) {
    if (this.player) {
      this.player.update();
      const tile = this.player.getTilePos();
      if (this.objectManager) this.objectManager.update(tile.x, tile.y);
      if (this.player.justInteracted()) {
        if (this.panelManager.isOpen()) this.panelManager.close();
        else if (this.objectManager) this.objectManager.interact();
      }
    }
    if (this.bubbleManager) this.bubbleManager.update();
  }
```

- [ ] **Step 4: Verify interaction**

Walk to Gemeinschaftsraum, press E near center — Kanban panel should open showing tasks. ESC to close. Test other objects.

- [ ] **Step 5: Commit**

```bash
git add frontend/office/panels.js frontend/office/objects.js frontend/office/tilemap.js
git commit -m "feat(office): interactive objects with popup panels (whiteboard, schedule, coffee, telegram)"
```

---

## Task 9: HUD & Minimap

**Files:**
- Create: `frontend/office/hud.js`
- Modify: `frontend/office/tilemap.js` (wire HUD)

- [ ] **Step 1: Create HUD with minimap**

Create `frontend/office/hud.js`:

```javascript
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
    // Minimap click to teleport camera
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

    // Draw static minimap base
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

  _updateStats() {
    const agentCount = this.am.agents.size;
    document.getElementById('hud-agents').textContent = agentCount;
  }

  updateTaskCount(count) {
    document.getElementById('hud-tasks').textContent = count;
  }

  updateScheduleCount(count) {
    document.getElementById('hud-schedules').textContent = count;
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

    // Draw walkable areas
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

    // Save as base image
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

    // Restore base
    ctx.putImageData(this._minimapBase, 0, 0);

    // Draw agents as colored dots
    const colors = { coder: '#44aaff', researcher: '#ffaa44', writer: '#aa44ff', ops: '#44ff88' };
    for (const agent of this.am.agents.values()) {
      ctx.fillStyle = colors[agent.type] || '#ffffff';
      ctx.fillRect(agent.tileX * sx - 1, agent.tileY * sy - 1, 3, 3);
    }

    // Draw player as blue dot
    const pt = this.tm.worldToTile(playerX, playerY);
    ctx.fillStyle = '#4488ff';
    ctx.fillRect(pt.x * sx - 2, pt.y * sy - 2, 5, 5);
  }
}
```

- [ ] **Step 2: Wire HUD into OfficeScene**

In `frontend/office/tilemap.js`, add import:

```javascript
import { HUD } from './hud.js';
```

In `OfficeScene.create()`, after objectManager:

```javascript
    // HUD
    this.hud = new HUD(this, this.tilemap, this.agentManager);
    this.hud.create();
```

In `OfficeScene.update()`, add:

```javascript
    if (this.hud && this.player) {
      const pos = this.player.getWorldPos();
      this.hud.update(pos.x, pos.y);
    }
```

- [ ] **Step 3: Verify HUD and minimap**

HUD bar should show agent count. Minimap should show the floor plan with colored dots for agents and blue dot for player. Click minimap to pan camera.

- [ ] **Step 4: Commit**

```bash
git add frontend/office/hud.js frontend/office/tilemap.js
git commit -m "feat(office): HUD bar with stats and minimap with click-to-pan"
```

---

## Task 10: WebSocket Integration

**Files:**
- Create: `frontend/office/ws.js`
- Modify: `frontend/office/tilemap.js` (wire WS)

- [ ] **Step 1: Create WebSocket client**

Create `frontend/office/ws.js`:

```javascript
export class OfficeWS {
  constructor(agentManager, bubbleManager, hud) {
    this.am = agentManager;
    this.bm = bubbleManager;
    this.hud = hud;
    this.ws = null;
  }

  connect() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    this.ws = new WebSocket(proto + '//' + location.host + '/ws');

    this.ws.onopen = () => {
      this.hud.setWSConnected(true);
    };

    this.ws.onclose = () => {
      this.hud.setWSConnected(false);
      setTimeout(() => this.connect(), 3000);
    };

    this.ws.onerror = () => this.ws.close();

    this.ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      this._dispatch(msg);
    };
  }

  _dispatch(msg) {
    const type = msg.type || '';

    switch (type) {
      case 'full_state':
        this._handleFullState(msg);
        break;

      case 'agent_spawned':
        this.am.spawnAgent(msg.agent_id, msg.agent_type || 'coder', msg.task || '');
        this.bm.showBubble(msg.agent_id, msg.task || 'Gestartet...');
        break;

      case 'agent_done':
        this.bm.showBubble(msg.agent_id, '✅ Fertig!');
        // Delay removal so bubble is visible
        setTimeout(() => this.am.removeAgent(msg.agent_id), 3000);
        break;

      case 'agent_error':
        this.bm.showBubble(msg.agent_id, '❌ Fehler!');
        setTimeout(() => this.am.removeAgent(msg.agent_id), 3000);
        break;

      case 'agent_progress':
        this.am.updateAgentStatus(msg.agent_id, msg.label || msg.tool || '');
        this.bm.showBubble(msg.agent_id, msg.label || `🔧 ${msg.tool || '...'}`);
        break;

      case 'task_created':
        this._refreshTaskCount();
        break;

      case 'schedule_fired':
        this._refreshScheduleCount();
        break;

      case 'state_update':
        this._handleFullState(msg);
        break;
    }
  }

  _handleFullState(msg) {
    const agents = msg.active_agents || [];
    // Spawn agents that aren't already in the office
    for (const a of agents) {
      const id = a.agent_id || a.id || `agent-${Math.random().toString(36).slice(2, 8)}`;
      if (!this.am.agents.has(id)) {
        this.am.spawnAgent(id, a.agent_type || a.type || 'coder', a.task || '');
      }
    }
    // Remove agents that are no longer active
    const activeIds = new Set(agents.map(a => a.agent_id || a.id));
    for (const id of this.am.agents.keys()) {
      if (id === 'main-agent') continue; // MainAgent stays
      if (!activeIds.has(id)) {
        this.am.removeAgent(id);
      }
    }
    this._refreshTaskCount();
    this._refreshScheduleCount();
  }

  async _refreshTaskCount() {
    try {
      const res = await fetch('/api/admin/tasks?status=open&limit=1');
      const data = await res.json();
      this.hud.updateTaskCount(data.total || 0);
    } catch (_) {}
  }

  async _refreshScheduleCount() {
    try {
      const res = await fetch('/api/admin/schedules');
      const data = await res.json();
      const active = (data.tasks || []).filter(s => s.active).length;
      this.hud.updateScheduleCount(active);
    } catch (_) {}
  }
}
```

- [ ] **Step 2: Wire WebSocket into OfficeScene**

In `frontend/office/tilemap.js`, add import:

```javascript
import { OfficeWS } from './ws.js';
```

In `OfficeScene.create()`, after HUD:

```javascript
    // WebSocket
    this.officeWS = new OfficeWS(this.agentManager, this.bubbleManager, this.hud);
    this.officeWS.connect();
```

- [ ] **Step 3: Verify live updates**

Open `/office`. Create a task via the dashboard in another tab. Agent should spawn in the office, walk to desk, show speech bubble. When done, walks out.

- [ ] **Step 4: Commit**

```bash
git add frontend/office/ws.js frontend/office/tilemap.js
git commit -m "feat(office): WebSocket integration for live agent spawning and status updates"
```

---

## Task 11: Final Wiring & Polish

**Files:**
- Modify: `frontend/office/tilemap.js` (final OfficeScene with all imports wired)

- [ ] **Step 1: Ensure OfficeScene has all imports and complete create/update**

Verify `frontend/office/tilemap.js` has this final form for the imports and scene:

```javascript
import { PlayerEntity } from './player.js';
import { CameraManager } from './camera.js';
import { AgentManager } from './agents.js';
import { BubbleManager } from './bubbles.js';
import { PanelManager } from './panels.js';
import { ObjectManager } from './objects.js';
import { HUD } from './hud.js';
import { OfficeWS } from './ws.js';

// ... TilemapManager class (unchanged) ...

export class OfficeScene extends Phaser.Scene {
  constructor() { super('Office'); }

  create() {
    this.tilemap = new TilemapManager(this);
    this.tilemap.create();

    const bounds = this.tilemap.getWorldBounds();
    this.physics.world.setBounds(0, 0, bounds.width, bounds.height);
    this.cameras.main.setBounds(0, 0, bounds.width, bounds.height);
    this.cameras.main.setZoom(1);

    const spawnRoom = this.tilemap.rooms.find(r => r.name === 'Gemeinschaftsraum')
      || this.tilemap.rooms[0];
    const spawnX = spawnRoom ? spawnRoom.centerX : 30;
    const spawnY = spawnRoom ? spawnRoom.centerY : 24;

    this.player = new PlayerEntity(this, this.tilemap);
    this.player.create(spawnX, spawnY);

    this.cameraManager = new CameraManager(this, this.player);
    this.cameraManager.create();

    this.agentManager = new AgentManager(this, this.tilemap);
    this.agentManager.create();
    this.agentManager.spawnAgent('main-agent', 'ops', 'MainAgent — Koordination');

    this.bubbleManager = new BubbleManager(this, this.agentManager);
    this.bubbleManager.create();

    this.panelManager = new PanelManager();
    this.panelManager.create();

    this.objectManager = new ObjectManager(this, this.tilemap, this.panelManager, this.agentManager);
    this.objectManager.create();

    this.hud = new HUD(this, this.tilemap, this.agentManager);
    this.hud.create();

    this.officeWS = new OfficeWS(this.agentManager, this.bubbleManager, this.hud);
    this.officeWS.connect();
  }

  update(time, delta) {
    if (this.player) {
      this.player.update();
      const tile = this.player.getTilePos();
      if (this.objectManager) this.objectManager.update(tile.x, tile.y);
      if (this.player.justInteracted()) {
        if (this.panelManager.isOpen()) this.panelManager.close();
        else if (this.objectManager) this.objectManager.interact();
      }
    }
    if (this.bubbleManager) this.bubbleManager.update();
    if (this.hud && this.player) {
      const pos = this.player.getWorldPos();
      this.hud.update(pos.x, pos.y);
    }
  }
}
```

- [ ] **Step 2: End-to-end test**

1. Start backend: `python -m backend.main`
2. Open `http://localhost:8080` — click Büro button in sidebar → new tab opens
3. Walk with WASD, zoom with scroll wheel
4. Press E near Whiteboard → Kanban panel opens
5. Press E near Kaffeemaschine → Stats receipt
6. Create a task via dashboard → agent spawns in office, walks to desk
7. Agent finishes → walks out
8. Minimap shows all positions

- [ ] **Step 3: Commit**

```bash
git add frontend/office/tilemap.js
git commit -m "feat(office): complete pixel office with all systems wired together"
```

---

## Execution Summary

| Task | Description | Est. files |
|------|-------------|-----------|
| 1 | Scaffolding (HTML, CSS, route, game shell) | 5 create, 2 modify |
| 2 | Tilemap loading & rendering | 2 modify |
| 3 | Player character & WASD | 1 create, 1 modify |
| 4 | Hybrid camera (zoom, click) | 1 create, 1 modify |
| 5 | A* pathfinding | 1 create |
| 6 | Agent manager (spawn, walk, sit, breaks) | 1 create, 1 modify |
| 7 | Speech bubbles | 1 create, 1 modify |
| 8 | Interactive objects & popup panels | 2 create, 1 modify |
| 9 | HUD & minimap | 1 create, 1 modify |
| 10 | WebSocket integration | 1 create, 1 modify |
| 11 | Final wiring & polish | 1 modify |
