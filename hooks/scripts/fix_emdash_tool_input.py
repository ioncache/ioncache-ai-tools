#!/usr/bin/env python3
"""PreToolUse hook: silently rewrites em-dashes in Bash/Edit/Write/MultiEdit
tool input before the tool runs, instead of blocking and forcing a retry.

Replaces the earlier hookify.block-emdash-*.local.md rules, which denied the
call outright. PreToolUse hooks support returning updatedInput to mutate the
call in place, so the fix can happen silently with no extra turn, unlike the
Stop hook (block_emdash_turn.py), which has no such field and can only block
and force a full retry, since it fires after the text is already generated.

updatedInput REPLACES the tool_input object wholesale rather than merging
into it, so it must always carry every field the tool's schema requires
(file_path, old_string, etc.), not just the field being changed. Returning
a partial object like {"new_string": ...} drops the other required fields
and fails schema validation, crashing the tool call outright instead of
fixing it. Always start from a copy of the original tool_input and set the
fixed field(s) on top of it.

Uses \\s* (zero or more), not \\s+, around the dash: an em-dash with no
surrounding whitespace, or one at the very start/end of a string, would not
match \\s+ and would pass through unfixed.

Builds the target character from its code point rather than embedding it as a
literal in source, so this file itself never contains the banned byte (which
would otherwise trip the very rule this file replaced, back when that rule
was still active).
"""

import json
import re
import sys

EM_DASH = chr(0x2014)
EM_DASH_PATTERN = re.compile(r"\s*" + EM_DASH + r"\s*")
REPLACEMENT = ", "


def fix(text):
    return EM_DASH_PATTERN.sub(REPLACEMENT, text)


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    tool_input = dict(data.get("tool_input", {}) or {})
    changed = False

    if tool_name == "Bash":
        command = tool_input.get("command", "")
        if EM_DASH in command:
            tool_input["command"] = fix(command)
            changed = True

    elif tool_name == "Write":
        content = tool_input.get("content", "")
        if EM_DASH in content:
            tool_input["content"] = fix(content)
            changed = True

    elif tool_name == "Edit":
        new_string = tool_input.get("new_string", "")
        if EM_DASH in new_string:
            tool_input["new_string"] = fix(new_string)
            changed = True

    elif tool_name == "MultiEdit":
        fixed_edits = []
        for edit in tool_input.get("edits", []):
            new_string = edit.get("new_string", "")
            if EM_DASH in new_string:
                changed = True
                fixed_edits.append({**edit, "new_string": fix(new_string)})
            else:
                fixed_edits.append(edit)
        if changed:
            tool_input["edits"] = fixed_edits

    if not changed:
        sys.exit(0)

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "updatedInput": tool_input,
                },
                "systemMessage": "Auto-fixed em-dash(es) in tool input before execution.",
            }
        )
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
