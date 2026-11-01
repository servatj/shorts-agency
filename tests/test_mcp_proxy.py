"""Real loopback HTTP regression tests; no production credentials/network."""
import http.client
import json
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agency_store import AgencyStore
from api_server import make_server
from web_backend import build_server


class MCPProxyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = AgencyStore(self.root / 'agency.db')
        self.store.initialize()
        self.api = make_server(self.store, 'synthetic-app-token')
        self.seen = []
        owner = self

        class Upstream(BaseHTTPRequestHandler):
            def handle_request(self):
                body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                owner.seen.append((self.command, self.path, dict(self.headers), body))
                status, data, headers = 200, b'{"jsonrpc":"2.0","id":1,"result":{}}', {}
                if self.headers.get('Authorization') != 'Bearer synthetic-mcp-token':
                    status, data = 401, b'{"error":"unauthorized"}'
                    headers['WWW-Authenticate'] = 'Bearer'
                elif self.command != 'POST':
                    status, data = 405, b'{"error":"method_not_allowed"}'
                    headers['Allow'] = 'POST'
                elif b'notifications/initialized' in body:
                    status, data = 202, b''
                if hasattr(owner, 'upstream_result'):
                    status, data, headers = owner.upstream_result
                if getattr(owner, 'delay', 0):
                    time.sleep(owner.delay)
                self.send_response(status)
                self.send_header('Content-Type', headers.pop('Content-Type', 'application/json'))
                if not getattr(owner, 'omit_length', False):
                    self.send_header('Content-Length', str(len(data)))
                for name, value in headers.items():
                    self.send_header(name, value)
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass
            do_POST = do_GET = do_DELETE = handle_request
            def log_message(self, *args):
                pass

        self.upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        self.start(self.upstream)
        self.server = build_server(self.api, '127.0.0.1', 0, root=self.root, mcp_port=self.upstream.server_port)
        self.start(self.server)

    def start(self, server):
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
        thread.start()
        def stop():
            server.shutdown()
            server.server_close()
            thread.join()
        self.addCleanup(stop)

    def request(self, method='POST', path='/mcp', body=b'{"jsonrpc":"2.0","method":"initialize","id":1}', headers=None):
        conn = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        try:
            conn.request(method, path, body, headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def test_dedicated_token_without_app_login(self):
        status, headers, body = self.request(headers={'Authorization': 'Bearer synthetic-mcp-token', 'Content-Type': 'application/json'})
        self.assertEqual(status, 200, body)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(json.loads(body)['result'], {})
        self.assertEqual(self.seen[0][1], '/mcp')

    def raw(self, headers, method='POST'):
        conn = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        try:
            conn.putrequest(method, '/mcp', skip_host=True)
            for name, value in headers:
                conn.putheader(name, value)
            conn.endheaders()
            response = conn.getresponse()
            response.read()
            return response.status
        finally:
            conn.close()

    def test_duplicate_host_rejected_before_upstream(self):
        self.assertEqual(self.raw([('Host', 'one.example'), ('Host', 'two.example'), ('Content-Length', '0')]), 400)
        self.assertEqual(self.seen, [])

    def test_nonexact_paths_never_reach_upstream(self):
        for path in ['/mcp/', '/mcp?token=synthetic', '/mcp/child']:
            self.assertEqual(self.request(path=path)[0], 404)
        self.assertEqual(self.seen, [])

    def test_invalid_ports_fail_at_construction(self):
        for port in [True, False, '8766', 0, -1, 65536, 8766.0, None]:
            with self.subTest(port=port), self.assertRaises(ValueError):
                server = build_server(self.api, '127.0.0.1', 0, root=self.root, mcp_port=port)
                server.server_close()

    def test_unreachable_upstream_is_sanitized(self):
        self.upstream.shutdown()
        self.upstream.server_close()
        status, _, body = self.request()
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body), {'error': 'mcp_unavailable'})

    def test_response_limit_and_sse_rejected(self):
        for data, kind in [(b'x' * (2 * 1024 * 1024 + 1), 'application/json'), (b'data: secret\n\n', 'text/event-stream')]:
            self.upstream_result = (200, data, {'Content-Type': kind})
            status, _, body = self.request()
            self.assertEqual(status, 502)
            self.assertEqual(json.loads(body), {'error': 'mcp_bad_response'})

    def test_forwarding_allowlist_and_actual_host(self):
        headers = {'Authorization': 'Bearer synthetic-mcp-token', 'Host': 'untrusted.example:123', 'Accept': 'application/json, text/event-stream', 'Content-Type': 'application/json', 'MCP-Protocol-Version': '2025-03-26', 'MCP-Session-Id': 'synthetic-id', 'Cookie': 'session=not-forwarded', 'Origin': 'http://localhost:8765', 'X-Forwarded-Host': 'spoof.example', 'X-Forwarded-Proto': 'https', 'X-API-Key': 'not-forwarded', 'X-CSRF-Token': 'not-forwarded'}
        self.assertEqual(self.request(headers=headers)[0], 200)
        forwarded = self.seen[-1][2]
        for name in ['Host', 'Authorization', 'Accept', 'Content-Type', 'MCP-Protocol-Version', 'MCP-Session-Id', 'Origin']:
            self.assertEqual(forwarded[name], headers[name])
        for name in ['Cookie', 'X-Forwarded-Host', 'X-Forwarded-Proto', 'X-API-Key', 'X-CSRF-Token']:
            self.assertNotIn(name, forwarded)

    def test_auth_cannot_be_replaced_by_cookie_or_app_token(self):
        from web_auth import Auth
        from web_store import WebStore
        with WebStore(self.store.database_path).connect() as db:
            db.execute('INSERT INTO web_sessions VALUES (?, ?, ?, ?)', (Auth.hash('synthetic-session'), 'test-user', 'synthetic-csrf', time.time() + 300))
        cookie = {'Cookie': 'agency_session=synthetic-session'}
        self.assertEqual(self.request(method='GET', path='/auth/me', body=None, headers=cookie)[0], 200)
        for headers in [{}, cookie, {'Authorization': 'Bearer synthetic-app-token'}]:
            status, response_headers, _ = self.request(headers=headers)
            self.assertEqual(status, 401)
            self.assertEqual(response_headers['WWW-Authenticate'], 'Bearer')
        self.assertEqual(len(self.seen), 3)
        self.assertNotIn('Authorization', self.seen[0][2])
        self.assertNotIn('Cookie', self.seen[1][2])

    def test_methods_and_notifications_preserve_status(self):
        headers = {'Authorization': 'Bearer synthetic-mcp-token'}
        for method in ['GET', 'DELETE']:
            status, result, _ = self.request(method=method, body=None, headers=headers)
            self.assertEqual(status, 405)
            self.assertEqual(result['Allow'], 'POST')
        self.assertEqual(self.request(body=b'{"method":"notifications/initialized"}', headers=headers)[0], 202)

    def test_redirect_not_followed_and_sensitive_response_headers_stripped(self):
        self.upstream_result = (307, b'{}', {'Location': 'http://127.0.0.1:1/leak', 'Set-Cookie': 'secret=x', 'MCP-Session-Id': 'synthetic'})
        status, headers, _ = self.request()
        self.assertEqual(status, 307)
        self.assertEqual(len(self.seen), 1)
        self.assertNotIn('Location', headers)
        self.assertNotIn('Set-Cookie', headers)
        self.assertEqual(headers['MCP-Session-Id'], 'synthetic')

    def test_request_protections_precede_proxy(self):
        self.assertEqual(self.request(headers={'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(self.request(body=b'x' * (256 * 1024 + 1))[0], 413)
        for headers, expected in [([], 400), ([('Transfer-Encoding', 'chunked')], 400), ([('Content-Length', '0'), ('Content-Length', '0')], 400), ([('Content-Length', '0, 0')], 400), ([('Content-Length', '0'), ('Authorization', 'a'), ('Authorization', 'b')], 400), ([('Content-Length', '0'), ('Origin', 'http://localhost:8765'), ('Origin', 'http://localhost:8765')], 403)]:
            self.assertEqual(self.raw([('Host', 'localhost'), *headers]), expected)
        self.assertEqual(self.seen, [])

    def test_app_auth_and_security_headers_unchanged(self):
        self.assertEqual(self.request(method='GET', path='/v1/shorts', body=None)[0], 401)
        status, headers, body = self.request(method='GET', path='/v1/shorts', body=None, headers={'Authorization': 'Bearer synthetic-app-token'})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {'items': []})
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertIn('Content-Security-Policy', headers)
        self.assertEqual(self.seen, [])

    def test_upstream_timeout_is_504_and_connection_uses_fixed_loopback(self):
        original = http.client.HTTPConnection
        self.delay = 0.15
        calls = []
        def short_connection(host, port, timeout):
            calls.append((host, port, timeout))
            return original(host, port, timeout=0.03)
        # Patch only the proxy reference, retaining a real upstream socket.
        import types
        facade = types.SimpleNamespace(HTTPConnection=short_connection, HTTPException=http.client.HTTPException)
        with patch('mcp_http_proxy.http', types.SimpleNamespace(client=facade)):
            status, _, body = self.request()
        self.assertEqual(status, 504)
        self.assertEqual(json.loads(body), {'error': 'mcp_timeout'})
        self.assertEqual(calls, [('127.0.0.1', self.upstream.server_port, 30)])

    def test_unframed_oversize_response_is_bounded(self):
        self.omit_length = True
        self.upstream_result = (200, b'x' * (2 * 1024 * 1024 + 1), {})
        self.assertEqual(self.request()[0], 502)

    def test_maximum_body_is_forwarded_without_truncation(self):
        body = b'x' * (256 * 1024)
        self.assertEqual(self.request(body=body, headers={'Authorization': 'Bearer synthetic-mcp-token'})[0], 200)
        self.assertEqual(self.seen[-1][3], body)
