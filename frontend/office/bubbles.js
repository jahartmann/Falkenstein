const BUBBLE_DURATION = 5000;
const MAX_TEXT_LEN = 30;

export class BubbleManager {
  constructor(scene, agentManager) {
    this.scene = scene;
    this.am = agentManager;
    this.bubbles = new Map();
  }

  create() {
    return this;
  }

  showBubble(agentId, message) {
    const agent = this.am.agents.get(agentId);
    if (!agent) return;

    this.hideBubble(agentId);

    const truncated = message.length > MAX_TEXT_LEN
      ? message.slice(0, MAX_TEXT_LEN - 1) + '\u2026'
      : message;

    const textObj = this.scene.add.text(0, 0, truncated, {
      fontSize: '10px',
      fontFamily: 'Courier New',
      color: '#ffffff',
      backgroundColor: '#2a2a4a',
      padding: { x: 6, y: 3 },
      resolution: 2,
    }).setOrigin(0.5, 1).setDepth(20);

    const arrow = this.scene.add.triangle(0, 0, 0, 0, 8, 0, 4, 6, 0x2a2a4a)
      .setOrigin(0.5, 0).setDepth(20);

    const bubble = { text: textObj, arrow, agentId };

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
