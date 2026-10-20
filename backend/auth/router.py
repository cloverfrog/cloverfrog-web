# 公共登录接口：校验凭据、查询会话和退出；Cookie 的写入与清除由应用中间件统一执行。
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, SecretStr

from .service import check_origin, pocketbase_auth, require_user

router = APIRouter(prefix='/api/auth', tags=['auth'])


# 限制输入长度，密码使用 SecretStr，避免在对象展示时直接泄露。
class Login(BaseModel):
    identity: str = Field(min_length=1, max_length=254)
    password: SecretStr = Field(min_length=1, max_length=512)


# 登录前检查来源和尝试频率；成功后仅向前端返回用户信息。
@router.post('/login', dependencies=[Depends(check_origin)])
async def login(body: Login, request: Request):
    request.app.state.login_limiter.check(request.client.host if request.client else 'unknown')
    identity = await pocketbase_auth(
        request,
        'auth-with-password',
        credentials={
            'identity': body.identity.strip(),
            'password': body.password.get_secret_value(),
        },
    )
    return {'authenticated': True, 'user': identity.user}


# 未登录是正常会话状态；只有认证服务故障等其他错误才继续向上返回。
@router.get('/session')
async def session(request: Request):
    try:
        identity = await require_user(request)
        return {'authenticated': True, 'user': identity.user}
    except HTTPException as error:
        if error.status_code != 401:
            raise
        request.state.clear_auth = True
        return {'authenticated': False}


# 标记本次响应需要删除本站 Cookie；不在本服务中维护另一个可撤销的会话记录。
@router.post('/logout', dependencies=[Depends(check_origin)])
async def logout(request: Request):
    request.state.clear_auth = True
    return {'authenticated': False}
