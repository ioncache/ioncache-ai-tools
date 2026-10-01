"""Validated review-loop transitions, replayed from the durable ledger.

The coordinator supplies evidence and judgments; this module checks bookkeeping,
not their truth. Failed or partial reviews cannot advance the loop. Every event
requires an actor and reason, and replay rejects unsupported or invalid history.
"""

import copy


class LedgerError(ValueError):
    """An invalid request or inconsistent ledger; callers must stop and report it."""


def require(condition, message):
    if not condition:
        raise LedgerError(message)


def text(value):
    require(isinstance(value, str) and bool(value.strip()), "Expected non-empty text")
    return value


def strings(value):
    require(isinstance(value, list) and bool(value), "Expected a non-empty text list")
    for item in value:
        text(item)
    return value


def positive(value):
    """Reject booleans as limits even though Python treats them as integers."""
    require(type(value) is int and value > 0, "Limits must be positive integers")
    return value


def fields(value, names):
    """Require an exact field set so misspelled or unsupported inputs cannot be ignored."""
    require(isinstance(value, dict) and set(value) == set(names.split()),
            f"Expected fields: {names}")


def phase(state, *allowed):
    require(state["phase"] in allowed, f"Operation not allowed in {state['phase']}")


def current_loop(state):
    """Return the mutable latest loop; phases without a started review must fail."""
    require(bool(state["loops"]), "No review has started")
    return state["loops"][-1]


def current_cycle(state):
    """Return the mutable latest cycle without silently creating or consuming one."""
    loop = current_loop(state)
    require(bool(loop["cycles"]), "No fixing cycle has started")
    return loop["cycles"][-1]


def actionable(finding):
    """Keep uncertainty and unverified fixes open unless explicitly disposed of."""
    return finding["validation"] != "invalid" and finding["disposition"] in {
        "open", "fix_applied", "fix_failed",
    }


def unresolved(state):
    """Return IDs that still block progress, including pending and uncertain findings."""
    return [key for key, value in state["findings"].items() if actionable(value)]


def evidence(event):
    strings(event["evidence"])


def checks_valid(checks):
    """Require explicit check evidence while preserving failed or unavailable results."""
    require(isinstance(checks, list) and bool(checks), "Verification must be recorded")
    for check in checks:
        fields(check, "name result evidence")
        text(check["name"])
        text(check["evidence"])
        require(check["result"] in ("passed", "failed", "unavailable", "not_applicable"),
                "Invalid verification result")


def checks_pass(checks):
    """Accept only passed or justified inapplicable checks after structural validation."""
    return all(item["result"] in ("passed", "not_applicable") for item in checks)


def review_valid(event):
    """Reject partial passes; worker completion alone is not review coverage."""
    passes = event["passes"]
    require(isinstance(passes, list) and bool(passes), "Review coverage is required")
    for item in passes:
        fields(item, "name worker result evidence")
        for key in ("name", "worker", "evidence"):
            text(item[key])
        require(item["result"] == "complete", "Partial or failed review cannot advance")


def start_review(state, event):
    """Consume outer capacity before review work so interruption cannot refund it."""
    phase(state, "ready_review")
    require(len(state["loops"]) < state["limits"]["outer"], "Outer limit reached")
    state["loops"].append({"number": len(state["loops"]) + 1,
                           "snapshot": event["snapshot"], "cycles": [], "complete": False})
    state["phase"] = "reviewing"


def review_done(state, event):
    """Preserve completed review evidence for validation, without accepting findings."""
    phase(state, "reviewing")
    review_valid(event)
    checks_valid(event["checks"])
    loop = current_loop(state)
    loop["review"] = copy.deepcopy(event)
    state["phase"] = "validating"


def finding(state, event):
    """Retain repeated observations without reopening an existing disposition.

    A new behavior key receives a stable run-scoped ID and pending validation.
    Reopening an existing key requires a separate, evidenced decision.
    """
    phase(state, "reviewing", "validating", "reviewing_fixes", "validating_fixes")
    for key in ("key", "summary"):
        text(event[key])
    strings(event["locations"])
    evidence(event)
    require(event["severity"] in ("High", "Medium", "Low"), "Invalid severity")
    existing = next((item for item in state["findings"].values()
                     if item["key"] == event["key"]), None)
    if existing is not None:
        existing["observations"].append(copy.deepcopy(event))
        return
    key = f"F{len(state['findings']) + 1:03}"
    state["findings"][key] = {
        "id": key, "key": event["key"], "summary": event["summary"],
        "severity": event["severity"], "locations": event["locations"],
        "validation": "pending", "disposition": "open",
        "observations": [copy.deepcopy(event)], "decisions": [],
    }


