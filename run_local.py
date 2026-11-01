#!/usr/bin/env python3
"""Run the local Shorts Agency API on loopback only."""

from pathlib import Path

from agency_store import AgencyStore
from api_server import serve

ROOT = Path(__file__).resolve().parent
TOKEN_FILE = ROOT / "secrets" / "api_token"

def main():
    if not TOKEN_FILE.exists():
        raise SystemExit("Missing secrets/api_token. Run bootstrap.py first.")

    token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    if len(token) < 8:
        raise SystemExit("Invalid secrets/api_token. Restore credentials or rerun bootstrap.py after removing the invalid file.")
    import json
    try:
        credentials = json.loads((ROOT / 'secrets/admin.json').read_text(encoding='utf-8'))
        if (credentials['algorithm'] != 'scrypt' or
                not isinstance(credentials['username'], str) or
                not 1 <= len(credentials['username']) <= 1024 or
                len(bytes.fromhex(credentials['salt'])) < 16 or
                len(bytes.fromhex(credentials['password_hash'])) != 64):
            raise ValueError()
    except (OSError, ValueError, KeyError, TypeError):
        raise SystemExit("Missing or invalid secrets/admin.json. Restore credentials or run bootstrap.py; existing files are never overwritten.") from None
    if not (ROOT / 'data/shorts_agency.db').is_file():
        raise SystemExit("Missing local database. Run bootstrap.py first.")
    store = AgencyStore(ROOT / "data" / "shorts_agency.db")
    # Bootstrap owns legacy schema and seed data; web tables initialize in serve.
    serve(store, token, "127.0.0.1", 8765, root=ROOT)


if __name__ == '__main__':
    main()
