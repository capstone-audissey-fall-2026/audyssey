import { peaksDb } from "./waveform";

export interface EngineTrack { id: string; url: string | null }

interface Entry {
  gainNode: GainNode;
  url: string | null;
  buffer: AudioBuffer | null;
  gain: number;
  keep: boolean;
}

// What a track contributes to the mix: dropped tracks are silent, and while one is soloed the rest are too.
export function effectiveGain(track: { gain: number; keep: boolean }, solo: string | null, id: string): number {
  if (!track.keep) return 0;
  if (solo !== null && solo !== id) return 0;
  return track.gain;
}

// The picture comes from the (muted) <video>; every kept track is mixed live with Web Audio, so keep, gain
// and solo apply at once. The AudioContext clock is the master clock.
export class AudioEngine {
  duration = 0;
  private tracks = new Map<string, Entry>();
  private sources: AudioBufferSourceNode[] = [];
  private master: GainNode;
  private playing = false;
  private offset = 0;
  private startedAt = 0;
  private raf = 0;
  private solo: string | null = null;
  private only: string | null = null;
  private mode: "edit" | "original" = "edit";
  private listeners = new Set<(t: number) => void>();
  private loadedListeners = new Set<() => void>();

  constructor(readonly video: HTMLVideoElement, private ctx: BaseAudioContext = new AudioContext()) {
    this.master = ctx.createGain();
    this.master.connect(ctx.destination);
    video.muted = true;
  }

  private get total(): number {
    return this.duration || this.video.duration || 0;
  }

  private useMix(): boolean {
    return this.only !== null || (this.mode === "edit" && [...this.tracks.values()].some((t) => t.buffer));
  }

  private applyGains(): void {
    for (const [id, t] of this.tracks) {
      // A track played on its own is heard even when it is dropped from the mix.
      t.gainNode.gain.value =
        this.only !== null
          ? effectiveGain({ gain: t.gain, keep: true }, this.only, id)
          : effectiveGain(t, this.solo, id);
    }
  }

  // Loads the buffers of tracks whose url changed and releases the rest. A track without a url has no audio.
  async setTracks(list: EngineTrack[]): Promise<void> {
    const ids = new Set(list.map((t) => t.id));
    for (const [id, t] of this.tracks) {
      if (ids.has(id)) continue;
      t.gainNode.disconnect();
      this.tracks.delete(id);
    }
    const loads: Promise<void>[] = [];
    for (const { id, url } of list) {
      let entry = this.tracks.get(id);
      if (!entry) {
        const gainNode = this.ctx.createGain();
        gainNode.connect(this.master);
        entry = { gainNode, url: null, buffer: null, gain: 1, keep: true };
        this.tracks.set(id, entry);
      }
      if (entry.url === url) continue;
      const e = entry;
      e.url = url;
      e.buffer = null;
      if (url) loads.push(this.load(e, url));
    }
    this.applyGains();
    this.restartIfPlaying();
    await Promise.all(loads);
  }

  private async load(entry: Entry, url: string): Promise<void> {
    try {
      const bytes = await (await fetch(url)).arrayBuffer();
      const buffer = await this.ctx.decodeAudioData(bytes);
      if (entry.url !== url) return; // replaced or released while loading
      entry.buffer = buffer;
      this.restartIfPlaying();
      for (const cb of this.loadedListeners) cb();
    } catch {
      // The lane keeps showing no waveform; playback goes on without this track.
    }
  }

  private restartIfPlaying(): void {
    if (!this.playing) return;
    const t = this.now();
    this.offset = t;
    this.startSources(t);
    this.video.muted = this.useMix();
  }

  // dB peaks of the decoded track, or null while it has no audio.
  peaks(id: string, buckets: number): Float32Array | null {
    const buffer = this.tracks.get(id)?.buffer;
    return buffer ? peaksDb(buffer.getChannelData(0), buckets) : null;
  }

