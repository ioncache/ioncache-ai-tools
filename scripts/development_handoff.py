#!/usr/bin/env python3
"""Generate bounded native dispatches and collect validated files, never model-relayed state."""

import argparse
import copy
from contextlib import contextmanager
import errno
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import time

import development_dispatch as dispatches
import development_executor as executor
import development_jobs as jobs
from development_jobs import MAX_JSON_BYTES, read_bytes
import development_manifest as plan
import development_models as models
import development_run as run
import plugin_config
import review_ledger as review


# Claude's Workflow tool refuses scripts over 524,288 bytes; keep a margin below it.
SCRIPT_BYTES = 480_000
LAUNCH_FIELDS = ("role", "options", "result_file", "prompt")
# Claude restarts a stalled workflow agent at most five times:
# https://code.claude.com/docs/en/workflows
MAX_RESTARTS = 5


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
    return jobs.decode_json(read_bytes(path))


def read_document(path, record, number, expected=None):
    content = read_bytes(path)
    identity = plan.digest(content)
    archive = review.safe_path(Path(record["spec"]["store"]),
                               f"handoffs/{record['id']}/{number}-{identity}.json")
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists() or plan.digest(read_bytes(archive)) != identity:
        review.atomic_write(archive, content)
    if expected is not None and identity != expected:
        raise HandoffError("changed_report", "Submitted report changed; restore its retained bytes before retrying")
    return jobs.decode_json(content), identity


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


def script_text(folder, spec):
    """Renders the launch script with only the job fields the template reads.

    Reviewer packets are already embedded in their prompts; RUN.json keeps the full
    spec, so repeating them would only bring the script closer to the host size limit.
    """
    template = (folder / "executor/workflows/autonomous-development.js").read_text()
    marker = "const handoff = null"
    plan.require(template.count(marker) == 1, "Pinned dispatch template is unavailable")
    launch = {**spec, "jobs": [{key: item[key] for key in LAUNCH_FIELDS} for item in spec["jobs"]]}
    return template.replace(marker, "const handoff = " + json.dumps(launch, ensure_ascii=True, sort_keys=True))


def launchable_jobs(folder, spec):
    """Keeps the longest job prefix whose script fits the Workflow tool's size limit.

    The remaining reviewer requests stay pending and run in later batches.
    """
    count = len(spec["jobs"])
    while len(script_text(folder, {**spec, "jobs": spec["jobs"][:count]}).encode()) > SCRIPT_BYTES:
        plan.require(count > 1, f"The launch script for {spec['jobs'][0]['result_file']} alone exceeds the "
                     "Workflow tool's size limit, so no batch was created. Run interrupt, then "
                     "resume-review with native shutdown evidence, then prepare, so the review owner "
                     "can replan that request smaller.")
        count -= 1
    return spec["jobs"][:count]


def require_launchable(folder, record, assignment, requests):
    """Rejects an owner request whose own launch script would exceed the size limit.

    Checking at submission returns a correctable report error to the owner,
    rather than leaving an unlaunchable request queued for prepare.
    """
    executor_root = Path(record["spec"]["pluginRoot"])
    for request in requests:
        spec = {**record["spec"], "jobs": [jobs.job(assignment, request, executor_root)]}
        plan.require(len(script_text(folder, spec).encode()) <= SCRIPT_BYTES,
                     f"Request for {request['result_file']} is too large to launch in one Workflow "
                     "script; shorten its prompt, or report the review blocked if a frozen "
                     "reviewer packet cannot fit")


def render(folder, record):
    script = script_text(folder, record["spec"])
    path = script_path(folder, record["id"])
    path.parent.mkdir(mode=0o700, exist_ok=True)
    if path.exists():
        plan.require(path.is_file() and not path.is_symlink() and path.read_text() == script,
                     "Generated script changed; restore it from the pinned batch, not a model response")
    else:
        review.atomic_write(path, script.encode())
    return path


