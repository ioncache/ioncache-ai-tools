#!/usr/bin/env python3
"""UserPromptSubmit hook: records the user's typed prompt so an authorization
check can later read exactly that one message.

The authorization agent hook was previously handed the whole transcript and
asked to work out which message was "current". It got that wrong repeatedly,
citing an unrelated skill's instructions, and the assistant's own earlier
question, as grounds to deny a commit the user had just authorized. Writing
the prompt to a known path removes the navigation step entirely: the judge
reads one message and has no access to anything else.

Truncating on every prompt is also what makes an earlier turn's authorization
impossible to reuse. Nothing has to reason about turn boundaries for that to
hold.
"""
import json
import pathlib
import sys
import time

PROMPT_FILE = "/tmp/.ioncache-last-prompt-{session_id}"


def capture(data):
    path = pathlib.Path(PROMPT_FILE.format(session_id=data.get("session_id", "unknown")))
    path.write_text(json.dumps({"prompt": data.get("prompt", ""), "captured_at": time.time()}))


def main():
    data = json.load(sys.stdin)
    try:
        capture(data)
    except Exception:
        # Fail closed: an authorization that cannot be recorded must not fall
        # back to whatever the previous turn left behind.
        pathlib.Path(PROMPT_FILE.format(session_id=data.get("session_id", "unknown"))).unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # A throwing hook stalls the session, so this never propagates. If the
        # hook fails before it can even parse its input, the previous turn's
        # file survives and the judge would read it as current. That residual
        # is documented in README rather than papered over.
        pass
    sys.exit(0)
