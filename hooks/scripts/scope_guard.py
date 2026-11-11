"""Deterministic question, request-freshness, skill, and graph guards."""
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

from block_pending_question import is_mutating
from classify_question import QUESTION_CONTRACT, has_marker, has_question, set_marker
from plugin_config import enabled, feature_settings
from evidence_store import EvidenceStore
from rule_engine import (
    load_rules_for_event, run_rules,
    skip_wrappers, split_into_simple_commands, tokenize_command,
)

DISTILLER_ENV = 'IONCACHE_DOCS_DISTILLER'
CATEGORY = 'scope-policy'
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
            'bootstrapped': True, 'continuations': [], 'graph': {},
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
        'id': uuid.uuid4().hex, 'prompt': parent['prompt'], 'question': parent['question'],
        'native_prompt': parent.get('native_prompt'), 'graph': {},
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


def record_tool(data):
    ensure_child_state(data)
    with store_for(data) as store:
        state = store.get(CATEGORY, 'state')
        if not state or 'id' not in state:
            return None
        if enabled('graphify', data) and graph_query(data) and state.get('pending_graph') == graph_identity(data):
            state['graph'] = {
                'identity': graph_identity(data),
                'fallback': None if result_status(data) else 'query success unverified; use source discovery',
            }
            store.put(CATEGORY, ('state', state))
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
    if not mutating and not delegation and not discovery(data) and not graph_query(data):
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
        return output
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
    if event in ('PostToolUse', 'PostToolUseFailure'):
        result = data.get('tool_response')
        if event == 'PostToolUseFailure' and result is None:
            result = {'error': data.get('error'), 'interrupted': data.get('is_interrupt', False)}
        return record_tool({**data, 'hook_event_name': event, 'tool_response': result})
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
