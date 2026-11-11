"""Silent turn state and bounded evidence-aware checks."""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
import uuid

from block_pending_question import allows_review_metadata, is_mutating
from classify_question import QUESTION_CONTRACT, has_marker, has_question, set_marker
from docs_cache import DISTILLER_ENV, TTL_SECONDS
from evidence_store import EvidenceStore
from rule_engine import get_disabled_rule_ids, load_rules_for_event, run_rules
import turn_review

CATEGORY = 'turn-policy'
MAX_EVIDENCE_CHARS = 32_000
MAX_RESULT_CHARS = 8_000
MAX_INPUT_CHARS = 2_000
MAX_REQUEST_CHARS = 16_000
MAX_HISTORY_CHARS = 12_000
MAX_RESPONSE_CHARS = 16_000
USER_INPUT_TOOLS = {'AskUserQuestion', 'ask_user', 'request_user_input'}
BOOTSTRAP = (
    'This session uses documentation-backed third-party specifics, not recalled '
    'API or CLI behavior. Applicable verified documentation can be reused; '
    'cached summaries establish only the details they contain. Question replies '
    'contain the answer and reasoning, with work products only when requested.'
)
UNVERIFIED = 'Turn check did not verify this response: '
DELEGATION_TOOLS = {
    'Agent', 'Task', 'task', 'spawn_agent', 'run_dynamic_workflow',
    'write_agent', 'send_input', 'resume_agent', 'SendMessage',
}


def store_for(data):
    store = EvidenceStore(data)
    store.agent = json.dumps(['turn-policy', data.get('agent_id') or 'root'])
    return store


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def context(event, text):
    return {'hookSpecificOutput': {'hookEventName': event, 'additionalContext': text}} if text else None


def denial(reason):
    return {'hookSpecificOutput': {
        'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
        'permissionDecisionReason': reason,
    }}


def bootstrap(data, event):
    disabled = get_disabled_rule_ids(data['cwd'])
    rules = load_rules_for_event(Path(__file__).parent.parent / 'rules', 'SessionStart', disabled)
    output = run_rules(rules, 'SessionStart', data) or {}
    policy = output.get('hookSpecificOutput', {}).get('additionalContext', '')
    return context(event, '\n\n'.join(filter(None, (BOOTSTRAP, policy))))


def lifecycle(event, data):
    if event == 'SubagentStart' and not data.get('agent_id'):
        return bootstrap(data, event)
    inherited = None
    if event == 'SubagentStart' and data.get('agent_id'):
        with store_for({**data, 'agent_id': None}) as parent:
            inherited = parent.get(CATEGORY, 'state')
    with store_for(data) as store:
        state = store.get(CATEGORY, 'state') or {}
        if event == 'SessionEnd':
            end_session(store, data)
            return None
        if event == 'PreCompact':
            state['bootstrapped'] = False
            store.put(CATEGORY, ('state', state))
            return None
        if inherited and 'id' in inherited and (
                'id' not in state or state.get('parent_turn') != inherited['id']):
            state = child_state(inherited)
        refresh = data.get('source') in ('compact', 'clear')
        if data.get('source') == 'clear':
            state = {'history_recovery_disabled': True}
            set_marker(data, False)
            set_marker(data, False, 'prompt')
        elif state.get('question'):
            set_marker(data, True)
        if event == 'SessionStart' and data.get('source') == 'resume':
            state.update(observations=[], reviews={})
            store.put(CATEGORY, ('state', state))
        if state.get('bootstrapped') and not refresh:
            return None
        state['bootstrapped'] = True
        store.put(CATEGORY, ('state', state))
    output = bootstrap(data, event)
    if state.get('question'):
        output['hookSpecificOutput']['additionalContext'] += '\n\n' + QUESTION_CONTRACT
    return output


