/* FitzLandia — audio.js  (tiny WebAudio synth, no files needed) */
'use strict';
const Audio_ = {
  ctx: null, enabled: true, master: null, whoosh: null, whooshGain: null,
  init() {
    if (this.ctx) return;
    try {
      const AC = window.AudioContext || window.webkitAudioContext; this.ctx = new AC();
      this.master = this.ctx.createGain(); this.master.gain.value = 0.5; this.master.connect(this.ctx.destination);
      // whoosh: filtered noise
      const size = this.ctx.sampleRate * 2, buf = this.ctx.createBuffer(1, size, this.ctx.sampleRate), d = buf.getChannelData(0);
      for (let i = 0; i < size; i++) d[i] = Math.random() * 2 - 1;
      const src = this.ctx.createBufferSource(); src.buffer = buf; src.loop = true;
      const f = this.ctx.createBiquadFilter(); f.type = 'bandpass'; f.frequency.value = 600; f.Q.value = 0.7;
      this.whooshGain = this.ctx.createGain(); this.whooshGain.gain.value = 0;
      src.connect(f); f.connect(this.whooshGain); this.whooshGain.connect(this.master); src.start();
      this.whoosh = f;
    } catch (e) { this.ctx = null; }
  },
  resume() { if (this.ctx && this.ctx.state !== 'running') this.ctx.resume(); },
  tone(freq, dur = 0.12, type = 'sine', vol = 0.3, when = 0) {
    if (!this.ctx || !this.enabled) return;
    const t = this.ctx.currentTime + when; const o = this.ctx.createOscillator(), g = this.ctx.createGain();
    o.type = type; o.frequency.value = freq; g.gain.setValueAtTime(vol, t); g.gain.exponentialRampToValueAtTime(0.001, t + dur);
    o.connect(g); g.connect(this.master); o.start(t); o.stop(t + dur + 0.02);
  },
  click() { this.tone(880, 0.06, 'square', 0.12); },
  pop() { this.tone(520, 0.1, 'triangle', 0.3); this.tone(780, 0.12, 'triangle', 0.2, 0.05); },
  coin() { this.tone(1320, 0.1, 'square', 0.15); this.tone(1760, 0.18, 'square', 0.15, 0.08); },
  fail() { this.tone(300, 0.25, 'sawtooth', 0.2); this.tone(220, 0.4, 'sawtooth', 0.2, 0.22); },
  fanfare() { [523, 659, 784, 1047].forEach((f, i) => this.tone(f, 0.25, 'triangle', 0.3, i * 0.12)); this.tone(1319, 0.6, 'triangle', 0.3, 0.5); },
  cheer() { for (let i = 0; i < 6; i++) this.tone(600 + Math.random() * 600, 0.15, 'triangle', 0.08, Math.random() * 0.4); },
  splash() { if (!this.ctx || !this.enabled) return; const t = this.ctx.currentTime; const g = this.ctx.createGain(); g.gain.setValueAtTime(0.6, t); g.gain.exponentialRampToValueAtTime(0.001, t + 0.7); const f = this.ctx.createBiquadFilter(); f.type = 'lowpass'; f.frequency.value = 900; const src = this.ctx.createBufferSource(); src.buffer = this.whoosh ? this.whooshNoise() : null; if (!src.buffer) return; src.connect(f); f.connect(g); g.connect(this.master); src.start(t); src.stop(t + 0.8); },
  whooshNoise() { const size = this.ctx.sampleRate, buf = this.ctx.createBuffer(1, size, this.ctx.sampleRate), d = buf.getChannelData(0); for (let i = 0; i < size; i++) d[i] = Math.random() * 2 - 1; return buf; },
  setWhoosh(speed) { if (!this.whooshGain) return; const v = this.enabled ? Math.min(0.5, Math.max(0, (speed - 4) / 30)) : 0; this.whooshGain.gain.setTargetAtTime(v, this.ctx.currentTime, 0.1); if (this.whoosh) this.whoosh.frequency.setTargetAtTime(400 + speed * 40, this.ctx.currentTime, 0.1); },
};
