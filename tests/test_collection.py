"""Public framework fixtures only; all identities, schemas and media are simulated."""
import copy
import unittest

import httpx
from fastapi.testclient import TestClient

from config import Settings
from main import create_app
from tests.test_api import token
from modules.collection.configuration import resource_url
from modules.collection.router import MAX_IMAGE_BYTES


def listing(items, page=1, total=1):
    return {'page': page, 'totalPages': 1, 'totalItems': total, 'items': items}


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.auth_status = 200
        self.type_status = 200
        self.record_status = 200
        self.image_status = 200
        self.image_type = 'image/png'
        self.image = b'\x89PNG\r\n\x1a\nfixture'
        self.media_response = None
        self.record_id = 'abcdefghijklmn0'
        self.type_id = 'abcdefghijklmn1'
        self.empty_types = False
        self.type_record = {
            'id': self.type_id, 'key': 'example', 'name': 'Example',
            'allowed_users': ['private-user'],
            'media_gateway': 'http://media.example/internal/',
            'display': {
                'title_field': 'caption', 'identifier_field': 'source_code',
                'properties': [{'field': 'score', 'label': 'Score', 'format': 'number'},
                               {'field': 'labels', 'label': 'Labels', 'format': 'tags'}],
                'cover': 'artwork', 'resources': {'artwork': {'field': 'image_path'}},
            },
        }
        self.item = {'id': self.record_id, 'caption': '<script>text</script>', 'source_code': '001',
                     'score': 0, 'labels': ['one', 'two'], 'image_path': 'folder/图 片.png',
                     'private_notes': 'not-for-cards'}

        async def upstream(request):
            self.requests.append(request)
            path = request.url.path
            if path.endswith(('auth-refresh', 'auth-with-password')):
                return httpx.Response(self.auth_status, json={'token': token(marker='refreshed'),
                    'record': {'id': 'user1', 'collectionName': 'users'}})
            if request.url.host == 'media.example':
                self.media_response = httpx.Response(self.image_status, content=self.image,
                    headers={'Content-Type': self.image_type, 'Location': 'http://other.example/secret'})
                return self.media_response
            if path.endswith('collection_types/records'):
                # Simulates List Rules independently of View Rules.
                return httpx.Response(200, json=listing([] if self.empty_types else [self.type_record]))
            if path.endswith('collection_types/records/' + self.type_id):
                return httpx.Response(self.type_status, json=self.type_record)
            if path.endswith('/records/' + self.record_id):
                return httpx.Response(self.record_status, json=self.item)
            if path.endswith('/records'):
                return httpx.Response(self.record_status, json=listing([self.item],
                    page=int(request.url.params.get('page', 1))))
            raise AssertionError(str(request.url))

        context = TestClient(create_app(Settings(public_origin='http://testserver', dev_mode=True),
                                       transport=httpx.MockTransport(upstream)))
        self.client = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)

    def login(self):
        self.assertEqual(self.client.post('/api/auth/login', headers={'Origin': 'http://testserver'},
            json={'identity': 'example@example.com', 'password': 'fixture'}).status_code, 200)

    @property
    def base(self):
        return '/api/collection/types/' + self.type_record['key']

    @property
    def media(self):
        return self.base + '/items/' + self.record_id + '/resources/artwork'

    def test_all_reads_require_login_and_logout_blocks_media(self):
        paths = ['/api/collection/types', self.base, self.base + '/items', self.media]
        for path in paths:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.headers['cache-control'], 'private, no-store')
        self.assertEqual(self.requests, [])
        self.login()
        self.assertEqual(self.client.get(self.media).status_code, 200)
        self.client.post('/api/auth/logout', headers={'Origin': 'http://testserver'})
        self.requests.clear()
        for path in paths:
            self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.requests, [])

    def test_type_and_card_projection_and_pagination(self):
        self.login()
        types = self.client.get('/api/collection/types').json()
        self.assertEqual(types['items'], [{'key': 'example', 'name': 'Example'}])
        detail = self.client.get(self.base)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()['properties'][0]['label'], 'Score')
        response = self.client.get(self.base + '/items?page=2&filter=secret&expand=owner&sort=-caption')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['page'], 2)
        self.assertEqual(data['items'][0]['title'], '<script>text</script>')
        self.assertEqual(data['items'][0]['identifier'], '001')
        self.assertEqual(data['items'][0]['properties'], [0, ['one', 'two']])
        self.assertEqual(data['items'][0]['cover'], self.media)
        for secret in ('image_path', 'media.example', 'private-user', 'private_notes', '图 片'):
            self.assertNotIn(secret, response.text + detail.text)
        upstream = self.requests[-1]
        self.assertEqual(upstream.url.params['perPage'], '24')
        self.assertEqual(upstream.url.params['sort'], 'id')
        self.assertEqual(upstream.url.path, '/api/collections/example/records')
        self.assertNotIn('filter', upstream.url.params)
        self.assertNotIn('expand', upstream.url.params)
        self.assertEqual(upstream.headers['Authorization'], token(marker='refreshed'))
        self.assertNotIn('cookie', upstream.headers)

    def test_other_schema_and_gateway_need_no_code_changes(self):
        self.login()
        self.type_record['key'] = 'different_records'
        self.type_record['display'] = {
            'title_field': 'heading', 'identifier_field': 'external_key',
            'properties': [{'field': 'complete', 'label': 'Done', 'format': 'boolean'}],
            'resources': {},
        }
        self.item = {'id': self.record_id, 'heading': 'Other', 'external_key': '02', 'complete': False}
        response = self.client.get(self.base + '/items')
        self.assertEqual(response.status_code, 200)
        item = response.json()['items'][0]
        self.assertEqual(item['title'], 'Other')
        self.assertEqual(item['properties'], [False])
        self.assertIsNone(item['cover'])
        self.assertIn('/different_records/', self.requests[-1].url.path)
        self.type_record['display'] = {
            'title_field': 'heading', 'identifier_field': 'external_key',
            'resources': {'artwork': {'field': 'asset'}}, 'cover': 'artwork'}
        self.item['asset'] = 'another.png'
        self.type_record['media_gateway'] = 'http://media.example/another-base'
        self.assertEqual(self.client.get(self.media).status_code, 200)
        self.assertEqual(self.requests[-1].url.path, '/another-base/another.png')

    def test_list_and_view_rules_are_both_enforced(self):
        self.login()
        self.empty_types = True
        self.assertEqual(self.client.get('/api/collection/types').json()['items'], [])
        self.assertEqual(self.client.get(self.base).status_code, 404)
        self.empty_types = False
        self.type_status = 404
        count = len(self.requests)
        self.assertEqual(self.client.get(self.media).status_code, 404)
        self.assertEqual(len(self.requests) - count, 3)  # auth, type list, type view
        self.type_status = 200
        self.record_status = 404
        self.assertEqual(self.client.get(self.media).status_code, 404)
        self.assertFalse(any(r.url.host == 'media.example' for r in self.requests))

    def test_media_uses_gateway_and_never_forwards_credentials(self):
        self.login()
        self.client.app.state.http.cookies.set('upstream-private', 'secret')
        response = self.client.get(self.media)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, self.image)
        self.assertEqual(response.headers['cache-control'], 'private, no-store')
        self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
        upstream = self.requests[-1]
        record_request = self.requests[-2]
        self.assertEqual(record_request.url.path, '/api/collections/example/records/' + self.record_id)
        self.assertEqual(upstream.url.path, '/internal/folder/图 片.png')
        self.assertNotIn('Authorization', upstream.headers)
        self.assertNotIn('cookie', upstream.headers)
        self.assertTrue(self.media_response.is_closed)

    def test_config_errors_and_missing_resource(self):
        self.login()
        original = copy.deepcopy(self.type_record)
        for invalid in ({}, {'title_field': 'x.y', 'identifier_field': 'code'},
                        {'title_field': 'image_path', 'identifier_field': 'code',
                         'resources': {'artwork': {'field': 'image_path'}}}):
            with self.subTest(invalid=invalid):
                self.type_record['display'] = invalid
                self.assertEqual(self.client.get(self.base + '/items').status_code, 503)
        self.type_record = original
        self.item.pop('image_path')
        self.assertIsNone(self.client.get(self.base + '/items').json()['items'][0]['cover'])
        self.assertEqual(self.client.get(self.media).status_code, 404)

    def test_media_limits_type_redirect_and_cleanup(self):
        self.login()
        for status, kind, body in [(302, 'image/png', self.image), (500, 'image/png', self.image),
                                   (200, 'image/svg+xml', b'<svg/>'), (200, 'image/png', b'html'),
                                   (200, 'image/png', b'x' * (MAX_IMAGE_BYTES + 1))]:
            with self.subTest(status=status, kind=kind, size=len(body)):
                self.image_status, self.image_type, self.image = status, kind, body
                response = self.client.get(self.media)
                self.assertEqual(response.status_code, 503)
                self.assertTrue(self.media_response.is_closed)
        self.assertFalse(any(r.url.host == 'other.example' for r in self.requests))

    def test_invalid_routes_readonly_expiry_and_outage(self):
        self.login()
        for path in (self.base + '/items?page=0', self.base + '/items?page=100001'):
            self.assertEqual(self.client.get(path).status_code, 422)
        for path in ('/api/collection/types/bad%22key', self.base + '/items/bad/resources/artwork',
                     self.media.replace('artwork', 'unknown')):
            self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.post(self.base + '/items', json={}).status_code, 405)
        self.record_status = 503
        self.assertEqual(self.client.get(self.base + '/items').status_code, 503)
        self.auth_status = 503
        response = self.client.get(self.base)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('Max-Age=0', response.headers.get('set-cookie', ''))
        self.auth_status = 401
        response = self.client.get(self.media)
        self.assertEqual(response.status_code, 401)
        self.assertIn('Max-Age=0', response.headers['set-cookie'])

    def test_resource_paths_cannot_escape_gateway(self):
        from fastapi import HTTPException
        for path in ('../secret', '/secret', '//other.example/a', 'x/../secret', 'x\\secret',
                     'x%2fsecret', 'x?query=1', 'x#fragment', 'http://other.example/a', 'x\x00'):
            with self.subTest(path=path), self.assertRaises(HTTPException):
                resource_url('http://media.example/base', path)
        self.assertEqual(resource_url('http://media.example/base', 'x/图 片.png'),
                         'http://media.example/base/x/%E5%9B%BE%20%E7%89%87.png')
