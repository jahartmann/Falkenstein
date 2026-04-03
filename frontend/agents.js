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
const SPRITE_SCALE = 3;

const STATE_ANIM = {
    idle_wander: 'idle_anim',
    idle_talk:   'idle_anim',
    idle_coffee: 'idle_anim',
    idle_phone:  'phone',
    idle_sit:    'sit',
    work_sit:    'sit',
    work_type:   'sit',
    work_tool:   'sit',
    work_review: 'sit',
};

function getMoodEmoji(mood) {
    if (!mood) return '';
    if (mood.stress > 0.7) return '😰';
    if (mood.frustration > 0.6) return '😤';
    if (mood.energy < 0.3) return '😴';
    if (mood.motivation > 0.8) return '🔥';
    if (mood.motivation > 0.6) return '😊';
    return '';
}

const TOOL_ICONS = {
    file_manager:     '💾',
    web_research:     '🌐',
    shell_runner:     '💻',
    code_executor:    '⚡',
    obsidian_manager: '📝',
    cli_bridge:       '🚀',
};

class AgentSprites {
    constructor(scene) {
        this.scene = scene;
        this.sprites = {};
        this.nameLabels = {};
        this.moodLabels = {};
        this.toolIcons = {};
        this.bubbles = {};
        this.agentStates = {};
    }

    preload(scene) {
        const chars = ['Adam', 'Alex', 'Amelia', 'Bob'];
        const anims = ['run', 'idle_anim', 'sit', 'phone'];
        chars.forEach(name => {
            anims.forEach(anim => {
                const key = `${name}_${anim}`;
                scene.load.spritesheet(key, `static/assets/characters/${name}_${anim}_16x16.png`, {
                    frameWidth: 16,
                    frameHeight: 32,  // FIXED: sprites are 16x32, not 16x16
                });
            });
        });
    }

    createAnimations(scene) {
        const chars = ['Adam', 'Alex', 'Amelia', 'Bob'];
        const animDefs = [
            { suffix: 'run',       frameRate: 8, repeat: -1 },
            { suffix: 'idle_anim', frameRate: 4, repeat: -1 },
            { suffix: 'sit',       frameRate: 4, repeat: -1 },
            { suffix: 'phone',     frameRate: 4, repeat: -1 },
        ];
        chars.forEach(name => {
            animDefs.forEach(def => {
                const key = `${name}_${def.suffix}`;
                if (!scene.anims.exists(key)) {
                    const frames = scene.anims.generateFrameNumbers(key, {});
                    if (frames.length > 0) {
                        scene.anims.create({
                            key, frames,
                            frameRate: def.frameRate,
                            repeat: def.repeat,
                        });
                    }
                }
            });
        });
    }

    createAgents(agentList) {
        agentList.forEach(agent => {
            if (!this.sprites[agent.id]) this.createAgent(agent);
        });
    }

    createAgent(agent) {
        const charName = SPRITE_MAP[agent.id] || 'Adam';
        const animSuffix = STATE_ANIM[agent.state] || 'idle_anim';
        const key = `${charName}_${animSuffix}`;
        const x = agent.x * TILE_SIZE + TILE_SIZE / 2;
        const y = agent.y * TILE_SIZE + TILE_SIZE / 2;

        const sprite = this.scene.add.sprite(x, y, key);
        sprite.setScale(SPRITE_SCALE);
        sprite.setOrigin(0.5, 0.75);  // bottom-center like Jarvis
        sprite.setDepth(100 + agent.y);  // Y-sort depth
        sprite.play(key);

        if (TINT_MAP[agent.id]) sprite.setTint(TINT_MAP[agent.id]);

        sprite.setInteractive({ useHandCursor: true });
        sprite.on('pointerdown', () => {
            if (typeof showAgentDetail === 'function') showAgentDetail(agent.id);
        });

        // Name label below sprite
        const label = this.scene.add.text(x, y + 8, agent.name, {
            fontSize: '8px', fontFamily: 'monospace',
            color: '#ffffff', backgroundColor: '#000000cc',
            padding: { x: 3, y: 1 },
        }).setOrigin(0.5).setDepth(300);

        // Mood emoji above sprite
        const emoji = getMoodEmoji(agent.mood);
        const moodLabel = this.scene.add.text(x, y - 40, emoji, {
            fontSize: '12px',
        }).setOrigin(0.5).setDepth(301);

        this.sprites[agent.id] = sprite;
        this.nameLabels[agent.id] = label;
        this.moodLabels[agent.id] = moodLabel;
        this.agentStates[agent.id] = { x: agent.x, y: agent.y, state: agent.state };
    }

