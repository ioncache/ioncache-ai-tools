"""Active scope, approval, question, and graph checks. No claim verification."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from block_pending_question import is_mutating
from context_handoff import is_handoff_write
from classify_question import QUESTION_CONTRACT, has_marker, has_question, set_marker
from plugin_config import enabled, feature_settings
from evidence_store import EvidenceStore
from rule_engine import (
    load_rules_for_event, run_rules,
    skip_wrappers, split_into_simple_commands, tokenize_command,
)
import scope_review as turn_review

DISTILLER_ENV = 'IONCACHE_DOCS_DISTILLER'
CATEGORY = 'scope-policy'
MAX_INTERACTION_CHARS = 32_000
MAX_RESULT_CHARS = 8_000
MAX_INPUT_CHARS = 2_000
MAX_REQUEST_CHARS = 16_000
MAX_HISTORY_CHARS = 12_000
MAX_RESPONSE_CHARS = 16_000
USER_INPUT_TOOLS = {'AskUserQuestion', 'ask_user', 'request_user_input'}
BOOTSTRAP = {
    'documentation-first': (
        'Use documentation-backed third-party specifics. Applicable verified '
        'documentation can be reused; summaries establish only their stated details.'
    ),
    'answer-questions': 'Question replies contain the answer and reasoning, with work products only when requested.',
    'graphify': (
        'In projects with graphify-out/graph.json, code discovery starts with a '
        'relevant graphify query, followed by targeted source reads.'
    ),
}
GRAPH_DENIAL = (
    'Code discovery requires a relevant graphify query first. '
    'Run graphify query with the codebase question, then inspect the sources.'
)
UNVERIFIED = 'Turn check did not verify this response: '
DELEGATION_TOOLS = {
    'Agent', 'Task', 'task', 'spawn_agent', 'run_dynamic_workflow',
    'write_agent', 'send_input', 'resume_agent', 'SendMessage',
}


def store_for(data):
    store = EvidenceStore(data)
    store.agent = json.dumps(['scope-policy', data.get('agent_id') or 'root'])
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
    disabled = set(feature_settings(data).disabled)
    if 'skill:engineering-judgment' in disabled:
        disabled.add('engineering-judgment')
    rules = load_rules_for_event(Path(__file__).parent.parent / 'rules', 'SessionStart', disabled)
    output = run_rules(rules, 'SessionStart', data) or {}
    policy = output.get('hookSpecificOutput', {}).get('additionalContext', '')
    messages = [text for name, text in BOOTSTRAP.items() if name not in disabled]
    skills = sorted(name.removeprefix('skill:') for name in disabled if name.startswith('skill:'))
    if skills:
        messages.append('Disabled plugin skills: ' + ', '.join(skills) +
                        '. Do not invoke or apply these skills, including automatic or slash-command activation.')
    return context(event, '\n\n'.join(filter(None, (*messages, policy))))


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
        elif state.get('question') and enabled('answer-questions', data):
            set_marker(data, True)
        if event == 'SessionStart' and data.get('source') == 'resume':
            state.update(reviews={})
            store.put(CATEGORY, ('state', state))
        if state.get('bootstrapped') and not refresh:
            return None
        state['bootstrapped'] = True
        store.put(CATEGORY, ('state', state))
    output = bootstrap(data, event)
    if state.get('question') and enabled('answer-questions', data):
        text = (output or {}).get('hookSpecificOutput', {}).get('additionalContext', '')
        return context(event, '\n\n'.join(filter(None, (text, QUESTION_CONTRACT))))
    return output


def end_session(store, data):
    rows = store.connection.execute(
        'SELECT agent, value FROM records WHERE category = ? AND key = ?', (CATEGORY, 'state'),
    ).fetchall()
    for agent, value in rows:
        state = json.loads(value)
        state.update(reviews={})
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
            'bootstrapped': True, 'continuations': [], 'stop_attempts': 0, 'stop_checks': 0,
            'reviews': {}, 'graph': {},
            'pending_tools': {}, 'history': history, 'messages': [],
            'messages_truncated': False, 'recent_messages': [], 'recent_messages_omitted': False,
            'native_prompt': data.get('prompt_id') or data.get('turn_id'),
            'user_interactions': previous.get('user_interactions', []),
            'interaction_context_incomplete': previous.get('interaction_context_incomplete', False),
            'recovered_dialogue': previous.get('recovered_dialogue', []),
            'recovery_problem': previous.get('recovery_problem', ''),
            'history_recovery_disabled': previous.get('history_recovery_disabled', False),
        }
        store.put(CATEGORY, ('state', state))
        set_marker(data, state['question'] and enabled('answer-questions', data))
    messages = []
    if not previous.get('bootstrapped'):
        output = bootstrap(data, 'UserPromptSubmit')
        if output:
            messages.append(output['hookSpecificOutput']['additionalContext'])
    if state['question'] and enabled('answer-questions', data):
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
    return (
        (enabled('scope-exactly-what-asked', data) or enabled('answer-questions', data))
        and (has_marker(data, 'prompt') or has_marker({**data, 'agent_id': None}, 'prompt'))
    )


def shell_commands(data):
    if data.get('tool_name') != 'Bash':
        return []
    commands = split_into_simple_commands(tokenize_command(data['tool_input'].get('command', '')))
    return [executable for command in commands if command and (executable := skip_wrappers(command))]


def graph_query(data):
    commands = shell_commands(data)
    if len(commands) != 1:
        return False
    args = commands[0]
    if (len(args) < 3 or Path(args[0]).name != 'graphify' or args[1] != 'query'
            or not args[2].strip() or args[2].startswith('-')
            or any(value in ('--help', '-h') for value in args)):
        return False
    expected = Path(data['cwd']) / 'graphify-out/graph.json'
    for index, value in enumerate(args):
        if value == '--graph':
            return index + 1 < len(args) and (Path(data['cwd']) / args[index + 1]).resolve() == expected.resolve()
        if value.startswith('--graph='):
            return (Path(data['cwd']) / value.split('=', 1)[1]).resolve() == expected.resolve()
    return True


def discovery(data):
    if data.get('tool_name') in ('Grep', 'Glob', 'grep', 'rg', 'glob', 'semantic_code_search'):
        return True
    if data.get('tool_name') == 'Read':
        path = str(data.get('tool_input', {}).get('file_path', ''))
        target = (Path(data['cwd']) / path).resolve()
        return (target.is_relative_to(Path(data['cwd']).resolve())
                and target.name not in ('CLAUDE.md', 'AGENTS.md', 'GEMINI.md', 'copilot-instructions.md'))
    for command in shell_commands(data):
        executable = Path(command[0]).name
        if executable in ('rg', 'grep', 'find'):
            return True
        if executable in ('cat', 'sed', 'head', 'tail'):
            if any(not arg.startswith('-') and (Path(data['cwd']) / arg).is_file() for arg in command[1:]):
                return True
    return False


def parent_state(data):
    if data.get('agent_id') in (None, '', 'root'):
        return None
    with store_for({**data, 'agent_id': None}) as parent:
        return parent.get(CATEGORY, 'state')


def child_state(parent):
    return {
        **parent, 'id': uuid.uuid4().hex, 'reviews': {}, 'graph': {},
        'continuations': [], 'stop_attempts': 0, 'stop_checks': 0, 'bootstrapped': False,
        'parent_turn': parent['id'],
        'pending_tools': {}, 'last_response': None,
        'last_earlier_response': [], 'earlier_response_truncated': False, 'earlier_response_omitted': False,
        'messages': [], 'messages_truncated': False, 'recent_messages': [], 'recent_messages_omitted': False,
    }


def ensure_child_state(data):
    parent = parent_state(data)
    if parent and 'id' in parent:
        with store_for(data) as store:
            if 'id' not in (store.get(CATEGORY, 'state') or {}):
                store.put(CATEGORY, ('state', child_state(parent)))
    return parent


def graph_identity(data):
    graph = Path(data['cwd']) / 'graphify-out/graph.json'
    try:
        info = graph.stat()
    except FileNotFoundError:
        return None
    except OSError:
        return [str(graph.absolute()), 'unavailable', None]
    return [str(graph.resolve()), info.st_mtime_ns, info.st_size]


def graph_gate(data, state):
    if not enabled('graphify', data):
        return None
    identity = graph_identity(data)
    if not identity or not discovery(data) or state.get('graph', {}).get('identity') == identity:
        return None
    if identity[1] == 'unavailable' or not shutil.which('graphify'):
        state['graph'] = {'identity': identity, 'fallback': 'graph or executable unavailable'}
        return denial('Graphify or its graph is unavailable. Source discovery is available on retry.')
    return denial(GRAPH_DENIAL)


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


def bounded(items):
    while items and len(json.dumps(items)) > MAX_INTERACTION_CHARS:
        items.pop(0)
    return items


def tool_key(data):
    return str(data.get('tool_use_id') or fingerprint(
        [data['cwd'], data.get('tool_name'), data.get('tool_input')],
    ))


def append_recovery(state, item):
    if not state.get('recovered_dialogue'):
        return
    dialogue = [*state['recovered_dialogue'], item]
    if len(json.dumps(dialogue)) > turn_review.MAX_RECOVERY_CHARS:
        state.update(recovered_dialogue=[], recovery_problem='Recovered dialogue exceeded its retention budget.')
    else:
        state['recovered_dialogue'] = dialogue


def record_start(data):
    if data.get('tool_name') not in USER_INPUT_TOOLS:
        return
    with store_for(data) as store:
        state = store.get(CATEGORY, 'state')
        if not state or 'id' not in state:
            return
        pending = state.get('pending_tools', {})
        key = tool_key(data)
        entry = {
            'turn': state['id'], 'ambiguous': key in pending,
            'invocation': fingerprint([data['tool_name'], data['tool_input']]),
        }
        state['pending_tools'] = dict([*pending.items()][-63:])
        state['pending_tools'][key] = entry
        store.put(CATEGORY, ('state', state))


def record_interaction(state, data):
    if data['tool_name'] not in USER_INPUT_TOOLS:
        return
    before = state.get('pending_tools', {}).pop(tool_key(data), None)
    item = {
        'tool': data['tool_name'], 'cwd': data['cwd'], 'turn': state['id'],
        'success': result_status(data), 'input': data['tool_input'],
        'result': json.dumps(data.get('tool_response')), 'truncated': False,
        'correlated': bool(before and not before['ambiguous'] and before['turn'] == state['id']
                           and before['invocation'] == fingerprint([data['tool_name'], data['tool_input']])),
    }
    if len(json.dumps(item)) > MAX_REQUEST_CHARS:
        item.update(input={'excerpt': json.dumps(item['input'])[:MAX_INPUT_CHARS]},
                    result=item['result'][:MAX_RESULT_CHARS], truncated=True)
    items = [*state.get('user_interactions', []), item]
    count = len(items)
    state['user_interactions'] = bounded(items)
    state['interaction_context_incomplete'] = state.get('interaction_context_incomplete', False) or len(items) < count
    if data.get('agent_id') in (None, '', 'root'):
        append_recovery(state, {'kind': 'interaction', **item})


def record_tool(data):
    ensure_child_state(data)
    with store_for(data) as store:
        state = store.get(CATEGORY, 'state')
        if not state or 'id' not in state:
            return None
        record_interaction(state, data)
        if enabled('graphify', data) and graph_query(data) and state.get('pending_graph') == graph_identity(data):
            state['graph'] = {
                'identity': graph_identity(data),
                'fallback': None if result_status(data) else 'query success unverified; use source discovery',
            }
        store.put(CATEGORY, ('state', state))
    if not state.get('bootstrapped'):
        return lifecycle(data['hook_event_name'], data)
    return None


def review_request(data, state, candidate):
    recovery = enabled('approval-recovery', data)
    return turn_review.fit_context({
        'latest_request': state['prompt'], 'request_context': state['requests'][:-1],
        'request_context_incomplete': state.get('request_context_incomplete', False),
        'assistant_context': state.get('history', []),
        'user_interactions': state.get('user_interactions', []),
        'interaction_context_incomplete': state.get('interaction_context_incomplete', False),
        'recovered_dialogue': state.get('recovered_dialogue', []) if recovery else [],
        'recovery_problem': state.get('recovery_problem', '') if recovery else '',
        'question_only': enabled('answer-questions', data) and state['question'],
        'scope': enabled('scope-exactly-what-asked', data),
        'turn': state['id'], 'candidate': candidate,
    })


def check_candidate(data, state, candidate):
    request = review_request(data, state, candidate)
    key = fingerprint(request)
    if not request['scope'] and not request['question_only']:
        return key, {'ok': True, 'reason': ''}
    if key in state.get('reviews', {}):
        return key, state['reviews'][key]
    try:
        result = turn_review.review(data.get('_ioncache_harness', 'claude'), request)
    except turn_review.ReviewInputTooLarge:
        return key, {'ok': False, 'reason': 'The current request and candidate exceed the review input budget; use smaller changes.'}
    except turn_review.UnsupportedReviewerCLI as error:
        print(f'scope-guard: {error}', file=sys.stderr)
        return key, {'ok': False, 'reason': str(error)}
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f'scope-guard: semantic checker failed ({type(error).__name__})', file=sys.stderr)
        return key, {'ok': False, 'reason': 'The semantic checker is unavailable or returned invalid output.'}
    fresh_data = {**data, '_ioncache_features': feature_settings(data, refresh=True)}
    with store_for(data) as store:
        current = store.get(CATEGORY, 'state')
        if not current or 'id' not in current or fingerprint(review_request(fresh_data, current, candidate)) != key:
            return key, {'ok': False, 'reason': 'The request or authorization changed during review. Retry with the current request.'}
        current['reviews'] = dict([*current.get('reviews', {}).items()][-15:])
        current['reviews'][key] = result
        store.put(CATEGORY, ('state', current))
    return key, result


def pre_tool(data):
    if data.get('tool_name') in ('Skill', 'skill'):
        skill = data['tool_input'].get('skill', data['tool_input'].get('name', ''))
        if isinstance(skill, str):
            namespace, _, name = skill.split(' ')[0].rpartition(':')
            setting = 'skill:' + name
            if namespace in ('', 'ioncache-ai-tools') and setting in feature_settings(data).catalog and not enabled(setting, data):
                return denial(f'The {name} plugin skill is disabled in configuration.')
    # The handoff file is plugin-private session state, not user work to authorize.
    if is_handoff_write(data):
        return None
    mutating = is_mutating(data.get('tool_name'), data.get('tool_input'))
    delegation = data.get('tool_name') in DELEGATION_TOOLS
    if (mutating or delegation) and prompt_pending(data):
        return denial('The current user request was not recorded. Submit the request again before authorizing work.')
    if not mutating and not delegation and not discovery(data) and not graph_query(data):
        record_start(data)
        return None
    parent = ensure_child_state(data)
    with store_for(data) as store:
        state = store.get(CATEGORY, 'state')
        if not state or 'id' not in state:
            return None
        native_prompt = data.get('prompt_id') or data.get('turn_id')
        protected = enabled('scope-exactly-what-asked', data) or enabled('answer-questions', data)
        if protected and (mutating or delegation) and not parent and state.get('native_prompt') and native_prompt:
            if native_prompt != state['native_prompt']:
                return denial('The current native prompt has not been recorded. Resubmit the request.')
        if protected and (mutating or delegation) and parent and parent.get('id') != state.get('parent_turn'):
            return denial('The parent user request changed after this subagent started. New work requires a current assignment.')
        if enabled('graphify', data) and graph_query(data):
            state['pending_graph'] = graph_identity(data)
        output = graph_gate(data, state)
        store.put(CATEGORY, ('state', state))
    if output or not (mutating or delegation):
        if not output:
            record_start(data)
        return output
    if enabled('answer-questions', data) and state['question'] and mutating:
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
            return denial('The request or authorization changed during review. Retry with the current request.')
    record_start(data)
    return None


def remember_continuation(data, reason):
    with store_for(data) as store:
        state = store.get(CATEGORY, 'state')
        if state and 'id' in state:
            state['continuations'] = [*state.get('continuations', [])[-7:], reason]
            store.put(CATEGORY, ('state', state))


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
            and not state.get('history_recovery_disabled') and enabled('approval-recovery', data)):
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
    if not enabled('scope-exactly-what-asked', data) and not (
            enabled('answer-questions', data) and state['question']):
        return None
    key, result = final_verdict(data, state, response)
    with store_for(data) as store:
        current = store.get(CATEGORY, 'state')
        if not current or current.get('id') != state['id']:
            return {'systemMessage': UNVERIFIED + 'the active user turn changed during review.'}
        if key and fingerprint(review_request(data, current, response_candidate(data, current, response))) != key:
            result = {'ok': False, 'reason': 'The request or authorization changed during response review.'}
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
    snapshot = feature_settings(data, refresh=True)
    data = {**data, '_ioncache_features': snapshot}
    disabled = snapshot.disabled
    if not enabled('answer-questions', data):
        set_marker(data, False)
    if {'answer-questions', 'scope-exactly-what-asked', 'graphify',
            'documentation-first', 'engineering-judgment'} <= disabled and not any(
                name.startswith('skill:') for name in disabled):
        return None
    if event in ('PreToolUse', 'PostToolUse', 'PostToolUseFailure'):
        if not isinstance(data.get('tool_name'), str) or not isinstance(data.get('tool_input'), dict):
            raise ValueError('invalid tool event')
    if event == 'UserPromptSubmit':
        return begin_turn(data)
    if event == 'PreToolUse':
        return pre_tool(data)
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
        print(f'scope-guard: {error}', file=sys.stderr)
        if len(sys.argv) > 1 and sys.argv[1] in ('Stop', 'SubagentStop'):
            print(json.dumps({'systemMessage': UNVERIFIED + 'turn state or hook input is unavailable.'}))
        else:
            sys.exit(2)


if __name__ == '__main__':
    main()
