#!/usr/bin/env python3
"""Stop hook: blocks finishing a turn if the assistant wrote an em-dash in it.

Reads last_assistant_message from the hook input instead of parsing
transcript_path by hand. Both Claude Code and Codex document this field as
the correct source for "the current turn's final assistant text": the
transcript file is written asynchronously and documented as lagging the
in-memory conversation, so a hook that parses it can miss text that hasn't
been flushed yet. Claude Code's own docs recommend last_assistant_message
on Stop specifically to avoid that race, and Codex exposes the same field
name for the same event. It also sidesteps a subtler problem an earlier
version of this file had to work around: transcript entries for tool
results are also type="user" in Claude Code's transcript format, so
distinguishing "the last real user prompt" from "the last tool result" by
hand was easy to get wrong, and Codex's transcript format isn't documented
to match Claude Code's at all. Using last_assistant_message means the
harness has already scoped the text correctly, for both tools, without any
of that.

Builds the target character from its code point rather than embedding it as
a literal in source, so this file can't trip hooks/rules/fix_emdash.py (the
paired PreToolUse rule, run by hooks/scripts/rule_engine.py) when it is
itself written or edited.
"""

import json
import sys

EM_DASH = chr(0x2014)


def main():
    try:
        input_data = json.load(sys.stdin)
    except ValueError:
        sys.exit(0)

    text = input_data.get("last_assistant_message") or ""

    if EM_DASH in text:
        idx = text.index(EM_DASH)
        snippet = text[max(0, idx - 40) : idx + 20]
        print(
            json.dumps(
                {
                    "decision": "block",
                    "reason": (
                        "This turn's response contains an em-dash, which is "
                        "banned in all output per project/user instructions. "
                        f"Found near: ...{snippet}... "
                        "Rewrite the response using a comma, period, "
                        "parentheses, or colon instead, then stop again."
                    ),
                }
            )
        )
    else:
        print(json.dumps({}))

    sys.exit(0)


if __name__ == "__main__":
    main()
