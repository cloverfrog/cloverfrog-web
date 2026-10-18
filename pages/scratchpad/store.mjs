import { pruneCache } from './retention.mjs';

// 按用户 ID 隔离手动保存的恢复副本；编辑器输入不会直接写入此存储。
export class Store {
  // 页面启动时打开数据库，并在读取账号缓存前清理所有账号的过期副本。
  async open() {
    this.db = await new Promise((resolve, reject) => {
      const request = indexedDB.open('cloverfrog-scratchpad', 1);
      request.onupgradeneeded = () => request.result.createObjectStore('accounts');
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    await this.prune();
  }
  async prune() {
    return new Promise((resolve, reject) => {
      const transaction = this.db.transaction('accounts', 'readwrite');
      const cursor = transaction.objectStore('accounts').openCursor();
      cursor.onsuccess = () => {
        const entry = cursor.result;
        if (!entry) return;
        const result = pruneCache(entry.value);
        if (result.changed) entry.update(result.state);
        entry.continue();
      };
      // 游标更新成功不代表事务已提交，清理完成后再允许页面读取缓存。
      transaction.oncomplete = resolve;
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error);
    });
  }
  // 没有缓存时返回空工作区，让新账号与首次使用走相同的恢复流程。
  async get(userId) {
    return new Promise((resolve, reject) => {
      const transaction = this.db.transaction('accounts');
      const request = transaction.objectStore('accounts').get(userId);
      request.onsuccess = () => resolve(request.result || { drafts: [], selected: null });
      request.onerror = () => reject(request.error);
    });
  }
  // 保存独立快照，避免页面随后修改内存对象影响本次准备写入的数据。
  async put(userId, state) {
    return new Promise((resolve, reject) => {
      const transaction = this.db.transaction('accounts', 'readwrite');
      transaction.objectStore('accounts').put(structuredClone(state), userId);
      transaction.oncomplete = resolve;
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error || new Error('Local save aborted'));
    });
  }
}
