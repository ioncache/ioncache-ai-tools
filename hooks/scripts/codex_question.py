"""Identify a directly user-started Codex turn without inheriting delegated work."""
import json

from classify_question import has_question, is_root
from question_history import history_tail


def user_turn(payload, turn_id):
    origin = payload.get('turn_attribution')
    return (payload.get('turn_id') == turn_id and isinstance(origin, dict)
            and origin.get('turn_id') == turn_id and origin.get('turn_trigger') == 'user'
            and origin.get('parent_turn_id') is None
            and origin.get('initiating_agent_path') is None
            and origin.get('root_turn_id') == turn_id)


def user_text(payload, turn_id):
    metadata = payload.get('internal_chat_message_metadata_passthrough')
    if (not isinstance(metadata, dict) or metadata.get('turn_id') != turn_id
            or metadata.get('content_item_kinds') != ['user.text']):
        return None
    content = payload.get('content')
    if not isinstance(content, list) or not content or not all(
        isinstance(item, dict) and item.get('type') == 'input_text'
        and isinstance(item.get('text'), str) for item in content
    ):
        return None
    return '\n'.join(item['text'] for item in content)


def question_from_events(lines, data):
    """Return None when no turn boundary establishes the question state."""
    active = None
    text = None
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
            elif (payload.get('type') in ('task_complete', 'turn_aborted')
                  and payload.get('turn_id') == data['turn_id']):
                active = False
        if (not active or event.get('type') != 'response_item'
                or payload.get('type') != 'message' or payload.get('role') != 'user'):
            continue
        if text is not None:
            active = False
        else:
            text = user_text(payload, data['turn_id'])
    return active and text is not None and has_question(text)


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
