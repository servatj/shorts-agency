"""Credential and URL configuration. Importing does not read credentials."""
from dataclasses import dataclass, field
import ipaddress
import os
from pathlib import Path
import re
from urllib.parse import urlsplit


def loopback(host):
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == 'localhost'


def safe_url(value):
    try:
        u = urlsplit(value)
        if (not u.hostname or u.username is not None or u.password is not None
            or u.query or u.fragment or '?' in value or '#' in value
            or '\\' in value or any(ord(c) <= 32 or ord(c) == 127 for c in value)
            or u.scheme not in ('http', 'https')
            or (u.scheme == 'http' and not loopback(u.hostname))):
            raise ValueError()
        u.port
        return u
    except (ValueError, TypeError):
        raise ValueError('invalid_endpoint_configuration') from None


def credential(env, name, required=True):
    path = env.get(name + '_FILE')
    try:
        token = Path(path).read_text().strip() if path else env.get(name, '')
    except (OSError, UnicodeError):
        raise ValueError('credential_file_unavailable') from None
    if not token and not required:
        return ''
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_~.+/=-]{32,4096}', token) or len(set(token)) < 8:
        raise ValueError('missing_or_weak_credential')
    return token


@dataclass(frozen=True)
class Config:
    api_base_url: str
    api_token: str = field(repr=False)
    mcp_token: str = field(default='', repr=False)
    allowed_hosts: tuple[str, ...] = ('127.0.0.1:8766', 'localhost:8766', '[::1]:8766')
    allowed_origins: tuple[str, ...] = ()

    @classmethod
    def from_env(cls, env=None, transport='http', port=8766):
        env = os.environ if env is None else env
        base = env.get('SHORTS_API_BASE_URL', 'http://127.0.0.1:8765').rstrip('/')
        safe_url(base)
        api = credential(env, 'SHORTS_API_TOKEN')
        incoming = credential(env, 'SHORTS_MCP_TOKEN', required=transport == 'http')
        if incoming and incoming == api:
            raise ValueError('credentials_must_be_separate')
        hosts = {f'127.0.0.1:{port}', f'localhost:{port}', f'[::1]:{port}'}
        origins = set()
        public = env.get('SHORTS_MCP_PUBLIC_URL')
        if public:
            u = safe_url(public)
            if u.path not in ('', '/', '/mcp'):
                raise ValueError('invalid_public_path')
            hosts.add(u.netloc)
            origins.add(f'{u.scheme}://{u.netloc}')
        for value in filter(None, env.get('SHORTS_MCP_ALLOWED_HOSTS', '').split(',')):
            if value != value.strip() or '*' in value or '/' in value:
                raise ValueError('invalid_allowed_host')
            u = urlsplit('https://' + value)
            if not u.hostname or u.username or u.password or u.query or u.fragment or u.netloc != value:
                raise ValueError('invalid_allowed_host')
            u.port
            hosts.add(value)
        for value in filter(None, env.get('SHORTS_MCP_ALLOWED_ORIGINS', '').split(',')):
            u = safe_url(value)
            if '*' in value or u.path or value != f'{u.scheme}://{u.netloc}':
                raise ValueError('invalid_allowed_origin')
            origins.add(value)
        return cls(base, api, incoming, tuple(sorted(hosts)), tuple(sorted(origins)))
