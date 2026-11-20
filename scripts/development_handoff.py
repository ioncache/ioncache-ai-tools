#!/usr/bin/env python3
"""Generate bounded native dispatches and collect validated files, never model-relayed state."""

import argparse
import copy
from contextlib import contextmanager
import errno
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import time

import development_dispatch as dispatches
import development_executor as executor
import development_jobs as jobs
import development_manifest as plan
import development_models as models
import development_run as run
import review_ledger as review


class HandoffError(ValueError):
    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


@contextmanager
def locked(folder):
    deadline = time.monotonic() + 3
    while True:
        guard = run.locked(folder)
        try:
            guard.__enter__()
            break
        except OSError as error:
            if error.errno not in (errno.EAGAIN, errno.EACCES) or time.monotonic() >= deadline:
                raise HandoffError("state_unavailable", "Controller lock unavailable; retry this command "
                                   "after the current writer finishes. No worker was started.") from error
            time.sleep(0.02)
    try:
        yield
    finally:
        guard.__exit__(None, None, None)


def read_json(path):
    plan.require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 16 * 1024 * 1024,
                 f"Expected a regular bounded JSON file: {path}")
    return json.loads(path.read_bytes())


def persist(folder, state):
    if state["active"] is not None:
        state["history"][-1] = state["active"]
    state["revision"] += 1
    run.save(folder, state)


def choices(args, settings):
    configured = "autonomous-development-model-selection" in settings.disabled
    plan.require(args.models_file or args.configured_models or configured,
                 "Supply --models-file with resolved choices, or explicitly select --configured-models")
    values = read_json(Path(args.models_file)) if args.models_file else {
        role: {"model": None, "effort": None, "fallback": "configured"} for role in models.ROLES}
    values.setdefault("development-control", {"model": None, "effort": None, "fallback": "configured"})
    models.configuration({"models": values})
    plan.require(set(values) == set(models.ROLES), "Provide launch choices for every active worker role")
    return values


def batch_record(state, batch_id):
    record = state.get("handoffs", {}).get(batch_id)
    plan.require(record is not None, "Unknown batch; inspect prepare/status instead of reconstructing it")
    return record


def assignment_for(state, record, settings):
    plan.require(state["active"] is not None and state["active"]["id"] == record["assignment"],
                 "Batch no longer owns the active assignment; inspect its retained receipt")
    return run.request(state, settings)


def script_path(folder, batch_id):
    return review.safe_path(folder, f"handoffs/{batch_id}.js")


def render(folder, record):
    template = (folder / "executor/workflows/autonomous-development.js").read_text()
    marker = "const handoff = null"
    plan.require(template.count(marker) == 1, "Pinned dispatch template is unavailable")
    script = template.replace(marker, "const handoff = " +
                              json.dumps(record["spec"], ensure_ascii=True, sort_keys=True))
    path = script_path(folder, record["id"])
    path.parent.mkdir(mode=0o700, exist_ok=True)
    if path.exists():
        plan.require(path.is_file() and not path.is_symlink() and path.read_text() == script,
                     "Generated script changed; restore it from the pinned batch, not a model response")
    else:
        review.atomic_write(path, script.encode())
    return path


def descriptor(folder, record):
    action = "launch" if record["status"] == "prepared" else "collect"
    return {"action": action, "batch": record["id"], "assignment": record["assignment"],
            "script": str(render(folder, record)),
            "helper": str(folder / "executor/scripts/development_handoff.py")}


def request_identity(request):
    return json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def reserve_requests(state, assignment, requests):
    requests = jobs.review_requests(assignment, requests)
    saved = assignment["review_dispatch"]
    fresh = [item for item in requests if item["result_file"] not in saved["reservations"]]
    plan.require(saved["calls"] + len(fresh) < assignment["limits"]["review_dispatches"],
                 "Review dispatch allowance cannot cover the requested leaves and owner handback")
    checkpoint = copy.deepcopy(saved)
    for request in requests:
        path = request["result_file"]
        identity = request_identity(request)
        previous = checkpoint["reservations"].get(path)
        if previous:
            plan.require(not previous["started"] and previous["identity"] == plan.digest(identity.encode()),
                         "Review report belongs to a launched worker or a different reservation")
            continue
        checkpoint["calls"] += 1
        checkpoint["reservations"][path] = {
            "identity": identity, "dispatch": checkpoint["calls"], "started": False, "role": request["role"]}
    dispatches.checkpoint(state, {"assignment": assignment["id"], **checkpoint})
    state["active"]["pending_requests"] = requests


