"""Correlate Claude's current prompt with explicitly human-authored transcript input."""
import json
import re

from classify_question import has_question, is_root
from claude_prompt import normalize_prompt
from question_history import history_tail

COMMAND_FRAMING = re.compile(r'\s*<command-(?:message|name)>')
IMAGE_NOTE = re.compile(r'\[Image: original \d+x\d+, displayed at \d+x\d+\.')


def prompt_text(message):
    content = message.get('content')
    if isinstance(content, str):
        return content
    if isinstance(content, list) and content and all(
        isinstance(block, dict) and block.get('type') == 'text'
        and isinstance(block.get('text'), str) for block in content
    ):
        return '\n'.join(block['text'] for block in content)
    return None


def human_question(event, data):
    if (event.get('sessionId') != data['session_id']
            or event.get('isSidechain') is not False or event.get('isMeta')
            or event.get('origin') != {'kind': 'human'}
            or event.get('turnOrigin', 'human') != 'human'
            or event.get('promptId') != data['prompt_id']
            or event.get('turnPromptId', data['prompt_id']) != data['prompt_id']):
        return False
    text = prompt_text(event['message'])
    if text is None or COMMAND_FRAMING.match(text):
        return False
    normalized = normalize_prompt({'prompt': text, '_ioncache_prompt_origin': 'user'})
    return normalized['_ioncache_prompt_origin'] == 'user' and has_question(normalized['prompt'])


def same_prompt_host_content(event, data):
    """Return whether Claude attached tool-loaded skill or image content to this prompt."""
    if not event.get('isMeta') or event.get('promptId') != data['prompt_id']:
        return False
    if event.get('sourceToolUseID'):
        return True
    text = prompt_text(event['message'])
    return text is not None and IMAGE_NOTE.match(text) is not None


def question_from_events(lines, data):
    for line in reversed(lines):
        event = json.loads(line)
        if not isinstance(event, dict):
            raise ValueError('invalid native question event')
        if event.get('isSidechain') or event.get('agentId'):
            continue
        message = event.get('message')
        if not isinstance(message, dict):
            continue
        if event.get('sessionId') != data['session_id']:
            return False
        if event.get('type') == 'assistant' and message.get('stop_reason') == 'end_turn':
            return False
        if event.get('type') != 'user' or message.get('role') != 'user':
            continue
        content = message.get('content')
        if isinstance(content, list) and any(
            isinstance(block, dict) and block.get('type') == 'tool_result' for block in content
        ):
            continue
        if same_prompt_host_content(event, data):
            continue
        return human_question(event, data)
    return None


def question_turn(data):
    if not is_root(data) or data.get('agent_type'):
        return False
    if not data.get('prompt_id') or not data.get('transcript_path'):
        return False
    try:
        lines, truncated = history_tail(data['transcript_path'])
    except FileNotFoundError:
        return False
    result = question_from_events(lines, data)
    if result is None and truncated:
        raise ValueError('current prompt exceeds the native question history budget')
    return result is True
