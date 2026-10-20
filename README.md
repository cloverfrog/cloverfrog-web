# cloverfrog-web

个人网站 Monorepo，前后端分别运行与部署。

- `frontend/`：静态前端（Caddy）。
- `backend/`：FastAPI 后端（Uvicorn / systemd）。
- `/srv/resources/`：服务器上的独立资源目录，不属于仓库。

部署目标：`/srv/cloverfrog/frontend`、`/srv/cloverfrog/backend`。部署配置应按服务器实际路径调整。各模块细节见子目录文档。

## 本地联调

1. 按后端 README 安装依赖，在后端 `.env` 中设置：

   ```dotenv
   PUBLIC_ORIGIN=http://127.0.0.1:8080
   DEV_MODE=true
   ```

2. 在后端项目根目录启动 API：

   ```powershell
   cd backend
   .\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8765 --reload
   ```

3. 安装 Caddy 后，在本网站项目根目录启动：

   ```bash
   caddy run --config Caddyfile
   ```

4. 打开 `http://127.0.0.1:8080`。现有 `Caddyfile` 提供静态页面，并将 `/api/*` 转发到 `127.0.0.1:8765`；`config.js` 中 `API_URL=''` 表示同源访问。

浏览器地址必须与 `PUBLIC_ORIGIN` 一致，`localhost` 和 `127.0.0.1` 不可混用。仅预览无 API 依赖的模块时，也可使用普通静态服务器。

## 资源与部署

主站为 `https://cloverfrog.xyz`。本地开发后推送至 GitHub，服务器拉取更新，由 Caddy 提供静态服务；API 反向代理到后端。

仓库内 `Caddyfile` 用于本地联调。生产服务器的配置、`.env` 和内部数据放在静态网站目录之外。
