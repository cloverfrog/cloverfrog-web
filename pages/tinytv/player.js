import { API_URL } from '/config.js';
import { requireUser, goToLogin } from '/assets/auth.mjs';
import { TinyTVPlayback } from './playback.js';

const video = new TinyTVPlayback(document.querySelector('#video'));
const status = document.querySelector('#status');
const player = document.querySelector('#player');
const enter = document.querySelector('#enter');
const entry = document.querySelector('.entry');
const enterLabel = document.querySelector('#enter-label');
const fullscreen = document.querySelector('#fullscreen');
let hideControls, needsAttention = false, playbackIssue = '';
function setStatus(message, attention = false) {
  status.textContent = attention ? message : '';
  status.hidden = !attention || !message;
  needsAttention = attention;
  if (attention) revealControls();
}
function offerEntry(message) {
  playbackIssue = message;
  entry.hidden = false;
  enterLabel.textContent = '重新进入';
  setStatus(message, true);
}
function playChannel() {
  video.play().catch(error => {
    // Loading the next program can cancel an earlier play request.
    if (error.name === 'AbortError') return;
    if (!authenticated || !started) return;
    started = false;
    offerEntry('播放未能开始，请点击重新进入频道。');
  });
}
let authenticated = false;
// Remove obsolete direct-source settings from earlier local previews.
try { localStorage.removeItem('tinytv.settings'); } catch {}
function setAuthenticated(value) {
  authenticated = value;
  enter.disabled = !value;
  if (!value) {
    started = false; current = null; pending = null; needsEntryPosition = false;
    clearTimeout(boundary);
    video.clear().catch(() => {});
    document.querySelector('#current').textContent = '登录后进入频道';
    document.querySelector('#next').textContent = '';
    document.querySelector('#programs').replaceChildren();
    entry.hidden = false;
    playbackIssue = '';
    enterLabel.textContent = '进入频道';
    setStatus('使用 PocketBase 账号登录', true);
  }
}
let busy = false, current = null, boundary = null, pending = null, started = false;
let needsEntryPosition = false;
const label = p => `${p.title} · 第 ${p.season} 季 第 ${p.episode} 集`;
const identity = p => `${p.programStart}:${p.playUrl}`;
function applyPosition() {
  if (!pending || video.readyState < 1) return;
  const target = pending.offset + (performance.now() - pending.received) / 1000;
  if (Number.isFinite(video.duration) && target >= video.duration) {
    setStatus('视频已结束，等待节目时间线切换；请核对节目时长。', true);
    return;
  }
  // The playback adapter serializes seek and play: never start before entry positioning.
  if (needsEntryPosition || Math.abs(video.currentTime - target) > 30) video.seek(target).catch(() => {});
  needsEntryPosition = false;
  pending = null;
  if (started && video.paused) playChannel();
}
async function sync() {
  if (busy || !authenticated) return;
  busy = true;
  try {
    const sent = performance.now();
    const response = await fetch(API_URL + '/api/tinytv/channels/tiny/now', {cache:'no-store', signal:AbortSignal.timeout(10000)});
    if (response.status === 401) { setAuthenticated(false); goToLogin(); return; }
    if (!response.ok) throw new Error(`接口返回 ${response.status}`);
    const data = await response.json();
    if (!authenticated) return;
    const received = performance.now();
    clearTimeout(boundary);
    if (data.status === 'waiting') {
      video.pause().catch(() => {}); current = null; pending = null;
      setStatus(`频道将于 ${new Date(data.startTime * 1000).toLocaleString()} 开播`, true);
      boundary = setTimeout(sync, Math.min(30000, Math.max(100, (data.startTime-data.serverTime)*1000)));
      return;
    }
    const delay = (received - sent) / 2000;
    pending = {offset:data.offset + delay, received};
    if (current !== identity(data)) {
      current = identity(data);
      needsEntryPosition = true;
      video.load(data.playUrl).catch(() => {});
    }
    document.querySelector('#current').textContent = label(data);
    document.querySelector('#next').textContent = `接下来：${label(data.next)}`;
    const position = data.programs.findIndex(p => p.title === data.title && p.season === data.season && p.episode === data.episode);
    const upcoming = position < 0 ? [data, data.next] : Array.from(
      {length: Math.min(11, data.programs.length)},
      (_, index) => data.programs[(position + index) % data.programs.length]
    );
    document.querySelector('#programs').replaceChildren(...upcoming.map((p, index) => {
      const li = document.createElement('li');
      li.textContent = `${index === 0 ? '正在播放：' : ''}${label(p)} · ${p.duration.toFixed(2)} 秒`;
      li.classList.toggle('active', index === 0);
      return li;
    }));
    if (playbackIssue) setStatus(playbackIssue, true);
    else setStatus('正在缓冲…', started && video.readyState < 3);
    applyPosition();
    boundary = setTimeout(sync, Math.max(100, (data.remaining-delay)*1000+50));
  } catch (error) {
    setStatus(`同步失败：${error.message}。稍后自动重试。`, true);
  } finally { busy = false; }
}
video.addEventListener('loadedmetadata', applyPosition);
video.addEventListener('ended', sync);
video.addEventListener('play', () => { started = true; sync(); });
video.addEventListener('playing', () => {
  playbackIssue = '';
  entry.hidden = true;
  setStatus('');
  revealControls();
});
video.addEventListener('waiting', () => {
  if (authenticated && started) setStatus('正在缓冲…', true);
});
video.addEventListener('pause', revealControls);
video.addEventListener('error', () => {
  if (authenticated) {
    current = null;
    offerEntry(video.error?.message || '视频加载失败，请重新进入频道。');
  }
});
video.addEventListener('resume', () => {
  if (authenticated && started) offerEntry('声音播放被浏览器暂停，请点击重新进入频道。');
});