def end_session(store, data):
    rows = store.connection.execute(
        'SELECT agent, value FROM records WHERE category = ? AND key = ?', (CATEGORY, 'state'),
    ).fetchall()
    for agent, value in rows:
        state = json.loads(value)
        state.update(observations=[], reviews={})
        store.connection.execute(
            'UPDATE records SET value = ? WHERE agent = ? AND category = ? AND key = ?',
            (json.dumps(state), agent, CATEGORY, 'state'),
        )
        set_marker({**data, 'agent_id': json.loads(agent)[1]}, False)


def begin_turn(data):
    prompt = data.get('prompt')
    if not isinstance(prompt, str):
        raise ValueError('missing prompt')
    parent = parent_state(data)
    with store_for(data) as store:
        previous = store.get(CATEGORY, 'state') or {}
        if prompt in previous.get('continuations', []):
            if data.get('_prompt_was_pending'):
                raise ValueError('the current user request has not been recorded')
            previous['native_prompt'] = data.get('prompt_id') or data.get('turn_id')
            store.put(CATEGORY, ('state', previous))
            return None
        requests = [*previous.get('requests', []), prompt]
        incomplete = previous.get('request_context_incomplete', False)
        while len(requests) > 1 and sum(map(len, requests)) > MAX_REQUEST_CHARS:
            requests.pop(0)
            incomplete = True
        history, history_incomplete = prior_history(previous)
        if not parent:
            append_recovery(previous, {'kind': 'request', 'text': prompt})
        state = {
            'id': uuid.uuid4().hex, 'prompt': prompt, 'requests': requests,
            'request_context_incomplete': incomplete or history_incomplete,
            'question': has_question(prompt) or bool(parent and parent.get('question')),
            'parent_turn': parent.get('id') if parent else None,
            'mutation': 0, 'observations': [],
            'docs': bounded([item for item in previous.get('docs', [])
                             if time.time() - item['observed_at'] < TTL_SECONDS]),
            'bootstrapped': True, 'continuations': [], 'stop_attempts': 0, 'stop_checks': 0,
            'reviews': {},
            'pending_tools': {}, 'history': history, 'messages': [],
            'messages_truncated': False, 'recent_messages': [], 'recent_messages_omitted': False,
            'native_prompt': data.get('prompt_id') or data.get('turn_id'),
            'user_interactions': previous.get('user_interactions', []),
            'interaction_context_incomplete': previous.get('interaction_context_incomplete', False),
            'hook_decisions': previous.get('hook_decisions', []),
            'command_history': previous.get('command_history', []),
            'command_history_incomplete': previous.get('command_history_incomplete', False),
            'recovered_dialogue': previous.get('recovered_dialogue', []),
            'recovery_problem': previous.get('recovery_problem', ''),
            'history_recovery_disabled': previous.get('history_recovery_disabled', False),
        }
        store.put(CATEGORY, ('state', state))
        set_marker(data, state['question'])
    messages = []
    if not previous.get('bootstrapped'):
        messages.append(bootstrap(data, 'UserPromptSubmit')['hookSpecificOutput']['additionalContext'])
    if state['question']:
        messages.append(QUESTION_CONTRACT)
    return context('UserPromptSubmit', '\n\n'.join(messages))


def prior_history(previous):
    history = list(previous.get('history', []))
    response = previous.get('last_response')
    truncated = previous.get('response_truncated', False)
    if response is None and previous.get('messages'):
        response = '\n\n'.join(item['text'] for item in previous['messages'])
        truncated = previous.get('messages_truncated') or not all(item['final'] for item in previous['messages'])
    if response is not None:
        history.append({
            'request': previous['prompt'], 'response': response, 'truncated': truncated,
            'earlier_messages': previous.get('last_earlier_response', ''),
            'earlier_messages_truncated': previous.get('earlier_response_truncated', False),
            'earlier_messages_omitted': previous.get('earlier_response_omitted', False),
        })
    incomplete = False
    while history and len(json.dumps(history)) > MAX_HISTORY_CHARS:
        history.pop(0)
        incomplete = True
    return history, incomplete


def prompt_pending(data):
    return has_marker(data, 'prompt') or has_marker({**data, 'agent_id': None}, 'prompt')


