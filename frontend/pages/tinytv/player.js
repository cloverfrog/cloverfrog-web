import { API_URL } from '/config.js';
import { requireUser, goToLogin } from '/assets/auth.mjs';

// 频道页面入口：查询当前节目并校准播放进度，管理播放提示、屏幕常亮和全屏交互。
// 片源由浏览器原生 video 播放，需使用浏览器支持的封装和音视频编码。

// 页面元素与提示状态。
const video = document.querySelector('#video');
const status = document.querySelector('#status');
const player = document.querySelector('#player');
const enter = document.querySelector('#enter');
const entry = document.querySelector('.entry');
const enterLabel = document.querySelector('#enter-label');
const fullscreen = document.querySelector('#fullscreen');
const controls = document.querySelector('#controls');
const pictureInPicture = document.querySelector('#picture-in-picture');
const pageFullscreen = document.querySelector('#page-fullscreen');
const sleepTimerButton = document.querySelector('#sleep-timer');
const sleepTimerLabel = document.querySelector('#sleep-timer-label');
const sleepTimerMenu = document.querySelector('#sleep-timer-menu');
const cancelSleepTimerButton = sleepTimerMenu.querySelector('[data-cancel]');
const programEndTimerButton = sleepTimerMenu.querySelector('[data-program-end]');
let hideControls,
  needsAttention = false,
  playbackIssue = '';
// 播放时保持屏幕常亮，防止手机因长时间没有触摸操作而自动熄屏。
// 真正开始播放后申请，缓冲期间保留；暂停、结束、报错、退出登录或离开页面时释放。
// 切到后台时释放锁但保留常亮意愿，返回可见页面后可以重新申请。
// 这是尽力提供的观看体验：浏览器不支持或系统拒绝时，仍允许正常播放。
let screenLock = null, // 浏览器已授予的屏幕常亮锁；释放时需要用到此对象。
  screenLockRequest = null, // 正在等待的申请，避免多个播放事件重复申请。
  keepScreenAwake = false; // 播放状态是否需要常亮，与当前是否持有锁分开记录。
let pageActive = true;

// 定时关闭只保存在当前页面中。到时停止播放并释放屏幕常亮锁，不主动锁定设备。
let sleepTimer = null,
  sleepTimerTimeout = null,
  sleepTimerTicker = null;

function closeSleepTimerMenu() {
  sleepTimerMenu.hidden = true;
  sleepTimerButton.setAttribute('aria-expanded', 'false');
}

function updateSleepTimerLabel() {
  if (!sleepTimer) {
    sleepTimerLabel.textContent = '定时关闭';
    sleepTimerButton.title = '定时关闭';
    cancelSleepTimerButton.hidden = true;
    return;
  }
  cancelSleepTimerButton.hidden = false;
  if (sleepTimer.type === 'program') {
    sleepTimerLabel.textContent = '本集结束';
    sleepTimerButton.title = '当前节目结束后关闭';
    return;
  }
  const remaining = Math.max(0, sleepTimer.deadline - Date.now());
  const minutes = Math.floor(remaining / 60000);
  const seconds = Math.floor((remaining % 60000) / 1000);
  const text = `${minutes}:${String(seconds).padStart(2, '0')}`;
  sleepTimerLabel.textContent = text;
  sleepTimerButton.title = `${text} 后关闭`;
}

function clearSleepTimer() {
  sleepTimer = null;
  clearTimeout(sleepTimerTimeout);
  clearInterval(sleepTimerTicker);
  sleepTimerTimeout = null;
  sleepTimerTicker = null;
  updateSleepTimerLabel();
}

function stopForSleepTimer() {
  if (!sleepTimer) return;
  clearSleepTimer();
  started = false;
  setScreenAwake(false);
  video.pause();
  offerEntry('定时关闭已停止播放。');
}

function startMinuteSleepTimer(minutes) {
  clearSleepTimer();
  sleepTimer = { type: 'deadline', deadline: Date.now() + minutes * 60000 };
  sleepTimerTimeout = setTimeout(stopForSleepTimer, minutes * 60000);
  sleepTimerTicker = setInterval(updateSleepTimerLabel, 1000);
  updateSleepTimerLabel();
}