enter.onclick = () => {
  video.unlock();
  playbackIssue = '';
  started = true;
  needsEntryPosition = true;
  setStatus('正在进入频道…', true);
  // Audio is unlocked above; playback starts only after applyPosition queues the seek.
  sync();
};
function revealControls() {
  clearTimeout(hideControls);
  player.classList.remove('controls-hidden');
  if (entry.hidden && !video.paused && video.readyState >= 3 && !needsAttention) {
    hideControls = setTimeout(() => {
      if (player.querySelector('button:focus-visible')) return;
      player.classList.add('controls-hidden');
    }, 2500);
  }
}
['pointermove', 'pointerdown', 'keydown', 'focusin', 'focusout'].forEach(event => {
  player.addEventListener(event, revealControls);
});
fullscreen.onclick = async () => {
  try {
    if (document.fullscreenElement === player) await document.exitFullscreen();
    else if (player.requestFullscreen) {
      await player.requestFullscreen();
      // Rotation support is independent of fullscreen support.
      if (document.fullscreenElement === player && screen.orientation?.lock) {
        try { await screen.orientation.lock('landscape'); } catch { /* Keep fullscreen if rotation is unavailable. */ }
        if (document.fullscreenElement !== player) releaseOrientation();
      }
    } else { setStatus('当前浏览器不支持此页面的全屏模式。', true); }
  } catch { setStatus('无法进入全屏，请检查浏览器权限。', true); }
};
function releaseOrientation() {
  try { screen.orientation?.unlock?.(); } catch { /* Orientation locking is optional. */ }
}
document.addEventListener('fullscreenchange', () => {
  const active = document.fullscreenElement === player;
  fullscreen.setAttribute('aria-label', active ? '退出全屏' : '全屏');
  fullscreen.title = active ? '退出全屏' : '全屏';
  fullscreen.setAttribute('aria-pressed', String(active));
  if (!active) releaseOrientation();
  revealControls();
});

document.addEventListener('visibilitychange', () => { if (!document.hidden) sync(); });
setInterval(sync, 15000);
setAuthenticated(false);
requireUser()
  .then(user => { if (user) { setAuthenticated(true); sync(); } })
  .catch(() => { setStatus('无法连接登录服务，请稍后刷新。', true); });
window.addEventListener('pagehide', () => { video.clear().catch(() => {}); });
