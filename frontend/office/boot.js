export class BootScene extends Phaser.Scene {
  constructor() { super('Boot'); }

  preload() {
    this.load.on('complete', () => this.scene.start('Office'));
  }

  create() {
    if (this.load.totalComplete === this.load.totalToLoad) {
      this.scene.start('Office');
    }
  }
}
