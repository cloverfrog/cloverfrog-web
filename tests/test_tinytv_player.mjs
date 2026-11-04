// 用模拟 DOM/媒体事件验证模式竞态，不访问媒体源或登录服务。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

function page() {
  class Element {
    constructor() {
      this.hidden = true;
      this.disabled = false;
      this.value = '';
      this.style = {};
      this.listeners = {};
      this.paused = true;
      this.readyState = 1;
      this.currentTime = 0;
      this.duration = 600;
      this.classList = { add() {}, remove() {}, toggle() {}, contains: () => false };
    }
    setAttribute() {}
    removeAttribute(name) { delete this[name]; }
    querySelector(selector) { return element(selector); }
    querySelectorAll() { return []; }
    replaceChildren() {}
    contains() { return false; }
    addEventListener(event, listener) {
      (this.listeners[event] ||= []).push(listener);
    }
    emit(event) { for (const listener of this.listeners[event] || []) listener(); }
    pause() { this.paused = true; this.emit('pause'); }
    play() { this.paused = false; this.emit('play'); return Promise.resolve(); }
    load() {}
  }
  const elements = new Map();
  function element(selector) {
    if (!elements.has(selector)) elements.set(selector, new Element());
    return elements.get(selector);
  }
  const requests = [];
  const timers = [];
  const context = vm.createContext({
    document: {
      querySelector: element,
      createElement: () => new Element(),
      addEventListener() {},
      body: new Element()
    },
    window: { addEventListener() {} },
    navigator: {},
    localStorage: { removeItem() {} },
    location: { href: 'https://example.test/pages/tinytv/' },
    performance: { now: () => 1000 },
    URL, AbortSignal,
    HTMLVideoElement: class {},
    HTMLMediaElement: { HAVE_METADATA: 1 },
    setTimeout(callback) { timers.push(callback); return timers.length; },
    clearTimeout() {},
    setInterval(callback) { timers.push(callback); },
    clearInterval() {},
    requireUser: () => new Promise(() => {}),
    goToLogin() {},
    API_URL: '',
    fetch(url, options) {
      return new Promise((resolve, reject) => requests.push({ url, options, resolve, reject }));
    }
  });
  const script = readFileSync(new URL('../frontend/pages/tinytv/player.js', import.meta.url), 'utf8')
    .replace(/^import .*;\r?\n/gm, '');
  vm.runInContext(script, context);
  vm.runInContext('setAuthenticated(true)', context);
  return { element, requests, timers, run: (source) => vm.runInContext(source, context) };
}
const tick = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
const response = (data) => ({ status: 200, ok: true, json: async () => data });
const live = (offset = 100) => ({
  playUrl: '/live.mp4', programStart: 10, offset, remaining: 30,
  title: 'Live', season: 1, episode: 1, next: {}, upcoming: []
});
async function startVod(p) {
  p.element('#vod-path').value = 'unlisted.mp4';
  p.element('#vod-form').onsubmit({ preventDefault() {} });
  const request = p.requests.at(-1);
  assert.equal(request.url, '/api/tinytv/on-demand');
  request.resolve(response({ playUrl: '/vod.mp4' }));
  await tick();
}

test('点播隔离迟到直播响应、轮询、结束事件与拖动纠偏，返回直播重新定位', async () => {
  const p = page();
  p.run('sync()');
  const oldLive = p.requests[0];
  await startVod(p);
  const video = p.element('#video');
  assert.equal(video.src, 'https://example.test/vod.mp4');
  oldLive.resolve(response(live()));
  await tick();
  assert.equal(video.src, 'https://example.test/vod.mp4');
  const count = p.requests.length;
  for (let i = 0; i < 4; i++) {
    p.run('sync()');
    video.emit('ended');
    video.emit('play');
  }
  assert.equal(p.requests.length, count);
  video.currentTime = 42;
  video.emit('seeking');
  assert.equal(video.currentTime, 42);
  p.element('#vod-progress').value = '55';
  p.element('#vod-progress').oninput();
  assert.equal(video.currentTime, 55);
  p.element('#vod-toggle').onclick();
  assert.equal(video.paused, true);
  p.element('#vod-toggle').onclick();
  assert.equal(video.paused, false);
  p.element('#return-live').onclick();
  assert.equal(p.requests.at(-1).url, '/api/tinytv/channels/tiny/now');
  p.requests.at(-1).resolve(response(live(220)));
  await tick();
  assert.equal(video.src, 'https://example.test/live.mp4');
  assert.equal(video.currentTime, 220);
  assert.equal(p.element('#vod-controls').hidden, true);
});