    _setAnimation(agentId, state) {
        const sprite = this.sprites[agentId];
        if (!sprite) return;
        const charName = SPRITE_MAP[agentId] || 'Adam';
        const animSuffix = STATE_ANIM[state] || 'idle_anim';
        const key = `${charName}_${animSuffix}`;
        if (sprite.anims.currentAnim?.key !== key) sprite.play(key);
    }

    updateAgent(agent) {
        const sprite = this.sprites[agent.id];
        if (!sprite) return;

        const prev = this.agentStates[agent.id] || { x: agent.x, y: agent.y };
        const targetX = agent.x * TILE_SIZE + TILE_SIZE / 2;
        const targetY = agent.y * TILE_SIZE + TILE_SIZE / 2;

        if (agent.state) {
            this._setAnimation(agent.id, agent.state);
            if (this.agentStates[agent.id]) this.agentStates[agent.id].state = agent.state;
        }

        if (agent.mood) this._updateMood(agent.id, agent.mood);

        if (prev.x !== agent.x || prev.y !== agent.y) {
            // Flip based on direction
            if (agent.x < prev.x) sprite.setFlipX(true);
            else if (agent.x > prev.x) sprite.setFlipX(false);

            // Run animation during movement
            const charName = SPRITE_MAP[agent.id] || 'Adam';
            sprite.play(`${charName}_run`);

            this._tweenTo(agent.id, targetX, targetY, 500);
            if (this.agentStates[agent.id]) {
                this.agentStates[agent.id].x = agent.x;
                this.agentStates[agent.id].y = agent.y;
            }
        }
    }

    _tweenTo(agentId, x, y, duration) {
        const sprite = this.sprites[agentId];
        const label = this.nameLabels[agentId];
        const mood = this.moodLabels[agentId];
        const bubble = this.bubbles[agentId];

        if (sprite) {
            this.scene.tweens.add({
                targets: sprite, x, y, duration, ease: 'Linear',
                onComplete: () => {
                    sprite.setDepth(100 + Math.floor(y / TILE_SIZE));
                    const state = this.agentStates[agentId]?.state || 'idle_sit';
                    this._setAnimation(agentId, state);
                },
            });
        }
        if (label) this.scene.tweens.add({ targets: label, x, y: y + 8, duration, ease: 'Linear' });
        if (mood) this.scene.tweens.add({ targets: mood, x, y: y - 40, duration, ease: 'Linear' });
        if (bubble) this.scene.tweens.add({ targets: bubble, x, y: y - 54, duration, ease: 'Linear' });
    }

    _updateMood(agentId, mood) {
        const m = this.moodLabels[agentId];
        if (m) m.setText(getMoodEmoji(mood));
    }

    showBubble(agentId, text, duration = 4000) {
        const sprite = this.sprites[agentId];
        if (!sprite) return;
        if (this.bubbles[agentId]) this.bubbles[agentId].destroy();

        const bubble = this.scene.add.text(sprite.x, sprite.y - 54, text, {
            fontSize: '8px', fontFamily: 'monospace',
            color: '#ffffff', backgroundColor: '#333333dd',
            padding: { x: 4, y: 3 }, wordWrap: { width: 140 },
        }).setOrigin(0.5).setDepth(400);
        this.bubbles[agentId] = bubble;

        this.scene.time.delayedCall(duration, () => {
            if (this.bubbles[agentId] === bubble) {
                bubble.destroy();
                delete this.bubbles[agentId];
            }
        });
    }

    showToolIcon(agentId, toolName) {
        const sprite = this.sprites[agentId];
        if (!sprite) return;
        if (this.toolIcons[agentId]) this.toolIcons[agentId].destroy();
        const icon = TOOL_ICONS[toolName] || '🔧';
        const t = this.scene.add.text(sprite.x + 18, sprite.y - 18, icon, {
            fontSize: '14px',
        }).setOrigin(0.5).setDepth(350);
        this.toolIcons[agentId] = t;
        this.scene.time.delayedCall(3000, () => {
            if (this.toolIcons[agentId] === t) { t.destroy(); delete this.toolIcons[agentId]; }
        });
    }

    clearToolIcon(agentId) {
        if (this.toolIcons[agentId]) { this.toolIcons[agentId].destroy(); delete this.toolIcons[agentId]; }
    }

    removeAgent(agentId) {
        [this.sprites, this.nameLabels, this.moodLabels, this.toolIcons, this.bubbles].forEach(map => {
            if (map[agentId]) { map[agentId].destroy(); delete map[agentId]; }
        });
        delete this.agentStates[agentId];
    }

    updateAllAgents(agents) {
        agents.forEach(agent => {
            if (this.sprites[agent.id]) this.updateAgent(agent);
            else this.createAgent(agent);
        });
    }
}
