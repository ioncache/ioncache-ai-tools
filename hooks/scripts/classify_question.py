#!/usr/bin/env python3
"""Conservative question classification and the compact answer-only contract."""

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

# Words a genuine question typically opens with. Bare "do" is deliberately
# excluded: unlike "does"/"did", it's also the standard imperative-sentence
# auxiliary ("Do not do X", "Do the shell functions too"), and those are far
# more common in practice than a bare "Do ...?" question, so including it
# made every ordinary imperative starting with "do" a false positive.
QUESTION_STARTERS = re.compile(
    r"^\s*(what|why|how|when|where|who|which|is|are|does|did|"
    r"can|could|should|would|will|has|have|was|were)\b",
    re.IGNORECASE,
)

QUESTION_CONTRACT = (
    'Question turn: answer and reasoning only; no unsolicited drafts, plans, '
    'next steps, or actions. A work product belongs only when explicitly '
    'requested by the question. Read-only research remains available.'
)


def marker_path(data, kind='question'):
    if kind not in ('question', 'prompt'):
        raise ValueError('invalid marker kind')
    session = data.get('session_id')
    if not isinstance(session, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', session):
        raise ValueError('invalid question session identity')
    agent = data.get('agent_id')
    if agent and agent != 'root':
        session += '-' + hashlib.sha256(str(agent).encode()).hexdigest()
    return Path(f'/tmp/.ioncache-pending-{kind}-{session}')


def set_marker(data, active, kind='question'):
    path = marker_path(data, kind)
    if not active:
        path.unlink(missing_ok=True)
        return
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError('unsafe question marker')
        return
    os.close(descriptor)


def has_marker(data, kind='question'):
    try:
        marker_path(data, kind).lstat()
        return True
    except FileNotFoundError:
        return False


def has_question(text):
    text = text.strip()

    clauses = [c for c in re.split(r"(?<=[.!?])\s+|\n+", text) if c.strip()]
    if not clauses:
        return False

    return any(
        clause.rstrip().endswith("?") or QUESTION_STARTERS.match(clause)
        for clause in clauses
    )


def main():
    from scope_guard import run_hook

    data = json.load(sys.stdin)
    data.setdefault('cwd', str(Path.cwd()))
    output = run_hook('UserPromptSubmit', data)
    if output:
        print(json.dumps(output))


if __name__ == "__main__":
    main()