def review_jobs(state, assignment):
    pending = state["active"].get("pending_requests", [])
    if pending:
        count = 1
        if pending[0]["role"] != "fixer":
            while count < min(len(pending), 1000) and pending[count]["role"] != "fixer":
                count += 1
        return [{**item, "dispatch": assignment["review_dispatch"]["reservations"][item["result_file"]]["dispatch"]}
                for item in pending[:count]]
    saved = state["active"]["review_dispatch"]
    plan.require(saved["calls"] < assignment["limits"]["review_dispatches"],
                 "Review dispatch allowance exhausted; preserve the ledger and incomplete outcome")
    saved["calls"] += 1
    return [{"role": "review-owner", "dispatch": saved["calls"],
             "result_file": str(Path(assignment["store"]) / "reports" / assignment["id"] /
                                f"owner-{saved['calls']}.json")}]


def prepare(folder, args):
    with locked(folder):
        state = run.load(folder)
        settings = run.feature(Path(state["root"]))
        active = state["active"]
        if state["outcome"] != "running" and not (active and active.get("review_resume_ready")):
            return {"action": "inspect", "state": run.summary(state, settings)}
        plan.require_provider(state["manifest"], "claude-workflows")
        plan.validate(state["manifest"], folder / "inputs")
        pinned = executor.pin(folder)
        executor.require_current(folder)
        if active and active.get("review_resume_ready"):
            from review_ownership import locked as review_locked
            with review_locked(Path(active["root"])):
                dispatches.claim(state)
                previous = state.get("handoffs", {}).get(active.get("handoff"))
                if previous and previous["status"] != "collected":
                    previous["status"] = "reconciled"
                active.pop("handoff", None)
                active.pop("pending_requests", None)
                persist(folder, state)
        elif active and active.get("handoff"):
            record = batch_record(state, active["handoff"])
            if record["status"] in ("prepared", "claimed"):
                return descriptor(folder, record)
        elif active:
            raise HandoffError("outstanding_assignment",
                               "An assignment is outstanding without a generated batch. Collect its report or "
                               "reconcile native shutdown; do not infer that it never launched.")
        if state["active"] is None:
            run.reserve(state, settings, choices(args, settings))
            if state["active"] is None:
                persist(folder, state)
                return {"action": "inspect", "state": run.summary(state, settings)}
        assignment = run.request(state, settings)
        requests = (review_jobs(state, assignment) if assignment["role"] == "review" else
                    [{"role": assignment["role"], "result_file": assignment["result_file"], "dispatch": 1}])
        assignment = run.request(state, settings)
        batch_id = f"B{len(state.get('handoffs', {})) + 1:06d}"
        spec = {"batch": batch_id, "assignment": assignment["id"], "store": str(folder),
                "pluginRoot": str(pinned),
                "jobs": [jobs.job(assignment, item, pinned) for item in requests]}
        for item in spec["jobs"]:
            Path(item["result_file"]).parent.mkdir(parents=True, exist_ok=True)
        record = {"id": batch_id, "assignment": assignment["id"], "status": "prepared", "spec": spec,
                  "started": {}, "submitted": {}, "failures": {},
                  "before": None if assignment["role"] == "prepare" else run.capture(Path(assignment["root"]))}
        state.setdefault("handoffs", {})[batch_id] = record
        state["active"]["handoff"] = batch_id
        persist(folder, state)
        return descriptor(folder, record)


