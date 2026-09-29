#!/usr/bin/env python3
"""Translate Copilot CLI events to the existing hooks and their results back."""
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
TRANSCRIPT_WAIT_SECONDS = 2


def shared_input(data):
    session_id = data.get('sessionId')
    if not isinstance(session_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', session_id):
        raise ValueError('missing or invalid Copilot sessionId')
    return {
        'session_id': f'copilot-{session_id}',
        'cwd': data['cwd'],
        'prompt': data.get('prompt', ''),
    }


def run_shared_hooks(event, hook_input):
    """Use the shared manifest as the sole source of hook order and commands."""
    manifest = json.loads((PLUGIN_ROOT / 'hooks' / 'hooks.json').read_text())
    outputs = []
    for group in manifest['hooks'].get(event, []):
        for hook in group['hooks']:
            command = [
                arg.replace('${CLAUDE_PLUGIN_ROOT}', str(PLUGIN_ROOT))
                for arg in shlex.split(hook['command'])
            ]
            result = subprocess.run(
                command, input=json.dumps(hook_input), capture_output=True,
                text=True, cwd=hook_input['cwd'], timeout=hook.get('timeout', 5),
            )
            if result.stderr:
                print(result.stderr, file=sys.stderr, end='')
            if result.returncode:
                raise RuntimeError(f'{Path(command[1]).name} exited with {result.returncode}')
            if result.stdout.strip():
                output = json.loads(result.stdout)
                if not isinstance(output, dict):
                    raise ValueError(f'{Path(command[1]).name} returned a non-object result')
                outputs.append(output)
    return outputs


def transform_prompt(data):
    messages = []
    for output in run_shared_hooks('UserPromptSubmit', shared_input(data)):
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


def patch_inputs(patch):
    """Check patch targets and added text without rewriting matching context."""
    inputs = []
    current = None
    for line in patch.splitlines():
        match = re.match(r'^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$', line)
        if match:
            current = {'file_path': match[1], 'new_string': ''}
            inputs.append(current)
        elif line.startswith('+') and current is not None:
            current['new_string'] += line[1:] + '\n'
    if not inputs:
        raise ValueError('apply_patch input has no recognized file headers')
    return inputs


def normalized_tools(data):
    name = data['toolName']
    args = data['toolArgs']
    if isinstance(args, str) and name != 'apply_patch':
        args = json.loads(args)
    if name == 'apply_patch':
        patch = args if isinstance(args, str) else args.get('input')
        if not isinstance(patch, str):
            raise ValueError('apply_patch input must be a patch string')
        return [('Edit', item) for item in patch_inputs(patch)]
    if not isinstance(args, dict):
        raise ValueError(f'{name} toolArgs must be an object')
    if name in ('bash', 'powershell'):
        return [('Bash', args)]
    if name == 'create' or (name == 'str_replace_editor' and args.get('command') == 'create'):
        return [('Write', {'file_path': args['path'], 'content': args['file_text']})]
    if name == 'edit' or (name == 'str_replace_editor' and args.get('command') in ('str_replace', 'insert')):
        return [('Edit', {'file_path': args['path'], 'new_string': args.get('new_str', '')})]
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
        return None
    if data['toolName'] == 'apply_patch':
        return {
            'permissionDecision': 'deny',
            'permissionDecisionReason': (
                'This patch contains added text that a rule would rewrite. '
                'Remove em-dashes from the added text and resubmit the patch. '
                'Patch context and removed lines must not be auto-rewritten.'
            ),
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


def final_response(data):
    """Wait for this stop invocation to be flushed, never inspect a stale turn."""
    deadline = time.monotonic() + TRANSCRIPT_WAIT_SECONDS
    text = None
    with Path(data['transcriptPath']).open(encoding='utf-8') as transcript:
        while time.monotonic() < deadline:
            position = transcript.tell()
            line = transcript.readline()
            if not line or not line.endswith('\n'):
                transcript.seek(position)
                time.sleep(0.05)
                continue
            event = json.loads(line)
            payload = event.get('data', {})
            if event.get('agentId') or payload.get('parentToolCallId'):
                continue
            kind = event.get('type')
            if kind in ('user.message', 'assistant.turn_start'):
                text = None
            elif kind == 'assistant.message' and not payload.get('toolRequests'):
                text = payload.get('content')
            elif kind == 'hook.start' and payload.get('hookType') == 'agentStop':
                invocation = payload.get('input') or {}
                if (invocation.get('sessionId') == data['sessionId']
                        and invocation.get('timestamp') == data['timestamp']):
                    if not isinstance(text, str):
                        raise ValueError('current stop invocation has no final assistant text')
                    return text
    raise TimeoutError('current Copilot stop invocation was not flushed to the transcript')


def run_hook(event, data):
    hook_input = shared_input(data)
    if event == 'userPromptTransformed':
        return transform_prompt(data)
    if event == 'preToolUse':
        return pre_tool_use(data)
    if event == 'agentStop':
        outputs = run_shared_hooks('Stop', {
            **hook_input, 'last_assistant_message': final_response(data),
        })
        return next((output for output in outputs if output.get('decision') == 'block'), None)
    if event == 'sessionEnd':
        Path(f'/tmp/.ioncache-pending-question-{hook_input["session_id"]}').unlink(missing_ok=True)
        return None
    raise ValueError(f'unsupported Copilot event: {event}')


def main():
    try:
        output = run_hook(sys.argv[1], json.load(sys.stdin))
        if output:
            print(json.dumps(output))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.TimeoutExpired) as err:
        print(f'copilot-adapter: {err}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
