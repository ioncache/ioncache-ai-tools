#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys

import docs_cache
from docs_cache import DISTILLER_ENV
from hook_adapter_common import ADAPTER_TIMEOUT_SECONDS, PATCH_REWRITE_REASON, InvocationDeadline, invocation_deadline, run_shared_hooks, unavailable
from plugin_config import synchronize


def prompt_submit(data):
    if not isinstance(data.get('prompt'), str):
        raise ValueError('missing or invalid Codex prompt')
    messages = []
    warnings = []
    for output in run_shared_hooks('UserPromptSubmit', data):
        if output.get('systemMessage'):
            warnings.append(output['systemMessage'])
        context = output.get('hookSpecificOutput', {}).get('additionalContext')
        if context:
            messages.append(context)
    if not messages and not warnings:
        return None
    return {
        **({'systemMessage': '\n\n'.join(warnings)} if warnings else {}),
        'hookSpecificOutput': {
            'hookEventName': 'UserPromptSubmit',
            'additionalContext': '\n\n'.join(messages),
        },
    }


def pre_tool_use(data, completed_outputs=None):
    name = data.get('tool_name')
    if not isinstance(name, str) or not name:
        raise ValueError('missing or invalid Codex tool_name')
    args = data['tool_input']
    if name in ('Bash', 'apply_patch'):
        if not isinstance(args, dict) or not isinstance(args.get('command'), str):
            raise ValueError(f'{name} tool_input.command must be a string')
    rewrite = None
    warnings = []
    outputs = run_shared_hooks('PreToolUse', data) if completed_outputs is None else completed_outputs
    for output in outputs:
        if output.get('systemMessage'):
            warnings.append(output['systemMessage'])
        decision = output.get('hookSpecificOutput', {})
        if decision.get('permissionDecision') == 'deny':
            if warnings:
                output = {**output, 'systemMessage': '\n\n'.join(warnings)}
            return output
        if 'updatedInput' in decision and rewrite is None:
            rewrite = output
    if rewrite is not None:
        if name == 'apply_patch':
            return {'hookSpecificOutput': {
                'hookEventName': 'PreToolUse',
                'permissionDecision': 'deny',
                'permissionDecisionReason': PATCH_REWRITE_REASON,
            }}
        # Codex requires allow with updatedInput, unlike Claude's rewrite-only protocol.
        rewrite['hookSpecificOutput']['permissionDecision'] = 'allow'
        if warnings:
            rewrite['systemMessage'] = '\n\n'.join(warnings)
        return rewrite
    output = docs_cache.native_hook('codex', 'PreToolUse', data) if completed_outputs is None else None
    if warnings:
        return {**(output or {}), 'systemMessage': '\n\n'.join(warnings)}
    return output


def run_hook(event, data):
    try:
        with invocation_deadline(2 if event == 'SessionEnd' else ADAPTER_TIMEOUT_SECONDS):
            return dispatch(event, data)
    except InvocationDeadline as error:
        output = None
        if event == 'PreToolUse' and error.outputs:
            output = pre_tool_use(data, error.outputs)
        else:
            output = next((item for item in error.outputs if item.get('decision') == 'block'), None)
        warning = unavailable('codex-adapter', error)['systemMessage']
        output = output or {}
        return {**output, 'systemMessage': '\n\n'.join(filter(None, (output.get('systemMessage'), warning)))}
    except Exception as error:
        return unavailable('codex-adapter', error)


def dispatch(event, data):
    if not isinstance(data, dict):
        raise ValueError('Codex hook input must be an object')
    data = {**data, '_ioncache_harness': 'codex'}
    session_id = data.get('session_id')
    if not isinstance(session_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', session_id):
        raise ValueError('missing or invalid Codex session_id')
    if not isinstance(data.get('cwd'), str) or not data['cwd']:
        raise ValueError('missing or invalid Codex cwd')
    synchronize(data['cwd'], 'codex')
    if event == 'UserPromptSubmit':
        return prompt_submit(data)
    if event == 'PreToolUse':
        return pre_tool_use(data)
    if event in ('PostToolUse', 'SessionStart', 'SessionEnd', 'PreCompact', 'SubagentStart', 'Stop'):
        outputs = run_shared_hooks(event, {**data, 'evidence_model_output': event == 'PostToolUse'})
        blocked = next((output for output in outputs if output.get('decision') == 'block'), None)
        if blocked:
            return blocked
        cache_output = docs_cache.native_hook('codex', event, data)
        if cache_output:
            if cache_output.get('decision') == 'block':
                return cache_output
            outputs.append(cache_output)
        messages = [
            output['hookSpecificOutput']['additionalContext'] for output in outputs
            if output.get('hookSpecificOutput', {}).get('additionalContext')
        ]
        warnings = [output['systemMessage'] for output in outputs if output.get('systemMessage')]
        result = {}
        if messages:
            result['hookSpecificOutput'] = {'hookEventName': event, 'additionalContext': '\n\n'.join(messages)}
        if warnings:
            result['systemMessage'] = '\n\n'.join(warnings)
        return result or None
    raise ValueError(f'unsupported Codex event: {event}')


def main():
    if os.environ.get(DISTILLER_ENV):
        return
    try:
        output = run_hook(sys.argv[1], json.load(sys.stdin))
        if output:
            print(json.dumps(output))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.TimeoutExpired) as err:
        print(json.dumps(unavailable('codex-adapter', err)))


if __name__ == '__main__':
    main()
