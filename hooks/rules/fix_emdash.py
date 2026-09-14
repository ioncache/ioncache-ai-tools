"""Silently rewrites em-dashes in Write/Edit/MultiEdit tool input before the
tool runs; denies Bash instead of rewriting, since inserting a space can
split one shell argument into two. Builds the target character from its
code point, never a literal, so this file itself is never mangled by the
very rule it implements.
"""
import re

EM_DASH = chr(0x2014)
EM_DASH_PATTERN = re.compile(r'\s*' + EM_DASH + r'\s*')
REPLACEMENT = ', '

EVENT = 'PreToolUse'
TOOL_NAMES = ['Bash', 'Write', 'Edit', 'MultiEdit']


def _fix(text):
    return EM_DASH_PATTERN.sub(REPLACEMENT, text)


def _contains_em_dash(text):
    return isinstance(text, str) and EM_DASH in text


def matches(hook_input):
    tool_input = hook_input.get('tool_input') or {}
    tool_name = hook_input.get('tool_name')
    if tool_name == 'Bash':
        return _contains_em_dash(tool_input.get('command'))
    if tool_name == 'Write':
        return _contains_em_dash(tool_input.get('content'))
    if tool_name == 'Edit':
        return _contains_em_dash(tool_input.get('new_string'))
    if tool_name == 'MultiEdit':
        return any(_contains_em_dash(edit.get('new_string')) for edit in tool_input.get('edits') or [])
    return False


def check(hook_input):
    tool_name = hook_input.get('tool_name')
    if tool_name == 'Bash':
        return {
            'action': 'deny',
            'message': (
                'This Bash command contains an em-dash. Rewriting it automatically '
                'would insert a space, which can split one shell argument into two '
                '(e.g. `rm -- foo' + EM_DASH + 'bar` becoming two arguments). '
                'Rewrite the command yourself using a comma, period, parentheses, '
                'or colon instead, then resubmit it.'
            ),
        }

    tool_input = dict(hook_input.get('tool_input') or {})
    if tool_name == 'Write':
        tool_input['content'] = _fix(tool_input.get('content'))
    elif tool_name == 'Edit':
        tool_input['new_string'] = _fix(tool_input.get('new_string'))
    elif tool_name == 'MultiEdit':
        tool_input['edits'] = [
            {**edit, 'new_string': _fix(edit.get('new_string'))} if _contains_em_dash(edit.get('new_string')) else edit
            for edit in tool_input.get('edits') or []
        ]
    return {
        'action': 'rewrite',
        'updatedInput': tool_input,
        'systemMessage': 'Auto-fixed em-dash(es) in tool input before execution.',
    }
