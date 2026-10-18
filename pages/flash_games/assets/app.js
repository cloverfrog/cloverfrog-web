// Flash 游戏柜的两种页面共用此入口：列表页负责搜索、标签和存档备份，播放页负责创建 Ruffle 播放器。
// 游戏清单、封面和 SWF 共用模块配置的资源目录。
var GAME_BASE = new URL(window.FLASH_GAMES_CONFIG.gameBase, window.location.href).href.replace(
  /\/?$/,
  '/'
);

var state = { games: [], tags: [], filter: 'all', query: '' };

var $ = function (selector) {
  return document.querySelector(selector);
};

function swfPath(game) {
  return GAME_BASE + game.id + '/' + game.id + '.swf';
}

function coverPath(game) {
  return GAME_BASE + game.id + '/' + game.id + '.jpg';
}

// 通过解码后的 SOL 文件头识别 Ruffle 存档，避免导出站点的其他 localStorage 数据。
function isSolValue(value) {
  if (typeof value !== 'string') return false;
  try {
    var decoded = atob(value);
    return (
      decoded.charCodeAt(0) === 0x00 &&
      decoded.charCodeAt(1) === 0xbf &&
      decoded.slice(6, 10) === 'TCSO' &&
      [0x00, 0x04, 0x00, 0x00, 0x00, 0x00].every(function (expectedByte, byteOffset) {
        return decoded.charCodeAt(10 + byteOffset) === expectedByte;
      })
    );
  } catch (e) {
    return false;
  }
}

// 扫描当前站点的本地存储，只收集带有效 SOL 文件头的值，供全量存档备份使用。
function collectEntries() {
  var entries = [];
  for (var i = 0; i < localStorage.length; i++) {
    var key = localStorage.key(i),
      value = key ? localStorage.getItem(key) : null;
    if (key && isSolValue(value)) entries.push({ key: key, value: value });
  }
  return entries;
}

