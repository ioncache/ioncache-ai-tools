"""Bash-side companion to no-manual-lockfile-edit.json: that rule only
matches Edit/Write/MultiEdit, so a Bash mutation (redirection, sed -i,
tee, perl -i) targeting a lockfile bypasses it entirely.

Checks each simple command's mutation operation, its options, and its
target together, rather than matching a lockfile name and a mutation
pattern independently anywhere in the whole command. Matching
independently denied unrelated commands (a lockfile name mentioned in
one simple command was enough to deny a completely different mutation
elsewhere in the same compound command) and missed a real bypass (an
in-place-edit flag not immediately adjacent to `sed`, e.g. `sed -E -i`,
since the flag's exact position in the token list was never checked).

Scope, by design (see README's `hooks/rules/` section): this catches
common redirection/`sed`/`perl`/`tee`/`cp`/`mv` forms, not every possible
one. A less common redirection operator (`>|`, `&>`) or a deliberately
obfuscated command is an accepted, out-of-scope gap, the same trade-off
`never_kill_without_asking` documents for itself.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts'))
from rule_engine import tokenize_command, split_into_simple_commands, skip_wrappers  # noqa: E402

LOCKFILE_NAMES = {'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml'}

EVENT = 'PreToolUse'
TOOL_NAMES = ['Bash']
ACTION = 'deny'
MESSAGE = (
    'Never hand-edit a lockfile from Bash (redirection, sed -i, tee, perl -i). '
    'Resolve the conflict in package.json first, then regenerate the lockfile '
    "by running the package manager's install command."
)


def _is_lockfile(token):
    return os.path.basename(token) in LOCKFILE_NAMES


# Checks for 'i' anywhere in a short-flag cluster (-i, -pi, -Ei, -i.bak,
# -Ei.bak), since sed/perl combine single-letter flags into one token and
# an exact '-i'/'-i.' match misses that. Also accepts GNU sed's long form.
# Known, accepted gap: doesn't parse cp/mv's own flags, so `cp -t DIR
# package-lock.json` (destination given via -t, lockfile is actually the
# source being read) reads as a mutation; narrow enough not to chase.
def _has_inplace_edit_flag(executable):
    for token in executable[1:]:
        if token == '--in-place' or token.startswith('--in-place='):
            return True
        if token.startswith('-') and not token.startswith('--'):
            flags = token[1:].split('.', 1)[0]
            if 'i' in flags:
                return True
    return False


def _mutates_lockfile(simple_command):
    for i, token in enumerate(simple_command):
        if token in ('>', '>>') and i + 1 < len(simple_command) and _is_lockfile(simple_command[i + 1]):
            return True
    executable = skip_wrappers(simple_command)
    if not executable:
        return False
    head = os.path.basename(executable[0])
    if head == 'tee':
        return any(_is_lockfile(t) for t in executable[1:])
    if head in ('sed', 'perl'):
        return _has_inplace_edit_flag(executable) and any(_is_lockfile(t) for t in executable[1:])
    if head in ('cp', 'mv') and len(executable) > 1:
        return _is_lockfile(executable[-1])
    return False


def matches(hook_input):
    command = (hook_input.get('tool_input') or {}).get('command') or ''
    return any(_mutates_lockfile(sc) for sc in split_into_simple_commands(tokenize_command(command)))
