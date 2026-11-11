#!/usr/bin/env python3
"""Claude Code context handoff instead of compaction.

At the configured context threshold, Claude must stop, write a handoff prompt
to a per-session file, and the session halts. After /clear, the next session
receives that handoff. Hooks receive no context usage, so the status line copy
of context_statusline.py records it under CLAUDE_PLUGIN_DATA for these hooks.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time

from plugin_config import enabled

FEATURE = 'context-handoff'
SKILL_NAME = 'context-handoff'
SKILL = 'ioncache-ai-tools:' + SKILL_NAME
THRESHOLD_ENV = 'CLAUDE_PLUGIN_OPTION_HANDOFF_THRESHOLD_PERCENT'
SESSION_ID = re.compile(r'[A-Za-z0-9_-]+')
STATUSLINE_SOURCE = Path(__file__).resolve().with_name('context_statusline.py')
EVENTS = ('SessionStart', 'UserPromptSubmit', 'PreToolUse', 'PostToolUse', 'Stop', 'PreCompact')


def data_dir():
    value = os.environ.get('CLAUDE_PLUGIN_DATA')
    if not value:
        raise RuntimeError('CLAUDE_PLUGIN_DATA is not set for this hook')
    return Path(value)


def session_id(data):
    value = data.get('session_id')
    if not isinstance(value, str) or not SESSION_ID.fullmatch(value):
        raise ValueError('missing or invalid session_id')
    return value


def statusline_path():
    return data_dir() / 'statusline.py'


def handoff_path(data):
    return data_dir() / 'handoffs' / f'{session_id(data)}.md'


def usage_path(data):
    return data_dir() / 'context' / f'{session_id(data)}.json'


def session_path(data):
    return data_dir() / 'sessions' / f'{session_id(data)}.json'


def pending_path(cwd):
    return data_dir() / 'pending' / (hashlib.sha256(cwd.encode()).hexdigest() + '.json')


def write_atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None


def threshold():
    raw = os.environ.get(THRESHOLD_ENV)
    if raw is None:
        raise RuntimeError(f'{THRESHOLD_ENV} is not set for this hook')
    value = float(raw)
    if not 1 <= value <= 99:
        raise ValueError(f'{THRESHOLD_ENV} must be between 1 and 99, got {raw}')
    return value


def applies(data):
    """Claude Code main sessions only; Codex and Copilot adapters mark their input."""
    return not data.get('_ioncache_harness') and not data.get('agent_id') and enabled(FEATURE, data)


def is_handoff_write(data):
    """True for a Write of this session's handoff file, which other guards must allow."""
    if data.get('tool_name') != 'Write' or not SESSION_ID.fullmatch(str(data.get('session_id'))):
        return False
    if not os.environ.get('CLAUDE_PLUGIN_DATA') or not applies(data):
        return False
    target = (data.get('tool_input') or {}).get('file_path')
    if not isinstance(target, str) or not target:
        return False
    return Path(data['cwd'], target).resolve() == handoff_path(data).resolve()


def usage(data):
    state = read_json(usage_path(data))
    if state is None:
        return None
    percent = state['used_percentage']
    if type(percent) not in (int, float):
        raise ValueError(f'invalid used_percentage in {usage_path(data)}')
    return state


def required_handoff(data):
    """The recorded usage when a handoff is due and not yet written, otherwise None."""
    state = usage(data)
    if state is None or state['used_percentage'] < threshold() or handoff_path(data).exists():
        return None
    return state


def instruction(data, state):
    path = handoff_path(data)
    if enabled('skill:' + SKILL_NAME, data):
        how = f'Load the {SKILL} skill and follow it to write the handoff with the Write tool to {path}.'
    else:
        how = (
            'Write a self-contained handoff prompt for a fresh session with no access to this conversation '
            '(goal, worktree path and branch, current task, the commands the new session runs to check '
            'uncommitted changes and test results itself rather than reported results, decisions and why, '
            'every user instruction quoted verbatim, open questions, exact next step) '
            f'with the Write tool to {path}.'
        )
    return (
        f'Context handoff required: context usage is {state["used_percentage"]:g}% of the '
        f'{state["context_window_size"]}-token window, at or above the {threshold():g}% threshold. '
        f'Stop the current work now. {how} Do not use other tools or continue the task; '
        'the session halts once the handoff is saved.'
    )


def statusline_notice(data):
    """Report once per session that the status line is not recording usage."""
    marker = session_path(data)
    state = read_json(marker) or {}
    if not state.get('responded') or state.get('notified') or usage_path(data).exists():
        return None
    write_atomic(marker, json.dumps({**state, 'notified': True}))
    return (
        'ioncache-ai-tools context handoff is inactive: no context usage was recorded for this session, '
        'so the status line is not configured. Run this once in Claude Code: '
        f'/statusline Use the command: python3 "{statusline_path()}"'
    )


