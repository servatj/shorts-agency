"""Opaque, expiring database sessions and password verification."""
import hashlib
import hmac
from http.cookies import SimpleCookie, CookieError
import json
import secrets
import time

def allowed_origins():
    """Local development plus one explicit origin; never accept wildcard origins."""
    import os
    from urllib.parse import urlsplit
    origins = {'http://localhost:8765', 'http://127.0.0.1:8765'}
    configured = os.environ.get('SHORTS_AGENCY_ORIGIN', '').strip()
    if configured:
        try:
            url = urlsplit(configured)
            if (url.scheme not in {'http', 'https'} or not url.hostname or
                    url.username is not None or url.password is not None or
                    url.path or url.query or url.fragment or
                    any(c.isspace() or ord(c) < 32 for c in configured) or '\\' in configured):
                raise ValueError()
            url.port
        except ValueError:
            raise ValueError('SHORTS_AGENCY_ORIGIN must be an http(s) origin without path, credentials, query or fragment') from None
        origins.add(configured)
    return frozenset(origins)


ORIGINS = allowed_origins()
COOKIE = 'agency_session'


def equal(left, right):
    return hmac.compare_digest(str(left).encode(), str(right).encode())


class Auth:
    def __init__(self, store, root):
        self.store = store
        self.root = root

    def limited(self, client):
        now = time.time()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM web_login_limits WHERE started <= ?', (now - 300,))
            row = db.execute('SELECT attempts FROM web_login_limits WHERE client=?', (client,)).fetchone()
            if row and row['attempts'] >= 5:
                return True
            db.execute('INSERT INTO web_login_limits VALUES (?, 1, ?) ON CONFLICT(client) DO UPDATE SET attempts=attempts+1', (client, now))
        return False

    def login(self, username, password):
        credentials = json.loads((self.root / 'secrets/admin.json').read_text())
        if credentials['algorithm'] != 'scrypt':
            raise ValueError('Unsupported password algorithm')
        actual = hashlib.scrypt(password.encode('utf-8'), salt=bytes.fromhex(credentials['salt']), n=16384, r=8, p=1, dklen=64).hex()
        if not (equal(actual, credentials['password_hash']) & equal(username, credentials['username'])):
            return None
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.store.connect() as db:
            db.execute('DELETE FROM web_sessions WHERE expires_at <= ?', (time.time(),))
            db.execute('INSERT INTO web_sessions VALUES (?, ?, ?, ?)', (self.hash(token), username, csrf, time.time() + 43200))
        return token, {'user': {'username': username}, 'csrf_token': csrf}

    @staticmethod
    def hash(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def session(self, cookie_header):
        cookie = SimpleCookie()
        try:
            cookie.load(cookie_header or '')
            token = cookie[COOKIE].value
        except (CookieError, KeyError):
            return None
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM web_sessions WHERE token_hash=? AND expires_at>?', (self.hash(token), time.time())).fetchone()
        return dict(row) if row else None

    def logout(self, session):
        with self.store.connect() as db:
            db.execute('DELETE FROM web_sessions WHERE token_hash=?', (session['token_hash'],))


def cookie(value, secure=False, clear=False):
    return f'{COOKIE}={value}; Path=/; HttpOnly; SameSite=Strict; Max-Age={0 if clear else 43200}' + ('; Secure' if secure else '')
