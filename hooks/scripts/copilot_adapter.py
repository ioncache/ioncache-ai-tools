#!/usr/bin/env python3
"""Translate Copilot CLI events to the existing hooks and their results back."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import docs_cache
from copilot_history import recover_history
from classify_question import set_marker
from docs_cache import DISTILLER_ENV
from hook_adapter_common import PATCH_REWRITE_REASON, run_shared_hooks
from plugin_config import enabled, synchronize
from scope_guard import CATEGORY, MAX_RESPONSE_CHARS, prompt_pending, retain_recent_messages, store_for

TRANSCRIPT_WAIT_SECONDS = 2


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
    hook_input['_prompt_was_pending'] = prompt_pending(hook_input)
    set_marker(hook_input, True, 'prompt')
    messages = []
    for output in run_shared_hooks('UserPromptSubmit', hook_input):
        context = output.get('hookSpecificOutput', {}).get('additionalContext')
        if context:
            messages.append(context)
    set_marker(hook_input, False, 'prompt')
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


def pre_tool_use(data):
    hook_input = shared_input(data)
    rewrite = None
    for name, args in normalized_tools(data):
        for output in run_shared_hooks('PreToolUse', {
            **hook_input, 'tool_name': name, 'tool_input': args,
        }):
            decision = output.get('hookSpecificOutput', {})
            if decision.get('permissionDecision') == 'deny':
                return {
                    'permissionDecision': 'deny',
                    'permissionDecisionReason': decision['permissionDecisionReason'],
                }
            if 'updatedInput' in decision:
                rewrite = decision['updatedInput']
    if rewrite is None:
        return docs_cache_hook(docs_cache.copilot_pre, data)
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


def response_context(data):
    """Wait for this stop invocation to be flushed, never inspect a stale turn."""
    deadline = time.monotonic() + TRANSCRIPT_WAIT_SECONDS
    with store_for(shared_input(data)) as store:
        state = store.get(CATEGORY, 'state') or {}
    response = {
        'text': None, 'messages': [], 'complete': False, 'recent_messages': [], 'recent_messages_omitted': False,
        'continuations': state.get('continuations', []), 'stop': data,
    }
    with Path(data['transcriptPath']).open(encoding='utf-8') as transcript:
        while time.monotonic() < deadline:
            position = transcript.tell()
            line = transcript.readline()
            if not line or not line.endswith('\n'):
                transcript.seek(position)
                time.sleep(0.05)
                continue
            output = consume_response_event(response, json.loads(line))
            if output:
                output['_recovery_turn'] = state.get('id')
                if not state.get('history_recovery_disabled') and enabled('approval-recovery', shared_input(data)):
                    output['_recovered_history'] = recover_history(data)
                return output
    raise TimeoutError('current Copilot stop invocation was not flushed to the transcript')


def consume_response_event(response, event):
    payload = event.get('data', {})
    if event.get('agentId') or payload.get('parentToolCallId'):
        return None
    kind = event.get('type')
    if kind == 'user.message':
        response['text'] = None
        if payload.get('content') not in response['continuations']:
            response.update(messages=[], complete=True, recent_messages=[], recent_messages_omitted=False)
    elif kind == 'assistant.turn_start':
        response['text'] = None
    elif kind == 'assistant.message':
        append_response_message(response, payload)
    elif kind == 'session.task_complete':
        summary = payload.get('summary')
        text = summary if isinstance(summary, str) and summary.strip() else None
        append_response_message(response, {'content': text})
    elif kind == 'hook.start' and payload.get('hookType') == 'agentStop':
        invocation = payload.get('input') or {}
        if (invocation.get('sessionId') == response['stop']['sessionId']
                and invocation.get('timestamp') == response['stop']['timestamp']):
            available = isinstance(response['text'], str)
            return {
                'last_assistant_message': response['text'] if available else None,
                '_assistant_messages': response['messages'],
                '_recent_assistant_messages': response['recent_messages'],
                '_recent_messages_omitted': response['recent_messages_omitted'],
                '_response_coverage': 'turn' if response['complete'] and available else 'partial',
            }
    return None


def append_response_message(response, payload):
    content = payload.get('content')
    response['text'] = None if payload.get('toolRequests') else content
    if not isinstance(content, str) or not content:
        return
    response['recent_messages'].append({'text': content, 'truncated': False})
    omitted = retain_recent_messages(response['recent_messages'])
    response['recent_messages_omitted'] |= omitted
    remaining = max(0, MAX_RESPONSE_CHARS - sum(map(len, response['messages'])))
    response['messages'].append(content[:remaining])
    response['complete'] &= len(content) <= remaining
    if len(response['messages']) > 64:
        del response['messages'][64:]
        response['complete'] = False


def final_response(data):
    return response_context(data)['last_assistant_message']


def run_hook(event, data):
    hook_input = shared_input(data)
    synchronize(hook_input['cwd'], 'copilot')
    if event == 'userPromptTransformed':
        return transform_prompt(data)
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
        if not any(enabled(name, hook_input) for name in ('fix_emdash', 'scope-exactly-what-asked', 'answer-questions')):
            user_warning(docs_cache_hook(docs_cache.copilot_stop, data))
            return None
        response = response_context(data)
        outputs = run_shared_hooks('Stop', {
            **hook_input, **response,
        })
        for output in outputs:
            user_warning(output)
        decision = next((output for output in outputs if output.get('decision') == 'block'), None)
        if decision:
            return decision
        user_warning(docs_cache_hook(docs_cache.copilot_stop, {
            **data, 'last_assistant_message': response['last_assistant_message'],
        }))
        return None
    if event == 'sessionEnd':
        Path(f'/tmp/.ioncache-pending-question-{hook_input["session_id"]}').unlink(missing_ok=True)
        run_shared_hooks('SessionEnd', hook_input)
        return None
    if event in ('sessionStart', 'preCompact', 'subagentStart', 'subagentStop'):
        shared_event = {
            'sessionStart': 'SessionStart', 'preCompact': 'PreCompact',
            'subagentStart': 'SubagentStart', 'subagentStop': 'SubagentStop',
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
        print(f'copilot-adapter: {err}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
