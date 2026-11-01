"""Strict field allowlists. Stored URLs are never fetched by the server."""
import math
import re
from datetime import datetime
from urllib.parse import parse_qs, urlsplit

MEDIA_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,199}\.(?:mp4|webm)')
TEXT_LIMITS = {'title': 500, 'script': 100000, 'status': 20, 'language': 2, 'format': 4, 'youtube_url': 2048, 'preview_url': 2048, 'thumbnail_url': 4096, 'youtube_title': 500, 'description': 20000, 'channel': 500, 'notes': 20000}


class ValidationError(ValueError):
    pass


def https_url(value):
    if any(ord(char) <= 32 or ord(char) == 127 for char in value) or '\\' in value:
        raise ValidationError('invalid_url')
    try:
        parsed = urlsplit(value)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError()
        parsed.port  # Reject malformed port syntax.
    except ValueError:
        raise ValidationError('invalid_url')
    return parsed


def youtube_url(value):
    parsed = https_url(value)
    if parsed.hostname not in {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be'} or parsed.port not in (None, 443):
        raise ValidationError('invalid_youtube_url')
    video_id = ''
    if parsed.hostname == 'youtu.be':
        video_id = parsed.path[1:]
    elif parsed.path == '/watch':
        ids = parse_qs(parsed.query, keep_blank_values=True).get('v', [])
        if len(ids) == 1:
            video_id = ids[0]
    else:
        match = re.fullmatch(r'/(?:shorts|embed)/([A-Za-z0-9_-]{11})', parsed.path)
        if match:
            video_id = match[1]
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
        raise ValidationError('invalid_youtube_url')


def metric_fields(body):
    integer_fields = {'views', 'likes', 'comments', 'shares'}
    number_fields = {'average_view_duration_seconds', 'retention_percent'}
    if set(body) - (integer_fields | number_fields | {'observed_at', 'source', 'notes'}):
        raise ValidationError('unknown_field')
    observed = body.get('observed_at')
    try:
        if not isinstance(observed, str) or len(observed) > 40 or 'T' not in observed or datetime.fromisoformat(observed).tzinfo is None:
            raise ValueError()
    except ValueError:
        raise ValidationError('invalid_observed_at')
    for key in integer_fields | number_fields:
        value = body.get(key)
        if value is None:
            continue
        if type(value) not in (int, float) or value < 0 or value > 1.7976931348623157e308 or not math.isfinite(value):
            raise ValidationError('invalid_' + key)
        if key in integer_fields and (type(value) is not int or value > 9223372036854775807):
            raise ValidationError('invalid_' + key)
    if body.get('source', 'manual') not in ('manual', 'agent'):
        raise ValidationError('invalid_source')
    if not isinstance(body.get('notes', ''), str) or len(body.get('notes', '')) > 20000:
        raise ValidationError('invalid_notes')
    return {**dict.fromkeys(integer_fields | number_fields), 'source': 'manual', 'notes': '', **body}


def short_fields(body, create=False):
    if set(body) - (set(TEXT_LIMITS) | {'tags', 'social_account_id'}):
        raise ValidationError('unknown_field')
    if create and 'title' not in body:
        raise ValidationError('title_required')
    for key, value in body.items():
        if key == 'social_account_id':
            if value is not None and (not isinstance(value, str) or not 1 <= len(value) <= 500 or '\x00' in value):
                raise ValidationError('invalid_social_account_id')
        elif key == 'tags':
            if not isinstance(value, list) or len(value) > 100 or any(not isinstance(tag, str) or not 1 <= len(tag) <= 100 for tag in value):
                raise ValidationError('invalid_tags')
        elif not isinstance(value, str) or len(value) > TEXT_LIMITS[key] or '\x00' in value:
            raise ValidationError('invalid_' + key)
    if 'title' in body and not body['title'].strip():
        raise ValidationError('title_required')
    for key, choices in {'status': {'draft', 'review', 'ready', 'published'}, 'language': {'es', 'en'}, 'format': {'9:16', '16:9'}}.items():
        if key in body and body[key] not in choices:
            raise ValidationError('invalid_' + key)
    if body.get('youtube_url'):
        youtube_url(body['youtube_url'])
    if body.get('thumbnail_url'):
        https_url(body['thumbnail_url'])
    if body.get('preview_url'):
        value = body['preview_url']
        if not (value.startswith('/media/') and MEDIA_NAME.fullmatch(value[7:])):
            https_url(value)
    return body
