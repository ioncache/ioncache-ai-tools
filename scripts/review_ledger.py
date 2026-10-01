#!/usr/bin/env python3
"""Run-scoped review ledger CLI. Run --help for commands and options.

Run in the consuming Git worktree, never the installed plugin directory.
`init` saves a baseline; `apply` reads one event from stdin and atomically
appends it at the requested revision. `status` reconciles current file hashes
without modifying history. `diff` reads saved snapshots, not a remote PR.

JSON goes to stdout. Invalid input, stale evidence, unsupported files and
storage errors go to stderr with exit 2. No command edits project code, invokes
tests, commits, resets, or uploads data. The ledger is not a security boundary.
"""

import argparse
import difflib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from uuid import uuid4

from review_loop_state import (
    LedgerError, apply_event, current_cycle, fields, replay, require, text,
)


def encode(value):
    """Use canonical JSON bytes so snapshot IDs survive process restarts."""
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, indent=2) + "\n").encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(root, args):
    """Return raw Git output; surface failures instead of treating them as no data."""
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)
    require(result.returncode == 0, result.stderr.decode(errors="replace").strip())
    return result.stdout


def worktree():
    """Anchor storage at the canonical Git root, independent of launch directory."""
    return Path(os.fsdecode(git(Path.cwd(), ["rev-parse", "--show-toplevel"])).strip()).resolve()


def safe_path(root, relative):
    """Reject absolute paths, parent traversal, Git metadata, and symlink components.

    Missing components are allowed for new storage or fix targets. This check
    does not isolate the path from concurrent filesystem changes.
    """
    parts = Path(relative).parts
    require(parts and not Path(relative).is_absolute() and
            all(part not in (".", "..", ".git") for part in parts), "Unsafe relative path")
    path = root
    for part in parts:
        path = path / part
        require(not path.is_symlink(), f"Symlink not allowed: {path}")
    return path


def atomic_write(path, data):
    """Replace one file only after its complete bytes are durably written."""
    require(not path.is_symlink(), f"Symlink not allowed: {path}")
    fd, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def store_blob(folder, content):
    """Return a content ID, saving bytes or verifying the existing object matches."""
    key = digest(content)
    objects = safe_path(folder, "objects")
    objects.mkdir(exist_ok=True, mode=0o700)
    target = safe_path(objects, key)
    if target.exists():
        require(target.read_bytes() == content, "Corrupt snapshot object")
    else:
        atomic_write(target, content)
    return key


def file_entry(root, name, folder):
    """Describe content and mode without following symlinks; omit deleted files.

    A folder enables blob storage; otherwise only hashes are calculated.
    Unsupported file types raise LedgerError rather than leaving coverage gaps.
    """
    path = root / name
    if path.parent != root:
        safe_path(root, str(path.parent.relative_to(root)))
    if not path.exists() and not path.is_symlink():
        return None
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        content, mode = os.fsencode(os.readlink(path)), "120000"
    elif stat.S_ISREG(info.st_mode):
        content = path.read_bytes()
        mode = "100755" if info.st_mode & 0o111 else "100644"
    else:
        raise LedgerError(f"Unsupported file or submodule: {name}")
    key = store_blob(folder, content) if folder else digest(content)
    return {"blob": key, "mode": mode}


def snapshot(root, folder=None):
    """Capture tracked and non-ignored untracked files, excluding run artifacts.

    Symlinks record their target text without following it. Gitlinks and
    Git-enumerated special files fail explicitly. HEAD and index metadata detect
    staging or branch drift. Snapshots do not isolate concurrent writers.
    """
    names = git(root, ["ls-files", "-z", "--cached", "--others", "--exclude-standard"])
    index = git(root, ["ls-files", "--stage", "-z"])
    require(not any(entry.startswith(b"160000 ") for entry in index.split(b"\0")),
            "Submodules are not supported by review snapshots")
    files = {}
    for raw in sorted(set(names.split(b"\0")) - {b""}):
        name = os.fsdecode(raw)
        if name == ".review-loop" or name.startswith(".review-loop/"):
            continue
        entry = file_entry(root, name, folder)
        if entry is not None:
            files[name] = entry
    return {"head": git(root, ["rev-parse", "--verify", "HEAD"]).decode().strip(),
            "index": digest(index), "files": files}


def changed(before, after):
    """Include additions, deletions, content, and mode changes in fix-scope checks."""
    return sorted(name for name in before["files"].keys() | after["files"].keys()
                  if before["files"].get(name) != after["files"].get(name))


