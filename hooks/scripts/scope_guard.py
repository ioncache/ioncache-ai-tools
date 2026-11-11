"""Deterministic question, request-freshness, and skill guards."""
import json
import os
from pathlib import Path
import sys
import uuid

from block_pending_question import is_mutating
from classify_question import QUESTION_CONTRACT, has_marker, has_question, set_marker
from plugin_config import enabled, feature_settings
from evidence_store import EvidenceStore
from rule_engine import load_rules_for_event, run_rules

DISTILLER_ENV = 'IONCACHE_DOCS_DISTILLER'
CATEGORY = 'scope-policy'
BOOTSTRAP = {
    'documentation-first': (
        'Use documentation-backed third-party specifics. Applicable verified '
        'documentation can be reused; summaries establish only their stated details.'
    ),
    'answer-questions': 'Question replies contain the answer and reasoning, with work products only when requested.',
}
DELEGATION_TOOLS = {
    'Agent', 'Task', 'task', 'spawn_agent', 'run_dynamic_workflow',
    'write_agent', 'send_input', 'resume_agent', 'SendMessage',
}


def store_for(data):
    store = EvidenceStore(data)
    store.agent = json.dumps(['scope-policy', data.get('agent_id') or 'root'])
    return store


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
            state = {}
            set_marker(data, False)
            set_marker(data, False, 'prompt')
        elif 'question' in state:
            set_marker(data, state['question'] and enabled('answer-questions', data))
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
        'SELECT agent FROM records WHERE category = ? AND key = ?', (CATEGORY, 'state'),
    ).fetchall()
    for (agent,) in rows:
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
        state = {
            'id': uuid.uuid4().hex, 'prompt': prompt,
            'question': has_question(prompt) or bool(parent and parent.get('question')),
            'parent_turn': parent.get('id') if parent else None,
            'bootstrapped': True, 'continuations': [],
            'native_prompt': data.get('prompt_id') or data.get('turn_id'),
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


def prompt_pending(data):
    return (
        (enabled('scope-exactly-what-asked', data) or enabled('answer-questions', data))
        and (has_marker(data, 'prompt') or has_marker({**data, 'agent_id': None}, 'prompt'))
    )


def parent_state(data):
    if data.get('agent_id') in (None, '', 'root'):
        return None
    with store_for({**data, 'agent_id': None}) as parent:
        return parent.get(CATEGORY, 'state')


def child_state(parent):
    return {
        'id': uuid.uuid4().hex, 'prompt': parent['prompt'], 'question': parent['question'],
        'native_prompt': parent.get('native_prompt'),
        'continuations': [], 'bootstrapped': False,
        'parent_turn': parent['id'],
    }


def ensure_child_state(data):
    parent = parent_state(data)
    if parent and 'id' in parent:
        with store_for(data) as store:
            if 'id' not in (store.get(CATEGORY, 'state') or {}):
                store.put(CATEGORY, ('state', child_state(parent)))
    return parent


def record_tool(data):
    ensure_child_state(data)
    with store_for(data) as store:
        state = store.get(CATEGORY, 'state')
        if not state or 'id' not in state:
            return None
    if not state.get('bootstrapped'):
        return lifecycle(data['hook_event_name'], data)
    return None


def pre_tool(data):
    if data.get('tool_name') in ('Skill', 'skill'):
        skill = data['tool_input'].get('skill', data['tool_input'].get('name', ''))
        if isinstance(skill, str):
            namespace, _, name = skill.split(' ')[0].rpartition(':')
            setting = 'skill:' + name
            if namespace in ('', 'ioncache-ai-tools') and setting in feature_settings(data).catalog and not enabled(setting, data):
                return denial(f'The {name} plugin skill is disabled in configuration.')
    mutating = is_mutating(data.get('tool_name'), data.get('tool_input'))
    delegation = data.get('tool_name') in DELEGATION_TOOLS
    if (mutating or delegation) and prompt_pending(data):
        return denial('The current user request was not recorded. Submit the request again before authorizing work.')
    parent = ensure_child_state(data)
    if not mutating and not delegation:
        return None
    with store_for(data) as store:
        state = store.get(CATEGORY, 'state')
        if not state or 'id' not in state:
            return None
        native_prompt = data.get('prompt_id') or data.get('turn_id')
        protected = enabled('scope-exactly-what-asked', data) or enabled('answer-questions', data)
        if protected and not parent and state.get('native_prompt') and native_prompt:
            if native_prompt != state['native_prompt']:
                return denial('The current native prompt has not been recorded. Resubmit the request.')
        if protected and parent and parent.get('id') != state.get('parent_turn'):
            return denial('The parent user request changed after this subagent started. New work requires a current assignment.')
    if enabled('answer-questions', data) and state['question'] and mutating:
        return denial('BLOCKED: classified as a question. This turn is answer-only; read-only research remains available.')
    return None


def remember_continuation(data, reason):
    with store_for(data) as store:
        state = store.get(CATEGORY, 'state')
        if state and 'id' in state:
            state['continuations'] = [*state.get('continuations', [])[-7:], reason]
            store.put(CATEGORY, ('state', state))


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
    if {'answer-questions', 'scope-exactly-what-asked',
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
    if event in ('PostToolUse', 'PostToolUseFailure'):
        return record_tool({**data, 'hook_event_name': event})
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
        sys.exit(2)


if __name__ == '__main__':
    main()
