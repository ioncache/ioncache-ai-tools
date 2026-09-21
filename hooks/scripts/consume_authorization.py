#!/usr/bin/env python3
"""PostToolUse hook: consumes the captured prompt once a guarded git action has
run, so one instruction authorizes one action instead of standing for the rest
of the turn.

Detection here is the deterministic tokenizer, not the authorization agent, and
its lexical gaps are real: an obfuscated or indirect invocation will not be
recognized, leaving the authorization usable for one more action in the same
turn. That is deliberate. On this side a miss is over-permissive by one action,
whereas on the deny side a miss blocks work the user asked for, so the weaker
check is acceptable here and would not be acceptable there.

PostToolUse only fires after a tool call succeeds, so reaching this hook is
itself the evidence that the action went through.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rule_engine import tokenize_command, split_into_simple_commands, skip_wrappers  # noqa: E402

import pathlib  # noqa: E402

GUARDED_SUBCOMMANDS = {"push", "commit"}

# git global options that consume the following token as their value, so the
# subcommand is two positions further along rather than one.
GIT_GLOBAL_OPTIONS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree"}

PROMPT_FILE = "/tmp/.ioncache-last-prompt-{session_id}"


def git_subcommand(executable):
    """Returns the git subcommand token, stepping past git's own global
    options first, or None when there is no subcommand.
    """
    i = 1  # executable[0] is git itself
    while i < len(executable):
        token = executable[i]
        if token in GIT_GLOBAL_OPTIONS_WITH_VALUE and i + 1 < len(executable):
            i += 2
            continue
        if token.startswith("-"):
            i += 1
            continue
        return token
    return None


def runs_guarded_action(command):
    # A newline separates commands just as `;` does, but it is not one of the
    # control operators the shared tokenizer splits on, so a multi-line script
    # would otherwise collapse into a single "command" whose first word is
    # whatever came first (often `cd`) and never look like git at all. Splice
    # line continuations away first so a command broken across lines with a
    # trailing backslash is still read as one command.
    for line in command.replace("\\\n", "").split("\n"):
        for simple_command in split_into_simple_commands(tokenize_command(line)):
            executable = skip_wrappers(simple_command)
            if not executable or os.path.basename(executable[0]) != "git":
                continue
            if git_subcommand(executable) in GUARDED_SUBCOMMANDS:
                return True
    return False


def main():
    data = json.load(sys.stdin)
    if data.get("tool_name") != "Bash":
        return
    if not runs_guarded_action((data.get("tool_input") or {}).get("command") or ""):
        return
    pathlib.Path(PROMPT_FILE.format(session_id=data.get("session_id", "unknown"))).unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
