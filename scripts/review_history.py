"""Write-ahead freshness witnesses independent of recoverable review stores."""

import json
import os
from pathlib import Path
import re
from uuid import uuid4

import review_ledger as ledger
import review_ownership as ownership


RECOVERY = ("Review history freshness unavailable; restore the latest witnessed history, or use "
            "abandon with --reason, --evidence and --shutdown-evidence after stopping workers. "
            "If its store is absent, use release-ownership with unused replacement storage. "
            "Unknown spending remains unavailable")


def witness_path(root, run_id):
    ledger.require(isinstance(run_id, str) and re.fullmatch(r"[a-f0-9]{32}", run_id), "Invalid review run ID")
    return ownership.directory(root) / f"HISTORY-{run_id}.json"


def read(root, run_id):
    path = witness_path(root, run_id)
    if not path.exists() and not path.is_symlink():
        return None
    try:
        ledger.require(not path.is_symlink() and path.is_file(), "Freshness witness is not a regular file")
        value = json.loads(path.read_bytes())
        ledger.fields(value, "schema root run_id digest events outcome stores unavailable")
        ledger.require(value["schema"] == 1 and value["root"] == str(root) and value["run_id"] == run_id,
                       "Wrong freshness identity")
        ledger.require(type(value["unavailable"]) is bool, "Invalid freshness availability")
        ledger.require(value["outcome"] in ("running", "interrupted", "blocked", "failed", "stalled",
                                            "limit_reached", "completed", "completed_with_exceptions"),
                       "Invalid witnessed outcome")
        ledger.require(isinstance(value["stores"], list) and all(
            isinstance(item, str) and Path(item).is_absolute() and Path(item).name == ledger.root_key(root)
            for item in value["stores"]), "Invalid witnessed storage")
        if value["digest"] is None:
            ledger.require(value["unavailable"] and value["events"] is None, "Missing witnessed history")
        else:
            ledger.require(isinstance(value["digest"], str) and re.fullmatch(r"[a-f0-9]{64}", value["digest"]) and
                           isinstance(value["events"], list) and all(
                               isinstance(item, str) and re.fullmatch(r"[a-f0-9]{64}", item)
                               for item in value["events"]), "Invalid witnessed history")
        return value
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise ledger.LedgerError(f"{RECOVERY}: {error}") from error


def require_current(value, *, closing=False):
    root = Path(value["root"])
    saved = read(root, value["run_id"])
    ledger.require(saved is not None and not saved["unavailable"] and
                   saved["digest"] == ledger.digest(ledger.encode(value)), RECOVERY)
    if not closing:
        ledger.require(not any(ownership.release_path(root, Path(base)).exists() for base in saved["stores"]),
                       RECOVERY)


def known_release(root, run_id):
    try:
        saved = read(root, run_id)
        return saved is not None and any(
            ownership.release_path(root, Path(base)).exists() for base in saved["stores"])
    except (OSError, ValueError, TypeError, KeyError):
        return False


def remember(path, value, state):
    root, run_id = Path(value["root"]), value["run_id"]
    prior = read(root, run_id)
    ledger.require(prior is None or not prior["unavailable"], RECOVERY)
    stores = list(dict.fromkeys([*(prior["stores"] if prior else []), str(path.parent.parent)]))
    result = {"schema": 1, "root": str(root), "run_id": run_id, "digest": ledger.digest(ledger.encode(value)),
              "events": [ledger.digest(ledger.encode(event)) for event in value["events"]],
              "outcome": state["outcome"], "stores": stores, "unavailable": False}
    ledger.atomic_write(witness_path(root, run_id), ledger.encode(result))


def remember_location(path, root):
    try:
        saved = read(root, path.parent.name)
    except (OSError, ValueError, TypeError, KeyError):
        return
    base = str(path.parent.parent)
    if saved is not None and base not in saved["stores"]:
        saved["stores"].append(base)
        ledger.atomic_write(witness_path(root, path.parent.name), ledger.encode(saved))


def close(path, root):
    run_id = path.parent.name
    target = witness_path(root, run_id)
    try:
        prior = read(root, run_id)
    except (OSError, ValueError, TypeError, KeyError):
        os.rename(target, target.with_name(f"HISTORY-ARCHIVE-{run_id}-{uuid4().hex}.json"))
        ledger.sync_directory(target.parent)
        prior = None
    result = prior or {"schema": 1, "root": str(root), "run_id": run_id, "digest": None,
                       "events": None, "stores": []}
    result.update(outcome="failed", unavailable=True)
    result["stores"] = list(dict.fromkeys([*result["stores"], str(path.parent.parent)]))
    ledger.atomic_write(target, ledger.encode(result))


def cached_invalidation(root, accepted):
    try:
        saved = read(root, Path(accepted["ledger"]).parent.name)
        if saved is None:
            return None
        if saved["unavailable"]:
            return "Accepted review history was closed; its allowance is unavailable"
        if any(ownership.release_path(root, Path(base)).exists() for base in saved["stores"]):
            return "Accepted review store was released; its allowance is unavailable"
        events = [ledger.digest(ledger.encode(event)) for event in accepted["history"]]
        if (saved["outcome"] == "failed" and len(saved["events"]) > len(events) and
                saved["events"][:len(events)] == events):
            return "Accepted review was invalidated as failed"
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return None
