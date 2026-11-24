import os
from pathlib import Path
import shutil
import subprocess
from contextlib import ExitStack

import pytest


@pytest.fixture(autouse=True)
def stable_git_fixtures(request, monkeypatch):
    state = request.node.get_closest_marker("state_logic")
    storage = request.node.get_closest_marker("stable_storage")
    if not (state or storage):
        return
    from self_check_support import fixed_git_metadata, fixed_storage_membership

    instance = request.instance
    setup = instance.setUp

    def isolated_setup():
        setup()
        stack = ExitStack()
        instance.addCleanup(stack.close)
        if state:
            stack.enter_context(fixed_git_metadata())
        stack.enter_context(fixed_storage_membership())

    monkeypatch.setattr(instance, "setUp", isolated_setup)


@pytest.fixture(scope="session")
def repository_seeds(tmp_path_factory):
    folder = tmp_path_factory.mktemp("repository-seeds")
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(HOME=str(folder), GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    seeds = {}
    for kind, ignored in (("DevelopmentRunTests", ".review-loop/\n.worktrees/\n"),
                          ("ReviewLedgerTests", ".review-loop/\nignored.txt\n")):
        root = folder / kind
        root.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(root)], env=env, check=True)
        for key, value in (("user.name", "Test fixture"), ("user.email", "fixture@example.invalid"),
                           ("commit.gpgsign", "false")):
            subprocess.run(["git", "-C", str(root), "config", key, value], env=env, check=True)
        if kind == "DevelopmentRunTests":
            subprocess.run(["git", "-C", str(root), "remote", "add", "origin",
                            "https://example.invalid/project.git"], env=env, check=True)
        (root / "app.txt").write_text("before\n")
        (root / ".gitignore").write_text(ignored)
        subprocess.run(["git", "-C", str(root), "add", "."], env=env, check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture"], env=env, check=True)
        seeds[kind] = root
    return seeds


@pytest.fixture(autouse=True)
def repository_seed(request):
    if request.instance is not None and type(request.instance).__name__ in (
        "DevelopmentRunTests", "ReviewLedgerTests",
    ):
        request.instance.repository_seed = request.getfixturevalue("repository_seeds")[
            type(request.instance).__name__
        ]


@pytest.fixture(scope="session")
def executor_source(tmp_path_factory):
    root = Path(__file__).parent
    source = tmp_path_factory.mktemp("executor-source")
    for name in (
        "scripts/development_run.py", "scripts/development_handoff.py", "scripts/review_ledger.py",
        "workflows/autonomous-development.js", ".claude-plugin/plugin.json",
        "skills/autonomous-development/WORKERS.md",
        "skills/review-code/WRITING.md", "skills/review-code/categories.json",
        "skills/autonomous-development/FOLLOW_UPS.md",
    ):
        destination = source / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, destination)
    shutil.copytree(root / "skills/review-code/categories", source / "skills/review-code/categories")
    return source


@pytest.fixture(autouse=True)
def state_test_executor(request, monkeypatch):
    if request.instance is None or type(request.instance).__name__ != "DevelopmentRunTests":
        return
    if request.node.get_closest_marker("process"):
        return
    import development_executor

    monkeypatch.setattr(development_executor, "ROOT", request.getfixturevalue("executor_source"))


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    for key in tuple(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key)
    for key, directory in (
        ("HOME", "home"),
        ("XDG_STATE_HOME", "state"),
        ("XDG_CACHE_HOME", "cache"),
        ("CODEX_HOME", "codex"),
        ("COPILOT_HOME", "copilot"),
    ):
        path = tmp_path / directory
        path.mkdir()
        monkeypatch.setenv(key, str(path))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
