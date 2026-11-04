"""PocketBase rules authorize each read; no local account policy or admin token."""
import re

import httpx
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from auth.service import Identity, require_user
from .configuration import KEY, configuration, display_value, resource_url
from .errors import fail

router = APIRouter(prefix='/api/collection', tags=['collection'])
RECORD_ID = re.compile(r'[a-z0-9]{15}')
MAX_IMAGE_BYTES = 10 * 1024 * 1024


async def pb_get(request, identity, path, *, stage, **params):
    try:
        response = await request.app.state.http.get(
            request.app.state.settings.pocketbase_url + '/api/collections/' + path,
            headers={'Authorization': identity.token}, params=params,
        )
    except httpx.HTTPError as error:
        fail(request, 503, 'storage_unreachable', '无法连接 PocketBase，请检查后端到数据库的连接。',
             stage=stage, target=path, reason=type(error).__name__)
    if response.status_code != 200:
        status = response.status_code if response.status_code in (401, 403, 404, 429) else 503
        messages = {
            'type_list': '收藏类型目录读取失败，请检查 collection_types 表及其 List Rule。',
            'type_lookup': '类型注册查询失败，请检查 collection_types 表及其 List Rule。',
            'type_view': '类型配置读取失败，记录可能不存在或被 View Rule 拒绝。',
            'item_list': '条目列表读取失败，请检查业务表名是否与 key 一致，以及该表的 List Rule。',
            'item_view': '资源所属记录读取失败，记录可能不存在或被业务表的 View Rule 拒绝。',
        }
        fail(request, status, stage + '_failed', messages[stage], stage=stage,
             target=path, upstream_status=response.status_code)
    try:
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except ValueError:
        fail(request, 503, 'storage_response_invalid', 'PocketBase 返回了无效的 JSON 数据。',
             stage=stage, target=path)


def page_result(data, request, stage):
    try:
        if not isinstance(data['items'], list) or not all(isinstance(v, dict) for v in data['items']):
            raise ValueError()
        for field in ('page', 'totalPages', 'totalItems'):
            if type(data[field]) is not int or data[field] < 0:
                raise ValueError()
        return {field: data[field] for field in ('page', 'totalPages', 'totalItems')}
    except (KeyError, ValueError, TypeError):
        fail(request, 503, 'storage_page_invalid', 'PocketBase 分页响应缺少有效的 items 或分页信息。', stage=stage)


def type_summary(record, request):
    try:
        key, name = record['key'], record['name']
        if not isinstance(key, str) or not KEY.fullmatch(key) or not isinstance(name, str) or not name:
            raise ValueError()
        return {'key': key, 'name': name}
    except (KeyError, ValueError, TypeError):
        fail(request, 503, 'type_summary_invalid', '类型注册记录缺少有效的 key 或 name。', stage='type_config')


async def read_type(request, identity, key):
    if not KEY.fullmatch(key):
        fail(request, 404, 'type_key_invalid', '类型代号格式无效，请从收藏类型目录进入。', stage='type_lookup')
    result = await pb_get(request, identity, 'collection_types/records',
                          stage='type_lookup', filter=f'key = "{key}"', perPage=1, page=1)
    page_result(result, request, 'type_lookup')
    if not result['items']:
        fail(request, 404, 'type_not_visible',
             '找不到可见的类型注册，请检查 key、allowed_users 和 collection_types 的 List Rule。', stage='type_lookup')
    record_id = result['items'][0].get('id', '')
    if not isinstance(record_id, str) or not RECORD_ID.fullmatch(record_id):
        fail(request, 503, 'type_id_invalid', '类型注册记录的 PocketBase 内部 ID 无效。', stage='type_lookup')
    # List and View rules may differ. Both must allow this type before its data is read.
    record = await pb_get(request, identity, f'collection_types/records/{record_id}', stage='type_view')
    if type_summary(record, request)['key'] != key:
        fail(request, 503, 'type_key_mismatch', '类型记录返回的 key 与请求不一致。', stage='type_view')
    return record


@router.get('/types')
async def types(request: Request, page: int = Query(1, ge=1, le=100000),
                identity: Identity = Depends(require_user)):
    result = await pb_get(request, identity, 'collection_types/records',
                          stage='type_list', page=page, perPage=24, sort='key', fields='id,key,name')
    return {**page_result(result, request, 'type_list'),
            'items': [type_summary(item, request) for item in result['items']]}


@router.get('/types/{key}')
async def detail(key: str, request: Request, identity: Identity = Depends(require_user)):
    record = await read_type(request, identity, key)
    display = configuration(record, request)
    return {**type_summary(record, request),
            'properties': [{'label': prop.label, 'format': prop.format} for prop in display.properties]}


