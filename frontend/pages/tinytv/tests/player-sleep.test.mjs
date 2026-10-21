import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { SleepTimer } from '../sleep-timer.mjs';

const source = (await readFile(new URL('../player.js', import.meta.url), 'utf8'))
  .replace(/^import .*;\n/gm, '');
function setup() {
  let now = 0, timer, resolveFetch;
  const elements = new Map();
  const element = (selector) => {
    if (!elements.has(selector)) elements.set(selector, {
      hidden: false, value: '1', textContent: '',
      classList: { add() {}, remove() {}, toggle() {} },
      addEventListener() {}, setAttribute() {}, replaceChildren() {},
      querySelector() { return null; }, reportValidity() { return true; }
    });
    return elements.get(selector);
  };
  const document = { hidden: false, querySelector: element, addEventListener() {},
    createElement: () => element('li') };
  class Playback extends EventTarget {
    paused = true; readyState = 0; loads = []; clears = 0;
    clear() { this.clears++; this.readyState = 0; return Promise.resolve(); }
    load(url) { this.loads.push(url); return Promise.resolve(); }
    play() { throw Error('unexpected automatic playback'); }
    unlock() {} seek() { return Promise.resolve(); }
  }
  const context = vm.createContext({
    API_URL: '', TinyTVPlayback: Playback,
    SleepTimer: class extends SleepTimer {
      constructor(options) { super({ ...options, now: () => now,
        schedule: () => 1, unschedule() {} }); timer = this; }
    }, document, navigator: {}, window: { addEventListener() {} },
    localStorage: { removeItem() {} }, performance: { now: () => now },
    setTimeout: () => 1, clearTimeout() {}, setInterval() {},
    requireUser: () => new Promise(() => {}), goToLogin() {},
    AbortSignal, fetch: () => new Promise((resolve) => { resolveFetch = resolve; })
  });
  vm.runInContext(source, context);
  return { context, element, timer,
    advance: (ms) => { now += ms; },
    respond: (data) => resolveFetch({ ok: true, json: async () => data }),
    run: (code) => vm.runInContext(code, context) };
}

test('expiry blocks late sync responses and subsequent polling until user re-enters', async () => {
  const f = setup();
  f.run('setAuthenticated(true); started = true;');
  f.timer.start(1);
  const pending = f.run('sync()');
  f.advance(60000);
  f.timer.check();
  const clears = f.run('video.clears');
  f.respond({ status: 'playing', playUrl: 'late.mp4' });
  await pending;
  await f.run('sync()');
  assert.equal(f.run('video.loads.length'), 0);
  assert.equal(f.run('started'), false);
  assert.equal(f.run('sleepStopped'), true);
  assert.equal(f.run('video.clears'), clears);
  assert.match(f.element('#status').textContent, /定时已到/);
  f.timer.cancel();
  assert.equal(f.run('sleepStopped'), true);
  f.run('enter.onclick()');
  assert.equal(f.run('sleepStopped'), false);
  assert.equal(f.run('started'), true);
});

test('sleep timer disables wake lock intent while active', () => {
  const f = setup();
  let requests = 0;
  f.context.navigator.wakeLock = { request() { requests++; return new Promise(() => {}); } };
  f.timer.start(1);
  f.run('setScreenAwake(true)');
  assert.equal(requests, 0);
  f.timer.cancel();
  f.run('updateScreenLock()');
  assert.equal(requests, 1);
});
