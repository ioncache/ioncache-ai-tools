"""Bounded reads of native question provenance, without persistent permission state."""
import os
from pathlib import Path
import stat

MAX_HISTORY_BYTES = 4 * 1024 * 1024


def history_tail(path, max_bytes=MAX_HISTORY_BYTES):
    path = Path(path)
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid():
            raise ValueError('unsafe native question history')
        offset = max(0, before.st_size - max_bytes)
        stream.seek(offset)
        content = stream.read(before.st_size - offset)
        after = path.lstat()
        if ((before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
                or after.st_size < before.st_size or len(content) != before.st_size - offset):
            raise ValueError('native question history changed during reading')
    if content and not content.endswith(b'\n'):
        raise ValueError('native question history has an incomplete event')
    if offset:
        content = content.partition(b'\n')[2]
    return content.decode('utf-8').splitlines(), bool(offset)
