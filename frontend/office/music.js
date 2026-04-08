/**
 * MusicPlayer — HTML5 Audio + Web Audio API fallback
 * Genres: lofi, jazz, ambient, classical
 * Falls back to procedurally generated ambient pad when no .mp3 files are present
 */
class MusicPlayer {
  constructor() {
    this.volume = 0.3;
    this.genre = 'lofi';
    this.isPlaying = false;
    this.currentIndex = 0;
    this.audio = null;
    this.audioCtx = null;
    this.generatorNodes = [];

    this.genres = {
      lofi:      { label: 'Lofi Beats',      tracks: ['/static/music/lofi_1.mp3', '/static/music/lofi_2.mp3'] },
      jazz:      { label: 'Jazz Vibes',       tracks: ['/static/music/jazz_1.mp3', '/static/music/jazz_2.mp3'] },
      ambient:   { label: 'Ambient Pads',     tracks: ['/static/music/ambient_1.mp3', '/static/music/ambient_2.mp3'] },
      classical: { label: 'Classical Focus',  tracks: ['/static/music/classical_1.mp3', '/static/music/classical_2.mp3'] },
    };

    // Ambient pad config per genre (used when mp3 not found)
    this.padConfig = {
      lofi:      { freqs: [110, 165, 220, 277.18], detune: 12, gain: 0.08 },
      jazz:      { freqs: [138.59, 174.61, 220, 293.66], detune: 8, gain: 0.07 },
      ambient:   { freqs: [55, 82.41, 110, 130.81], detune: 20, gain: 0.06 },
      classical: { freqs: [130.81, 164.81, 196, 246.94], detune: 5, gain: 0.07 },
    };
  }

  _currentTracks() {
    return this.genres[this.genre]?.tracks || [];
  }

  _updateTitle() {
    const genreLabel = this.genres[this.genre]?.label || this.genre;
    const tracks = this._currentTracks();
    const trackNum = tracks.length > 0 ? ` ${this.currentIndex + 1}/${tracks.length}` : '';
    const el = document.getElementById('music-title');
    if (el) el.textContent = genreLabel + trackNum;
  }

  _updateToggleBtn(playing) {
    const btn = document.getElementById('music-toggle');
    if (btn) btn.textContent = playing ? '⏸' : '▶';
  }

  /* ── HTML5 Audio playback ── */

  _playTrack(url) {
    this._stopAudio();
    this.audio = new Audio(url);
    this.audio.volume = this.volume;
    this.audio.loop = false;
    this.audio.addEventListener('ended', () => this._nextTrack());
    this.audio.addEventListener('error', () => {
      // mp3 not available — fall back to generated pad
      console.info(`MusicPlayer: ${url} not found, using generated pad`);
      this._stopAudio();
      this._startGeneratedPad();
    });
    this.audio.play().catch(() => {
      this._stopAudio();
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

  _startGeneratedPad() {
    const ctx = this._ensureAudioCtx();
    const cfg = this.padConfig[this.genre] || this.padConfig.ambient;
    this._stopGeneratedPad();

    cfg.freqs.forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const gainNode = ctx.createGain();
      const detune = (i % 2 === 0 ? 1 : -1) * cfg.detune * (i + 1) * 0.5;

      osc.type = 'sine';
      osc.frequency.value = freq;
      osc.detune.value = detune;

      // Slow LFO tremolo
      const lfo = ctx.createOscillator();
      const lfoGain = ctx.createGain();
      lfo.type = 'sine';
      lfo.frequency.value = 0.08 + i * 0.03;
      lfoGain.gain.value = cfg.gain * 0.3;
      lfo.connect(lfoGain);
      lfoGain.connect(gainNode.gain);

      gainNode.gain.value = cfg.gain * this.volume;
      osc.connect(gainNode);
      gainNode.connect(ctx.destination);

      osc.start();
      lfo.start();

      this.generatorNodes.push(osc, lfo, gainNode, lfoGain);
    });

    this.isPlaying = true;
    this._updateToggleBtn(true);
    this._updateTitle();
  }

  _stopGeneratedPad() {
    this.generatorNodes.forEach(node => {
      try { node.disconnect(); } catch (_) {}
      if (node.stop) { try { node.stop(); } catch (_) {} }
    });
    this.generatorNodes = [];
  }

  _updateGeneratedPadVolume() {
    const ctx = this.audioCtx;
    if (!ctx) return;
    this.generatorNodes.forEach(node => {
      if (node instanceof GainNode) {
        // Only update main gain nodes (not LFO gains)
        if (node.gain.value > 0.001) {
          node.gain.setTargetAtTime(this.volume * 0.08, ctx.currentTime, 0.1);
        }
      }
    });
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
    const tracks = this._currentTracks();
    if (tracks.length > 0) {
      this._playTrack(tracks[this.currentIndex]);
    } else {
      this._startGeneratedPad();
    }
    this.isPlaying = true;
    this._updateToggleBtn(true);
    this._updateTitle();
  }

  _stopPlayback() {
    this._stopAudio();
    this._stopGeneratedPad();
    this.isPlaying = false;
    this._updateToggleBtn(false);
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
    this._nextTrack();
  }

  prev() {
    this._prevTrack();
  }

  setVolume(v) {
    this.volume = Math.max(0, Math.min(1, v));
    if (this.audio) this.audio.volume = this.volume;
    this._updateGeneratedPadVolume();
    const slider = document.getElementById('music-volume');
    if (slider) slider.value = Math.round(this.volume * 100);
  }

  setGenre(g) {
    if (!this.genres[g]) return;
    const wasPlaying = this.isPlaying;
    this._stopPlayback();
    this.genre = g;
    this.currentIndex = 0;
    if (wasPlaying) this._startPlayback();
    else this._updateTitle();
  }
}

window.musicPlayer = new MusicPlayer();