def claim(folder, args):
    with locked(folder):
        state = run.load(folder)
        settings = run.feature(Path(state["root"]))
        executor.require_current(folder)
        record = batch_record(state, args.batch)
        assignment = assignment_for(state, record, settings)
        plan.require(state["outcome"] == "running", "Run is stopped; inspect and reconcile it before dispatch")
        plan.require(record["status"] == "prepared",
                     "Batch already claimed; inspect native activity and collect reports, never launch it twice")
        render(folder, record)
        if record["before"] is not None:
            run.unchanged(record["before"], run.capture(Path(assignment["root"])))
            snapshot = review.digest(review.encode(record["before"]))
            plan.require(all(item["role"] != "reviewer" or item["packet"]["snapshot"] == snapshot
                             for item in record["spec"]["jobs"]),
                         "Reviewer packet is stale; preserve it and replan against the current snapshot")
        context = (run.claim_dispatch(state, SimpleNamespace(assignment=assignment["id"]), settings)
                   if assignment["requires_dispatch_claim"] else run.ExitStack())
        with context:
            record["status"] = "claimed"
            if assignment["role"] == "review":
                for item in record["spec"]["jobs"]:
                    if item["role"] in jobs.LEAVES:
                        state["active"]["review_dispatch"]["reservations"][item["result_file"]]["started"] = True
            persist(folder, state)
        return {"action": "launch_once", "batch": record["id"], "script": str(render(folder, record))}


def selected_job(record, number):
    plan.require(1 <= number <= len(record["spec"]["jobs"]), "Unknown job number")
    return record["spec"]["jobs"][number - 1]


def progress(state, record, job, event, settings):
    if job["role"] not in run.monitoring.ROLES or not run.monitoring.enabled(settings):
        return
    args = SimpleNamespace(assignment=record["assignment"], dispatch=job["dispatch"], role=job["role"],
                           category=job.get("packet", {}).get("review_type"), event=event, loop=None, cycle=None)
    try:
        run.monitoring.write(state, args)
    except (ValueError, OSError, KeyError, TypeError) as error:
        record["progress_error"] = str(error)


def start(folder, args):
    with locked(folder):
        state = run.load(folder)
        settings = run.feature(Path(state["root"]))
        executor.require_current(folder)
        record = batch_record(state, args.batch)
        assignment = assignment_for(state, record, settings)
        plan.require(state["outcome"] == "running" and record["status"] == "claimed",
                     "Worker needs a claimed active batch; inspect instead of starting stale work")
        job = selected_job(record, args.job)
        key = str(args.job)
        plan.require(key not in record["started"],
                     "Worker already started; inspect its report and effects instead of repeating work")
        if record["before"] is not None:
            run.unchanged(record["before"], run.capture(Path(assignment["root"])))
        if assignment["requires_dispatch_claim"]:
            run.require_cached_review_usable(state, assignment["pr"], Path(assignment["root"]))
        record["started"][key] = {"revision": state["revision"] + 1}
        progress(state, record, job, "started", settings)
        persist(folder, state)
        return {"result_file": job["result_file"], "assignment": assignment["id"]}


def report_for(assignment, job, path):
    report = read_json(path)
    jobs.validate(assignment, job, report)
    if job["role"] == "review-owner" and report["outcome"] != "dispatch":
        jobs.development_report(assignment, read_json(Path(assignment["result_file"])))
    return report


