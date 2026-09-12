"""Denies kill/pkill/killall unless the user has explicitly said yes
first, even for the assistant's own leftover process.

A regex-based version of this rule (matching a boundary-anchored
`(kill|pkill|killall)` against the raw or backslash/quote-normalized
command text) went through several rounds of bypass fixes and each one
opened a new false positive or false negative: a path prefix added to
catch `/bin/kill` also matched `ls /tmp/kill` (an argument, not an
invocation); a boundary character list added to catch redirection
missed the next one; quote-stripping added to catch `'kill'` exposed
operator characters that were safely inside the quotes. None of that is
fixable by patching the regex further, a flat-text match fundamentally
can't tell "this word is the command being run" from "this word is
somewhere in the text". Real command tokenization (Python's shlex, which
JS has no equivalent of) can, so this rule is scripted rather than a
declarative regex pattern.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts'))
from rule_engine import tokenize_command, split_into_simple_commands  # noqa: E402

GUARDED_COMMANDS = {'kill', 'pkill', 'killall'}

EVENT = 'PreToolUse'
TOOL_NAMES = ['Bash']
ACTION = 'deny'
MESSAGE = (
    'Never run kill/pkill/killall without asking the user first, even for '
    'your own leftover process. Ask, then wait for an explicit yes. If '
    'this is genuinely getting in your way, disable this rule via '
    ".claude/ioncache-ai-tools.local.json or Codex config (see README's "
    'Disabling a rule section).'
)


def matches(hook_input):
    command = (hook_input.get('tool_input') or {}).get('command') or ''
    tokens = tokenize_command(command)
    for simple_command in split_into_simple_commands(tokens):
        if not simple_command:
            continue
        head = os.path.basename(simple_command[0])
        if head in GUARDED_COMMANDS:
            return True
    return False
