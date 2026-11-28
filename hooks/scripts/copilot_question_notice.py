"""Deliver question-check warnings without caching question or permission verdicts."""
from contextlib import contextmanager
import errno
import json
import os
from pathlib import Path
import re
import stat
import time

from plugin_config import acquire_lock, enabled, write_atomic

NOTICE = (
    "ioncache-ai-tools couldn't determine whether your message was a question "
    "from the available conversation history. Its extra safeguard against taking "
    "actions while answering questions wasn't applied. Other safeguards still apply."
)
KNOWN_FAILURES = {
    'current prompt exceeds the native question history budget': 'history-budget',
    'unsafe native question history': 'unsafe-history',
    'native question history changed during reading': 'history-changed',
    'native question history has an incomplete event': 'incomplete-event',
    'invalid native question event': 'invalid-event',
    'native user message has no matching prompt hook': 'missing-prompt',
    'missing native prompt evidence': 'missing-evidence',
    'native prompt belongs to another session': 'session-mismatch',
    'native prompt and emitted user message do not match': 'message-mismatch',
}
MAX_STATE_BYTES = 32768


def failure_detail(error):
    if isinstance(error, json.JSONDecodeError):
        return 'invalid-json', 'Native question history contains invalid JSON.'
    if isinstance(error, UnicodeError):
        return 'invalid-encoding', 'Native question history is not valid UTF-8.'
    if isinstance(error, OSError):
        code = errno.errorcode.get(error.errno, 'UNKNOWN')
        return f'history-io-{code.lower()}', f'Native question history could not be read ({code}).'
    message = str(error)
    if message in KNOWN_FAILURES:
        code = KNOWN_FAILURES[message]
        if code == 'history-budget':
            message = 'No current prompt conclusion within the bounded native history window.'
        return code, message
    return 'invalid-evidence', 'Native question evidence could not be interpreted.'


def notice_path(data):
    session = data['sessionId']
    if not isinstance(session, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', session):
        raise ValueError('invalid notice session')
    cache = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache')
    if not cache.is_absolute():
        cache = Path.home() / '.cache'
    return cache.resolve() / 'ioncache-ai-tools/question-notices' / f'copilot-{session}.json'


def private_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise ValueError('unsafe question notice directory')


@contextmanager
def private_file(path, flags):
    descriptor = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or info.st_mode & 0o077):
            raise ValueError('unsafe question notice file')
        yield stream


def read_state(path):
    try:
        with private_file(path, os.O_RDONLY) as stream:
            content = stream.read(MAX_STATE_BYTES + 1)
    except FileNotFoundError:
        return {'notified': [], 'diagnostics': {}}
    if len(content) > MAX_STATE_BYTES:
        raise ValueError('question notice state exceeds its size limit')
    state = json.loads(content)
    if (not isinstance(state, dict) or set(state) != {'notified', 'diagnostics'}
            or not isinstance(state['notified'], list)
            or not all(isinstance(cause, str) for cause in state['notified'])
            or not isinstance(state['diagnostics'], dict)):
        raise ValueError('invalid question notice state')
    return state


def deliver(emit):
    try:
        emit({'userNotice': NOTICE})
    except (OSError, ValueError, TypeError, RuntimeError):
        return False
    return True


def observe(data, error, emit):
    if data.get('agentId') or data.get('parentAgentId') or data.get('agentType'):
        return
    delivered = False
    try:
        if error is not None and not enabled(
                'answer-questions-warning-deduplication', {**data, '_ioncache_harness': 'copilot'}):
            deliver(emit)
            return
        path = notice_path(data)
        if error is None and not path.exists():
            return
        private_directory(path.parent.parent)
        private_directory(path.parent)
        with private_file(path.with_suffix('.lock'), os.O_RDWR | os.O_CREAT) as lock:
            acquire_lock(lock)
            state = read_state(path)
            if error is not None:
                cause, detail = failure_detail(error)
                if cause in state['notified']:
                    return
                delivered = deliver(emit)
                if not delivered:
                    return
                state['notified'].append(cause)
                state['diagnostics'][cause] = {'detail': detail, 'observed_at': time.time()}
            elif state['notified']:
                state['notified'] = []
            else:
                return
            write_atomic(path, json.dumps(state) + '\n')
    except (OSError, ValueError, TypeError, RuntimeError):
        if error is not None and not delivered:
            deliver(emit)
