# 验证草稿代理的登录复用、路由边界、请求大小和下载流程；模拟存储响应以检查本站转发行为。
import json
import unittest

import httpx
from fastapi.testclient import TestClient

from config import Settings
from main import create_app
from tests.test_api import token, VideoBytes


class ScratchpadTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.record_status = 200
        self.auth_status = 200
        self.stream = None
        self.record_id = 'abcdefghijklmn0'

        async def upstream(request):
            self.requests.append(request)
            path = request.url.path
            if path.endswith(('auth-refresh', 'auth-with-password')):
                return httpx.Response(self.auth_status, json={'token': token(marker='refreshed'), 'record': {
                    'id': 'user1', 'collectionName': 'users', 'email': 'me@example.com'}})
            if path == '/api/files/token':
                return httpx.Response(200, json={'token': 'short-file-token'})
            if path.startswith('/api/files/scratchpad_files/'):
                self.stream = VideoBytes()
                return httpx.Response(200, stream=self.stream)
            if self.record_status != 200:
                return httpx.Response(self.record_status, json={'message': 'private upstream error'})
            if request.method == 'DELETE':
                return httpx.Response(204)
            if request.method in ('POST', 'PATCH'):
                return httpx.Response(200, json={'id': self.record_id})
            if path.endswith(self.record_id):
                return httpx.Response(200, json={'id': self.record_id, 'owner': 'user1', 'file': 'hello 世界.txt'})
            return httpx.Response(200, json={'items': [], 'totalPages': 1})

        self.context = TestClient(create_app(Settings(public_origin='http://testserver', dev_mode=True),
                                             transport=httpx.MockTransport(upstream)))
        self.client = self.context.__enter__()
        self.addCleanup(self.context.__exit__, None, None, None)

    def login(self):
        self.assertEqual(self.client.post('/api/auth/login', headers={'Origin': 'http://testserver'},
                         json={'identity': 'me@example.com', 'password': 'secret'}).status_code, 200)

    def test_cookie_shared_with_both_modules(self):
        self.assertEqual(self.client.get('/api/scratchpad/collections/scratchpads/records').status_code, 401)
        self.login()
        self.assertEqual(self.client.get('/api/tinytv/channels/tiny/now').status_code, 200)
        response = self.client.get('/api/scratchpad/collections/scratchpads/records?page=2&expand=owner')
        self.assertEqual(response.status_code, 200)
        upstream = self.requests[-1]
        self.assertEqual(upstream.headers['Authorization'], token(marker='refreshed'))
        self.assertNotIn('cookie', upstream.headers)
        self.assertEqual(str(upstream.url.query, 'utf-8'), 'page=2')
        self.client.post('/api/auth/logout', headers={'Origin': 'http://testserver'})
        for path in ('/api/scratchpad/collections/scratchpads/records', '/api/tinytv/channels/tiny/now'):
            self.assertEqual(self.client.get(path).status_code, 401)

    def test_writes_and_route_boundary(self):
        self.login()
        path = '/api/scratchpad/collections/scratchpads/records'
        body = {'owner': 'user1', 'title': 'draft', 'content': 'hello'}
        self.assertEqual(self.client.post(path, json=body).status_code, 403)
        self.assertEqual(self.client.post(path, json=body, headers={'Origin': 'https://other.example'}).status_code, 403)
        response = self.client.post(path, json=body, headers={'Origin': 'http://testserver'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(self.requests[-1].content), body)
        self.assertEqual(self.client.patch(path + '/' + self.record_id, json={'title': 'new'},
                         headers={'Origin': 'http://testserver'}).status_code, 200)
        self.assertEqual(self.client.delete(path + '/' + self.record_id,
                         headers={'Origin': 'http://testserver'}).status_code, 204)
        for collection in ('users', '_superusers'):
            self.assertEqual(self.client.get('/api/scratchpad/collections/' + collection + '/records').status_code, 404)
        self.assertEqual(self.client.get(path + '/bad-id').status_code, 404)
        self.assertEqual(self.client.post(path, content=b'{}', headers={'Origin': 'http://testserver',
                         'Content-Type': 'text/plain'}).status_code, 415)

    def test_upload_download_and_owner_rules(self):
        self.login()
        path = '/api/scratchpad/collections/scratchpad_files/records'
        response = self.client.post(path, data={'owner': 'user1', 'originalName': 'hello.txt', 'size': '5'},
                                    files={'file': ('hello.txt', b'hello')}, headers={'Origin': 'http://testserver'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'hello', self.requests[-1].content)
        self.assertIn('multipart/form-data', self.requests[-1].headers['Content-Type'])
        response = self.client.get('/api/scratchpad/files/' + self.record_id)
        self.assertEqual(response.content, b'0123')
        self.assertTrue(self.stream.closed)
        self.assertEqual(self.requests[-1].url.params['token'], 'short-file-token')
        self.assertIn(b'%E4%B8%96%E7%95%8C', self.requests[-1].url.raw_path)
        self.record_status = 404  # PocketBase denies another user's record.
        count = len(self.requests)
        response = self.client.get('/api/scratchpad/files/' + self.record_id)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(len(self.requests) - count, 2)  # Refresh + record read; no file fetched.
        self.assertNotIn('private upstream error', response.text)

    def test_limits_expiry_and_outage(self):
        self.login()
        path = '/api/scratchpad/collections/scratchpad_files/records'
        response = self.client.post(path, content=b'', headers={'Origin': 'http://testserver',
                                    'Content-Type': 'multipart/form-data; boundary=test',
                                    'Content-Length': str(52 * 1024 * 1024)})
        self.assertEqual(response.status_code, 413)
        self.record_status = 503
        response = self.client.get(path)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('Max-Age=0', response.headers.get('set-cookie', ''))
        self.auth_status = 401
        response = self.client.get(path)
        self.assertEqual(response.status_code, 401)
        self.assertIn('Max-Age=0', response.headers['set-cookie'])
