const SPEED = 160;
const PLAYER_SPRITE = 'Adam';

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

    this.sprite = this.scene.physics.add.sprite(pos.x, pos.y, `${PLAYER_SPRITE}_idle_anim`, 0);
    this.sprite.setScale(3);
    this.sprite.setDepth(10);
    this.sprite.setOrigin(0.5, 0.75);
    this.sprite.body.setSize(12, 12);
    this.sprite.body.setOffset(2, 20);
    this.sprite.setCollideWorldBounds(true);

    const blockedLayer = this.tm.layers['Blocked'];
    if (blockedLayer) {
      this.scene.physics.add.collider(this.sprite, blockedLayer);
    }

    this._createAnimations();

    this.cursors = this.scene.input.keyboard.createCursorKeys();
    this.wasd = this.scene.input.keyboard.addKeys({
      up: Phaser.Input.Keyboard.KeyCodes.W,
      down: Phaser.Input.Keyboard.KeyCodes.S,
      left: Phaser.Input.Keyboard.KeyCodes.A,
      right: Phaser.Input.Keyboard.KeyCodes.D,
    });
    this.interactKey = this.scene.input.keyboard.addKey(Phaser.Input.Keyboard.KeyCodes.E);

    this.scene.cameras.main.startFollow(this.sprite, true, 0.1, 0.1);

    return this;
  }

  _createAnimations() {
    const anims = this.scene.anims;
    const directions = ['down', 'left', 'right', 'up'];

    for (let index = 0; index < directions.length; index++) {
      const dir = directions[index];
      const start = index * 3;
      if (!anims.exists(`player_walk_${dir}`)) {
        anims.create({
          key: `player_walk_${dir}`,
          frames: anims.generateFrameNumbers(`${PLAYER_SPRITE}_run`, { start, end: start + 2 }),
          frameRate: 8,
          repeat: -1
        });
      }
      if (!anims.exists(`player_idle_${dir}`)) {
        anims.create({
          key: `player_idle_${dir}`,
          frames: anims.generateFrameNumbers(`${PLAYER_SPRITE}_idle_anim`, { start, end: start + 2 }),
          frameRate: 5,
          repeat: -1
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

    if (vx !== 0 && vy !== 0) {
      vx *= 0.707;
      vy *= 0.707;
    }

    this.sprite.body.setVelocity(vx, vy);
    this.sprite.flipX = false;

    if (vx !== 0 || vy !== 0) {
      this.sprite.anims.play(`player_walk_${this.facing}`, true);
    } else {
      this.sprite.anims.play(`player_idle_${this.facing}`, true);
    }
  }

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