def parent_state(data):
    if data.get('agent_id') in (None, '', 'root'):
        return None
    with store_for({**data, 'agent_id': None}) as parent:
        return parent.get(CATEGORY, 'state')


def child_state(parent):
    return {
        **parent, 'id': uuid.uuid4().hex, 'observations': [], 'reviews': {},
        'continuations': [], 'stop_attempts': 0, 'stop_checks': 0, 'bootstrapped': False,
        'parent_turn': parent['id'],
        'pending_tools': {}, 'last_response': None,
        'last_earlier_response': [], 'earlier_response_truncated': False, 'earlier_response_omitted': False,
        'messages': [], 'messages_truncated': False, 'recent_messages': [], 'recent_messages_omitted': False,
        'hook_decisions': [],
        'command_history': [], 'command_history_incomplete': False,
    }


def ensure_child_state(data):
    parent = parent_state(data)
    if parent and 'id' in parent:
        with store_for(data) as store:
            if 'id' not in (store.get(CATEGORY, 'state') or {}):
                store.put(CATEGORY, ('state', child_state(parent)))
    return parent


def result_status(data):
    result = data.get('tool_response')
    if data.get('hook_event_name') == 'PostToolUseFailure':
        return False
    if isinstance(result, dict):
        if result.get('isError') or result.get('error') or result.get('interrupted'):
            return False
        if result.get('resultType') == 'failure':
            return False
        for key in ('exit_code', 'exitCode'):
            if key in result:
                return result[key] == 0 if type(result[key]) is int else None
        if data.get('tool_name') == 'WebFetch' and 'code' in result:
            return type(result['code']) is int and 200 <= result['code'] < 300
    if data.get('tool_name') == 'Bash' and data.get('_ioncache_harness') == 'codex':
        return None
    return True


def is_documentation(data):
    name = data.get('tool_name', '').lower()
    if name in ('webfetch', 'web_fetch', 'webrun', 'websearch', 'web_search'):
        return True
    return 'context7' in name and ('query' in name or 'get-library-docs' in name)


def bounded(items):
    while items and len(json.dumps(items)) > MAX_EVIDENCE_CHARS:
        items.pop(0)
    return items


def tool_key(data):
    return str(data.get('tool_use_id') or fingerprint(
        [data['cwd'], data.get('tool_name'), data.get('tool_input')],
    ))


def record_start(data):
    try:
        with store_for(data) as store:
            state = store.get(CATEGORY, 'state')
            if not state or 'id' not in state:
                return
            pending = state.get('pending_tools', {})
            key = tool_key(data)
            entry = {
                'turn': state['id'], 'mutation': state['mutation'],
                'file_snapshot': file_snapshot(data), 'ambiguous': key in pending,
                'invocation': fingerprint([data.get('tool_name'), data.get('tool_input')]),
            }
            state['pending_tools'] = dict([*pending.items()][-63:])
            state['pending_tools'][key] = entry
            store.put(CATEGORY, ('state', state))
    except (OSError, ValueError, sqlite3.Error):
        print('turn-guard: tool start could not be recorded', file=sys.stderr)


def observation(data, state):
    result = json.dumps(data.get('tool_response'), ensure_ascii=True)
    args = data.get('tool_input')
    encoded_args = json.dumps(args, ensure_ascii=True)
    input_truncated = len(encoded_args) > MAX_INPUT_CHARS
    before = state.get('pending_tools', {}).pop(tool_key(data), None)
    snapshot = file_snapshot(data)
    correlated = bool(before and not before['ambiguous'] and before['turn'] == state['id']
                      and before.get('invocation') == fingerprint([data.get('tool_name'), args]))
    fresh = correlated and before['mutation'] == state['mutation']
    unchanged = fresh and (data.get('tool_name') != 'Read'
                           or bool(snapshot and before['file_snapshot'] == snapshot))
    return {
        'tool': data.get('tool_name'),
        'input': {'excerpt': encoded_args[:MAX_INPUT_CHARS]} if input_truncated else args,
        'cwd': data['cwd'], 'turn': state['id'], 'mutation': state['mutation'],
        'observed_at': time.time(), 'success': result_status(data),
        'result': result[:MAX_RESULT_CHARS],
        'truncated': input_truncated or len(result) > MAX_RESULT_CHARS,
        'file_snapshot': snapshot, 'unchanged': unchanged, 'fresh': fresh, 'correlated': correlated,
    }


