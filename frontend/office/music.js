/**
 * MusicPlayer — local HTML5 audio + Web Audio fallback + Apple Music via MCP
 * Genres: lofi, jazz, ambient, classical + apple_* variants
 * Falls back to a generated ambient pad when local audio is unavailable
 */
class MusicPlayer {
  constructor() {
    this.volume = parseFloat(localStorage.getItem('music_volume') ?? '0.3');
    this.genre = localStorage.getItem('music_genre') || 'lofi';
    this.isPlaying = false;
    this.currentIndex = 0;
    this.audio = null;
    this.audioCtx = null;
    this.generatorNodes = [];
    this._pulseInterval = null;
    this._jazzPitchTimer = null;
    this._classicalSwellTimer = null;

    this.genres = {
      lofi:      { label: 'Lofi Beats',      tracks: ['/static/music/lofi_loop.wav'] },
      jazz:      { label: 'Jazz Vibes',       tracks: ['/static/music/jazz_loop.wav'] },
      ambient:   { label: 'Ambient Waves',    tracks: ['/static/music/ambient_loop.wav'] },
      classical: { label: 'Classical Piano',  tracks: ['/static/music/classical_loop.wav'] },
      custom:    { label: 'Eigene Musik',     tracks: [] },
      apple_lofi:      { label: 'Apple Lofi',      tracks: [] },
      apple_jazz:      { label: 'Apple Jazz',       tracks: [] },
      apple_ambient:   { label: 'Apple Ambient',    tracks: [] },
      apple_classical: { label: 'Apple Classical',  tracks: [] },
    };

    // Ambient pad config per genre (used when mp3 not found)
    // freqs: distinct chord per genre, detune in cents, lfoRate: LFO Hz (0 = no LFO)
    this.padConfig = {
      lofi:      { freqs: [130.81, 164.81, 196, 246.94], detune: 12, gain: 0.08, lfoRate: 0.05 },
      jazz:      { freqs: [146.83, 174.61, 220, 261.63], detune: 8,  gain: 0.07, lfoRate: 0.12 },
      ambient:   { freqs: [65.41, 98, 130.81],           detune: 20, gain: 0.06, lfoRate: 0.02 },
      classical: { freqs: [261.63, 329.63, 392, 523.25], detune: 2,  gain: 0.07, lfoRate: 0 },
    };

    // Apple Music search terms per genre
    this._appleMusicTerms = {
      apple_lofi:      'lofi beats chill',
      apple_jazz:      'jazz cafe smooth',
      apple_ambient:   'ambient relaxation',
      apple_classical: 'classical piano peaceful',
    };
  }

  _isAppleGenre(g) {
    return (g || this.genre).startsWith('apple_');
  }

  _currentTracks() {
    if (this.genre === 'custom') {
      return this._getCustomPlaylist();
    }
    return this.genres[this.genre]?.tracks || [];
  }

  _getCustomPlaylist() {
    return (localStorage.getItem('music_custom_playlist') || '')
      .split('\n')
      .map(line => line.trim())
      .filter(Boolean);
  }

  _updateTitle() {
    const genreLabel = this.genres[this.genre]?.label || this.genre;
    const tracks = this._currentTracks();
    const trackNum = (!this._isAppleGenre() && tracks.length > 0)
      ? ` ${this.currentIndex + 1}/${tracks.length}` : '';
    const el = document.getElementById('music-title');
    if (el) el.textContent = genreLabel + trackNum;
    this._updateSubtitle();
    this._updateBadge();
  }

  _updateToggleBtn(playing) {
    const btn = document.getElementById('music-toggle');
    if (btn) btn.textContent = playing ? '⏸' : '▶';
  }

  _updateSubtitle(text = '') {
    const el = document.getElementById('music-subtitle');
    if (!el) return;
    if (text) {
      el.textContent = text;
      return;
    }
    if (this._isAppleGenre()) {
      el.textContent = 'Apple Music Anfrage';
      return;
    }
    if (this.genre === 'custom') {
      const playlist = this._getCustomPlaylist();
      if (playlist.length === 0) {
        el.textContent = 'Eigene Quelle fehlt noch';
        return;
      }
      try {
        const firstTrack = new URL(playlist[0]);
        el.textContent = playlist.length > 1
          ? `${firstTrack.host} · ${playlist.length} Tracks`
          : (firstTrack.host || 'Eigene Audio-Quelle');
      } catch (_) {
        el.textContent = playlist.length > 1 ? `Eigene Playlist · ${playlist.length} Tracks` : 'Eigene Audio-Quelle';
      }
      return;
    }
    el.textContent = 'Lokale Loop';
  }

