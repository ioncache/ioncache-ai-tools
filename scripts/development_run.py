#!/usr/bin/env python3
"""Private, bounded development-run bookkeeping. Does not launch models or publish.

The caller executes returned assignments using its native host. Native permissions
remain authoritative. JSON results use stdout; errors use stderr and exit 2.
"""

import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace
import sys
import tempfile
from uuid import uuid4

import development_manifest as plan
import review_ledger as review

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks" / "scripts"))
from plugin_config import feature_settings


def git(root, *args):
    try:
        return review.git(root, list(args)).decode().strip()
    except review.LedgerError as error:
        raise plan.ManifestError(f"Git check failed ({' '.join(args[:3])}): {error}") from error


def feature(root):
    settings = feature_settings({"cwd": str(root)})
    features = {"autonomous-development", "skill:autonomous-development"}
    plan.require(features <= settings.catalog and not features.intersection(settings.disabled),
                 "Autonomous development is disabled; continue without this workflow. "
                 "Status and interruption commands remain available.")


def common_directory(root):
    return (root / git(root, "rev-parse", "--git-common-dir")).resolve()


def save(folder, state):
    review.atomic_write(folder / "RUN.json", plan.encode(state))


def load(folder):
    state = json.loads((folder / "RUN.json").read_bytes())
    plan.require(state["schema"] == 1 and state["store"] == str(folder), "Invalid run storage")
    validated = plan.validate(state["manifest"], folder / "inputs")
    plan.require(validated["identity"] == state["approval"], "Approved manifest changed")
    plan.require(json.loads((folder / "MANIFEST.json").read_bytes()) == state["manifest"],
                 "Shared approved manifest changed")
    return state


@contextmanager
def locked(folder):
    plan.require(folder.is_dir() and not folder.is_symlink(), "Run directory is unavailable")
    with (folder / ".lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def initialize(args):
    source = Path(args.manifest).resolve()
    validated = plan.read(source)
    manifest = validated["manifest"]
    plan.require(args.approved == validated["identity"], "Approval must identify this exact manifest")
    root = Path(args.root).resolve()
    plan.require(Path(git(root, "rev-parse", "--show-toplevel")).resolve() == root,
                 "Use the repository worktree root")
    feature(root)
    repository = manifest["repository"]
    plan.require(git(root, "remote", "get-url", repository["remote"]) == repository["url"],
                 "Repository remote does not match the approved manifest")
    for item in manifest["prs"]:
        git(root, "check-ref-format", "--branch", item["branch"])
        git(root, "check-ref-format", "--branch", item["target"])
        git(root, "rev-parse", "--verify", item["base"] + "^{commit}")
        target = (root / item["worktree"]).resolve()
        plan.require(target.is_relative_to(root) and target != root, "Worktree escapes the repository")
        plan.require(not target.exists(), f"Worktree already exists: {target}")
        plan.require(not git(root, "branch", "--list", item["branch"]), "Owned branch already exists")
    plan.require(not Path(args.store).is_symlink(), "Store cannot be a symlink")
    folder = Path(args.store).resolve()
    plan.require(not folder.exists() and not folder.is_symlink(), "Store already exists; inspect and resume it")
    plan.require(not folder.resolve().is_relative_to(root), "Keep run evidence outside the repository")
    folder.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".initializing-development-", dir=folder.parent))
    try:
        for item in manifest["artifacts"]:
            target = temporary / "inputs" / item["snapshot"]
            target.parent.mkdir(parents=True, exist_ok=True)
            review.atomic_write(target, (source.parent / item["snapshot"]).read_bytes())
        plan.validate(manifest, temporary / "inputs")
        review.atomic_write(temporary / "MANIFEST.json", plan.encode(manifest))
        state = {"schema": 1, "id": uuid4().hex, "store": str(folder), "root": str(root),
                 "manifest": manifest, "approval": args.approved, "revision": 0,
                 "outcome": "running", "preflight": False, "active": None, "attempts": {},
                 "history": [], "prs": {item["id"]: {"position": 0, "waiting": False,
                                                    "accepted": None, "url": None}
                                       for item in manifest["prs"]}}
        (temporary / "reports").mkdir(mode=0o700)
        save(temporary, state)
        os.rename(temporary, folder)
        review.sync_directory(folder.parent)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return state