def decision(state, event):
    """Record judgment history while keeping validity distinct from disposition.

    Verified resolution requires an applied fix in the current reviewed cycle
    and passing checks. The coordinator remains responsible for evidence truth.
    """
    phase(state, "validating", "validating_fixes")
    require(event["id"] in state["findings"], "Unknown finding")
    evidence(event)
    item = state["findings"][event["id"]]
    valid, disposition = event["validation"], event["disposition"]
    require(valid in ("valid", "invalid", "uncertain"), "Invalid validation")
    require(disposition in ("open", "ignored", "out_of_scope", "fixed", "fix_failed"),
            "Invalid disposition")
    require(event["severity"] in ("High", "Medium", "Low"), "Invalid severity")
    if disposition in ("fixed", "fix_failed"):
        phase(state, "validating_fixes")
        cycle = current_cycle(state)
        require(event["id"] in cycle["findings"], "Finding not part of this fix cycle")
        require(valid == "valid", "Fix outcomes require a valid finding")
        if disposition == "fixed":
            require(item["disposition"] == "fix_applied", "No applied fix to verify")
            require(checks_pass(cycle["result"]["checks"]), "Fix checks did not pass")
    item["decisions"].append({"previous": {key: item[key] for key in
                                         ("validation", "disposition", "severity")},
                              **copy.deepcopy(event)})
    item.update(validation=valid, disposition=disposition, severity=event["severity"])


def start_fix(state, event):
    """Consume inner capacity for a declared batch of validated actionable findings.

    The previous focused review must be advanced before another batch starts.
    Pending validation and unreviewed applied fixes cannot be bypassed.
    """
    phase(state, "validating", "validating_fixes")
    loop = current_loop(state)
    if state["phase"] == "validating_fixes":
        require(current_cycle(state)["complete"], "Advance the reviewed cycle before another fix")
    require(len(loop["cycles"]) < state["limits"]["inner"], "Inner limit reached; stop run")
    ids = strings(event["findings"])
    strings(event["files"])
    require(len(set(ids)) == len(ids), "Duplicate fix IDs")
    require(not any(item["validation"] == "pending" for item in state["findings"].values()),
            "Validate all findings before fixing")
    for key in ids:
        require(key in state["findings"], "Unknown finding")
        item = state["findings"][key]
        require(item["validation"] == "valid" and actionable(item), "Finding not fixable")
        require(item["disposition"] != "fix_applied", "Review the applied fix first")
    loop["cycles"].append({"number": len(loop["cycles"]) + 1,
                           "findings": ids, "files": event["files"],
                           "before": event["snapshot"], "complete": False})
    state["phase"] = "fixing"


def fix_done(state, event):
    """Record every attempted outcome as unverified until focused review completes."""
    phase(state, "fixing")
    cycle = current_cycle(state)
    results = event["results"]
    require(isinstance(results, dict) and set(results) == set(cycle["findings"]),
            "Record a result for every attempted finding")
    checks_valid(event["checks"])
    for key, result in results.items():
        fields(result, "result evidence")
        text(result["evidence"])
        require(result["result"] in ("applied", "failed"), "Invalid fix result")
        state["findings"][key]["disposition"] = (
            "fix_applied" if result["result"] == "applied" else "fix_failed")
    cycle["result"] = copy.deepcopy(event)
    cycle["after"] = event["snapshot"]
    state["phase"] = "reviewing_fixes"


def fixes_reviewed(state, event):
    """Require completed focused passes before validating correction outcomes."""
    phase(state, "reviewing_fixes")
    review_valid(event)
    current_cycle(state)["review"] = copy.deepcopy(event)
    state["phase"] = "validating_fixes"


def finish(state, outcome, reason):
    """Record an outcome without discarding the phase or consumed allowances."""
    state["outcome"] = outcome
    state["stop_reason"] = reason


def advance(state, event):
    """Choose inner retry, outer confirmation, or termination from validated evidence.

    Inner exhaustion stops the whole run. Even a clean focused review needs
    another full review before completion; accepted risks remain exceptions.
    """
    phase(state, "validating", "validating_fixes")
    require(not any(item["validation"] == "pending" for item in state["findings"].values()),
            "Pending validation prevents advancing")
    loop = current_loop(state)
    if state["phase"] == "validating_fixes":
        cycle = current_cycle(state)
        cycle["complete"] = True
        if unresolved(state):
            require(not any(item["disposition"] == "fix_applied"
                            for item in state["findings"].values()),
                    "Resolve applied fix outcomes before advancing")
            if len(loop["cycles"]) >= state["limits"]["inner"]:
                finish(state, "limit_reached", "Inner limit reached with unresolved findings")
            return
        require(checks_pass(cycle["result"]["checks"]), "Required fix verification incomplete")
        loop["complete"] = True
        if len(state["loops"]) >= state["limits"]["outer"]:
            finish(state, "limit_reached", "Final full-scope confirmation needs another outer loop")
        else:
            state["phase"] = "ready_review"
        return
    require(not unresolved(state), "Findings need fixing or explicit disposition")
    require(checks_pass(loop["review"]["checks"]), "Required review verification incomplete")
    loop["complete"] = True
    exceptions = any(item["validation"] in ("valid", "uncertain") and
                     item["disposition"] in ("ignored", "out_of_scope")
                     for item in state["findings"].values())
    finish(state, "completed_with_exceptions" if exceptions else "completed", event["reason"])


