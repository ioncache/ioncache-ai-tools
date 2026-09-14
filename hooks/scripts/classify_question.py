#!/usr/bin/env python3
"""UserPromptSubmit hook: flags a session as having a pending question.

Reads the prompt piped in on UserPromptSubmit, checks whether it contains a
question, and writes a per-session marker file that the paired PreToolUse
hook (block_pending_question.py) uses to deny tool calls until the question
has been answered in text.

Blocks on ANY question, even one that arrives alongside an instruction
("Fix the bug, why did it happen?" or "Can you check the tests?"). An
earlier version tried to detect when a "real" instruction was attached to
the question and let those through unblocked, but that check only looked
for instruction clauses *after* the last question clause, so an instruction
placed *before* the question was never caught, misclassifying exactly the
case it was meant to handle. Ordering-sensitive classifiers like that are
cheap to write and expensive to get right. Blocking every question is the
simple rule that's actually reliable: the cost is an occasional extra "yes
go ahead", which is cheaper than the classifier silently guessing wrong.
"""

import json
import pathlib
import re
import sys

# Words a genuine question typically opens with. Bare "do" is deliberately
# excluded: unlike "does"/"did", it's also the standard imperative-sentence
# auxiliary ("Do not do X", "Do the shell functions too"), and those are far
# more common in practice than a bare "Do ...?" question, so including it
# made every ordinary imperative starting with "do" a false positive.
QUESTION_STARTERS = re.compile(
    r"^\s*(what|why|how|when|where|who|which|is|are|does|did|"
    r"can|could|should|would|will|has|have|was|were)\b",
    re.IGNORECASE,
)


def has_question(text):
    text = text.strip()

    clauses = [c for c in re.split(r"(?<=[.!?])\s+|\n+", text) if c.strip()]
    if not clauses:
        return False

    return any(
        clause.rstrip().endswith("?") or QUESTION_STARTERS.match(clause)
        for clause in clauses
    )


def main():
    data = json.load(sys.stdin)
    session_id = data.get("session_id", "unknown")
    prompt = data.get("prompt", "") or ""

    flag_path = pathlib.Path(f"/tmp/.ioncache-pending-question-{session_id}")

    if has_question(prompt):
        flag_path.write_text("1")
        print(
            json.dumps(
                {
                    "additionalContext": (
                        "This message contains a question. Answer it directly "
                        "in plain text this turn. Tool calls will be blocked "
                        "until your next reply."
                    )
                }
            )
        )
    elif flag_path.exists():
        flag_path.unlink()


if __name__ == "__main__":
    main()
