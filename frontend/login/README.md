# 公共登录与前端认证

登录页位于 `/login/`，模块通过 `/assets/auth.mjs` 使用网站公共认证。后端接口与 Cookie 行为见[后端认证说明](https://github.com/cloverfrog/cloverfrog.github.io-backend/blob/main/auth/README.md)。

## 页面行为

未登录时，模块跳转 `/login/?returnTo=原页面地址`；登录成功后返回原页面。直接打开登录页且未提供返回地址时，登录后返回首页。返回地址仅接受本站路径，排除登录页和 API 路径。

同一浏览器、同一站点来源共用登录状态。退出登录入口统一位于首页，仅在已登录时显示；业务模块不提供退出按钮，可通过返回首页退出。退出成功后前往登录页，并清除当前浏览器的全站会话；其他已打开页面在后续受保护接口请求返回 401 时处理过期，不主动通知其他标签页。

登录服务临时不可用时显示错误，不按未登录处理。前端不读取或保存登录 token。

## 模块接入

在模块入口脚本中查询会话，再加载模块数据：

```js
import { requireUser, goToLogin } from '/assets/auth.mjs';

try {
  const user = await requireUser();
  if (user) {
    // 在此初始化本模块；user 包含 id、email。
  }
} catch (error) {
  // 在本模块显示连接错误，并允许用户重试。
}
```

| 导出 | 用途 |
| --- | --- |
| `requireUser()` | 返回用户信息；未登录时跳转并返回 null；服务故障时抛错 |
| `goToLogin()` | 携带当前路径、查询参数和锚点前往登录页 |
| `logout()` | 请求退出，成功后前往登录页；失败时抛错 |
| `authRequest(action, body)` | 调用 session、login、logout；需要自行安排退出后清理时使用 |
| `loginUrl()` / `safeReturnPath(value)` | 构造登录地址 / 校验返回路径 |

模块不放登录框。模块自身接口返回 401 时调用 `goToLogin()`；403、404 和临时服务故障按模块错误处理，避免反复跳登录页。涉及未保存内容时，由模块决定如何提示或清理，再跳转。

前端认证脚本从根目录 `config.js` 读取 `API_URL`。当前使用同源 `/api/*` 和 Cookie，本地联调方法见[网站 README](../README.md)。
