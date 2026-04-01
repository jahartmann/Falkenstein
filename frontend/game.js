let ws, agentSprites;

const config = {
    type: Phaser.AUTO,
    width: 1280,
    height: 720,
    parent: 'game-container',
    pixelArt: true,
    scene: {
        preload: preload,
        create: create,
        update: update,
    },
    scale: {
        mode: Phaser.Scale.FIT,
        autoCenter: Phaser.Scale.CENTER_BOTH,
    },
};

function preload() {
    this.load.tilemapTiledJSON('office', 'static/assets/office.tmj');
    this.load.image('Room_Builder_Office_48x48', 'static/assets/Room_Builder_Office_48x48.png');
    this.load.image('Modern_Office_Black_Shadow', 'static/assets/Modern_Office_Black_Shadow.png');
    this.load.image('Modern_Office_Black_Shadow_48x48', 'static/assets/Modern_Office_Black_Shadow_48x48.png');

    agentSprites = new AgentSprites(this);
    agentSprites.preload(this);
}

function create() {
    const map = this.make.tilemap({ key: 'office' });
    const tilesetRB = map.addTilesetImage('Room_Builder_Office_48x48', 'Room_Builder_Office_48x48');
    const tilesetMS = map.addTilesetImage('Modern_Office_Black_Shadow', 'Modern_Office_Black_Shadow');
    const tilesetMS48 = map.addTilesetImage('Modern_Office_Black_Shadow_48x48', 'Modern_Office_Black_Shadow_48x48');
    const allTilesets = [tilesetRB, tilesetMS, tilesetMS48].filter(Boolean);

    const layerNames = ['Walkable', 'Blocked', 'Furniture', 'WalkableFurniture', 'Stühle'];
    layerNames.forEach(name => {
        const layer = map.createLayer(name, allTilesets);
        if (layer) {
            layer.setDepth(name === 'Stühle' ? 50 : 0);
        }
    });

    this.cameras.main.setBounds(0, 0, map.widthInPixels, map.heightInPixels);
    this.cameras.main.setZoom(0.5);

    this.input.on('pointermove', (pointer) => {
        if (pointer.isDown) {
            this.cameras.main.scrollX -= (pointer.x - pointer.prevPosition.x) / this.cameras.main.zoom;
            this.cameras.main.scrollY -= (pointer.y - pointer.prevPosition.y) / this.cameras.main.zoom;
        }
    });

    this.input.on('wheel', (pointer, gameObjects, deltaX, deltaY) => {
        const zoom = this.cameras.main.zoom;
        this.cameras.main.setZoom(Phaser.Math.Clamp(zoom - deltaY * 0.001, 0.25, 2));
    });

    const wsUrl = `ws://${window.location.hostname}:${window.location.port}/ws`;
    ws = new FalkensteinWS(wsUrl);

    ws.on('full_state', (data) => {
        agentSprites.createAgents(data.agents);
    });

    ws.on('state_update', (data) => {
        agentSprites.updateAllAgents(data.agents);
    });

    ws.on('move', (data) => {
        agentSprites.updateAgent(data);
    });

    ws.on('talk', (data) => {
        agentSprites.showBubble(data.agent, data.message);
    });

    ws.on('coffee', (data) => {
        agentSprites.showBubble(data.agent, '☕ Kaffeepause...');
    });

    ws.on('task_assigned', (data) => {
        agentSprites.showBubble(data.agent, `📋 ${data.task_title}`);
    });

    ws.on('tool_use', (data) => {
        const icons = {
            file_manager: '💾',
            web_surfer: '🔍',
            shell_runner: '💻',
            code_executor: '⚡',
            obsidian_manager: '📝',
        };
        const icon = icons[data.tool] || '🔧';
        agentSprites.showBubble(data.agent, `${icon} ${data.tool}`);
    });

    ws.connect();
}

function update() {}

const game = new Phaser.Game(config);
