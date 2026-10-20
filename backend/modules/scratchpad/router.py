# 草稿与文件中转的存储代理：前端只访问本站；后端限定集合、操作和请求大小，PocketBase 判定记录权限。
"""Narrow PocketBase adapter using the site's existing user cookie."""
import re
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from starlette.background import BackgroundTask

from auth.service import Identity, check_origin, require_user

router = APIRouter(prefix='/api/scratchpad', tags=['scratchpad'])
COLLECTIONS = {'scratchpads', 'scratchpad_files'}
MAX_BODY = 51 * 1024 * 1024  # 50 MB 文件之外，为 multipart 字段与边界预留 1 MB。


# 限定可代理的集合与记录 ID 格式，防止此入口变成任意 PocketBase API 的转发器。
def validate(collection, record_id=None):
    if collection not in COLLECTIONS or (
        record_id is not None and not re.fullmatch(r'[a-z0-9]{15}', record_id)
    ):
        raise HTTPException(404, 'Not found')


# 使用当前用户凭据访问存储服务，记录权限仍由 PocketBase 的规则判定。
async def send(request, method, path, identity, **kwargs):
    client = request.app.state.http
    headers = {'Authorization': identity.token, **kwargs.pop('headers', {})}
    upstream_request = client.build_request(
        method,
        request.app.state.settings.pocketbase_url + path,
        headers=headers,
        timeout=300,
        **kwargs,
    )
    try:
        response = await client.send(upstream_request, stream=True)
    except httpx.HTTPError:
        raise HTTPException(503, 'Storage service unavailable') from None
    if response.status_code >= 400 or response.is_redirect:
        status = response.status_code if response.status_code in (400, 401, 403, 404, 413, 429) else 503
        await response.aclose()
        raise HTTPException(status, 'Storage request failed')
    return response


# 读完记录操作响应再返回，并关闭上游；文件下载使用下面独立的流式分支。
async def json_response(response):
    try:
        body = await response.aread()
        return Response(body, status_code=response.status_code, media_type='application/json')
    except httpx.HTTPError:
        raise HTTPException(503, 'Storage service unavailable') from None
    finally:
        await response.aclose()


# 列表与单条记录共用校验：读操作允许分页排序，写操作还要验证来源和请求体大小。
async def records(request, collection, record_id, identity):
    validate(collection, record_id)
    method = request.method
    if method != 'GET':
        check_origin(request)
    # 文件上传后只允许读取或删除，不提供覆盖文件的 PATCH，保持一次上传对应一份记录。
    if method == 'PATCH' and collection == 'scratchpad_files':
        raise HTTPException(405, 'Method not allowed')
    # 只转发分页和排序参数，避免客户端扩展代理查询能力。
    params = [
        (key, value)
        for key, value in request.query_params.multi_items()
        if key in ('page', 'perPage', 'sort')
    ]
    headers = {}
    content = None
    if method in ('POST', 'PATCH'):
        content_type = request.headers.get('content-type', '')
        multipart = (
            method == 'POST'
            and collection == 'scratchpad_files'
            and content_type.startswith('multipart/form-data;')
        )
        if not multipart and content_type.split(';')[0] != 'application/json':
            raise HTTPException(415, 'Unsupported content type')
        limit = MAX_BODY if multipart else 2 * 1024 * 1024
        try:
            length = int(request.headers.get('content-length', '0'))
        except ValueError:
            raise HTTPException(400, 'Invalid content length') from None
        if length < 0 or length > limit:
            raise HTTPException(413, 'Request too large')

        # Content-Length 可能缺失或不可信，实际读取流时仍累计校验大小。
        async def bounded_body():
            size = 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, 'Request too large')
                yield chunk

        content = bounded_body()
        headers['Content-Type'] = content_type
        if length:
            headers['Content-Length'] = str(length)
    path = f'/api/collections/{collection}/records' + (f'/{record_id}' if record_id else '')
    response = await send(request, method, path, identity, params=params, headers=headers, content=content)
    return await json_response(response)


@router.api_route('/collections/{collection}/records', methods=['GET', 'POST'])
async def collection_records(
    collection: str, request: Request, identity: Identity = Depends(require_user)
):
    return await records(request, collection, None, identity)


@router.api_route('/collections/{collection}/records/{record_id}', methods=['GET', 'PATCH', 'DELETE'])
async def single_record(
    collection: str, record_id: str, request: Request, identity: Identity = Depends(require_user)
):
    return await records(request, collection, record_id, identity)


# 下载分三步：先验证当前用户可读记录，再申请临时文件 token，最后在后端取文件并转发。
@router.get('/files/{record_id}')
async def download(record_id: str, request: Request, identity: Identity = Depends(require_user)):
    validate('scratchpad_files', record_id)
    # 文件 token 本身不能代替记录权限校验，先用当前用户凭据确认记录可读。
    response = await send(request, 'GET', f'/api/collections/scratchpad_files/records/{record_id}', identity)
    try:
        await response.aread()
        filename = response.json()['file']
        if not isinstance(filename, str) or not filename or '/' in filename or '\\' in filename:
            raise ValueError()
    except (ValueError, KeyError, TypeError, httpx.HTTPError):
        raise HTTPException(503, 'Invalid storage response') from None
    finally:
        await response.aclose()
    # 受保护文件的短期 token 仅在后端使用，浏览器通过本站接口获取文件流。
    response = await send(request, 'POST', '/api/files/token', identity, json={})
    try:
        await response.aread()
        file_token = response.json()['token']
        if not isinstance(file_token, str) or not file_token:
            raise ValueError()
    except (ValueError, KeyError, TypeError, httpx.HTTPError):
        raise HTTPException(503, 'Invalid storage response') from None
    finally:
        await response.aclose()
    response = await send(
        request,
        'GET',
        f'/api/files/scratchpad_files/{record_id}/{quote(filename, safe="")}',
        identity,
        params={'token': file_token, 'download': '1'},
    )

    async def body():
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            await response.aclose()

    return StreamingResponse(
        body(),
        media_type='application/octet-stream',
        background=BackgroundTask(response.aclose),
    )