def stop(state, event):
    """Allow explicit incomplete outcomes, never shortcut completion or limit checks."""
    require(event["outcome"] in ("blocked", "interrupted", "failed", "stalled"),
            "Use advance for completion and limits")
    finish(state, event["outcome"], event["reason"])


def resume(state, event):
    """Reopen only blocked or interrupted work without refunding consumed capacity."""
    require(state["outcome"] in ("blocked", "interrupted"), "Run is not resumable")
    state["outcome"] = "running"
    state["stop_reason"] = None


def reconcile(state, event):
    """Invalidate old evidence after external edits without refunding loop counts."""
    require(state["phase"] != "fixing", "Reconcile an interrupted fix through fix_done or stop")
    evidence(event)
    state["outcome"] = "running"
    state["stop_reason"] = None
    if state["loops"]:
        current_loop(state)["invalidated"] = True
    for item in state["findings"].values():
        item["validation"] = "pending"
        item["disposition"] = "open"
    if len(state["loops"]) >= state["limits"]["outer"]:
        finish(state, "limit_reached", "External changes require another full review")
    else:
        state["phase"] = "ready_review"


EVENTS = {
    "start_review": (start_review, ""),
    "review_done": (review_done, "passes checks"),
    "finding": (finding, "key summary locations severity evidence"),
    "decision": (decision, "id validation disposition severity evidence"),
    "start_fix": (start_fix, "findings files"),
    "fix_done": (fix_done, "results checks"),
    "fixes_reviewed": (fixes_reviewed, "passes"),
    "advance": (advance, ""),
    "stop": (stop, "outcome"),
    "resume": (resume, ""),
    "reconcile": (reconcile, "evidence"),
}


def apply_event(state, event):
    """Apply a fully recorded event to derived state, or raise LedgerError.

    Stop and resume preserve the prior evidence snapshot to prevent stale
    reviews from becoming current. Discard derived state if a handler fails;
    handlers may mutate it before rejecting an event.
    """
    require(isinstance(event, dict), "Event must be an object")
    kind = event.get("type")
    require(isinstance(kind, str) and kind in EVENTS, "Unknown event type")
    handler, extra = EVENTS[kind]
    fields(event, f"type actor reason snapshot sequence time {extra}")
    text(event["actor"])
    text(event["reason"])
    require(event["sequence"] == state["revision"] + 1, "Event sequence mismatch")
    text(event["time"])
    if kind == "reconcile":
        require(state["outcome"] in ("running", "interrupted", "blocked"),
                "Finished run cannot be reconciled")
    elif kind != "resume":
        require(state["outcome"] == "running", "Run has stopped")
    handler(state, event)
    if kind not in ("stop", "resume"):
        state["snapshot"] = event["snapshot"]
    state["revision"] += 1


def replay(ledger, snapshot_check=None):
    """Derive current findings, loop counters and outcome from validated history.

    The optional callback checks each snapshot transition before its event
    mutates state. File-backed callers supply it to validate saved evidence.
    """
    fields(ledger, "schema run_id root objective scope base limits initial snapshots events")
    require(type(ledger["schema"]) is int and ledger["schema"] == 1,
            "Unsupported ledger schema")
    for key in ("run_id", "root", "objective", "scope", "base", "initial"):
        text(ledger[key])
    fields(ledger["limits"], "outer inner")
    for value in ledger["limits"].values():
        positive(value)
    require(isinstance(ledger["events"], list), "Invalid event history")
    state = {"revision": 0, "phase": "ready_review", "outcome": "running",
             "stop_reason": None, "snapshot": ledger["initial"], "loops": [],
             "findings": {}, "limits": ledger["limits"]}
    require(isinstance(ledger["snapshots"], dict), "Invalid snapshots")
    require(ledger["initial"] in ledger["snapshots"], "Missing initial snapshot")
    for event in ledger["events"]:
        require(isinstance(event, dict) and event.get("snapshot") in ledger["snapshots"],
                "Missing event snapshot")
        if snapshot_check:
            snapshot_check(ledger, state, event)
        apply_event(state, event)
    return state