function startProgramEndSleepTimer() {
  if (currentProgramStart === null) return;
  clearSleepTimer();
  // 播放地址可能在同一节目内刷新，节目开播时间才是稳定的节目轮次标识。
  sleepTimer = { type: 'program', programStart: currentProgramStart };
  updateSleepTimerLabel();
}

// 播放事件只需声明是否需要常亮，锁的实际申请和释放统一在下面处理。
function setScreenAwake(value) {
  keepScreenAwake = value;
  updateScreenLock();
}

// 让浏览器持有的锁符合当前播放需求和页面状态；播放中切回前台也调用这里。
function updateScreenLock() {
  const shouldHold = () => keepScreenAwake && pageActive && !document.hidden;
  if (!shouldHold()) {
    // 先清空引用，再异步释放，后续状态更新就不会误以为仍然持有锁。
    const lock = screenLock;
    screenLock = null;
    if (lock) lock.release().catch(() => {});
    return;
  }
  if (!navigator.wakeLock || screenLock || screenLockRequest) return;
  screenLockRequest = navigator.wakeLock
    .request('screen')
    .then((lock) => {
      // 申请是异步的，等待期间可能已经暂停或切到后台；此时拿到锁也应立即释放。
      if (!shouldHold()) return lock.release();
      screenLock = lock;
      lock.addEventListener(
        'release',
        () => {
          // 系统也可能主动释放锁，清除引用后才能在下次状态更新时重新申请。
          if (screenLock === lock) screenLock = null;
        },
        { once: true }
      );
    })
    .catch(() => {
      // 常亮申请可能因省电策略或权限被拒绝，无需让用户为此中断观看。
    })
    .finally(() => {
      screenLockRequest = null;
    });
}

// 播放提示与重新进入频道：正常观看时隐藏提示，遇到需要处理的情况再显示。
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
  video.play().catch((error) => {
    // 切集会取消旧节目的播放请求，这是正常换源，不应提示用户重新进入。
    if (error.name === 'AbortError') return;
    if (!authenticated || !started) return;
    started = false;
    setScreenAwake(false);
    offerEntry('播放未能开始，请点击重新进入频道。');
  });
}

function loadVideo(source) {
  video.pause();
  video.src = new URL(source, location.href).href;
  video.load();
}

function clearVideo() {
  video.pause();
  video.removeAttribute('src');
  video.load();
}

// 登录失效时清空节目与播放资源，同时停止常亮，避免登录页仍占用播放器状态。
let authenticated = false;
// 清除旧版本地预览留下的直连片源设置，当前片源统一由后端提供。
try {
  localStorage.removeItem('tinytv.settings');
} catch {}
function setAuthenticated(value) {
  authenticated = value;
  // 登录成功后仍需等节目地址写入原生 video，避免用户点击时还没有可播放的媒体。
  enter.disabled = true;
  if (!value) {
    clearSleepTimer();
    setScreenAwake(false);
    started = false;
    current = null;
    currentProgramStart = null;
    pending = null;
    channelClock = null;
    needsEntryPosition = false;
    clearTimeout(boundary);
    clearVideo();
    document.querySelector('#current').textContent = '登录后进入频道';
    document.querySelector('#next').textContent = '';
    document.querySelector('#programs').replaceChildren();
    entry.hidden = false;
    playbackIssue = '';
    enterLabel.textContent = '进入频道';
    setStatus('使用 PocketBase 账号登录', true);
  }
}
// 频道时间同步：所有观众跟随后端的同一条时间线，进入频道和切集时都要定位。
// current 用“开播时刻 + 播放地址”区分同一节目在不同轮次的播放。
// boundary 在节目结束时触发查询，busy 防止查询重叠。
// pending 保存待定位进度及收到响应的时刻；started 表示用户已点击进入频道。
let busy = false,
  current = null,
  currentProgramStart = null,
  boundary = null,
  pending = null,
  channelClock = null,
  positioning = false,
  started = false;
let needsEntryPosition = false;
const label = (program) =>
  `${program.title} · ${program.seasonName || `第 ${program.season} 季`} · 第 ${program.episode} 集`;
