"""Pin runtime resources outside the target tree before generating dispatches."""

import json
import os
from pathlib import Path
import shutil
import tempfile

import development_manifest as plan
import review_ledger as review


ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = ("scripts", "hooks", "skills", "config", "workflows", ".claude-plugin")


def files(root):
    result = {}
    for directory in DIRECTORIES:
        for path in sorted((root / directory).rglob("*")):
            if "__pycache__" in path.parts or path.suffix not in (".py", ".js", ".json", ".md", ".yaml"):
                continue
            plan.require(not any(part.is_symlink() for part in (path, *path.parents) if part != root.parent),
                         "Executor resources cannot be symlinks")
            if path.is_file():
                result[path.relative_to(root).as_posix()] = plan.digest(path.read_bytes())
    return result


def verify(folder):
    record = json.loads((folder / "EXECUTOR.json").read_bytes())
    root = review.safe_path(folder, "executor")
    plan.require(record["identity"] == plan.digest(plan.encode(record["files"])),
                 "Executor pin is malformed; preserve it and restore the recorded resources")
    plan.require(files(root) == record["files"],
                 "Pinned executor changed; restore its exact recorded bytes before continuing. "
                 "Do not switch to the target checkout or modify an active review.")
    return root, record


def pin(folder):
    if (folder / "EXECUTOR.json").exists():
        return verify(folder)[0]
    target = review.safe_path(folder, "executor")
    if target.exists():
        record = json.loads((target / "EXECUTOR.json").read_bytes())
        plan.require(record["identity"] == plan.digest(plan.encode(record["files"])) and
                     files(target) == record["files"], "Incomplete executor pin cannot be adopted")
        review.atomic_write(folder / "EXECUTOR.json", plan.encode(record))
        return target
    inventory = files(ROOT)
    temporary = Path(tempfile.mkdtemp(prefix=".executor-", dir=folder))
    try:
        for name in inventory:
            destination = temporary / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, destination)
        plan.require(files(temporary) == inventory, "Executor changed while pinning; retry from a stable revision")
        version = json.loads((temporary / ".claude-plugin/plugin.json").read_bytes()).get("version")
        record = {"source": str(ROOT), "version": version, "files": inventory,
                  "identity": plan.digest(plan.encode(inventory))}
        review.atomic_write(temporary / "EXECUTOR.json", plan.encode(record))
        os.rename(temporary, target)
        review.atomic_write(folder / "EXECUTOR.json", plan.encode(record))
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return target


def require_current(folder):
    root, record = verify(folder)
    plan.require(files(ROOT) == record["files"],
                 f"Use the pinned helper at {root / 'scripts/development_handoff.py'}; "
                 "the invoking executor revision differs")
    return root


def restore(folder, source):
    record = json.loads((folder / "EXECUTOR.json").read_bytes())
    plan.require(record["identity"] == plan.digest(plan.encode(record["files"])) and
                 files(source) == record["files"],
                 "Recovery source must match every recorded executor resource; keep the pin unchanged")
    target = review.safe_path(folder, "executor")
    archive = review.safe_path(folder, "executor-recovery")
    archive.mkdir(exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="restored-", dir=archive))
    try:
        for name in record["files"]:
            destination = temporary / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, destination)
        plan.require(files(temporary) == record["files"], "Recovery source changed during copying")
        review.atomic_write(temporary / "EXECUTOR.json", plan.encode(record))
        if target.exists():
            retained = archive / ("retained-" + temporary.name)
            os.rename(target, retained)
        os.rename(temporary, target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return {"executor": str(target), "identity": record["identity"]}
