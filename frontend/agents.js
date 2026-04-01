const SPRITE_MAP = {
    pm:         'Adam',
    team_lead:  'Alex',
    coder_1:    'Amelia',
    coder_2:    'Bob',
    researcher: 'Adam',
    writer:     'Amelia',
    ops:        'Bob',
};

const TINT_MAP = {
    researcher: 0x88ccff,
    writer:     0xffcc88,
    ops:        0xcc88ff,
};

const TILE_SIZE = 48;
const SPRITE_SCALE = 2.5;

class AgentSprites {
    constructor(scene) {
        this.scene = scene;
        this.sprites = {};
        this.nameLabels = {};
        this.bubbles = {};
    }

    preload(scene) {
        const chars = ['Adam', 'Alex', 'Amelia', 'Bob'];
        const anims = ['run', 'idle_anim', 'sit', 'phone'];
        chars.forEach(name => {
            anims.forEach(anim => {
                const key = `${name}_${anim}`;
                const frameH = 16;
                const frameW = 16;
                scene.load.spritesheet(key, `static/assets/characters/${name}_${anim}_16x16.png`, {
                    frameWidth: frameW,
                    frameHeight: frameH,
                });
            });
        });
    }

    createAgents(agentList) {
        agentList.forEach(agent => {
            this.createAgent(agent);
        });
    }

    createAgent(agent) {
        const charName = SPRITE_MAP[agent.id] || 'Adam';
        const key = `${charName}_idle_anim`;
        const x = agent.x * TILE_SIZE + TILE_SIZE / 2;
        const y = agent.y * TILE_SIZE + TILE_SIZE / 2;

        const sprite = this.scene.add.sprite(x, y, key);
        sprite.setScale(SPRITE_SCALE);
        sprite.setDepth(100);

        if (TINT_MAP[agent.id]) {
            sprite.setTint(TINT_MAP[agent.id]);
        }

        const label = this.scene.add.text(x, y - 28, agent.name, {
            fontSize: '11px',
            fontFamily: 'monospace',
            color: '#ffffff',
            backgroundColor: '#00000088',
            padding: { x: 3, y: 1 },
        });
        label.setOrigin(0.5);
        label.setDepth(200);

        this.sprites[agent.id] = sprite;
        this.nameLabels[agent.id] = label;
    }

    updateAgent(agent) {
        const sprite = this.sprites[agent.id];
        if (!sprite) return;

        const targetX = agent.x * TILE_SIZE + TILE_SIZE / 2;
        const targetY = agent.y * TILE_SIZE + TILE_SIZE / 2;

        this.scene.tweens.add({
            targets: sprite,
            x: targetX,
            y: targetY,
            duration: 400,
            ease: 'Linear',
        });

        const label = this.nameLabels[agent.id];
        if (label) {
            this.scene.tweens.add({
                targets: label,
                x: targetX,
                y: targetY - 28,
                duration: 400,
                ease: 'Linear',
            });
        }
    }

    showBubble(agentId, text, duration = 4000) {
        const sprite = this.sprites[agentId];
        if (!sprite) return;

        if (this.bubbles[agentId]) {
            this.bubbles[agentId].destroy();
        }

        const bubble = this.scene.add.text(sprite.x, sprite.y - 50, text, {
            fontSize: '10px',
            fontFamily: 'monospace',
            color: '#ffffff',
            backgroundColor: '#333333cc',
            padding: { x: 6, y: 4 },
            wordWrap: { width: 160 },
        });
        bubble.setOrigin(0.5);
        bubble.setDepth(300);
        this.bubbles[agentId] = bubble;

        this.scene.time.delayedCall(duration, () => {
            if (this.bubbles[agentId] === bubble) {
                bubble.destroy();
                delete this.bubbles[agentId];
            }
        });
    }

    updateAllAgents(agents) {
        agents.forEach(agent => {
            if (this.sprites[agent.id]) {
                this.updateAgent(agent);
            } else {
                this.createAgent(agent);
            }
        });
    }
}
