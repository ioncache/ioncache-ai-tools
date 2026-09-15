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
import os
import pathlib
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rule_engine import tokenize_command, split_into_simple_commands, skip_wrappers  # noqa: E402

ALWAYS_MUTATING_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}

# Bash commands that change state - git/gh mutations, filesystem writes,
# package installs, and arbitrary-code interpreters that can do any of the
# above without ever matching a specific pattern. Read-only commands (git
# log/diff/show/status, ls, cat, grep, graphify query, gh pr view) are
# intentionally not matched here. `gh api graphql` is handled separately
# (see _is_graphql_mutation_document), since it can be either a read or
# a write.
# A real file redirect (`>`, `>>`, `>&file`, `&>file`, `>|file`) is
# handled separately too (see has_file_redirect): unlike these, a
# redirect operator needs actual tokenization to check, a raw text scan
# for `>` also matches one quoted inside another command's argument
# (`grep "a > b" file`) or a `((...))` arithmetic comparison, neither of
# which is a redirect at all.
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
    r"\btee\b",
    re.IGNORECASE,
)

# Redirecting to one of these doesn't persist anything; the extremely
# common `2>/dev/null` idiom for suppressing stderr noise on an otherwise
# read-only command shouldn't itself count as a mutation.
NULL_REDIRECT_TARGETS = {"/dev/null", "/dev/stdout", "/dev/stderr"}


# Redirect operators that always take a real target (no fd-duplication
# form exists for any of them): `>`/`>>` (write/append), `>|` (force
# write past noclobber), `&>`/`&>>` (both stdout+stderr, write/append),
# `<>` (open for read+write, creating the target if it doesn't exist).
FILE_REDIRECT_OPERATORS = {">", ">>", ">|", "&>", "&>>", "<>"}


def _redirects_to_a_file(simple_command):
    if simple_command and simple_command[0] == "((":
        # Arithmetic evaluation: `>`/`<` are comparison operators here,
        # never a redirect.
        return False
    for i, token in enumerate(simple_command):
        if token in FILE_REDIRECT_OPERATORS:
            if i + 1 < len(simple_command) and simple_command[i + 1] not in NULL_REDIRECT_TARGETS:
                return True
        elif token == ">&":
            if i + 1 < len(simple_command):
                target = simple_command[i + 1]
                if target != "-" and not target.isdigit() and target not in NULL_REDIRECT_TARGETS:
                    return True
    return False


def has_file_redirect(command):
    """True if `command` contains a real Bash redirect into a file
    (`>`, `>>`, `>|`, `<>`, `>&file`, `&>file`, `&>>file`), tokenized
    rather than text-matched so `>` inside a quoted argument or a
    `((...))` comparison isn't mistaken for one. Excludes descriptor
    duplication/closing (`>&1`, `2>&1`, `>&-`) and redirects to
    /dev/null-style sinks, neither persists anything.

    Known, accepted gap: named-fd redirects (`{fd}>file`) aren't
    recognized, rare enough in practice not to be worth the added
    complexity here.
    """
    tokens = tokenize_command(command)
    return any(_redirects_to_a_file(sc) for sc in split_into_simple_commands(tokens))

GRAPHQL_FIELD_FLAGS = {"-f", "-F", "--raw-field", "--field"}


def _extract_graphql_query_document(simple_command):
    """Extracts the value of a `query=...` field passed to `gh api
    graphql` via `-f`/`-F`/`--raw-field`/`--field`, from one simple
    command's real tokens rather than a regex anchored on one specific
    shell-quoting style. `-f query='...'` (only the value quoted) and
    `-f 'query=...'` (the whole `key=value` pair quoted together) are
    both valid and tokenize to the exact same shape, a regex expecting
    the literal text `query=` to appear unquoted matched the first form
    and silently missed the second. Returns None if no such field is
    found. Takes one simple command, not the whole compound command, so
    a second `gh api graphql` call chained after a first one (`cmd1 &&
    cmd2`) is extracted and checked independently rather than the first
    match in the whole command winning and the second never being seen.
    """
    for i, token in enumerate(simple_command):
        if token in GRAPHQL_FIELD_FLAGS and i + 1 < len(simple_command) and simple_command[i + 1].startswith("query="):
            return simple_command[i + 1][len("query="):]
    return None


def _strip_ignored_tokens(text):
    # GraphQL's grammar treats commas and "#"-to-end-of-line comments as
    # insignificant, ignorable tokens that may legally precede the real
    # operation keyword. Stripping only whitespace let a mutation
    # prefixed with either slip past as unrecognized instead of matched.
    return re.sub(r"^(?:\s+|,+|#[^\n]*\n?)+", "", text)


def _skip_leading_fragments(query_text):
    """Skips any number of leading GraphQL fragment definitions (and the
    ignored tokens around them). A fragment isn't itself an operation,
    and one commonly precedes the real query/mutation; checking only the
    document's literal prefix treated `fragment F on X { id } mutation
    { ... }` as unrecognized (not a mutation) instead of skipping past
    the fragment to the operation that follows it.
    """
    while True:
        query_text = _strip_ignored_tokens(query_text)
        if not re.match(r"fragment\b", query_text, re.IGNORECASE):
            return query_text
        brace_index = query_text.find("{")
        if brace_index == -1:
            return query_text  # malformed; nothing more to safely skip
        depth = 0
        end = None
        for i in range(brace_index, len(query_text)):
            if query_text[i] == "{":
                depth += 1
            elif query_text[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end is None:
            return ""  # unbalanced braces; nothing safely left to check
        query_text = query_text[end:]


def _is_graphql_mutation_document(query_text):
    """True if a GraphQL query document (after skipping any leading
    fragments) is a mutation.

    Only an explicit `query` operation, or GraphQL's anonymous-query
    shorthand (a bare `{`, which the spec permits only for queries, never
    mutation/subscription), is treated as safe. Everything else,
    including an explicit mutation/subscription or a document that
    couldn't be confidently extracted, defaults to mutating: treating an
    unrecognized document as read-only risks letting a real mutation
    through unexamined.
    """
    query_text = _strip_ignored_tokens(_skip_leading_fragments(query_text))
    return not (query_text.startswith("{") or bool(re.match(r"query\b", query_text, re.IGNORECASE)))


def _is_graphql_call(simple_command):
    executable = skip_wrappers(simple_command)
    return executable[:3] == ["gh", "api", "graphql"]


def is_mutating(tool_name, tool_input):
    if tool_name in ALWAYS_MUTATING_TOOLS:
        return True
    if tool_name == "Bash":
        command = (tool_input or {}).get("command", "")
        simple_commands = split_into_simple_commands(tokenize_command(command))
        # Each `gh api graphql` call in a compound command is checked on
        # its own: GraphQL over this transport is a single mechanism for
        # two different things, reading (a `query`) and writing (a
        # `mutation`), and one simple command's query document says
        # nothing about another's. Checking the whole command as one
        # unit meant a read-only call followed by `&& gh api graphql -f
        # query='mutation {...}'` let the first match win and the
        # second, mutating call was never examined.
        for simple_command in simple_commands:
            if not _is_graphql_call(simple_command):
                continue
            query_text = _extract_graphql_query_document(simple_command)
            if query_text is None or _is_graphql_mutation_document(query_text):
                return True
        return bool(BASH_MUTATION_PATTERNS.search(command)) or has_file_redirect(command)
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