def record_interaction(state, data, item):
    if data['tool_name'] not in USER_INPUT_TOOLS:
        return
    interaction = {
        key: item[key] for key in ('tool', 'cwd', 'turn', 'observed_at', 'success', 'correlated')
    }
    interaction.update(input=data['tool_input'], result=json.dumps(data.get('tool_response')), truncated=False)
    if len(json.dumps(interaction)) > MAX_REQUEST_CHARS:
        interaction.update(input=item['input'], result=item['result'], truncated=True)
    items = [*state.get('user_interactions', []), interaction]
    count = len(items)
    state['user_interactions'] = bounded(items)
    state['interaction_context_incomplete'] = state.get('interaction_context_incomplete', False) or len(items) < count
    if data.get('agent_id') in (None, '', 'root'):
        append_recovery(state, {'kind': 'interaction', **interaction})


def append_recovery(state, item):
    if not state.get('recovered_dialogue'):
        return
    dialogue = [*state['recovered_dialogue'], item]
    if len(json.dumps(dialogue)) > turn_review.MAX_RECOVERY_CHARS:
        state.update(recovered_dialogue=[], recovery_problem='Recovered dialogue exceeded its retention budget.')
    else:
        state['recovered_dialogue'] = dialogue


def file_snapshot(data):
    if data.get('tool_name') != 'Read' or not data.get('tool_input', {}).get('file_path'):
        return None
    path = Path(data['cwd']) / data['tool_input']['file_path']
    try:
        info = path.stat()
    except OSError:
        return None
    return [str(path.resolve()), info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns, info.st_size]


def current_observations(state):
    items = []
    for item in state['observations']:
        snapshot = item.get('file_snapshot')
        unchanged = item.get('unchanged', False)
        if snapshot:
            data = {'tool_name': 'Read', 'cwd': '/', 'tool_input': {'file_path': snapshot[0]}}
            unchanged = unchanged and file_snapshot(data) == snapshot
        items.append({**item, 'unchanged': unchanged})
    return items


def record_command(state, data, item):
    if data['tool_name'] != 'Bash':
        return
    records = [*state.get('command_history', []), {**item, 'tool_use_id': data.get('tool_use_id')}]
    count = len(records)
    state['command_history'] = bounded(records)
    state['command_history_incomplete'] = state.get('command_history_incomplete', False) or len(records) < count


def record_tool(data):
    ensure_child_state(data)
    with store_for(data) as store:
        state = store.get(CATEGORY, 'state')
        if not state or 'id' not in state:
            return None
        item = observation(data, state)
        record_interaction(state, data, item)
        if is_mutating(data.get('tool_name'), data.get('tool_input')):
            store.put(CATEGORY, ('state', state))
            invalidate_live_state(store)
            state = store.get(CATEGORY, 'state')
            item['mutation'] = state['mutation']
        record_command(state, data, item)
        key = 'docs' if is_documentation(data) else 'observations'
        state[key] = bounded([*state.get(key, []), item])
        store.put(CATEGORY, ('state', state))
    if not state.get('bootstrapped'):
        return lifecycle(data['hook_event_name'], data)
    return None


def invalidate_live_state(store):
    rows = store.connection.execute(
        'SELECT agent, value FROM records WHERE category = ? AND key = ?', (CATEGORY, 'state'),
    ).fetchall()
    for agent, value in rows:
        state = json.loads(value)
        if 'id' not in state:
            continue
        state.update(mutation=state['mutation'] + 1, observations=[], reviews={})
        store.connection.execute(
            'UPDATE records SET value = ? WHERE agent = ? AND category = ? AND key = ?',
            (json.dumps(state), agent, CATEGORY, 'state'),
        )


