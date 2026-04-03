let agentSprites, player, cursors, wasd, shiftKey;
let collisionGrid = null;

const TILE = 48;
const MAP_W = 60;
const MAP_H = 48;
const WALK_MS = 200;
const SPRINT_MS = 100;
const PLAYER_SCALE = 3;

const config = {
    type: Phaser.AUTO,
    parent: 'game-container',
    pixelArt: true,
    backgroundColor: '#1a1a2e',
    scale: {
        mode: Phaser.Scale.RESIZE,
        width: '100%',
        height: '100%',
    },
    scene: { preload, create, update },
};

// --- Collision grid from Blocked layer ---
function buildCollisionGrid(map) {
    const grid = [];
    const blocked = map.getLayer('Blocked');
    const furniture = map.getLayer('Furniture');
    for (let y = 0; y < MAP_H; y++) {
        const row = [];
        for (let x = 0; x < MAP_W; x++) {
            const bTile = blocked ? blocked.data[y]?.[x] : null;
            const fTile = furniture ? furniture.data[y]?.[x] : null;
            const isBlocked = (bTile && bTile.index > 0) || (fTile && fTile.index > 0);
            row.push(isBlocked ? 1 : 0);
        }
        grid.push(row);
    }
    return grid;
}

function isWalkable(tileX, tileY) {
    if (tileX < 0 || tileX >= MAP_W || tileY < 0 || tileY >= MAP_H) return false;
    if (!collisionGrid) return true;
    return collisionGrid[tileY][tileX] === 0;
}

function tileToPixel(tileX, tileY) {
    return { x: tileX * TILE + TILE / 2, y: tileY * TILE + TILE / 2 };
}

// --- Preload ---
function preload() {
    this.load.tilemapTiledJSON('office', 'static/assets/office.tmj');
    this.load.image('Room_Builder_Office_48x48', 'static/assets/Room_Builder_Office_48x48.png');
    this.load.image('Modern_Office_Black_Shadow', 'static/assets/Modern_Office_Black_Shadow.png');
    this.load.image('Modern_Office_Black_Shadow_48x48', 'static/assets/Modern_Office_Black_Shadow_48x48.png');

    agentSprites = new AgentSprites(this);
    agentSprites.preload(this);
}

