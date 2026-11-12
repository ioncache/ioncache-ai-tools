"""Reject name-based and process-group signals; exact owned targets remain usable."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts'))
from rule_engine import command_executable, split_into_simple_commands, tokenize_command  # noqa: E402

EVENT = 'PreToolUse'
TOOL_NAMES = ['Bash']
ACTION = 'deny'
MESSAGE = (
    'Do not terminate processes by name or process group: that can stop other agents. '
    'Use the exact positive PID of a process you started or were explicitly assigned to manage, '
    'or let it finish and continue with another available port or resource. '
    'Do not retry the same broad termination command.'
)


def matches(hook_input):
    command = (hook_input.get('tool_input') or {}).get('command') or ''
    for part in split_into_simple_commands(tokenize_command(command)):
        executable = command_executable(part)
        if not executable:
            continue
        head = os.path.basename(executable[0])
        if head in {'pkill', 'killall'}:
            return True
        if head != 'kill':
            continue
        args = executable[1:]
        if args[:1] in (['-l'], ['-L'], ['--list'], ['--table']):
            continue
        if args[:1] in (['-s'], ['-n'], ['--signal']):
            args = args[2:]
        elif args and args[0].startswith('-') and args[0] != '--':
            args = args[1:]
        if args[:1] == ['--']:
            args = args[1:]
        if any(arg == '0' or (arg.startswith('-') and arg[1:].isdigit()) for arg in args):
            return True
    return False
