#!/usr/bin/env python3
"""Self-checks for the deterministic halves of the git authorization guard.

The guard has two halves. The judgment half (does this message authorize this
action) runs inside Claude Code's agent runtime and cannot be exercised from
here. The mechanical half can be, and is: capturing the prompt, truncating a
previous turn's capture, and recognizing a guarded action well enough to
consume the authorization afterwards.

Cases are organized by behavior, not by past bug, and both outcomes of every
check are asserted. An earlier version of this guard was signed off on a test
set drawn entirely from reported symptoms, which meant the success path, the
one the feature exists to provide, was never run once.
"""
import json
import os
import pathlib
import subprocess
import sys
import uuid

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
import consume_authorization  # noqa: E402

PROMPT_FILE = "/tmp/.ioncache-last-prompt-{session_id}"


def run_hook(script, payload):
    subprocess.run(
        [sys.executable, os.path.join(SCRIPT_DIR, script)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
    )


def main():
    # runs_guarded_action: a real guarded action is recognized. These are the
    # cells that must be caught for the authorization to be consumed at all.
    guarded = [
        ('git push', 'a bare push'),
        ('git commit -m "x"', 'a bare commit'),
        ('git -C /some/dir push origin main', 'a global option before the subcommand'),
        ('git --no-pager commit -m "x"', 'a bare global flag before the subcommand'),
        ('/usr/bin/git push', 'a path-qualified git'),
        ('timeout 5 git push', 'a recognized wrapper command'),
        ('git status && git push', 'the second command in a chain'),
    ]
    for command, label in guarded:
        assert consume_authorization.runs_guarded_action(command) is True, f'should recognize {label}: {command!r}'

    # runs_guarded_action: everything that is not a guarded action. A false
    # positive here consumes an authorization the user has not spent, so the
    # negative cases matter as much as the positive ones.
    unguarded = [
        ('git log --oneline -1', 'git log'),
        ('git status --porcelain', 'git status'),
        ('git diff', 'git diff'),
        ('echo "reminder: git push later"', 'the words quoted inside an echo'),
        ('git log origin/never-push-without-asking', 'a branch name containing the verb'),
        ('gh api repos/o/r/pulls/1/replies -f body="$(cat f)"', 'an unrelated program with a substitution'),
        ('curl -d "$(cat payload.json)" https://example.com', 'curl with a substitution'),
        ('ls -la', 'an unrelated command'),
    ]
    for command, label in unguarded:
        assert consume_authorization.runs_guarded_action(command) is False, f'should not recognize {label}: {command!r}'

    # A known, deliberate gap, asserted so that it stays visible rather than
    # being rediscovered later: shlex sees one opaque token, so the tokenizer
    # cannot see through shell expansion. Missing here only leaves an
    # authorization unconsumed, it never denies anything.
    assert consume_authorization.runs_guarded_action('git${IFS}push') is False, (
        'documented gap: the tokenizer cannot see through ${IFS} expansion'
    )

    session_id = f'selfcheck-{uuid.uuid4()}'
    path = pathlib.Path(PROMPT_FILE.format(session_id=session_id))
    try:
        # capture_prompt: the success path. The captured message is what a
        # later authorization check will read, so it must survive verbatim.
        run_hook('capture_prompt.py', {'session_id': session_id, 'prompt': 'go ahead and commit'})
        assert path.exists(), 'capture should write the prompt file'
        assert json.loads(path.read_text())['prompt'] == 'go ahead and commit', 'prompt should be captured verbatim'

        # capture_prompt: a new prompt replaces the previous one. This is what
        # makes an earlier turn's authorization unusable without anything
        # having to reason about where a turn began.
        run_hook('capture_prompt.py', {'session_id': session_id, 'prompt': 'what does this do?'})
        assert json.loads(path.read_text())['prompt'] == 'what does this do?', 'a new prompt should replace the old one'

        # consume_authorization: a guarded action spends the authorization,
        # so a second action in the same turn has none.
        run_hook('consume_authorization.py',
                 {'session_id': session_id, 'tool_name': 'Bash', 'tool_input': {'command': 'git push'}})
        assert not path.exists(), 'a guarded action should consume the captured prompt'

        # consume_authorization: an unguarded command leaves it alone.
        run_hook('capture_prompt.py', {'session_id': session_id, 'prompt': 'commit this'})
        run_hook('consume_authorization.py',
                 {'session_id': session_id, 'tool_name': 'Bash', 'tool_input': {'command': 'git status'}})
        assert path.exists(), 'an unguarded command should leave the captured prompt in place'

        # consume_authorization: a non-Bash tool leaves it alone.
        run_hook('consume_authorization.py',
                 {'session_id': session_id, 'tool_name': 'Read', 'tool_input': {'file_path': '/tmp/x'}})
        assert path.exists(), 'a non-Bash tool should leave the captured prompt in place'
    finally:
        path.unlink(missing_ok=True)

    print('All authorization self-checks passed.')


if __name__ == '__main__':
    main()
