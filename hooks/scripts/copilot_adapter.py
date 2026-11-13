#!/usr/bin/env python3
"""Translate Copilot CLI events to the existing hooks and their results back."""
import json
import os
import re
import subprocess
import sys

import docs_cache
from docs_cache import DISTILLER_ENV
from hook_adapter_common import ADAPTER_TIMEOUT_SECONDS, PATCH_REWRITE_REASON, InvocationDeadline, invocation_deadline, run_shared_hooks, unavailable
from plugin_config import synchronize


def docs_cache_hook(handler, data):
    """Swallow cache faults here: this adapter fails closed, the cache must not."""
    try:
        return handler(data)
    except Exception as err:
        print(f'docs-cache: {err}', file=sys.stderr)
        return None


def shared_input(data):
    session_id = data.get('sessionId')
    if not isinstance(session_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', session_id):
        raise ValueError('missing or invalid Copilot sessionId')
    return {
        '_ioncache_harness': 'copilot',
        'session_id': f'copilot-{session_id}',
        'cwd': data['cwd'],
        'prompt': data.get('prompt', ''),
        'agent_id': data.get('agentId'),
        'parent_agent_id': data.get('parentAgentId'),
        'source': data.get('source'),
        'stop_hook_active': data.get('stop_hook_active', False),
        'transcript_path': data.get('transcriptPath'),
        'tool_use_id': data.get('toolCallId'),
    }


def user_warning(output):
    message = (output or {}).get('systemMessage') or (output or {}).get('userNotice')
    if message:
        print(json.dumps({'type': 'progress', 'message': message}), flush=True)


def transform_prompt(data):
    hook_input = shared_input(data)
    synchronize(hook_input['cwd'], 'copilot')
    messages = []
    for output in run_shared_hooks('UserPromptSubmit', hook_input):
        user_warning(output)
        context = output.get('hookSpecificOutput', {}).get('additionalContext')
        if context:
            messages.append(context)
    if not messages:
        return None
    return {
        'modifiedTransformedPrompt': (
            data['transformedPrompt'] + '\n\n<ioncache-ai-tools>\n'
            + '\n\n'.join(messages) + '\n</ioncache-ai-tools>'
        )
    }


def normalized_tools(data):
    name = data['toolName']
    args = data['toolArgs']
    if isinstance(args, str) and name != 'apply_patch':
        args = json.loads(args)
    if name == 'apply_patch':
        patch = args if isinstance(args, str) else args.get('input')
        if not isinstance(patch, str):
            raise ValueError('apply_patch input must be a patch string')
        return [('apply_patch', {'command': patch})]
    if not isinstance(args, dict):
        raise ValueError(f'{name} toolArgs must be an object')
    if name in ('bash', 'powershell'):
        return [('Bash', args)]
    if name == 'view' or (name == 'str_replace_editor' and args.get('command') == 'view'):
        normalized = {'file_path': args['path']}
        if args.get('view_range') is not None:
            start, end = args['view_range']
            normalized['offset'] = start
            if end != -1:
                normalized['limit'] = end - start + 1
        return [('Read', normalized)]
    if name == 'create' or (name == 'str_replace_editor' and args.get('command') == 'create'):
        return [('Write', {'file_path': args['path'], 'content': args['file_text']})]
    if name == 'edit' or (name == 'str_replace_editor' and args.get('command') in ('str_replace', 'insert')):
        return [('Edit', {
            'file_path': args['path'], 'new_string': args.get('new_str', ''),
            'old_string': args.get('old_str', ''),
            **{key: args[key] for key in ('insert_line', 'replace_all', 'command') if key in args},
        })]
    return [(name, args)]


def pre_tool_use(data, completed_outputs=None):
    hook_input = shared_input(data)
    rewrite = None
    for name, args in normalized_tools(data):
        outputs = run_shared_hooks('PreToolUse', {
            **hook_input, 'tool_name': name, 'tool_input': args,
        }) if completed_outputs is None else completed_outputs
        for output in outputs:
            user_warning(output)
            decision = output.get('hookSpecificOutput', {})
            if decision.get('permissionDecision') == 'deny':
                return {
                    'permissionDecision': 'deny',
                    'permissionDecisionReason': decision['permissionDecisionReason'],
                }
            if 'updatedInput' in decision:
                rewrite = decision['updatedInput']
    if rewrite is None:
        return docs_cache_hook(docs_cache.copilot_pre, data) if completed_outputs is None else None
    if data['toolName'] == 'apply_patch':
        return {
            'permissionDecision': 'deny',
            'permissionDecisionReason': PATCH_REWRITE_REASON,
        }
    original = data['toolArgs']
    modified = dict(json.loads(original) if isinstance(original, str) else original)
    if 'content' in rewrite:
        modified['file_text'] = rewrite['content']
    elif 'new_string' in rewrite:
        modified['new_str'] = rewrite['new_string']
    else:
        raise ValueError('unsupported rule rewrite for Copilot tool')
    # A rewrite must not grant permission that the user's normal policy denies.
    return {'modifiedArgs': modified}


def run_hook(event, data):
    try:
        with invocation_deadline(4 if event == 'sessionEnd' else ADAPTER_TIMEOUT_SECONDS):
            return dispatch(event, data)
    except InvocationDeadline as error:
        user_warning(unavailable('copilot-adapter', error))
        if event == 'preToolUse' and error.outputs:
            return pre_tool_use(data, error.outputs)
        return next((item for item in error.outputs if item.get('decision') == 'block'), None)
    except Exception as error:
        user_warning(unavailable('copilot-adapter', error))
        return None


def dispatch(event, data):
    hook_input = shared_input(data)
    if event == 'userPromptTransformed':
        return transform_prompt(data)
    synchronize(hook_input['cwd'], 'copilot')
    if event == 'preToolUse':
        return pre_tool_use(data)
    if event in ('postToolUse', 'postToolUseFailure'):
        messages = []
        shared_event = 'PostToolUse' if event == 'postToolUse' else 'PostToolUseFailure'
        for name, args in normalized_tools(data):
            for output in run_shared_hooks(shared_event, {
                **hook_input, 'tool_name': name, 'tool_input': args,
                'tool_response': data.get('toolResult', {'error': data.get('error')}),
                'evidence_model_output': True,
            }):
                user_warning(output)
                context = output.get('hookSpecificOutput', {}).get('additionalContext')
                if context:
                    messages.append(context)
        notice = docs_cache_hook(docs_cache.copilot_post, data) if event == 'postToolUse' else None
        user_warning(notice)
        return {'additionalContext': '\n\n'.join(messages)} if messages else None
    if event == 'agentStop':
        outputs = run_shared_hooks('Stop', hook_input)
        for output in outputs:
            user_warning(output)
        decision = next((output for output in outputs if output.get('decision') == 'block'), None)
        if decision:
            return decision
        user_warning(docs_cache_hook(docs_cache.copilot_stop, data))
        return None
    if event == 'sessionEnd':
        run_shared_hooks('SessionEnd', hook_input)
        return None
    if event in ('sessionStart', 'preCompact', 'subagentStart'):
        shared_event = {
            'sessionStart': 'SessionStart', 'preCompact': 'PreCompact',
            'subagentStart': 'SubagentStart',
        }[event]
        outputs = run_shared_hooks(shared_event, {
            **hook_input, 'last_assistant_message': data.get('response'),
        })
        for output in outputs:
            user_warning(output)
            if output.get('decision') == 'block':
                return output
        messages = [item['hookSpecificOutput']['additionalContext'] for item in outputs
                    if item.get('hookSpecificOutput', {}).get('additionalContext')]
        return {'additionalContext': '\n\n'.join(messages)} if messages else None
    raise ValueError(f'unsupported Copilot event: {event}')


def main():
    if os.environ.get(DISTILLER_ENV):
        return
    try:
        output = run_hook(sys.argv[1], json.load(sys.stdin))
        if output:
            print(json.dumps(output))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.TimeoutExpired) as err:
        user_warning(unavailable('copilot-adapter', err))


if __name__ == '__main__':
    main()
