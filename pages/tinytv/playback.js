// AVPlayer 1.3.1 and its decoding resources ship with this module.
const ASSET_ROOT = new URL('./vendor/libmedia', import.meta.url).href;
let library;
function loadLibrary() {
  if (!library) {
    // Use the non-shared-memory build without requiring site-wide COOP/COEP.
    window.CHEAP_DISABLE_THREAD = true;
    library = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = `${ASSET_ROOT}/avplayer/avplayer.js`;
      script.onload = () => window.AVPlayer ? resolve(window.AVPlayer) : reject(new Error('播放器初始化失败'));
      script.onerror = () => reject(new Error('播放器资源加载失败，请刷新后重试。'));
      document.head.append(script);
    });
  }
  return library;
}

// Start fetching before the first user gesture. Report errors when loading media.
loadLibrary().catch(() => {});

export class TinyTVPlayback extends EventTarget {
  constructor(container) {
    super();
    this.container = container;
    this.engine = null;
    this.currentSrc = '';
    this.readyState = 0;
    this.paused = true;
    this.error = null;
    this.generation = 0;
    this.operation = Promise.resolve();
  }

  get currentTime() { return this.engine ? Number(this.engine.currentTime) / 1000 : 0; }
  get duration() { return this.readyState ? Number(this.engine.getDuration()) / 1000 : NaN; }

  emit(name) { this.dispatchEvent(new Event(name)); }

  report(error, generation) {
    if (generation !== this.generation || this.error) return;
    this.error = error instanceof Error ? error : new Error('视频加载或解码失败');
    this.paused = true;
    this.readyState = 0;
    this.emit('error');
  }

  enqueue(task) {
    const generation = this.generation;
    const result = this.operation.catch(() => {}).then(async () => {
      if (generation === this.generation) return task(generation);
    });
    this.operation = result.catch(error => this.report(error, generation));
    return result;
  }

  // Call directly inside the entry button's click handler, before any await.
  unlock() {
    const AVPlayer = window.AVPlayer;
    if (!AVPlayer) return;
    if (!AVPlayer.audioContext) AVPlayer.audioContext = new AudioContext();
    if (AVPlayer.audioContext.state !== 'running') {
      AVPlayer.audioContext.resume().catch(() => this.emit('resume'));
    }
  }

  load(source) {
    const generation = ++this.generation;
    this.currentSrc = source;
    this.readyState = 0;
    this.paused = true;
    this.error = null;
    return this.enqueue(async () => {
      if (this.engine) {
        await this.engine.destroy();
        this.engine = null;
      }
      if (generation !== this.generation) return;
      this.container.replaceChildren();
      if (!source) return;
      const AVPlayer = await loadLibrary();
      if (generation !== this.generation) return;
      const engine = new AVPlayer({
        container: this.container,
        checkUseMSE: () => false,
        enableWebCodecs: true,
        enableHardware: true,
        enableWebGPU: false,
        enableWorker: true,
        loop: false,
        getWasm(type, codecId) {
          if (type === 'resampler') return `${ASSET_ROOT}/resample/resample.wasm`;
          if (type === 'stretchpitcher') return `${ASSET_ROOT}/stretchpitch/stretchpitch.wasm`;
          const codec = {27: 'h264', 173: 'hevc', 86018: 'aac'}[codecId];
          if (!codec) throw new Error(`当前播放器资源不包含此编码的解码器：${codecId}`);
          return `${ASSET_ROOT}/decode/${codec}.wasm`;
        }
      });
      this.engine = engine;
      const on = (name, handler) => engine.on(name, (...args) => {
        if (generation === this.generation && !this.error) handler(...args);
      });
      on('playing', () => { this.readyState = 1; this.emit('waiting'); });
      on('played', () => {
        const wasPaused = this.paused;
        this.paused = false;
        this.readyState = 3;
        if (wasPaused) this.emit('play');
        this.emit('playing');
      });
      on('paused', () => { this.paused = true; this.emit('pause'); });
      on('seeking', () => { this.readyState = 1; this.emit('waiting'); });
      on('seeked', () => {
        this.readyState = this.paused ? 1 : 3;
        if (!this.paused) this.emit('playing');
      });
      on('ended', () => { this.paused = true; this.emit('ended'); });
      on('resume', () => this.emit('resume'));
      on('error', error => this.report(error, generation));
      // Worker fetches do not resolve root-relative paths against the page URL.
      await engine.load(new URL(source, location.href).href, {isLive: false, http: {credentials: 'same-origin'}});
      if (generation !== this.generation || this.error) return;
      this.readyState = 1;
      this.emit('loadedmetadata');
    });
  }

  seek(seconds) {
    return this.enqueue(async () => {
      if (this.error) throw this.error;
      if (this.engine) await this.engine.seek(BigInt(Math.round(seconds * 1000)));
    });
  }

  play() {
    this.unlock();
    return this.enqueue(async () => {
      if (this.error) throw this.error;
      if (!this.engine) return;
      await this.engine.resume();
      await this.engine.play();
    });
  }

  pause() {
    return this.enqueue(async () => {
      if (this.engine && !this.paused) await this.engine.pause();
    });
  }

  clear() { return this.load(''); }
}
