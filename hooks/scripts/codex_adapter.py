#!/usr/bin/env python3
import json
import re
import subprocess
import sys

from hook_adapter_common import PATCH_REWRITE_REASON, patch_inputs, run_shared_hooks


def prompt_submit(data):
    if not isinstance(data.get('prompt'), str):
        raise ValueError('missing or invalid Codex prompt')
    messages = []
    for output in run_shared_hooks('UserPromptSubmit', data):
        context = output.get('hookSpecificOutput', {}).get('additionalContext')
        if context:
            messages.append(context)
    if not messages:
        return None
    return {
        'hookSpecificOutput': {
            'hookEventName': 'UserPromptSubmit',
            'additionalContext': '\n\n'.join(messages),
        },
    }


def normalized_inputs(data):
    name = data.get('tool_name')
    if not isinstance(name, str) or not name:
        raise ValueError('missing or invalid Codex tool_name')
    args = data['tool_input']
    if name in ('Bash', 'apply_patch'):
        if not isinstance(args, dict) or not isinstance(args.get('command'), str):
            raise ValueError(f'{name} tool_input.command must be a string')
    if name != 'apply_patch':
        return [data]
    return [
        {**data, 'tool_name': 'Edit', 'tool_input': item}
        for item in patch_inputs(args['command'])
    ]


def pre_tool_use(data):
    rewrite = None
    for hook_input in normalized_inputs(data):
        for output in run_shared_hooks('PreToolUse', hook_input):
            decision = output.get('hookSpecificOutput', {})
            if decision.get('permissionDecision') == 'deny':
                return output
            if 'updatedInput' in decision and rewrite is None:
                rewrite = output
    if rewrite is not None and data['tool_name'] == 'apply_patch':
        return {
            'hookSpecificOutput': {
                'hookEventName': 'PreToolUse',
                'permissionDecision': 'deny',
                'permissionDecisionReason': PATCH_REWRITE_REASON,
            },
        }
    return rewrite


def run_hook(event, data):
    if not isinstance(data, dict):
        raise ValueError('Codex hook input must be an object')
    session_id = data.get('session_id')
    if not isinstance(session_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', session_id):
        raise ValueError('missing or invalid Codex session_id')
    if not isinstance(data.get('cwd'), str) or not data['cwd']:
        raise ValueError('missing or invalid Codex cwd')
    if event == 'UserPromptSubmit':
        return prompt_submit(data)
    if event == 'PreToolUse':
        return pre_tool_use(data)
    raise ValueError(f'unsupported Codex event: {event}')


def main():
    try:
        output = run_hook(sys.argv[1], json.load(sys.stdin))
        if output:
            print(json.dumps(output))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.TimeoutExpired) as err:
        print(f'codex-adapter: {err}', file=sys.stderr)
        # Codex treats exit 2 as a block; other error exits would fail open.
        sys.exit(2)


if __name__ == '__main__':
    main()
