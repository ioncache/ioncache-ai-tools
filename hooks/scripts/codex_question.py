"""Identify a directly user-started Codex turn without inheriting delegated work."""
import json
import re

from classify_question import has_question, is_root
from question_history import history_tail

HOST_CONTEXT_KINDS = {'environments.environment_context', 'skills.selected_skill_instructions'}
SKILL_NAME = re.compile(r'<skill>\n<name>([^<\n]+)</name>\n')
LEADING_MENTION = re.compile(r'\s*(?:\[\$([A-Za-z0-9_:-]+)\]\([^)]*\)|\$([A-Za-z0-9_:-]+))')


def user_turn(payload, turn_id):
    origin = payload.get('turn_attribution')
    return (payload.get('turn_id') == turn_id and isinstance(origin, dict)
            and origin.get('turn_id') == turn_id and origin.get('turn_trigger') == 'user'
            and origin.get('parent_turn_id') is None
            and origin.get('initiating_agent_path') is None
            and origin.get('root_turn_id') == turn_id)


def message_text(payload):
    content = payload.get('content')
    if not isinstance(content, list) or not content or not all(
        isinstance(item, dict) and item.get('type') == 'input_text'
        and isinstance(item.get('text'), str) for item in content
    ):
        return None
    return '\n'.join(item['text'] for item in content)


def item_kinds(payload, turn_id):
    metadata = payload.get('internal_chat_message_metadata_passthrough')
    if not isinstance(metadata, dict) or metadata.get('turn_id') != turn_id:
        return None
    kinds = metadata.get('content_item_kinds')
    return kinds if isinstance(kinds, list) else None


def host_context_skills(payload, turn_id):
    """Return injected skill names for host context, or None for possible user input."""
    kinds = item_kinds(payload, turn_id)
    text = message_text(payload)
    if not kinds or text is None or not all(kind in HOST_CONTEXT_KINDS for kind in kinds):
        return None
    return set(SKILL_NAME.findall(text))


def user_text(payload, turn_id):
    if item_kinds(payload, turn_id) != ['user.text']:
        return None
    return message_text(payload)


def invokes_skill(text, skills):
    match = LEADING_MENTION.match(text)
    return match is not None and (match.group(1) or match.group(2)) in skills


def question_from_events(lines, data):
    """Return None when no turn boundary establishes the question state."""
    active = None
    text = None
    authored = False
    skills = set()
    for line in lines:
        event = json.loads(line)
        if not isinstance(event, dict) or not isinstance(event.get('payload'), dict):
            raise ValueError('invalid native question event')
        payload = event['payload']
        if event.get('type') == 'session_meta' and payload.get('id') != data['session_id']:
            return False
        if event.get('type') == 'event_msg':
            if payload.get('type') == 'task_started':
                active = user_turn(payload, data['turn_id'])
                text = None
                authored = False
                skills = set()
            elif (payload.get('type') in ('task_complete', 'turn_aborted')
                  and payload.get('turn_id') == data['turn_id']):
                active = False
        if (not active or event.get('type') != 'response_item'
                or payload.get('type') != 'message' or payload.get('role') != 'user'):
            continue
        injected = host_context_skills(payload, data['turn_id'])
        if injected is not None:
            skills |= injected
        elif authored:
            active = False
        else:
            authored = True
            text = user_text(payload, data['turn_id'])
    return (active and text is not None and not invokes_skill(text, skills)
            and has_question(text))


def question_turn(data):
    if not is_root(data) or data.get('agent_type'):
        return False
    if not data.get('turn_id') or not data.get('transcript_path'):
        return False
    try:
        lines, truncated = history_tail(data['transcript_path'])
    except FileNotFoundError:
        return False
    result = question_from_events(lines, data)
    if result is None and truncated:
        raise ValueError('current turn exceeds the native question history budget')
    return result is True
