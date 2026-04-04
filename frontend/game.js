let agentDisplay;

const TILE = 48;
const MAP_W = 60;
const MAP_H = 48;

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

// --- Preload ---
function preload() {
    this.load.tilemapTiledJSON('office', 'static/assets/office.tmj');
    this.load.image('Room_Builder_Office_48x48', 'static/assets/Room_Builder_Office_48x48.png');
    this.load.image('Modern_Office_Black_Shadow', 'static/assets/Modern_Office_Black_Shadow.png');
    this.load.image('Modern_Office_Black_Shadow_48x48', 'static/assets/Modern_Office_Black_Shadow_48x48.png');

    // Preload character spritesheets for AgentDisplay
    const chars = ['adam', 'alex', 'amelia', 'bob'];
    chars.forEach(name => {
        const capitalized = name.charAt(0).toUpperCase() + name.slice(1);
        this.load.spritesheet(name, `static/assets/characters/${capitalized}_idle_anim_16x16.png`, {
            frameWidth: 16, frameHeight: 32,
        });
    });
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

    // Passive agent display
    agentDisplay = new AgentDisplay(scene);

    // Camera — centered on main agent position, mouse-drag pan
    const mainAgentX = MAIN_AGENT_POS.x * TILE + TILE / 2;
    const mainAgentY = MAIN_AGENT_POS.y * TILE + TILE / 2;
    this.cameras.main.setBounds(0, 0, map.widthInPixels, map.heightInPixels);
    this.cameras.main.centerOn(mainAgentX, mainAgentY);
    this.cameras.main.setZoom(1.5);

    // Mouse wheel zoom
    this.input.on('wheel', (p, go, dx, dy) => {
        const z = this.cameras.main.zoom;
        this.cameras.main.setZoom(Phaser.Math.Clamp(z - dy * 0.002, 0.5, 3));
    });

    // Mouse-drag pan
    this.input.on('pointermove', (pointer) => {
        if (pointer.isDown) {
            this.cameras.main.scrollX -= (pointer.x - pointer.prevPosition.x) / this.cameras.main.zoom;
            this.cameras.main.scrollY -= (pointer.y - pointer.prevPosition.y) / this.cameras.main.zoom;
        }
    });

    // Disable keyboard when typing in task input
    const taskInput = document.getElementById('task-input');
    if (taskInput) {
        taskInput.addEventListener('focus', () => { this.input.keyboard.enabled = false; });
        taskInput.addEventListener('blur', () => { this.input.keyboard.enabled = true; });
    }

    // --- WebSocket via FalkensteinWS (auto-reconnect, submitTask support) ---
    const port = window.location.port ? `:${window.location.port}` : '';
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.hostname}${port}/ws`;
    const fws = new FalkensteinWS(wsUrl);

    fws.on('full_state', (data) => {
        if (data.active_agents) {
            data.active_agents.forEach(a => {
                agentDisplay.spawnAgent(a.agent_id, a.type, a.task);
            });
        }
    });

    fws.on('agent_spawned', (data) => agentDisplay.handleEvent(data));
    fws.on('agent_done', (data) => agentDisplay.handleEvent(data));
    fws.on('agent_working', (data) => agentDisplay.handleEvent(data));

    fws.connect();
    window.ws = fws;
    console.log('Falkenstein ready');
}

// --- Update (no sim loop needed) ---
function update(time, delta) {
    // Passive dashboard — nothing to update per frame
}

const game = new Phaser.Game(config);
