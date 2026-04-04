// frontend/agents.js
// Passive agent display — agents appear when working, disappear when done

const AGENT_SPRITES = {
    coder: { key: 'adam', frame: 0 },
    researcher: { key: 'amelia', frame: 0 },
    writer: { key: 'bob', frame: 0 },
    ops: { key: 'alex', frame: 0 },
};

const DESK_POSITIONS = {
    coder: { x: 10, y: 20 },
    researcher: { x: 20, y: 25 },
    writer: { x: 25, y: 25 },
    ops: { x: 40, y: 15 },
};

const MAIN_AGENT_POS = { x: 30, y: 10 };

class AgentDisplay {
    constructor(scene) {
        this.scene = scene;
        this.sprites = {};
        this.bubbles = {};
        this.tileSize = 48;
        this._createMainAgent();
    }

    _createMainAgent() {
        const x = MAIN_AGENT_POS.x * this.tileSize + this.tileSize / 2;
        const y = MAIN_AGENT_POS.y * this.tileSize + this.tileSize / 2;
        this.mainSprite = this.scene.add.sprite(x, y, 'alex', 0);
        this.mainSprite.setScale(3);
        this.mainSprite.setDepth(10);
        this.mainLabel = this.scene.add.text(x, y - 55, '🧠 Falkenstein', {
            fontSize: '12px',
            color: '#ffffff',
            backgroundColor: '#333333',
            padding: { x: 4, y: 2 },
        }).setOrigin(0.5).setDepth(11);
    }

    spawnAgent(agentId, agentType, taskTitle) {
        const pos = DESK_POSITIONS[agentType] || DESK_POSITIONS.ops;
        const spriteInfo = AGENT_SPRITES[agentType] || AGENT_SPRITES.ops;
        const x = pos.x * this.tileSize + this.tileSize / 2;
        const y = pos.y * this.tileSize + this.tileSize / 2;

        const sprite = this.scene.add.sprite(x, y, spriteInfo.key, spriteInfo.frame);
        sprite.setScale(3);
        sprite.setDepth(10);
        sprite.setAlpha(0);
        this.scene.tweens.add({ targets: sprite, alpha: 1, duration: 500 });
        this.sprites[agentId] = sprite;

        const bubble = this.scene.add.text(x, y - 55, `💻 ${taskTitle}`, {
            fontSize: '10px',
            color: '#ffffff',
            backgroundColor: '#1a1a2e',
            padding: { x: 4, y: 2 },
            wordWrap: { width: 200 },
        }).setOrigin(0.5).setDepth(11);
        this.bubbles[agentId] = bubble;

        this._startTypingAnim(sprite);
    }

    removeAgent(agentId) {
        const sprite = this.sprites[agentId];
        const bubble = this.bubbles[agentId];
        if (sprite) {
            this.scene.tweens.killTweensOf(sprite);
            this.scene.tweens.add({
                targets: sprite,
                alpha: 0,
                duration: 500,
                onComplete: () => sprite.destroy(),
            });
            delete this.sprites[agentId];
        }
        if (bubble) {
            this.scene.tweens.killTweensOf(bubble);
            this.scene.tweens.add({
                targets: bubble,
                alpha: 0,
                duration: 500,
                onComplete: () => bubble.destroy(),
            });
            delete this.bubbles[agentId];
        }
    }

    updateBubble(agentId, text) {
        const bubble = this.bubbles[agentId];
        if (bubble) {
            bubble.setText(text);
        }
    }

    _startTypingAnim(sprite) {
        this.scene.tweens.add({
            targets: sprite,
            y: sprite.y - 3,
            duration: 600,
            yoyo: true,
            repeat: -1,
            ease: 'Sine.easeInOut',
        });
    }

    handleEvent(event) {
        switch (event.type) {
            case 'agent_spawned':
                this.spawnAgent(event.agent_id, event.agent_type, event.task);
                break;
            case 'agent_done':
                this.removeAgent(event.agent_id);
                break;
            case 'agent_working':
                this.updateBubble(event.agent_id, `💻 ${event.status || ''}`);
                break;
        }
    }
}
