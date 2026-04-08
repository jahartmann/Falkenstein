# Pixel-Büro Upgrade — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the Pixel-Büro from a basic agent visualizer into an atmospheric chill-mode experience with Lofi music, daylight cycle, MCP tool animations, and a mini activity feed.

**Architecture:** Extend existing Phaser.js office modules. Add Lofi player as DOM overlay (HTML5 Audio API). Add daylight overlay as Phaser graphics object. Extend agent animations for MCP tools. Add mini activity feed as DOM panel.

**Tech Stack:** Phaser.js 3.80 (existing), HTML5 Audio API, CSS for player/feed UI.

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `frontend/office/music.js` | Lofi player — playlist management, audio controls, UI |
| `frontend/office/daylight.js` | Daylight cycle — time-based overlay tinting |

### Modified Files

| File | Changes |
|------|---------|
| `frontend/office.html` | Add music player DOM, activity feed DOM, load new scripts |
| `frontend/office.css` | Add music player and activity feed styles |
| `frontend/office/agents.js` | Extend ANIMATION_MAP for MCP tools, add MCP bubble icons |
| `frontend/office/ws.js` | Forward events to activity feed |
| `frontend/office/tilemap.js` | Init daylight overlay in OfficeScene |

---

## Task 1: Lofi Music Player

**Files:**
- Create: `frontend/office/music.js`
- Modify: `frontend/office.html`
- Modify: `frontend/office.css`

- [ ] **Step 1: Add music player DOM to `office.html`**

Add before the closing `</body>` tag, before the script tags:

```html
<!-- Music Player -->
<div id="music-player" class="music-player">
  <div class="music-info">
    <span class="music-icon">🎵</span>
    <span id="music-title">Lofi Beats</span>
  </div>
  <div class="music-controls">
    <button id="music-prev" onclick="musicPlayer.prev()">⏮</button>
    <button id="music-toggle" onclick="musicPlayer.toggle()">▶</button>
    <button id="music-next" onclick="musicPlayer.next()">⏭</button>
  </div>
  <input type="range" id="music-volume" class="music-volume" min="0" max="100" value="30"
         oninput="musicPlayer.setVolume(this.value/100)">
  <select id="music-genre" onchange="musicPlayer.setGenre(this.value)">
    <option value="lofi">Lofi</option>
    <option value="jazz">Jazz</option>
    <option value="ambient">Ambient</option>
    <option value="classical">Classical</option>
  </select>
</div>
```

- [ ] **Step 2: Add music player CSS to `office.css`**

```css
.music-player {
  position: fixed;
  bottom: 16px;
  left: 16px;
  background: rgba(26, 26, 46, 0.9);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 12px;
  padding: 10px 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  z-index: 1000;
  backdrop-filter: blur(8px);
  color: #e0e0e0;
  font-family: 'Courier New', monospace;
  font-size: 12px;
}
.music-info { display: flex; align-items: center; gap: 6px; min-width: 100px; }
.music-icon { font-size: 16px; }
.music-controls { display: flex; gap: 4px; }
.music-controls button {
  background: none;
  border: 1px solid rgba(255,255,255,0.2);
  color: #e0e0e0;
  border-radius: 4px;
  padding: 4px 8px;
  cursor: pointer;
  font-size: 12px;
}
.music-controls button:hover { background: rgba(255,255,255,0.1); }
.music-volume {
  width: 60px;
  accent-color: #44ff88;
}
#music-genre {
  background: rgba(255,255,255,0.1);
  color: #e0e0e0;
  border: 1px solid rgba(255,255,255,0.2);
  border-radius: 4px;
  padding: 2px 4px;
  font-size: 11px;
}
```

- [ ] **Step 3: Create `frontend/office/music.js`**