def install_statusline():
    """Keep a copy at a path that survives plugin updates, for the user's statusLine setting."""
    source = STATUSLINE_SOURCE.read_text(encoding='utf-8')
    target = statusline_path()
    try:
        if target.read_text(encoding='utf-8') == source:
            return
    except FileNotFoundError:
        pass
    write_atomic(target, source)


def resume_context(data):
    pending = pending_path(data['cwd'])
    record = read_json(pending)
    if record is None:
        return None
    handoff = Path(record['handoff_path'])
    text = handoff.read_text(encoding='utf-8')
    claimed = data_dir() / 'consumed' / f'{session_id(data)}.json'
    claimed.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Only one starting session wins the rename, so a handoff is injected once.
        os.rename(pending, claimed)
    except FileNotFoundError:
        return None
    saved = time.strftime('%Y-%m-%d %H:%M:%S %Z', time.localtime(record['saved_at']))
    return (
        f'This session continues from a context handoff that a previous session saved at {saved} '
        f'to {handoff}. Act on it when the user sends their first message. If the handoff below '
        'appears cut off, read the full file at that path.\n\n'
        f'<handoff>\n{text}\n</handoff>'
    )


def context(event, text):
    return {'hookSpecificOutput': {'hookEventName': event, 'additionalContext': text}} if text else None


def session_start(data):
    install_statusline()
    if data.get('source') in ('clear', 'startup'):
        return context('SessionStart', resume_context(data))
    return None


def user_prompt(data):
    state = required_handoff(data)
    if state:
        return context('UserPromptSubmit', instruction(data, state))
    notice = statusline_notice(data)
    return {'systemMessage': notice} if notice else None


def pre_tool(data):
    state = required_handoff(data)
    if not state or data.get('tool_name') == 'Skill' or is_handoff_write(data):
        return None
    return {'hookSpecificOutput': {
        'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
        'permissionDecisionReason': instruction(data, state),
    }}


def save_pending(data):
    path = handoff_path(data)
    write_atomic(pending_path(data['cwd']), json.dumps({
        'cwd': data['cwd'], 'session_id': session_id(data),
        'handoff_path': str(path), 'saved_at': time.time(),
    }))
    return {
        'continue': False,
        'stopReason': f'Handoff saved to {path}. Type /clear, then send any message to continue in a fresh session.',
    }


def post_tool(data):
    if is_handoff_write(data):
        return save_pending(data)
    state = required_handoff(data)
    if state and data.get('tool_name') != 'Skill':
        return {'decision': 'block', 'reason': instruction(data, state)}
    if state:
        return None
    notice = statusline_notice(data)
    return {'systemMessage': notice} if notice else None


def stop(data):
    marker = session_path(data)
    state = read_json(marker) or {}
    if not state.get('responded'):
        write_atomic(marker, json.dumps({**state, 'responded': True}))
    usage_state = required_handoff(data)
    if not usage_state:
        return None
    # One forced continuation per stop; a repeat stop reaches the user instead of looping.
    if not data.get('stop_hook_active'):
        return {'decision': 'block', 'reason': instruction(data, usage_state)}
    return {'systemMessage': (
        f'Context usage is {usage_state["used_percentage"]:g}%, at or above the handoff threshold, '
        'and no handoff was written. Send any message to have Claude write it, '
        f'or run /{SKILL}.'
    )}


def pre_compact():
    print(
        'Compaction is disabled by ioncache-ai-tools (context-handoff). '
        f'Run /{SKILL} to save a handoff, then /clear and send any message to continue in a fresh '
        'session. To allow compaction again, set "context-handoff": false in '
        '~/.claude/ioncache-ai-tools.local.json.',
        file=sys.stderr,
    )
    sys.exit(2)


def run_hook(event, data):
    if not isinstance(data, dict) or not isinstance(data.get('cwd'), str) or not data['cwd']:
        raise ValueError('missing cwd')
    if not applies(data):
        return None
    if event == 'PreCompact':
        pre_compact()
    return {
        'SessionStart': session_start, 'UserPromptSubmit': user_prompt,
        'PreToolUse': pre_tool, 'PostToolUse': post_tool, 'Stop': stop,
    }[event](data)


def main():
    event = sys.argv[1] if len(sys.argv) > 1 else None
    if event not in EVENTS:
        print(f'context-handoff: unsupported event {event!r}', file=sys.stderr)
        sys.exit(2)
    try:
        output = run_hook(event, json.load(sys.stdin))
    except Exception as error:
        message = f'ioncache-ai-tools context handoff failed: {type(error).__name__}: {error}'
        print(message, file=sys.stderr)
        if event == 'PreCompact':
            sys.exit(2)
        output = {'systemMessage': message}
    if output:
        print(json.dumps(output))


if __name__ == '__main__':
    main()
