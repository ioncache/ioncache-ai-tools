#!/usr/bin/env python3
"""Stop hook: blocks finishing a turn if the assistant wrote an em-dash in it.

Scans assistant text since the last real user prompt, but only the portion
not already scanned by a previous invocation of this hook within the same
turn. A blocked Stop doesn't erase the text that caused it. Without this, a
turn with several tool calls and an em-dash near the start would re-flag
that same already-sent, already-seen text on every retry forever, since
transcript lines already shown to the user can't be un-written, even after
the actual new text is clean. A per-session marker file records how far the
previous invocation scanned, plus which real user prompt was current when
it did; a stale marker (from before the current user prompt) is ignored, so
a fresh user turn always rescans from the start of that turn.

Tool results are also stored as type="user"/role="user" entries (that's how
the underlying API represents a tool result being returned to the model),
distinguished only by a top-level "toolUseResult" key. Matching on
type/role alone would treat the last tool result, not the last real prompt,
as the turn boundary, which excludes almost the entire turn on any response
that calls a tool. Real user prompts never carry "toolUseResult".

Builds the target character from its code point rather than embedding it as
a literal in source, so this file can't trip fix_emdash_tool_input.py (the
paired PreToolUse hook) when it is itself written or edited.
"""

import json
import pathlib
import sys

EM_DASH = chr(0x2014)


def is_real_user_message(entry):
    return (
        entry.get("type") == "user"
        and entry.get("message", {}).get("role") == "user"
        and "toolUseResult" not in entry
    )


def read_entries(transcript_path):
    try:
        with open(transcript_path, "r") as f:
            lines = f.readlines()
    except (IOError, OSError):
        return []

    entries = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    return entries


def find_last_user_index(entries):
    last_user_index = -1
    for i, entry in enumerate(entries):
        if is_real_user_message(entry):
            last_user_index = i
    return last_user_index


def extract_text(entries, start):
    texts = []
    for entry in entries[start:]:
        if entry.get("type") != "assistant":
            continue
        for block in entry.get("message", {}).get("content", []):
            if block.get("type") == "text":
                texts.append(block.get("text", ""))
    return "\n".join(texts)


def load_marker(marker_path):
    try:
        data = json.loads(marker_path.read_text())
        return data.get("last_user_index", -1), data.get("scanned_upto", -1)
    except (IOError, OSError, ValueError):
        return -1, -1


def save_marker(marker_path, last_user_index, scanned_upto):
    marker_path.write_text(
        json.dumps({"last_user_index": last_user_index, "scanned_upto": scanned_upto})
    )


def main():
    try:
        input_data = json.load(sys.stdin)
    except ValueError:
        sys.exit(0)

    transcript_path = input_data.get("transcript_path")
    if not transcript_path:
        sys.exit(0)

    entries = read_entries(transcript_path)
    if not entries:
        sys.exit(0)

    last_user_index = find_last_user_index(entries)
    session_id = input_data.get("session_id", "unknown")
    marker_path = pathlib.Path(f"/tmp/.claude-emdash-scanned-{session_id}")

    stored_user_index, scanned_upto = load_marker(marker_path)
    if stored_user_index == last_user_index:
        scan_from = max(scanned_upto + 1, last_user_index + 1)
    else:
        scan_from = last_user_index + 1

    text = extract_text(entries, scan_from)
    save_marker(marker_path, last_user_index, len(entries) - 1)

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
