# cloverfrog.github.io

cloverfrog 的个人网站源码。首页和各页面模块使用静态 HTML、CSS、JavaScript，无需统一前端框架或构建系统。

## 目录与边界

```text
/
├── index.html        # 网站首页
├── assets/           # 首页资源与公共脚本
├── config.js         # 公共前端配置
├── login/            # 公共登录页与认证接入说明
├── pages/            # 独立页面模块，各自维护 README
├── Caddyfile         # 本地静态服务与 API 反向代理
└── resources/        # 本地大文件资源，不提交 Git
```

`pages/` 下各模块尽量自包含，不互相依赖；需要共享的基础服务放在模块目录外。模块的使用说明留在本模块，公共服务只维护一份说明，由模块引用。

公共认证见 [login/README.md](login/README.md)。API 服务由独立的[后端项目](https://github.com/cloverfrog/cloverfrog.github.io-backend)提供，安装与启动见该项目 README。

## 本地联调

1. 按后端 README 安装依赖，在后端 `.env` 中设置：

   ```dotenv
   PUBLIC_ORIGIN=http://127.0.0.1:8080
   DEV_MODE=true
   ```

2. 在后端项目根目录启动 API：

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8765 --reload
   ```

3. 安装 Caddy 后，在本网站项目根目录启动：

   ```bash
   caddy run --config Caddyfile
   ```

4. 打开 `http://127.0.0.1:8080`。现有 `Caddyfile` 提供静态页面，并将 `/api/*` 转发到 `127.0.0.1:8765`；`config.js` 中 `API_URL=''` 表示同源访问。

浏览器地址必须与 `PUBLIC_ORIGIN` 一致，`localhost` 和 `127.0.0.1` 不可混用。仅预览无 API 依赖的模块时，也可使用普通静态服务器。

## 资源与部署

大文件不提交 Git，本地放在 `resources/`。线上 `/resources/*` 由 Caddy 映射到 `/srv/resources/`，页面使用 `/resources/...` 引用。

主站为 `https://cloverfrog.xyz`，网站 Git 工作目录为 `/srv/web`。本地开发后推送至 GitHub，服务器拉取更新，由 Caddy 提供静态服务；API 反向代理到独立后端。

仓库内 `Caddyfile` 用于本地联调。生产服务器的配置、后端代码、`.env` 和内部数据放在静态网站目录之外。涉及接口变更时，前后端配套发布。
