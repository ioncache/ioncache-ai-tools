"""Check incremental assessment handoffs without launching or waiting for workers."""

import argparse
import json
from pathlib import Path

import review_assignments as records


def candidate_keys(result):
    candidates = result["candidates"]
    records.require(isinstance(candidates, list) and all(isinstance(item, dict) for item in candidates),
                    "Candidates must be a list of objects")
    keys = [records.text(item.get("key"), "Candidate key") for item in candidates]
    records.strings(keys, "Candidate keys within a report")
    return set(keys)


def checked_assessment(record, attempt):
    records.require(isinstance(record, dict), "Report assessment must be an object")
    records.require(isinstance(attempt["result"], dict), "Assessment needs the original returned report")
    records.require(record.get("packet_identity") == attempt["packet"]["identity"] and
                    record.get("result_identity") == records.digest(attempt["result"]),
                    "Stale report assessment; assess the changed report, not another discovery pass")
    records.require(record.get("coverage") in ("complete", "incomplete"), "Missing assessed coverage")
    records.strings(record.get("evidence"), "Assessment evidence")
    records.require(bool(record["evidence"]), "Assessment requires evidence")
    assessments = record.get("assessments")
    records.require(isinstance(assessments, list), "Missing candidate assessments")
    records.require(all(isinstance(item, dict) for item in assessments),
                    "Candidate assessments must be objects")
    keys = records.strings([item.get("key") for item in assessments], "Assessed keys")
    records.require(set(keys) == candidate_keys(attempt["result"]), "Assessment omits or adds candidate keys")
    for item in assessments:
        records.require(item.get("validation") in ("valid", "invalid", "uncertain", "pending"),
                        "Invalid assessment validation")
        records.require(bool(records.strings(item.get("evidence"), "Candidate assessment evidence")),
                        "Each assessment needs evidence")
    return record["coverage"] == "complete" and all(
        item["validation"] != "pending" for item in assessments)


def observe_worker(record, workers, declared):
    records.require(isinstance(record, dict), "Assessment record must be an object")
    worker = record.get("worker")
    records.require("worker" in record and
                    (worker is None or isinstance(worker, str) and bool(worker.strip())),
                    "Assessment worker must be an observed identity or null")
    records.require(worker is None or worker not in workers, "Assessment reused a worker context")
    records.require(worker is None or worker in declared,
                    "Record the observed assessment worker as an adjudicator in other_workers")
    if worker is not None:
        workers.add(worker)


def progress(plan, handoff, state):
    records.verify_plan(plan)
    records.require(isinstance(handoff, dict) and set(handoff) ==
                    {"history_complete", "attempts", "active", "other_workers"}, "Invalid handoff fields")
    records.require(isinstance(state, dict) and set(state) == {"reports", "merge"},
                    "Adjudication state needs reports and merge")
    records.require(isinstance(state["reports"], list), "Reports must be a list")
    errors, diagnostics, workers = [], [], set()
    indexed, workers, _ = records.attempt_index(
        plan, handoff["attempts"], errors, records.isolation_assessments(handoff))
    declared = set()
    for other in handoff["other_workers"]:
        worker = other.get("worker")
        records.require(worker is None or isinstance(worker, str) and bool(worker.strip()),
                        "Invalid other-worker identity")
        if worker is not None:
            if other["role"] == "adjudicator":
                declared.add(worker)
            else:
                workers.add(worker)
    missing = records.active_coverage(plan, handoff["active"], indexed, errors, diagnostics)
    active = {key for keys in handoff["active"].values() for key in keys}
    selected = {key: attempt for key, attempt in indexed.items() if key in active}
    complete = {}
    for record in state["reports"]:
        try:
            key = record["attempt"]
            records.require(key in selected, "Assessment must name a current active attempt")
            observe_worker(record, workers, declared)
            attempt = indexed[key]
            ready = checked_assessment(record, attempt)
            records.require(key not in complete, "Duplicate active report assessment")
            complete[key] = (ready, records.digest(record))
        except (KeyError, TypeError, ValueError) as error:
            errors.append(str(error))
    ready = [key for key, attempt in selected.items()
             if isinstance(attempt["result"], dict) and not attempt["result_error"] and key not in complete]
    enabled = records.enabled_categories(plan["request"], plan["registry"])
    unresolved = [key for key in enabled if plan["technical_applicability"][key]["status"] == "unknown"]
    merge_ready = (not errors and not missing and not unresolved and handoff["history_complete"] is True and
                   set(complete) == active and all(item[0] for item in complete.values()))
    merged = False
    if state["merge"] is not None:
        try:
            merge = state["merge"]
            observe_worker(merge, workers, declared)
            records.require(merge_ready, "Merge cannot complete before required report assessments")
            records.require(merge.get("snapshot") == plan["request"]["snapshot"] and
                            merge.get("plan_identity") == plan["identity"], "Merge targets another phase")
            identities = records.strings(merge.get("report_identities"), "Merged report identities")
            records.require(set(identities) == {item[1] for item in complete.values()},
                            "Merge must consume the current assessments exactly once")
            records.require(bool(records.strings(merge.get("evidence"), "Merge evidence")),
                            "Merge needs evidence")
            records.require(merge.get("outcome") in ("complete", "incomplete"), "Invalid merge outcome")
            merged = merge["outcome"] == "complete"
        except (KeyError, TypeError, ValueError) as error:
            errors.append(str(error))
    return {"ready": ready, "merge_ready": merge_ready, "complete": merged and not errors,
            "errors": errors, "limitations": diagnostics,
            "evidence_limit": "Record checks cannot prove semantic assessment or native overlap."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("handoff", type=Path)
    parser.add_argument("adjudication", type=Path)
    args = parser.parse_args()
    try:
        result = progress(*(json.loads(path.read_text()) for path in
                            (args.plan, args.handoff, args.adjudication)))
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, KeyError, TypeError, ValueError) as error:
        parser.exit(2, f"review-progress: {error}; retain reports and repair the handoff\n")


if __name__ == "__main__":
    raise SystemExit(main())
