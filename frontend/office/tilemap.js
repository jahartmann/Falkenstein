export class OfficeScene extends Phaser.Scene {
  constructor() { super('Office'); }

  create() {
    this.add.text(400, 300, 'Falkenstein Büro', {
      fontSize: '24px', color: '#9b9bff', fontFamily: 'Courier New'
    }).setOrigin(0.5);
  }
}
