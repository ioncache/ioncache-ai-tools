"""Worktree-wide review ownership, independent of ledger storage selection."""

from contextlib import contextmanager, ExitStack
import fcntl
import json
from pathlib import Path
import re
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


def active_paths(base):
    ledger.require(base.is_dir(), f"Review ownership storage unavailable: {base}; restore it or use "
                   "recover-ownership with the retained ledger and native shutdown evidence")
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


def recover(path, root, base, args):
    ledger.text(args.reason)
    ledger.text(args.shutdown_evidence)
    target = ledger.ledger_path(root, args.ledger, allow_unavailable=True)
    saved = ledger.abandoned(target)
    if saved is None:
        saved, _ = ledger.load(target)
    ledger.ensure_owner(saved, root)
    if path.exists():
        archive = path.with_name(f"OWNER-{uuid4().hex}.json")
        ledger.atomic_write(archive, path.read_bytes())
    ledger.atomic_write(path.with_name(f"RECOVERY-{uuid4().hex}.json"), ledger.encode({
        "ledger": str(target), "reason": args.reason, "shutdown_evidence": args.shutdown_evidence,
    }))


@contextmanager
def guard(root, bases, args):
    folder = directory(root)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = ledger.safe_path(folder, "OWNER.json")
    with ExitStack() as locks:
        owner_lock = locks.enter_context(ledger.safe_path(folder, ".lock").open("a"))
        fcntl.flock(owner_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
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
        if previous is None and not closing:
            default = ledger.state_directory() / "reviews" / ledger.root_key(root)
            if default.is_dir():
                previous = default
        if previous is not None and not closing and args.command != "recover-ownership":
            ledger.require(previous.is_dir(), f"Review ownership storage unavailable: {previous}; "
                           "use recover-ownership with retained history and native shutdown evidence")
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
            recover(path, root, base, args)
        elif closing and previous is not None:
            try:
                check(previous, base, args)
            except (ledger.LedgerError, OSError) as error:
                print(f"review-ledger: ownership unchanged during closure: {error}", file=sys.stderr)
            else:
                bind = True
        elif not closing:
            check(previous, base, args)
        if bind:
            ledger.atomic_write(path, ledger.encode({"schema": 1, "root": str(root), "storage": str(base)}))
        yield
