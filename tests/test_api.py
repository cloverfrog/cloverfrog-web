# 验证公共认证与频道 HTTP 协议；PocketBase 和媒体请求由 MockTransport 模拟，不访问真实上游。
import base64
import json
import time
import unittest
from dataclasses import replace

import httpx
from fastapi.testclient import TestClient

from auth.service import COOKIE_NAME
from config import Settings
from main import create_app


# 测试 token 只携带过期时间，模拟认证源已经验证后的响应；不用于证明本地签名校验。
def token(expiry=None, marker='initial'):
    payload = base64.urlsafe_b64encode(json.dumps({'exp': expiry or int(time.time()) + 86400}).encode()).decode().rstrip('=')
    return f'header.{payload}.{marker}'


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.pb_status = 200
        self.refresh_token = token(marker='refreshed')
        self.requests = []
        self.settings = Settings(public_origin='http://testserver', dev_mode=True)

        async def upstream(request):
            self.requests.append(request)
            if request.url.host == 'pocketbase.cloverfrog.xyz':
                if self.pb_status != 200:
                    return httpx.Response(self.pb_status, json={'message':'private upstream error'})
                return httpx.Response(200, json={'token':self.refresh_token, 'record':{
                    'id':'user1', 'collectionName':'users', 'email':'me@example.com', 'private':'hidden'}})
            raise AssertionError('Channel lookup must not contact AList or video storage')

        self.app = create_app(self.settings, transport=httpx.MockTransport(upstream))
        self.context = TestClient(self.app)
        self.client = self.context.__enter__()
        self.addCleanup(self.context.__exit__, None, None, None)

    def login(self):
        response = self.client.post('/api/auth/login', json={'identity':'me@example.com', 'password':'private-password'},
                                    headers={'Origin':'http://testserver'})
        self.assertEqual(response.status_code, 200)
        return response

    def test_login_refresh_and_cookie(self):
        response = self.login()
        cookie = response.headers['set-cookie']
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=strict', cookie)
        self.assertIn('Path=/api/', cookie)
        self.assertNotIn('Secure', cookie)
        self.assertNotIn('token', response.json())
        self.assertNotIn('private', response.text)
        request = self.requests[-1]
        self.assertEqual(json.loads(request.content)['identity'], 'me@example.com')
        self.assertEqual(request.url.path, '/api/collections/users/auth-with-password')
        self.refresh_token = token(marker='new-token')
        response = self.client.get('/api/auth/session')
        self.assertTrue(response.json()['authenticated'])
        self.assertEqual(self.client.cookies.get(COOKIE_NAME), self.refresh_token)
        self.assertEqual(self.requests[-1].url.path, '/api/collections/users/auth-refresh')

    def test_unauthenticated_and_static_paths(self):
        for path in ('/api/tinytv/channels/tiny/now',):
            self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.get('/api/auth/session').json(), {'authenticated':False})
        for path in ('/', '/pages/tinytv/', '/sources.json', '/data/tinytv/sources.json', '/docs'):
            self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.requests, [])

    def test_wrong_password_and_limiter(self):
        self.pb_status = 400
        for _ in range(5):
            response = self.client.post('/api/auth/login', json={'identity':'me@example.com', 'password':'bad'},
                                        headers={'Origin':'http://testserver'})
            self.assertEqual(response.status_code, 401)
            self.assertNotIn('private', response.text)
        self.assertEqual(self.client.post('/api/auth/login', json={'identity':'me@example.com', 'password':'bad'},
                                         headers={'Origin':'http://testserver'}).status_code, 429)

    def test_expired_token_cleared(self):
        self.login()
        self.pb_status = 401
        response = self.client.get('/api/auth/session')
        self.assertFalse(response.json()['authenticated'])
        self.assertIn('Max-Age=0', response.headers['set-cookie'])
        self.assertIsNone(self.client.cookies.get(COOKIE_NAME))

    def test_outage_does_not_clear_cookie(self):
        self.login()
        before = self.client.cookies.get(COOKIE_NAME)
        self.pb_status = 503
        for path in ('/api/auth/session', '/api/tinytv/channels/tiny/now'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 503)
            self.assertNotIn('set-cookie', response.headers)
            self.assertNotIn('private', response.text)
        self.assertEqual(self.client.cookies.get(COOKIE_NAME), before)

    def test_logout(self):
        self.login()
        response = self.client.post('/api/auth/logout', headers={'Origin':'http://testserver'})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.client.cookies.get(COOKIE_NAME))
        self.assertEqual(self.client.get('/api/tinytv/channels/tiny/now').status_code, 401)

    def test_origin_and_validation(self):
        response = self.client.post('/api/auth/login', json={'identity':'me@example.com','password':'secret'},
                                    headers={'Origin':'https://other.example'})
        self.assertEqual(response.status_code, 403)
        response = self.client.post('/api/auth/login', json={'password':'private-password'},
                                    headers={'Origin':'http://testserver'})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn('private-password', response.text)

    def test_secure_cookie_and_restart(self):
        settings = Settings(public_origin='https://testserver')
        with TestClient(create_app(settings, transport=self.app.state.http._transport),
                        base_url='https://testserver') as client:
            client.cookies.set(COOKIE_NAME, token(), path='/api/')
            response = client.get('/api/auth/session')
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()['authenticated'])
            self.assertIn('; Secure', response.headers['set-cookie'])

    def test_now_returns_alist_url_without_media_request(self):
        self.login()
        response = self.client.get('/api/tinytv/channels/tiny/now')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('path', response.json())
        self.assertTrue(response.json()['playUrl'].startswith(self.settings.alist_url + '/d/'))
        self.assertIn('no-store', response.headers['cache-control'])
        self.assertTrue(all(r.url.host == 'pocketbase.cloverfrog.xyz' for r in self.requests))
        self.assertEqual(self.client.get('/api/tinytv/play/arbitrary').status_code, 404)

    def test_direct_download_path_encoding(self):
        self.app.state.settings = replace(self.settings, alist_root='/baidu/影视 #?')
        self.login()
        response = self.client.get('/api/tinytv/channels/tiny/now')
        url = httpx.URL(response.json()['playUrl'])
        self.assertTrue(url.path.startswith('/d/baidu/影视 #?/'))
        self.assertIn(b'%E5%BD%B1%E8%A7%86%20%23%3F', url.raw_path)
        self.assertEqual(url.query, b'')
        self.assertTrue(all(r.url.host == 'pocketbase.cloverfrog.xyz' for r in self.requests))
