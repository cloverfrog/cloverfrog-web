# 模块化 API 后端

为[网站前端](https://github.com/cloverfrog/cloverfrog.github.io)提供 API，使用 FastAPI，Python 3.10+。静态页面由网站项目托管；后端目录可改名。

## 目录与边界

```text
main.py       # 应用入口、公共中间件、模块路由组装
config.py     # 环境配置加载
auth/         # 公共认证服务
modules/      # 独立业务模块，各自维护 README
tests/        # 后端测试
```

业务模块使用公共认证，不互相依赖。公共配置与启动方式维护在本文；认证协议、模块接口和专属配置在各自目录说明。

- [公共认证](auth/README.md)
- [Scratchpad](modules/scratchpad/README.md)
- [TinyTV](modules/tinytv/README.md)

## 安装与运行

在本项目根目录创建虚拟环境并激活：

```bash
python -m venv .venv
source .venv/bin/activate # PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

将 `.env.example` 复制为 `.env`（PowerShell：`Copy-Item .env.example .env`；Linux/macOS：`cp .env.example .env`）。环境变量优先于 `.env`，文件按项目位置读取，不依赖启动时的工作目录。

| 公共配置 | 用途 |
| --- | --- |
| `POCKETBASE_URL` | PocketBase 地址，默认 `https://pocketbase.cloverfrog.xyz`；同服务器可使用 `http://127.0.0.1:8090` |
| `PUBLIC_ORIGIN` | 浏览器访问的网站来源，不含路径；本地示例 `http://127.0.0.1:8080` |
| `DEV_MODE` | 本地 HTTP 为 true，正式 HTTPS 为 false |

模块专属配置见模块 README，仍统一通过项目 `.env` 加载。启动：

```bash
uvicorn main:app --host 127.0.0.1 --port 8765
```

本地开发可加 `--reload`，静态页面和 API 的同源代理配置见[网站联调说明](https://github.com/cloverfrog/cloverfrog.github.io#本地联调)。当前先使用单 worker；存在进程内计数的限制，多 worker 时不会合并计算。

## 部署与验证

正式运行设置 `DEV_MODE=false`、`PUBLIC_ORIGIN` 为实际 HTTPS 网站来源，由反向代理转发 `/api/*` 到本服务。后端代码、内部数据和 `.env` 放在静态网站目录外，代码更新不要覆盖服务器 `.env`。接口变更时前后端配套发布。

在项目根目录运行全部测试：

```bash
python -m unittest discover -s tests -v
```

测试模拟外部服务，不需要真实凭据。各服务的测试范围、配置和真实联调步骤见对应 README。
