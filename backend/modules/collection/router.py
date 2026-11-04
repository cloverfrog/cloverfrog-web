"""PocketBase rules authorize each read; no local account policy or admin token."""
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from auth.service import Identity, require_user
from .configuration import KEY, configuration, display_value, resource_url

router = APIRouter(prefix='/api/collection', tags=['collection'])
RECORD_ID = re.compile(r'[a-z0-9]{15}')
MAX_IMAGE_BYTES = 10 * 1024 * 1024


async def pb_get(request, identity, path, **params):
    try:
        response = await request.app.state.http.get(
            request.app.state.settings.pocketbase_url + '/api/collections/' + path,
            headers={'Authorization': identity.token}, params=params,
        )
    except httpx.HTTPError:
        raise HTTPException(503, 'Storage service unavailable') from None
    if response.status_code != 200:
        status = response.status_code if response.status_code in (401, 403, 404, 429) else 503
        raise HTTPException(status, 'Storage request failed')
    try:
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except ValueError:
        raise HTTPException(503, 'Invalid storage response') from None


def page_result(data):
    try:
        if not isinstance(data['items'], list) or not all(isinstance(v, dict) for v in data['items']):
            raise ValueError()
        for field in ('page', 'totalPages', 'totalItems'):
            if type(data[field]) is not int or data[field] < 0:
                raise ValueError()
        return {field: data[field] for field in ('page', 'totalPages', 'totalItems')}
    except (KeyError, ValueError, TypeError):
        raise HTTPException(503, 'Invalid storage response') from None


def type_summary(record):
    try:
        key, name = record['key'], record['name']
        if not isinstance(key, str) or not KEY.fullmatch(key) or not isinstance(name, str) or not name:
            raise ValueError()
        return {'key': key, 'name': name}
    except (KeyError, ValueError, TypeError):
        raise HTTPException(503, 'Invalid collection configuration') from None


async def read_type(request, identity, key):
    if not KEY.fullmatch(key):
        raise HTTPException(404, 'Not found')
    result = await pb_get(request, identity, 'collection_types/records',
                          filter=f'key = "{key}"', perPage=1, page=1)
    page_result(result)
    if not result['items']:
        raise HTTPException(404, 'Not found')
    record_id = result['items'][0].get('id', '')
    if not isinstance(record_id, str) or not RECORD_ID.fullmatch(record_id):
        raise HTTPException(503, 'Invalid storage response')
    # List and View rules may differ. Both must allow this type before its data is read.
    record = await pb_get(request, identity, f'collection_types/records/{record_id}')
    if type_summary(record)['key'] != key:
        raise HTTPException(503, 'Invalid storage response')
    return record


@router.get('/types')
async def types(request: Request, page: int = Query(1, ge=1, le=100000),
                identity: Identity = Depends(require_user)):
    result = await pb_get(request, identity, 'collection_types/records',
                          page=page, perPage=24, sort='key', fields='id,key,name')
    return {**page_result(result), 'items': [type_summary(item) for item in result['items']]}


@router.get('/types/{key}')
async def detail(key: str, request: Request, identity: Identity = Depends(require_user)):
    record = await read_type(request, identity, key)
    display = configuration(record)
    return {**type_summary(record),
            'properties': [{'label': prop.label, 'format': prop.format} for prop in display.properties]}


@router.get('/types/{key}/items')
async def items(key: str, request: Request, page: int = Query(1, ge=1, le=100000),
                identity: Identity = Depends(require_user)):
    record = await read_type(request, identity, key)
    display = configuration(record)
    fields = {'id', display.title_field, display.identifier_field}
    fields.update(prop.field for prop in display.properties)
    # Request resource presence, but never expose the underlying reference to the browser.
    fields.update(resource.field for resource in display.resources.values())
    result = await pb_get(request, identity, f'{key}/records', page=page,
                          perPage=24, sort='id', fields=','.join(sorted(fields)))
    metadata = page_result(result)
    cards = []
    for item in result['items']:
        record_id = item.get('id', '')
        if not isinstance(record_id, str) or not RECORD_ID.fullmatch(record_id):
            raise HTTPException(503, 'Invalid storage response')
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
        raise HTTPException(404, 'Not found')
    record = await read_type(request, identity, key)
    display = configuration(record)
    if slot not in display.resources:
        raise HTTPException(404, 'Not found')
    field = display.resources[slot].field
    item = await pb_get(request, identity, f'{key}/records/{record_id}', fields=f'id,{field}')
    if not item.get(field):
        raise HTTPException(404, 'Not found')
    url = resource_url(record.get('media_gateway'), item[field])
    # Use a fresh Request to avoid sending the shared client's cookies or PB credentials.
    upstream = httpx.Request('GET', url, headers={'Accept': 'image/jpeg,image/png,image/webp'},
                             extensions={'timeout': httpx.Timeout(20, connect=5).as_dict()})
    try:
        response = await request.app.state.http.send(upstream, stream=True, follow_redirects=False)
        try:
            if response.status_code != 200:
                raise HTTPException(404 if response.status_code == 404 else 503, 'Resource unavailable')
            content_type = response.headers.get('content-type', '').split(';')[0].strip().lower()
            if content_type not in ('image/jpeg', 'image/png', 'image/webp'):
                raise HTTPException(503, 'Unsupported resource type')
            body = bytearray()
            async for chunk in response.aiter_bytes():
                if len(body) + len(chunk) > MAX_IMAGE_BYTES:
                    raise HTTPException(503, 'Resource too large')
                body.extend(chunk)
            valid = (content_type == 'image/jpeg' and body.startswith(b'\xff\xd8\xff')
                     or content_type == 'image/png' and body.startswith(b'\x89PNG\r\n\x1a\n')
                     or content_type == 'image/webp' and body[:4] == b'RIFF' and body[8:12] == b'WEBP')
            if not valid:
                raise HTTPException(503, 'Invalid image response')
            return Response(bytes(body), media_type=content_type)
        finally:
            await response.aclose()
    except httpx.HTTPError:
        raise HTTPException(503, 'Resource service unavailable') from None