```javascript
class MusicPlayer {
  constructor() {
    this.audio = new Audio();
    this.audio.loop = true;
    this.audio.volume = 0.3;
    this.playing = false;
    this.genre = 'lofi';
    this.trackIndex = 0;

    // Stream URLs for different genres (free/royalty-free streams)
    this.streams = {
      lofi: [
        // Placeholder URLs — user can configure in settings
        '/static/music/lofi.mp3',
      ],
      jazz: ['/static/music/jazz.mp3'],
      ambient: ['/static/music/ambient.mp3'],
      classical: ['/static/music/classical.mp3'],
    };

    // Fallback: use Web Audio API for generated ambient if no files exist
    this.audioCtx = null;
    this.oscillators = [];
  }

  toggle() {
    if (this.playing) {
      this.pause();
    } else {
      this.play();
    }
  }

  play() {
    const tracks = this.streams[this.genre] || [];
    if (tracks.length > 0) {
      const src = tracks[this.trackIndex % tracks.length];
      if (this.audio.src !== location.origin + src) {
        this.audio.src = src;
      }
      this.audio.play().catch(() => {
        // Autoplay blocked — generate ambient instead
        this._playGeneratedAmbient();
      });
    } else {
      this._playGeneratedAmbient();
    }
    this.playing = true;
    document.getElementById('music-toggle').textContent = '⏸';
  }

  pause() {
    this.audio.pause();
    this._stopGenerated();
    this.playing = false;
    document.getElementById('music-toggle').textContent = '▶';
  }

  next() {
    this.trackIndex++;
    if (this.playing) this.play();
  }

  prev() {
    this.trackIndex = Math.max(0, this.trackIndex - 1);
    if (this.playing) this.play();
  }

  setVolume(v) {
    this.audio.volume = v;
    if (this.gainNode) this.gainNode.gain.value = v * 0.3;
  }

  setGenre(genre) {
    this.genre = genre;
    this.trackIndex = 0;
    if (this.playing) this.play();
  }

  // Generate simple ambient pad sound when no audio files available
  _playGeneratedAmbient() {
    this._stopGenerated();
    this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    this.gainNode = this.audioCtx.createGain();
    this.gainNode.gain.value = this.audio.volume * 0.3;
    this.gainNode.connect(this.audioCtx.destination);

    // Soft pad: layered detuned oscillators
    const freqs = [220, 277.18, 329.63, 440];
    freqs.forEach(f => {
      const osc = this.audioCtx.createOscillator();
      osc.type = 'sine';
      osc.frequency.value = f;
      osc.detune.value = Math.random() * 10 - 5;
      const oscGain = this.audioCtx.createGain();
      oscGain.gain.value = 0.08;
      osc.connect(oscGain);
      oscGain.connect(this.gainNode);
      osc.start();
      this.oscillators.push(osc);
    });
  }

  _stopGenerated() {
    this.oscillators.forEach(o => { try { o.stop(); } catch {} });
    this.oscillators = [];
    if (this.audioCtx) {
      this.audioCtx.close().catch(() => {});
      this.audioCtx = null;
    }
  }
}

const musicPlayer = new MusicPlayer();
```

- [ ] **Step 4: Add script tag to `office.html`**

Add before the existing office scripts:
```html
<script src="/static/office/music.js"></script>
```

- [ ] **Step 5: Create music directory**

```bash
mkdir -p frontend/music
```

- [ ] **Step 6: Commit**

```bash
git add frontend/office/music.js frontend/office.html frontend/office.css
git commit -m "feat(office): add lofi music player with genre selection and generated ambient fallback"
```

---

## Task 2: Daylight Cycle

**Files:**
- Create: `frontend/office/daylight.js`
- Modify: `frontend/office/tilemap.js`
- Modify: `frontend/office.html`

- [ ] **Step 1: Create `frontend/office/daylight.js`**