def submit(folder, args):
    with locked(folder):
        state = run.load(folder)
        settings = run.feature(Path(state["root"]))
        executor.require_current(folder)
        record = batch_record(state, args.batch)
        assignment = assignment_for(state, record, settings)
        job = selected_job(record, args.job)
        key = str(args.job)
        plan.require(record["status"] == "claimed" and key in record["started"],
                     "Report requires an actually started job in the claimed batch")
        if key in record["submitted"]:
            path = review.safe_path(folder, str(Path(job["result_file"]).relative_to(folder)))
            plan.require(record["submitted"][key]["sha256"] == plan.digest(path.read_bytes()),
                         "Submitted report changed; restore its retained bytes or reconcile, do not overwrite acceptance")
            return {"valid": True, **record["submitted"][key]}
        correction = "autonomous-development-report-correction" not in settings.disabled
        maximum = 3 if correction else 1
        plan.require(record["failures"].get(key, 0) < maximum,
                     "Report correction allowance exhausted; preserve candidates and reconcile the assignment")
        path = review.safe_path(folder, str(Path(job["result_file"]).relative_to(folder)))
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if args.command == "submit":
                candidate_path = Path(args.candidate)
                plan.require(candidate_path.is_absolute() and candidate_path.is_relative_to(folder),
                             "Candidate must be an absolute path inside the private run store")
                candidate_path = review.safe_path(folder, str(candidate_path.relative_to(folder)))
                candidate_bytes = candidate_path.read_bytes()
                plan.require(len(candidate_bytes) <= 16 * 1024 * 1024, "Candidate JSON exceeds the size limit")
                archive = review.safe_path(folder, f"handoffs/{record['id']}/{args.job}-"
                                           f"{plan.digest(candidate_bytes)}.json")
                archive.parent.mkdir(parents=True, exist_ok=True)
                review.atomic_write(archive, candidate_bytes)
                candidate = read_json(candidate_path)
                if job["role"] == "review-owner" and isinstance(candidate, dict) and "report" in candidate:
                    plan.fields(candidate, "outcome requests report")
                    plan.require(candidate["requests"] == [] and candidate["outcome"] in ("complete", "blocked"),
                                 "An owner development report must complete or block, without dispatch requests")
                    development = jobs.candidate_report(assignment, {"role": "review"}, candidate["report"])
                    jobs.development_report(assignment, development)
                    plan.require(development["outcome"] == candidate["outcome"], "Owner report outcomes differ")
                    review.atomic_write(Path(assignment["result_file"]), plan.encode(development))
                    candidate = {"outcome": candidate["outcome"], "requests": [],
                                 "result_file": assignment["result_file"]}
                report = jobs.candidate_report(assignment, job, candidate)
                jobs.validate(assignment, job, report)
                review.atomic_write(path, plan.encode(report))
            report_for(assignment, job, path)
        except (ValueError, KeyError, TypeError) as error:
            attempt = record["failures"].get(key, 0) + 1
            record["failures"][key] = attempt
            record["last_error"] = {"kind": "invalid_report", "job": args.job, "error": str(error)}
            persist(folder, state)
            raise HandoffError("invalid_report", f"{error}. Correction attempts remaining: {maximum - attempt}. "
                               "Correct only the report from existing evidence; do not repeat external effects.") from error
        record["submitted"][key] = {"result_file": str(path), "sha256": plan.digest(path.read_bytes())}
        progress(state, record, job, "reported", settings)
        persist(folder, state)
        return {"valid": True, **record["submitted"][key]}


def collect_reports(folder, state, record, settings):
    assignment = assignment_for(state, record, settings)
    reports = []
    for number, job in enumerate(record["spec"]["jobs"], 1):
        receipt = record["submitted"].get(str(number))
        if not receipt:
            raise HandoffError("missing_report", f"Job {number} has no validated report. Inspect native activity "
                               "and its original file; run finish for existing evidence, never repeat the worker.")
        path = review.safe_path(folder, str(Path(job["result_file"]).relative_to(folder)))
        plan.require(receipt["sha256"] == plan.digest(path.read_bytes()),
                     "Submitted report changed; preserve it and reconcile, never accept a changed receipt")
        reports.append(report_for(assignment, job, path))
    return assignment, reports


def collect_review(state, record, assignment, reports):
    first = record["spec"]["jobs"][0]
    if first["role"] == "review-owner":
        owner = reports[0]
        if owner["outcome"] == "dispatch":
            reserve_requests(state, assignment, owner["requests"])
            return None
        return read_json(Path(assignment["result_file"]))
    checkpoint = copy.deepcopy(state["active"]["review_dispatch"])
    for job, report in zip(record["spec"]["jobs"], reports):
        checkpoint["reports"].append({
            "role": job["role"], "result_file": job["result_file"],
            "outcome": "complete" if report["outcome"] == "complete" else "blocked"})
    pending = state["active"].get("pending_requests", [])
    remaining = pending[len(reports):]
    if first["role"] == "fixer" or any(report["outcome"] != "complete" for report in reports):
        checkpoint["reports"].extend({"role": item["role"], "result_file": item["result_file"],
                                      "outcome": "not_started"} for item in remaining)
        remaining = []
    dispatches.checkpoint(state, {"assignment": assignment["id"], **checkpoint})
    state["active"]["pending_requests"] = remaining
    return None


