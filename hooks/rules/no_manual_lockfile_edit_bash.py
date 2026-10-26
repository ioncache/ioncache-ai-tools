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

Leading literal cd chains are resolved without executing the shell. Later
directory changes, expansions, and complex control flow leave cwd unknown;
relative copies of lockfiles are then rejected rather than guessed safe.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts'))
from rule_engine import (  # noqa: E402
    is_shell_operator, tokenize_command, split_into_simple_commands, skip_wrappers,
    without_redirections,
)

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


def _copy_targets_lockfile(executable, cwd):
    if len(executable) < 3:
        return False
    destination = executable[-1]
    if _is_lockfile(destination):
        return True
    if not any(_is_lockfile(source) for source in executable[1:-1]):
        return False
    if destination.endswith(os.sep):
        return True
    if os.path.isabs(destination):
        return os.path.isdir(destination)
    return cwd is None or os.path.isdir(os.path.join(cwd, destination))


def _directory_after_cd(executable, cwd):
    arguments = executable[1:]
    if arguments[:1] == ['--']:
        arguments = arguments[1:]
    if len(arguments) != 1 or arguments[0].startswith('-'):
        return None
    target = arguments[0]
    if not target or any(character in target for character in '$`~*?['):
        return None
    if not os.path.isabs(target):
        if cwd is None or os.environ.get('CDPATH'):
            return None
        target = os.path.join(cwd, target)
    target = os.path.normpath(target)
    return target if os.path.isdir(target) else None


def _mutates_lockfile(simple_command, cwd):
    for i, token in enumerate(simple_command):
        if is_shell_operator(token, {'>', '>>'}) and i + 1 < len(simple_command) and _is_lockfile(simple_command[i + 1]):
            return True
    executable = skip_wrappers(without_redirections(simple_command))
    if not executable:
        return False
    head = os.path.basename(executable[0])
    if head == 'tee':
        return any(_is_lockfile(t) for t in executable[1:])
    if head in ('sed', 'perl'):
        return _has_inplace_edit_flag(executable) and any(_is_lockfile(t) for t in executable[1:])
    if head in ('cp', 'mv'):
        return _copy_targets_lockfile(executable, cwd)
    return False


def matches(hook_input):
    command = (hook_input.get('tool_input') or {}).get('command') or ''
    cwd = hook_input.get('cwd') or os.getcwd()
    tokens = tokenize_command(command)
    leading_cd = not any(is_shell_operator(token, {'(', ')', '|', '||', '&'}) for token in tokens)
    for simple_command in split_into_simple_commands(tokens):
        if _mutates_lockfile(simple_command, cwd):
            return True
        executable = skip_wrappers(without_redirections(simple_command))
        if executable and executable[0] == 'cd':
            cwd = _directory_after_cd(executable, cwd) if leading_cd else None
        elif executable:
            leading_cd = False
    return False
