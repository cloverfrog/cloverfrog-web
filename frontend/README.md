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

