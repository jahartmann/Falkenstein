const TILESETS = [
  { key: 'tiles_room', url: '/static/assets/Room_Builder_Office_48x48.png' },
  { key: 'tiles_shadow', url: '/static/assets/Modern_Office_Black_Shadow.png' },
  { key: 'tiles_shadow48', url: '/static/assets/Modern_Office_Black_Shadow_48x48.png' },
];

const CHARACTERS = ['Adam', 'Alex', 'Amelia', 'Bob'];
const CHAR_ANIMS = ['idle_anim', 'run', 'sit', 'phone'];

export class BootScene extends Phaser.Scene {
  constructor() { super('Boot'); }

  preload() {
    const bar = this.add.rectangle(
      this.scale.width / 2, this.scale.height / 2, 300, 20, 0x2a2a4a
    );
    const fill = this.add.rectangle(
      this.scale.width / 2 - 148, this.scale.height / 2, 4, 16, 0x7b7bff
    ).setOrigin(0, 0.5);
    this.load.on('progress', (v) => { fill.width = 296 * v; });

    this.load.json('office-map', '/static/assets/office.tmj');

    for (const ts of TILESETS) {
      this.load.image(ts.key, ts.url);
    }

    for (const name of CHARACTERS) {
      for (const anim of CHAR_ANIMS) {
        const key = `${name}_${anim}`;
        const url = `/static/assets/characters/${name}_${anim}_16x16.png`;
        this.load.spritesheet(key, url, { frameWidth: 16, frameHeight: 32 });
      }
    }

    for (let i = 0; i <= 5; i++) {
      this.load.spritesheet(`char_${i}`, `/static/assets/characters/char_${i}.png`, {
        frameWidth: 16, frameHeight: 16
      });
    }
  }

  create() {
    this.scene.start('Office');
  }
}
