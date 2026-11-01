#!/usr/bin/env python3
"""Interactive, local-only setup. Existing credentials and records are preserved."""
import getpass
import hashlib
import json
import os
from pathlib import Path
import secrets
import warnings

from agency_store import AgencyStore
from reference_store import ReferenceStore
from web_store import WebStore

ROOT = Path(__file__).resolve().parent


def setup(root=ROOT):
    root = Path(root)
    private = root / 'secrets'
    private.mkdir(parents=True, mode=0o700, exist_ok=True)
    private.chmod(0o700)
    admin_path = private / 'admin.json'
    if not admin_path.exists():
        username = input('Admin username [admin]: ').strip() or 'admin'
        if not 1 <= len(username) <= 1024:
            raise ValueError('Username must contain 1–1024 characters')
        # Refuse getpass fallback rather than risk echoing a secret on a non-TTY.
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            password = getpass.getpass('New admin password (at least 12 characters): ')
            confirmation = getpass.getpass('Confirm admin password: ')
        if not 12 <= len(password) <= 1024:
            raise ValueError('Password must contain 12–1024 characters')
        if password != confirmation:
            raise ValueError('Passwords do not match')
        salt = secrets.token_bytes(32)
        credentials = {'username': username, 'algorithm': 'scrypt', 'salt': salt.hex(),
                       'password_hash': hashlib.scrypt(password.encode('utf-8'), salt=salt,
                                                       n=16384, r=8, p=1, dklen=64).hex()}
        fd = os.open(admin_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(credentials, stream, indent=2)
            stream.write('\n')
    token_path = private / 'api_token'
    if not token_path.exists():
        fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(secrets.token_urlsafe(32) + '\n')
    admin_path.chmod(0o600)
    token_path.chmod(0o600)
    (root / 'data').mkdir(mode=0o700, exist_ok=True)
    (root / 'media').mkdir(mode=0o700, exist_ok=True)
    inventory = root / 'data/social-inventory.json'
    if not inventory.exists():
        with inventory.open('x', encoding='utf-8') as stream:
            json.dump({'accounts': [], 'recorded_at': None}, stream, indent=2)
            stream.write('\n')
    store = AgencyStore(root / 'data/shorts_agency.db')
    # On reruns do not replace customized templates or other existing records.
    if not store.database_path.exists():
        store.initialize()
    WebStore(store.database_path)
    ReferenceStore(store.database_path)


if __name__ == '__main__':
    try:
        setup()
    except (ValueError, OSError, EOFError, getpass.GetPassWarning) as error:
        raise SystemExit(f'Setup failed: {error}') from None
    print('Local setup ready. Credentials remain in secrets/ (never commit them).')
    print('Run: python3 run_local.py')
