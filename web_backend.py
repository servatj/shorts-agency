"""HTTP transport; only explicit static routes are public."""
import json
import re
from urllib.parse import urlsplit, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from web_auth import Auth, ORIGINS, cookie, equal
from web_store import PublishedScriptLocked, WebStore
from reference_store import ReferenceStore
from web_media import open_media, byte_range
from web_validation import ValidationError, short_fields, metric_fields
from mcp_http_proxy import forward as forward_mcp

CSP = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' https: data:; media-src 'self' https:; frame-src https://www.youtube-nocookie.com https://www.tiktok.com; frame-ancestors 'none'; base-uri 'none'; object-src 'none'; form-action 'self'"


class RequestError(Exception):
    def __init__(self, status, error):
        self.status = status
        self.error = error


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_key')
        result[key] = value
    return result


def build_server(api, host, port, *, root=None, mcp_port=8766):
    if type(mcp_port) is not int or not 1 <= mcp_port <= 65535:
        raise ValueError('invalid_mcp_port')
    root = Path(root) if root is not None else Path(__file__).resolve().parent
    static = {'/': ('index.html', 'text/html; charset=utf-8'), '/static/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/static/style.css': ('style.css', 'text/css; charset=utf-8')}
    for page in ('/social', '/scripts', '/videos', '/references'):
        static[page] = static['/']

    store = WebStore(api.store.database_path)
    references = ReferenceStore(api.store.database_path)
    auth = Auth(store, root)

    class Handler(BaseHTTPRequestHandler):
        timeout = 10

        def respond(self, status, body, content_type='application/json; charset=utf-8', headers=None, stream=None):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=True, allow_nan=False).encode()
            self.send_response(status)
            for name, value in {'Content-Type': content_type, 'Content-Length': str(len(data)), 'Cache-Control': 'no-store', 'Content-Security-Policy': CSP, 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer', **(headers or {})}.items():
                self.send_header(name, value)
            self.end_headers()
            if self.command != 'HEAD':
                if stream is None:
                    self.wfile.write(data)
                else:
                    remaining = int(headers['Content-Length'])
                    while remaining:
                        chunk = stream.read(min(65536, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)

        def body_length(self, required=False):
            lengths = self.headers.get_all('Content-Length', [])
            if self.headers.get('Transfer-Encoding') or len(lengths) > 1 or (required and not lengths):
                raise RequestError(400, 'invalid_body')
            value = lengths[0] if lengths else '0'
            if not re.fullmatch(r'[0-9]{1,12}', value):
                raise RequestError(400, 'invalid_body')
            length = int(value)
            if length > 256 * 1024:
                raise RequestError(413, 'body_too_large')
            return length

        def read_json(self):
            length = self.body_length(required=True)
            if self.headers.get_content_type() != 'application/json':
                raise RequestError(400, 'json_required')
            try:
                body = json.loads(self.rfile.read(length).decode('utf-8'), object_pairs_hook=unique_object, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            except (ValueError, UnicodeError, RecursionError):
                raise RequestError(400, 'invalid_json')
            if not isinstance(body, dict):
                raise RequestError(400, 'object_required')
            return body

        def read_short(self, create=False, short_id=None):
            fields = short_fields(self.read_json(), create=create)
            account_id = fields.get('social_account_id')
            if account_id is not None:
                inventory = json.loads((root / 'data/social-inventory.json').read_text())
                if account_id not in {a['id'] for a in inventory['accounts']} and (
                    short_id is None or account_id != store.get_short(short_id).get('social_account_id')
                ):
                    raise ValidationError('unknown_social_account_id')
            return fields

        def handle_request(self):
            try:
                if len(self.headers.get_all('Origin', [])) > 1:
                    return self.respond(403, {'error': 'forbidden_origin'})
                if any(len(self.headers.get_all(name, [])) > 1 for name in ('Host', 'Authorization', 'Cookie', 'X-CSRF-Token', 'X-Forwarded-Proto')):
                    raise RequestError(400, 'duplicate_header')
                origin = self.headers.get('Origin')
                if origin is not None and origin not in ORIGINS:
                    return self.respond(403, {'error': 'forbidden_origin'})
                self.body_length()
                if self.path.startswith(('/mcp/', '/mcp?', '/mcp#')):
                    return self.respond(404, {'error': 'not_found'})
                if self.path == '/mcp':
                    if not self.headers.get('Host'):
                        raise RequestError(400, 'invalid_host')
                    length = self.body_length(required=self.command == 'POST')
                    body = self.rfile.read(length)
                    if len(body) != length:
                        raise RequestError(400, 'invalid_body')
                    status, data, kind, headers = forward_mcp(self.command, self.headers, body, port=mcp_port)
                    return self.respond(status, data, kind, headers)
                session = auth.session(self.headers.get('Cookie'))
                bearer = bool(api.token) and equal(self.headers.get('Authorization', ''), f'Bearer {api.token}')
                secure = self.headers.get('X-Forwarded-Proto', '').lower() == 'https'
                if self.path == '/auth/login' and self.command == 'POST':
                    if origin not in ORIGINS:
                        return self.respond(403, {'error': 'forbidden_origin'})
                    body = self.read_json()
                    if set(body) != {'username', 'password'} or any(not isinstance(body[k], str) or not 1 <= len(body[k]) <= 1024 for k in body):
                        raise RequestError(400, 'invalid_credentials')
                    try:
                        body['username'].encode('utf-8')
                        body['password'].encode('utf-8')
                    except UnicodeError:
                        raise RequestError(400, 'invalid_credentials')
                    if auth.limited(self.client_address[0]):
                        return self.respond(429, {'error': 'rate_limited'}, headers={'Retry-After': '300'})
                    result = auth.login(body['username'], body['password'])
                    if not result:
                        return self.respond(401, {'error': 'unauthorized'})
                    token, body = result
                    return self.respond(200, body, headers={'Set-Cookie': cookie(token, secure)})
                if self.path == '/auth/me' and self.command == 'GET':
                    if not session:
                        return self.respond(401, {'error': 'unauthorized'})
                    return self.respond(200, {'user': {'username': session['username']}, 'csrf_token': session['csrf_token']})
                if self.path == '/auth/logout' and self.command == 'POST':
                    if not session:
                        return self.respond(401, {'error': 'unauthorized'})
                    if origin not in ORIGINS or not equal(self.headers.get('X-CSRF-Token', ''), session['csrf_token']):
                        return self.respond(403, {'error': 'csrf_failed'})
                    auth.logout(session)
                    return self.respond(200, {'ok': True}, headers={'Set-Cookie': cookie('', secure, clear=True)})
                if self.command == 'GET' and self.path in static:
                    filename, kind = static[self.path]
                    return self.respond(200, (root / 'static' / filename).read_bytes(), kind)
                if self.path.startswith('/static/'):
                    return self.respond(404, {'error': 'not_found'})
                if not session and not bearer:
                    return self.respond(401, {'error': 'unauthorized'})
                if self.command not in {'GET', 'HEAD'} and not bearer:
                    if origin not in ORIGINS or not equal(self.headers.get('X-CSRF-Token', ''), session['csrf_token']):
                        return self.respond(403, {'error': 'csrf_failed'})
                path = urlsplit(self.path).path
                if path == '/v1/scripts':
                    if self.command != 'GET':
                        return self.respond(405, {'error': 'method_not_allowed'})
                    query = parse_qs(urlsplit(self.path).query).get('q', [''])[0].strip().casefold()
                    items = store.list_shorts()
                    if query:
                        items = [item for item in items if any(query in str(item.get(key, '')).casefold() for key in ('title', 'script', 'channel'))]
                    return self.respond(200, {'items': items})
                if path == '/v1/social-accounts':
                    if self.command != 'GET':
                        return self.respond(405, {'error': 'method_not_allowed'})
                    inventory = json.loads((root / 'data/social-inventory.json').read_text())
                    accounts = inventory['accounts']
                    counts = {platform: sum(a['platform'] == platform for a in accounts) for platform in sorted({a['platform'] for a in accounts})}
                    return self.respond(200, {'items': accounts, 'total': len(accounts), 'counts': counts, 'recorded_at': inventory.get('recorded_at')})
                if path == '/v1/references' and self.command == 'GET':
                    query = parse_qs(urlsplit(self.path).query)
                    return self.respond(200, {'items': references.list_references(query.get('q', [''])[0], query.get('type', [''])[0])})
                if path == '/v1/references/status' and self.command == 'GET':
                    return self.respond(200, references.status())
                if path == '/v1/references/import' and self.command == 'POST':
                    if not bearer:
                        return self.respond(403, {'error': 'bearer_required'})
                    return self.respond(200, references.import_references(self.read_json()))
                reference_match = re.fullmatch(r'/v1/references/([1-9][0-9]{0,17})', path)
                if reference_match and self.command == 'GET':
                    return self.respond(200, references.get_reference(int(reference_match[1])))
                if path in {'/v1/references', '/v1/references/status', '/v1/references/import'} or reference_match:
                    return self.respond(405, {'error': 'method_not_allowed'})
                if path.startswith('/media/'):
                    if self.command not in {'GET', 'HEAD'}:
                        return self.respond(405, {'error': 'method_not_allowed'})
                    with open_media(root, path[7:]) as (stream, size):
                        try:
                            start, end = byte_range(self.headers.get('Range'), size)
                        except ValueError:
                            return self.respond(416, {'error': 'invalid_range'}, headers={'Content-Range': f'bytes */{size}'})
                        partial = self.headers.get('Range') is not None
                        media_headers = {'Content-Length': str(end - start + 1), 'Accept-Ranges': 'bytes'}
                        if partial:
                            media_headers['Content-Range'] = f'bytes {start}-{end}/{size}'
                        stream.seek(start)
                        kind = 'video/mp4' if path.endswith('.mp4') else 'video/webm'
                        return self.respond(206 if partial else 200, b'', kind, media_headers, stream=stream)
                if path == '/v1/shorts':
                    if self.command == 'GET':
                        return self.respond(200, {'items': store.list_shorts()})
                    if self.command == 'POST':
                        return self.respond(201, store.create_short(self.read_short(create=True)))
                    return self.respond(405, {'error': 'method_not_allowed'})
                metric_match = re.fullmatch(r'/v1/shorts/([1-9][0-9]{0,17})/metrics', path)
                if metric_match:
                    short_id = int(metric_match[1])
                    if self.command == 'GET':
                        return self.respond(200, {'items': store.list_metrics(short_id)})
                    if self.command == 'POST':
                        return self.respond(201, store.append_metric(short_id, metric_fields(self.read_json())))
                    return self.respond(405, {'error': 'method_not_allowed'})
                match = re.fullmatch(r'/v1/shorts/([1-9][0-9]{0,17})', path)
                if match:
                    short_id = int(match[1])
                    if self.command == 'GET':
                        return self.respond(200, store.get_short(short_id))
                    if self.command == 'PATCH':
                        return self.respond(200, store.patch_short(short_id, self.read_short(short_id=short_id)))
                    return self.respond(405, {'error': 'method_not_allowed'})
                authorization = f'Bearer {api.token}' if session or bearer else None
                status, body = api.dispatch(self.command, self.path, authorization)
                self.respond(status, body)
            except TimeoutError:
                self.respond(408, {'error': 'request_timeout'})
            except ValidationError as error:
                self.respond(400, {'error': str(error)})
            except PublishedScriptLocked as error:
                self.respond(409, {'error': str(error)})
            except RequestError as error:
                self.respond(error.status, {'error': error.error})
            except (FileNotFoundError, KeyError):
                self.respond(404, {'error': 'not_found'})
            except Exception:
                self.respond(500, {'error': 'internal_error'})

        do_GET = handle_request
        do_POST = handle_request
        do_PATCH = handle_request
        do_HEAD = handle_request
        do_PUT = handle_request
        do_DELETE = handle_request
        do_OPTIONS = handle_request
        do_TRACE = handle_request

        def send_error(self, code, message=None, explain=None):
            # Do not reflect parser diagnostics, request paths, or credentials.
            origin = getattr(self, 'headers', {}).get('Origin')
            if origin is not None and origin not in ORIGINS:
                return self.respond(403, {'error': 'forbidden_origin'})
            if code == 501:
                return self.respond(405, {'error': 'method_not_allowed'})
            return self.respond(code, {'error': 'invalid_request'})

        def log_message(self, _format, *_args):
            pass

    return ThreadingHTTPServer((host, port), Handler)
