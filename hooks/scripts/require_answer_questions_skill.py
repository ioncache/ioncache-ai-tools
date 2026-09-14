#!/usr/bin/env python3
"""UserPromptSubmit hook: tells the assistant to apply the
ioncache-ai-tools:answer-questions skill whenever the prompt was a
question.

Paired with classify_question.py, which must run first in the same
UserPromptSubmit event and writes a per-session marker file when the
prompt reads as a question. This hook only reads that marker; it does
not re-classify the prompt itself, since classify_question.py's own
question-detection heuristic is already the single source of truth
block_pending_question.py depends on, and re-implementing it here would
just be a second place for the two classifications to drift apart.
"""

import json
import pathlib
import sys


def main():
    data = json.load(sys.stdin)
    session_id = data.get("session_id", "unknown")

    flag_path = pathlib.Path(f"/tmp/.ioncache-pending-question-{session_id}")
    if not flag_path.exists():
        return

    print(
        json.dumps(
            {
                "additionalContext": (
                    "This prompt contains a question. Before writing any "
                    "other output, load and apply the "
                    "ioncache-ai-tools:answer-questions skill to the "
                    "response."
                )
            }
        )
    )


if __name__ == "__main__":
    main()