def launch_copy(folder, state, record, launch_dir):
    """Returns a launchable path for the batch script, copying it where the host can read it.

    Some hosts only load workflow scripts from their working directories, while the
    private store must stay outside every repository. The store copy remains
    authoritative: a differing launch copy is retained and rewritten from it.
    """
    source = render(folder, record)
    if launch_dir is None:
        return source
    directory = Path(launch_dir)
    plan.require(directory.is_absolute(), "Launch directory must be an absolute path")
    directory = directory.resolve()
    plan.require(directory.is_dir(), "Launch directory must be an existing directory")
    info = directory.stat()
    plan.require(info.st_uid == os.getuid() and not info.st_mode & 0o022,
                 "Launch directory must be owned by this user and not group- or world-writable; "
                 "use a private session directory such as the host's scratchpad")
    protected = [run.roots(state, None)] + [run.roots(state, item["id"]) for item in state["manifest"]["prs"]]
    plan.require(not any(directory.is_relative_to(path) for path in protected),
                 "Launch directory must be outside the launch repository and planned worktrees")
    content = source.read_bytes()
    path = review.safe_path(directory, f"ioncache-{state['id']}-{record['id']}.js")
    if path.exists() or path.is_symlink():
        plan.require(path.is_file() and not path.is_symlink(), "Launch copy must be a regular file")
        current = path.read_bytes()
        if current == content:
            path.chmod(0o600)
            return path
        path.rename(path.with_name(f"{path.stem}-changed-{plan.digest(current)}.js"))
    review.atomic_write(path, content)
    plan.require(path.read_bytes() == content, "Launch copy differs from the generated script")
    return path


