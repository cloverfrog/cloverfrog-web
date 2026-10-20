# 公共认证的权限边界：本站 Cookie 提供 token，PocketBase 每次验证并续期；本服务不另建密码库或会话库。
"""PocketBase is the only authority; no local password or session store."""
import base64
import json
import time
from dataclasses import dataclass

import httpx
from fastapi import HTTPException, Request

COOKIE_NAME = 'site_auth'


# 一次请求内传递认证结果；token 仅供后端访问 PocketBase，不放入返回前端的 user 对象。
@dataclass
class Identity:
    token: str
    expires: int
    user: dict


# 登录和续期都交给 PocketBase 验证，只有成功的结果才写入请求状态。
async def pocketbase_auth(request: Request, method: str, *, credentials=None, token=None):
    settings = request.app.state.settings
    headers = {'Authorization': token} if token else {}
    try:
        response = await request.app.state.http.post(
            f'{settings.pocketbase_url}/api/collections/users/{method}',
            json=credentials or {}, headers=headers,
        )
    except httpx.HTTPError:
        raise HTTPException(503, 'Authentication service unavailable') from None
    if response.status_code == 429:
        raise HTTPException(429, 'Too many login attempts')
    denied = (400, 401, 403) if credentials is not None else (401, 403, 404)
    if response.status_code in denied:
        raise HTTPException(401, 'Authentication required')
    if response.status_code != 200:
        raise HTTPException(503, 'Authentication service unavailable')
    try:
        data = response.json()
        record = data['record']
        if record['collectionName'] != 'users' or not record['id']:
            raise ValueError()
        new_token = data['token']
        # 这里只读取已由 PocketBase 验证的 token 的过期时间，供 Cookie 设置有效期。
        payload = new_token.split('.')[1]
        expires = int(
            json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))['exp']
        )
        if expires <= time.time():
            raise ValueError()
        identity = Identity(
            new_token,
            expires,
            {'id': record['id'], 'email': record.get('email', '')},
        )
    except (ValueError, KeyError, TypeError, IndexError, AttributeError):
        raise HTTPException(503, 'Invalid authentication service response') from None
    # 中间件读取此状态设置续期 Cookie；业务接口只拿经过验证的最小用户信息。
    request.state.identity = identity
    return identity


# 受保护路由的依赖：不能只根据 Cookie 是否存在判断登录，必须向认证源重新验证。
async def require_user(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, 'Authentication required')
    return await pocketbase_auth(request, 'auth-refresh', token=token)


# Cookie 会被浏览器自动携带，写操作校验来源以防其他站点借用当前登录态发起请求。
# 只接受配置的站点来源，并拒绝浏览器明确标记的跨站请求。
def check_origin(request: Request):
    if (
        request.headers.get('origin') != request.app.state.settings.public_origin
        or request.headers.get('sec-fetch-site') == 'cross-site'
    ):
        raise HTTPException(403, 'Origin denied')


# 进程内按 IP 记录固定十五分钟窗口，成功或失败的登录尝试都会计数。
class LoginLimiter:
    def __init__(self):
        self.attempts = {}

    # 记录尝试而非失败次数；清除到期窗口，避免持续保存不再访问的 IP。
    def check(self, ip):
        now = time.monotonic()
        self.attempts = {key: value for key, value in self.attempts.items() if value[1] > now}
        count, until = self.attempts.get(ip, (0, now + 900))
        if count >= 5:
            raise HTTPException(429, 'Too many login attempts')
        self.attempts[ip] = count + 1, until