def record_cache(data, facts, reason):
    with store_for(data) as store:
        state = store.get(CATEGORY, 'state')
        if not state or 'id' not in state:
            return
        item = observation({**data, 'tool_response': reason}, state)
        item['observed_at'] = min(fact['fetched_at'] for fact in facts)
        item['cached_summary'] = True
        state['docs'] = bounded([*state.get('docs', []), item])
        store.put(CATEGORY, ('state', state))


def review_request(data, state, candidate):
    disabled = get_disabled_rule_ids(data['cwd'])
    return turn_review.fit_context({
        'latest_request': state['prompt'], 'request_context': state['requests'][:-1],
        'request_context_incomplete': state.get('request_context_incomplete', False),
        'assistant_context': state.get('history', []),
        'user_interactions': state.get('user_interactions', []),
        'interaction_context_incomplete': state.get('interaction_context_incomplete', False),
        'recovered_dialogue': state.get('recovered_dialogue', []),
        'recovery_problem': state.get('recovery_problem', ''),
        'hook_decisions': state.get('hook_decisions', []) if candidate.get('kind') == 'response' else [],
        'command_history': state.get('command_history', []) if candidate.get('kind') == 'response' else [],
        'command_history_incomplete': (
            candidate.get('kind') == 'response' and state.get('command_history_incomplete', False)
        ),
        'question_only': state['question'],
        'scope': 'scope-exactly-what-asked' not in disabled,
        'live_state': 'verify-state-before-claiming' not in disabled,
        'turn': state['id'], 'mutation': state['mutation'],
        'documentation': [item for item in state['docs']
                          if time.time() - item['observed_at'] < TTL_SECONDS],
        'observations': current_observations(state),
        'candidate': candidate,
    })


def check_candidate(data, state, candidate):
    request = review_request(data, state, candidate)
    key = fingerprint(request)
    if key in state.get('reviews', {}):
        return key, state['reviews'][key]
    try:
        result = turn_review.review(data.get('_ioncache_harness', 'claude'), request)
    except turn_review.ReviewInputTooLarge:
        return key, {'ok': False, 'reason': 'The current request and candidate exceed the review input budget; use smaller changes.'}
    except turn_review.UnsupportedReviewerCLI as error:
        print(f'turn-guard: {error}', file=sys.stderr)
        return key, {'ok': False, 'reason': str(error)}
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f'turn-guard: semantic checker failed ({type(error).__name__})', file=sys.stderr)
        return key, {'ok': False, 'reason': 'The semantic checker is unavailable or returned invalid output.'}
    with store_for(data) as store:
        current = store.get(CATEGORY, 'state')
        if current and 'id' in current and fingerprint(review_request(data, current, candidate)) == key:
            current['reviews'] = dict([*current.get('reviews', {}).items()][-15:])
            current['reviews'][key] = result
            store.put(CATEGORY, ('state', current))
    return key, result


