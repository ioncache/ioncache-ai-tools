"""Bash-side companion to no-manual-lockfile-edit.json: that rule only
matches Edit/Write/MultiEdit, so a Bash mutation (redirection, sed -i,
tee, perl -i) targeting a lockfile bypasses it entirely.
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts'))
from rule_engine import normalize_shell_command  # noqa: E402

LOCKFILE_PATTERN = re.compile(r'(package-lock\.json|yarn\.lock|pnpm-lock\.yaml)')
MUTATION_PATTERN = re.compile(r'(>{1,2}|\btee\b|\bsed\s+-i\b|\bperl\s+-i\b)')

EVENT = 'PreToolUse'
TOOL_NAMES = ['Bash']
ACTION = 'deny'
MESSAGE = (
    'Never hand-edit a lockfile from Bash (redirection, sed -i, tee, perl -i). '
    'Resolve the conflict in package.json first, then regenerate the lockfile '
    "by running the package manager's install command."
)


def matches(hook_input):
    command = normalize_shell_command((hook_input.get('tool_input') or {}).get('command') or '')
    return bool(LOCKFILE_PATTERN.search(command) and MUTATION_PATTERN.search(command))