def validate_snapshots(ledger, folder):
    """Reject malformed manifests or corrupt blobs before trusting saved evidence."""
    for key, item in ledger["snapshots"].items():
        require(key == digest(encode(item)), "Snapshot checksum mismatch")
        fields(item, "head index files")
        require(isinstance(item["files"], dict), "Invalid snapshot file map")
        for name, entry in item["files"].items():
            require(isinstance(name, str), "Invalid snapshot filename")
            fields(entry, "blob mode")
            require(isinstance(entry["blob"], str) and
                    re.fullmatch(r"[a-f0-9]{64}", entry["blob"]), "Invalid blob ID")
            require(entry["mode"] in ("100644", "100755", "120000"), "Invalid file mode")
            content = safe_path(folder, f"objects/{entry['blob']}").read_bytes()
            require(digest(content) == entry["blob"], "Snapshot object checksum mismatch")


def load(path):
    """Return validated history and replayed state, not yet checked for ownership."""
    ledger = json.loads(path.read_bytes())
    state = replay(ledger, check_snapshot_transition)
    require(ledger["run_id"] == path.parent.name, "Run ID does not match ledger directory")
    validate_snapshots(ledger, path.parent)
    return ledger, state


def ledger_path(root, argument):
    """Resolve run paths against root without admitting foreign or symlinked storage."""
    candidate = Path(os.path.abspath(root / argument))
    base = safe_path(root, ".review-loop")
    require(candidate.parent.parent == base and candidate.name == "REVIEW_LEDGER.json",
            "Ledger must be .review-loop/<run-id>/REVIEW_LEDGER.json in this worktree")
    return safe_path(root, str(candidate.relative_to(root)))


def ensure_owner(ledger, root):
    require(ledger["root"] == str(root), "Ledger belongs to a different worktree")


def assert_available(base):
    """Prevent a second run from authorizing work while a resumable run still exists."""
    for folder in base.iterdir():
        if folder.name == ".lock":
            continue
        require(not folder.is_symlink(), "Symlink in run storage")
        if not folder.is_dir():
            continue
        ledger, state = load(folder / "REVIEW_LEDGER.json")
        require(state["outcome"] not in ("running", "interrupted", "blocked"),
                f"Existing active run: {ledger['run_id']}; resume or stop it first")


def init(args, root):
    """Create an isolated run; never reuse a session-wide or repository-wide ledger."""
    base = safe_path(root, ".review-loop")
    assert_available(base)
    require(args.max_loops > 0 and args.max_fix_cycles > 0, "Limits must be positive")
    for value in (args.objective, args.scope):
        text(value)
    git(root, ["rev-parse", "--verify", "--end-of-options", args.base + "^{commit}"])
    folder = base / uuid4().hex
    folder.mkdir(mode=0o700)
    try:
        return create_ledger(args, root, folder)
    except (OSError, LedgerError):
        if not (folder / "REVIEW_LEDGER.json").exists():
            shutil.rmtree(folder)
        raise


def create_ledger(args, root, folder):
    """Persist a stable baseline and return its absolute ledger path and initial state."""
    initial = snapshot(root, folder)
    require(initial == snapshot(root), "Worktree changed during initial snapshot")
    key = digest(encode(initial))
    ledger = {"schema": 1, "run_id": folder.name, "root": str(root),
              "objective": args.objective, "scope": args.scope,
              "base": git(root, ["rev-parse", "--verify", "--end-of-options",
                                 args.base + "^{commit}"]).decode().strip(),
              "limits": {"outer": args.max_loops, "inner": args.max_fix_cycles},
              "initial": key, "snapshots": {key: initial}, "events": []}
    path = folder / "REVIEW_LEDGER.json"
    atomic_write(path, encode(ledger))
    return {"ledger": str(path), **replay(ledger)}


def check_snapshot_transition(ledger, state, event):
    """Reject drift not allowed by the event's phase and declared fix files.

    Fix completion and fixing resumption must preserve HEAD and index metadata.
    Both append and replay use this check so saved history obeys the same rules.
    """
    before = ledger["snapshots"][state["snapshot"]]
    after = ledger["snapshots"][event["snapshot"]]
    kind = event["type"]
    if kind == "fix_done" or (kind == "resume" and state["phase"] == "fixing"):
        cycle = current_cycle(state)
        require(before["head"] == after["head"] and before["index"] == after["index"],
                "HEAD or index changed during fixing")
        require(set(changed(before, after)) <= set(cycle["files"]),
                "Changes outside declared fix files; stop and reconcile manually")
        if kind == "fix_done" and isinstance(event.get("results"), dict):
            applied = any(isinstance(item, dict) and item.get("result") == "applied"
                          for item in event["results"].values())
            require(not applied or bool(changed(before, after)), "Applied fix has no file changes")
    elif kind not in ("stop", "reconcile"):
        require(before == after, "Worktree drift; reconcile before using old evidence")
    if kind == "start_fix":
        for name in event.get("files", []):
            require(isinstance(name, str) and str(Path(name)) == name, "Invalid fix path")
            parts = Path(name).parts
            require(parts and not Path(name).is_absolute() and
                    all(part not in (".", "..", ".git", ".review-loop") for part in parts),
                    "Unsafe fix path")


