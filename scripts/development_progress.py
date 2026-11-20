"""Private advisory progress and lock-free monitoring, separate from acceptance."""

import json
import math
from pathlib import Path
import re
import time

import development_manifest as plan
from review_assignments import PROJECT_ID
import review_ledger as review


FEATURE = "autonomous-development-progress"
ROLES = ("review-owner", "reviewer", "adjudicator", "validator", "fixer")
EVENTS = ("started", "checkpoint", "reported")


def enabled(settings):
    return FEATURE in settings.catalog and FEATURE not in settings.disabled


def write(state, args):
    assignment = state["active"]
    plan.require(assignment is not None and assignment["id"] == args.assignment and
                 assignment["role"] == "review", "Progress requires the current review assignment")
    maximum = state["manifest"]["limits"]["review_dispatches"]
    plan.require(1 <= args.dispatch <= maximum, "Progress dispatch is outside the approved allowance")
    if args.category is not None:
        plan.require(known_category(args.category), "Unknown progress category")
        plan.require(args.role == "reviewer", "Only reviewers have a progress category")
    for name, limit in (("loop", "review_loops"), ("cycle", "fix_cycles")):
        value = getattr(args, name)
        plan.require(value is None or (args.role == "review-owner" and
                     0 <= value <= state["manifest"]["limits"][limit]),
                     "Only review owners report bounded loop/cycle counts")
    folder = review.safe_path(Path(state["store"]), f"progress/{assignment['id']}")
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = review.safe_path(folder, f"{args.dispatch:06d}.json")
    plan.require(not path.exists() or path.is_file(), "Progress must be a regular file")
    old = json.loads(path.read_bytes()) if path.exists() else {}
    identity = {"assignment": args.assignment, "dispatch": args.dispatch,
                "role": args.role, "category": args.category}
    plan.require(not old or all(old.get(key) == value for key, value in identity.items()),
                 "Progress dispatch identity changed")
    if old.get("event") == "reported":
        return old
    record = {**old, **identity, "event": args.event,
              "updated_at": time.time(), "started_at": old.get("started_at", time.time())}
    for name in ("loop", "cycle"):
        if getattr(args, name) is not None:
            record[name] = getattr(args, name)
    review.atomic_write(path, plan.encode(record))
    return record


def category_names():
    path = Path(__file__).resolve().parents[1] / "skills/review-code/categories.json"
    catalog = json.loads(path.read_bytes())
    return {item["id"] for item in catalog["categories"]}


def known_category(value):
    return isinstance(value, str) and (value in category_names() or bool(PROJECT_ID.fullmatch(value)))


def records(state, assignment):
    if assignment is None or assignment["role"] != "review":
        return [], None
    result = []
    try:
        folder = review.safe_path(Path(state["store"]), f"progress/{assignment['id']}")
        if not folder.exists():
            return [], None
        for entry in sorted(folder.iterdir()):
            if not re.fullmatch(r"[0-9]{6,}\.json", entry.name):
                continue
            number = int(entry.stem)
            plan.require(1 <= number <= state["manifest"]["limits"]["review_dispatches"],
                         "Invalid progress dispatch")
            path = review.safe_path(folder, entry.name)
            plan.require(path.is_file() and path.stat().st_size <= 8192, "Invalid progress file")
            item = json.loads(path.read_bytes())
            plan.require(item["assignment"] == assignment["id"] and item["dispatch"] == number and
                         item["role"] in ROLES and item["event"] in EVENTS and
                         (item.get("category") is None or known_category(item["category"])),
                         "Invalid progress record")
            projected = {key: item[key] for key in ("dispatch", "role", "category", "event")}
            for key in ("loop", "cycle", "updated_at", "started_at"):
                if key in item:
                    plan.require(type(item[key]) in (int, float) and math.isfinite(item[key]),
                                 "Invalid progress counter")
                    projected[key] = item[key]
            result.append(projected)
    except (OSError, ValueError, KeyError, TypeError):
        return result, "Progress unavailable; retained state is not evidence of worker completion"
    return result, None