  _updateBadge(text = '') {
    const el = document.getElementById('music-badge');
    if (!el) return;
    if (text) {
      el.textContent = text;
      return;
    }
    if (this._isAppleGenre()) {
      el.textContent = 'apple';
    } else if (this.genre === 'custom') {
      el.textContent = 'custom';
    } else {
      el.textContent = 'lokal';
    }
  }

  _syncCustomUrlUI() {
    const row = document.getElementById('music-custom-row');
    const input = document.getElementById('music-custom-url');
    if (!row || !input) return;
    const isCustom = this.genre === 'custom';
    row.classList.toggle('hidden', !isCustom);
    input.value = (localStorage.getItem('music_custom_playlist') || '').trim();
  }

  _setPulse(active) {
    clearInterval(this._pulseInterval);
    const icon = document.querySelector('#music-player .music-icon');
    if (!icon) return;
    if (active) {
      icon.style.transition = 'opacity 0.6s ease-in-out';
      let visible = true;
      this._pulseInterval = setInterval(() => {
        visible = !visible;
        icon.style.opacity = visible ? '1' : '0.3';
      }, 600);
    } else {
      icon.style.opacity = '1';
    }
  }

  /* ── HTML5 Audio playback ── */

  _playTrack(url) {
    this._stopAudio();
    this.audio = new Audio(url);
    this.audio.volume = this.volume;
    this.audio.loop = false;
    this.audio.addEventListener('ended', () => this._nextTrack());
    this.audio.addEventListener('error', () => {
      // Local audio not available — fall back to generated pad
      console.info(`MusicPlayer: ${url} not found, using generated pad`);
      this._stopAudio();
      this._updateSubtitle('Generator-Fallback aktiv');
      this._updateBadge('fallback');
      this._startGeneratedPad();
    });
    this.audio.play().catch(() => {
      this._stopAudio();
      this._updateSubtitle('Generator-Fallback aktiv');
      this._updateBadge('fallback');
      this._startGeneratedPad();
    });
  }

  _stopAudio() {
    if (this.audio) {
      this.audio.pause();
      this.audio.src = '';
      this.audio = null;
    }
  }

  /* ── Apple Music via Falkenstein API ── */

  async _playAppleMusic(genre) {
    const term = this._appleMusicTerms[genre] || 'lofi beats';
    try {
      const token = localStorage.getItem('falkenstein_token');
      const resp = await fetch('/api/admin/assist', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { 'Authorization': 'Bearer ' + token } : {}),
        },
        body: JSON.stringify({ text: `Spiel "${term}" auf Apple Music`, direct_only: true }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const payload = await resp.json();
      if (payload?.status !== 'ok') throw new Error(payload?.error || 'MCP request failed');
      if (String(payload?.result || '').toLowerCase().includes('kein passendes mcp-tool aktiv')) {
        throw new Error(payload.result);
      }
      const el = document.getElementById('music-title');
      if (el) el.textContent = `Apple Music: ${genre.replace('apple_', '')}`;
      this._updateSubtitle('Streaming via MCP');
      this._updateBadge('apple');
      this.isPlaying = true;
      this._updateToggleBtn(true);
      this._setPulse(true);
      console.info(`MusicPlayer: Apple Music gestartet — "${term}"`);
    } catch (e) {
      console.warn('MusicPlayer: Apple Music nicht verfügbar, nutze generierten Pad', e);
      // map apple genre to local fallback
      const fallback = genre.replace('apple_', '');
      const savedGenre = this.genre;
      this.genre = fallback in this.padConfig ? fallback : 'ambient';
      this._startGeneratedPad();
      this.genre = savedGenre;
      const el = document.getElementById('music-title');
      if (el) el.textContent = `Fallback: ${fallback}`;
      this._updateSubtitle('Lokaler Synth aktiv');
      this._updateBadge('fallback');
    }
  }

  /* ── Web Audio fallback: layered detuned sine oscillators ── */