def steps(manifest, pr_id):
    task_map = plan.indexed(manifest["tasks"])
    result = [("prepare", None)]
    for key in plan.dependency_order(task_map):
        if task_map[key]["pr"] == pr_id:
            result.extend((role, key) for role in ("implement", "review", "commit"))
    result.extend((role, None) for role in ("draft", "review", "commit"))
    if manifest["permissions"]["screenshots"]:
        result.append(("evidence", None))
    result.append(("ready", None))
    return result


def current_target(state):
    if not state["preflight"]:
        return None, "preflight", None
    prs = plan.indexed(state["manifest"]["prs"])
    for key in plan.dependency_order(prs):
        progress = state["prs"][key]
        sequence = steps(state["manifest"], key)
        if progress["waiting"] or progress["position"] == len(sequence):
            continue
        if any(state["prs"][dep]["position"] != len(steps(state["manifest"], dep))
               for dep in prs[key]["dependencies"]):
            continue
        role, task = sequence[progress["position"]]
        return key, role, task
    return None


def roots(state, pr_id):
    root = Path(state["root"])
    if pr_id is None:
        return root
    pr = plan.indexed(state["manifest"]["prs"])[pr_id]
    target = (root / pr["worktree"]).resolve()
    plan.require(target.is_relative_to(root) and target != root, "Worktree path changed")
    return target


def unchanged(before, after):
    plan.require(before == after, "Worktree drift invalidates this assignment; preserve work and reconcile")


def capture(root):
    return review.fingerprint(None, root)["manifest"]


def check_worktree(state, pr_id):
    root = roots(state, pr_id)
    pr = plan.indexed(state["manifest"]["prs"])[pr_id]
    plan.require(common_directory(root) == common_directory(Path(state["root"])),
                 "Prepared worktree belongs to another repository")
    plan.require(git(root, "branch", "--show-current") == pr["branch"], "Unexpected worktree branch")
    return root


def permission(manifest, role):
    required = {"preflight": ["commit", "push", "create_pr", "mark_ready"],
                "commit": ["commit"], "draft": ["push", "create_pr"],
                "ready": ["push", "mark_ready"], "evidence": ["screenshots"]}
    for key in required.get(role, []):
        plan.require(manifest["permissions"][key], f"{key} was not approved for this run")


def reserve(state):
    feature(Path(state["root"]))
    plan.require(state["outcome"] == "running", "Run is stopped; inspect it before resuming")
    plan.require(state["active"] is None, "An assignment is outstanding; collect or reconcile it first")
    target = current_target(state)
    if target is None:
        waiting = any(item["waiting"] for item in state["prs"].values())
        state["outcome"] = "waiting" if waiting else "completed"
        return
    pr_id, role, task_id = target
    key = f"{pr_id or 'run'}:{role}:{task_id or 'pr'}"
    limits = state["manifest"]["limits"]
    if len(state["history"]) >= limits["assignments"] or state["attempts"].get(key, 0) >= limits["attempts"]:
        state["outcome"] = "failed"
        state["reason"] = f"Assignment allowance exhausted: {key}; retained work is not complete"
        return
    permission(state["manifest"], role)
    root = (roots(state, pr_id) if role in ("preflight", "prepare")
            else check_worktree(state, pr_id))
    before = None if role in ("preflight", "prepare") else capture(root)
    if role in ("commit", "ready", "evidence"):
        accepted = state["prs"][pr_id]["accepted"]
        plan.require(accepted is not None, "A completed review is required")
        plan.require(before["files"] == accepted["files"], "Reviewed content changed")
        unchanged(accepted, before)
    if role == "implement":
        state["prs"][pr_id].setdefault("task_bases", {}).setdefault(task_id, before["head"])
    state["attempts"][key] = state["attempts"].get(key, 0) + 1
    assignment = {"id": f"A{len(state['history']) + 1:04d}", "key": key, "role": role,
                  "pr": pr_id, "task": task_id, "root": str(root), "before": before,
                  "attempt": state["attempts"][key], "worker": None, "outcome": "reserved"}
    state["active"] = assignment
    state["history"].append(assignment)


def scope_paths(state, assignment):
    tasks = state["manifest"]["tasks"]
    if assignment["task"]:
        tasks = [item for item in tasks if item["id"] == assignment["task"]]
    else:
        tasks = [item for item in tasks if item["pr"] == assignment["pr"]]
    return {path for task in tasks for path in task["paths"]}


