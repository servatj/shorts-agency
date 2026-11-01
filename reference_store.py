"""Separate, unseeded reference catalog. No network access or owned-record writes."""
import json
import re
import math
from datetime import datetime, date
from urllib.parse import urlsplit, parse_qs
from web_store import WebStore
from web_validation import ValidationError

TEXT_FIELDS = ('source_id', 'channel_id', 'channel_name', 'channel_url', 'content_type',
               'title', 'url', 'thumbnail_url', 'description', 'summary', 'topic',
               'agent_angle', 'evidence_basis', 'views_text', 'published_at',
               'observed_at', 'raw_source_path', 'notes')
FIELDS = TEXT_FIELDS + ('views', 'views_approximate', 'likes', 'duration_seconds')
TYPES = ('short', 'video', 'live', 'post')
HOSTS = ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be')


def text(value, field, required=False, limit=20000):
    if value is None and not required:
        return
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()) or '\x00' in value:
        raise ValidationError('invalid_' + field)
    try:
        value.encode('utf-8')
    except UnicodeError:
        raise ValidationError('invalid_' + field)


def timestamp(value, field, optional=False):
    if value is None and optional:
        return
    try:
        if optional and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            date.fromisoformat(value)
        elif 'T' not in value or datetime.fromisoformat(value).tzinfo is None:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValidationError('invalid_' + field)


def safe_url(value, kind='content'):
    text(value, 'url', required=True, limit=2048)
    if re.search(r'[\s\\\x00-\x1f\x7f]', value):
        raise ValidationError('invalid_url')
    try:
        url = urlsplit(value)
        hosts = ('i.ytimg.com', 'img.youtube.com', 'i9.ytimg.com', 'yt3.ggpht.com', 'yt3.googleusercontent.com') if kind == 'thumbnail' else HOSTS
        if url.scheme != 'https' or url.hostname not in hosts or url.username or url.password or url.port or url.fragment:
            raise ValueError()
        if kind == 'thumbnail':
            return None
        if kind == 'channel':
            if url.hostname == 'youtu.be' or not re.fullmatch(r'/(?:@?[\w.%~-]+|(?:channel|c|user)/[\w.-]+)(?:/(?:shorts|videos|streams|posts|community|featured))?/?', url.path):
                raise ValueError()
            return None
        query = parse_qs(url.query, keep_blank_values=True)
        if url.hostname == 'youtu.be':
            match = re.fullmatch(r'/([A-Za-z0-9_-]{11})', url.path)
        elif url.path == '/watch' and len(query.get('v', [])) == 1:
            match = re.fullmatch(r'([A-Za-z0-9_-]{11})', query['v'][0])
        else:
            match = re.fullmatch(r'/(?:shorts|live|embed)/([A-Za-z0-9_-]{11})', url.path)
            if not match:
                match = re.fullmatch(r'/post/([A-Za-z0-9_-]{1,200})', url.path)
        if not match:
            raise ValueError()
        return match[1]
    except ValueError:
        raise ValidationError('invalid_url')