test('旧请求异常和 finally 不能覆盖新状态或释放新的直播同步锁', async () => {
  const p = page();
  p.run('sync()');
  const oldLive = p.requests[0];
  await startVod(p);
  p.element('#return-live').onclick();
  oldLive.reject(new Error('old failure'));
  await tick();
  assert.equal(p.element('#status').textContent, '正在同步直播…');
  const count = p.requests.length;
  p.run('sync()');
  assert.equal(p.requests.length, count);
  p.requests.at(-1).resolve(response(live()));
  await tick();
});

test('连续点播及返回直播时丢弃旧点播结果；失败仍保留返回直播入口', async () => {
  const p = page();
  p.element('#vod-path').value = 'first.mp4';
  p.element('#vod-form').onsubmit({ preventDefault() {} });
  const oldVod = p.requests[0];
  await startVod(p);
  oldVod.resolve(response({ playUrl: '/first.mp4' }));
  await tick();
  assert.equal(p.element('#video').src, 'https://example.test/vod.mp4');
  p.element('#vod-form').onsubmit({ preventDefault() {} });
  p.requests.at(-1).reject(new Error('missing file'));
  await tick();
  assert.match(p.element('#status').textContent, /点播失败.*missing file/);
  assert.equal(p.element('#vod-controls').hidden, false);
  p.element('#vod-form').onsubmit({ preventDefault() {} });
  const lateVod = p.requests.at(-1);
  p.element('#return-live').onclick();
  lateVod.resolve(response({ playUrl: '/late.mp4' }));
  await tick();
  assert.notEqual(p.element('#video').src, 'https://example.test/late.mp4');
});


test('默认直播仍同步、纠偏并在视频结束时查询节目', async () => {
  const p = page();
  p.run('sync()');
  p.requests[0].resolve(response(live(100)));
  await tick();
  const video = p.element('#video');
  assert.equal(video.currentTime, 100);
  video.emit('seeked');
  video.currentTime = 20;
  video.emit('seeking');
  video.emit('seeked');
  assert.equal(video.currentTime, 100);
  video.emit('ended');
  assert.equal(p.requests.at(-1).url, '/api/tinytv/channels/tiny/now');
  p.requests.at(-1).resolve(response(live(110)));
  await tick();
  assert.equal(p.element('#vod-controls').hidden, true);
});

const transition = () => ({
  ...live(600), status: 'transition', remaining: 10,
  nextPlayback: { ...live(0), programStart: 620, playUrl: '/next.mp4' }
});
async function answerSync(p, data) {
  p.run('sync()');
  p.requests.at(-1).resolve(response(data));
  await tick();
}

test('过渡保留稍长片尾，结束后预加载且暂停，慢加载下一集仍从片头开始', async () => {
  const p = page();
  await answerSync(p, live(590));
  p.run('started = true');
  const video = p.element('#video');
  video.paused = false;
  video.duration = 605;
  await answerSync(p, transition());
  assert.equal(video.src, 'https://example.test/live.mp4');
  assert.match(p.element('#current').textContent, /过渡中/);
  video.ended = true;
  await answerSync(p, transition());
  assert.equal(video.src, 'https://example.test/next.mp4');
  assert.equal(video.paused, true);
  video.ended = false;
  video.currentTime = 0;
  video.readyState = 0;
  await answerSync(p, { ...live(4), programStart: 620, playUrl: '/next.mp4' });
  await answerSync(p, { ...live(20), programStart: 620, playUrl: '/next.mp4' });
  video.readyState = 1;
  video.emit('loadedmetadata');
  assert.equal(video.currentTime, 0);
  assert.equal(video.paused, false);
});

test('超过过渡余量强制切集；part 结束不触发整集关闭', async () => {
  const p = page();
  await answerSync(p, { ...live(590), partIndex: 1, partCount: 2 });
  p.run('started = true; startProgramEndSleepTimer()');
  p.element('#video').emit('ended');
  assert.equal(p.run('sleepTimer.type'), 'program');
  p.requests.at(-1).resolve(response({ ...live(0), playUrl: '/part2.mp4', partIndex: 2, partCount: 2 }));
  await tick();
  await answerSync(p, transition());
  await answerSync(p, { ...live(1), programStart: 620, playUrl: '/next.mp4' });
  assert.equal(p.element('#video').src, 'https://example.test/next.mp4');
  assert.equal(p.run('started'), false);
  assert.equal(p.run('sleepTimer'), null);
});
