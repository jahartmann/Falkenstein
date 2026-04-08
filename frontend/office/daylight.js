/**
 * DaylightCycle — time-based lighting overlay for the Phaser office scene.
 * Reads the system clock and applies a color/alpha overlay over the full map.
 *
 * Time ranges:
 *   06-08: Dawn   — warm orange, fading out
 *   08-17: Day    — no overlay (alpha 0)
 *   17-19: Sunset — warm orange, fading in
 *   19-21: Evening — blue tint, increasing
 *   21-06: Night  — dark blue, alpha 0.35
 */
class DaylightCycle {
  constructor(scene) {
    this.scene = scene;

    const bounds = scene.tilemap.getWorldBounds();
    // Fullscreen rectangle over the entire tilemap at depth 50
    this.overlay = scene.add.rectangle(
      bounds.width / 2,
      bounds.height / 2,
      bounds.width,
      bounds.height,
      0x000020,
      0
    );
    this.overlay.setDepth(50);
    this.overlay.setOrigin(0.5, 0.5);

    this._apply();

    // Update every 60 seconds
    scene.time.addEvent({
      delay: 60000,
      callback: this._apply,
      callbackScope: this,
      loop: true,
    });
  }

  _getTimeOfDay() {
    const now = new Date();
    // Fractional hour, e.g. 14.5 for 14:30
    return now.getHours() + now.getMinutes() / 60;
  }

  _lerp(a, b, t) {
    return a + (b - a) * Math.max(0, Math.min(1, t));
  }

  _apply() {
    const h = this._getTimeOfDay();

    let color = 0x000020;
    let alpha = 0;

    if (h >= 21 || h < 6) {
      // Night: dark blue, alpha 0.35
      color = 0x00001a;
      alpha = 0.35;
    } else if (h >= 19 && h < 21) {
      // Evening: fade from sunset to night (blue tint increasing)
      const t = (h - 19) / 2;
      color = 0x000830;
      alpha = this._lerp(0.15, 0.35, t);
    } else if (h >= 17 && h < 19) {
      // Sunset: warm orange fading in
      const t = (h - 17) / 2;
      color = 0x331100;
      alpha = this._lerp(0, 0.15, t);
    } else if (h >= 8 && h < 17) {
      // Day: no overlay
      color = 0x000020;
      alpha = 0;
    } else if (h >= 6 && h < 8) {
      // Dawn: warm orange fading out
      const t = (h - 6) / 2;
      color = 0x331800;
      alpha = this._lerp(0.25, 0, t);
    }

    if (this.overlay) {
      this.overlay.setFillStyle(color, alpha);
    }
  }

  // Force a refresh (useful for testing)
  refresh() {
    this._apply();
  }
}

window.DaylightCycle = DaylightCycle;
