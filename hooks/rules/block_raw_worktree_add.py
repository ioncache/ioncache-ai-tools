"""Denies creating a worktree by any path other than /create-worktree.

Raw `git worktree add` skips whatever per-project setup a repo defines (see
../../scripts/create-worktree.js and .worktree-setup.json): untracked local
config, generated caches, post-create commands. So does oh-my-zsh's stock
`gwta` alias for it. The /create-worktree command is the only permitted
path. This rule only matches the assistant's own tool calls; the git call
that /create-worktree runs internally never passes through PreToolUse. A
shell function or alias defined on one machine cannot be recognised here: a
hook only sees the command text, so wrappers like that have to be removed
from the shell, not denied by name.
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts'))
from rule_engine import normalize_shell_command  # noqa: E402

# Non-greedy `(?:\s+\S+)*?` tolerates any git global options (-C <dir>,
# --no-pager, -c name=value, etc.) between `git` and `worktree add`, at the
# cost of also matching an unrelated later `worktree add` in a long command,
# an acceptable false positive for a safety guard.
RAW_WORKTREE_ADD = re.compile(r'(^|[\s;&|(`<>])git(?:\s+\S+)*?\s+worktree\s+add($|[\s;&|)`<>])')
OH_MY_ZSH_ALIAS = re.compile(r'(^|[\s;&|(`<>])gwta($|[\s;&|)`<>])')

EVENT = 'PreToolUse'
TOOL_NAMES = ['Bash']
ACTION = 'deny'
MESSAGE = (
    'Creating a worktree with raw git or `gwta` is not allowed: it skips '
    'the per-project worktree setup. Use the `/create-worktree <same args>` '
    "command instead, it wraps the git call and applies the repo's "
    '.worktree-setup.json, writing a default one first if the repo has none.'
)


def matches(hook_input):
    command = normalize_shell_command((hook_input.get('tool_input') or {}).get('command') or '')
    return bool(RAW_WORKTREE_ADD.search(command) or OH_MY_ZSH_ALIAS.search(command))
