// 草稿工作台：输入只修改内存，点击保存才写本机恢复副本和云端；刷新用于主动读取其他设备的修改。
// 本文件组织编辑流程，store.mjs 管理本机副本，retention.mjs 管理过期清理，files.mjs 管理文件传输。
import { API_URL } from '/config.js';
import { requireUser, goToLogin } from '/assets/auth.mjs';
import { Store } from './store.mjs';
import { FileTransfer } from './files.mjs';
import { pruneCache, cleanExpired } from './retention.mjs';

const $ = (id) => document.getElementById(id);
// 正文显示设置：记住本机的字号、字体、行高和换行习惯，不随草稿同步到其他设备。
const displayKey = 'scratchpad-display';
const display = { size: 16, font: 'mono', lineHeight: 1.65, wrap: true };
try {
  const saved = JSON.parse(localStorage.getItem(displayKey));
  if ([12, 14, 16, 18, 20, 22, 24].includes(saved?.size)) display.size = saved.size;
  if (['mono', 'system'].includes(saved?.font)) display.font = saved.font;
  if ([1.5, 1.65, 1.8].includes(saved?.lineHeight)) display.lineHeight = saved.lineHeight;
  if (typeof saved?.wrap === 'boolean') display.wrap = saved.wrap;
} catch {
  /* 偏好数据损坏或存储被禁用时，使用默认显示设置继续编辑。 */
}
function applyDisplay(persist = false) {
  const editor = $('content');
  editor.style.setProperty('--editor-size', `${display.size}px`);
  editor.style.setProperty('--editor-line-height', display.lineHeight);
  editor.style.setProperty(
    '--editor-font',
    display.font === 'system'
      ? 'system-ui, -apple-system, "Microsoft YaHei", sans-serif'
      : 'ui-monospace, Consolas, "Microsoft YaHei", monospace'
  );
  editor.wrap = display.wrap ? 'soft' : 'off';
  $('font-size').textContent = `${display.size}px`;
  $('font-smaller').disabled = display.size === 12;
  $('font-larger').disabled = display.size === 24;
  $('font-family').value = display.font;
  $('line-height').value = String(display.lineHeight);
  $('word-wrap').checked = display.wrap;
  if (persist) {
    try {
      localStorage.setItem(displayKey, JSON.stringify(display));
    } catch {
      /* 无法记住偏好时，仍让设置在当前页面立即生效。 */
    }
  }
}
for (const [id, step] of [
  ['font-smaller', -2],
  ['font-larger', 2]
]) {
  $(id).onclick = () => {
    display.size = Math.max(12, Math.min(24, display.size + step));
    applyDisplay(true);
  };
}
$('font-family').onchange = (event) => {
  display.font = event.target.value;
  applyDisplay(true);
};
$('line-height').onchange = (event) => {
  display.lineHeight = Number(event.target.value);
  applyDisplay(true);
};
$('word-wrap').onchange = (event) => {
  display.wrap = event.target.checked;
  applyDisplay(true);
};
applyDisplay();
const store = new Store();
// 编辑状态：dirty 表示未保存修改，pending 表示正在等待完成操作的撤销期限。
// session 持有当前账号的草稿；busy 防止云端操作重叠，但不禁止用户继续输入。
// composing 标记输入法组词，刷新结束时避免重写输入框打断中文输入。
let session,
  busy = false,
  composing = false;
const files = new FileTransfer(undefined, (error) => {
  notice(errorMessage(error));
});
const notice = (text) => {
  $('notice').textContent = text;
};
const selected = () =>
  session?.drafts.find(
    (currentDraft) => currentDraft.localId === session.selected && !currentDraft.pending
  );
const hasChanges = () =>
  session?.drafts.some((currentDraft) => currentDraft.dirty || currentDraft.pending);
const recordId = () =>
  Array.from(
    crypto.getRandomValues(new Uint8Array(15)),
    (randomByte) => 'abcdefghijklmnopqrstuvwxyz0123456789'[randomByte % 36]
  ).join('');
// localId 用于本机选择，id 是云端记录 ID，createId 在首次创建重试时保持不变。
// seq 每次编辑递增，用于判断请求发出后是否又出现了未保存修改。
const draft = (record) => ({
  localId: record.id || crypto.randomUUID(),
  id: record.id || null,
  createId: record.id || recordId(),
  title: record.title || '',
  content: record.content || '',
  seq: 0,
  dirty: !record.id,
  localSavedAt: Date.now()
});

