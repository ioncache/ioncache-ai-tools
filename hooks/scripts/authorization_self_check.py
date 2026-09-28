#!/usr/bin/env python3
"""Self-checks for the deterministic half of the git authorization guard.

The guard has two halves. The judgment half (does this message authorize this
action, and was it typed by a human) runs inside Claude Code's agent runtime and
cannot be exercised from here. The mechanical half can be, and is: where state
lives, whether the judge can find it, who can write it, what survives a
machine-injected message, and what a malformed payload does to an authorization
already on disk.

Cases are organized by behavior, not by past bug, and both outcomes of every
check are asserted. An earlier version of this guard was signed off on tests
that exercised the writer alone. The writer was correct, the judge was told to
look somewhere else, and every authorized commit was denied. The path contract
test below exists so that cannot pass silently again.
"""
import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile
import uuid

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
import session_state  # noqa: E402
from session_state import PROMPTS, TRANSCRIPT_SUFFIX, state_file  # noqa: E402
import capture_prompt  # noqa: E402

HOOKS_JSON = pathlib.Path(SCRIPT_DIR).parent / 'hooks.json'

# Verbatim shapes of the two machine-injected message types that Claude Code
# submits through UserPromptSubmit exactly as if the user had typed them. These
# are what used to destroy an authorization the user had just given.
HANDBACK = '<agent-message from="a7872aca">\n[Subagent hand-back] The report follows:\n  # Findings\n</agent-message>'
NOTIFICATION = '<task-notification>\n<task-id>abc123</task-id>\n<status>completed</status>\n</task-notification>'


def run_hook_raw(script, payload_text):
    """Feeds a hook exactly these bytes, so a payload that is not valid JSON at
    all can be exercised. A hook must never throw whatever it is handed, so a
    non-zero exit is a failure of the test, not of the case.
    """
    subprocess.run(
        [sys.executable, os.path.join(SCRIPT_DIR, script)],
        input=payload_text,
        text=True,
        capture_output=True,
        check=True,
    )


def prompts_of(path):
    return [m['prompt'] for m in json.loads(path.read_text())['messages']]


def check_path_contract():
    """The capture hook and the judge must resolve the same file. The judge is
    an agent hook with only Read, Grep and Glob, so the only path it can build
    is one it copies from its own hook input. Both agent prompts have to name
    `transcript_path` and the exact suffix the capture hook appends, and the
    capture hook has to write exactly <transcript_path><that suffix>.

    Two earlier designs passed every other check here and still denied every
    authorized commit in a live session, because this contract was broken.
    """
    suffix = f'{TRANSCRIPT_SUFFIX}{PROMPTS}'
    prompts = [
        hook['prompt']
        for entry in json.loads(HOOKS_JSON.read_text())['hooks'].get('PreToolUse', [])
        for hook in entry.get('hooks', [])
        if hook.get('type') == 'agent' and 'git' in (hook.get('if') or '')
    ]
    assert len(prompts) == 2, f'expected the push and commit guards, found {len(prompts)}'
    for prompt in prompts:
        assert 'transcript_path' in prompt, 'the judge must derive the path from its hook input'
        assert suffix in prompt, f'the judge must be told the exact suffix {suffix}'
        assert 'scratchpad_dir' not in prompt, 'scratchpad_dir is absent in headless sessions and must not be used'
        assert '\\n' not in prompt, 'prompt paragraphs must be real newlines, not a literal backslash-n'

    with tempfile.TemporaryDirectory() as root:
        transcript = f'{root}/1234.jsonl'
        assert state_file({'transcript_path': transcript}, PROMPTS) == pathlib.Path(transcript + suffix), (
            'the capture hook must write exactly where the judge is told to look'
        )


def check_capture_behavior(root):
    transcript = f'{root}/{uuid.uuid4()}.jsonl'
    base = {'session_id': f'selfcheck-{uuid.uuid4()}', 'transcript_path': transcript}
    path = state_file(base, PROMPTS)
    assert path == pathlib.Path(f'{transcript}{TRANSCRIPT_SUFFIX}{PROMPTS}'), f'unexpected state path {path}'

    def submit(prompt):
        run_hook_raw('capture_prompt.py', json.dumps({**base, 'prompt': prompt}))

    # The success path. The captured message is what a later authorization
    # check reads, so it has to survive verbatim.
    submit('go ahead and commit')
    assert prompts_of(path) == ['go ahead and commit'], 'the prompt should be captured verbatim'

    # THE REGRESSION THIS DESIGN EXISTS FOR. A subagent hand-back and a task
    # notification both arrive through UserPromptSubmit. While only the latest
    # message was kept, either one erased the user's instruction and the next
    # guarded action was refused. Both must now land AFTER it.
    submit(HANDBACK)
    submit(NOTIFICATION)
    assert prompts_of(path) == ['go ahead and commit', HANDBACK, NOTIFICATION], (
        'a machine-injected message must not displace the human instruction'
    )

    # A later human message lands last, which is what expires an old
    # authorization: it stops being the most recent human message.
    submit('actually just run the tests')
    assert prompts_of(path)[-1] == 'actually just run the tests'

    # Nothing consumes the list, so a second guarded action in the same turn
    # still finds the instruction. Refusing the second commit of a turn was the
    # other half of the reported bug.
    assert 'go ahead and commit' in prompts_of(path), 'one instruction covers the turn'

    # Bounded, so a long session cannot grow the file without limit.
    for i in range(capture_prompt.MAX_MESSAGES + 5):
        submit(f'message {i}')
    captured = prompts_of(path)
    assert len(captured) == capture_prompt.MAX_MESSAGES, f'should cap at {capture_prompt.MAX_MESSAGES}'
    assert captured[-1] == f'message {capture_prompt.MAX_MESSAGES + 4}', 'the newest message should be kept'

    assert stat.S_IMODE(path.stat().st_mode) == 0o600, 'the prompts file should be owner-only'

    # A payload that will not parse discards what came before instead of
    # leaving it to be read as current, using the locating fields recovered
    # from the raw text.
    submit('go ahead and push')
    run_hook_raw('capture_prompt.py',
                 '{"session_id": "%s", "transcript_path": "%s", "prompt": not-json}'
                 % (base['session_id'], transcript))
    assert not path.exists(), 'a payload that fails to parse should discard the previous state'

    # Payloads with nothing recoverable must still exit cleanly.
    run_hook_raw('capture_prompt.py', 'garbage')
    run_hook_raw('capture_prompt.py', '')

    # A corrupt state file is treated as empty rather than fatal.
    path.write_text('{ not json at all')
    submit('commit it')
    assert prompts_of(path) == ['commit it'], 'a corrupt state file should not stop a new capture'


