// 统一登录页：先检查已有会话，必要时提交凭据，成功后返回经过校验的目标页。
import { authRequest, safeReturnPath } from '/assets/auth.mjs';

const form = document.querySelector('#login');
const button = form.querySelector('button');
const status = document.querySelector('#status');
// 先校验回跳地址，再供已有会话和本次登录共用。
const returnTo = safeReturnPath(new URLSearchParams(location.search).get('returnTo'));

// 登录成功后清空密码输入，并替换历史记录中的登录页。
form.onsubmit = async (event) => {
  event.preventDefault();
  button.disabled = true;
  status.textContent = '正在登录…';
  try {
    await authRequest('login', {
      identity: document.querySelector('#identity').value.trim(),
      password: document.querySelector('#password').value
    });
    document.querySelector('#password').value = '';
    location.replace(returnTo);
  } catch (error) {
    status.textContent = error.message;
  } finally {
    button.disabled = false;
  }
};

// 已登录用户直接回到目标页面，无需重复提交凭据。
try {
  const data = await authRequest('session');
  if (data.authenticated) location.replace(returnTo);
  else status.textContent = '';
} catch (error) {
  status.textContent = error.message;
} finally {
  button.disabled = false;
}