// --- Create ---
function create() {
    const scene = this;

    // Tilemap
    const map = this.make.tilemap({ key: 'office' });
    const tilesetRB = map.addTilesetImage('Room_Builder_Office_48x48', 'Room_Builder_Office_48x48');
    const tilesetMS = map.addTilesetImage('Modern_Office_Black_Shadow', 'Modern_Office_Black_Shadow');
    const tilesetMS48 = map.addTilesetImage('Modern_Office_Black_Shadow_48x48', 'Modern_Office_Black_Shadow_48x48');
    const allTilesets = [tilesetRB, tilesetMS, tilesetMS48].filter(Boolean);

    ['Walkable', 'Blocked', 'Furniture', 'WalkableFurniture', 'Stühle'].forEach(name => {
        const layer = map.createLayer(name, allTilesets);
        if (layer) layer.setDepth(name === 'Stühle' ? 50 : 0);
    });

    // Collision grid
    collisionGrid = buildCollisionGrid(map);

    // Pathfinder for agents
    try { agentSprites.initPathfinder(map); } catch (e) {
        console.warn('Pathfinder:', e.message);
    }

    // Animations
    agentSprites.createAnimations(this);

    // --- Player ---
    const startTX = 30, startTY = 24;
    const sp = tileToPixel(startTX, startTY);
    player = scene.add.sprite(sp.x, sp.y, 'Alex_idle_anim');
    player.setScale(PLAYER_SCALE);
    player.setOrigin(0.5, 0.75);
    player.setDepth(500);
    player.play('Alex_idle_anim');
    player._tileX = startTX;
    player._tileY = startTY;
    player._moving = false;

    player._label = scene.add.text(sp.x, sp.y + 8, 'Du', {
        fontSize: '8px', fontFamily: 'monospace', color: '#ffd700',
        backgroundColor: '#000000cc', padding: { x: 3, y: 1 },
    }).setOrigin(0.5).setDepth(501);

    // Camera
    this.cameras.main.setBounds(0, 0, map.widthInPixels, map.heightInPixels);
    this.cameras.main.startFollow(player, true, 0.08, 0.08);
    this.cameras.main.setZoom(2);

    this.input.on('wheel', (p, go, dx, dy) => {
        const z = this.cameras.main.zoom;
        this.cameras.main.setZoom(Phaser.Math.Clamp(z - dy * 0.002, 0.5, 3));
    });

    // Keyboard
    cursors = this.input.keyboard.createCursorKeys();
    wasd = this.input.keyboard.addKeys({
        up: Phaser.Input.Keyboard.KeyCodes.W,
        down: Phaser.Input.Keyboard.KeyCodes.S,
        left: Phaser.Input.Keyboard.KeyCodes.A,
        right: Phaser.Input.Keyboard.KeyCodes.D,
    });
    shiftKey = this.input.keyboard.addKey(Phaser.Input.Keyboard.KeyCodes.SHIFT);

    // Disable keyboard when typing
    const taskInput = document.getElementById('task-input');
    taskInput.addEventListener('focus', () => { this.input.keyboard.enabled = false; });
    taskInput.addEventListener('blur', () => { this.input.keyboard.enabled = true; });

    // --- WebSocket ---
    const wsUrl = `ws://${window.location.hostname}:${window.location.port}/ws`;
    window.ws = new FalkensteinWS(wsUrl);

    window.ws.on('full_state', (data) => {
        console.log('Agents:', data.agents.length);
        agentSprites.createAgents(data.agents);
    });
    window.ws.on('state_update', (data) => agentSprites.updateAllAgents(data.agents));
    window.ws.on('move', (data) => agentSprites.updateAgent(data));
    window.ws.on('talk', (data) => agentSprites.showBubble(data.agent, data.message));
    window.ws.on('coffee', (data) => agentSprites.showBubble(data.agent, '☕'));
    window.ws.on('task_assigned', (data) => {
        const pre = data.is_sub_agent ? '🆕 ' : '';
        agentSprites.showBubble(data.agent, `${pre}📋 ${data.task_title}`);
    });
    window.ws.on('tool_use', (data) => {
        agentSprites.showToolIcon(data.agent, data.tool);
        agentSprites.showBubble(data.agent, `${TOOL_ICONS[data.tool]||'🔧'} ${data.tool}`, 2000);
    });
    window.ws.on('task_completed', (data) => {
        agentSprites.clearToolIcon(data.agent);
        agentSprites.showBubble(data.agent, '✅', 3000);
    });
    window.ws.on('review', (data) => {
        agentSprites.showBubble(data.agent, `${data.score>=7?'⭐':'⚠️'} ${data.score}/10`, 2000);
    });
    window.ws.on('sub_agent_retired', (data) => agentSprites.removeAgent(data.agent));

    window.ws.connect();
    console.log('Falkenstein ready');
}

// --- Tile-based movement with collision ---
function movePlayerTo(scene, tx, ty) {
    if (player._moving) return;
    if (!isWalkable(tx, ty)) return;

    player._moving = true;
    player._tileX = tx;
    player._tileY = ty;

    const target = tileToPixel(tx, ty);
    const duration = shiftKey.isDown ? SPRINT_MS : WALK_MS;

    // Run animation
    const runKey = 'Alex_run';
    if (player.anims.currentAnim?.key !== runKey) player.play(runKey);

    scene.tweens.add({
        targets: player,
        x: target.x, y: target.y,
        duration,
        ease: 'Linear',
        onUpdate: () => {
            player._label.x = player.x;
            player._label.y = player.y + 8;
        },
        onComplete: () => {
            player._moving = false;
        },
    });
}

function update() {
    if (!player || !this.input.keyboard.enabled) return;
    if (player._moving) return;

    let dx = 0, dy = 0;
    if (cursors.left.isDown || wasd.left.isDown) { dx = -1; player.setFlipX(true); }
    else if (cursors.right.isDown || wasd.right.isDown) { dx = 1; player.setFlipX(false); }
    if (cursors.up.isDown || wasd.up.isDown) dy = -1;
    else if (cursors.down.isDown || wasd.down.isDown) dy = 1;

    if (dx !== 0 || dy !== 0) {
        movePlayerTo(this, player._tileX + dx, player._tileY + dy);
    } else {
        if (player.anims.currentAnim?.key !== 'Alex_idle_anim') {
            player.play('Alex_idle_anim');
        }
    }
}

const game = new Phaser.Game(config);