def check_location_safety():
    uid_dir = session_state.TMP_DIR  # /tmp/.ioncache-<uid>
    name = f'{TRANSCRIPT_SUFFIX}{PROMPTS}'

    # No transcript path at all (Codex, or an unusual host): the fallback is
    # plain /tmp on Linux and macOS alike, always usable. An earlier version
    # vetted /tmp's permissions, refused Linux's shared sticky /tmp, and so
    # returned None on every Linux host, silently switching the pending-question
    # guard off. Its contents are temporary and gone after a reboot.
    fallback = state_file({'session_id': 'abc'}, PROMPTS)
    assert fallback == uid_dir / f'{PROMPTS}-abc', f'no transcript path should fall back to /tmp, got {fallback}'
    assert uid_dir.is_dir(), 'the fallback directory should exist once resolved'

    # Our own /tmp subdirectory is checked even though /tmp is not. Exercised
    # by pointing the module at a stand-in path, so the real directory is never
    # touched. (An entry owned by another account is the case this exists for,
    # but a non-root test cannot create one; a symlink and a directory others
    # can write into stand in for it.)
    real = session_state.TMP_DIR
    try:
        with tempfile.TemporaryDirectory() as root:
            root = pathlib.Path(root)
            session_state.TMP_DIR = root / 'ok'
            assert state_file({'session_id': 'x'}, PROMPTS) == root / 'ok' / f'{PROMPTS}-x', (
                'a fresh subdirectory should be created and used'
            )

            (root / 'elsewhere').mkdir()
            (root / 'link').symlink_to(root / 'elsewhere')
            session_state.TMP_DIR = root / 'link'
            assert state_file({'session_id': 'x'}, PROMPTS) is None, 'a symlinked subdirectory must not be used'

            (root / 'open').mkdir()
            (root / 'open').chmod(0o777)
            session_state.TMP_DIR = root / 'open'
            assert state_file({'session_id': 'x'}, PROMPTS) is None, (
                'a subdirectory others can write into must not be used'
            )
    finally:
        session_state.TMP_DIR = real

    # A falsy session id normalizes to one path for every caller.
    assert state_file({'session_id': None}, PROMPTS) == state_file({'session_id': ''}, PROMPTS)

    with tempfile.TemporaryDirectory() as root:
        root = pathlib.Path(root)  # mkdtemp creates it 0700

        # The normal case: the transcript's directory exists and is private.
        ok = root / 'project'
        ok.mkdir(mode=0o755)
        assert state_file({'transcript_path': str(ok / 's.jsonl')}, PROMPTS) == ok / f's.jsonl{name}'

        # A missing transcript directory is never created, because it belongs
        # to Claude Code. The state falls back instead.
        missing = root / 'absent'
        assert state_file({'transcript_path': str(missing / 's.jsonl'), 'session_id': 'x'}, PROMPTS).parent == uid_dir
        assert not missing.exists(), "Claude Code's directory must not be created by a hook"

        # A directory others can write into is never used: someone could plant
        # a forged authorization there before the capture hook runs.
        shared = root / 'shared'
        shared.mkdir()
        shared.chmod(0o777)
        assert state_file({'transcript_path': str(shared / 's.jsonl'), 'session_id': 'x'}, PROMPTS).parent == uid_dir, (
            'a group- or world-writable directory must not be used'
        )

        # Nor a symlink standing in for one.
        link = root / 'link'
        link.symlink_to(ok)
        assert state_file({'transcript_path': str(link / 's.jsonl'), 'session_id': 'x'}, PROMPTS).parent == uid_dir, (
            'a symlinked directory must not be followed'
        )



def main():
    check_path_contract()
    with tempfile.TemporaryDirectory() as root:
        check_capture_behavior(root)
    check_location_safety()
    print('All authorization self-checks passed.')


if __name__ == '__main__':
    main()
