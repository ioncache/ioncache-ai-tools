"""Worktree-wide review ownership, independent of ledger storage selection."""

from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import re
import shlex
import sys
from uuid import uuid4

import review_ledger as ledger


def directory(root):
    anchor = Path.home() / ".local/state/ioncache-ai-tools/review-ownership" / ledger.root_key(root)
    try:
        resolved = ledger.external_directory(anchor.resolve(), root)
        ledger.require(resolved.name == ledger.root_key(root), "Ownership directory must retain the worktree identity")
        return resolved
    except ledger.LedgerError as error:
        raise ledger.LedgerError(
            f"{error}. Move the complete ownership directory {anchor} to unused external storage, "
            "retaining its worktree-identity name, and symlink the original path to its new location, then retry") from error


def read(path, root):
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_bytes())
        ledger.fields(value, "schema root storage")
        ledger.require(value["schema"] == 1 and value["root"] == str(root), "Wrong ownership identity")
        base = Path(value["storage"])
        ledger.require(base.is_absolute() and str(base) == value["storage"] and
                       base.name == ledger.root_key(root), "Invalid ownership storage")
        ledger.safe_path(Path(base.anchor), str(base.relative_to(base.anchor)))
        return base
    except (ledger.LedgerError, OSError, ValueError, TypeError, KeyError) as error:
        raise ledger.LedgerError(
            f"Review ownership unavailable at {path}: {error}; inspect retained ledgers and stop "
            "their workers, then use recover-ownership with the existing ledger, --reason "
            "and --shutdown-evidence. Do not initialize a replacement run") from error


def recovered_ledgers(root, run_id):
    try:
        folder = directory(root)
        records = list(folder.glob("RECOVERY-*.json"))
    except (ledger.LedgerError, OSError):
        return
    for record in records:
        try:
            record = ledger.safe_path(folder, record.name)
            if not record.is_file():
                continue
            value = json.loads(record.read_bytes())
            ledger.fields(value, "ledger reason shutdown_evidence")
            path = Path(value["ledger"])
            ledger.require(path.is_absolute() and path.name == "REVIEW_LEDGER.json" and
                           path.parent.name == run_id and path.parent.parent.name == ledger.root_key(root),
                           "Recovery belongs to a different review")
        except (ValueError, OSError, KeyError, TypeError):
            continue
        yield path