```javascript
class DaylightCycle {
  constructor(scene) {
    this.scene = scene;
    this.overlay = null;
    this._createOverlay();
    this._updateTimer = null;
  }

  _createOverlay() {
    const { width, height } = this.scene.tilemap.getWorldBounds();
    this.overlay = this.scene.add.rectangle(
      width / 2, height / 2, width * 2, height * 2, 0x000000, 0
    );
    this.overlay.setDepth(50); // Above tiles, below UI
    this.overlay.setScrollFactor(1);
    this.update();

    // Update every 60 seconds
    this._updateTimer = this.scene.time.addEvent({
      delay: 60000,
      callback: () => this.update(),
      loop: true,
    });
  }

  update() {
    const hour = new Date().getHours();
    const minute = new Date().getMinutes();
    const t = hour + minute / 60;

    let color, alpha;

    if (t >= 6 && t < 8) {
      // Dawn: warm orange, fading out
      color = 0xff9944;
      alpha = 0.15 * (1 - (t - 6) / 2);
    } else if (t >= 8 && t < 17) {
      // Day: no overlay
      color = 0x000000;
      alpha = 0;
    } else if (t >= 17 && t < 19) {
      // Sunset: warm orange, fading in
      color = 0xff6622;
      alpha = 0.15 * ((t - 17) / 2);
    } else if (t >= 19 && t < 21) {
      // Evening: blue tint, increasing
      color = 0x112244;
      alpha = 0.1 + 0.15 * ((t - 19) / 2);
    } else {
      // Night: dark blue overlay
      color = 0x0a0a2e;
      alpha = 0.35;
    }

    this.overlay.setFillStyle(color, alpha);
  }

  destroy() {
    if (this._updateTimer) this._updateTimer.destroy();
    if (this.overlay) this.overlay.destroy();
  }
}
```

- [ ] **Step 2: Add script tag to `office.html`**

Add before tilemap.js:
```html
<script src="/static/office/daylight.js"></script>
```

- [ ] **Step 3: Init daylight in `tilemap.js` OfficeScene**

In `OfficeScene.create()`, after all other managers are initialized, add:
```javascript
this.daylight = new DaylightCycle(this);
```

The `DaylightCycle` needs access to `this.tilemap` (the TilemapManager), so it must come after tilemap init. The constructor references `this.scene.tilemap` — adjust if the property is named differently (check actual property name in OfficeScene).

- [ ] **Step 4: Commit**

```bash
git add frontend/office/daylight.js frontend/office/tilemap.js frontend/office.html
git commit -m "feat(office): add daylight cycle — time-based lighting overlay"
```

---

## Task 3: MCP Tool Animations + Activity Feed

**Files:**
- Modify: `frontend/office/agents.js`
- Modify: `frontend/office/ws.js`
- Modify: `frontend/office.html`
- Modify: `frontend/office.css`

- [ ] **Step 1: Extend ANIMATION_MAP in `agents.js`**

Find the `ANIMATION_MAP` constant and extend it:

```javascript
const ANIMATION_MAP = {
  typing: 'sit',
  reading: 'phone',
  thinking: 'idle_anim',
  running: 'run',
  // MCP tool animations
  mcp_reminder: 'phone',     // Holds up phone for reminders
  mcp_calendar: 'phone',     // Phone for calendar
  mcp_music: 'idle_anim',    // Relaxed idle for music
  mcp_homekit: 'sit',        // Sitting, controlling devices
  mcp_notes: 'sit',          // Writing notes
  mcp_shell: 'sit',          // Terminal work
  mcp_default: 'idle_anim',  // Default MCP animation
};
```

- [ ] **Step 2: Update `onToolUse` in `agents.js` to handle MCP tool names**

Find the `onToolUse` method. Add MCP tool name mapping before the animation lookup:

```javascript
onToolUse(agentName, toolName, animHint, crewId) {
  const id = crewId || agentName;
  const agent = this.agents.get(id);
  if (!agent) return;

  // Map MCP tool names to animation keys
  let animKey = animHint;
  if (toolName && toolName.startsWith('mcp_')) {
    if (toolName.includes('reminder') || toolName.includes('calendar')) {
      animKey = 'mcp_reminder';
    } else if (toolName.includes('music')) {
      animKey = 'mcp_music';
    } else if (toolName.includes('homekit') || toolName.includes('light')) {
      animKey = 'mcp_homekit';
    } else if (toolName.includes('note')) {
      animKey = 'mcp_notes';
    } else if (toolName.includes('shell') || toolName.includes('command')) {
      animKey = 'mcp_shell';
    } else {
      animKey = 'mcp_default';
    }
  }

  const anim = ANIMATION_MAP[animKey] || ANIMATION_MAP[animHint] || 'sit';
  // ... rest of existing animation logic
}
```

- [ ] **Step 3: Add MCP-specific bubble icons**

In the bubble creation (either in `bubbles.js` or where `showBubble` is called in `ws.js`), add emoji prefixes for MCP tools:

