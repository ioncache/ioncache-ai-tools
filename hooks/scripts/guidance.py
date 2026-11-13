"""Stateless instructions and independently configured skill opt-outs."""
import json
import os
from pathlib import Path
import sys

from classify_question import has_question
from hook_adapter_common import InvocationDeadline, invocation_deadline, unavailable
from plugin_config import feature_settings
from rule_engine import load_rules_for_event, run_rules

BOOTSTRAP = {
    'documentation-first': (
        'Use documentation-backed third-party specifics. Applicable verified '
        'documentation can be reused; summaries establish only their stated details.'
    ),
    'answer-questions': (
        'Answer questions directly without starting unrelated work. A question does not '
        'cancel ongoing authorized work or another agent. Continue existing assignments '
        'unless the user explicitly pauses, cancels, or changes them.'
    ),
}
QUESTION_GUIDANCE = (
    'Question guidance: answer the question and its reasoning; do not invent new work. '
    'This is not a turn-wide restriction or a change to ongoing assignments.'
)


def context(event, text):
    return {'hookSpecificOutput': {'hookEventName': event, 'additionalContext': text}} if text else None


def evaluate(event, data):
    snapshot = feature_settings(data, refresh=True)
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
    messages = [text for name, text in BOOTSTRAP.items() if name not in disabled]
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
    if event == 'UserPromptSubmit' and 'answer-questions' not in disabled and has_question(data.get('prompt', '')):
        messages.append(QUESTION_GUIDANCE)
    return context(event, '\n\n'.join(messages))


def run_hook(event, data):
    if os.environ.get('IONCACHE_DOCS_DISTILLER'):
        return None
    try:
        with invocation_deadline(4):
            return evaluate(event, data)
    except (InvocationDeadline, Exception) as error:
        return unavailable('guidance', error)


def main():
    try:
        output = run_hook(sys.argv[1], json.load(sys.stdin))
    except Exception as error:
        output = unavailable('guidance', error)
    if output:
        print(json.dumps(output))


if __name__ == '__main__':
    main()
