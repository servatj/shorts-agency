"""Direct, non-symlink media files and single HTTP byte ranges."""
from contextlib import contextmanager
import os
import re
import stat

from web_validation import MEDIA_NAME


@contextmanager
def open_media(root, filename):
    if not MEDIA_NAME.fullmatch(filename):
        raise FileNotFoundError()
    directory_fd = None
    file_fd = None
    try:
        directory_fd = os.open(root / 'media', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        file_fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
        if not stat.S_ISREG(os.fstat(file_fd).st_mode):
            raise FileNotFoundError()
        stream = os.fdopen(file_fd, 'rb')
        file_fd = None
    except OSError:
        raise FileNotFoundError() from None
    finally:
        if directory_fd is not None:
            os.close(directory_fd)
        if file_fd is not None:
            os.close(file_fd)
    with stream:
        yield stream, os.fstat(stream.fileno()).st_size


def byte_range(value, size):
    if value is None:
        return 0, size - 1
    match = re.fullmatch(r'bytes=([0-9]{0,20})-([0-9]{0,20})', value)
    if not match or not any(match.groups()) or size == 0:
        raise ValueError('invalid_range')
    first, last = match.groups()
    if first:
        start = int(first)
        end = min(int(last), size - 1) if last else size - 1
    else:
        suffix = int(last)
        if suffix == 0:
            raise ValueError('invalid_range')
        start, end = max(0, size - suffix), size - 1
    if start >= size or start > end:
        raise ValueError('invalid_range')
    return start, end
