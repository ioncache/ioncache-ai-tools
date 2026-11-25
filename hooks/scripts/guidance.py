"""Prompt guidance, the root question marker, and skill opt-outs."""
import json
import os
from pathlib import Path
import sys

from classify_question import QUESTION_CONTRACT, has_question, is_root, set_marker
from claude_prompt import normalize_prompt
from hook_adapter_common import InvocationDeadline, invocation_deadline, unavailable
from plugin_config import enabled, feature_settings
from rule_engine import load_rules_for_event, run_rules

BOOTSTRAP = {
    'documentation-first': (
        'Use documentation-backed third-party specifics. Applicable verified '
        'documentation can be reused; summaries establish only their stated details.'
    ),
    'answer-questions': (
        'A user question asks for information, not action: answer it with its reasoning '
        'and do not decide or implement next steps in that turn, even for an existing '
        'assignment. A question to one agent does not pause, cancel, or stop other agents '
        'or their authorized work. A question about stopping workers is not permission '
        'to stop them.'
    ),
}
# Child identities receive prompts from their parent, not only from the user.
CHILD_BOOTSTRAP = (
    'Answer questions with their reasoning and do not invent unrequested work. A question '
    'in an assignment from your parent does not pause it, and a question to another agent '
    'does not stop your authorized work.'
)
CHILD_QUESTION_GUIDANCE = (
    'Question guidance: answer the question and its reasoning; do not invent new work. '
    'This does not restrict tools or change your existing assignment.'
)
UNVERIFIED_BOOTSTRAP = (
    BOOTSTRAP['answer-questions'] + ' Unverified hook origin is not permission to act '
    'on a user question. Apply the user-question rule only to questions from the user; '
    'question-shaped reports, notifications, or parent-written messages do not '
    'suspend authorized work.'
)


def context(event, text):
    return {'hookSpecificOutput': {'hookEventName': event, 'additionalContext': text}} if text else None


def evaluate(event, data):
    snapshot = feature_settings(data)
    disabled = set(snapshot.disabled)
    if event == 'PreToolUse':
        if data.get('tool_name') not in ('Skill', 'skill'):
            return None
        args = data.get('tool_input') or {}
        skill = args.get('skill', args.get('name', ''))
        if isinstance(skill, str) and skill.strip():
            namespace, _, name = skill.split(' ')[0].rpartition(':')
            if namespace in ('', 'ioncache-ai-tools') and 'skill:' + name in disabled:
                return {'hookSpecificOutput': {
                    'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                    'permissionDecisionReason': (
                        f'The {name} plugin skill is disabled in configuration. '
                        'Continue the task without that skill, using other available tools. '
                        'Do not repeatedly request the disabled skill.'
                    ),
                }}
        return None
    if event not in ('UserPromptSubmit', 'SessionStart', 'SubagentStart'):
        return None
    if 'skill:engineering-judgment' in disabled:
        disabled.add('engineering-judgment')
    rules = load_rules_for_event(Path(__file__).parent.parent / 'rules', 'SessionStart', disabled)
    output = run_rules(rules, 'SessionStart', data) or {}
    child = event == 'SubagentStart' or not is_root(data)
    bootstrap = {**BOOTSTRAP, 'answer-questions': CHILD_BOOTSTRAP} if child else BOOTSTRAP
    if not child and data.get('_ioncache_prompt_origin') != 'user':
        bootstrap = {**BOOTSTRAP, 'answer-questions': UNVERIFIED_BOOTSTRAP}
    messages = [text for name, text in bootstrap.items() if name not in disabled]
    skills = sorted(name.removeprefix('skill:') for name in disabled if name.startswith('skill:'))
    if skills:
        messages.append('Disabled plugin skills: ' + ', '.join(skills) +
                        '. Continue without these skills; do not invoke or apply them.')
    if 'review-auto-model-selection' in disabled:
        messages.append(
            'Automatic review model selection is disabled. Use configured models for '
            'unspecified review roles; explicit user model choices still follow host restrictions.'
        )
    policy = output.get('hookSpecificOutput', {}).get('additionalContext')
    if policy:
        messages.append(policy)
    if event == 'UserPromptSubmit' and 'answer-questions' not in disabled:
        if child and isinstance(data.get('prompt'), str) and has_question(data['prompt']):
            messages.append(CHILD_QUESTION_GUIDANCE)
        elif user_question(data):
            messages.append(QUESTION_CONTRACT)
    return context(event, '\n\n'.join(messages))


def user_question(data):
    prompt = data.get('prompt')
    return (is_root(data) and data.get('_ioncache_prompt_origin') == 'user'
            and isinstance(prompt, str) and has_question(prompt))


def record_question(data, *, question):
    """Only positively identified root-user questions can create a marker."""
    # A child without its own identity must not erase the root's marker.
    if not is_root(data) and data.get('agent_id') in (None, '', 'root'):
        return
    if question and not user_question(data):
        return
    # Clearing never needs configuration, so a failed settings read cannot keep a stale fence.
    set_marker(data, question and enabled('answer-questions', data))


def run_hook(event, data):
    if os.environ.get('IONCACHE_DOCS_DISTILLER'):
        return None
    prompt = event == 'UserPromptSubmit'
    warnings = []
    # Clear before guidance work, so a slow or killed evaluation cannot keep the last turn's marker.
    if prompt:
        record_safely(data, warnings, question=False)
    try:
        with invocation_deadline(3):
            if prompt:
                data = normalize_prompt(data)
            data = {**data, '_ioncache_features': feature_settings(data, refresh=True)}
            output = evaluate(event, data)
        if prompt and not warnings:
            record_safely(data, warnings, question=True)
    except (InvocationDeadline, Exception) as error:
        output = unavailable('guidance', error)
    if not warnings:
        return output
    output = output or {}
    return {**output, 'systemMessage': '\n\n'.join(filter(None, (output.get('systemMessage'), *warnings)))}


def record_safely(data, warnings, *, question):
    try:
        with invocation_deadline(1):
            record_question(data, question=question)
    except (InvocationDeadline, Exception) as error:
        warnings.append(unavailable('question-state', error)['systemMessage'])


def main():
    try:
        output = run_hook(sys.argv[1], json.load(sys.stdin))
    except Exception as error:
        output = unavailable('guidance', error)
    if output:
        print(json.dumps(output))


if __name__ == '__main__':
    main()