@contextmanager
def locked(root):
    folder = directory(root)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = ledger.safe_path(folder, "OWNER.json")
    with ledger.safe_path(folder, ".lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield path


def release_path(root, base):
    return ledger.safe_path(directory(root), f"RELEASE-{ledger.root_key(base)}.json")


def require_unreleased(root, base):
    ledger.require(not release_path(root, base).exists(),
                   f"Review store was released: {base}; its allowance is unavailable. Use inspect "
                   "for surviving evidence or close retained runs. Separately authorized work needs "
                   "init --storage with unused external storage retaining the worktree identity")


def unavailable(base):
    return (f"Review ownership storage unavailable: {base}; restore retained history with recover-ownership, "
            "or, if no usable copy survives, stop its native workers and use release-ownership "
            f"--storage {shlex.quote(str(base))} --replacement-storage <unused-external-store/{base.name}> "
            "--reason <loss-evidence> --shutdown-evidence <native-shutdown-evidence>")


def require_absent(base):
    try:
        base.stat()
    except FileNotFoundError:
        return
    raise ledger.LedgerError(
        f"Recorded store still exists: {base}; restore access and resume or close its retained runs")


def release(args, root):
    ledger.text(args.reason)
    ledger.text(args.shutdown_evidence)
    source = Path(args.storage)
    target = ledger.external_directory(Path(args.replacement_storage), root)
    ledger.require(target.name == ledger.root_key(root) and
                   not target.is_relative_to(source) and not source.is_relative_to(target),
                   "Choose a different unused external store retaining the worktree identity")
    with locked(root) as path:
        previous = read(path, root)
        record = release_path(root, source)
        if previous == target and record.is_file():
            saved = json.loads(record.read_bytes())
            ledger.fields(saved, "schema root storage replacement_storage owner outcome allowance "
                          "reason shutdown_evidence time")
            ledger.require(saved["schema"] == 1 and saved["root"] == str(root) and
                           saved["storage"] == str(source) and saved["replacement_storage"] == str(target) and
                           saved["outcome"] == "failed" and saved["allowance"] == "unavailable",
                           "Release receipt unavailable; inspect the current ownership and retained receipt")
            return saved
        ledger.require(previous == source, f"Release must name the recorded store: {previous}")
        require_absent(source)
        ledger.require(not release_path(root, target).exists(),
                       "Replacement store was already released; choose unused external storage")
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
        with ledger.safe_path(target, ".lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            ledger.require(set(target.iterdir()) == {target / ".lock"},
                           "Replacement store must be unused; preserve its contents and choose another")
            require_absent(source)
            result = {
                "schema": 1, "root": str(root), "storage": str(source), "replacement_storage": str(target),
                "owner": json.loads(path.read_bytes()), "outcome": "failed", "allowance": "unavailable",
                "reason": args.reason, "shutdown_evidence": args.shutdown_evidence,
                "time": datetime.now(timezone.utc).isoformat(),
            }
            if record.exists():
                ledger.atomic_write(record.with_name(f"RELEASE-ARCHIVE-{uuid4().hex}.json"), record.read_bytes())
            ledger.atomic_write(record, ledger.encode(result))
            ledger.atomic_write(path, ledger.encode({"schema": 1, "root": str(root), "storage": str(target)}))
            return result


def active_paths(base):
    ledger.require(base.is_dir(), unavailable(base))
    result = []
    for folder in base.iterdir():
        if not re.fullmatch(r"[a-f0-9]{32}", folder.name):
            continue
        path = ledger.safe_path(base, f"{folder.name}/REVIEW_LEDGER.json")
        if ledger.abandoned(path) is not None:
            continue
        _, state = ledger.load(path)
        if state["outcome"] in ("running", "interrupted", "blocked"):
            result.append(path)
    return result


def check(previous, base, args):
    if previous is None or previous == base:
        return
    active = active_paths(previous)
    if not active:
        return
    candidate = base / Path(getattr(args, "ledger", "")).parent.name / "REVIEW_LEDGER.json"
    if args.command in ("apply", "recover-ownership") and len(active) == 1 and candidate.parent.name == active[0].parent.name:
        try:
            ledger.external_directory(previous)
        except ledger.LedgerError:
            ledger.migration_preserved(ledger.migration_snapshot(active[0].parent), candidate.parent)
            return
    raise ledger.LedgerError(f"Existing active run: {active[0]}; resume or stop it first")


def recover(path, root, args):
    from review_history import close, remember, require_current

    ledger.text(args.reason)
    ledger.text(args.shutdown_evidence)
    target = ledger.ledger_path(root, args.ledger, allow_unavailable=True)
    saved = ledger.abandoned(target)
    if saved is None:
        saved, state = ledger.load(target)
        ledger.ensure_owner(saved, root)
        require_current(saved)
        remember(target, saved, state)
    else:
        ledger.ensure_owner(saved, root)
        close(target, root)
    if path.exists():
        archive = path.with_name(f"OWNER-{uuid4().hex}.json")
        ledger.atomic_write(archive, path.read_bytes())
    ledger.atomic_write(path.with_name(f"RECOVERY-{uuid4().hex}.json"), ledger.encode({
        "ledger": str(target), "reason": args.reason, "shutdown_evidence": args.shutdown_evidence,
    }))


@contextmanager
def guard(root, bases, args):
    with locked(root) as path, ExitStack() as locks:
        event = getattr(args, "event", None)
        closing = args.command in ("abandon", "recover-closure") or (
            args.command == "apply" and isinstance(event, dict) and event.get("type") == "stop")
        try:
            previous = read(path, root)
        except ledger.LedgerError as error:
            if not closing and args.command != "recover-ownership":
                raise
            if closing:
                print(f"review-ledger: ownership unchanged during closure: {error}", file=sys.stderr)
            previous = None
        base = bases[-1]
        if not closing:
            require_unreleased(root, base)
        if previous is None and not closing:
            default = ledger.state_directory() / "reviews" / ledger.root_key(root)
            if default.is_dir():
                previous = default
        if previous is not None and not closing and args.command != "recover-ownership":
            ledger.require(previous.is_dir(), unavailable(previous))
        for location in dict.fromkeys((*bases, *((previous,) if previous and previous.is_dir() else ()))):
            if args.command in ("init", "migrate"):
                location.mkdir(parents=True, exist_ok=True, mode=0o700)
            ledger.require(location.is_dir(), f"Review storage unavailable: {location}; restore retained history")
            handle = locks.enter_context(ledger.safe_path(location, ".lock").open("a"))
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        bind = not closing
        if args.command == "recover-ownership":
            if previous is not None and previous.is_dir():
                check(previous, base, args)
            recover(path, root, args)
        elif closing and previous is not None:
            from review_history import known_release

            try:
                check(previous, base, args)
            except (ledger.LedgerError, OSError) as error:
                print(f"review-ledger: ownership unchanged during closure: {error}", file=sys.stderr)
            else:
                bind = not (release_path(root, base).exists() or
                            known_release(root, Path(args.ledger).parent.name))
        elif not closing:
            check(previous, base, args)
        validated = None
        if args.command == "apply":
            from review_history import remember_location, require_current

            target = ledger.ledger_path(root, args.ledger)
            saved, state = ledger.load(target)
            require_current(saved, closing=closing)
            if bind:
                remember_location(target, root)
            validated = target, saved, state
        if bind:
            ledger.atomic_write(path, ledger.encode({"schema": 1, "root": str(root), "storage": str(base)}))
        yield validated