def descriptor(folder, state, record, launch_dir=None):
    action = "launch" if record["status"] == "prepared" else "collect"
    script = launch_copy(folder, state, record, launch_dir)
    return {"action": action, "batch": record["id"], "assignment": record["assignment"],
            "script": str(script), "script_sha256": plan.digest(script.read_bytes()),
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
    directory = review.safe_path(Path(assignment["store"]), f"reports/owners/{assignment['id']}")
    path = directory / f"owner-{saved['calls']}.json"
    suffix = 0
    while path.exists() or path.is_symlink() or str(path) in saved["reservations"]:
        suffix += 1
        path = directory / f"owner-{saved['calls']}-{suffix}.json"
    return [{"role": "review-owner", "dispatch": saved["calls"],
             "result_file": str(path)}]


def prepare(folder, args):
    with locked(folder), run.ExitStack() as guards:
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
            guards.enter_context(review_locked(Path(active["root"])))
            dispatches.claim(state)
            previous = state.get("handoffs", {}).get(active.get("handoff"))
            if previous and previous["status"] != "collected":
                previous["status"] = "reconciled"
            active.pop("handoff", None)
            active.pop("pending_requests", None)
        elif active and active.get("handoff"):
            record = batch_record(state, active["handoff"])
            if record["status"] in ("prepared", "claimed"):
                return descriptor(folder, state, record, args.launch_dir)
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
        spec["jobs"] = launchable_jobs(folder, spec)
        for item in spec["jobs"]:
            Path(item["result_file"]).parent.mkdir(parents=True, exist_ok=True)
        record = {"id": batch_id, "assignment": assignment["id"], "status": "prepared", "spec": spec,
                  "started": {}, "submitted": {}, "failures": {},
                  "before": None if assignment["role"] == "prepare" else run.capture(Path(assignment["root"]))}
        state.setdefault("handoffs", {})[batch_id] = record
        state["active"]["handoff"] = batch_id
        persist(folder, state)
        return descriptor(folder, state, record, args.launch_dir)


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
        if record["before"] is not None:
            run.unchanged(record["before"], run.capture(Path(assignment["root"])))
            snapshot = review.digest(review.encode(record["before"]))
            plan.require(all(item["role"] != "reviewer" or item["packet"]["snapshot"] == snapshot
                             for item in record["spec"]["jobs"]),
                         "Reviewer packet is stale; preserve it and replan against the current snapshot")
        # A rejected launch directory must leave the batch claimable, so copy before claiming.
        script = launch_copy(folder, state, record, args.launch_dir)
        context = (run.claim_dispatch(state, SimpleNamespace(assignment=assignment["id"]), settings)
                   if assignment["requires_dispatch_claim"] else run.ExitStack())
        with context:
            record["status"] = "claimed"
            if assignment["role"] == "review":
                for item in record["spec"]["jobs"]:
                    if item["role"] in jobs.LEAVES:
                        state["active"]["review_dispatch"]["reservations"][item["result_file"]]["started"] = True
            persist(folder, state)
        return {"action": "launch_once", "batch": record["id"], "script": str(script),
                "script_sha256": plan.digest(script.read_bytes())}


def release(folder, args):
    """Returns a claimed batch that never started to the queue, so prepare can issue a new batch.

    A host can refuse a claimed script before starting it, for example when it is too large.
    Without a start receipt no worker ran, and a stale launch of the released script fails
    its start check, so its work is reissued once rather than repeated.
    """
    with locked(folder):
        state = run.load(folder)
        settings = run.feature(Path(state["root"]))
        executor.require_current(folder)
        record = batch_record(state, args.batch)
        assignment = assignment_for(state, record, settings)
        plan.require(state["outcome"] == "running" and record["status"] == "claimed",
                     "Only a claimed batch of the running assignment can be released")
        plan.require(not record["started"] and not record["submitted"],
                     "A worker started this batch; collect or reconcile it instead of releasing it")
        plan.text(args.evidence)
        if assignment["role"] == "review":
            reservations = state["active"]["review_dispatch"]["reservations"]
            for item in record["spec"]["jobs"]:
                if item["role"] in jobs.LEAVES:
                    reservations[item["result_file"]]["started"] = False
        state["active"].pop("dispatch_claim", None)
        record["status"] = "released"
        record["release"] = {"evidence": args.evidence, "revision": state["revision"] + 1}
        persist(folder, state)
        return {"action": "prepare", "batch": record["id"], "assignment": record["assignment"]}


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


def restart(folder, state, record, job, key, assignment):
    """Lets the host's replacement for a started worker continue its job.

    Claude restarts a stalled workflow agent from the same prompt, and a
    relaunched run starts unfinished agents over; the earlier attempt no longer
    runs. For roles whose effects stay in the private store or the reviewed
    worktree, a second start is treated as that replacement, which must
    reconcile partial effects rather than repeat them. Collection still checks
    drift and report bindings, so the restart skips the fresh-start drift check.
    """
    # The helper cannot tell a restart from an accidental second launch, which
    # would leave two workers running. Roles with external effects keep the
    # strict refusal, so a commit, push, PR or publication is never repeated.
    plan.require(job["role"] not in run.REVIEW_DEPENDENT_ROLES,
                 f"Worker already started, and {job['role']} has external effects, so a restart cannot "
                 "continue it. Return this limitation; the launcher inspects its report and remote "
                 "effects, then collects it or retires it with shutdown evidence for a counted retry.")
    entry = record["started"][key]
    restarts = entry.get("restarts", 0)
    plan.require(restarts < MAX_RESTARTS,
                 "Worker restart allowance exhausted; leave the job for collection or reconciliation "
                 "and return this limitation without repeating its effects")
    entry["restarts"] = restarts + 1
    persist(folder, state)
    rejection = record.get("rejected", {}).get(key)
    reported = key in record["submitted"] and rejection is None
    if rejection:
        instruction = (f"Collection rejected the earlier report: {rejection['error']}. Correct only the "
                       "report from existing evidence and resubmit it; do not repeat work or effects.")
    elif reported:
        instruction = "A validated report already exists; return without repeating work."
    else:
        instruction = ("An earlier attempt of this job started and may have left partial effects. Inspect the "
                       "existing report, candidate and actual state, reconcile, then do only the remaining work.")
    return {"result_file": job["result_file"], "assignment": assignment["id"], "restart": restarts + 1,
            "reported": reported, "instruction": instruction}


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
        if key in record["started"]:
            return restart(folder, state, record, job, key, assignment)
        if record["before"] is not None:
            run.unchanged(record["before"], run.capture(Path(assignment["root"])))
        if assignment["requires_dispatch_claim"]:
            run.require_cached_review_usable(state, assignment["pr"], Path(assignment["root"]))
        record["started"][key] = {"revision": state["revision"] + 1}
        progress(state, record, job, "started", settings)
        persist(folder, state)
        return {"result_file": job["result_file"], "assignment": assignment["id"]}


def report_for(assignment, record, number, *, expected=None, bind_reference=False):
    job = selected_job(record, number)
    folder = Path(assignment["store"])
    path = review.safe_path(folder, str(Path(job["result_file"]).relative_to(folder)))
    report, identity = read_document(path, record, number, expected.get("sha256") if expected else None)
    jobs.validate(assignment, job, report)
    if job["role"] == "review-owner" and report["outcome"] == "dispatch":
        require_launchable(folder, record, assignment, report["requests"])
    receipt = {"result_file": str(path), "sha256": identity}
    development = None
    if job["role"] == "review-owner" and report["outcome"] != "dispatch":
        if expected and "development_sha256" not in expected and not bind_reference:
            raise HandoffError("unbound_report", "Legacy owner receipt has no referenced-report binding. "
                               "Run finish to validate and bind the current evidence before collection.")
        reference = review.safe_path(folder, str(Path(assignment["result_file"]).relative_to(folder)))
        development, identity = read_document(
            reference, record, number, expected.get("development_sha256") if expected else None)
        jobs.development_report(assignment, development)
        plan.require(report["outcome"] == development["outcome"], "Owner report outcomes differ")
        receipt["development_sha256"] = identity
    return {"report": report, "development": development, "receipt": receipt}


def correction_limit(settings):
    return 1 if "autonomous-development-report-correction" in settings.disabled else 3


def report_failure(record, number, error, settings, *, receipt=None):
    key = str(number)
    previous = record.get("rejected", {}).get(key)
    if receipt is None or previous is None or previous["receipt"] != receipt:
        record["failures"][key] = record["failures"].get(key, 0) + 1
    kind = "controller_rejected" if receipt else "invalid_report"
    if receipt:
        record.setdefault("rejected", {})[key] = {"receipt": receipt, "error": str(error)}
    record["last_error"] = {"kind": kind, "job": number, "error": str(error)}
    remaining = max(0, correction_limit(settings) - record["failures"][key])
    return HandoffError(kind, f"{error}. Correction attempts remaining: {remaining}. "
                        "Correct only the report from existing evidence; do not repeat external effects.")


def candidate_path(folder, value):
    path = Path(value)
    if not path.is_absolute():
        path = folder / path
    plan.require(path.is_relative_to(folder), "Candidate must be inside the private run store; "
                 "relative paths are resolved from that store")
    return review.safe_path(folder, str(path.relative_to(folder)))


def candidate_reports(assignment, job, candidate):
    development = None
    if job["role"] == "review-owner" and isinstance(candidate, dict) and "report" in candidate:
        plan.fields(candidate, "outcome requests report")
        plan.require(candidate["requests"] == [] and candidate["outcome"] in ("complete", "blocked"),
                     "An owner development report must complete or block, without dispatch requests")
        development = jobs.candidate_report(assignment, {"role": "review"}, candidate["report"])
        jobs.development_report(assignment, development)
        if development["outcome"] == "complete":
            jobs.validate_data(assignment, "review", development["data"])
        plan.require(development["outcome"] == candidate["outcome"], "Owner report outcomes differ")
        candidate = {"outcome": candidate["outcome"], "requests": [],
                     "result_file": assignment["result_file"]}
    report = jobs.candidate_report(assignment, job, candidate)
    jobs.validate(assignment, job, report)
    return report, development


def check_report(folder, args):
    state = run.load(folder)
    catalog = plugin_config.defaults()
    disabled = plugin_config.synchronize(state["root"], catalog=catalog, persist=False, strict=True)
    settings = run.feature(Path(state["root"]),
                           plugin_config.FeatureSettings(frozenset(catalog), frozenset(disabled)))
    executor.require_current(folder)
    record = batch_record(state, args.batch)
    assignment = assignment_for(state, record, settings)
    job = selected_job(record, args.job)
    candidate = read_json(candidate_path(folder, args.candidate))
    report, _ = candidate_reports(assignment, job, candidate)
    if job["role"] == "review-owner" and report["outcome"] == "dispatch":
        require_launchable(folder, record, assignment, report["requests"])
    return {"valid": True, "accepted": False,
            "next": "Submit or recover-report, then collect for the unchanged acceptance checks"}


def write_candidate(assignment, record, args):
    folder = Path(assignment["store"])
    job = selected_job(record, args.job)
    candidate, identity = read_document(candidate_path(folder, args.candidate), record, args.job)
    report, development = candidate_reports(assignment, job, candidate)
    if development is not None:
        reference = review.safe_path(folder, str(Path(assignment["result_file"]).relative_to(folder)))
        review.atomic_write(reference, plan.encode(development))
    path = review.safe_path(folder, str(Path(job["result_file"]).relative_to(folder)))
    review.atomic_write(path, plan.encode(report))
    return identity


def begin_report_recovery(record, args, settings):
    feature = "autonomous-development-report-recovery"
    plan.require(feature in settings.catalog and feature not in settings.disabled,
                 "Report recovery is disabled; precheck and existing evidence remain available")
    key = str(args.job)
    plan.require(record["failures"].get(key, 0) >= correction_limit(settings),
                 "Report allowance remains; use submit or finish for this job")
    plan.require(key not in record.get("report_recoveries", {}),
                 "This job's report recovery was already used; preserve its result and remaining evidence")
    plan.text(args.evidence)
    plan.text(args.shutdown_evidence)
    record.setdefault("report_recoveries", {})[key] = {
        "evidence": args.evidence, "shutdown_evidence": args.shutdown_evidence, "outcome": "attempted"}


def submit(folder, args):
    with locked(folder):
        state = run.load(folder)
        settings = run.feature(Path(state["root"]))
        executor.require_current(folder)
        record = batch_record(state, args.batch)
        assignment = assignment_for(state, record, settings)
        job = selected_job(record, args.job)
        key = str(args.job)
        recovering = (args.command == "finish" and record["status"] == "reconciled" and
                      job["role"] == "reviewer")
        plan.require((record["status"] == "claimed" or recovering) and key in record["started"],
                     "Report requires an actually started job in a claimed batch, or finish "
                     "for an original reviewer in a reconciled batch")
        previous = record["submitted"].get(key)
        rejected = key in record.get("rejected", {})
        if previous and not rejected:
            try:
                snapshot = report_for(assignment, record, args.job, expected=previous, bind_reference=True)
            except HandoffError:
                raise
            except (ValueError, KeyError, TypeError) as error:
                if job["role"] != "review-owner" or "development_sha256" in previous:
                    raise
                failure = report_failure(record, args.job, error, settings, receipt=previous)
                persist(folder, state)
                raise failure from error
            if snapshot["receipt"] == previous:
                return {"valid": True, **previous}
            record.setdefault("submission_history", {}).setdefault(key, []).append(previous)
            record["submitted"][key] = snapshot["receipt"]
            persist(folder, state)
            return {"valid": True, **snapshot["receipt"]}
        recovery = args.command == "recover-report"
        if recovery:
            begin_report_recovery(record, args, settings)
            persist(folder, state)
        else:
            plan.require(record["failures"].get(key, 0) < correction_limit(settings),
                         "Report correction allowance exhausted; use check-report on the preserved candidate, "
                         "then recover-report with evidence and shutdown-evidence. Do not repeat worker effects.")
        path = review.safe_path(folder, str(Path(job["result_file"]).relative_to(folder)))
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if args.command in ("submit", "recover-report"):
                identity = write_candidate(assignment, record, args)
                if recovery:
                    record["report_recoveries"][key]["candidate_sha256"] = identity
            snapshot = report_for(assignment, record, args.job)
        except FileNotFoundError as error:
            if recovery:
                record["report_recoveries"][key].update(outcome="failed", error=str(error))
                persist(folder, state)
                raise HandoffError("missing_report", "Recovery candidate or report is absent; the recorded "
                                   "recovery remains consumed. Preserve the existing evidence.") from error
            raise HandoffError("missing_report", "Report or candidate is absent; inspect native activity and "
                               "retry finish/submit when the original file is available. No attempt consumed.") from error
        except (ValueError, KeyError, TypeError) as error:
            if recovery:
                record["report_recoveries"][key].update(outcome="failed", error=str(error))
                persist(folder, state)
                raise HandoffError("invalid_report", f"{error}. The one report recovery was consumed; "
                                   "preserve evidence without repeating external effects.") from error
            failure = report_failure(record, args.job, error, settings)
            persist(folder, state)
            raise failure from error
        if rejected and snapshot["receipt"] == previous:
            raise HandoffError("controller_rejected", record["rejected"][key]["error"] +
                               ". Correct the report, or retry collect after restoring the underlying evidence.")
        if previous:
            record.setdefault("submission_history", {}).setdefault(key, []).append(previous)
        record["submitted"][key] = snapshot["receipt"]
        if recovery:
            record["report_recoveries"][key].update(outcome="validated", receipt=snapshot["receipt"])
        record.get("rejected", {}).pop(key, None)
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
        reports.append(report_for(assignment, record, number, expected=receipt))
    return assignment, reports


def collect_review(state, record, assignment, reports):
    first = record["spec"]["jobs"][0]
    if first["role"] == "review-owner":
        owner = reports[0]["report"]
        if owner["outcome"] == "dispatch":
            reserve_requests(state, assignment, owner["requests"])
            return None
        return reports[0]["development"]
    checkpoint = copy.deepcopy(state["active"]["review_dispatch"])
    for job, report in zip(record["spec"]["jobs"], reports):
        checkpoint["reports"].append({
            "role": job["role"], "result_file": job["result_file"],
            "outcome": "complete" if report["report"]["outcome"] == "complete" else "blocked"})
    pending = state["active"].get("pending_requests", [])
    remaining = pending[len(reports):]
    if first["role"] == "fixer" or any(report["report"]["outcome"] != "complete" for report in reports):
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
        original = state
        state = copy.deepcopy(state)
        record = batch_record(state, args.batch)
        assignment = assignment_for(state, record, settings)
        with run.ExitStack() as guards:
            try:
                report = (collect_review(state, record, assignment, reports) if assignment["role"] == "review"
                          else reports[0]["report"])
                if report is not None:
                    guards.enter_context(run.complete(state, report, settings))
            except review.EvidenceUnavailable as error:
                raise HandoffError("state_unavailable", f"{error}. No report correction attempt consumed.") from error
            except (ValueError, KeyError, TypeError) as error:
                previous = batch_record(original, args.batch)
                if len(reports) != 1 or previous["spec"]["jobs"][0]["role"] in jobs.LEAVES:
                    raise
                failure = report_failure(previous, 1, error, settings, receipt=reports[0]["receipt"])
                persist(folder, original)
                raise failure from error
            record.pop("rejected", None)
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
        return descriptor(folder, state, record)


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
        result = descriptor(folder, state, record)
        state["outcome"], state["reason"] = "running", args.reason
        state.pop("stop_kind", None)
        persist(folder, state)
        return result


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="command", required=True)
    for name in ("prepare", "claim", "start", "finish", "submit", "check-report", "recover-report",
                 "collect", "restore-executor",
                 "repair-script", "resume-prepared", "release"):
        command = commands.add_parser(name)
        command.add_argument("store")
        if name in ("prepare", "claim"):
            command.add_argument("--launch-dir", help="Host-readable private directory for a verified "
                                 "launch copy of the generated script")
        if name == "prepare":
            command.add_argument("--models-file")
            command.add_argument("--configured-models", action="store_true")
        elif name == "restore-executor":
            command.add_argument("--source", required=True)
            command.add_argument("--shutdown-evidence", required=True)
        else:
            command.add_argument("--batch", required=True)
        if name in ("start", "finish", "submit", "check-report", "recover-report"):
            command.add_argument("--job", type=int, required=True)
        if name in ("submit", "check-report", "recover-report"):
            command.add_argument("--candidate", required=True)
        if name == "recover-report":
            command.add_argument("--evidence", required=True)
            command.add_argument("--shutdown-evidence", required=True)
        if name == "resume-prepared":
            command.add_argument("--reason", required=True)
        if name == "release":
            command.add_argument("--evidence", required=True,
                                 help="How the host refused the claimed script before starting it")
    return cli


def main():
    args = parser().parse_args()
    try:
        operations = {"prepare": prepare, "claim": claim, "start": start,
                      "submit": submit, "finish": submit, "collect": collect,
                      "check-report": check_report, "recover-report": submit,
                      "restore-executor": restore_executor, "repair-script": repair_script,
                      "resume-prepared": resume_prepared, "release": release}
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