@router.get('/types/{key}/items')
async def items(key: str, request: Request, page: int = Query(1, ge=1, le=100000),
                identity: Identity = Depends(require_user)):
    record = await read_type(request, identity, key)
    display = configuration(record, request)
    fields = {'id', display.title_field, display.identifier_field}
    fields.update(prop.field for prop in display.properties)
    # Request resource presence, but never expose the underlying reference to the browser.
    fields.update(resource.field for resource in display.resources.values())
    result = await pb_get(request, identity, f'{key}/records', stage='item_list', page=page,
                          perPage=24, sort='id', fields=','.join(sorted(fields)))
    metadata = page_result(result, request, 'item_list')
    cards = []
    for item in result['items']:
        record_id = item.get('id', '')
        if not isinstance(record_id, str) or not RECORD_ID.fullmatch(record_id):
            fail(request, 503, 'item_id_invalid', '条目的 PocketBase 内部 ID 无效。', stage='item_list')
        resources = {
            slot: f'/api/collection/types/{key}/items/{record_id}/resources/{slot}'
            for slot, resource in display.resources.items() if item.get(resource.field)
        }
        cards.append({
            'id': record_id,
            'title': display_value(item.get(display.title_field)),
            'identifier': display_value(item.get(display.identifier_field)),
            'properties': [display_value(item.get(prop.field), prop.format) for prop in display.properties],
            'cover': resources.get(display.cover),
        })
    return {**metadata, 'items': cards}


@router.get('/types/{key}/items/{record_id}/resources/{slot}')
async def resource(key: str, record_id: str, slot: str, request: Request,
                   identity: Identity = Depends(require_user)):
    if not RECORD_ID.fullmatch(record_id) or not KEY.fullmatch(slot):
        fail(request, 404, 'resource_locator_invalid', '资源记录 ID 或槽位格式无效。', stage='resource_lookup')
    record = await read_type(request, identity, key)
    display = configuration(record, request)
    if slot not in display.resources:
        fail(request, 404, 'resource_slot_missing', '展示配置未声明请求的资源槽位。', stage='resource_lookup')
    field = display.resources[slot].field
    item = await pb_get(request, identity, f'{key}/records/{record_id}', stage='item_view', fields=f'id,{field}')
    if not item.get(field):
        fail(request, 404, 'resource_path_missing', '记录中没有可读的资源路径，请检查槽位字段映射和字段值。',
             stage='resource_lookup')
    url = resource_url(record.get('media_gateway'), item[field], request)
    # Use a fresh Request to avoid sending the shared client's cookies or PB credentials.
    upstream = httpx.Request('GET', url, headers={'Accept': 'image/jpeg,image/png,image/webp'},
                             extensions={'timeout': httpx.Timeout(20, connect=5).as_dict()})
    try:
        response = await request.app.state.http.send(upstream, stream=True, follow_redirects=False)
        try:
            if response.status_code != 200:
                fail(request, 404 if response.status_code == 404 else 503, 'media_http_error',
                     '媒体网关返回错误，请检查网关基础地址与记录相对路径的拼接结果。',
                     stage='media_fetch', target=url, upstream_status=response.status_code)
            content_type = response.headers.get('content-type', '').split(';')[0].strip().lower()
            if content_type not in ('image/jpeg', 'image/png', 'image/webp'):
                fail(request, 503, 'media_type_unsupported', '媒体响应不是支持的 JPEG、PNG 或 WebP 图片。',
                     stage='media_fetch', target=url, reason=content_type)
            body = bytearray()
            async for chunk in response.aiter_bytes():
                if len(body) + len(chunk) > MAX_IMAGE_BYTES:
                    fail(request, 503, 'media_too_large', '图片超过 10 MiB 读取上限。', stage='media_fetch', target=url)
                body.extend(chunk)
            valid = (content_type == 'image/jpeg' and body.startswith(b'\xff\xd8\xff')
                     or content_type == 'image/png' and body.startswith(b'\x89PNG\r\n\x1a\n')
                     or content_type == 'image/webp' and body[:4] == b'RIFF' and body[8:12] == b'WEBP')
            if not valid:
                fail(request, 503, 'media_image_invalid', '媒体响应的图片文件头与声明类型不符。', stage='media_fetch', target=url)
            return Response(bytes(body), media_type=content_type)
        finally:
            await response.aclose()
    except httpx.HTTPError as error:
        fail(request, 503, 'media_unreachable', '无法读取媒体网关，请检查网络连通性与超时。',
             stage='media_fetch', target=url, reason=type(error).__name__)
