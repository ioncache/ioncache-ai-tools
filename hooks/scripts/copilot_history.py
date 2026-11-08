"""Recover bounded dialogue from the native transcript supplied by Copilot Stop."""
import json
import os
from pathlib import Path
import stat
import time

MAX_RECOVERY_CHARS = 48_000
MAX_TRANSCRIPT_BYTES = 64 * 1024 * 1024
MAX_EVENT_BYTES = 8 * 1024 * 1024


class HistoryUnavailable(ValueError):
    pass


class Dialogue:
    def __init__(self, session):
        self.session = session
        self.initialized = False
        self.items = []
        self.size = 2
        self.request = 0
        self.pending = {}
        self.seen = set()

    def append(self, item):
        self.size += len(json.dumps(item)) + 2
        if self.size > MAX_RECOVERY_CHARS:
            raise HistoryUnavailable('Native dialogue exceeds its recovery budget.')
        self.items.append(item)

    def consume(self, event):
        kind, data = event.get('type'), event.get('data')
        if not isinstance(data, dict):
            raise HistoryUnavailable('Native event data is incomplete.')
        if not self.initialized:
            if (kind != 'session.start' or data.get('sessionId') != self.session
                    or data.get('version') != 1 or data.get('producer') != 'copilot-agent'):
                raise HistoryUnavailable('Native session identity or format is unsupported.')
            self.initialized = True
            return
        if kind == 'session.start':
            raise HistoryUnavailable('Native history contains another session start.')
        if event.get('agentId') or data.get('parentToolCallId'):
            return
        if kind == 'hook.start' and data.get('hookType') == 'userPromptTransformed':
            self.prompt(data.get('input'))
        elif kind == 'user.message':
            self.message(data)
        elif kind == 'tool.execution_start' and data.get('toolName') == 'ask_user':
            self.start(data)
        elif kind == 'tool.execution_complete' and data.get('toolCallId') in self.seen:
            self.complete(data)

    def prompt(self, invocation):
        if (not isinstance(invocation, dict) or invocation.get('sessionId') != self.session
                or not isinstance(invocation.get('prompt'), str)):
            raise HistoryUnavailable('Native prompt provenance is incomplete.')
        self.request += 1
        self.append({'kind': 'request', 'text': invocation['prompt']})

    def message(self, data):
        self.request += 1
        text = data.get('content')
        if not isinstance(text, str):
            raise HistoryUnavailable('Native message text is missing.')
        if not text or (self.items and self.items[-1] == {'kind': 'request', 'text': text}):
            return
        self.append({'kind': 'unverified_message', 'text': text})

    def start(self, data):
        if data.get('mcpServerName') or data.get('mcpToolName'):
            return
        identity, args = data.get('toolCallId'), data.get('arguments')
        if (not isinstance(identity, str) or not identity or identity in self.seen
                or not isinstance(args, dict) or not isinstance(args.get('message'), str)):
            raise HistoryUnavailable('Native question-tool provenance is incomplete or ambiguous.')
        if len(self.seen) >= 128 or len(json.dumps(args)) > MAX_RECOVERY_CHARS:
            raise HistoryUnavailable('Native question-tool history exceeds its recovery budget.')
        self.seen.add(identity)
        self.pending[identity] = (args, data.get('turnId'), self.request)

    def complete(self, data):
        entry = self.pending.pop(data['toolCallId'], None)
        if entry is None:
            raise HistoryUnavailable('Native question-tool completion is duplicated.')
        args, turn, request = entry
        result = data.get('result', {})
        if type(data.get('success')) is not bool or not isinstance(result, dict):
            raise HistoryUnavailable('Native question-tool outcome is incomplete.')
        text = result.get('detailedContent', result.get('content', ''))
        if not isinstance(text, str) or (data['success'] and 'content' not in result):
            raise HistoryUnavailable('Native question-tool answer is missing.')
        self.append({
            'kind': 'interaction', 'tool': 'ask_user', 'tool_use_id': data['toolCallId'],
            'input': args, 'result': text, 'success': data['success'],
            'correlated': isinstance(turn, str) and turn == data.get('turnId') and request == self.request,
            'truncated': False,
        })


def current_stop(event, data):
    payload = event.get('data', {})
    invocation = payload.get('input')
    return (
        not event.get('agentId') and not payload.get('parentToolCallId')
        and event.get('type') == 'hook.start' and payload.get('hookType') == 'agentStop'
        and isinstance(invocation, dict) and invocation.get('sessionId') == data['sessionId']
        and invocation.get('timestamp') == data['timestamp']
    )


def read_history(stream, data):
    dialogue = Dialogue(data['sessionId'])
    consumed = 0
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        line = stream.readline(MAX_EVENT_BYTES + 1)
        consumed += len(line)
        if not line or not line.endswith(b'\n'):
            raise HistoryUnavailable('Native history does not reach the current Stop event.')
        if consumed > MAX_TRANSCRIPT_BYTES or len(line) > MAX_EVENT_BYTES:
            raise HistoryUnavailable('Native transcript exceeds its recovery budget.')
        event = json.loads(line)
        if not isinstance(event, dict):
            raise HistoryUnavailable('Native event is not an object.')
        dialogue.consume(event)
        if current_stop(event, data):
            if dialogue.pending:
                raise HistoryUnavailable('Native question-tool exchanges are still incomplete.')
            return dialogue.items
    raise HistoryUnavailable('Native history recovery exceeded its time budget.')


def recover_history(data):
    try:
        path = Path(data['transcriptPath'])
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                    or before.st_mode & 0o022 or before.st_size > MAX_TRANSCRIPT_BYTES):
                raise HistoryUnavailable('Native transcript is unsafe or exceeds its recovery budget.')
            dialogue = read_history(stream, data)
            after = path.lstat()
            if (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino) or after.st_size < before.st_size:
                raise HistoryUnavailable('Native transcript was replaced or truncated during recovery.')
        return {'dialogue': dialogue, 'problem': ''}
    except HistoryUnavailable as error:
        return {'dialogue': [], 'problem': str(error)}
    except (OSError, ValueError, TypeError, KeyError):
        return {'dialogue': [], 'problem': 'Native history is unavailable or malformed.'}
