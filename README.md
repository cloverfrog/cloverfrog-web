# cloverfrog-web

个人网站 Monorepo，前后端分别运行与部署。

- `frontend/`：静态前端（Caddy）。
- `backend/`：FastAPI 后端（Uvicorn / systemd）。
- `/srv/resources/`：服务器上的独立资源目录，不属于仓库。

部署目标：`/srv/cloverfrog/frontend`、`/srv/cloverfrog/backend`。部署配置应按服务器实际路径调整。各模块细节见子目录文档。
