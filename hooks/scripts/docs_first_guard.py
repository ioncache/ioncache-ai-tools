#!/usr/bin/env python3
"""UserPromptSubmit hook: reminds the model to verify library/API/tool/
service specifics against a current, real source instead of training data.

Earlier versions tried to detect *when* this was needed: first by
regexing the prompt for doc-related keywords, which missed any request
that doesn't mention documentation at all (e.g. "add pagination to this
endpoint"); then by checking the project's own dependency manifest,
which missed anything not already a dependency (a prospective package,
an alternative being evaluated). Both misses are real, not hypothetical:
an already-integrated SDK got a wrong answer because it didn't match
the pinned version in use. Since almost any substantive engineering
prompt touches some named external thing, a classifier accurate enough
to actually cover this converges on firing nearly every turn anyway, so
there's no real savings left in trying to classify at all. This always
reminds instead: the reminder is a small, fixed cost, cheaper than the
false confidence of a classifier with its own permanent blind spots,
and it never denies or blocks anything, so it can't brick a session the
way a PreToolUse gate on this same logic once did.
"""

import json
import sys

REMINDER = (
    "Never state or rely on specifics about any library, API, framework, "
    "SDK, CLI tool, or service (method signatures, config syntax, flags, "
    "behavior, version differences) from training data or memory. Always "
    "verify with a real, current lookup (WebFetch, WebSearch, or the "
    "context7 MCP) first, whether answering a question or writing code, "
    "even for something already used in this project, and even when "
    "confident. Training data can be stale or simply wrong for the exact "
    "version actually in use."
)


def main():
    try:
        json.load(sys.stdin)
    except ValueError:
        pass
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": REMINDER,
                }
            }
        )
    )


if __name__ == "__main__":
    main()