def within_scope(state, assignment, after):
    before = assignment["before"]
    plan.require(before["head"] == after["head"] and before["index"] == after["index"],
                 "Implementation and review must not change HEAD or staging")
    permitted = scope_paths(state, assignment)
    for name in review.changed(before, after):
        plan.require(any(path == "." or name == path or name.startswith(path + "/") for path in permitted),
                     f"Change outside the approved scope: {name}")


def prepare_result(state, assignment, data):
    root = check_worktree(state, assignment["pr"])
    pr = plan.indexed(state["manifest"]["prs"])[assignment["pr"]]
    observed = git(root, "rev-parse", "HEAD")
    git(root, "merge-base", "--is-ancestor", pr["base"], observed)
    plan.require(data["base"] == observed, "Preparation must report the actual base")
    plan.strings(data["merged_dependencies"], empty=True)
    plan.require(set(data["merged_dependencies"]) == set(pr["dependencies"]),
                 "Every prerequisite PR must be observed merged before preparation")
    state["prs"][pr["id"]]["base"] = observed


def review_result(state, assignment, data):
    root = Path(assignment["root"])
    report = review.status(SimpleNamespace(ledger=data["ledger"]), root)
    plan.require(report["outcome"] in ("completed", "completed_with_exceptions") and not report["drift"],
                 "Review is incomplete or stale")
    progress = state["prs"][assignment["pr"]]
    base = progress["task_bases"][assignment["task"]] if assignment["task"] else progress["base"]
    plan.require(report["base"] == base, "Review comparison base does not match its assignment")
    manifest = state["manifest"]
    target = (plan.indexed(manifest["tasks"])[assignment["task"]] if assignment["task"]
              else plan.indexed(manifest["prs"])[assignment["pr"]])
    observed = {item["name"]: item for item in report["loops"][-1]["review"]["checks"]}
    plan.require(all(item["name"] in observed and observed[item["name"]]["result"] == "passed"
                     for item in target["checks"]), "Required acceptance checks did not all pass")
    plan.require(report["limits"] == {"outer": manifest["limits"]["review_loops"],
                                      "inner": manifest["limits"]["fix_cycles"]},
                 "Review allowances differ from the approved limits")
    after = capture(root)
    plan.require(review.digest(review.encode(after)) == report["snapshot"],
                 "Code changed after the completed review snapshot")
    within_scope(state, assignment, after)
    progress["accepted"] = after
    progress["review"] = report


def commit_result(state, assignment, data):
    root = Path(assignment["root"])
    before = assignment["before"]
    after = capture(root)
    unchanged(before["files"], after["files"])
    plan.require(data["commit"] == after["head"], "Commit receipt does not match HEAD")
    if after["head"] != before["head"]:
        parents = git(root, "rev-list", "--parents", "-n", "1", "HEAD").split()
        plan.require(parents == [after["head"], before["head"]], "Commit must extend the accepted HEAD")
    git(root, "diff", "--exit-code")
    git(root, "diff", "--cached", "--exit-code")
    for name in state["prs"][assignment["pr"]].get("changed", []):
        if name in after["files"]:
            git(root, "ls-files", "--error-unmatch", "--", name)
    progress = state["prs"][assignment["pr"]]
    progress["accepted"] = after
    progress["commit"] = after["head"]


def delivery_result(state, assignment, data):
    progress = state["prs"][assignment["pr"]]
    after = capture(Path(assignment["root"]))
    unchanged(assignment["before"], after)
    plan.require(data["commit"] == after["head"], "Publication receipt is stale")
    plan.text(data["url"])
    plan.text(data["evidence"])
    expected = "draft" if assignment["role"] == "draft" else "ready"
    plan.require(data["state"] == expected, "PR state does not match the assignment")
    if progress["url"]:
        plan.require(progress["url"] == data["url"], "Publication cannot replace the owned PR")
    progress["url"] = data["url"]


