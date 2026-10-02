#!/usr/bin/env python3
"""Evidence reader, review inventory, and native hook checkpoint entry point."""
import argparse
import json
import os
from pathlib import Path
import shlex
import signal
import sqlite3
import sys

from evidence_review import checked_reference, check_review, guarded_request, inventory, review_metadata_request
from evidence_source import PAGE_CHARACTERS, check_native_read, digest, encoded, read_page, source_snapshot, unit_bounds
from evidence_store import EvidenceStore, record_page, reference_key
from rule_engine import get_disabled_rule_ids

RULE_ID = 'claim-evidence'
HELPER = Path(__file__).resolve()
READ_TOOLS = {'Read'}
RESET_EVENTS = {'PreCompact', 'SessionStart', 'SessionEnd', 'SubagentStart'}


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('action', choices=('units', 'read', 'prepare', 'approve'))
    result.add_argument('path')
    result.add_argument('--unit', default='file')
    result.add_argument('--page', type=int, default=1)
    result.add_argument('--sha256')
    result.add_argument('--review')
    return result


def load_document(path):
    return json.loads(source_snapshot(path)['text'])


def helper_call(data):
    if data.get('tool_name') != 'Bash':
        return None
    command = data['tool_input'].get('command', '')
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if len(tokens) < 3 or Path(tokens[0]).name not in ('python', 'python3', Path(sys.executable).name):
        return None
    if (Path(data['cwd']) / tokens[1]).resolve() != HELPER:
        return None
    if any(character in command for character in (';', '&', '|', '>', '<', '`', '$', '\n')):
        raise ValueError('run the evidence helper as a standalone command without redirection')
    if data['tool_input'].get('run_in_background') or data['tool_input'].get('mode') == 'async':
        raise ValueError('evidence helper calls must finish in the foreground')
    return parser().parse_args(tokens[2:])


def protocol_output(event, message):
    if event == 'PreToolUse':
        return {'hookSpecificOutput': {
            'hookEventName': event, 'permissionDecision': 'deny',
            'permissionDecisionReason': message,
        }}
    if event == 'Stop':
        return {'decision': 'block', 'reason': message}
    return {'hookSpecificOutput': {'hookEventName': event, 'additionalContext': message}}


def pending_key(data):
    return digest(encoded([data.get('tool_use_id'), data['tool_name'], data['tool_input']]))


def approval_candidate(options, cwd):
    if not options.review:
        raise ValueError('approve requires --review')
    prepared = inventory(load_document(Path(cwd) / options.path), cwd)
    review = load_document(Path(cwd) / options.review)
    output = 'CLAIM_EVIDENCE_REVIEW ' + encoded({
        'fingerprint': prepared['fingerprint'], 'review_sha256': digest(encoded(review)),
    })
    return prepared, review, output