def validate_import(payload):
    if not isinstance(payload, dict) or set(payload) != {'items', 'run'}:
        raise ValidationError('items_and_run_required')
    items, run = payload['items'], payload['run']
    if not isinstance(items, list) or len(items) > 100:
        raise ValidationError('invalid_items_max_100')
    run_fields = {'channel_id', 'channel_name', 'source_url', 'canonical_url', 'observed_at', 'status', 'notes', 'counts'}
    if not isinstance(run, dict) or set(run) - run_fields:
        raise ValidationError('invalid_run')
    for field in run_fields - {'counts'}:
        text(run.get(field), field, required=field not in {'notes', 'channel_name'}, limit=20000)
    if run['status'] not in ('partial', 'complete'):
        raise ValidationError('invalid_status')
    timestamp(run['observed_at'], 'observed_at')
    safe_url(run['source_url'], 'channel')
    safe_url(run['canonical_url'], 'channel')
    counts = run.get('counts', {})
    if not isinstance(counts, dict) or len(counts) > 30:
        raise ValidationError('invalid_counts')
    for key, value in counts.items():
        text(key, 'count_key', required=True, limit=100)
        if value is not None and (type(value) is not int or not 0 <= value <= 9007199254740991):
            raise ValidationError('invalid_counts')
    for item in items:
        if not isinstance(item, dict) or set(item) - set(FIELDS):
            raise ValidationError('invalid_reference_fields')
        for field in TEXT_FIELDS:
            text(item.get(field), field, required=field in {'source_id', 'channel_id', 'title', 'url', 'content_type', 'observed_at'})
        if item['channel_id'] != run['channel_id'] or item['content_type'] not in TYPES:
            raise ValidationError('invalid_channel_or_type')
        if safe_url(item['url']) != item['source_id']:
            raise ValidationError('source_id_url_mismatch')
        is_post = urlsplit(item['url']).path.startswith('/post/')
        if is_post != (item['content_type'] == 'post'):
            raise ValidationError('content_type_url_mismatch')
        for field, kind in [('channel_url', 'channel'), ('thumbnail_url', 'thumbnail')]:
            if item.get(field):
                safe_url(item[field], kind)
        timestamp(item['observed_at'], 'observed_at')
        timestamp(item.get('published_at'), 'published_at', optional=True)
        for field in ('views', 'likes'):
            value = item.get(field)
            if value is not None and (type(value) is not int or not 0 <= value <= 9007199254740991):
                raise ValidationError('invalid_' + field)
        if type(item.get('views_approximate', False)) is not bool:
            raise ValidationError('invalid_views_approximate')
        duration = item.get('duration_seconds')
        if duration is not None and (type(duration) not in (int, float) or not 0 <= duration <= 31536000 or not math.isfinite(duration)):
            raise ValidationError('invalid_duration_seconds')
    return items


class ReferenceStore(WebStore):
    def __init__(self, path):
        self.path = path
        with self.connect() as db:
            columns = ', '.join(f'{name} TEXT' for name in TEXT_FIELDS)
            db.execute(f'''CREATE TABLE IF NOT EXISTS external_references (
                id INTEGER PRIMARY KEY AUTOINCREMENT, {columns},
                views INTEGER, views_approximate BOOLEAN NOT NULL DEFAULT 0,
                likes INTEGER, duration_seconds REAL, UNIQUE(source_id),
                CHECK(content_type IN ('short','video','live','post'))
            )''')
            db.execute('''CREATE TABLE IF NOT EXISTS reference_import_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, document TEXT NOT NULL
            )''')

    @staticmethod
    def record(row):
        result = dict(row)
        result['views_approximate'] = bool(result['views_approximate'])
        return result

    def list_references(self, query='', content_type=''):
        if content_type and content_type not in TYPES:
            raise ValidationError('invalid_type')
        with self.connect() as db:
            rows = [self.record(row) for row in db.execute('SELECT * FROM external_references ORDER BY id DESC')]
        return [row for row in rows if (not content_type or row['content_type'] == content_type)
                and (not query or any(query.casefold() in (row[field] or '').casefold() for field in ('title', 'topic')))]

    def status(self):
        with self.connect() as db:
            latest = db.execute('SELECT * FROM reference_import_runs ORDER BY id DESC LIMIT 1').fetchone()
            counts = dict.fromkeys(TYPES, 0)
            counts.update(dict(db.execute('SELECT content_type, COUNT(*) FROM external_references GROUP BY content_type').fetchall()))
        return {'latest_run': {**json.loads(latest['document']), 'id': latest['id']} if latest else None,
                'total': sum(counts.values()), 'counts': counts}

    def get_reference(self, reference_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM external_references WHERE id=?', (reference_id,)).fetchone()
        if row is None:
            raise KeyError(reference_id)
        return self.record(row)

    def import_references(self, payload):
        items = validate_import(payload)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for item in items:
                values = {field: item.get(field) for field in FIELDS}
                values['views_approximate'] = item.get('views_approximate', False)
                values['evidence_basis'] = item.get('evidence_basis') or 'title/description'
                db.execute(f'''INSERT INTO external_references ({','.join(FIELDS)})
                    VALUES ({','.join('?' for _ in FIELDS)})
                    ON CONFLICT(source_id) DO UPDATE SET
                    {','.join(f'{field}=excluded.{field}' for field in FIELDS if field != 'source_id')}
                ''', [values[field] for field in FIELDS])
            db.execute('INSERT INTO reference_import_runs(document) VALUES (?)', (json.dumps(payload['run']),))
            total = db.execute('SELECT COUNT(*) FROM external_references').fetchone()[0]
        return {'imported': len({item['source_id'] for item in items}), 'total': total}
