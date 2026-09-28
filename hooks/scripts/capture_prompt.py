#!/usr/bin/env python3
"""UserPromptSubmit hook: records recent prompts so an authorization check can
later read what the user actually asked for.

The authorization agent hook was once handed the whole transcript and asked to
work out which message was "current". It got that wrong repeatedly. Writing the
prompts to a known path removes the navigation step: the judge reads a short,
ordered list and has no access to anything else.

This keeps a LIST rather than one message, and that is the whole fix for a real
defect. UserPromptSubmit fires for machine-injected messages too, subagent
hand-back reports and background task notifications among them. While it stored
only the latest message, any background agent finishing mid-turn overwrote the
user's instruction with its own report, and the very next guarded action was
denied with "the captured message is a task-notification, not a user
instruction". The user had authorized it seconds earlier and had no way to see
why it vanished.

Keeping the last few messages means a machine message can no longer displace a
human one; it just lands after it. Deciding which entries are human is left to
the judge reading them, which is a thing a language model does well and a
pattern list does badly.

Nothing here expires the list on a turn boundary, deliberately. An instruction
stops authorizing as soon as the user says something else, because then it is no
longer the most recent human message. That is the same rule, enforced by the
data rather than by guessing where a turn began, and it survives a subagent
hand-back arriving in the middle.
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from session_state import PROMPTS, state_file, write_private  # noqa: E402

# Enough to hold a real instruction plus the machine chatter that can follow it,
# small enough that the judge reads a short list rather than a transcript. The
# bounded size is also what keeps the file from growing for the life of a
# session.
MAX_MESSAGES = 10


def load_messages(path):
    """Existing messages, or an empty list if the file is missing or unusable.

    A corrupt file is treated as empty rather than fatal: losing history costs
    the user one restated instruction, while raising here would stall the turn.
    """
    try:
        data = json.loads(path.read_text())
    except Exception:
        return []
    messages = data.get("messages")
    return messages if isinstance(messages, list) else []


def capture(hook_input):
    path = state_file(hook_input, PROMPTS)
    if path is None:
        # Nowhere safe to record it. Raising sends the caller down its discard
        # path, and the judge then finds no file and denies, which is the
        # right outcome for a guard that cannot see its evidence.
        raise RuntimeError("no private location for session state")
    prompt = hook_input.get("prompt", "") or ""
    messages = load_messages(path)
    messages.append({"prompt": prompt, "captured_at": time.time()})
    write_private(path, json.dumps({"messages": messages[-MAX_MESSAGES:]}))


def locator_from(raw):
    """Best-effort recovery of the fields that locate session state, from a
    payload that would not parse. Used only to discard stale state, never to
    authorize anything, so a loose pattern is the right amount of effort: if it
    finds nothing there is nothing to discard under that name anyway.
    """
    found = {}
    for field in ("session_id", "transcript_path"):
        match = re.search(r'"%s"\s*:\s*"([^"]+)"' % field, raw)
        if match:
            found[field] = match.group(1)
    return found


def discard(hook_input):
    try:
        path = state_file(hook_input, PROMPTS)
        if path is not None:
            path.unlink(missing_ok=True)
    except Exception:
        pass


def main():
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except Exception:
        # Fail closed. Anything that stops this turn being recorded must also
        # discard what came before, or the judge reads older messages as
        # current. Parsing used to sit outside this guard, so a malformed
        # payload silently left the earlier authorization standing.
        discard(locator_from(raw))
        return
    try:
        capture(data)
    except Exception:
        discard(data)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # A throwing hook stalls the session, so nothing propagates out of here.
        # Every failure path inside main() already discards the state.
        pass
    sys.exit(0)