def append(args, root):
    """Persist one stdin event only at its expected revision and allowed snapshot.

    The caller must hold the worktree lock. Rejected events can leave snapshot
    blobs, but only successful validation replaces the canonical ledger.
    """
    path = ledger_path(root, args.ledger)
    ledger, state = load(path)
    ensure_owner(ledger, root)
    require(args.revision == state["revision"], "Stale revision; read status before retrying")
    event = json.load(sys.stdin)
    require(isinstance(event, dict), "Event must be an object")
    require(not ({"snapshot", "sequence", "time"} & event.keys()), "Reserved event fields")
    if event.get("type") == "start_fix":
        for name in event.get("files", []):
            require(isinstance(name, str), "Invalid fix path")
            require(not name.startswith(".review-loop"), "Cannot fix ledger artifacts")
            require(str(Path(name)) == name, "Fix paths must be normalized")
            safe_path(root, name)
    current = snapshot(root, path.parent)
    require(current == snapshot(root), "Worktree changed during snapshot")
    key = digest(encode(current))
    ledger["snapshots"][key] = current
    event.update(snapshot=key, sequence=state["revision"] + 1,
                 time=datetime.now(timezone.utc).isoformat())
    check_snapshot_transition(ledger, state, event)
    apply_event(state, event)
    ledger["events"].append(event)
    atomic_write(path, encode(ledger))
    return {"ledger": str(path), **state}


def status(args, root):
    """Report saved decisions and live drift without accepting drift as new evidence."""
    path = ledger_path(root, args.ledger)
    ledger, state = load(path)
    ensure_owner(ledger, root)
    current = snapshot(root)
    before = ledger["snapshots"][state["snapshot"]]
    return {"ledger": str(path), "objective": ledger["objective"],
            "scope": ledger["scope"], "base": ledger["base"], **state,
            "drift": current != before, "changed_files": changed(before, current),
            "usage": "not_collected", "history": ledger["events"]}


def blob(folder, entry):
    """Represent an absent diff side as empty bytes; load present sides from storage."""
    return b"" if entry is None else safe_path(folder, f"objects/{entry['blob']}").read_bytes()


def diff(args, root):
    """Show saved correction deltas without writing them into the working tree."""
    path = ledger_path(root, args.ledger)
    ledger, state = load(path)
    ensure_owner(ledger, root)
    after_key = args.to_snapshot or state["snapshot"]
    require(args.from_snapshot in ledger["snapshots"] and after_key in ledger["snapshots"],
            "Unknown snapshot")
    before, after = (ledger["snapshots"][key] for key in (args.from_snapshot, after_key))
    output = []
    for name in changed(before, after):
        left, right = before["files"].get(name), after["files"].get(name)
        a, b = blob(path.parent, left), blob(path.parent, right)
        patch = "".join(difflib.unified_diff(
            a.decode(errors="replace").splitlines(keepends=True),
            b.decode(errors="replace").splitlines(keepends=True),
            fromfile=f"before/{name}", tofile=f"after/{name}"))
        output.append({"file": name, "before": left, "after": right, "diff": patch})
    return output


def parser():
    """Require run intent and explicit write revisions at the CLI boundary."""
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="command", required=True)
    create = commands.add_parser("init", help="Start a new run in the current worktree")
    create.add_argument("--objective", required=True)
    create.add_argument("--scope", required=True)
    create.add_argument("--base", default="HEAD", help="Pinned comparison commit, not a moving PR")
    create.add_argument("--max-loops", type=int, default=3)
    create.add_argument("--max-fix-cycles", type=int, default=3)
    for name in ("apply", "status", "diff"):
        command = commands.add_parser(name)
        command.add_argument("ledger", help="Absolute path or path relative to the worktree root")
        if name == "apply":
            command.add_argument("--revision", required=True, type=int)
        if name == "diff":
            command.add_argument("--from", dest="from_snapshot", required=True)
            command.add_argument("--to", dest="to_snapshot")
    return cli


def main():
    """Lock ledger mutations and keep JSON results separate from failure diagnostics."""
    args = parser().parse_args()
    try:
        root = worktree()
        handlers = {"init": init, "apply": append, "status": status, "diff": diff}
        if args.command in ("init", "apply"):
            base = safe_path(root, ".review-loop")
            base.mkdir(exist_ok=True, mode=0o700)
            lock = safe_path(base, ".lock")
            with lock.open("a") as handle:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = handlers[args.command](args, root)
        else:
            result = handlers[args.command](args, root)
        print(json.dumps(result, indent=2, ensure_ascii=True))
    except (LedgerError, OSError, ValueError, TypeError, KeyError) as error:
        print(f"review-ledger: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
