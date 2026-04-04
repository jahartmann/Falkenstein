const MIN_ZOOM = 0.4;
const MAX_ZOOM = 2.0;
const ZOOM_STEP = 0.1;
const CLICK_MODE_THRESHOLD = 0.8;

export class CameraManager {
  constructor(scene, player) {
    this.scene = scene;
    this.player = player;
    this.zoom = 1.0;
    this.isFollowing = true;
  }

  create() {
    const cam = this.scene.cameras.main;

    this.scene.input.on('wheel', (pointer, gameObjects, deltaX, deltaY) => {
      if (deltaY > 0) {
        this.zoom = Math.max(MIN_ZOOM, this.zoom - ZOOM_STEP);
      } else {
        this.zoom = Math.min(MAX_ZOOM, this.zoom + ZOOM_STEP);
      }
      cam.setZoom(this.zoom);
      this._updateFollowMode();
      this._updateHUD();
    });

    this.scene.input.on('pointerdown', (pointer) => {
      if (this.zoom >= CLICK_MODE_THRESHOLD) return;
      if (pointer.rightButtonDown()) return;

      const worldPoint = cam.getWorldPoint(pointer.x, pointer.y);
      cam.stopFollow();
      this.isFollowing = false;
      cam.pan(worldPoint.x, worldPoint.y, 400, 'Sine.easeInOut');
    });

    this.scene.input.keyboard.on('keydown-SPACE', () => {
      if (!this.isFollowing) {
        this._snapToPlayer();
      }
    });

    this._updateHUD();
    return this;
  }

  _snapToPlayer() {
    const cam = this.scene.cameras.main;
    const pos = this.player.getWorldPos();
    cam.pan(pos.x, pos.y, 300, 'Sine.easeInOut', false, () => {
      cam.startFollow(this.player.sprite, true, 0.1, 0.1);
      this.isFollowing = true;
    });
    this.zoom = 1.0;
    cam.zoomTo(1.0, 300);
    this._updateHUD();
  }

  _updateFollowMode() {
    const cam = this.scene.cameras.main;
    if (this.zoom >= CLICK_MODE_THRESHOLD && !this.isFollowing) {
      cam.startFollow(this.player.sprite, true, 0.1, 0.1);
      this.isFollowing = true;
    }
  }

  _updateHUD() {
    const el = document.getElementById('hud-zoom');
    if (el) el.textContent = this.zoom.toFixed(1) + 'x';
  }
}