  _ensureAudioCtx() {
    if (!this.audioCtx) {
      this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (this.audioCtx.state === 'suspended') {
      this.audioCtx.resume();
    }
    return this.audioCtx;
  }

  // Brownian/pink noise buffer for lofi texture
  _createNoiseBuffer(ctx, seconds = 3) {
    const bufSize = ctx.sampleRate * seconds;
    const buf = ctx.createBuffer(1, bufSize, ctx.sampleRate);
    const data = buf.getChannelData(0);
    let lastOut = 0;
    for (let i = 0; i < bufSize; i++) {
      const white = Math.random() * 2 - 1;
      // Simple brownian noise: integrate white noise with leak
      lastOut = (lastOut + 0.02 * white) / 1.02;
      data[i] = lastOut * 3.5;
    }
    return buf;
  }

  _startGeneratedPad() {
    const ctx = this._ensureAudioCtx();
    const genre = this._isAppleGenre() ? this.genre.replace('apple_', '') : this.genre;
    const cfg = this.padConfig[genre] || this.padConfig.ambient;
    this._stopGeneratedPad();

    // Master output gain
    const masterGain = ctx.createGain();
    masterGain.gain.value = this.volume;
    masterGain.connect(ctx.destination);
    this.generatorNodes.push(masterGain);

    // ── Genre-specific effects ──

    // AMBIENT: feedback delay (simple reverb-like effect)
    let ambientDelay = null;
    let ambientFeedback = null;
    if (genre === 'ambient') {
      ambientDelay = ctx.createDelay(2.0);
      ambientDelay.delayTime.value = 0.45;
      ambientFeedback = ctx.createGain();
      ambientFeedback.gain.value = 0.55;
      ambientDelay.connect(ambientFeedback);
      ambientFeedback.connect(ambientDelay);
      ambientDelay.connect(masterGain);
      this.generatorNodes.push(ambientDelay, ambientFeedback);
    }

    // LOFI: subtle brownian noise layer
    if (genre === 'lofi') {
      const noiseBuf = this._createNoiseBuffer(ctx);
      const noiseSource = ctx.createBufferSource();
      noiseSource.buffer = noiseBuf;
      noiseSource.loop = true;
      const noiseGain = ctx.createGain();
      noiseGain.gain.value = 0.012 * this.volume; // very quiet
      noiseSource.connect(noiseGain);
      noiseGain.connect(masterGain);
      noiseSource.start();
      this.generatorNodes.push(noiseSource, noiseGain);
    }

    // Build oscillators
    const oscNodes = [];
    cfg.freqs.forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const gainNode = ctx.createGain();
      const detune = (i % 2 === 0 ? 1 : -1) * cfg.detune * (i + 1) * 0.5;

      osc.type = 'sine';
      osc.frequency.value = freq;
      osc.detune.value = detune;

      gainNode.gain.value = cfg.gain;
      osc.connect(gainNode);

      if (genre === 'ambient' && ambientDelay) {
        gainNode.connect(ambientDelay);
      }
      gainNode.connect(masterGain);

      osc.start();
      this.generatorNodes.push(osc, gainNode);
      oscNodes.push({ osc, gainNode });

      // Slow LFO tremolo — skip for genres with lfoRate === 0 (e.g. classical)
      if (cfg.lfoRate > 0) {
        const lfo = ctx.createOscillator();
        const lfoGain = ctx.createGain();
        lfo.type = 'sine';
        lfo.frequency.value = cfg.lfoRate + i * 0.01;
        lfoGain.gain.value = cfg.gain * 0.3;
        lfo.connect(lfoGain);
        lfoGain.connect(gainNode.gain);
        lfo.start();
        this.generatorNodes.push(lfo, lfoGain);
      }
    });

    // JAZZ: random pitch variations every few seconds (simulated improvisation)
    if (genre === 'jazz') {
      clearTimeout(this._jazzPitchTimer);
      const jazzVariation = () => {
        if (!this.isPlaying) return;
        oscNodes.forEach(({ osc }) => {
          const shift = (Math.random() - 0.5) * 30; // ±15 cents
          osc.detune.setTargetAtTime(osc.detune.value + shift, ctx.currentTime, 0.3);
        });
        const delay = 2000 + Math.random() * 3000; // 2–5 s
        this._jazzPitchTimer = setTimeout(jazzVariation, delay);
      };
      this._jazzPitchTimer = setTimeout(jazzVariation, 2000);
    }

    // CLASSICAL: volume swells (crescendo/decrescendo)
    if (genre === 'classical') {
      clearTimeout(this._classicalSwellTimer);
      const swellCycle = () => {
        if (!this.isPlaying) return;
        const now = ctx.currentTime;
        const swellDuration = 4 + Math.random() * 3; // 4–7 s per phase
        // Crescendo
        masterGain.gain.setTargetAtTime(this.volume * 1.4, now, swellDuration * 0.4);
        // Decrescendo back
        masterGain.gain.setTargetAtTime(this.volume * 0.6, now + swellDuration * 0.5, swellDuration * 0.4);
        // Restore base
        masterGain.gain.setTargetAtTime(this.volume, now + swellDuration, 0.8);
        this._classicalSwellTimer = setTimeout(swellCycle, (swellDuration + 2) * 1000);
      };
      this._classicalSwellTimer = setTimeout(swellCycle, 3000);
    }

