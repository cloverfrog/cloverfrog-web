import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { formatValue } from '../frontend/pages/collection/format.mjs';

test('基础字段保留零、false、业务编号及纯文本', () => {
  assert.equal(formatValue(0, 'number'), '0');
  assert.equal(formatValue(false, 'boolean'), '否');
  assert.equal(formatValue('001'), '001');
  assert.equal(formatValue('<script>example</script>'), '<script>example</script>');
  assert.equal(formatValue(['a', 'b'], 'tags'), 'a · b');
});

test('缺失或不兼容的数据使用占位，不隐式展示对象', () => {
  for (const value of [null, undefined, '', { private: 'hidden' }]) assert.equal(formatValue(value), '—');
  assert.equal(formatValue('false', 'boolean'), '—');
  assert.equal(formatValue('1', 'number'), '—');
  assert.equal(formatValue([], 'tags'), '—');
});

// A minimal DOM checks the page lifecycle, not just the field formatter.
function pageHarness() {
  class Element {
    constructor(tag = 'div') { this.tag = tag; this.children = []; this.hidden = false; this.textContent = ''; }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
    setAttribute() {}
    remove() {}
  }
  const nodes = new Map();
  const get = (id) => { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); };
  const requests = [];
  const revoked = [];
  let redirects = 0;
  class PageURL extends URL {
    static createObjectURL() { return 'blob:fixture'; }
    static revokeObjectURL(url) { revoked.push(url); }
  }
  const location = { search: '?type=demo', href: 'https://example.test/pages/collection/view.html?type=demo' };
  const context = vm.createContext({
    document: { body: { dataset: { page: 'items' } }, getElementById: get,
      createElement: (tag) => new Element(tag) },
    location, history: { replaceState(_state, _unused, url) { location.href = String(url); } },
    window: { addEventListener() {} },
    URL: PageURL, URLSearchParams, AbortController, AbortSignal, DOMException, formatValue,
    API_URL: '', requireUser: async () => ({ id: 'fixture' }), goToLogin: () => { redirects++; },
    fetch: (url) => new Promise((resolve) => requests.push({ url, resolve })),
  });
  const source = readFileSync(new URL('../frontend/pages/collection/app.mjs', import.meta.url), 'utf8')
    .replace(/^import .*;\r?\n/gm, '');
  vm.runInContext(source, context);
  const settle = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
  const respond = (index, body, status = 200) => requests[index].resolve({
    status, ok: status === 200, json: async () => body, blob: async () => ({})
  });
  const config = { name: 'Demo', properties: [{ label: 'Custom label', format: 'boolean' }] };
  const items = { page: 1, totalPages: 2, totalItems: 25,
    items: [{ id: 'fixture', title: '<script>text</script>', identifier: '001', properties: [false],
      cover: '/api/collection/types/demo/items/fixture/resources/cover' }] };
  return { get, requests, revoked, settle, respond, config, items, redirects: () => redirects };
}

test('配置标签、纯文本卡片与分页，并在图片认证失效时清除内容', async () => {
  const h = pageHarness();
  await h.settle();
  h.respond(0, h.config);
  await h.settle();
  h.respond(1, h.items);
  await h.settle();
  const card = h.get('content').children[0];
  const body = card.children[1];
  assert.equal(body.children[0].textContent, '<script>text</script>');
  assert.equal(body.children[2].children[0].textContent, 'Custom label');
  assert.equal(body.children[2].children[1].textContent, '否');
  assert.equal(h.get('previous').disabled, true);
  assert.equal(h.get('next').disabled, false);
  h.respond(2, null, 401);
  await h.settle();
  assert.equal(h.redirects(), 1);
  assert.equal(h.get('content').children.length, 0);
});

test('翻页释放图片，旧请求的迟到错误不会清除新页面', async () => {
  const h = pageHarness();
  await h.settle(); h.respond(0, h.config);
  await h.settle(); h.respond(1, h.items);
  await h.settle(); h.respond(2, {});
  await h.settle();
  h.get('next').onclick();
  await h.settle();
  assert.deepEqual(h.revoked, ['blob:fixture']);
  // A second retry cancels the in-flight page-2 configuration request.
  h.get('retry').onclick();
  await h.settle();
  h.respond(4, h.config);
  await h.settle();
  assert.ok(h.requests[5].url.endsWith('/items?page=2'));
  h.respond(5, { ...h.items, items: [] });
  await h.settle();
  h.respond(3, null, 401);
  await h.settle();
  assert.equal(h.redirects(), 0);
  assert.equal(h.get('status').textContent, '暂无可见内容。');
});

test('页面显示接口错误阶段、上游状态与关联编号', async () => {
  const h = pageHarness();
  await h.settle();
  h.respond(0, { detail: { message: '类型配置读取失败', stage: 'type_view', code: 'type_view_failed',
    upstream_status: 404, request_id: 'trace-example' } }, 404);
  await h.settle();
  const text = h.get('status').textContent;
  for (const expected of ['类型配置读取失败', 'HTTP 404', 'type_view', 'trace-example', '/api/collection/types/demo']) {
    assert.ok(text.includes(expected));
  }
  assert.equal(h.get('retry').hidden, false);
});

test('图片失败保留媒体诊断，通用路由404提示检查部署', async () => {
  const h = pageHarness();
  await h.settle(); h.respond(0, h.config);
  await h.settle(); h.respond(1, h.items);
  await h.settle();
  h.respond(2, { detail: { message: '媒体网关返回错误', stage: 'media_fetch',
    code: 'media_http_error', upstream_status: 404, request_id: 'media-trace' } }, 404);
  await h.settle();
  const placeholder = h.get('content').children[0].children[0].children[0];
  assert.ok(placeholder.textContent.includes('媒体网关返回错误'));
  assert.ok(placeholder.textContent.includes('media-trace'));
  const other = pageHarness();
  await other.settle();
  other.respond(0, { detail: 'Not Found' }, 404);
  await other.settle();
  assert.ok(other.get('status').textContent.includes('后端已更新'));
  assert.ok(other.get('status').textContent.includes('HTTP 404'));
});
