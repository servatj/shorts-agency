from contextlib import closing
import hashlib
import http.client
import json
import sqlite3
import tempfile
import subprocess
import sys
import threading
import unittest
from synthetic_credentials import TEST_PASSWORD, TEST_TOKEN
from unittest.mock import patch
from pathlib import Path

import api_server
from agency_store import AgencyStore


class WebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'data').mkdir()
        (self.root / 'data/social-inventory.json').write_text(json.dumps({'accounts': [], 'recorded_at': None}))
        (self.root / 'static').mkdir()
        (self.root / 'static/index.html').write_text('<html>Agency</html>')
        (self.root / 'static/app.js').write_text('"use strict";')
        (self.root / 'static/style.css').write_text('body {}')
        (self.root / 'secrets').mkdir()
        salt = bytes.fromhex('1234567890abcdef' * 2)
        password_hash = hashlib.scrypt(TEST_PASSWORD.encode(), salt=salt, n=16384, r=8, p=1, dklen=64).hex()
        (self.root / 'secrets/admin.json').write_text(json.dumps(dict(username='admin', salt=salt.hex(), password_hash=password_hash, algorithm='scrypt')))
        self.store = AgencyStore(self.root / 'data/agency.db')
        self.store.initialize()
        self.assertTrue(hasattr(api_server, 'create_http_server'), 'real HTTP server factory missing')
        self.server = api_server.create_http_server(self.store, TEST_TOKEN, '127.0.0.1', 0, root=self.root)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, method, path, body=None, headers=None):
        headers = dict(headers or {})
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
            headers.setdefault('Content-Type', 'application/json')
        conn = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        try:
            conn.request(method, path, body, headers)
            response = conn.getresponse()
            data = response.read()
            result = json.loads(data) if data and 'application/json' in response.getheader('Content-Type', '') else data
            return response.status, dict(response.getheaders()), result
        finally:
            conn.close()

    def login(self, extra=None):
        status, headers, body = self.request('POST', '/auth/login', {'username': 'admin', 'password': TEST_PASSWORD}, {'Origin': 'http://localhost:8765', **(extra or {})})
        self.assertEqual(status, 200, body)
        return {'Cookie': headers['Set-Cookie'].split(';')[0], 'X-CSRF-Token': body['csrf_token'], 'Origin': 'http://localhost:8765'}, headers, body

    def test_session_login_me_logout_and_origin_csrf(self):
        self.assertEqual(self.request('GET', '/auth/me')[0], 401)
        self.assertEqual(self.request('POST', '/auth/login', {'username': 'admin', 'password': 'wrong'}, {'Origin': 'http://localhost:8765'})[0], 401)
        self.assertEqual(self.request('POST', '/auth/login', {'username': 'admin', 'password': TEST_PASSWORD}, {'Origin': 'https://evil.example'})[0], 403)
        headers, response_headers, body = self.login()
        self.assertEqual(body['user'], {'username': 'admin'})
        self.assertIn('HttpOnly', response_headers['Set-Cookie'])
        self.assertIn('SameSite=Strict', response_headers['Set-Cookie'])
        self.assertNotIn('Secure', response_headers['Set-Cookie'])
        self.assertEqual(self.request('GET', '/auth/me', headers=headers)[2], body)
        self.assertEqual(self.request('GET', '/v1/templates', headers=headers)[0], 200)
        with closing(sqlite3.connect(self.store.database_path)) as db, db:
            session_data = str(db.execute('SELECT * FROM web_sessions').fetchall())
        self.assertNotIn(headers['Cookie'].split('=', 1)[1], session_data)
        self.assertEqual(self.request('POST', '/auth/logout', {}, {'Cookie': headers['Cookie'], 'Origin': headers['Origin']})[0], 403)
        self.assertEqual(self.request('POST', '/auth/logout', {}, {'Cookie': headers['Cookie'], 'X-CSRF-Token': headers['X-CSRF-Token']})[0], 403)
        self.assertEqual(self.request('POST', '/auth/logout', {}, headers)[0], 200)
        self.assertEqual(self.request('GET', '/auth/me', headers=headers)[0], 401)
        _, secure_headers, _ = self.login({'X-Forwarded-Proto': 'https'})
        self.assertIn('Secure', secure_headers['Set-Cookie'])

    def test_auth_validation_limits_and_rate_limit(self):
        origin = {'Origin': 'http://localhost:8765', 'Content-Type': 'application/json'}
        for body in ['{', '[]', '{}', '{"username":1,"password":true}', '{"username":"admin","password":"x","extra":1}']:
            self.assertEqual(self.request('POST', '/auth/login', body, origin)[0], 400)
        self.assertEqual(self.request('POST', '/auth/login', 'x' * (256 * 1024 + 1), origin)[0], 413)
        for _ in range(5):
            self.assertEqual(self.request('POST', '/auth/login', {'username': 'admin', 'password': 'wrong'}, origin)[0], 401)
        self.assertEqual(self.request('POST', '/auth/login', {'username': 'admin', 'password': TEST_PASSWORD}, origin)[0], 429)

    def test_session_expiration_and_empty_token_rejected(self):
        headers, _, _ = self.login()
        with closing(sqlite3.connect(self.store.database_path)) as db, db:
            db.execute('UPDATE web_sessions SET expires_at=0')
        self.assertEqual(self.request('GET', '/auth/me', headers=headers)[0], 401)
        with self.assertRaises(ValueError):
            api_server.make_server(self.store, '')

    def test_shorts_create_list_read_patch_persistence_and_csrf(self):
        bearer = {'Authorization': f'Bearer {TEST_TOKEN}'}
        self.assertEqual(self.request('GET', '/v1/shorts', headers=bearer)[2], {'items': []})
        item = {'title': 'Science', 'script': 'Narration', 'status': 'review', 'language': 'en', 'format': '16:9', 'youtube_url': 'https://youtu.be/SAMPLE00001', 'preview_url': 'https://cdn.example/video.mp4', 'youtube_title': 'Title', 'description': 'Description', 'tags': ['science'], 'channel': 'Main', 'notes': 'Manual metadata'}
        status, _, created = self.request('POST', '/v1/shorts', item, bearer)
        self.assertEqual(status, 201, created)
        self.assertTrue(created['created_at'])
        path = '/v1/shorts/' + str(created['id'])
        self.assertEqual(self.request('GET', path, headers=bearer)[2], created)
        for key, value in item.items():
            self.assertEqual(created[key], value)
        headers, _, _ = self.login()
        self.assertEqual(self.request('PATCH', path, {'title': 'Changed'}, {'Cookie': headers['Cookie']})[0], 403)
        self.assertEqual(self.request('PATCH', path, {'title': 'Changed'}, headers)[0], 200)
        result = self.request('GET', path, headers=bearer)[2]
        self.assertEqual(result['title'], 'Changed')
        self.assertEqual(result['script'], 'Narration')
        self.assertEqual(self.request('GET', '/v1/shorts', headers=bearer)[2]['items'], [result])
        second = api_server.create_http_server(self.store, TEST_TOKEN, '127.0.0.1', 0, root=self.root)
        second.server_close()
        self.assertEqual(self.request('GET', path, headers=bearer)[2], result)
        self.assertEqual(self.request('GET', '/v1/shorts/9999', headers=bearer)[0], 404)
        self.assertEqual(self.request('PATCH', '/v1/shorts/9999', {'title': 'No'}, bearer)[0], 404)
        self.assertEqual(self.request('GET', path)[0], 401)

    def test_short_validation_and_url_injections(self):
        bearer = {'Authorization': f'Bearer {TEST_TOKEN}'}
        invalid = [{}, {'title': ''}, {'title': ' '}, {'title': 1}, {'title': 'x' * 501}, {'title': 'x', 'id': 9}, {'title': 'x', 'status': 'upload'}, {'title': 'x', 'language': 'fr'}, {'title': 'x', 'format': 'square'}, {'title': 'x', 'tags': 'bad'}, {'title': 'x', 'tags': [1]}, {'title': 'x', 'script': None}]
        for fields in invalid:
            with self.subTest(fields=str(fields)[:60]):
                self.assertEqual(self.request('POST', '/v1/shorts', fields, bearer)[0], 400)
        for field, urls in {
            'youtube_url': ['https://youtube.com.evil.example/watch?v=SAMPLE00001', 'https://youtube.com@evil.example/watch?v=SAMPLE00001', 'https://www.youtube.com/watch?v=bad', 'https://www.youtube.com/watch?v=SAMPLE00001&v=aaaaaaaaaaa', 'https://www.youtube.com/channel/SAMPLE00001', 'javascript:alert(1)', 'https://youtu.be/SAMPLE00001/extra', 'https://youtube.com:444/watch?v=SAMPLE00001'],
            'preview_url': ['javascript:alert(1)', 'http://example.com/file.mp4', '//evil.example/x', '/media/../secrets/admin.json', '/media/evil.html', 'https://user:pass@example.com/v.mp4', 'https://example.com\\@evil.com/v.mp4', 'https://example.com/\nx']
        }.items():
            for url in urls:
                with self.subTest(field=field, url=url):
                    self.assertEqual(self.request('POST', '/v1/shorts', {'title': 'x', field: url}, bearer)[0], 400)
        for url in ['https://youtu.be/SAMPLE00001', 'https://www.youtube.com/watch?v=SAMPLE00001', 'https://m.youtube.com/shorts/SAMPLE00001', 'https://youtube.com/embed/SAMPLE00001']:
            self.assertEqual(self.request('POST', '/v1/shorts', {'title': "Quote'); DROP TABLE channels; --", 'youtube_url': url, 'preview_url': '/media/demo.mp4'}, bearer)[0], 201)
        created = self.request('POST', '/v1/shorts', {'title': 'Minimal'}, bearer)[2]
        self.assertEqual(created['status'], 'draft')
        self.assertEqual(created['language'], 'es')
        self.assertEqual(created['tags'], [])
        self.assertEqual(self.request('PATCH', '/v1/shorts/' + str(created['id']), {'created_at': 'fake'}, bearer)[0], 400)
        self.assertEqual(self.request('GET', '/v1/channels', headers=bearer)[0], 200)

    def test_metrics_append_nullable_manual_and_agent(self):
        bearer = {'Authorization': f'Bearer {TEST_TOKEN}'}
        short = self.request('POST', '/v1/shorts', {'title': 'Metrics'}, bearer)[2]
        path = '/v1/shorts/' + str(short['id']) + '/metrics'
        self.assertEqual(self.request('GET', path, headers=bearer)[2], {'items': []})
        first = {'observed_at': '2026-10-29T12:00:00Z', 'views': 12, 'likes': 0, 'comments': None, 'shares': None, 'average_view_duration_seconds': 1.5, 'retention_percent': 120.5, 'source': 'manual', 'notes': 'Entered by user, not YouTube analytics'}
        status, _, result = self.request('POST', path, first, bearer)
        self.assertEqual(status, 201)
        for key, value in first.items():
            self.assertEqual(result[key], value)
        self.assertEqual(result['short_id'], short['id'])
        self.assertTrue(result['created_at'])
        self.assertEqual(result.get('updated_at'), result['created_at'])
        second = {'observed_at': '2026-10-29T13:00:00+00:00', 'source': 'agent'}
        self.assertEqual(self.request('POST', path, second, bearer)[0], 201)
        rows = self.request('GET', path, headers=bearer)[2]['items']
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], result)
        self.assertIsNone(rows[1]['views'])
        self.assertEqual(self.request('GET', '/v1/shorts/999/metrics', headers=bearer)[0], 404)
        self.assertEqual(self.request('POST', '/v1/shorts/999/metrics', first, bearer)[0], 404)
        invalid = [{}, {'observed_at': 'yesterday'}, {'observed_at': '2026-10-29'}, {'observed_at': '2026-10-29T12:00:00'}, {'views': -1}, {'views': 1.5}, {'views': True}, {'likes': '3'}, {'retention_percent': -0.1}, {'average_view_duration_seconds': float('inf')}, {'source': 'youtube'}, {'extra': 'bad'}]
        for fields in invalid:
            payload = fields if 'observed_at' in fields or not fields else {**first, **fields}
            with self.subTest(fields=fields):
                self.assertEqual(self.request('POST', path, payload, bearer)[0], 400)
        self.assertEqual(len(self.request('GET', path, headers=bearer)[2]['items']), 2)

    def test_authenticated_media_ranges_and_path_confinement(self):
        media = self.root / 'media'
        media.mkdir()
        (media / 'sample.mp4').write_bytes(b'0123456789')
        (media / 'sample.webm').write_bytes(b'webm')
        (media / 'escape.mp4').symlink_to(self.root / 'secrets/admin.json')
        (media / 'directory.mp4').mkdir()
        bearer = {'Authorization': f'Bearer {TEST_TOKEN}'}
        self.assertEqual(self.request('GET', '/media/sample.mp4')[0], 401)
        status, headers, data = self.request('GET', '/media/sample.mp4', headers=bearer)
        self.assertEqual((status, data), (200, b'0123456789'))
        self.assertEqual(headers['Content-Type'], 'video/mp4')
        self.assertEqual(headers['Content-Length'], '10')
        self.assertEqual(headers['Accept-Ranges'], 'bytes')
        session, _, _ = self.login()
        self.assertEqual(self.request('GET', '/media/sample.webm', headers=session)[2], b'webm')
        for value, expected, content_range in [('bytes=2-5', b'2345', 'bytes 2-5/10'), ('bytes=7-', b'789', 'bytes 7-9/10'), ('bytes=-3', b'789', 'bytes 7-9/10'), ('bytes=8-100', b'89', 'bytes 8-9/10')]:
            status, headers, data = self.request('GET', '/media/sample.mp4', headers={**bearer, 'Range': value})
            self.assertEqual((status, data), (206, expected))
            self.assertEqual(headers['Content-Range'], content_range)
            self.assertEqual(int(headers['Content-Length']), len(expected))
        for value in ['bytes=10-', 'bytes=5-2', 'bytes=-0', 'bytes=0-1,3-4', 'nonsense']:
            status, headers, _ = self.request('GET', '/media/sample.mp4', headers={**bearer, 'Range': value})
            self.assertEqual(status, 416)
            self.assertEqual(headers['Content-Range'], 'bytes */10')
        status, headers, data = self.request('HEAD', '/media/sample.mp4', headers=bearer)
        self.assertEqual((status, headers['Content-Length'], data), (200, '10', b''))
        for path in ['/media/escape.mp4', '/media/directory.mp4', '/media/missing.mp4', '/media/../secrets/admin.json', '/media/%2e%2e/secrets/admin.json', '/media/sample.mp4/extra', '/media/admin.json']:
            with self.subTest(path=path):
                self.assertEqual(self.request('GET', path, headers=bearer)[0], 404)

    def test_launcher_import_has_no_side_effects(self):
        target = self.root / 'run_local.py'
        target.write_text((Path(api_server.__file__).parent / 'run_local.py').read_text())
        result = subprocess.run([sys.executable, '-c', 'import runpy; runpy.run_path(' + repr(str(target)) + ', run_name="imported")'], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / 'data/shorts_agency.db').exists())

    def test_launcher_preserves_existing_seed_data(self):
        import run_local
        token_path = self.root / 'secrets/api_token'
        token_path.write_text(TEST_TOKEN)
        target_db = self.root / 'data/shorts_agency.db'
        target = AgencyStore(target_db)
        target.initialize()
        with closing(sqlite3.connect(target_db)) as db, db:
            db.execute("UPDATE templates SET name='Customized title'")
        # Replace only the blocking serve loop, not persistence or application logic.
        with patch.object(run_local, 'ROOT', self.root), patch.object(run_local, 'TOKEN_FILE', token_path), patch.object(run_local, 'serve') as serve:
            run_local.main()
            self.assertEqual(serve.call_args.args[2:4], ('127.0.0.1', 8765))
        self.assertTrue(all(item['name'] == 'Customized title' for item in target.list_templates()))

    def test_unsupported_methods_still_enforce_origin_and_headers(self):
        for method in ['PUT', 'DELETE', 'OPTIONS', 'TRACE', 'BREW']:
            with self.subTest(method=method):
                status, headers, _ = self.request(method, '/v1/shorts', headers={'Origin': 'https://evil.example'})
                self.assertEqual(status, 403)
                self.assertEqual(headers['Cache-Control'], 'no-store')
                self.assertEqual(self.request(method, '/v1/shorts', headers={'Authorization': f'Bearer {TEST_TOKEN}'})[0], 405)

    def test_malformed_json_and_extreme_numbers_are_400(self):
        bearer = {'Authorization': f'Bearer {TEST_TOKEN}', 'Content-Type': 'application/json'}
        for body in ['{"title":"first","title":"second"}', '"scalar"', '{"title":"x","tags":null}', '{"title":"x","status":{}}']:
            with self.subTest(body=body):
                self.assertEqual(self.request('POST', '/v1/shorts', body, bearer)[0], 400)
        item = self.request('POST', '/v1/shorts', {'title': 'Numbers'}, bearer)[2]
        path = '/v1/shorts/' + str(item['id']) + '/metrics'
        for key in ['views', 'average_view_duration_seconds']:
            with self.subTest(key=key):
                self.assertEqual(self.request('POST', path, {'observed_at': '2026-10-29T12:00:00Z', key: 10 ** 1000}, bearer)[0], 400)
        self.assertEqual(self.request('POST', '/auth/login', {'username': 'admin', 'password': '\ud800'}, {'Origin': 'http://localhost:8765'})[0], 400)

    def test_legacy_routes_are_exact_and_decode_query(self):
        bearer = {'Authorization': f'Bearer {TEST_TOKEN}'}
        self.assertEqual(self.request('GET', '/v1/prompts-secret', headers=bearer)[0], 404)
        status, _, result = self.request('GET', '/v1/prompts?other=x&template_id=animated%2Dscience%2Dshort%2Dv1', headers=bearer)
        self.assertEqual(status, 200)
        self.assertEqual(len(result['items']), 3)
        self.assertTrue(all(item['template_id'] == 'animated-science-short-v1' for item in result['items']))
        self.assertEqual(api_server.make_server(self.store, TEST_TOKEN).dispatch('GET', '/v1/prompts-secret', f'Bearer {TEST_TOKEN}')[0], 404)

    def test_duplicate_origin_and_auth_headers_are_rejected(self):
        for name, values, expected in [('Origin', ['http://localhost:8765', 'https://evil.example'], 403), ('Authorization', [f'Bearer {TEST_TOKEN}', 'Bearer wrong'], 400)]:
            conn = http.client.HTTPConnection(*self.server.server_address, timeout=5)
            try:
                conn.putrequest('GET', '/v1/shorts')
                for value in values:
                    conn.putheader(name, value)
                conn.endheaders()
                result = conn.getresponse()
                result.read()
                self.assertEqual(result.status, expected)
            finally:
                conn.close()

    def test_incomplete_body_has_bounded_read_timeout(self):
        self.assertEqual(self.server.RequestHandlerClass.timeout, 10)
        self.server.RequestHandlerClass.timeout = 0.1
        conn = http.client.HTTPConnection(*self.server.server_address, timeout=2)
        try:
            conn.putrequest('POST', '/v1/shorts')
            conn.putheader('Authorization', f'Bearer {TEST_TOKEN}')
            conn.putheader('Content-Type', 'application/json')
            conn.putheader('Content-Length', '100')
            conn.endheaders(b'{}')
            response = conn.getresponse()
            self.assertEqual(response.status, 408)
            self.assertEqual(json.loads(response.read()), {'error': 'request_timeout'})
        finally:
            conn.close()

    def test_database_state_and_sessions_survive_server_restart(self):
        headers, _, body = self.login()
        item = self.request('POST', '/v1/shorts', {'title': 'Persisted'}, headers)[2]
        self.stop()
        self.server = api_server.create_http_server(self.store, TEST_TOKEN, '127.0.0.1', 0, root=self.root)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.assertEqual(self.request('GET', '/auth/me', headers=headers)[2], body)
        self.assertEqual(self.request('GET', '/v1/shorts/' + str(item['id']), headers=headers)[2], item)
        for _ in range(4):
            self.assertEqual(self.request('POST', '/auth/login', {'username': 'admin', 'password': 'wrong'}, {'Origin': 'http://localhost:8765'})[0], 401)
        self.assertEqual(self.request('POST', '/auth/login', {'username': 'admin', 'password': 'wrong'}, {'Origin': 'http://localhost:8765'})[0], 429)

    def test_internal_database_failure_is_generic(self):
        with closing(sqlite3.connect(self.store.database_path)) as db, db:
            db.execute('DROP TABLE web_metrics')
            db.execute('DROP TABLE web_shorts')
        status, headers, body = self.request('GET', '/v1/shorts', headers={'Authorization': f'Bearer {TEST_TOKEN}'})
        self.assertEqual(status, 500)
        self.assertEqual(body, {'error': 'internal_error'})
        self.assertEqual(headers['Cache-Control'], 'no-store')

    def test_body_limit_applies_to_logout_and_reads(self):
        headers, _, _ = self.login()
        for method, path in [('POST', '/auth/logout'), ('GET', '/v1/shorts')]:
            with self.subTest(method=method):
                self.assertEqual(self.request(method, path, 'x' * (256 * 1024 + 1), headers)[0], 413)
        self.assertEqual(self.request('GET', '/auth/me', headers=headers)[0], 200)

    def test_public_shell_exact_static_allowlist_security_headers(self):
        for path in ['/', '/static/app.js', '/static/style.css']:
            status, headers, data = self.request('GET', path)
            self.assertEqual(status, 200)
            self.assertTrue(data)
            self.assertEqual(headers['Cache-Control'], 'no-store')
            self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
            self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        for path in ['/static/../secrets/admin.json', '/static/secret.js']:
            self.assertEqual(self.request('GET', path)[0], 404)
        self.assertEqual(self.request('GET', '/v1/templates')[0], 401)
        self.assertEqual(self.request('GET', '/v1/templates', headers={'Authorization': f'Bearer {TEST_TOKEN}'})[0], 200)
