#!/usr/bin/env python3
"""Run-scoped review ledger CLI. Run --help for commands and options.

Run in the consuming Git worktree, never the installed plugin directory.
`init` saves a baseline; `apply` reads one event from stdin and atomically
appends it at the requested revision. `status` reconciles current file hashes
without modifying history. `diff` reads saved snapshots, not a remote PR.
`fingerprint` hashes the current worktree without creating a run or storing blobs.

JSON goes to stdout. Invalid input, stale evidence, unsupported files and
storage errors go to stderr with exit 2. No command edits project code, invokes
tests, commits, resets, or uploads data. The ledger is not a security boundary.
"""

import argparse
import difflib
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
    LedgerError, apply_event, check_reconcile_request, fields, replay, require, text,
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
    """Identify the owning checkout without coupling its lifetime to storage."""
    return Path(os.fsdecode(git(Path.cwd(), ["rev-parse", "--show-toplevel"])).strip()).resolve()


def root_key(root):
    return digest(os.fsencode(str(root)))


def external_directory(path, root=None):
    path = Path(os.path.abspath(path))
    require(".git" not in path.parts, "Review storage must be outside Git metadata; choose external storage")
    safe_path(Path(path.anchor), str(path.relative_to(path.anchor)))
    require(root is None or not path.is_relative_to(root), "Review storage must be outside its repository")
    probe = path
    while not probe.exists():
        probe = probe.parent
    environment = {key: value for key, value in os.environ.items()
                   if key not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_CEILING_DIRECTORIES")}
    environment["LC_ALL"] = "C"
    environment["GIT_DISCOVERY_ACROSS_FILESYSTEM"] = "1"
    result = subprocess.run(["git", "-C", str(probe), "rev-parse", "--git-dir"],
                            capture_output=True, env=environment)
    require(result.returncode != 0,
            "Review storage must be outside every repository and Git metadata directory; "
            "set XDG_STATE_HOME to an external state directory. For an existing development review, "
            "stop its workers and use development_run.py recover-review-storage; do not initialize "
            "a replacement ledger. For a standalone run, stop its writers and copy the complete run "
            "directory, including objects, to unused external storage, retaining "
            "<worktree-identity>/<run-id>. Run status on the copied absolute ledger path, then "
            "continue with apply at its retained revision. Keep the original evidence; see "
            "skills/review-validate-fix-loop/LEDGER.md")
    if result.returncode != 128 or not result.stderr.startswith(b"fatal: not a git repository (or any "):
        detail = result.stderr.decode(errors="replace").strip() or f"Git exited with status {result.returncode}"
        raise OSError(f"Git storage check unavailable: {detail}")
    return path


def state_directory():
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state").expanduser().resolve()
    return base / "ioncache-ai-tools"


def storage(root):
    return external_directory(state_directory() / "reviews" / root_key(root), root)


def external_run_directory(path, run_id, root):
    try:
        return external_directory(path, root)
    except LedgerError:
        require(isinstance(run_id, str) and re.fullmatch(r"[a-f0-9]{32}", run_id),
                "Invalid development run identity")
        return external_directory(state_directory() / "development-recovery" / run_id, root)


def review_paths(root, folders=()):
    paths = {}
    for base in dict.fromkeys((safe_path(root, ".review-loop"), *folders)):
        if base.exists():
            for entry in base.iterdir():
                if re.fullmatch(r"[a-f0-9]{32}", entry.name):
                    paths[entry.name] = entry / "REVIEW_LEDGER.json"
    return sorted(paths.values())


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


def sync_directory(path):
    """Make directory-entry changes durable before reporting publication."""
    directory = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


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
        sync_directory(path.parent)
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
    """Capture all tracked and non-ignored untracked files.

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
        entry = file_entry(root, name, folder)
        if entry is not None:
            files[name] = entry
    return {"head": git(root, ["rev-parse", "--verify", "HEAD"]).decode().strip(),
            "index": digest(index), "files": files}


def changed(before, after):
    """Include additions, deletions, content, and mode changes in fix-scope checks."""
    return sorted(name for name in before["files"].keys() | after["files"].keys()
                  if before["files"].get(name) != after["files"].get(name))


def fingerprint(_args, root):
    """Detect drift without requiring standalone reviewers to create a ledger."""
    current = snapshot(root)
    require(current == snapshot(root), "Worktree changed during fingerprint")
    return {"root": str(root), "snapshot": digest(encode(current)), "manifest": current}


def validate_snapshots(ledger, folder):
    """Reject malformed manifests or corrupt blobs before trusting saved evidence."""
    require(isinstance(ledger["snapshots"], dict), "Invalid snapshots")
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


def load_history(path):
    """Validate surviving history without authorizing use of a closed run."""
    try:
        require(not path.is_symlink(), f"Symlink not allowed: {path}")
        ledger = json.loads(path.read_bytes())
        validate_snapshots(ledger, path.parent)
        state = replay(ledger, check_snapshot_transition)
        require(ledger["run_id"] == path.parent.name, "Run ID does not match ledger directory")
        owner = Path(ledger["root"])
        require(owner.is_absolute() and
                (path.parent.parent == owner / ".review-loop" or
                 path.parent.parent.name == root_key(owner)), "Storage belongs to a different worktree")
    except (LedgerError, OSError, ValueError, TypeError, KeyError) as error:
        raise LedgerError(f"Review history unavailable: {error}. Restore verified history, "
                          "or use abandon with --reason, --evidence and --shutdown-evidence "
                          "after stopping workers; do not reset unknown spending") from error
    return ledger, state


def load(path):
    """Return validated history and replayed state, not yet checked for ownership."""
    require(abandoned(path) is None, "Run was abandoned; its remaining allowance is unavailable")
    return load_history(path)


def abandoned(path):
    """Keep terminal closure separate from history that could authorize more work."""
    try:
        record = safe_path(path.parent, "ABANDONED.json")
        if not record.exists():
            return None
        value = json.loads(record.read_bytes())
        fields(value, "schema ledger root run_id outcome allowance reason evidence shutdown_evidence "
                      "error time previous_record")
        owner = Path(value["root"])
        recorded = Path(value["ledger"])
        require(value["schema"] == 1 and owner.is_absolute() and
                recorded.name == path.name and recorded.parent.name == path.parent.name and
                (recorded.parent.parent == owner / ".review-loop" or
                 recorded.parent.parent.name == root_key(owner)) and
                (path.parent.parent == owner / ".review-loop" or
                 path.parent.parent.name == root_key(owner)) and value["run_id"] == path.parent.name,
                "Abandonment belongs to a different run")
        require(value["outcome"] == "failed" and value["allowance"] == "unavailable",
                "Abandonment cannot authorize completion or restore allowance")
        for key in ("reason", "evidence", "shutdown_evidence", "error", "time"):
            text(value[key])
        require(value["previous_record"] is None or (
                isinstance(value["previous_record"], str) and
                re.fullmatch(r"ABANDONED-[a-f0-9]{32}\.json", value["previous_record"])),
                "Invalid prior abandonment record")
    except (LedgerError, OSError, ValueError, TypeError, KeyError) as error:
        raise LedgerError(f"Closure record unavailable: {error}. After stopping workers, use "
                          "recover-closure for readable history or abandon for unrecoverable history, "
                          "with --reason, --evidence and --shutdown-evidence") from error
    return value


def cached_invalidation(root, path, accepted):
    """Detect retained closure without revalidating cached snapshots or granting fresh acceptance."""
    try:
        path = ledger_path(root, str(path), allow_unavailable=True, historical=True)
        require(path.parent.name == Path(accepted["ledger"]).parent.name,
                "Path does not identify the accepted review")
    except (ValueError, OSError, KeyError, TypeError):
        return None
    try:
        if safe_path(path.parent, "ABANDONED.json").is_file() and abandoned(path) is not None:
            return "Accepted review was abandoned; its allowance is unavailable"
    except (ValueError, OSError, KeyError, TypeError):
        pass
    try:
        require(not path.is_symlink() and path.is_file(), "Cached history is not a regular file")
        ledger = json.loads(path.read_bytes())
        ensure_owner(ledger, root)
        require(ledger["run_id"] == path.parent.name, "Run ID does not match cached review")
        require(accepted["outcome"] in ("completed", "completed_with_exceptions"),
                "Cache does not contain completed acceptance")
        history, events = accepted["history"], ledger["events"]
        require(isinstance(events, list) and events[:len(history)] == history,
                "History does not extend the accepted review")
        if len(events) == len(history):
            return None
        # Completion only permits a failed stop; damaged snapshot objects cannot undo it.
        state = dict(accepted)
        apply_event(state, events[len(history)])
    except (ValueError, OSError, KeyError, TypeError):
        return None
    return f"Accepted review was invalidated as {state['outcome']}"


def recover_closure(args, root):
    """Close readable history before removing a damaged marker's terminal fence."""
    path = ledger_path(root, args.ledger, allow_unavailable=True)
    for value in (args.reason, args.evidence, args.shutdown_evidence):
        text(value)
    error = None
    try:
        closed = abandoned(path)
    except LedgerError as failure:
        error = str(failure)
    else:
        require(closed is None, "Valid abandonment is terminal; it cannot be recovered")
    ledger, state = load_history(path)
    ensure_owner(ledger, root)
    terminal_failure = state["outcome"] in ("failed", "stalled", "limit_reached")
    if error is None:
        require(terminal_failure, "No damaged closure record to recover")
        return {"ledger": str(path), **state}
    if not terminal_failure:
        event = {"type": "stop", "outcome": "failed", "actor": "closure-recovery",
                 "reason": json.dumps({"reason": args.reason, "evidence": args.evidence,
                                       "shutdown_evidence": args.shutdown_evidence,
                                       "closure_error": error}),
                 "snapshot": state["snapshot"], "sequence": state["revision"] + 1,
                 "time": datetime.now(timezone.utc).isoformat()}
        apply_event(state, event)
        ledger["events"].append(event)
        atomic_write(path, encode(ledger))
    os.rename(path.parent / "ABANDONED.json", path.parent / f"ABANDONED-{uuid4().hex}.json")
    sync_directory(path.parent)
    return {"ledger": str(path), **state}


def abandon(args, root):
    """Close unreadable history as failed without rewriting any surviving evidence."""
    path = ledger_path(root, args.ledger, allow_unavailable=True)
    require(path.parent.is_dir() and re.fullmatch(r"[a-f0-9]{32}", path.parent.name),
            "Abandon requires an existing published run directory")
    for value in (args.reason, args.evidence, args.shutdown_evidence):
        text(value)
    try:
        existing = abandoned(path)
    except (LedgerError, OSError, ValueError, TypeError, KeyError):
        existing = None
    if existing is not None:
        return existing
    try:
        load_history(path)
    except (LedgerError, OSError, ValueError, TypeError, KeyError) as error:
        unavailable = str(error)
    else:
        raise LedgerError("History is readable; use stop to retain its decisions and counters, "
                          "or recover-closure if the closure record is damaged")
    record = path.parent / "ABANDONED.json"
    previous = None
    if record.exists() or record.is_symlink():
        previous = f"ABANDONED-{uuid4().hex}.json"
        os.rename(record, path.parent / previous)
        sync_directory(path.parent)
    result = {"schema": 1, "ledger": str(path), "root": str(root), "run_id": path.parent.name,
              "outcome": "failed", "allowance": "unavailable", "reason": args.reason,
              "evidence": args.evidence, "shutdown_evidence": args.shutdown_evidence,
              "error": unavailable, "time": datetime.now(timezone.utc).isoformat(),
              "previous_record": previous}
    atomic_write(record, encode(result))
    return result


def ledger_path(root, argument, *, allow_unavailable=False, historical=False):
    """Validate owned storage, retaining an unusable ledger entry only for inspection or closure."""
    candidate = Path(os.path.abspath((root or Path.cwd()) / argument))
    require(candidate.name == "REVIEW_LEDGER.json" and
            re.fullmatch(r"[a-f0-9]{32}", candidate.parent.name), "Invalid review ledger path")
    legacy = candidate.parent.parent.name == ".review-loop"
    if legacy:
        root = root or candidate.parent.parent.parent
        require(candidate.parent.parent == root / ".review-loop", "Ledger belongs to a different worktree")
        safe_path(Path(candidate.anchor), str(candidate.parent.relative_to(candidate.anchor)))
        if not candidate.parent.exists():
            base = state_directory() / "reviews" / root_key(root) if historical else storage(root)
            candidate = base / candidate.parent.name / candidate.name
            legacy = False
    if not legacy:
        if not historical:
            external_directory(candidate.parent.parent, root)
        require(re.fullmatch(r"[a-f0-9]{64}", candidate.parent.parent.name) and
                (root is None or candidate.parent.parent.name == root_key(root)),
                "Ledger belongs to a different worktree")
    folder = safe_path(Path(candidate.anchor), str(candidate.parent.relative_to(candidate.anchor)))
    return folder / candidate.name if allow_unavailable else safe_path(folder, candidate.name)


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
        if re.fullmatch(r"\.initializing-[a-f0-9]{32}", folder.name):
            continue
        if abandoned(folder / "REVIEW_LEDGER.json") is not None:
            continue
        ledger, state = load(folder / "REVIEW_LEDGER.json")
        require(state["outcome"] not in ("running", "interrupted", "blocked"),
                f"Existing active run: {folder / 'REVIEW_LEDGER.json'}; resume or stop it first")


def init(args, root):
    """Create an isolated run; never reuse a session-wide or repository-wide ledger."""
    base = external_directory(Path(args.storage), root) if getattr(args, "storage", None) else storage(root)
    require(base.name == root_key(root), "Storage directory must retain the worktree identity")
    legacy = [path for path in review_paths(root) if path.parent.parent == root / ".review-loop"]
    require(not legacy, "Legacy review records remain; run migrate on each ledger before starting a new run")
    assert_available(base)
    require(args.max_loops > 0 and args.max_fix_cycles > 0, "Limits must be positive")
    for value in (args.objective, args.scope):
        text(value)
    git(root, ["rev-parse", "--verify", "--end-of-options", args.base + "^{commit}"])
    run_id = uuid4().hex
    folder = base / f".initializing-{run_id}"
    folder.mkdir(mode=0o700)
    try:
        result = create_ledger(args, root, folder)
        published = base / run_id
        os.rename(folder, published)
        sync_directory(base)
        result["ledger"] = str(published / "REVIEW_LEDGER.json")
        return result
    finally:
        if folder.exists():
            shutil.rmtree(folder)


def create_ledger(args, root, folder):
    """Persist a stable baseline and return its absolute ledger path and initial state."""
    initial = snapshot(root, folder)
    require(initial == snapshot(root), "Worktree changed during initial snapshot")
    key = digest(encode(initial))
    ledger = {"schema": 1, "run_id": folder.name.removeprefix(".initializing-"), "root": str(root),
              "objective": args.objective, "scope": args.scope,
              "base": git(root, ["rev-parse", "--verify", "--end-of-options",
                                 args.base + "^{commit}"]).decode().strip(),
              "limits": {"outer": args.max_loops, "inner": args.max_fix_cycles},
              "initial": key, "snapshots": {key: initial}, "events": []}
    path = folder / "REVIEW_LEDGER.json"
    atomic_write(path, encode(ledger))
    return {"ledger": str(path), **replay(ledger)}


def stored_files(folder):
    entries = {}
    for path in sorted(folder.rglob("*")):
        mode = stat.S_IMODE(path.lstat().st_mode)
        if path.is_symlink():
            entry = ("link", digest(os.fsencode(os.readlink(path))), mode)
        elif path.is_file():
            entry = ("file", digest(path.read_bytes()), mode)
        else:
            require(path.is_dir(), "Unsupported file in legacy review storage")
            entry = ("directory", None, mode)
        entries[str(path.relative_to(folder))] = list(entry)
    return entries


def migration_snapshot(source):
    files = stored_files(source)
    entry = files.get("REVIEW_LEDGER.json")
    content = (source / "REVIEW_LEDGER.json").read_bytes() if entry and entry[0] == "file" else None
    require(content is None or digest(content) == entry[1],
            "Legacy history changed during capture; stop its writers and retry migration")
    return {"files": files, "ledger": content.hex() if content is not None else None}


def migration_preserved(baseline, target):
    before, after = baseline["files"], stored_files(target)
    if before == after:
        return
    require(all(after.get(name) == entry for name, entry in before.items()
                if name != "REVIEW_LEDGER.json"), "Migration destination does not preserve the source files")
    require(isinstance(baseline["ledger"], str), "Original history cannot verify a changed migration destination")
    content = bytes.fromhex(baseline["ledger"])
    require(digest(content) == before["REVIEW_LEDGER.json"][1], "Migration checkpoint history changed")
    original = json.loads(content)
    validate_snapshots(original, target)
    replay(original, check_snapshot_transition)
    current, _ = load_history(target / "REVIEW_LEDGER.json")
    require(all(current[key] == value for key, value in original.items()
                if key not in ("events", "snapshots")) and
            current["events"][:len(original["events"])] == original["events"] and
            all(current["snapshots"].get(key) == value for key, value in original["snapshots"].items()),
            "Migration destination has conflicting history; preserve both records, never overwrite it")


def migration_checkpoint(path, source, target):
    record = json.loads(path.read_bytes())
    fields(record, "schema source target files ledger")
    require(record["schema"] == 1 and record["source"] == str(source) and record["target"] == str(target) and
            isinstance(record["files"], dict), "Migration cleanup checkpoint belongs to a different transfer")
    return {"files": record["files"], "ledger": record["ledger"]}


def copy_run_evidence(source, target, baseline):
    temporary = target.parent / f".initializing-{uuid4().hex}"
    try:
        shutil.copytree(source, temporary, symlinks=True)
        migration_preserved(baseline, temporary)
        for path in temporary.rglob("*"):
            if not path.is_symlink() and path.is_file():
                with path.open("rb") as handle:
                    os.fsync(handle.fileno())
        for path in sorted(temporary.rglob("*"), key=lambda value: len(value.parts), reverse=True):
            if not path.is_symlink() and path.is_dir():
                sync_directory(path)
        sync_directory(temporary)
        os.rename(temporary, target)
        sync_directory(target.parent)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def migrate(args, root):
    """Move complete legacy evidence, preserving newer destination history on retry."""
    text(args.shutdown_evidence)
    candidate = Path(os.path.abspath(root / args.ledger))
    require(candidate.name == "REVIEW_LEDGER.json" and
            candidate.parent.parent == root / ".review-loop" and
            re.fullmatch(r"[a-f0-9]{32}", candidate.parent.name), "Migration requires a legacy run path")
    source = safe_path(root, str(candidate.parent.relative_to(root)))
    target = safe_path(storage(root), source.name)
    checkpoint = safe_path(target.parent, f".migration-{source.name}.json")
    migrated = source.exists()
    if not source.exists():
        require(target.is_dir(), "Legacy source and external destination are both missing")
        if not checkpoint.exists():
            return {"ledger": str(target / candidate.name), "migrated": False}
    baseline = (migration_checkpoint(checkpoint, source, target) if checkpoint.exists()
                else migration_snapshot(source))
    if checkpoint.exists():
        require(target.is_dir(), "Verified migration destination is missing; restore it before retrying cleanup")
    if not target.exists():
        copy_run_evidence(source, target, baseline)
    migration_preserved(baseline, target)
    require(all(baseline["files"].get(name) == entry for name, entry in stored_files(source).items()),
            "Legacy source changed after verification; preserve the new evidence before retrying cleanup")
    if not checkpoint.exists():
        atomic_write(checkpoint, encode({"schema": 1, "source": str(source), "target": str(target), **baseline}))
    if source.exists():
        shutil.rmtree(source)
        sync_directory(source.parent)
    checkpoint.unlink()
    sync_directory(checkpoint.parent)
    return {"ledger": str(target / candidate.name), "migrated": migrated,
            "shutdown_evidence": args.shutdown_evidence}


def check_snapshot_transition(ledger, state, event):
    """Reject drift not allowed by the event's phase.

    Fix completion and fixing resumption must preserve HEAD and index metadata.
    Both append and replay use this check so saved history obeys the same rules.
    """
    before = ledger["snapshots"][state["snapshot"]]
    after = ledger["snapshots"][event["snapshot"]]
    kind = event["type"]
    if kind == "fix_done" or (kind == "resume" and state["phase"] == "fixing"):
        require(before["head"] == after["head"] and before["index"] == after["index"],
                "HEAD or index changed during fixing")
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
                    all(part not in (".", "..", ".git") for part in parts),
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
    event = args.event if hasattr(args, "event") else json.load(sys.stdin)
    require(isinstance(event, dict), "Event must be an object")
    require(not ({"snapshot", "sequence", "time"} & event.keys()), "Reserved event fields")
    if event.get("type") == "start_fix":
        for name in event.get("files", []):
            require(isinstance(name, str), "Invalid fix path")
            require(str(Path(name)) == name, "Fix paths must be normalized")
            safe_path(root, name)
    current = snapshot(root, path.parent)
    require(current == snapshot(root), "Worktree changed during snapshot")
    key = digest(encode(current))
    ledger["snapshots"][key] = current
    event.update(snapshot=key, sequence=state["revision"] + 1,
                 time=datetime.now(timezone.utc).isoformat())
    check_snapshot_transition(ledger, state, event)
    check_reconcile_request(state, event)
    apply_event(state, event)
    ledger["events"].append(event)
    atomic_write(path, encode(ledger))
    return {"ledger": str(path), **state}


def status(args, root):
    """Report saved decisions and live drift without accepting drift as new evidence."""
    path = ledger_path(root, args.ledger, allow_unavailable=True, historical=root is None)
    if root is not None:
        from review_ownership import require_unreleased

        require_unreleased(root, path.parent.parent)
    closed = abandoned(path)
    if closed is not None:
        return closed
    ledger, state = load(path)
    if root is not None:
        ensure_owner(ledger, root)
    current = snapshot(root) if root is not None else None
    before = ledger["snapshots"][state["snapshot"]]
    return {"ledger": str(path), "objective": ledger["objective"],
            "scope": ledger["scope"], "base": ledger["base"], **state,
            "drift": current != before if current is not None else None,
            "changed_files": changed(before, current) if current is not None else None,
            "usage": "not_collected", "history": ledger["events"]}


def blob(folder, entry):
    """Represent an absent diff side as empty bytes; load present sides from storage."""
    return b"" if entry is None else safe_path(folder, f"objects/{entry['blob']}").read_bytes()


def diff(args, root):
    """Show saved correction deltas without writing them into the working tree."""
    path = ledger_path(root, args.ledger, historical=root is None)
    ledger, state = load(path)
    if root is not None:
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
    commands.add_parser("fingerprint", help="Hash the current worktree without storing snapshots")
    create = commands.add_parser("init", help="Start an externally stored run owned by this worktree")
    create.add_argument("--objective", required=True)
    create.add_argument("--scope", required=True)
    create.add_argument("--base", default="HEAD", help="Pinned comparison commit, not a moving PR")
    create.add_argument("--max-loops", type=int, default=3)
    create.add_argument("--max-fix-cycles", type=int, default=3)
    create.add_argument("--storage", help="Pinned external worktree storage directory returned by the controller")
    release = commands.add_parser("release-ownership", help="Release an absent store after native worker shutdown")
    for flag in ("storage", "replacement-storage", "reason", "shutdown-evidence"):
        release.add_argument("--" + flag, required=True)
    for name in ("apply", "status", "inspect", "diff", "abandon", "recover-closure", "recover-ownership", "migrate"):
        command = commands.add_parser(name)
        command.add_argument("ledger", help="Absolute path or path relative to the worktree root")
        if name == "apply":
            command.add_argument("--revision", required=True, type=int)
        if name == "diff":
            command.add_argument("--from", dest="from_snapshot", required=True)
            command.add_argument("--to", dest="to_snapshot")
        if name in ("abandon", "recover-closure"):
            for flag in ("reason", "evidence", "shutdown-evidence"):
                command.add_argument("--" + flag, required=True)
        if name == "recover-ownership":
            for flag in ("reason", "shutdown-evidence"):
                command.add_argument("--" + flag, required=True)
        if name == "migrate":
            command.add_argument("--shutdown-evidence", required=True)
    return cli


def main():
    """Lock ledger mutations and keep JSON results separate from failure diagnostics."""
    args = parser().parse_args()
    try:
        root = None if args.command in ("inspect", "diff") else worktree()
        if args.command == "apply":
            args.event = json.load(sys.stdin)
        if root is None and not Path(args.ledger).is_absolute():
            try:
                relative_root = worktree()
            except LedgerError:
                relative_root = Path.cwd()
            args.ledger = str(relative_root / args.ledger)
        handlers = {"init": init, "apply": append, "status": status, "diff": diff,
                    "inspect": status, "migrate": migrate, "fingerprint": fingerprint,
                    "abandon": abandon, "recover-closure": recover_closure, "recover-ownership": status}
        if args.command == "release-ownership":
            from review_ownership import release

            result = release(args, root)
        elif args.command in ("init", "apply", "abandon", "recover-closure", "recover-ownership", "migrate"):
            from review_ownership import guard

            base = (external_directory(Path(args.storage), root) if args.command == "init" and args.storage else
                    storage(root) if args.command in ("init", "migrate") else
                    ledger_path(root, args.ledger, allow_unavailable=True).parent.parent)
            require(base != root / ".review-loop",
                    "Legacy storage is read-only; run migrate with --shutdown-evidence, then retry")
            require(base.name == root_key(root), "Storage directory must retain the worktree identity")
            bases = [safe_path(root, ".review-loop"), base] if args.command == "migrate" else [base]
            with guard(root, bases, args):
                result = handlers[args.command](args, root)
                if (args.command == "migrate" and bases[0].exists() and
                        set(bases[0].iterdir()) == {bases[0] / ".lock"}):
                    (bases[0] / ".lock").unlink()
                    bases[0].rmdir()
                    sync_directory(root)
        else:
            result = handlers[args.command](args, root)
        print(json.dumps(result, indent=2, ensure_ascii=True))
    except (LedgerError, OSError, ValueError, TypeError, KeyError) as error:
        print(f"review-ledger: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
