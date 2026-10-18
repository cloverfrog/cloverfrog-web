// 临时中转内容的生命周期：由页面打开、刷新或文件上传等流程触发清理，不在后台定时删除。
// 云端草稿按 updated 计算，文件按 created 计算，本机副本按 localSavedAt 计算。
// 云端记录与本机恢复副本均保留三天；无效时间不判为过期。
export const RETENTION_MS = 3 * 24 * 60 * 60 * 1000;
export const expired = (timestamp, now = Date.now()) =>
  Number.isFinite(timestamp) && timestamp <= now - RETENTION_MS;
const timestamp = (value) => Date.parse(value?.replace(' ', 'T'));

// 清理云端：删除前重新读取记录，尽量避免删掉列表读取后又被其他设备更新的内容。
// 重读和删除是两个 REST 请求，仍存在并发更新窗口；此流程不提供原子的版本条件删除。
export async function cleanExpired(
  items,
  { collection, owner, field, request, keep = new Set(), now = Date.now() }
) {
  const retained = [];
  let removed = 0,
    failed = 0;
  for (const item of items) {
    if (item.owner !== owner) continue;
    // 正在编辑或等待完成的记录由调用方保护，清理过程跳过它们。
    if (keep.has(item.id) || !expired(timestamp(item[field]), now)) {
      retained.push(item);
      continue;
    }
    const path = `/api/collections/${collection}/records/${encodeURIComponent(item.id)}`;
    try {
      const current = await request(path);
      if (current.owner !== owner) continue;
      if (!expired(timestamp(current[field]), now)) {
        retained.push(current);
        continue;
      }
      await request(path, 'DELETE');
      removed++;
    } catch (error) {
      // 已被另一设备删除视为清理成功；登录失效交给页面处理，其他失败留到下次操作再试。
      if (error.status === 404) {
        removed++;
        continue;
      }
      if (error.status === 401) throw error;
      retained.push(item);
      failed++;
    }
  }
  return { items: retained, removed, failed };
}

// 清理本机恢复副本，并在当前选中项被清理后选中另一份仍保留的草稿。
// 旧副本没有保存时间时，只在首次迁移时补时间，给用户三天取回机会；之后不延长保留期。
export function pruneCache(state, now = Date.now()) {
  let changed = false;
  const drafts = (state.drafts || []).filter((cachedDraft) => {
    if (!Number.isFinite(cachedDraft.localSavedAt)) {
      cachedDraft.localSavedAt = now;
      changed = true;
    }
    if (expired(cachedDraft.localSavedAt, now)) {
      changed = true;
      return false;
    }
    return true;
  });
  const selected = drafts.some((cachedDraft) => cachedDraft.localId === state.selected)
    ? state.selected
    : drafts[0]?.localId || null;
  if (selected !== state.selected) changed = true;
  return { state: { ...state, drafts, selected }, changed };
}
