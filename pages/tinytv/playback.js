// 播放器适配层：把 AVPlayer 的加载、事件和时间单位转换成频道页面使用的统一接口。
// 换源会废弃旧任务，操作队列保证先加载、再定位、后播放，防止切集时旧画面或声音串入。
// AVPlayer 1.3.1 与解码资源随本模块提供，播放时从本站按需加载。
const ASSET_ROOT = new URL('./vendor/libmedia', import.meta.url).href;
let library;
function loadLibrary() {
  if (!library) {
    // 关闭共享内存线程模式，使播放器不要求整个站点启用 COOP/COEP。
    window.CHEAP_DISABLE_THREAD = true;
    library = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = `${ASSET_ROOT}/avplayer/avplayer.js`;
      script.onload = () =>
        window.AVPlayer ? resolve(window.AVPlayer) : reject(new Error('播放器初始化失败'));
      script.onerror = () => reject(new Error('播放器资源加载失败，请刷新后重试。'));
      document.head.append(script);
    });
  }
  return library;
}

// 提前加载播放器库，减少点击进入后的等待；预加载失败留到实际加载节目时再提示。
loadLibrary().catch(() => {});

// 对页面暴露以秒为单位的播放接口，内部集中处理 AVPlayer 的毫秒时间和事件。
export class TinyTVPlayback extends EventTarget {
  constructor(container) {
    super();
    this.container = container;
    this.engine = null;
    // readyState 是页面用的简化状态：0 未就绪，1 可定位或缓冲中，3 正在播放。
    this.currentSrc = '';
    this.readyState = 0;
    this.paused = true;
    this.error = null;
    // 每次换源递增版本号，使旧节目的排队操作和迟到事件自动失效。
    this.generation = 0;
    this.operation = Promise.resolve();
  }

  get currentTime() {
    return this.engine ? Number(this.engine.currentTime) / 1000 : 0;
  }
  get duration() {
    return this.readyState ? Number(this.engine.getDuration()) / 1000 : NaN;
  }

  emit(name) {
    this.dispatchEvent(new Event(name));
  }

  // 只上报当前节目的首个错误，避免旧实例迟到的错误覆盖新节目的播放状态。
  report(error, generation) {
    if (generation !== this.generation || this.error) return;
    this.error = error instanceof Error ? error : new Error('视频加载或解码失败');
    this.paused = true;
    this.readyState = 0;
    this.emit('error');
  }

  // 加载、定位、播放串行执行；某次失败不会阻断后续操作队列。
  enqueue(task) {
    const generation = this.generation;
    const result = this.operation
      .catch(() => {})
      .then(async () => {
        if (generation === this.generation) return task(generation);
      });
    this.operation = result.catch((error) => this.report(error, generation));
    return result;
  }

  // 恢复被浏览器自动播放策略挂起的音频；必须在点击处理函数中、任何 await 之前直接调用。
  unlock() {
    const AVPlayer = window.AVPlayer;
    if (!AVPlayer) return;
    if (!AVPlayer.audioContext) AVPlayer.audioContext = new AudioContext();
    if (AVPlayer.audioContext.state !== 'running') {
      AVPlayer.audioContext.resume().catch(() => this.emit('resume'));
    }
  }

  // 换源先销毁旧引擎，再创建新引擎；传空地址时只释放资源，供退出登录或离开页面使用。
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
      // Only the address lookup uses the website session. Video bytes are read
      // directly from the returned source, without forwarding login credentials.
      const response = await fetch(new URL(source, location.href).href, {
        credentials: 'same-origin', cache: 'no-store', signal: AbortSignal.timeout(15000)
      });
      if (generation !== this.generation) return;
      if (response.status === 401) {
        this.emit('authrequired');
        return;
      }
      if (!response.ok) throw new Error(`获取播放地址失败：${response.status}`);
      const {url} = await response.json();
      const mediaUrl = new URL(url);
      if (!['https:', 'http:'].includes(mediaUrl.protocol)) throw new Error('无效的播放地址');
      if (generation !== this.generation) return;
      const engine = new AVPlayer({
        container: this.container,
        // 使用非 MSE 播放路径，优先硬解；不支持的编码由随模块准备的 WASM 解码器处理。
        checkUseMSE: () => false,
        enableWebCodecs: true,
        enableHardware: true,
        enableWebGPU: false,
        enableWorker: true,
        loop: false,
        getWasm(type, codecId) {
          if (type === 'resampler') return `${ASSET_ROOT}/resample/resample.wasm`;
          if (type === 'stretchpitcher') return `${ASSET_ROOT}/stretchpitch/stretchpitch.wasm`;
          const codec = { 27: 'h264', 173: 'hevc', 86018: 'aac' }[codecId];
          if (!codec) throw new Error(`当前播放器资源不包含此编码的解码器：${codecId}`);
          return `${ASSET_ROOT}/decode/${codec}.wasm`;
        }
      });
      this.engine = engine;
      // 引擎销毁和异步事件到达不一定同步，只转发仍属于本次换源的事件。
      const on = (name, handler) =>
        engine.on(name, (...args) => {
          if (generation === this.generation && !this.error) handler(...args);
        });
      // AVPlayer 的 playing 表示准备播放，played 才表示画面已开始推进。
      on('playing', () => {
        this.readyState = 1;
        this.emit('waiting');
      });
      on('played', () => {
        const wasPaused = this.paused;
        this.paused = false;
        this.readyState = 3;
        if (wasPaused) this.emit('play');
        this.emit('playing');
      });
      on('paused', () => {
        this.paused = true;
        this.emit('pause');
      });
      on('seeking', () => {
        this.readyState = 1;
        this.emit('waiting');
      });
      on('seeked', () => {
        this.readyState = this.paused ? 1 : 3;
        if (!this.paused) this.emit('playing');
      });
      on('ended', () => {
        this.paused = true;
        this.emit('ended');
      });
      on('resume', () => this.emit('resume'));
      on('error', (error) => this.report(error, generation));
      await engine.load(mediaUrl.href, {
        isLive: false,
        http: { credentials: 'omit', referrerPolicy: 'no-referrer' }
      });
      if (generation !== this.generation || this.error) return;
      this.readyState = 1;
      this.emit('loadedmetadata');
    });
  }

  // AVPlayer 的 seek 接收 BigInt 毫秒，页面层始终使用秒。
  seek(seconds) {
    return this.enqueue(async () => {
      if (this.error) throw this.error;
      if (this.engine) await this.engine.seek(BigInt(Math.round(seconds * 1000)));
    });
  }

  // 排在已有加载和定位任务之后播放；resume 用于恢复引擎可能挂起的音频状态。
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

  clear() {
    return this.load('');
  }
}
