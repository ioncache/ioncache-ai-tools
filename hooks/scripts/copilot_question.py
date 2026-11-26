"""Identify the current local Copilot question from emitted native message evidence."""
import json
import os
from pathlib import Path
import re

from classify_question import has_question
from question_history import history_tail as read_history_tail

MAX_HISTORY_BYTES = 4 * 1024 * 1024
SKILL_PREAMBLE = re.compile(
    r'The user explicitly invoked the "(/[^"\s]+)" skill\. Follow its instructions now\.\n\n'
    r'<skill-context name="[^"\n]+">\n'
)
SKILL_CLOSE = '</skill-context>'
SKILL_ARGUMENTS = '\n\nARGUMENTS: '
# Prompt mode delivers a typed command unexpanded; the model then loads the skill.
LEADING_COMMAND = re.compile(r'\s*/[A-Za-z0-9_-]+(?::[A-Za-z0-9_-]+)?(?=\s|$)')


def history_tail(path):
    return read_history_tail(path, MAX_HISTORY_BYTES)


def words(text):
    return ' '.join(text.split())


def skill_prompt_question(prompt, content):
    """Classify a user-invoked skill expansion, or return None for unknown framing.

    A leading invocation is an instruction to run the skill. An inline mention
    keeps the user's own text after the expansion, which is classified normally.
    """
    match = SKILL_PREAMBLE.match(prompt)
    end = prompt.rfind(SKILL_CLOSE)
    if not match or end < match.end():
        return None
    command = match.group(1)
    body = prompt[match.end():end]
    tail = prompt[end + len(SKILL_CLOSE):]
    if not tail.strip():
        typed = content.split(maxsplit=1)
        if not typed or typed[0] != command:
            return None
        arguments = typed[1] if len(typed) > 1 else ''
        if not arguments:
            return False
        marker = body.rfind(SKILL_ARGUMENTS)
        if marker < 0 or words(body[marker + len(SKILL_ARGUMENTS):]) != words(arguments):
            return None
        return False
    if tail.startswith('\n\n') and command in content and words(tail) == words(content):
        return has_question(content)
    return None


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
            if isinstance(data.get('source'), str) and data['source'].startswith('skill-'):
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
        if not isinstance(prompt.get('prompt'), str):
            raise ValueError('missing native prompt evidence')
        if prompt['prompt'] == message['content']:
            return not LEADING_COMMAND.match(prompt['prompt']) and has_question(prompt['prompt'])
        question = skill_prompt_question(prompt['prompt'], message['content'])
        if question is None:
            raise ValueError('native prompt and emitted user message do not match')
        return question
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
