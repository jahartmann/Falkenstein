import { PlayerEntity } from './player.js';
import { CameraManager } from './camera.js';
import { AgentManager } from './agents.js';
import { BubbleManager } from './bubbles.js';
import { PanelManager } from './panels.js';
import { ObjectManager } from './objects.js';
import { HUD } from './hud.js';
import { OfficeWS } from './ws.js';

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
    this.collisionGrid = null;
    this.rooms = [];
    this.desks = [];
  }

  create() {
    const mapData = this.scene.cache.json.get('office-map');

    // Add to tilemap cache so we can use make.tilemap
    this.scene.cache.tilemap.add('office-map', { format: 1, data: mapData });
    this.map = this.scene.make.tilemap({ key: 'office-map' });

    for (const ts of mapData.tilesets) {
      const imageKey = TILESET_MAP[ts.name];
      if (imageKey) {
        this.map.addTilesetImage(ts.name, imageKey);
      }
    }

    const allTilesets = this.map.tilesets.map(t => t.name);

    for (const name of TILE_LAYERS) {
      const layer = this.map.createLayer(name, allTilesets, 0, 0);
      if (layer) {
        this.layers[name] = layer;
        if (name === 'Blocked') {
          layer.setCollisionByExclusion([-1, 0]);
        }
      }
    }

    this._buildCollisionGrid(mapData);
    this._extractRooms(mapData);
    this._extractDesks(mapData);
    this._renderRoomLabels();

    return this;
  }

  _buildCollisionGrid(mapData) {
    const w = mapData.width;
    const h = mapData.height;
    this.collisionGrid = Array.from({ length: h }, () => new Uint8Array(w));

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

    const walkLayer = mapData.layers.find(l => l.name === 'Walkable');
    if (walkLayer) {
      for (let y = 0; y < h; y++) {
        for (let x = 0; x < w; x++) {
          if (walkLayer.data[y * w + x] === 0 && this.collisionGrid[y][x] === 0) {
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

  _renderRoomLabels() {
    for (const room of this.rooms) {
      if (!room.name) continue;
      const pos = this.tileToWorld(room.centerX, room.centerY);
      const label = this.scene.add.text(pos.x, pos.y - 38, room.name, {
        fontSize: '11px',
        fontFamily: 'Courier New, monospace',
        color: '#9fb6d9',
        backgroundColor: '#0d132199',
        padding: { x: 6, y: 3 },
      });
      label.setOrigin(0.5, 0.5);
      label.setDepth(6);
      label.setAlpha(0.72);
    }
  }

  tileToWorld(tileX, tileY) {
    return { x: tileX * 48 + 24, y: tileY * 48 + 24 };
  }

  worldToTile(worldX, worldY) {
    return { x: Math.floor(worldX / 48), y: Math.floor(worldY / 48) };
  }

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
    // Tilemap
    this.tilemap = new TilemapManager(this);
    this.tilemap.create();

    const bounds = this.tilemap.getWorldBounds();
    // Extra padding so sprites at world edges are fully visible
    const pad = 48;
    this.physics.world.setBounds(-pad, -pad, bounds.width + pad * 2, bounds.height + pad * 2);
    this.cameras.main.setBounds(-pad, -pad, bounds.width + pad * 2, bounds.height + pad * 2);
    this.cameras.main.setZoom(1);

    // Player
    const spawnRoom = this.tilemap.rooms.find(r => r.name === 'Gemeinschaftsraum') || this.tilemap.rooms[0];
    const spawnX = spawnRoom ? spawnRoom.centerX : 30;
    const spawnY = spawnRoom ? spawnRoom.centerY : 24;
    this.player = new PlayerEntity(this, this.tilemap);
    this.player.create(spawnX, spawnY);

    // Camera (hybrid zoom)
    this.cameraManager = new CameraManager(this, this.player);
    this.cameraManager.create();

    // Agent manager + NPC employees
    this.agentManager = new AgentManager(this, this.tilemap);
    this.agentManager.create();
    this.agentManager.spawnNPCs();

    // Speech bubbles
    this.bubbleManager = new BubbleManager(this, this.agentManager);
    this.bubbleManager.create();
    this.agentManager.setBubbleManager(this.bubbleManager);

    // Popup panels
    this.panelManager = new PanelManager();
    this.panelManager.create();

    // Interactive objects
    this.objectManager = new ObjectManager(this, this.tilemap, this.panelManager, this.agentManager);
    this.objectManager.create();

    // HUD + Minimap
    this.hud = new HUD(this, this.tilemap, this.agentManager);
    this.hud.create();

    // WebSocket
    this.officeWS = new OfficeWS(this.agentManager, this.bubbleManager, this.hud);
    this.officeWS.connect();

    // Daylight cycle overlay
    if (typeof DaylightCycle !== 'undefined') {
      this.daylight = new DaylightCycle(this);
      window.daylightCycle = this.daylight;
    }
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
    if (this.agentManager) this.agentManager.updatePositions();
    if (this.bubbleManager) this.bubbleManager.update();
    if (this.hud && this.player) {
      const pos = this.player.getWorldPos();
      this.hud.update(pos.x, pos.y);
    }
  }
}
