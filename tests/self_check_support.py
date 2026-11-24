from contextlib import contextmanager, redirect_stderr, redirect_stdout
import copy
import io
import importlib
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch


def uses_process(test):
    method = getattr(test, test._testMethodName, None)
    return any(
        mark.name == "process" and mark.kwargs.get("helpers", True)
        for mark in getattr(method, "pytestmark", ())
    )


@contextmanager
def invocation_state(module, args, cwd, env, stdin):
    directory = Path.cwd()
    handler = signal.getsignal(signal.SIGALRM)
    timer = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()
    try:
        with (
            patch.object(sys, "argv", [str(module.__file__), *map(str, args)]),
            patch.object(sys, "stdin", io.StringIO(stdin or "")),
            patch.dict(os.environ, env if env is not None else os.environ.copy(), clear=True),
        ):
            if cwd is not None:
                os.chdir(cwd)
            yield
    finally:
        os.chdir(directory)
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, handler)
        if timer[0]:
            signal.setitimer(
                signal.ITIMER_REAL, max(0.000001, timer[0] - (time.monotonic() - started)), timer[1],
            )


def run_main(module, args=(), *, cwd=None, env=None, input=None, process=False):
    command = [sys.executable, str(module.__file__), *map(str, args)]
    if process:
        return subprocess.run(
            command, cwd=cwd, env=env, input=input, text=True, capture_output=True, timeout=30,
        )
    stdout, stderr = io.StringIO(), io.StringIO()
    with (
        invocation_state(module, args, cwd, env, input),
        redirect_stdout(stdout),
        redirect_stderr(stderr),
    ):
        try:
            code = module.main()
        except SystemExit as error:
            code = error.code
        if isinstance(code, str):
            print(code, file=sys.stderr)
            code = 1
    return subprocess.CompletedProcess(command, code or 0, stdout.getvalue(), stderr.getvalue())


@contextmanager
def inprocess_hooks():
    import hook_adapter_common

    modules = {
        name: importlib.import_module(name)
        for name in ("guidance", "block_pending_question", "rule_engine", "docs_cache")
    }

    def run(command, **kwargs):
        script = Path(command[1])
        module = modules.get(script.stem)
        if module is None or script.resolve() != Path(module.__file__).resolve():
            return subprocess.run(command, **kwargs)
        return run_main(module, command[2:], cwd=kwargs.get("cwd"), input=kwargs.get("input"))

    with patch.object(hook_adapter_common, "subprocess", SimpleNamespace(run=run)):
        yield


@contextmanager
def fixed_git_metadata():
    import review_ledger

    snapshot = review_ledger.snapshot
    baselines = {}

    def capture(root, folder=None):
        if root not in baselines:
            baselines[root] = snapshot(root)
        current = copy.deepcopy(baselines[root])
        current["files"] = {
            name: entry for name in current["files"]
            if (entry := review_ledger.file_entry(root, name, folder)) is not None
        }
        return current

    try:
        with patch.object(review_ledger, "snapshot", capture):
            yield
    finally:
        for root, initial in baselines.items():
            current = snapshot(root)
            assert (current["head"], current["index"], set(current["files"])) == (
                initial["head"], initial["index"], set(initial["files"]),
            ), "This fixture changed Git metadata or file membership; use the real snapshot boundary"


@contextmanager
def fixed_storage_membership():
    import review_ledger

    check = review_ledger.external_directory
    verified = {}

    def external(path, root=None):
        key = (Path(os.path.abspath(path)), root)
        if key not in verified:
            verified[key] = check(*key)
        return verified[key]

    try:
        with patch.object(review_ledger, "external_directory", external):
            yield
    finally:
        for key, expected in verified.items():
            assert check(*key) == expected
