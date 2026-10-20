"""API-only application. Run: uvicorn main:app --host 127.0.0.1 --port 8765."""
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from auth.router import router as auth_router
from auth.service import COOKIE_NAME, LoginLimiter
from config import Settings
from modules.tinytv.router import router as tinytv_router
from modules.scratchpad.router import router as scratchpad_router


# 应用入口集中组装公共认证与各业务路由，HTTP 客户端随应用生命周期复用和关闭。
def create_app(settings=None, *, transport=None):
    settings = settings or Settings.load()

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(30, connect=10),
            follow_redirects=False,
            headers={'User-Agent': 'TinyTV/1.0'},
        ) as client:
            app.state.http = client
            yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.login_limiter = LoginLimiter()

    # 认证响应统一禁用缓存，并在业务处理完成后落 Cookie，避免各路由自行管理登录态。
    @app.middleware('http')
    async def auth_cookie(request: Request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        # 路由只记录认证结果；统一在响应阶段刷新或清除浏览器 Cookie。
        if getattr(request.state, 'clear_auth', False) or response.status_code == 401:
            response.delete_cookie(
                COOKIE_NAME,
                path='/api/',
                httponly=True,
                secure=not settings.dev_mode,
                samesite='strict',
            )
        elif identity := getattr(request.state, 'identity', None):
            response.set_cookie(
                COOKIE_NAME,
                identity.token,
                path='/api/',
                httponly=True,
                secure=not settings.dev_mode,
                samesite='strict',
                max_age=max(0, int(identity.expires - time.time())),
            )
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        # 参数校验错误只返回通用说明，避免框架默认错误详情回显用户提交的密码或 token。
        return JSONResponse({'detail': 'Invalid request'}, status_code=422)

    # 应用入口负责组装模块，认证公共服务不需要知道有哪些业务使用它。
    app.include_router(auth_router)
    app.include_router(tinytv_router)
    app.include_router(scratchpad_router)
    return app


app = create_app()
