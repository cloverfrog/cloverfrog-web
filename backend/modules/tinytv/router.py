# 登录验证后的频道接口直接返回时间线和 AList 下载地址。
from urllib.parse import quote
import time

from fastapi import APIRouter, Depends, HTTPException, Request

from auth.service import require_user
from .timeline import read_json, timeline

router = APIRouter(prefix='/api/tinytv', tags=['tinytv'], dependencies=[Depends(require_user)])


# 每次按当前配置文件和服务器时间计算节目，配置缺失或无效时对外统一表示频道不可用。
def current_program():
    try:
        return timeline(read_json('schedule.json'), read_json('sources.json'), time.time())
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(503, 'Channel unavailable') from None


# 登录后直接返回 AList 下载地址，下载重定向和媒体传输由浏览器处理。
@router.get('/channels/tiny/now')
async def now(request: Request):
    result = current_program()
    source = result.pop('path', None)
    if source:
        settings = request.app.state.settings
        path = settings.alist_root.rstrip('/') + '/' + source.lstrip('/')
        result['playUrl'] = settings.alist_url.rstrip('/') + '/d' + quote(path, safe='/')
    return result