const identity = (program) => `${program.programStart}:${program.playUrl}`;
// 把播放器定位到频道此刻的进度；首次进入必须定位，播放中只纠正超过 30 秒的偏差。
// 目标加上响应收到后的等待时间，避免视频加载完成时仍使用查询时的旧进度。
function applyPosition() {
  if (!pending || video.readyState < 1) return;
  const target = pending.offset + (performance.now() - pending.received) / 1000;
  if (Number.isFinite(video.duration) && target >= video.duration) {
    setStatus('视频已结束，等待节目时间线切换；请核对节目时长。', true);
    return;
  }
  // 元数据就绪后先定位再播放，避免从片头闪播。
  if (needsEntryPosition || Math.abs(video.currentTime - target) > 30) {
    try {
      positioning = true;
      video.currentTime = target;
    } catch {
      positioning = false;
      setStatus('无法定位到频道当前进度，请重新进入频道。', true);
      return;
    }
  }
  needsEntryPosition = false;
  pending = null;
  if (started && video.paused) playChannel();
}

// 查询当前节目、更新节目单，并安排节目边界的下一次查询；定时轮询负责兜底校准。
async function sync() {
  if (busy || !authenticated) return;
  busy = true;
  try {
    const sent = performance.now();
    const response = await fetch(API_URL + '/api/tinytv/channels/tiny/now', {
      cache: 'no-store',
      signal: AbortSignal.timeout(10000)
    });
    if (response.status === 401) {
      setAuthenticated(false);
      goToLogin();
      return;
    }
    if (!response.ok) throw new Error(`接口返回 ${response.status}`);
    const data = await response.json();
    if (!authenticated) return;
    const received = performance.now();
    clearTimeout(boundary);
    if (data.status === 'waiting') {
      video.pause();
      current = null;
      currentProgramStart = null;
      pending = null;
      channelClock = null;
      setStatus(`频道将于 ${new Date(data.startTime * 1000).toLocaleString()} 开播`, true);
      boundary = setTimeout(
        sync,
        Math.min(30000, Math.max(100, (data.startTime - data.serverTime) * 1000))
      );
      return;
    }
    // 用往返耗时的一半估计单程延迟，将服务端进度校准到响应接收时刻。
    const delay = (received - sent) / 2000;
    channelClock = { offset: data.offset + delay, received };
    pending = channelClock;
    const nextIdentity = identity(data);
    if (
      sleepTimer?.type === 'program' &&
      sleepTimer.programStart !== data.programStart
    )
      stopForSleepTimer();
    currentProgramStart = data.programStart;
    if (current !== nextIdentity) {
      needsEntryPosition = true;
      loadVideo(data.playUrl);
      current = nextIdentity;
    }
    enter.disabled = false;
    document.querySelector('#current').textContent = label(data);
    document.querySelector('#next').textContent = `接下来：${label(data.next)}`;
    document.querySelector('#programs').replaceChildren(
      ...data.upcoming.map((program, index) => {
        const listItem = document.createElement('li');
        listItem.textContent = `${index === 0 ? '正在播放：' : ''}${label(program)} · ${program.duration.toFixed(2)} 秒`;
        listItem.classList.toggle('active', index === 0);
        return listItem;
      })
    );
    if (playbackIssue) setStatus(playbackIssue, true);
    else setStatus('正在缓冲…', started && video.readyState < 3);
    applyPosition();
    boundary = setTimeout(sync, Math.max(100, (data.remaining - delay) * 1000 + 50));
  } catch (error) {
    setStatus(`同步失败：${error.message}。稍后自动重试。`, true);
  } finally {
    busy = false;
  }
}
// 播放状态与观看体验的联动。
// playing 表示实际开始播放，此时才申请常亮；waiting 只是缓冲，不释放已有常亮锁。
// pause / ended / error 都停止常亮；ended 还会立即查询时间线，尝试接入下一节目。
video.addEventListener('loadedmetadata', applyPosition);
// 画中画的进度条由浏览器提供，页面无法隐藏；用户拖动时立即拉回频道时间线。
video.addEventListener('seeking', () => {
  if (positioning || !channelClock || video.readyState < 1) return;
  const target = channelClock.offset + (performance.now() - channelClock.received) / 1000;
  if (!Number.isFinite(video.duration) || target >= video.duration) return;
  try {
    positioning = true;
    video.currentTime = target;
  } catch {
    positioning = false;
  }
});
video.addEventListener('seeked', () => {
  positioning = false;
});
video.addEventListener('ended', () => {
  setScreenAwake(false);
  sync();
});
video.addEventListener('play', () => {
  started = true;
  sync();
});
video.addEventListener('playing', () => {
  setScreenAwake(true);
  playbackIssue = '';
  entry.hidden = true;
  setStatus('');
  revealControls();
});
video.addEventListener('waiting', () => {
  if (authenticated && started) setStatus('正在缓冲…', true);
});
video.addEventListener('pause', () => {
  setScreenAwake(false);
  revealControls();
});
video.addEventListener('error', () => {
  setScreenAwake(false);
  if (authenticated) {
    current = null;
    offerEntry(video.error?.message || '视频加载失败，请重新进入频道。');
  }
});