def prepare_page(options, cwd):
    path = str((Path(cwd) / options.path).resolve())
    prepared = inventory(load_document(path), cwd)
    text = json.dumps(prepared, ensure_ascii=False, indent=2)
    pages = max(1, (len(text) + PAGE_CHARACTERS - 1) // PAGE_CHARACTERS)
    if not 1 <= options.page <= pages:
        raise ValueError(f'inventory page must be between 1 and {pages}')
    if options.sha256 and options.sha256 != prepared['fingerprint']:
        raise ValueError('inventory changed; restart preparation with its current fingerprint')
    offset = (options.page - 1) * PAGE_CHARACTERS
    record = {
        'path': path, 'sha256': prepared['fingerprint'], 'unit': 'inventory',
        'page': options.page, 'pages': pages, 'content': text[offset:offset + PAGE_CHARACTERS],
    }
    return record, 'CLAIM_EVIDENCE_INVENTORY ' + json.dumps(record, ensure_ascii=False, sort_keys=True)


def check_inventory_delivery(options, prepared, store):
    reference = {
        'path': str((Path(prepared['cwd']) / options.path).resolve()),
        'sha256': prepared['fingerprint'], 'unit': 'inventory',
    }
    if not store.get('coverage', reference_key(reference)):
        raise ValueError('prepare every inventory page before submitting its review')


def save_request(prepared, store):
    path = store.request_path(prepared['fingerprint'])
    descriptor = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write(encoded(prepared['request']))
    return path


def checkpoint(prepared, store):
    receipt = store.get('approvals', prepared['fingerprint'])
    if receipt is None:
        path = save_request(prepared, store)
        raise ValueError(
            'checkpoint required for this exact outgoing content. Load the claim-evidence skill; '
            f'prepare request {path}, review every outgoing line, then approve its evidence record'
        )
    context = {'cwd': prepared['cwd'], 'store': store}
    for reference in receipt['references']:
        checked_reference(reference, context)


def before_tool(data, store):
    options = helper_call(data)
    if options:
        path = str((Path(data['cwd']) / options.path).resolve())
        options.path = path
        if options.action == 'read':
            record, output = read_page(options)
            store.put('pending', (pending_key(data), {'page': record, 'output': output}))
        elif options.action == 'prepare':
            record, output = prepare_page(options, data['cwd'])
            store.put('pending', (pending_key(data), {'page': record, 'output': output}))
        elif options.action == 'approve':
            prepared, review, output = approval_candidate(options, data['cwd'])
            check_inventory_delivery(options, prepared, store)
            check_review(review, prepared, {'cwd': data['cwd'], 'store': store})
            store.put('pending', (pending_key(data), {'output': output}))
        return
    if data['tool_name'] in READ_TOOLS:
        check_native_read(data['tool_input'], data['cwd'])
    if review_metadata_request(data, store):
        return
    if guarded_request(data['tool_name'], data['tool_input']):
        checkpoint(inventory(data, data['cwd']), store)


def result_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return '\n'.join(result_text(item) or '' for item in value)
    if not isinstance(value, dict):
        return None
    for key in ('textResultForLlm', 'stdout', 'text', 'content'):
        if key in value:
            return result_text(value[key])
    return None


def after_tool(data, store):
    options = helper_call(data)
    if not options or options.action not in ('read', 'prepare', 'approve'):
        return None
    key = pending_key(data)
    pending = store.get('pending', key)
    store.remove('pending', key)
    if not pending:
        raise ValueError('no matching pre-tool candidate; repeat the evidence helper call')
    text = result_text(data.get('tool_response'))
    if text is None or pending['output'] not in text.split('\n'):
        raise ValueError('evidence page was not delivered intact; repeat the standalone reader call')
    if options.action == 'approve':
        prepared, review, output = approval_candidate(options, data['cwd'])
        if output != pending['output']:
            raise ValueError('review or outgoing artifacts changed during approval')
        refs = check_review(review, prepared, {'cwd': data['cwd'], 'store': store})
        store.put('approvals', (prepared['fingerprint'], {'references': refs, 'review': review}))
        return protocol_output('PostToolUse', 'Claim evidence checkpoint recorded for this exact request.')
    page = pending['page']
    current = (
        prepare_page(options, data['cwd'])[0]['sha256'] if options.action == 'prepare'
        else source_snapshot(page['path'])['sha256']
    )
    if current != page['sha256']:
        raise ValueError('source changed during delivery; restart the logical read')
    complete = record_page(store, page)
    status = 'complete' if complete else 'incomplete'
    return protocol_output('PostToolUse', f'Claim evidence: {page["path"]} unit {page["unit"]} coverage {status}.')


def after_batch(data, store):
    messages = []
    for call in data['tool_calls']:
        try:
            output = after_tool({**data, **call}, store)
            if output:
                messages.append(output['hookSpecificOutput']['additionalContext'])
        except ValueError as error:
            messages.append(f'Claim evidence: {error}.')
    if messages:
        return protocol_output('PostToolBatch', '\n'.join(messages))
    return None


def check_stop(data, store):
    text = data.get('last_assistant_message')
    if not isinstance(text, str):
        raise ValueError('final response text is unavailable')
    prepared = inventory({'tool_name': 'Answer', 'tool_input': {'text': text}}, data['cwd'])
    try:
        checkpoint(prepared, store)
    except ValueError:
        if store.get('stop-retry', 'active'):
            return {'systemMessage': (
                'Claim evidence: ending after one correction request; final prose is not mechanically verified.'
            )}
        store.put('stop-retry', ('active', True))
        raise
    return None


def dispatch_event(event, context):
    data, store = context
    if event in RESET_EVENTS:
        store.reset()
    elif event == 'PreToolUse':
        before_tool(data, store)
    elif event == 'PostToolUse':
        if data.get('evidence_model_output'):
            return after_tool(data, store)
    elif event == 'PostToolBatch':
        return after_batch(data, store)
    elif event == 'Stop':
        return check_stop(data, store)
    else:
        raise ValueError(f'unsupported evidence event {event}')
    return None


def run_hook(event, data):
    if not isinstance(data, dict) or not isinstance(data.get('cwd'), str):
        raise ValueError('claim evidence hook requires an object with cwd')
    if event in ('PreToolUse', 'PostToolUse'):
        if not isinstance(data.get('tool_name'), str) or not isinstance(data.get('tool_input'), dict):
            raise ValueError('tool hooks require a tool name and an argument object')
    if RULE_ID in get_disabled_rule_ids(data['cwd']):
        with EvidenceStore(data) as store:
            store.reset()
        return None
    if event == 'UserPromptSubmit':
        with EvidenceStore(data) as store:
            store.remove('stop-retry', 'active')
        return protocol_output(event, (
            'Before writing comments, documentation, commit/PR text, or behavioral answers, '
            'load the claim-evidence skill. Reads of files up to 400 lines must be whole-file. '
            'Search snippets are discovery only; use the evidence reader for complete-unit receipts. '
            f'Evidence helper: {HELPER}. Session identity: {data.get("session_id", "unavailable")}.'
        ))
    with EvidenceStore(data) as store:
        try:
            return dispatch_event(event, (data, store))
        except ValueError as error:
            return protocol_output(event, f'Claim evidence: {error}.')


def run_command(options):
    if options.action == 'read':
        print(read_page(options)[1])
    elif options.action == 'units':
        snapshot = source_snapshot(options.path)
        print(encoded({
            'path': snapshot['path'], 'sha256': snapshot['sha256'],
            'units': unit_bounds(snapshot),
        }))
    elif options.action == 'prepare':
        print(prepare_page(options, str(Path.cwd()))[1])
    else:
        print(approval_candidate(options, str(Path.cwd()))[2])


def timeout_handler(signum, frame):
    print('claim-evidence: internal deadline exceeded', file=sys.stderr)
    raise SystemExit(2)


def main():
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(2 if sys.argv[-1:] == ['SessionEnd'] else 4)
    try:
        if len(sys.argv) > 1 and sys.argv[1] == 'hook':
            output = run_hook(sys.argv[2], json.load(sys.stdin))
            if output:
                print(encoded(output))
        else:
            run_command(parser().parse_args())
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as error:
        print(f'claim-evidence: {error}', file=sys.stderr)
        raise SystemExit(2) from error
    finally:
        signal.alarm(0)


if __name__ == '__main__':
    main()
