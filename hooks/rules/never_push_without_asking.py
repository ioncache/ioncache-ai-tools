"""Denies `git push` unless the user has explicitly asked for it in this
same turn, every single time.

Uses the same tokenization approach as `never_kill_without_asking.py`:
checking the executable position of each simple command, not a text
match anywhere in the string, for the same reason (a flat-text match
can't tell "this is the command being run" from "this word is
somewhere in the text").

`push` is a git subcommand, not a bare executable, so this also has to
find where it sits after `git` itself and any global options git
accepts before the subcommand (`git -C <dir> push`, `git --no-pager
push`). Only the common forms are handled; an uncommon or combined
global-option form is a known, accepted gap, matching the "Scope, by
design" note in README's `hooks/rules/` section: this guards against
casual/automatic pushes, not deliberate evasion.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts'))
from rule_engine import tokenize_command, split_into_simple_commands, skip_wrappers  # noqa: E402

# git global options that take a value as the next token, vs. bare flags
# that don't. Not exhaustive, the common real-world forms only.
GIT_GLOBAL_OPTIONS_WITH_VALUE = {'-C', '-c', '--git-dir', '--work-tree'}

EVENT = 'PreToolUse'
TOOL_NAMES = ['Bash']
ACTION = 'deny'
MESSAGE = (
    'Never run git push without asking the user first, every single time, '
    'even if a push was approved earlier in this session or earlier in '
    'this same turn. One approval covers exactly one push. Ask, then wait '
    'for an explicit yes for this specific push. If this is genuinely '
    'getting in your way, disable this rule via '
    ".claude/ioncache-ai-tools.local.json or Codex config (see README's "
    'Disabling a rule section).'
)


def _git_subcommand(executable):
    """Returns the git subcommand token, skipping git's own global
    options first (`-C <dir>`, bare flags like `--no-pager`). Returns
    None if the subcommand position can't be found.
    """
    i = 1  # executable[0] is 'git' itself
    n = len(executable)
    while i < n:
        token = executable[i]
        if token in GIT_GLOBAL_OPTIONS_WITH_VALUE and i + 1 < n:
            i += 2
            continue
        if token.startswith('-'):
            i += 1
            continue
        break
    return executable[i] if i < n else None


def matches(hook_input):
    command = (hook_input.get('tool_input') or {}).get('command') or ''
    tokens = tokenize_command(command)
    for simple_command in split_into_simple_commands(tokens):
        executable = skip_wrappers(simple_command)
        if not executable or os.path.basename(executable[0]) != 'git':
            continue
        if _git_subcommand(executable) == 'push':
            return True
    return False
