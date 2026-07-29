#!/usr/bin/env python3
"""Codex hook: require documentation lookup before docs-dependent work."""

import json
import os
import pathlib
import re
import sys

STATE_PATH = pathlib.Path(
    os.environ.get("PLUGIN_DATA")
    or os.environ.get("CLAUDE_PLUGIN_DATA")
    or "/tmp"
) / "docs-first-state.json"

DOCS_REQUIRED_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\bofficial docs?\b",
        r"\bdocumentation\b",
        r"\bmanual\b",
        r"\bapi reference\b",
        r"\bopenapi\b",
        r"\bread the docs\b",
        r"\bdocs first\b",
        r"\blook (?:up|into)\b.*\b(docs?|documentation|manual|reference)\b",
        r"\bverify\b.*\b(docs?|documentation|manual|reference)\b",
        r"\b(latest|current|up[- ]to[- ]date)\b.*\b(api|sdk|library|framework|package|tool|docs?|documentation|config|configuration|settings?|option|flag|syntax|guide)\b",
    ]
]

DOCS_LOOKUP_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"https?://[^\s\"']*(docs\.|developers\.|developer\.|reference\.|manual\.)[^\s\"']*",
        r"https?://[^\s\"']*/((docs?)|(documentation)|(manual)|(reference)|(api-reference)|(openapi))(/|[?#]|$)",
        r"\bdomains?\b[^\n]*\b(docs\.|developers\.|developer\.|reference\.|manual\.)",
        r"\b(search_query|open|click)\b[\s\S]*\b(docs?|documentation|manual|reference|openapi)\b",
        r"\bfetch[-_ ]?[a-z0-9_-]*manual\b",
    ]
]


def scope_key(payload):
    return payload.get("cwd") or os.getcwd()


def read_state():
    try:
        return json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        return {"scopes": {}}


def write_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


def set_scope(state, key, **patch):
    current = state["scopes"].get(
        key,
        {"docsRequired": False, "docsSatisfied": False},
    )
    state["scopes"][key] = {**current, **patch}
    write_state(state)


def requires_docs(prompt):
    return any(pattern.search(prompt or "") for pattern in DOCS_REQUIRED_PATTERNS)


def looks_like_docs_lookup(raw):
    return any(pattern.search(raw or "") for pattern in DOCS_LOOKUP_PATTERNS)


def hook_context(event, message):
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": event,
                    "additionalContext": message,
                }
            }
        )
    )


def user_prompt_submit(payload):
    state = read_state()
    key = scope_key(payload)
    required = requires_docs(payload.get("prompt", ""))
    set_scope(state, key, docsRequired=required, docsSatisfied=False)

    if required:
        hook_context(
            "UserPromptSubmit",
            "DOCS_FIRST required for this turn. Perform an official documentation lookup before other tool work.",
        )


def pre_tool_use(payload, raw):
    state = read_state()
    key = scope_key(payload)
    record = state["scopes"].get(key, {})

    if not record.get("docsRequired") or record.get("docsSatisfied"):
        return

    if looks_like_docs_lookup(raw):
        set_scope(state, key, docsSatisfied=True)
        hook_context(
            "PreToolUse",
            "Docs-first guard satisfied for this turn. Documentation lookup detected.",
        )
        return

    sys.stderr.write(
        "Docs-first guard: perform the relevant documentation lookup first.\n"
        "Allowed first step: query or open the actual documentation/reference/manual for the topic in the prompt.\n"
    )
    sys.exit(2)


def self_test():
    assert requires_docs("check the latest sdk option")
    assert requires_docs("docs first: how do Codex hooks work?")
    assert not requires_docs("fix the failing tests")
    assert looks_like_docs_lookup('{"command":"node /x/fetch-codex-manual.mjs"}')
    assert looks_like_docs_lookup('{"search_query":[{"q":"official documentation"}]}')


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        self_test()
        return

    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = {}

    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "user-prompt-submit":
        user_prompt_submit(payload)
    elif mode == "pre-tool-use":
        pre_tool_use(payload, raw)
    else:
        sys.stderr.write("Usage: docs_first_guard.py user-prompt-submit|pre-tool-use\n")
        sys.exit(2)


if __name__ == "__main__":
    main()
