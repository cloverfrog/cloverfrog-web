# 登录验证后的频道接口直接返回时间线和 AList 下载地址。
from urllib.parse import quote, urlencode
import asyncio
import logging
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from auth.service import require_user
from .timeline import read_json, timeline

router = APIRouter(prefix='/api/tinytv', tags=['tinytv'], dependencies=[Depends(require_user)])
logger = logging.getLogger(__name__)


class PlaybackURL:
    """只保存当前轮次的当前文件；锁避免多个观众同时重复获取签名。"""

    def __init__(self):
        self.lock = asyncio.Lock()
        self.key = None
        self.url = None

    async def get(self, client, settings, program, source):
        path = settings.alist_root.rstrip('/') + '/' + source.lstrip('/')
        url = settings.alist_url.rstrip('/') + '/d' + quote(path, safe='/')
        if not settings.alist_token:
            return url
        key = (program['programStart'], program['partIndex'], path)
        async with self.lock:
            if self.key == key:
                return self.url
            stage = 'HTTP request'
            try:
                response = await client.post(
                    settings.alist_url.rstrip('/') + '/api/fs/get',
                    json={'path': path},
                    headers={'Authorization': settings.alist_token},
                )
                stage = f'HTTP status {response.status_code}'
                response.raise_for_status()
                stage = 'JSON response'
                payload = response.json()
                stage = 'business status'
                if not isinstance(payload, dict) or payload.get('code') != 200:
                    raise ValueError('Invalid AList business status')
                data = payload.get('data')
                stage = 'sign field'
                if not isinstance(data, dict) or not isinstance(data.get('sign'), str):
                    raise ValueError('Invalid AList file metadata')
            except (httpx.HTTPError, ValueError) as error:
                # 不记录异常正文、上游响应或请求头，避免凭据及私有地址进入日志。
                logger.error('TinyTV AList metadata request failed at %s (%s)', stage, type(error).__name__)
                raise HTTPException(502, 'Playback URL unavailable') from None
            if data['sign']:
                url += '?' + urlencode({'sign': data['sign']})
            self.key, self.url = key, url
            return url


# 每次按当前配置文件和服务器时间计算节目；数据错误保留服务端堆栈，对外只返回通用说明。
def current_program():
    try:
        return timeline(
            read_json('schedule.json'),
            read_json('sources.json'),
            time.time(),
            media=read_json('media.json'),
        )
    except (OSError, ValueError, KeyError, TypeError):
        logger.exception('Failed to calculate current program for TinyTV channel tiny')
        raise HTTPException(500, 'Channel unavailable') from None


# 登录后按当前文件获取 AList 下载地址，下载重定向和媒体传输由浏览器处理。
@router.get('/channels/tiny/now')
async def now(request: Request):
    result = current_program()
    source = result.pop('path', None)
    if source:
        settings = request.app.state.settings
        if not hasattr(request.app.state, 'tinytv_playback_url'):
            request.app.state.tinytv_playback_url = PlaybackURL()
        result['playUrl'] = await request.app.state.tinytv_playback_url.get(
            request.app.state.http, settings, result, source,
        )
    return result