  private startSources(at: number): void {
    this.stopSources();
    if (this.useMix()) {
      for (const [id, t] of this.tracks) {
        if (!t.buffer || at >= t.buffer.duration) continue;
        if (this.only !== null && this.only !== id) continue;
        const src = this.ctx.createBufferSource();
        src.buffer = t.buffer;
        src.connect(t.gainNode);
        src.start(0, at);
        this.sources.push(src);
      }
    }
    this.startedAt = this.ctx.currentTime;
  }

  private stopSources(): void {
    for (const s of this.sources) {
      try {
        s.stop();
      } catch {
        // Already stopped.
      }
    }
    this.sources = [];
  }

  now(): number {
    return this.playing ? Math.min(this.total, this.offset + (this.ctx.currentTime - this.startedAt)) : this.offset;
  }

  private emit(): void {
    const t = this.now();
    for (const cb of this.listeners) cb(t);
  }

  onTime(cb: (t: number) => void): () => void {
    this.listeners.add(cb);
    return () => this.listeners.delete(cb);
  }

  // Called whenever a track's audio has finished decoding (waveforms can be drawn then).
  onLoaded(cb: () => void): () => void {
    this.loadedListeners.add(cb);
    return () => this.loadedListeners.delete(cb);
  }

  play(): void {
    if (this.playing) return;
    void (this.ctx as AudioContext).resume?.();
    if (this.offset >= this.total - 0.02) this.offset = 0;
    this.video.muted = this.useMix();
    this.video.currentTime = this.offset;
    this.startSources(this.offset);
    this.playing = true;
    void this.video.play().catch(() => {});
    this.tick();
  }

  // Plays one track on its own from the playhead; pausing returns to the normal mix.
  playOnly(id: string | null): void {
    if (this.playing) this.pause();
    this.only = id;
    this.applyGains();
    this.play();
  }

  pause(): void {
    if (!this.playing) return;
    this.offset = this.now();
    this.playing = false;
    this.stopSources();
    this.video.pause();
    globalThis.cancelAnimationFrame?.(this.raf);
    if (this.only !== null) {
      this.only = null;
      this.applyGains();
    }
    this.emit();
  }

  seek(t: number): void {
    this.offset = Math.max(0, Math.min(this.total, t));
    this.video.currentTime = this.offset;
    if (this.playing) this.startSources(this.offset);
    this.emit();
  }

  private tick = (): void => {
    const t = this.now();
    if (t >= this.total - 0.01) {
      this.pause();
      this.offset = this.total;
      this.emit();
      return;
    }
    // The audio clock leads; keep the picture within a frame or two of it.
    if (this.useMix() && Math.abs(this.video.currentTime - t) > 0.08) this.video.currentTime = t;
    this.emit();
    this.raf = globalThis.requestAnimationFrame?.(this.tick) ?? 0;
  };

  get isPlaying(): boolean {
    return this.playing;
  }

  get playingOnly(): boolean {
    return this.only !== null;
  }

  setSolo(id: string | null): void {
    this.solo = id;
    this.applyGains();
  }

  setGain(id: string, gain: number): void {
    const t = this.tracks.get(id);
    if (!t) return;
    t.gain = gain;
    this.applyGains();
  }

  setKeep(id: string, keep: boolean): void {
    const t = this.tracks.get(id);
    if (!t) return;
    t.keep = keep;
    this.applyGains();
  }

  setMode(mode: "edit" | "original"): void {
    this.mode = mode;
    this.restartIfPlaying();
    this.video.muted = this.useMix();
  }

  dispose(): void {
    this.playing = false;
    this.stopSources();
    this.video.pause();
    globalThis.cancelAnimationFrame?.(this.raf);
    for (const t of this.tracks.values()) t.gainNode.disconnect();
    this.tracks.clear();
    this.master.disconnect();
    this.listeners.clear();
    this.loadedListeners.clear();
    void (this.ctx as AudioContext).close?.();
  }
}
