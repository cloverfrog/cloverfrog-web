// 首页的登录态展示与退出操作；模块入口本身允许匿名浏览。
import { authRequest, logout } from './auth.mjs';

const button = document.getElementById('logout');
const status = document.getElementById('auth-status');

// 请求期间禁用按钮，避免重复退出；失败后允许用户手动重试。
button.onclick = async () => {
  button.disabled = true;
  status.textContent = '';
  try {
    await logout();
  } catch {
    status.textContent = '退出失败，请稍后重试。';
  } finally {
    button.disabled = false;
  }
};

// 首页允许匿名访问，会话结果只决定是否显示退出按钮。
try {
  const session = await authRequest('session');
  button.hidden = !session.authenticated;
} catch {
  status.textContent = '无法连接登录服务，请稍后刷新重试。';
}
