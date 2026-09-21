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
import os
import pathlib
import re
import sys
import time

PROMPT_FILE = "/tmp/.ioncache-last-prompt-{session_id}"

# The capture holds the user's raw message, which can contain anything they
# pasted, and /tmp is shared with every other account on the machine. The file
# is created 0600 and O_NOFOLLOW so a pre-planted symlink cannot redirect the
# write, rather than leaving confidentiality to whatever umask the hook
# happens to inherit.
CREATE_FLAGS = os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW
CREATE_MODE = 0o600


def path_for(session_id):
    return pathlib.Path(PROMPT_FILE.format(session_id=session_id or "unknown"))


def write_capture(session_id, prompt):
    path = path_for(session_id)
    fd = os.open(path, CREATE_FLAGS, CREATE_MODE)
    try:
        # A file that already existed keeps its old mode, so set it explicitly
        # rather than trusting the create mode to have applied.
        os.fchmod(fd, CREATE_MODE)
        os.write(fd, json.dumps({"prompt": prompt, "captured_at": time.time()}).encode())
    finally:
        os.close(fd)


def session_id_from(raw):
    """Best-effort session id from a payload that would not parse. Used only to
    delete a stale capture, never to authorize anything, so a loose regex is
    the right amount of effort: if it finds nothing there is nothing to delete
    under that name anyway.
    """
    match = re.search(r'"session_id"\s*:\s*"([^"]+)"', raw)
    return match.group(1) if match else None


def main():
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except Exception:
        # Fail closed. Anything that stops this turn from being recorded must
        # also destroy the previous turn's capture, or the judge reads a stale
        # message as if it were current and an old instruction authorizes a
        # new action. Parsing used to sit outside this guard, so a malformed
        # payload silently left the earlier authorization standing.
        path_for(session_id_from(raw)).unlink(missing_ok=True)
        return
    session_id = data.get("session_id", "unknown")
    try:
        write_capture(session_id, data.get("prompt", "") or "")
    except Exception:
        path_for(session_id).unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # A throwing hook stalls the session, so nothing propagates out of
        # here. Every failure path inside main() already deletes the capture.
        pass
    sys.exit(0)