```javascript
// In ws.js tool_use handler, before showBubble:
let bubbleText = data.tool_name || data.label || '';
if (bubbleText.startsWith('mcp_')) {
  const icons = {
    reminder: '⏰', calendar: '📅', music: '🎵',
    homekit: '💡', note: '📝', shell: '💻',
  };
  for (const [key, icon] of Object.entries(icons)) {
    if (bubbleText.includes(key)) { bubbleText = `${icon} ${bubbleText}`; break; }
  }
}
```

- [ ] **Step 4: Add activity feed DOM to `office.html`**

```html
<!-- Activity Feed (mini) -->
<div id="activity-feed" class="office-activity-feed">
  <div class="feed-header">Aktivitäten</div>
  <div id="feed-entries"></div>
</div>
```

- [ ] **Step 5: Add activity feed CSS to `office.css`**

```css
.office-activity-feed {
  position: fixed;
  bottom: 16px;
  right: 16px;
  width: 250px;
  max-height: 200px;
  background: rgba(26, 26, 46, 0.85);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 12px;
  padding: 10px 14px;
  z-index: 1000;
  backdrop-filter: blur(8px);
  color: #e0e0e0;
  font-family: 'Courier New', monospace;
  font-size: 11px;
  overflow-y: auto;
  transition: opacity 0.5s;
}
.office-activity-feed.faded { opacity: 0.3; }
.feed-header {
  font-weight: bold;
  margin-bottom: 6px;
  color: #44ff88;
  font-size: 12px;
}
.feed-entry {
  padding: 3px 0;
  border-bottom: 1px solid rgba(255,255,255,0.05);
  display: flex;
  gap: 6px;
}
.feed-entry .feed-time { color: #666; min-width: 45px; }
```

- [ ] **Step 6: Add activity feed logic to `ws.js`**

```javascript
// Activity feed management
const feedEntries = [];
const FEED_MAX = 8;
let feedFadeTimer = null;

function addFeedEntry(icon, text) {
  const time = new Date().toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
  feedEntries.unshift({ icon, text, time });
  if (feedEntries.length > FEED_MAX) feedEntries.pop();
  renderFeed();
  // Reset fade timer
  const feed = document.getElementById('activity-feed');
  feed.classList.remove('faded');
  clearTimeout(feedFadeTimer);
  feedFadeTimer = setTimeout(() => feed.classList.add('faded'), 10000);
}

function renderFeed() {
  const el = document.getElementById('feed-entries');
  if (!el) return;
  el.innerHTML = feedEntries.map(e =>
    `<div class="feed-entry"><span class="feed-time">${e.time}</span><span>${e.icon} ${e.text}</span></div>`
  ).join('');
}
```

Then in the WS message handler, add `addFeedEntry()` calls:
- `agent_spawn`: `addFeedEntry('🤖', crew + ' gestartet')`
- `agent_done`: `addFeedEntry('✅', crew + ' fertig')`
- `agent_error`: `addFeedEntry('❌', crew + ' Fehler')`
- `tool_use`: `addFeedEntry('🔧', toolName)`

- [ ] **Step 7: Commit**

```bash
git add frontend/office/agents.js frontend/office/ws.js frontend/office.html frontend/office.css
git commit -m "feat(office): add MCP tool animations, bubble icons, and activity feed"
```

---

## Task 4: Final Polish — Back Button + Visual Refinements

**Files:**
- Modify: `frontend/office.html`
- Modify: `frontend/office.css`

- [ ] **Step 1: Add "Zurück" button to navigate back to Command Center**

Add to office.html:
```html
<a href="/" id="back-btn" class="office-back-btn">← Zurück</a>
```

CSS:
```css
.office-back-btn {
  position: fixed;
  top: 16px;
  right: 16px;
  background: rgba(26, 26, 46, 0.9);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 8px;
  padding: 8px 16px;
  color: #e0e0e0;
  text-decoration: none;
  font-family: 'Courier New', monospace;
  font-size: 13px;
  z-index: 1000;
  backdrop-filter: blur(8px);
}
.office-back-btn:hover { background: rgba(68, 255, 136, 0.2); }
```

- [ ] **Step 2: Commit**

```bash
git add frontend/office.html frontend/office.css
git commit -m "feat(office): add back button and visual polish"
```
