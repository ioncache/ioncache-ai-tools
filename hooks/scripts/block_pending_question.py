#!/usr/bin/env python3
"""PreToolUse hook: denies mutating tool calls while a question is pending.

Paired with classify_question.py (UserPromptSubmit). That hook writes a
per-session marker file when the latest user message reads as a pure
question; this hook denies mutating tool calls for the rest of the turn
while that marker exists. Only the next UserPromptSubmit firing clears it,
so retrying a different tool does not bypass the block - the assistant has
to answer in text first.

Read-only/investigative tools (Read, Grep, graphify query, git log/diff/
show, a `gh api graphql` query rather than a mutation, etc.) are allowed
even while a question is pending, since answering a question well often
requires looking things up - the rule this enforces is "don't act before
answering," not "don't use any tool at all."

Bash matching here is a fixed pattern list, not real command parsing: it
catches common ways of mutating state, not every way. Known, accepted
gap: an interpreter one-liner or shell construct not in the list (an
uncommon shell, an obscure redirect form) can still slip through
unmatched.
"""

import json
import pathlib
import re
import sys

ALWAYS_MUTATING_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}

# Bash commands that change state - git/gh mutations, filesystem writes,
# package installs, and arbitrary-code interpreters that can do any of the
# above without ever matching a specific pattern. Read-only commands (git
# log/diff/show/status, ls, cat, grep, graphify query, gh pr view) are
# intentionally not matched here. `gh api graphql` is handled separately
# (see is_graphql_mutation), since it can be either a read or a write.
BASH_MUTATION_PATTERNS = re.compile(
    r"\bgit\s+("
    r"commit|push|reset|checkout\s+--|worktree\s+remove|branch\s+-[fD]\b|"
    r"rebase|merge|cherry-pick|clean\s+-"
    r")\b|"
    r"\bgh\s+("
    r"pr\s+(create|merge|close|edit)|"
    r"issue\s+(create|close|edit)|repo\s+(delete|create)"
    r")\b|"
    r"\brm\s|\bmv\s|"
    r"\bnpm\s+(install|uninstall|remove|update)\b|"
    # node -e/--eval and python -c run arbitrary code that could write
    # anything; treated as mutating outright rather than trying to parse
    # whether the inline snippet actually touches the filesystem, an
    # occasional false positive on a pure read-only one-liner is a small
    # cost next to what these can otherwise do unnoticed.
    r"\b(node|nodejs)\s+(-e|--eval)\b|"
    r"\bpython3?\s+-c\b|"
    r"\btee\b|"
    # A real redirect into a file: `>`, `>>`, `2>`, or `>&file`/`2>&file`
    # (Bash opens `file` there too, redirecting both streams to it), but
    # not descriptor duplication/closing like `>&1`, `2>&1`, `>&-`, where
    # what follows `&` is a bare fd number or `-`, never a real path.
    r">{1,2}(?!&)\s*\S|>&(?!-|\d+\b)\S",
    re.IGNORECASE,
)

GRAPHQL_QUERY_DOCUMENT = re.compile(
    r"(?:-f|-F|--raw-field|--field)\s+query=(['\"])(?P<query>.*?)\1",
    re.DOTALL,
)


def is_graphql_mutation(command):
    """True if a `gh api graphql` call's query document is a mutation.

    GraphQL over `gh api graphql` is a single transport for two different
    things: reading (a `query`) and writing (a `mutation`). Matching on
    `api graphql` alone, as an earlier version of this file did, blocks
    every read through it too, including the only way to fetch a PR
    review thread's `isResolved` status, something answering a question
    often requires. The actual operation type is the leading keyword in
    the query document itself, not anything visible in the command's
    surrounding shell syntax.

    Returns True (mutating, the safer default) when the query document
    can't be confidently extracted, since treating an unparseable call as
    read-only risks letting a real mutation through unexamined.
    """
    match = GRAPHQL_QUERY_DOCUMENT.search(command)
    if not match:
        return True
    query_text = match.group("query")
    # GraphQL's grammar treats commas and "#"-to-end-of-line comments as
    # insignificant, ignorable tokens that may legally precede the real
    # operation keyword. Stripping only whitespace let a mutation prefixed
    # with either slip past as unrecognized instead of matched.
    query_text = re.sub(r"^(?:\s+|,+|#[^\n]*\n?)+", "", query_text)
    return bool(re.match(r"mutation\b", query_text, re.IGNORECASE))


def is_mutating(tool_name, tool_input):
    if tool_name in ALWAYS_MUTATING_TOOLS:
        return True
    if tool_name == "Bash":
        command = (tool_input or {}).get("command", "")
        if re.search(r"\bgh\s+api\s+graphql\b", command, re.IGNORECASE) and is_graphql_mutation(command):
            return True
        return bool(BASH_MUTATION_PATTERNS.search(command))
    return False


def main():
    data = json.load(sys.stdin)
    session_id = data.get("session_id", "unknown")
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    flag_path = pathlib.Path(f"/tmp/.ioncache-pending-question-{session_id}")
    if not flag_path.exists():
        return

    if not is_mutating(tool_name, tool_input):
        return

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        "BLOCKED: the user's last message is a pending question "
                        "and this is a state-changing tool call. Answer the "
                        "question in plain text before making any change. "
                        "Read-only lookups are still allowed."
                    ),
                }
            }
        )
    )


if __name__ == "__main__":
    main()