// 保留 PocketBase 的记录路径形式，统一转发到带登录校验的同源代理。
async function request(path, method = 'GET', body) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(API_URL + '/api/scratchpad' + path.slice(4), {
      method,
      credentials: 'same-origin',
      headers: {
        ...(body ? { 'Content-Type': 'application/json' } : {})
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
      signal: controller.signal,
      cache: 'no-store'
    });
    const data = response.status === 204 ? null : await response.json();
    if (!response.ok)
      throw Object.assign(new Error(data?.message || '请求失败'), { status: response.status });
    return data;
  } finally {
    clearTimeout(timer);
  }
}
function errorMessage(error) {
  if (error.status === 401) {
    goToLogin();
    return '登录已过期，正在前往登录页。未保存内容请先复制保留。';
  }
  if (error.status === 403)
    return 'PocketBase 权限未配置（403），请按说明设置 scratchpads 的 API Rules。无需反复登录。';
  if (error.status === 404) return '集合或草稿不存在，或当前账号无权访问（404）。当前文本仍保留。';
  if (error.status === 400)
    return '保存被拒绝（400），请检查 owner 权限规则、字段长度及 version 是否仍为必填。当前文本仍保留。';
  return '请求失败，请检查网络后手动重试。当前文本仍保留。';
}
// 更新列表、操作按钮与编辑区；输入和异步保存期间传 false，避免重写输入框导致光标跳动。
function render(text = true) {
  const currentDraft = selected();
  $('workspace').hidden = !session;
  $('editor').hidden = !currentDraft;
  $('empty').hidden = !!currentDraft;
  $('drafts').replaceChildren(
    ...(session?.drafts || [])
      .filter((otherDraft) => !otherDraft.pending)
      .map((otherDraft) => {
        const button = document.createElement('button');
        button.textContent = (otherDraft.title || '未命名草稿') + (otherDraft.dirty ? ' *' : '');
        button.setAttribute('aria-current', String(otherDraft === currentDraft));
        button.disabled = busy;
        button.onclick = () => {
          session.selected = otherDraft.localId;
          render();
        };
        return button;
      })
  );
  if (text) {
    $('title').value = currentDraft?.title || '';
    $('content').value = currentDraft?.content || '';
  }
  for (const id of ['save', 'new', 'refresh', 'complete']) $(id).disabled = busy;
  $('status').textContent = busy
    ? '处理中…'
    : currentDraft?.dirty
      ? '未保存'
      : currentDraft
        ? '已保存'
        : '';
  $('undo').replaceChildren(
    ...(session?.drafts || [])
      .filter((otherDraft) => otherDraft.pending)
      .map((otherDraft) => {
        const paragraph = document.createElement('p');
        paragraph.textContent = `待完成：${otherDraft.title || '未命名草稿'}`;
        const button = document.createElement('button');
        button.textContent = '撤销';
        button.disabled = otherDraft.deleting;
        button.onclick = () => {
          clearTimeout(otherDraft.timer);
          otherDraft.pending = false;
          session.selected = otherDraft.localId;
          render();
        };
        paragraph.append(button);
        return paragraph;
      })
  );
}
// 手动保存的本机恢复副本：用于重新打开页面后恢复内容，与云端记录分开维护。
async function localSnapshot(activeSession) {
  // 只由手动保存触发，避免用户尚未决定保存的输入被自动落盘。
  // 仅保存可恢复的数据，不持久化删除计时器等运行中状态。
  await store.put(activeSession.auth.record.id, {
    selected: activeSession.selected,
    drafts: activeSession.drafts.map((currentDraft) => ({
      localId: currentDraft.localId,
      id: currentDraft.id,
      createId: currentDraft.createId,
      title: currentDraft.title,
      content: currentDraft.content,
      seq: currentDraft.seq,
      dirty: currentDraft.dirty,
      localSavedAt: currentDraft.localSavedAt,
      pending: null,
      op: null
    }))
  });
}
// 刷新只覆盖干净的草稿；未保存内容和等待完成的草稿继续保留在内存中。
async function refresh() {
  if (!session || busy) return;
  const activeSession = session;
  busy = true;
  render(false);
  try {
    await store.prune();
    const protectedDrafts = activeSession.drafts.filter(
      (currentDraft) => currentDraft.dirty || currentDraft.pending
    );
    const retained = pruneCache({
      drafts: activeSession.drafts.filter(
        (currentDraft) => !protectedDrafts.includes(currentDraft)
      ),
      selected: activeSession.selected
    }).state;
    retained.drafts.push(...protectedDrafts);
    if (retained.drafts.some((currentDraft) => currentDraft.localId === activeSession.selected))
      retained.selected = activeSession.selected;
    activeSession.drafts = retained.drafts;
    activeSession.selected = retained.selected;
    // 先读完所有分页再清理过期记录，防止删除导致后续分页位移而漏读。
    const items = [];
    let result,
      page = 1;
    do {
      result = await request(`/api/collections/scratchpads/records?perPage=200&page=${page++}`);
      items.push(...result.items);
    } while (page <= result.totalPages);
    const cleaned = await cleanExpired(items, {
      collection: 'scratchpads',
      owner: activeSession.auth.record.id,
      field: 'updated',
      request,
      keep: new Set(
        activeSession.drafts
          .filter((currentDraft) => currentDraft.dirty || currentDraft.pending)
          .map((currentDraft) => currentDraft.id)
      )
    });
    // 先移除已从云端消失的干净副本，再合并新增记录和已保存内容。
    const remote = new Map(cleaned.items.map((record) => [record.id, record]));
    activeSession.drafts = activeSession.drafts.filter(
      (currentDraft) => currentDraft.dirty || currentDraft.pending || remote.has(currentDraft.id)
    );
    for (const record of cleaned.items) {
      const existing = activeSession.drafts.find((currentDraft) => currentDraft.id === record.id);
      if (!existing) activeSession.drafts.push(draft(record));
      else if (!existing.dirty && !existing.pending) {
        existing.title = record.title;
        existing.content = record.content;
      }
    }
    if (
      !activeSession.drafts.some(
        (currentDraft) => currentDraft.localId === activeSession.selected && !currentDraft.pending
      )
    )
      activeSession.selected = activeSession.drafts.find(
        (currentDraft) => !currentDraft.pending
      )?.localId;
    notice(
      `已读取云端草稿。${cleaned.removed ? `已自动清理 ${cleaned.removed} 份过期草稿。` : ''}${cleaned.failed ? `${cleaned.failed} 份清理失败，下次刷新重试。` : ''}其他设备保存后，点击“刷新列表”查看。`
    );
  } catch (error) {
    notice(errorMessage(error));
  } finally {
    busy = false;
    render(!composing);
  }
}
// 保存当前草稿：本机留副本 → 云端创建或更新 → 根据编辑序号判断是否还有后续未保存输入。
async function save() {
  const activeSession = session,
    currentDraft = selected();
  if (!currentDraft || busy) return;
  busy = true;
  render(false);
  // 捕获点击保存时的编辑序号；等待网络期间，用户仍可能继续输入。
  const seq = currentDraft.seq,
    body = { title: currentDraft.title, content: currentDraft.content };
  try {
    currentDraft.localSavedAt = Date.now();
    // 先存本机再请求云端，即使断网或服务器拒绝保存，本次手动保存仍有恢复副本。
    await localSnapshot(activeSession);
    let result;
    if (currentDraft.id)
      result = await request(
        '/api/collections/scratchpads/records/' + currentDraft.id,
        'PATCH',
        body
      );
    else {
      try {
        result = await request('/api/collections/scratchpads/records', 'POST', {
          ...body,
          owner: activeSession.auth.record.id,
          id: currentDraft.createId
        });
      } catch (error) {
        // 首次创建可能已在服务端成功，但响应超时使前端没有拿到记录 ID。
        // 下次手动保存沿用 createId；遇到 400 时先确认记录存在，再改为更新，避免重复创建。
        if (error.status !== 400) throw error;
        try {
          await request('/api/collections/scratchpads/records/' + currentDraft.createId);
        } catch {
          throw error;
        }
        result = await request(
          '/api/collections/scratchpads/records/' + currentDraft.createId,
          'PATCH',
          body
        );
      }
    }
    currentDraft.id = result.id;
    currentDraft.dirty = currentDraft.seq !== seq;
    await localSnapshot(activeSession);
    notice(currentDraft.dirty ? '已保存刚才的内容；后续修改尚未保存。' : '已保存到云端。');
  } catch (error) {
    notice(errorMessage(error));
  } finally {
    busy = false;
    render(false);
  }
}
// 同一用户重新初始化时保留内存编辑；切换用户时只读取对应账号的恢复副本。
async function start(auth) {
  const previous = session;
  for (const currentDraft of previous?.drafts || []) clearTimeout(currentDraft.timer);
  const sameUser = previous?.auth.record.id === auth.record.id;
  const cached = sameUser ? null : await store.get(auth.record.id);
  session = {
    auth,
    drafts: sameUser
      ? previous.drafts
      : (cached.drafts || []).map((record) => ({
          ...draft(record),
          localId: record.localId || record.id || crypto.randomUUID(),
          createId: record.createId || record.id || recordId(),
          dirty: !!(record.dirty || record.op || record.pending),
          pending: false,
          seq: record.seq || 0,
          localSavedAt: record.localSavedAt
        })),
    selected: sameUser ? previous.selected : cached.selected
  };
  for (const currentDraft of session.drafts) currentDraft.pending = false;
  render();
  files.setSession(auth);
  await refresh();
}
// 新建与输入只更新内存；切换草稿不会自动上传或创建恢复副本。
$('new').onclick = () => {
  if (!session || busy) return;
  const currentDraft = draft({});
  session.drafts.push(currentDraft);
  session.selected = currentDraft.localId;
  render();
  $('content').focus();
};
function edit() {
  const currentDraft = selected();
  if (!currentDraft) return;
  currentDraft.title = $('title').value;
  currentDraft.content = $('content').value;
  currentDraft.dirty = true;
  currentDraft.seq++;
  render(false);
}
for (const id of ['title', 'content']) {
  $(id).addEventListener('input', edit);
  $(id).addEventListener('compositionstart', () => {
    composing = true;
  });
  $(id).addEventListener('compositionend', () => {
    composing = false;
    edit();
  });
}
$('save').onclick = save;
$('refresh').onclick = refresh;
// 复制用于把正文交给其他应用，不改变草稿的保存或完成状态。
async function copy() {
  const currentDraft = selected();
  if (!currentDraft) return;
  try {
    await navigator.clipboard.writeText(currentDraft.content);
    notice('已复制全文；复制不会保存或完成草稿。');
  } catch {
    notice('请手动复制选中的正文。');
    $('content').focus();
    $('content').select();
  }
}
$('copy').onclick = copy;
// 快捷键复用按钮操作；输入法组词时不处理，避免回车选词误触发复制。
document.addEventListener('keydown', (event) => {
  if (!(event.ctrlKey || event.metaKey) || event.isComposing || composing || event.keyCode === 229)
    return;
  if (event.key.toLowerCase() === 's') {
    event.preventDefault();
    save();
  }
  if (event.key === 'Enter') {
    event.preventDefault();
    copy();
  }
});
// 完成操作先提供八秒撤销窗口，再删除云端记录和对应的本机恢复副本。
$('complete').onclick = () => {
  const activeSession = session,
    currentDraft = selected();
  if (!currentDraft || busy) return;
  if (currentDraft.dirty && !confirm('这份草稿有未保存修改，完成将丢弃它们。继续？')) return;
  currentDraft.pending = true;
  activeSession.selected = activeSession.drafts.find(
    (otherDraft) => otherDraft !== currentDraft && !otherDraft.pending
  )?.localId;
  render();
  currentDraft.timer = setTimeout(async () => {
    // 计时器只处理发起操作时的账号和草稿；已撤销或切换账号时直接失效。
    if (session !== activeSession || !currentDraft.pending) return;
    if (busy) {
      currentDraft.pending = false;
      notice('当前操作尚未结束，请稍后重新点击完成。');
      render();
      return;
    }
    busy = true;
    currentDraft.deleting = true;
    render(false);
    try {
      if (currentDraft.id)
        await request('/api/collections/scratchpads/records/' + currentDraft.id, 'DELETE');
      activeSession.drafts = activeSession.drafts.filter(
        (otherDraft) => otherDraft !== currentDraft
      );
      // 只从旧恢复副本中移除已完成的这一份；此时不能顺便保存其他尚未手动保存的输入。
      const cached = await store.get(activeSession.auth.record.id);
      cached.drafts = cached.drafts.filter(
        (otherDraft) =>
          otherDraft.localId !== currentDraft.localId &&
          (!currentDraft.id || otherDraft.id !== currentDraft.id)
      );
      await store.put(activeSession.auth.record.id, cached);
      notice('已完成。');
    } catch (error) {
      currentDraft.pending = false;
      activeSession.selected = currentDraft.localId;
      notice(errorMessage(error));
    } finally {
      currentDraft.deleting = false;
      busy = false;
      render();
    }
  }, 8000);
};
// 页面关闭前只提示未保存或传输中的工作，不触发自动保存。
window.addEventListener('beforeunload', (event) => {
  if (hasChanges() || files.busy) {
    event.preventDefault();
    event.returnValue = '';
  }
});
// 启动顺序：先显示空工作台，再检查登录、清理本机过期副本、恢复当前账号并读取云端。
render();
try {
  const user = await requireUser();
  if (user) {
    await store.open();
    try {
      localStorage.removeItem('scratchpad-auth');
    } catch {
      /* 清除旧版本遗留的本地 token；当前登录态统一由公共认证维护。 */
    }
    await start({ record: user });
  }
} catch {
  notice('无法连接登录服务或读取本机草稿，请稍后刷新重试。');
}
