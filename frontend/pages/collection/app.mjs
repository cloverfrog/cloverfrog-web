import { API_URL } from '/config.js';
import { requireUser, goToLogin } from '/assets/auth.mjs';
import { formatValue } from './format.mjs';

const $ = (id) => document.getElementById(id);
const isTypes = document.body.dataset.page === 'types';
const params = new URLSearchParams(location.search);
const key = params.get('type') || '';
const requestedPage = Number(params.get('page'));
let page = Number.isInteger(requestedPage) && requestedPage > 0 && requestedPage <= 100000 ? requestedPage : 1;
let controller;
const images = new Set();

function clearContent() {
  $('content').replaceChildren();
  for (const url of images) URL.revokeObjectURL(url);
  images.clear();
}

function expired() {
  controller?.abort();
  clearContent();
  goToLogin();
}

function failure(status, detail, path) {
  const fallback = status === 403 ? '没有访问权限，请检查 PocketBase API Rules。'
    : status === 404 ? '请求地址未找到，请确认后端已更新、API 代理正确且类型已注册。'
    : status === 429 ? '请求过于频繁，请稍后重试。'
    : status === 422 ? '请求参数无效，请检查页面地址。'
    : '服务暂时不可用，请检查后端日志。';
  const info = detail && typeof detail === 'object' ? detail : {};
  const message = typeof info.message === 'string' ? info.message : fallback;
  const diagnostics = [`HTTP ${status}`, path];
  for (const field of ['stage', 'code', 'upstream_status', 'request_id']) {
    if (['string', 'number'].includes(typeof info[field])) diagnostics.push(`${field}=${info[field]}`);
  }
  return new Error(message + '\n' + diagnostics.join(' · '));
}

async function api(path, signal, image = false) {
  const response = await fetch(API_URL + path, {
    credentials: 'same-origin', cache: 'no-store',
    signal: AbortSignal.any([signal, AbortSignal.timeout(30000)])
  });
  if (signal.aborted) throw new DOMException('Request cancelled', 'AbortError');
  if (response.status === 401) {
    expired();
    throw new DOMException('Session expired', 'AbortError');
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw failure(response.status, body?.detail, path);
  }
  return image ? response.blob() : response.json();
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function typeCard(type) {
  const link = element('a', 'type-card');
  link.href = './view.html?type=' + encodeURIComponent(type.key);
  link.append(element('span', 'type-icon', '↗'), element('h2', '', type.name),
    element('span', 'type-action', '查看收藏'));
  return link;
}

function itemCard(item, properties, signal) {
  const card = element('article', 'card');
  const cover = element('div', 'cover');
  const placeholder = element('span', 'placeholder', item.cover ? '图片加载中…' : '暂无封面');
  cover.append(placeholder);
  const body = element('div', 'card-body');
  body.append(element('h2', '', formatValue(item.title)), element('p', 'identifier', formatValue(item.identifier)));
  const attributes = element('dl', 'attributes');
  properties.forEach((property, index) => {
    attributes.append(element('dt', '', property.label),
      element('dd', '', formatValue(item.properties[index], property.format)));
  });
  body.append(attributes);
  card.append(cover, body);
  if (item.cover) {
    api(item.cover, signal, true).then((blob) => {
      if (signal.aborted) return;
      const url = URL.createObjectURL(blob);
      images.add(url);
      const img = element('img');
      img.alt = formatValue(item.title);
      img.onload = () => placeholder.remove();
      img.onerror = () => { img.remove(); placeholder.textContent = '图片无法显示'; };
      img.src = url;
      cover.append(img);
    }).catch((error) => {
      if (error.name !== 'AbortError' && !signal.aborted) placeholder.textContent = '图片加载失败：' + error.message;
    });
  }
  return card;
}

async function load() {
  controller?.abort();
  controller = new AbortController();
  const { signal } = controller;
  clearContent();
  $('retry').hidden = true;
  $('pagination').hidden = true;
  $('content').setAttribute('aria-busy', 'true');
  $('status').textContent = '正在加载…';
  try {
    if (!await requireUser() || signal.aborted) return;
    if (!isTypes && !/^[a-zA-Z0-9_][a-zA-Z0-9_-]{0,63}$/.test(key)) {
      throw new Error('请返回收藏类型页面选择一个类型。');
    }
    const base = '/api/collection/types';
    let config;
    if (!isTypes) {
      config = await api(base + '/' + encodeURIComponent(key), signal);
      if (signal.aborted) return;
      $('heading').textContent = config.name;
      document.title = config.name + ' · Collection';
    }
    const data = await api(base + (isTypes ? '' : '/' + encodeURIComponent(key) + '/items') + '?page=' + page, signal);
    if (signal.aborted) return;
    $('content').append(...data.items.map((item) => isTypes ? typeCard(item) : itemCard(item, config.properties, signal)));
    $('status').textContent = data.items.length ? `共 ${data.totalItems} ${isTypes ? '个类型' : '条收藏'}` : '暂无可见内容。';
    $('pagination').hidden = data.totalPages <= 1 && page === 1;
    $('page-label').textContent = `第 ${page} 页 / 共 ${data.totalPages} 页`;
    $('previous').disabled = page <= 1;
    $('next').disabled = page >= data.totalPages;
  } catch (error) {
    if (signal.aborted) return;
    clearContent();
    $('status').textContent = error.message || '连接失败，请重试。';
    $('retry').hidden = false;
  } finally {
    if (!signal.aborted) $('content').setAttribute('aria-busy', 'false');
  }
}

function changePage(delta) {
  page += delta;
  const url = new URL(location.href);
  url.searchParams.set('page', page);
  history.replaceState(null, '', url);
  load();
}
$('previous').onclick = () => changePage(-1);
$('next').onclick = () => changePage(1);
$('retry').onclick = load;
// 清理对象 URL，避免离开页面后继续保留图片副本。
window.addEventListener('pagehide', () => { controller?.abort(); clearContent(); });
window.addEventListener('pageshow', (event) => { if (event.persisted) load(); });
load();