def condition(state):
    if state["outcome"] == "completed":
        return "complete"
    if state["outcome"] == "failed" and "allowance exhausted" in state.get("reason", "").lower():
        return "exhausted"
    if state["outcome"] == "blocked":
        return state.get("stop_kind", "blocked")
    return state["outcome"]


def snapshot(state):
    active = state["active"]
    latest = active or (state["history"][-1] if state["history"] else None)
    progress, error = records(state, latest)
    return {
        "run": state["id"], "store": state["store"], "revision": state["revision"],
        "outcome": state["outcome"], "condition": condition(state),
        "reason": "See private run diagnostics" if state.get("reason") else None,
        "diagnostic_reference": str(Path(state["store"]) / "RUN.json") + "#/reason"
        if state.get("reason") else None,
        "updated_at": state.get("updated_at"),
        "consumed_assignments": len(state["history"]), "limits": state["manifest"]["limits"],
        "assignment": ({key: active[key] for key in ("id", "role", "pr", "task", "attempt")}
                       if active else None),
        "progress_assignment": latest["id"] if latest else None,
        "handoff": handoff_progress(state, latest),
        "review_progress": progress, "progress_error": error,
        "prs": {key: {name: value[name] for name in ("position", "waiting", "url")}
                for key, value in state["prs"].items()},
    }


def handoff_progress(state, assignment):
    batch = state.get("handoffs", {}).get(assignment.get("handoff")) if assignment else None
    if not batch:
        return None
    return {"batch": batch["id"], "status": batch["status"],
            "started_jobs": len(batch["started"]), "validated_reports": len(batch["submitted"]),
            "validation_failures": sum(batch["failures"].values()),
            "diagnostic_reference": str(Path(state["store"]) / "RUN.json") +
            f"#/handoffs/{batch['id']}/last_error" if batch.get("last_error") else None}


def emit(value):
    print(json.dumps(value, sort_keys=True, ensure_ascii=True), flush=True)


def watch(folder, load, args):
    previous = None
    changed = time.monotonic()
    last_update = None
    while True:
        try:
            value = snapshot(load(folder))
        except (OSError, ValueError, KeyError, TypeError):
            emit({"event": "unavailable", "store": str(folder),
                  "reason": "Durable run state unavailable; no completion can be inferred"})
            return 2
        if value != previous:
            updates = [value["updated_at"]] + [item["updated_at"] for item in value["review_progress"]
                                              if "updated_at" in item]
            latest = max((stamp for stamp in updates if stamp is not None), default=None)
            if previous is not None:
                changed = time.monotonic()
            last_update = latest
            emit({"event": "state", **value})
            previous = value
        if value["outcome"] != "running":
            return 0 if value["outcome"] == "completed" else 1
        if value["progress_error"]:
            return 2
        elapsed = time.monotonic() - changed
        if last_update is not None:
            elapsed = max(elapsed, time.time() - last_update)
        if elapsed >= args.stale_after:
            emit({"event": "stalled", **value,
                  "notice": "No durable advancement observed; this does not prove the worker stopped"})
            return 3
        time.sleep(args.interval)


def positive_seconds(value):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Expected finite positive seconds")
    return value


def add_commands(commands):
    command = commands.add_parser("watch", help="Follow durable state without locking or changing it")
    command.add_argument("store")
    command.add_argument("--interval", type=positive_seconds, default=1.0)
    command.add_argument("--stale-after", type=positive_seconds, default=300.0)
    command = commands.add_parser("progress", help="Record private advisory review progress, not acceptance")
    command.add_argument("store")
    command.add_argument("--assignment", required=True)
    command.add_argument("--dispatch", type=int, required=True)
    command.add_argument("--role", choices=ROLES, required=True)
    command.add_argument("--event", choices=EVENTS, required=True)
    command.add_argument("--category")
    command.add_argument("--loop", type=int)
    command.add_argument("--cycle", type=int)