def pre_tool(data):
    mutating = is_mutating(data.get('tool_name'), data.get('tool_input'))
    delegation = data.get('tool_name') in DELEGATION_TOOLS
    if (mutating or delegation) and prompt_pending(data):
        return denial('The current user request was not recorded. Submit the request again before authorizing work.')
    parent = ensure_child_state(data)
    if not mutating and not delegation:
        record_start(data)
        return None
    with store_for(data) as store:
        state = store.get(CATEGORY, 'state')
        if not state or 'id' not in state:
            return None
        native_prompt = data.get('prompt_id') or data.get('turn_id')
        if not parent and state.get('native_prompt') and native_prompt:
            if native_prompt != state['native_prompt']:
                return denial('The current native prompt has not been recorded. Resubmit the request.')
        if parent and parent.get('id') != state.get('parent_turn'):
            return denial('The parent user request changed after this subagent started. New work requires a current assignment.')
    if allows_review_metadata(data):
        record_start(data)
        return None
    if state['question'] and mutating:
        return denial('BLOCKED: classified as a question. This turn is answer-only; read-only research remains available.')
    candidate = {'kind': 'tool', 'tool': data['tool_name'], 'input': data['tool_input']}
    key, result = check_candidate(data, state, candidate)
    if not result['ok']:
        recovery = ''
        if state.get('request_context_incomplete') or state.get('interaction_context_incomplete') or state.get('recovery_problem'):
            recovery = (
                ' If scope or approval is missing, provide the complete scope and authorization '
                'directly in chat; a confirmation tool is not required. Repeating this call grants no permission.'
            )
        return denial('Turn check: ' + result['reason'] + recovery)
    with store_for(data) as store:
        current = store.get(CATEGORY, 'state')
        if not current or 'id' not in current or fingerprint(review_request(data, current, candidate)) != key:
            return denial('Turn evidence changed during review. Retry with the current observations.')
    record_start(data)
    return None


def remember_continuation(data, reason):
    with store_for(data) as store:
        state = store.get(CATEGORY, 'state')
        if state and 'id' in state:
            state['continuations'] = [*state.get('continuations', [])[-7:], reason]
            store.put(CATEGORY, ('state', state))


def record_denial(data, output):
    decision = (output or {}).get('hookSpecificOutput', {})
    if decision.get('permissionDecision') != 'deny':
        return output
    try:
        with store_for(data) as store:
            state = store.get(CATEGORY, 'state')
            if not state or 'id' not in state:
                return output
            args = json.dumps(data['tool_input'])
            reason = decision['permissionDecisionReason']
            item = {
                'turn': state['id'], 'tool': data['tool_name'], 'tool_use_id': data.get('tool_use_id'),
                'input': {'excerpt': args[:MAX_INPUT_CHARS]} if len(args) > MAX_INPUT_CHARS else data['tool_input'],
                'reason': reason[:MAX_RESULT_CHARS], 'observed_at': time.time(),
                'truncated': len(args) > MAX_INPUT_CHARS or len(reason) > MAX_RESULT_CHARS,
            }
            state['hook_decisions'] = bounded([*state.get('hook_decisions', [])[-15:], item])
            store.put(CATEGORY, ('state', state))
    except (OSError, ValueError, sqlite3.Error):
        print('turn-guard: denial evidence could not be recorded', file=sys.stderr)
    return output


def retain_recent_messages(messages, limit=MAX_RESULT_CHARS):
    omitted = False
    while len(messages) > 64 or (len(messages) > 1 and sum(len(item['text']) for item in messages) > limit):
        messages.pop(0)
        omitted = True
    if messages and len(messages[0]['text']) > limit:
        messages[0]['text'] = messages[0]['text'][:limit]
        messages[0]['truncated'] = True
    return omitted


def record_recent_display(state, data):
    messages = state.setdefault('recent_messages', [])
    message = next((item for item in messages if item['id'] == data['message_id']), None)
    if message is None:
        message = {'id': data['message_id'], 'text': '', 'next_index': 0, 'final': False, 'truncated': False}
        messages.append(message)
    message['truncated'] |= data['index'] != message['next_index']
    if data['index'] >= message['next_index']:
        message['text'] += data['delta']
        message.update(next_index=data['index'] + 1, final=data['final'])
    omitted = retain_recent_messages(messages)
    state['recent_messages_omitted'] = state.get('recent_messages_omitted', False) or omitted