enter.onclick = () => {
  playbackIssue = '';
  started = true;
  needsEntryPosition = true;
  setStatus('正在进入频道…', true);
  // 直接在点击处理函数中请求播放，满足浏览器的声音播放授权要求。
  playChannel();
  sync();
};

// 原生 video 可以直接进入标准画中画；不支持的浏览器隐藏按钮。
const pictureInPictureSupported =
  document.pictureInPictureEnabled && 'requestPictureInPicture' in HTMLVideoElement.prototype;
pictureInPicture.hidden = !pictureInPictureSupported;
pictureInPicture.onclick = async () => {
  try {
    if (document.pictureInPictureElement === video) await document.exitPictureInPicture();
    else {
      if (video.readyState < HTMLMediaElement.HAVE_METADATA) {
        setStatus('节目加载完成后才能进入小窗。', true);
        return;
      }
      await video.requestPictureInPicture();
    }
  } catch {
    setStatus('无法进入小窗，请检查浏览器是否允许画中画。', true);
  }
};
video.addEventListener('enterpictureinpicture', () => {
  pictureInPicture.setAttribute('aria-label', '退出小窗');
  pictureInPicture.title = '退出小窗';
  revealControls();
});
video.addEventListener('leavepictureinpicture', () => {
  pictureInPicture.setAttribute('aria-label', '小窗播放');
  pictureInPicture.title = '小窗播放';
  revealControls();
});

// 网页全屏只铺满当前浏览器视口，适合作为系统全屏 API 不可用时的轻量模式。
function setPageFullscreen(active) {
  player.classList.toggle('page-fullscreen', active);
  document.body.classList.toggle('player-expanded', active);
  pageFullscreen.setAttribute('aria-pressed', String(active));
  pageFullscreen.setAttribute('aria-label', active ? '退出网页全屏' : '网页全屏');
  pageFullscreen.title = active ? '退出网页全屏' : '网页全屏';
  revealControls();
}
pageFullscreen.onclick = () =>
  setPageFullscreen(!player.classList.contains('page-fullscreen'));

sleepTimerButton.onclick = () => {
  const opening = sleepTimerMenu.hidden;
  sleepTimerMenu.hidden = !opening;
  sleepTimerButton.setAttribute('aria-expanded', String(opening));
  programEndTimerButton.disabled = currentProgramStart === null;
  if (opening) sleepTimerMenu.querySelector('button:not([hidden]):not(:disabled)')?.focus();
  revealControls();
};
sleepTimerMenu.onclick = (event) => {
  const option = event.target.closest('button');
  if (!option) return;
  if (option.hasAttribute('data-cancel')) clearSleepTimer();
  else if (option.hasAttribute('data-program-end')) startProgramEndSleepTimer();
  else startMinuteSleepTimer(Number(option.dataset.minutes));
  closeSleepTimerMenu();
  sleepTimerButton.focus();
  revealControls();
};
document.addEventListener('pointerdown', (event) => {
  if (!controls.contains(event.target) && !sleepTimerMenu.hidden) {
    closeSleepTimerMenu();
    revealControls();
  }
});
sleepTimerMenu.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  event.stopPropagation();
  closeSleepTimerMenu();
  sleepTimerButton.focus();
  revealControls();
});