    this.isPlaying = true;
    this._updateToggleBtn(true);
    this._updateTitle();
    this._setPulse(true);
  }

  _stopGeneratedPad() {
    clearTimeout(this._jazzPitchTimer);
    clearTimeout(this._classicalSwellTimer);
    this.generatorNodes.forEach(node => {
      try { node.disconnect(); } catch (_) {}
      if (node.stop) { try { node.stop(); } catch (_) {} }
    });
    this.generatorNodes = [];
  }

  _updateGeneratedPadVolume() {
    const ctx = this.audioCtx;
    if (!ctx) return;
    // Update master gain (first GainNode pushed is the masterGain)
    const master = this.generatorNodes.find(n => n instanceof GainNode);
    if (master) {
      master.gain.setTargetAtTime(this.volume, ctx.currentTime, 0.1);
    }
  }

  /* ── Track navigation ── */

  _nextTrack() {
    const tracks = this._currentTracks();
    if (tracks.length > 0) {
      this.currentIndex = (this.currentIndex + 1) % tracks.length;
    }
    if (this.isPlaying) this._startPlayback();
  }

  _prevTrack() {
    const tracks = this._currentTracks();
    if (tracks.length > 0) {
      this.currentIndex = (this.currentIndex - 1 + tracks.length) % tracks.length;
    }
    if (this.isPlaying) this._startPlayback();
  }

  _startPlayback() {
    if (this._isAppleGenre()) {
      this._playAppleMusic(this.genre);
      return;
    }
    const tracks = this._currentTracks();
    if (tracks.length > 0) {
      this._playTrack(tracks[this.currentIndex]);
      this._updateTitle();
    } else {
      this._startGeneratedPad();
      this._updateTitle();
      this._updateSubtitle(this.genre === 'custom' ? 'Keine URL gesetzt, Synth aktiv' : 'Lokaler Synth aktiv');
      this._updateBadge(this.genre === 'custom' ? 'custom' : 'fallback');
    }
    this.isPlaying = true;
    this._updateToggleBtn(true);
    this._setPulse(true);
  }

  _stopPlayback() {
    this._stopAudio();
    this._stopGeneratedPad();
    this.isPlaying = false;
    this._updateToggleBtn(false);
    this._setPulse(false);
    this._updateTitle();
  }

  /* ── Public API ── */

  toggle() {
    if (this.isPlaying) {
      this._stopPlayback();
    } else {
      // Resume AudioContext if needed (browser autoplay policy)
      if (this.audioCtx) this.audioCtx.resume();
      this._startPlayback();
    }
  }

  next() {
    if (!this._isAppleGenre()) this._nextTrack();
  }

  prev() {
    if (!this._isAppleGenre()) this._prevTrack();
  }

  setVolume(v) {
    this.volume = Math.max(0, Math.min(1, v));
    if (this.audio) this.audio.volume = this.volume;
    this._updateGeneratedPadVolume();
    const slider = document.getElementById('music-volume');
    if (slider) slider.value = Math.round(this.volume * 100);
    localStorage.setItem('music_volume', String(this.volume));
  }

  setGenre(g) {
    if (!this.genres[g]) return;
    const wasPlaying = this.isPlaying;
    this._stopPlayback();
    this.genre = g;
    this.currentIndex = 0;
    localStorage.setItem('music_genre', g);
    this._syncCustomUrlUI();
    if (wasPlaying) this._startPlayback();
    else this._updateTitle();
  }

  saveCustomPlaylist() {
    const input = document.getElementById('music-custom-url');
    if (!input) return;
    const playlist = input.value
      .split('\n')
      .map(line => line.trim())
      .filter(Boolean);
    if (playlist.length === 0) {
      localStorage.removeItem('music_custom_playlist');
    } else {
      localStorage.setItem('music_custom_playlist', playlist.join('\n'));
    }
    if (this.genre === 'custom') {
      const wasPlaying = this.isPlaying;
      this._stopPlayback();
      if (wasPlaying) this._startPlayback();
      else this._updateTitle();
    }
  }

  clearCustomUrl() {
    localStorage.removeItem('music_custom_playlist');
    const input = document.getElementById('music-custom-url');
    if (input) input.value = '';
    if (this.genre === 'custom') {
      const wasPlaying = this.isPlaying;
      this._stopPlayback();
      if (wasPlaying) this._startPlayback();
      else this._updateTitle();
    }
  }

  /* ── Init: restore persisted state and sync UI ── */
  init() {
    const volumeSlider = document.getElementById('music-volume');
    if (volumeSlider) volumeSlider.value = Math.round(this.volume * 100);

    const genreSelect = document.getElementById('music-genre');
    if (genreSelect && this.genres[this.genre]) genreSelect.value = this.genre;

    const customInput = document.getElementById('music-custom-url');
    if (customInput) {
      customInput.addEventListener('keydown', (event) => {
        if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
          event.preventDefault();
          this.saveCustomPlaylist();
        }
      });
    }

    this._syncCustomUrlUI();
    this._updateTitle();
  }
}

const musicPlayer = new MusicPlayer();
window.musicPlayer = musicPlayer;
// Run init after DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => musicPlayer.init());
} else {
  musicPlayer.init();
}
