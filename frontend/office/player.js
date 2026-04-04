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

    this.sprite = this.scene.physics.add.sprite(pos.x, pos.y, 'char_1', 0);
    this.sprite.setScale(3);
    this.sprite.setDepth(10);
    this.sprite.body.setSize(12, 12);
    this.sprite.body.setOffset(2, 4);
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
