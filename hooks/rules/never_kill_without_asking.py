"""Blocks recognized process-kill commands while enabled.

Chat approval does not override this rule; allowing these commands requires
disabling it in rule settings. Checks cover common direct, path-qualified,
and wrapped invocations, not deliberately indirect shell scripts.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts'))
from rule_engine import tokenize_command, split_into_simple_commands, skip_wrappers  # noqa: E402

GUARDED_COMMANDS = {'kill', 'pkill', 'killall'}

EVENT = 'PreToolUse'
TOOL_NAMES = ['Bash']
ACTION = 'deny'
MESSAGE = (
    'This rule blocks recognized kill/pkill/killall commands, even after chat approval. '
    'The user must disable never_kill_without_asking in their rule settings to permit them '
    '(see README: Disabling a rule).'
)


def matches(hook_input):
    command = (hook_input.get('tool_input') or {}).get('command') or ''
    tokens = tokenize_command(command)
    for simple_command in split_into_simple_commands(tokens):
        executable = skip_wrappers(simple_command)
        if not executable:
            continue
        head = os.path.basename(executable[0])
        if head in GUARDED_COMMANDS:
            return True
    return False
