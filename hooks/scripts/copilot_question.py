"""Identify the current local Copilot question from emitted native message evidence."""
import json
import os
from pathlib import Path

from classify_question import has_question
from question_history import history_tail as read_history_tail

MAX_HISTORY_BYTES = 4 * 1024 * 1024


def history_tail(path):
    return read_history_tail(path, MAX_HISTORY_BYTES)


def user_message(data):
    if (data.get('source') not in (None, 'user')
            or data.get('agentAuthored') not in (None, False)
            or data.get('isAutopilotContinuation') not in (None, False)):
        return False
    return isinstance(data.get('content'), str) and data.get('delivery') in ('idle', 'steering', 'queued')


def question_from_events(lines, session_id):
    message = None
    for line in reversed(lines):
        event = json.loads(line)
        if not isinstance(event, dict) or not isinstance(event.get('data'), dict):
            raise ValueError('invalid native question event')
        if event.get('agentId'):
            continue
        data = event['data']
        kind = event.get('type')
        if kind == 'hook.end' and data.get('hookType') == 'agentStop' and message is None:
            return False if data.get('success') is True else None
        if kind == 'user.message':
            if (message is not None and data.get('source') == 'memory' and data.get('content') == ''
                    and data.get('interactionId')
                    and data['interactionId'] == message.get('interactionId')):
                continue
            if message is not None:
                raise ValueError('native user message has no matching prompt hook')
            if not user_message(data):
                return False
            message = data
        if kind != 'hook.start' or data.get('hookType') != 'userPromptTransformed':
            continue
        prompt = data.get('input')
        if not isinstance(prompt, dict):
            raise ValueError('missing native prompt evidence')
        if prompt.get('agentId') or prompt.get('parentAgentId'):
            continue
        if prompt.get('sessionId') != session_id:
            raise ValueError('native prompt belongs to another session')
        if message is None:
            return False
        if not isinstance(prompt.get('prompt'), str) or prompt['prompt'] != message['content']:
            raise ValueError('native prompt and emitted user message do not match')
        return has_question(prompt['prompt'])
    return None


def question_turn(data):
    if data.get('agentId') or data.get('parentAgentId') or data.get('agentType'):
        return False
    home = Path(os.environ.get('COPILOT_HOME') or Path.home() / '.copilot')
    path = home / 'session-state' / data['sessionId'] / 'events.jsonl'
    try:
        lines, truncated = history_tail(path)
    except FileNotFoundError:
        return None
    result = question_from_events(lines, data['sessionId'])
    if result is None and truncated:
        raise ValueError('current prompt exceeds the native question history budget')
    return result