def record_display(data):
    if (not isinstance(data.get('message_id'), str) or type(data.get('index')) is not int
            or not isinstance(data.get('delta'), str) or type(data.get('final')) is not bool):
        raise ValueError('invalid display event')
    with store_for(data) as store:
        state = store.get(CATEGORY, 'state')
        if not state or 'id' not in state:
            return None
        if data.get('prompt_id') and state.get('native_prompt') != data['prompt_id']:
            return None
        record_recent_display(state, data)
        messages = state.setdefault('messages', [])
        message = next((item for item in messages if item['id'] == data['message_id']), None)
        if message is None:
            message = {'id': data['message_id'], 'text': '', 'next_index': 0, 'final': False}
            messages.append(message)
        if data['index'] != message['next_index']:
            state['messages_truncated'] = True
        if data['index'] >= message['next_index']:
            remaining = max(0, MAX_RESPONSE_CHARS - sum(len(item['text']) for item in messages))
            message['text'] += data['delta'][:remaining]
            state['messages_truncated'] |= len(data['delta']) > remaining
            message.update(next_index=data['index'] + 1, final=data['final'])
        if len(messages) > 64:
            del messages[64:]
            state['messages_truncated'] = True
        store.put(CATEGORY, ('state', state))
    return None


def response_candidate(data, state, response):
    texts = data.get('_assistant_messages')
    if texts is None:
        texts = [item['text'] for item in state.get('messages', [])]
    complete = data.get('_response_coverage') == 'turn'
    if state.get('messages') and not state.get('messages_truncated'):
        complete |= all(item['final'] for item in state['messages'])
    if state.get('messages_truncated'):
        complete = False
    if texts and texts[-1].rstrip() == response.rstrip():
        texts = texts[:-1]
    elif data.get('_response_coverage') != 'turn':
        complete = False
    joined = '\n\n'.join(texts)
    if len(joined) > MAX_RESPONSE_CHARS:
        joined, complete = joined[:MAX_RESPONSE_CHARS], False
    return {
        'kind': 'response', 'text': response, 'earlier_messages': joined,
        'coverage': 'observed-turn' if complete else 'final-message-or-partial-turn',
    }


def remember_recovery(data, state):
    recovered = data.get('_recovered_history')
    if (data.get('_ioncache_harness') == 'copilot' and data.get('agent_id') in (None, '', 'root')
            and data.get('_recovery_turn') == state.get('id') and isinstance(recovered, dict)
            and not state.get('history_recovery_disabled')):
        state.update(recovered_dialogue=recovered['dialogue'], recovery_problem=recovered['problem'])


def remember_response(data, state, response):
    candidate = response_candidate(data, state, response)
    state['last_response'] = response[:MAX_RESULT_CHARS]
    state['response_truncated'] = len(response) > MAX_RESULT_CHARS
    remaining = MAX_RESULT_CHARS - len(state['last_response'])
    recent = data.get('_recent_assistant_messages', state.get('recent_messages'))
    if recent is None:
        recent = [{'text': candidate['earlier_messages'], 'truncated': candidate['coverage'] != 'observed-turn'}]
    messages = [{'text': item['text'], 'truncated': item.get('truncated', False) or not item.get('final', True)}
                for item in recent]
    if messages and messages[-1]['text'].rstrip() == response.rstrip():
        messages.pop()
    omitted = retain_recent_messages(messages, remaining)
    state['last_earlier_response'] = messages
    state['earlier_response_truncated'] = any(item['truncated'] for item in messages)
    state['earlier_response_omitted'] = (
        omitted or data.get('_recent_messages_omitted', state.get('recent_messages_omitted', False))
        or candidate['coverage'] != 'observed-turn'
    )


def final_verdict(data, state, response):
    if not isinstance(response, str):
        return None, {'ok': False, 'reason': 'The current final response is unavailable.'}
    candidate = response_candidate(data, state, response)
    key = fingerprint(review_request(data, state, candidate))
    if key in state.get('reviews', {}):
        return key, state['reviews'][key]
    with store_for(data) as store:
        current = store.get(CATEGORY, 'state')
        if not current or current.get('id') != state['id']:
            return key, {'ok': False, 'reason': 'The user request changed during review.'}
        if current.get('stop_checks', 0) >= 2:
            return key, {
                'ok': False, 'reason': 'The final-review budget for this turn is exhausted.',
                'budget_exhausted': True,
            }
        current['stop_checks'] = current.get('stop_checks', 0) + 1
        store.put(CATEGORY, ('state', current))
    return check_candidate(data, state, candidate)


