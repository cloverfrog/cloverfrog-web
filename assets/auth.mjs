// 网站公共认证入口：查询会话、引导登录与退出，供页面共用；凭据由后端 Cookie 管理。
import { API_URL } from '/config.js';

// 保留当前页面的路径、查询参数和锚点，供登录成功后返回。
export function loginUrl() {
  return (
    '/login/?returnTo=' + encodeURIComponent(location.pathname + location.search + location.hash)
  );
}

export function goToLogin() {
  location.assign(loginUrl());
}

// 登录态由浏览器的 HttpOnly Cookie 携带，前端只读取会话结果。
export async function authRequest(action, body) {
  const response = await fetch(API_URL + '/api/auth/' + action, {
    method: action === 'session' ? 'GET' : 'POST',
    credentials: 'same-origin',
    cache: 'no-store',
    headers: body ? { 'Content-Type': 'application/json' } : {},
    ...(body ? { body: JSON.stringify(body) } : {}),
    signal: AbortSignal.timeout(15000)
  });
  if (!response.ok)
    throw new Error(
      response.status === 429
        ? '尝试过于频繁，请稍后再试。'
        : response.status === 401
          ? '登录失败，请检查邮箱和密码。'
          : '登录服务暂时不可用，请稍后重试。'
    );
  return response.json();
}

// 受保护页面应在加载业务数据前调用；跳转登录时返回 null。
export async function requireUser() {
  const data = await authRequest('session');
  if (!data.authenticated) {
    goToLogin();
    return null;
  }
  return data.user;
}

// 等待后端清除 Cookie 后再跳转，失败时由调用页面提示重试。
export async function logout() {
  await authRequest('logout');
  goToLogin();
}

// 登录回跳只接受本站普通页面，防止跳往外站、重新进入登录循环或直接打开 API。
// 无效地址统一返回首页；反斜杠和控制字符也拒绝，避免浏览器对路径产生不同解释。
export function safeReturnPath(value) {
  try {
    if (!value?.startsWith('/') || value.startsWith('//') || /[\\\x00-\x1f]/.test(value))
      return '/';
    const url = new URL(value, location.origin);
    if (
      url.origin !== location.origin ||
      /^\/login(?:\/|$)/i.test(url.pathname) ||
      /^\/api(?:\/|$)/i.test(url.pathname)
    )
      return '/';
    return url.pathname + url.search + url.hash;
  } catch {
    return '/';
  }
}
