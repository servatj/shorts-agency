"""Small token-protected local HTTP API for Claude Code and local tools."""

from __future__ import annotations

import hmac
from urllib.parse import parse_qs, urlsplit
from typing import Optional

from agency_store import AgencyStore


class AgencyApi:
    def __init__(self, store: AgencyStore, token: str):
        if not isinstance(token, str) or len(token.strip()) < 8:
            raise ValueError('API token must contain at least eight characters')
        self.store = store
        self.token = token

    def dispatch(self, method: str, path: str, authorization: Optional[str]) -> tuple[int, dict]:
        if not hmac.compare_digest((authorization or '').encode(), f"Bearer {self.token}".encode()):
            return 401, {"error": "unauthorized"}
        if method != "GET":
            return 405, {"error": "method_not_allowed"}
        if path == "/v1/health":
            return 200, {"ok": True}
        if path == "/v1/templates":
            return 200, {"items": self.store.list_templates()}
        if path == "/v1/channels":
            return 200, {"items": self.store.list_channels()}
        if urlsplit(path).path == "/v1/prompts":
            template_id = parse_qs(urlsplit(path).query).get("template_id", [None])[0]
            return 200, {"items": self.store.list_prompt_blocks(template_id)}
        return 404, {"error": "not_found"}


def make_server(store: AgencyStore, token: str) -> AgencyApi:
    return AgencyApi(store, token)


def create_http_server(store, token, host='127.0.0.1', port=8765, *, root=None):
    from web_backend import build_server
    return build_server(make_server(store, token), host, port, root=root)


def serve(store: AgencyStore, token: str, host: str, port: int, *, root=None) -> None:
    with create_http_server(store, token, host, port, root=root) as server:
        server.serve_forever()
