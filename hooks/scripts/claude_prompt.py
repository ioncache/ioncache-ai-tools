"""Normalize observed Claude prompt framing without inferring a human author."""
import re

HOST_SEGMENT = re.compile(
    r'^(?:<(?:task-notification|agent-message)(?:[ \t][^>\n]*)?>'
    r'|Another Claude session sent a message:)',
    re.MULTILINE,
)
REMINDER_TAG = re.compile(r'^<(/?)system-reminder>[ \t]*$', re.MULTILINE)


def reminder_end(text, start):
    depth = 1
    for tag in REMINDER_TAG.finditer(text, start):
        depth += -1 if tag[1] else 1
        if depth == 0:
            return tag.end()
    return None


def normalize_prompt(data):
    if data.get('_ioncache_harness', 'claude') != 'claude':
        return data
    text = data.get('prompt')
    if not isinstance(text, str):
        return data
    text = text.lstrip()
    origin = data.get('_ioncache_prompt_origin', 'unknown')
    if HOST_SEGMENT.search(text):
        return {**data, 'prompt': '', '_ioncache_prompt_origin': 'host'}
    pieces = []
    start = 0
    while tag := REMINDER_TAG.search(text, start):
        if tag[1]:
            return {**data, 'prompt': '', '_ioncache_prompt_origin': 'unknown'}
        pieces.append(text[start:tag.start()])
        end = reminder_end(text, tag.end())
        if end is None:
            return {**data, 'prompt': '', '_ioncache_prompt_origin': 'unknown'}
        start = end
    pieces.append(text[start:])
    return {**data, 'prompt': '\n'.join(pieces).strip(), '_ioncache_prompt_origin': origin}
