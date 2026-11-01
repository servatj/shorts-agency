"""Independent application tables; never migrates or seeds AgencyStore tables."""
from contextlib import contextmanager
import sqlite3
import json
from datetime import datetime, UTC

SHORT_DEFAULTS = dict(script='', status='draft', language='es', format='9:16', youtube_url='', preview_url='', thumbnail_url='', youtube_title='', description='', tags=[], channel='', notes='', social_account_id=None)


def now():
    return datetime.now(UTC).isoformat()


class PublishedScriptLocked(Exception):
    """A published short's script cannot be replaced or unlocked."""

    def __init__(self):
        super().__init__('published_script_locked')


class WebStore:
    def __init__(self, path):
        self.path = path
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS web_shorts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, document TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS web_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    short_id INTEGER NOT NULL REFERENCES web_shorts(id), document TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS web_login_limits (
                    client TEXT PRIMARY KEY, attempts INTEGER NOT NULL, started REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS web_sessions (
                    token_hash TEXT PRIMARY KEY, username TEXT NOT NULL,
                    csrf_token TEXT NOT NULL, expires_at REAL NOT NULL
                );
            ''')

    @staticmethod
    def short_row(row):
        return {'thumbnail_url': '', **json.loads(row['document']), 'id': row['id']}

    def list_shorts(self):
        with self.connect() as db:
            return [self.short_row(row) for row in db.execute('SELECT * FROM web_shorts ORDER BY id DESC')]

    def get_short(self, short_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM web_shorts WHERE id=?', (short_id,)).fetchone()
        if row is None:
            raise KeyError(short_id)
        return self.short_row(row)

    def create_short(self, fields):
        stamp = now()
        document = {**SHORT_DEFAULTS, **fields, 'created_at': stamp, 'updated_at': stamp}
        with self.connect() as db:
            cursor = db.execute('INSERT INTO web_shorts(document) VALUES (?)', (json.dumps(document),))
            short_id = cursor.lastrowid
        return {**document, 'id': short_id}

    def patch_short(self, short_id, fields):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM web_shorts WHERE id=?', (short_id,)).fetchone()
            if row is None:
                raise KeyError(short_id)
            existing = json.loads(row['document'])
            # Check the fresh row under the write lock, before merging any fields.
            if existing.get('status') == 'published' and (
                ('script' in fields and fields['script'] != existing.get('script', ''))
                or ('status' in fields and fields['status'] != 'published')
            ):
                raise PublishedScriptLocked()
            document = {'thumbnail_url': '', **existing, **fields, 'updated_at': now()}
            db.execute('UPDATE web_shorts SET document=? WHERE id=?', (json.dumps(document), short_id))
        return {**document, 'id': short_id}

    def list_metrics(self, short_id):
        self.get_short(short_id)
        with self.connect() as db:
            return [{**json.loads(row['document']), 'id': row['id'], 'short_id': row['short_id']} for row in db.execute('SELECT * FROM web_metrics WHERE short_id=? ORDER BY id', (short_id,))]

    def append_metric(self, short_id, fields):
        self.get_short(short_id)
        stamp = now()
        document = {**fields, 'created_at': stamp, 'updated_at': stamp}
        with self.connect() as db:
            cursor = db.execute('INSERT INTO web_metrics(short_id, document) VALUES (?, ?)', (short_id, json.dumps(document)))
            metric_id = cursor.lastrowid
        return {**document, 'id': metric_id, 'short_id': short_id}

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()
