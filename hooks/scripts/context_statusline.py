#!/usr/bin/env python3
"""Claude Code status line that records context usage for context handoff.

The plugin copies this file into its data directory at session start. Status
line commands receive no plugin environment variables, so usage is written
beside this copy, where the context-handoff hooks read it through
CLAUDE_PLUGIN_DATA.
"""
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time

SESSION_ID = re.compile(r'[A-Za-z0-9_-]+')


def write_atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def usage(data):
    window = data['context_window']
    percent = window['used_percentage']
    if percent is not None and (type(percent) not in (int, float) or not 0 <= percent <= 100):
        raise ValueError('invalid context_window.used_percentage')
    return percent, window['context_window_size']


def record(directory, data):
    percent, size = usage(data)
    # Usage is unknown before the first API response; keep the last known value.
    if percent is None:
        return
    session = data['session_id']
    if not isinstance(session, str) or not SESSION_ID.fullmatch(session):
        raise ValueError('invalid session_id')
    write_atomic(directory / f'{session}.json', json.dumps({
        'used_percentage': percent, 'context_window_size': size, 'updated_at': time.time(),
    }))


def render(data):
    percent, _ = usage(data)
    shown = '--' if percent is None else f'{percent:.0f}%'
    return f'[{data["model"]["display_name"]}] ctx {shown}'


def main():
    try:
        data = json.load(sys.stdin)
        record(Path(__file__).absolute().parent / 'context', data)
        print(render(data))
    except Exception as error:
        # The status line is the only place this process can report a failure.
        print(f'context handoff status line error: {type(error).__name__}: {error}')


if __name__ == '__main__':
    main()