def complete(state, report):
    plan.fields(report, "assignment worker outcome summary evidence artifacts data")
    active = state["active"]
    plan.require(active is not None and report["assignment"] == active["id"], "Unexpected assignment result")
    plan.text(report["worker"])
    plan.text(report["summary"])
    plan.strings(report["evidence"])
    expected = {item["id"]: item["sha256"] for item in state["manifest"]["artifacts"]}
    plan.require(report["artifacts"] == expected, "Approved artifact identity or freshness is missing")
    plan.require(report["outcome"] in ("complete", "blocked", "waiting"), "Unknown worker outcome")
    plan.require(isinstance(report["data"], dict), "Result data must be an object")
    if report["outcome"] == "complete":
        complete_role(state, active, report["data"])
        if active["pr"]:
            state["prs"][active["pr"]]["position"] += 1
        else:
            state["preflight"] = True
    elif report["outcome"] == "waiting" and active["role"] == "prepare":
        state["prs"][active["pr"]]["waiting"] = True
    else:
        state["outcome"] = "blocked"
    active.update(worker=report["worker"], outcome=report["outcome"], report=report)
    state["history"][-1] = active
    state["active"] = None


def complete_role(state, assignment, data):
    role = assignment["role"]
    if assignment["pr"] and role != "prepare":
        check_worktree(state, assignment["pr"])
    if role == "preflight":
        required = ("artifact_access", "native_permissions", "fresh_workers",
                    "independent_review", "result_delivery", "cancellation")
        plan.require(all(data.get(key) is True for key in required), "Required execution capability is unverified")
    elif role == "prepare":
        prepare_result(state, assignment, data)
    elif role == "implement":
        after = capture(Path(assignment["root"]))
        within_scope(state, assignment, after)
        state["prs"][assignment["pr"]]["changed"] = review.changed(assignment["before"], after)
    elif role == "review":
        review_result(state, assignment, data)
        progress = state["prs"][assignment["pr"]]
        progress["changed"] = sorted(set(progress.get("changed", [])) |
                                     set(review.changed(assignment["before"], progress["accepted"])))
    elif role == "commit":
        commit_result(state, assignment, data)
    elif role in ("draft", "ready"):
        delivery_result(state, assignment, data)
    else:
        plan.require(role == "evidence", "Unsupported assignment role")
        unchanged(assignment["before"], capture(Path(assignment["root"])))
        plan.require(data["commit"] == assignment["before"]["head"], "UI evidence is for a different revision")
        plan.strings(data["artifacts"])
        state["prs"][assignment["pr"]]["evidence"] = data


def request(state):
    assignment = state["active"]
    if assignment is None:
        return None
    manifest = state["manifest"]
    before = assignment["before"]
    before_identity = None if before is None else {
        "head": before["head"], "index": before["index"], "snapshot": plan.digest(plan.encode(before)),
    }
    progress = state["prs"].get(assignment["pr"], {})
    comparison = (progress.get("task_bases", {}).get(assignment["task"]) if assignment["task"]
                  else progress.get("base"))
    return {**assignment, "before": before_identity, "comparison_base": comparison,
            "store": state["store"], "approval": state["approval"],
            "manifest_file": str(Path(state["store"]) / "MANIFEST.json"),
            "objective": manifest["objective"], "configuration": manifest["configuration"],
            "repository": manifest["repository"], "constraints": manifest["constraints"],
            "limits": manifest["limits"], "permissions": manifest["permissions"],
            "artifacts": [{**item, "snapshot": str(Path(state["store"]) / "inputs" / item["snapshot"])}
                          for item in manifest["artifacts"]],
            "pr_plan": plan.indexed(manifest["prs"]).get(assignment["pr"]),
            "task_plan": plan.indexed(manifest["tasks"]).get(assignment["task"]),
            "dependencies": {
                key: progress_summary(state["prs"][key])
                for key in (plan.indexed(manifest["prs"])[assignment["pr"]]["dependencies"]
                            if assignment["pr"] else [])
            },
            "progress": progress_summary(state["prs"][assignment["pr"]]) if assignment["pr"] else None,
            "result_file": str(Path(state["store"]) / "reports" / (assignment["id"] + ".json"))}


def progress_summary(progress):
    result = {key: value for key, value in progress.items() if key not in ("accepted", "review", "changed")}
    reviewed = progress.get("review")
    if reviewed:
        result["review"] = {"ledger": reviewed["ledger"], "outcome": reviewed["outcome"],
                            "snapshot": reviewed["snapshot"]}
    return result


