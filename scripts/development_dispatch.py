"""Durable review dispatch accounting and one-use continuation handoffs."""

from pathlib import Path

import development_manifest as plan
import review_ledger as review


def empty(calls=0):
    return {"calls": calls, "reservations": {}, "reports": []}


def active_review(state):
    active = state["active"]
    plan.require(active is not None and active["role"] == "review",
                 "An active review assignment is required")
    return active


def reservation(state, path, value):
    active = active_review(state)
    folder = review.safe_path(Path(state["store"]), f"reports/{active['id']}")
    plan.require(Path(path).is_relative_to(folder) and Path(path) != folder,
                 "Review result path is outside the assigned private directory")
    review.safe_path(folder, str(Path(path).relative_to(folder)))
    plan.fields(value, "identity dispatch started role")
    plan.text(value["identity"])
    plan.require(type(value["dispatch"]) is int and value["dispatch"] > 0 and
                 type(value["started"]) is bool and
                 value["role"] in ("reviewer", "adjudicator", "validator", "fixer"),
                 "Invalid review reservation")


def checkpoint(state, data):
    active = active_review(state)
    plan.fields(data, "assignment calls reservations reports")
    plan.require(data["assignment"] == active["id"] and state["outcome"] == "running" and
                 not active.get("review_resume_ready"), "Review dispatch is not claimed for this assignment")
    old = active.get("review_dispatch")
    plan.require(old is not None, "Dispatch accounting unavailable; use resume-review with native dispatch evidence")
    calls = data["calls"]
    plan.require(type(calls) is int and old["calls"] <= calls <= state["manifest"]["limits"]["review_dispatches"],
                 "Review dispatch allowance cannot be reset or exceeded")
    reservations = data["reservations"]
    plan.require(isinstance(reservations, dict) and isinstance(data["reports"], list),
                 "Invalid review checkpoint")
    plan.require(old["reservations"].keys() <= reservations.keys(), "Review reservations cannot be removed")
    slots = set()
    checked = {}
    reserved_paths = {str(Path(path)) for path in old["reservations"]}
    for path, value in reservations.items():
        reservation(state, path, value)
        previous = old["reservations"].get(path)
        if previous is None or value["identity"] != previous["identity"]:
            value = {**value, "identity": review.digest(value["identity"].encode())}
        if previous is not None:
            plan.require(all(value[key] == previous[key] for key in ("identity", "dispatch", "role")) and
                         (not previous["started"] or value["started"]), "Review reservation cannot be replaced or reset")
        else:
            plan.require(str(Path(path)) == path and "//" not in path,
                         "Review result paths must be normalized; use distinct canonical report paths")
            plan.require(path not in reserved_paths, "Review result path is already reserved; use a fresh path")
            reserved_paths.add(path)
            plan.require(old["calls"] < value["dispatch"] <= calls,
                         "New review reservation must consume a fresh dispatch slot")
            plan.require(not Path(path).exists(), "Existing review reports cannot be overwritten by a fresh reservation")
        plan.require(value["dispatch"] <= calls and value["dispatch"] not in slots, "Duplicate review dispatch slot")
        slots.add(value["dispatch"])
        checked[path] = value
    reports = data["reports"]
    plan.require(reports[:len(old["reports"])] == old["reports"], "Review handbacks cannot be removed or rewritten")
    for item in reports[len(old["reports"]):]:
        saved = reservations.get(item.get("result_file")) if isinstance(item, dict) else None
        plan.require(saved is not None and item.get("role") == saved["role"] and
                     item.get("outcome") in ("complete", "blocked", "not_started", "interrupted") and
                     (item["outcome"] == "not_started" or saved["started"]), "Invalid review handback")
    active["review_dispatch"] = {"calls": calls, "reservations": checked, "reports": reports}
    state["history"][-1] = active


def prepare_resume(active, ledger, evidence):
    active["resume_ledger"] = str(ledger)
    active.setdefault("review_resumptions", []).append({"ledger": str(ledger), **evidence})
    active["review_resume_ready"] = True


def resume_path(active, argument):
    root = Path(active["root"])
    path = review.ledger_path(root, argument)
    plan.require(path.parent.parent == Path(active["review_storage"]), "Ledger is outside the pinned review_storage")
    ledger, _ = review.load(path)
    review.ensure_owner(ledger, root)
    return path


def resume(state, args):
    active = active_review(state)
    plan.require(state["outcome"] in ("running", "blocked"), "Review cannot resume from this outcome")
    plan.text(args.reason)
    plan.text(args.shutdown_evidence)
    path = resume_path(active, args.ledger)
    if "review_dispatch" not in active:
        plan.require(args.used_dispatches is not None and args.dispatch_evidence is not None,
                     "Legacy dispatch accounting is unavailable; supply --used-dispatches and "
                     "--dispatch-evidence from native history, or collect a finished report. "
                     "If spending cannot be established, retain the incomplete run without launching more workers")
        plan.text(args.dispatch_evidence)
        used = args.used_dispatches
        plan.require(type(used) is int and 0 <= used <= state["manifest"]["limits"]["review_dispatches"],
                     "Supply observed consumed dispatches, including reserved and failed calls; never guess")
        active["review_dispatch"] = empty(used)
        active["dispatch_reconciliation"] = {"used": used, "evidence": args.dispatch_evidence}
    else:
        plan.require(args.used_dispatches is None and args.dispatch_evidence is None,
                     "Existing dispatch accounting cannot be replaced")
    prepare_resume(active, path, {"reason": args.reason, "shutdown_evidence": args.shutdown_evidence})
    state["history"][-1] = active


def claim(state):
    active = active_review(state)
    plan.require(active.get("review_resume_ready") and "review_dispatch" in active,
                 "Review continuation requires resume-review with native shutdown evidence")
    plan.require(state["outcome"] in ("running", "blocked"), "Review cannot continue from this outcome")
    resume_path(active, active["resume_ledger"])
    active["review_resume_ready"] = False
    state["outcome"], state["reason"] = "running", None
    state.pop("stop_kind", None)
    state["history"][-1] = active