def stop(data):
    if prompt_pending(data):
        return {'systemMessage': UNVERIFIED + 'the current user request was not recorded.'}
    ensure_child_state(data)
    response = data.get('last_assistant_message')
    with store_for(data) as store:
        state = store.get(CATEGORY, 'state')
        if state and 'id' in state:
            remember_recovery(data, state)
            if isinstance(response, str):
                remember_response(data, state, response)
            store.put(CATEGORY, ('state', state))
    if not state or 'id' not in state:
        return None
    key, result = final_verdict(data, state, response)
    with store_for(data) as store:
        current = store.get(CATEGORY, 'state')
        if not current or current.get('id') != state['id']:
            return {'systemMessage': UNVERIFIED + 'the active user turn changed during review.'}
        if key and fingerprint(review_request(data, current, response_candidate(data, current, response))) != key:
            result = {'ok': False, 'reason': 'Evidence changed during response review; check the current observations.'}
        current['last_review'] = result
        if result['ok']:
            coverage = response_candidate(data, current, response)['coverage']
            if coverage != 'observed-turn':
                current['last_review'] = {
                    'ok': False, 'candidate_ok': True, 'coverage': coverage,
                    'reason': 'earlier assistant text was unavailable or incomplete',
                }
            store.put(CATEGORY, ('state', current))
            if coverage != 'observed-turn':
                return {'systemMessage': UNVERIFIED + current['last_review']['reason'] + '; available text was checked.'}
            return None
        if current['stop_attempts'] >= 1 or result.get('budget_exhausted'):
            store.put(CATEGORY, ('state', current))
            return {'systemMessage': UNVERIFIED + result['reason']}
        reason = 'Turn check: ' + result['reason'] + ' Revise only the requested answer; this feedback authorizes no extra work.'
        current['stop_attempts'] += 1
        current['continuations'].append(reason)
        store.put(CATEGORY, ('state', current))
    return {'decision': 'block', 'reason': reason}


def run_hook(event, data):
    if os.environ.get(DISTILLER_ENV):
        return None
    if not isinstance(data, dict) or not isinstance(data.get('cwd'), str) or not data['cwd']:
        raise ValueError('missing cwd')
    if event in ('PreToolUse', 'PostToolUse', 'PostToolUseFailure'):
        if not isinstance(data.get('tool_name'), str) or not isinstance(data.get('tool_input'), dict):
            raise ValueError('invalid tool event')
    if event == 'UserPromptSubmit':
        return begin_turn(data)
    if event == 'PreToolUse':
        return record_denial(data, pre_tool(data))
    if event == 'MessageDisplay':
        return record_display(data)
    if event in ('PostToolUse', 'PostToolUseFailure'):
        result = data.get('tool_response')
        if event == 'PostToolUseFailure' and result is None:
            result = {'error': data.get('error'), 'interrupted': data.get('is_interrupt', False)}
        return record_tool({**data, 'hook_event_name': event, 'tool_response': result})
    if event == 'SubagentStop' and data.get('agent_id') in (None, '', 'root'):
        return {'systemMessage': UNVERIFIED + 'the host supplied no subagent identity.'}
    if event in ('Stop', 'SubagentStop'):
        return stop(data)
    if event in ('SessionStart', 'SessionEnd', 'PreCompact', 'SubagentStart'):
        return lifecycle(event, data)
    raise ValueError('unsupported turn event')


def main():
    try:
        output = run_hook(sys.argv[1], json.load(sys.stdin))
        if output:
            print(json.dumps(output))
    except Exception as error:
        print(f'turn-guard: {error}', file=sys.stderr)
        if len(sys.argv) > 1 and sys.argv[1] in ('Stop', 'SubagentStop'):
            print(json.dumps({'systemMessage': UNVERIFIED + 'turn state or hook input is unavailable.'}))
        else:
            sys.exit(2)


if __name__ == '__main__':
    main()