function downloadJson(filename, data) {
  var blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  var url = URL.createObjectURL(blob);
  var link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function setStatus(element, message, isError) {
  if (!element) return;
  element.textContent = message;
  element.classList.toggle('status-text--error', !!isError);
}

// 导出当前浏览器的存档及资源来源，方便换设备或迁移资源地址后恢复。
function exportBackup(element) {
  var entries = collectEntries();
  if (!entries.length) {
    setStatus(element, '当前没有找到可导出的存档。', true);
    return;
  }
  downloadJson('flash-save-backup.json', {
    version: 1,
    exportedAt: new Date().toISOString(),
    origin: GAME_BASE,
    entries: entries
  });
  setStatus(element, '已导出 ' + entries.length + ' 项存档。');
}

// 导入先验证备份版本和存档内容，再经用户确认覆盖本机对应存档；不会自动重载正在玩的游戏。
function importBackup(file, element) {
  var reader = new FileReader();
  reader.onload = function () {
    try {
      var backup = JSON.parse(reader.result);
      if (backup.version !== 1 || !Array.isArray(backup.entries)) throw new Error('格式不正确');
      // 存档键包含资源来源；导入旧站点备份时替换为当前资源路径前缀。
      var oldOrigin = backup.origin || '';
      var oldPrefix = oldOrigin.replace(/^https?:\/\//, '').replace(/:\d+/, '');
      var newPrefix = GAME_BASE.replace(/^https?:\/\//, '').replace(/:\d+/, '');
      var entries = backup.entries.filter(function (e) {
        return typeof e.key === 'string' && isSolValue(e.value);
      });
      if (!entries.length) throw new Error('没有可导入的存档');
      if (!window.confirm('将覆盖 ' + entries.length + ' 项本地存档，是否继续？')) return;
      entries.forEach(function (e) {
        localStorage.setItem(oldPrefix ? e.key.replace(oldPrefix, newPrefix) : e.key, e.value);
      });
      setStatus(element, '已导入 ' + entries.length + ' 项存档，请重新载入游戏。');
    } catch (err) {
      setStatus(element, '导入失败：' + err.message, true);
    }
  };
  reader.readAsText(file);
}

// 搜索文本与标签筛选同时生效，原始清单保持不变。
function gameMatches(game) {
  var text = (game.title + ' ' + (game.originalName || '')).toLowerCase();
  return (
    text.includes(state.query.trim().toLowerCase()) &&
    (state.filter === 'all' || game.tags.includes(state.filter))
  );
}

function buildFilterChips() {
  var html = '<button class="filter-chip is-active" type="button" data-filter="all">全部</button>';
  state.tags.forEach(function (tag) {
    html +=
      '<button class="filter-chip" type="button" data-filter="' + tag + '">' + tag + '</button>';
  });
  return html;
}

// 由搜索词和标签计算可见卡片，同时更新数量与空列表提示。
function renderGames() {
  var grid = $('#game-grid');
  if (!grid) return;
  var games = state.games.filter(gameMatches);
  grid.innerHTML = games
    .map(function (game) {
      return (
        '<a class="game-card" href="play.html?id=' +
        encodeURIComponent(game.id) +
        '">' +
        '<div class="game-card__cover">' +
        '<img src="' +
        coverPath(game) +
        '" alt="' +
        game.title +
        '" loading="lazy"></div>' +
        '<div class="game-card__body"><h2>' +
        game.title +
        '</h2>' +
        (game.originalName ? '<p>' + game.originalName + '</p>' : '') +
        '</div></a>'
      );
    })
    .join('');
  $('#result-count').textContent = '显示 ' + games.length + ' / ' + state.games.length;
  $('#empty-state').hidden = games.length !== 0;
}

// 列表页：读取清单、生成标签，再绑定搜索与存档备份操作。
async function initIndex() {
  var response = await fetch(GAME_BASE + 'games.json');
  if (!response.ok) throw new Error('游戏清单请求失败');
  state.games = await response.json();
  var tagSet = new Set();
  state.games.forEach(function (game) {
    game.tags.filter(Boolean).forEach(function (tag) {
      tagSet.add(tag);
    });
  });
  state.tags = Array.from(tagSet).sort();
  var filterGroup = document.querySelector('.filter-group');
  if (filterGroup) filterGroup.innerHTML = buildFilterChips();
  $('#game-count').textContent = state.games.length + ' 款游戏';
  renderGames();
  $('#game-search').addEventListener('input', function (e) {
    state.query = e.target.value;
    renderGames();
  });
  filterGroup.addEventListener('click', function (e) {
    var c = e.target.closest('[data-filter]');
    if (!c) return;
    state.filter = c.dataset.filter;
    filterGroup.querySelectorAll('[data-filter]').forEach(function (i) {
      i.classList.toggle('is-active', i === c);
    });
    renderGames();
  });
  $('#export-all').addEventListener('click', function () {
    exportBackup($('#backup-status'));
  });
  $('#import-all').addEventListener('change', function (e) {
    if (e.target.files[0]) importBackup(e.target.files[0], $('#backup-status'));
    e.target.value = '';
  });
}

// 播放页：按查询参数选择游戏，重新载入时重建播放器实例。
async function initPlay() {
  var gameId = new URLSearchParams(window.location.search).get('id');
  var response = await fetch(GAME_BASE + 'games.json');
  if (!response.ok) throw new Error('游戏清单请求失败');
  var games = await response.json();
  var game = games.find(function (game) {
    return game.id === gameId;
  });
  if (!game) {
    $('#play-title').textContent = '游戏不存在';
    $('#player-status').textContent = '请返回列表选择一个游戏。';
    return;
  }
  document.title = game.title + ' · Flash 游戏柜';
  $('#play-title').textContent = game.title;
  $('#play-subtitle').textContent = game.originalName || '';
  $('#details-title').textContent = game.title;
  // 重建容器里的播放器，使“重新载入”从新的游戏实例开始，而不是复用旧运行状态。
  var loadPlayer = function () {
    var c = $('#player-container');
    c.innerHTML = '';
    var p =
      window.RufflePlayer &&
      window.RufflePlayer.newest &&
      window.RufflePlayer.newest().createPlayer();
    if (!p) {
      c.innerHTML =
        '<div class="loading-state" role="status">Ruffle 加载失败，请检查网络后重新载入。</div>';
      return;
    }
    p.style.width = '100%';
    p.style.height = '100%';
    c.appendChild(p);
    // base 指向 SWF 所在目录，让游戏内部的相对资源请求落到正确位置。
    p.ruffle().config = {
      base: new URL(swfPath(game), document.baseURI).href.replace(/[^/]*$/, ''),
      backgroundColor: '#000000',
      forceScale: true,
      letterbox: 'on',
      scale: 'showAll'
    };
    p.ruffle()
      .load(swfPath(game))
      .catch(function () {
        c.innerHTML =
          '<div class="loading-state" role="status">游戏资源加载失败，请稍后重新载入。</div>';
      });
  };
  $('#reload-game').addEventListener('click', loadPlayer);
  $('#fullscreen-game').addEventListener('click', function () {
    $('#player-container').requestFullscreen && $('#player-container').requestFullscreen();
  });
  loadPlayer();
}

// 通过 HTML 的 data-page 选择入口，避免列表页访问只存在于播放页的元素。
if (document.body.dataset.page === 'index')
  initIndex().catch(function (e) {
    console.error('Error in initIndex:', e);
    setStatus($('#backup-status'), '游戏清单加载失败。', true);
  });
if (document.body.dataset.page === 'play')
  initPlay().catch(function (e) {
    console.error('Error in initPlay:', e);
    $('#play-title').textContent = '页面加载失败';
  });
