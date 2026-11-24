import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

import review_ledger
from self_check_support import fixed_git_metadata, fixed_storage_membership, run_main


def test_invocation_restores_process_state_after_failure(tmp_path):
    before = (Path.cwd(), dict(os.environ), sys.argv, sys.stdin, signal.getsignal(signal.SIGALRM))

    def fail():
        assert Path.cwd() == tmp_path
        assert os.environ == {"FIXTURE": "isolated"}
        assert sys.argv == ["fixture.py", "argument"]
        assert sys.stdin.read() == "candidate"
        signal.signal(signal.SIGALRM, lambda *_: None)
        raise RuntimeError("fixture failure")

    with pytest.raises(RuntimeError, match="fixture failure"):
        run_main(SimpleNamespace(__file__="fixture.py", main=fail), ["argument"],
                 cwd=tmp_path, env={"FIXTURE": "isolated"}, input="candidate")
    assert (Path.cwd(), dict(os.environ), sys.argv, sys.stdin, signal.getsignal(signal.SIGALRM)) == before


@pytest.mark.parametrize("exit_code", [None, 2, "invalid candidate"])
def test_invocation_keeps_exit_and_protocol_streams_separate(exit_code):
    def respond():
        print('{"accepted": false}')
        print("diagnostic", file=sys.stderr)
        raise SystemExit(exit_code)

    result = run_main(SimpleNamespace(__file__="fixture.py", main=respond))
    assert result.returncode == (1 if isinstance(exit_code, str) else exit_code or 0)
    assert result.stdout == '{"accepted": false}\n'
    assert result.stderr == "diagnostic\n" + ("invalid candidate\n" if exit_code == "invalid candidate" else "")


def test_stable_snapshot_keeps_live_content_and_rejects_membership_changes(tmp_path, repository_seeds):
    root = tmp_path / "repository"
    shutil.copytree(repository_seeds["ReviewLedgerTests"], root)
    with pytest.raises(AssertionError, match="file membership"):
        with fixed_git_metadata():
            initial = review_ledger.snapshot(root)
            (root / "app.txt").write_text("changed\n")
            assert review_ledger.snapshot(root)["files"]["app.txt"] != initial["files"]["app.txt"]
            (root / "new.txt").write_text("untracked\n")
    assert "new.txt" in review_ledger.snapshot(root)["files"]


def test_stable_snapshot_rejects_index_changes(tmp_path, repository_seeds):
    root = tmp_path / "repository"
    shutil.copytree(repository_seeds["ReviewLedgerTests"], root)
    with pytest.raises(AssertionError, match="Git metadata"):
        with fixed_git_metadata():
            review_ledger.snapshot(root)
            (root / "app.txt").write_text("staged\n")
            subprocess.run(["git", "-C", str(root), "add", "app.txt"], check=True)


def test_stable_storage_rejects_a_repository_created_in_the_fixture(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    with pytest.raises(review_ledger.LedgerError, match="outside every repository"):
        with fixed_storage_membership():
            assert review_ledger.external_directory(store) == store
            subprocess.run(["git", "init", "-q", str(store)], check=True)
    with pytest.raises(review_ledger.LedgerError, match="outside every repository"):
        review_ledger.external_directory(store)