def summary(state):
    return {"run": state["id"], "store": state["store"], "revision": state["revision"],
            "outcome": state["outcome"], "reason": state.get("reason"),
            "consumed_assignments": len(state["history"]), "limits": state["manifest"]["limits"],
            "prs": {key: progress_summary(value) for key, value in state["prs"].items()},
            "assignment": request(state),
            "usage": "Model tokens, cost, and native retries are not measured by this ledger"}


def reconcile(state, args):
    feature(Path(state["root"]))
    plan.require(state["outcome"] in ("running", "blocked", "waiting") and state["active"] is None,
                 "Collect or retire the outstanding worker before reconciling an unfinished run")
    plan.text(args.reason)
    plan.require(args.pr in state["prs"], "Unknown PR")
    progress = state["prs"][args.pr]
    sequence = steps(state["manifest"], args.pr)
    plan.require(progress["position"] < len(sequence), "Cannot reopen an already delivered PR")
    reviews = [(index, task) for index, (role, task) in enumerate(sequence)
               if role == "review" and index <= progress["position"]]
    plan.require(bool(reviews) and progress["accepted"] is not None,
                 "No accepted review to reconcile; resume the unfinished assignment instead")
    index, task = reviews[-1]
    after = capture(check_worktree(state, args.pr))
    permitted = scope_paths(state, {"pr": args.pr, "task": task})
    for name in review.changed(progress["accepted"], after):
        plan.require(any(path == "." or name == path or name.startswith(path + "/") for path in permitted),
                     f"Drift outside the approved scope requires an explicit scope decision: {name}")
    progress.update(position=index, accepted=None, waiting=False, reconciliation=args.reason)
    state["outcome"] = "running"


def mutate(args, folder):
    with locked(folder):
        state = load(folder)
        report = json.loads(Path(args.report).read_bytes()) if args.command == "record" else None
        if report is not None and any(item.get("report") == report for item in state["history"]):
            return summary(state)
        plan.require(args.revision == state["revision"], "Stale revision; inspect status before retrying")
        if args.command == "next":
            reserve(state)
        elif args.command == "record":
            feature(Path(state["root"]))
            complete(state, report)
        elif args.command == "interrupt":
            plan.text(args.reason)
            state["outcome"], state["reason"] = "blocked", args.reason
        elif args.command == "resume":
            feature(Path(state["root"]))
            plan.require(state["outcome"] in ("blocked", "waiting"), "Run cannot resume from this outcome")
            plan.require(state["active"] is None, "Collect the outstanding result or retire it after native worker shutdown")
            plan.text(args.reason)
            state["outcome"], state["reason"] = "running", args.reason
            for progress in state["prs"].values():
                progress["waiting"] = False
        elif args.command == "retire":
            plan.require(state["active"] is not None, "No outstanding assignment")
            plan.text(args.reason)
            plan.text(args.shutdown_evidence)
            state["active"].update(outcome="retired", reason=args.reason,
                                   shutdown_evidence=args.shutdown_evidence)
            state["history"][-1] = state["active"]
            state["active"] = None
            state["outcome"] = "blocked"
        elif args.command == "reconcile":
            reconcile(state, args)
        state["revision"] += 1
        save(folder, state)
        return summary(state)


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("manifest")
    initialize = commands.add_parser("init")
    initialize.add_argument("manifest")
    for name in ("approved", "root", "store"):
        initialize.add_argument("--" + name, required=True)
    for name in ("status", "next", "record", "interrupt", "resume", "retire", "reconcile"):
        command = commands.add_parser(name)
        command.add_argument("store")
        if name != "status":
            command.add_argument("--revision", type=int, required=True)
        if name == "record":
            command.add_argument("--report", required=True)
        if name in ("interrupt", "resume", "retire", "reconcile"):
            command.add_argument("--reason", required=True)
        if name == "retire":
            command.add_argument("--shutdown-evidence", required=True)
        if name == "reconcile":
            command.add_argument("--pr", required=True)
    return cli


def main():
    args = parser().parse_args()
    try:
        if args.command == "validate":
            result = plan.read(args.manifest)
        elif args.command == "init":
            result = summary(initialize(args))
        else:
            folder = Path(args.store).resolve()
            result = summary(load(folder)) if args.command == "status" else mutate(args, folder)
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"development-run: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
