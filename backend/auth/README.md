# 公共认证

使用 PocketBase `users` 集合认证网站普通账号，业务模块通过本服务取得当前用户身份。前端登录入口和接入方式见[网站登录说明](https://github.com/cloverfrog/cloverfrog.github.io/blob/main/login/README.md)。

## 接口

| 方法与路径 | 行为 |
| --- | --- |
| `POST /api/auth/login` | JSON `{"identity":"邮箱","password":"密码"}`，成功返回 authenticated 和 user |
| `GET /api/auth/session` | 已登录返回 authenticated=true 和 user；未登录返回 authenticated=false |
| `POST /api/auth/logout` | 清除当前浏览器 Cookie，返回 authenticated=false |

`user` 仅包含 `id`、`email`。登录、退出要求 Origin 与 `PUBLIC_ORIGIN` 一致，并拒绝 cross-site 请求。登录输入校验失败返回 422；登录限流返回 429，当前按进程内客户端 IP 计数，每 15 分钟最多 5 次尝试，成功尝试也计入。

## 会话行为

后端把邮箱密码提交给 PocketBase `users/auth-with-password`，成功后将普通用户 token 写入 `site_auth` Cookie：

- Path 为 `/api/`，启用 HttpOnly、SameSite=Strict；生产环境额外启用 Secure。
- 有效期跟随 PocketBase token；查询会话或请求受保护接口时通过 `auth-refresh` 验证并续期。
- 密码不落盘，前端脚本不读取或保存登录 token；没有额外的账号、密码或会话数据库。

长期不用导致 token 过期后重新登录。后端重启不会主动清除浏览器 Cookie，有效性仍由 PocketBase 判断。

认证明确失效时清除 Cookie；受保护接口返回 401，会话查询返回 authenticated=false。认证服务临时故障返回 503，保留 Cookie 供恢复后重试。退出只清除当前浏览器会话，不撤销其他设备已有 token。

## 后端模块接入

从 `auth.service` 引入 `require_user`，用 FastAPI `Depends(require_user)` 保护接口。需要访问身份时接收返回的 `Identity`，其中 `user` 为必要用户信息，`token` 仅供后端访问 PocketBase。

写接口通过 `check_origin(request)` 或 `Depends(check_origin)` 校验来源。公共 Cookie 的写入和清理由应用入口中间件负责，模块不另建登录接口，也不向前端返回登录 token。

## 配置与验证

依赖 `POCKETBASE_URL`、`PUBLIC_ORIGIN` 和 `DEV_MODE`，加载方式见[后端 README](../README.md)。账号在 PocketBase 管理，当前不提供注册；`users` 的 Create 规则保持 locked。无需管理员 token 或独立会话密钥。

认证测试位于 `tests/test_api.py`，覆盖登录、续期、过期、退出、限流、来源校验、服务故障、Cookie 属性与重启后继续认证。统一运行命令见后端 README。