// 播放托盘在正常播放且无人操作时自动隐藏；缓冲、报错或键盘操作时保持可用。
function canHideControls() {
  return (
    sleepTimerMenu.hidden &&
    entry.hidden &&
    !video.paused &&
    video.readyState >= 3 &&
    !needsAttention &&
    !player.querySelector('button:focus-visible')
  );
}
function hidePlayerControls() {
  clearTimeout(hideControls);
  if (canHideControls()) player.classList.add('controls-hidden');
}
function revealControls() {
  clearTimeout(hideControls);
  player.classList.remove('controls-hidden');
  if (canHideControls()) hideControls = setTimeout(hidePlayerControls, 2500);
}
['keydown', 'focusin', 'focusout'].forEach((event) => {
  player.addEventListener(event, revealControls);
});
player.addEventListener('pointermove', (event) => {
  if (event.pointerType !== 'touch') revealControls();
});
player.addEventListener('pointerdown', (event) => {
  // 触屏点击画面切换托盘；操作托盘里的按钮时保持显示，避免吞掉按钮点击。
  if (event.pointerType === 'touch' && !controls.contains(event.target)) {
    if (player.classList.contains('controls-hidden')) revealControls();
    else hidePlayerControls();
    return;
  }
  revealControls();
});
player.addEventListener('pointerleave', (event) => {
  const fullscreenActive =
    document.fullscreenElement === player || player.classList.contains('page-fullscreen');
  if (event.pointerType === 'mouse' && !fullscreenActive) hidePlayerControls();
});

// 全屏与手机横屏：进入全屏后尝试锁定横屏，退出时解除；横屏失败不影响全屏观看。
fullscreen.onclick = async () => {
  try {
    if (document.fullscreenElement === player) await document.exitFullscreen();
    else if (player.requestFullscreen) {
      await player.requestFullscreen();
      // 浏览器可能支持全屏却不支持锁定方向，因此单独尝试。
      if (document.fullscreenElement === player && screen.orientation?.lock) {
        try {
          await screen.orientation.lock('landscape');
        } catch {
          /* 无法锁定横屏时继续保持全屏。 */
        }
        if (document.fullscreenElement !== player) releaseOrientation();
      }
    } else {
      setStatus('当前浏览器不支持此页面的全屏模式。', true);
    }
  } catch {
    setStatus('无法进入全屏，请检查浏览器权限。', true);
  }
};
function releaseOrientation() {
  try {
    screen.orientation?.unlock?.();
  } catch {
    /* 部分浏览器不允许页面管理屏幕方向，忽略解除失败。 */
  }
}
document.addEventListener('fullscreenchange', () => {
  const active = document.fullscreenElement === player;
  fullscreen.setAttribute('aria-label', active ? '退出全屏' : '全屏');
  fullscreen.title = active ? '退出全屏' : '全屏';
  fullscreen.setAttribute('aria-pressed', String(active));
  if (!active) releaseOrientation();
  revealControls();
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && player.classList.contains('page-fullscreen'))
    setPageFullscreen(false);
});

// 页面可见性：切后台时释放常亮锁，切回前台时按播放需求重新申请。
// 后台计时器可能被浏览器节流，恢复可见时也需要立即校准节目进度。
document.addEventListener('visibilitychange', () => {
  updateScreenLock();
  if (!document.hidden) sync();
});

// 启动页面：先校验公共登录态，再读取频道；播放期间每 15 秒校准一次。
setInterval(sync, 15000);
setAuthenticated(false);
requireUser()
  .then((user) => {
    if (user) {
      setAuthenticated(true);
      sync();
    }
  })
  .catch(() => {
    setStatus('无法连接登录服务，请稍后刷新。', true);
  });

// 离开页面时停止常亮并释放播放器；pageActive 防止迟到的申请重新持有常亮锁。
window.addEventListener('pagehide', () => {
  pageActive = false;
  clearSleepTimer();
  setScreenAwake(false);
  clearVideo();
});
// 浏览器从页面缓存恢复时，允许后续播放事件再次申请常亮。
window.addEventListener('pageshow', () => {
  pageActive = true;
  updateScreenLock();
});