def collect(folder, args):
    with locked(folder):
        state = run.load(folder)
        record = batch_record(state, args.batch)
        if record["status"] == "collected":
            return record["receipt"]
        settings = run.feature(Path(state["root"]))
        executor.require_current(folder)
        plan.require(record["status"] == "claimed", "Batch has not been claimed")
        plan.validate(state["manifest"], folder / "inputs")
        assignment, reports = collect_reports(folder, state, record, settings)
        if assignment["role"] == "review":
            after = run.capture(Path(assignment["root"]))
            if record["spec"]["jobs"][0]["role"] == "fixer":
                run.preserve_checkout({"before": record["before"]}, after)
            else:
                run.unchanged(record["before"], after)
        if assignment["role"] == "review":
            report = collect_review(state, record, assignment, reports)
        else:
            report = reports[0]
        with run.ExitStack() as guards:
            if report is not None:
                guards.enter_context(run.complete(state, report, settings))
            record["status"] = "collected"
            record["receipt"] = {"action": "prepare", "batch": record["id"], "assignment": record["assignment"]}
            persist(folder, state)
        return record["receipt"]


def restore_executor(folder, args):
    with locked(folder):
        state = run.load(folder)
        plan.require(state["outcome"] != "running", "Interrupt scheduling and stop native workers before recovery")
        plan.text(args.shutdown_evidence)
        result = executor.restore(folder, Path(args.source).resolve())
        state.setdefault("executor_recoveries", []).append({
            "identity": result["identity"], "shutdown_evidence": args.shutdown_evidence})
        persist(folder, state)
        return result


def repair_script(folder, args):
    with locked(folder):
        state = run.load(folder)
        executor.require_current(folder)
        record = batch_record(state, args.batch)
        plan.require(record["status"] == "prepared",
                     "Only an unclaimed script may be repaired; collect or reconcile a claimed batch")
        path = script_path(folder, args.batch)
        if path.exists():
            plan.require(path.is_file() and not path.is_symlink(), "Generated script must be a regular file")
            retained = path.with_name(path.stem + "-changed-" + plan.digest(path.read_bytes()) + ".js")
            if retained.exists():
                plan.require(retained.is_file() and not retained.is_symlink() and
                             retained.read_bytes() == path.read_bytes(), "Script recovery archive differs")
                path.unlink()
            else:
                path.rename(retained)
        return descriptor(folder, record)


def resume_prepared(folder, args):
    with locked(folder):
        state = run.load(folder)
        settings = run.feature(Path(state["root"]))
        executor.require_current(folder)
        record = batch_record(state, args.batch)
        assignment_for(state, record, settings)
        plan.require(state["outcome"] == "blocked" and record["status"] == "prepared" and
                     not record["started"] and not state["active"].get("dispatch_claim"),
                     "Only a provably unclaimed prepared batch can resume this way; "
                     "reconcile native shutdown and effects for a claimed batch")
        plan.validate(state["manifest"], folder / "inputs")
        plan.text(args.reason)
        state["outcome"], state["reason"] = "running", args.reason
        state.pop("stop_kind", None)
        persist(folder, state)
        return descriptor(folder, record)


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="command", required=True)
    for name in ("prepare", "claim", "start", "finish", "submit", "collect", "restore-executor",
                 "repair-script", "resume-prepared"):
        command = commands.add_parser(name)
        command.add_argument("store")
        if name == "prepare":
            command.add_argument("--models-file")
            command.add_argument("--configured-models", action="store_true")
        elif name == "restore-executor":
            command.add_argument("--source", required=True)
            command.add_argument("--shutdown-evidence", required=True)
        else:
            command.add_argument("--batch", required=True)
        if name in ("start", "finish", "submit"):
            command.add_argument("--job", type=int, required=True)
        if name == "submit":
            command.add_argument("--candidate", required=True)
        if name == "resume-prepared":
            command.add_argument("--reason", required=True)
    return cli


def main():
    args = parser().parse_args()
    try:
        operations = {"prepare": prepare, "claim": claim, "start": start,
                      "submit": submit, "finish": submit, "collect": collect,
                      "restore-executor": restore_executor, "repair-script": repair_script,
                      "resume-prepared": resume_prepared}
        result = operations[args.command](Path(args.store).resolve(), args)
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        fallback = "state_unavailable" if isinstance(error, OSError) else "reconciliation_required"
        print(json.dumps({"ok": False, "kind": getattr(error, "kind", fallback),
                          "error": str(error), "recovery": "Inspect durable status and retained evidence. "
                          "Do not repeat a claimed worker, change limits, or edit RUN.json."}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
