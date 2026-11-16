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
import time
from uuid import uuid4

import development_manifest as plan
import development_audit as audit
import development_progress as monitoring
import development_models as models
import review_assignments as assignments
import review_ledger as review

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks" / "scripts"))
from plugin_config import feature_settings


def git(root, *args):
    try:
        return review.git(root, list(args)).decode().strip()
    except review.LedgerError as error:
        raise plan.ManifestError(f"Git check failed ({' '.join(args[:3])}): {error}") from error


def feature(root, settings=None):
    if settings is None:
        settings = feature_settings({"cwd": str(root)})
    features = {"autonomous-development", "skill:autonomous-development"}
    plan.require(features <= settings.catalog and not features.intersection(settings.disabled),
                 "Autonomous development is disabled; continue without this workflow. "
                 "Status and interruption commands remain available.")
    return settings


def audit_enabled(state, settings):
    key = "autonomous-development-audit"
    return (state["manifest"]["permissions"].get("publish_audit", False) and
            key in settings.catalog and key not in settings.disabled)


def require_final_audit(state, pr, commit, settings):
    if audit_enabled(state, settings):
        published = state["prs"][pr].get("audits", [{}])[-1]
        plan.require(published.get("stage") == "audit-final" and
                     published.get("code_commit") == commit and not published.get("disabled") and
                     published.get("index_url") == audit.wiki_index(state) and published.get("wiki_commit"),
                     "Final audit is missing, stale or not in the wiki; reconcile for a counted review and audit")


def common_directory(root):
    return (root / git(root, "rev-parse", "--git-common-dir")).resolve()


def save(folder, state):
    state["updated_at"] = time.time()
    review.atomic_write(folder / "RUN.json", plan.encode(state))


def load(folder):
    state = json.loads((folder / "RUN.json").read_bytes())
    plan.require(state["schema"] == 1 and state["store"] == str(folder), "Invalid run storage")
    plan.require(plan.digest(plan.encode(state["manifest"])) == state["approval"],
                 "Approved manifest changed")
    plan.require(json.loads((folder / "MANIFEST.json").read_bytes()) == state["manifest"],
                 "Shared approved manifest changed")
    return state


def input_error(state):
    try:
        plan.artifacts(state["manifest"]["artifacts"], Path(state["store"]) / "inputs")
    except (ValueError, OSError) as error:
        return str(error)
    return None


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
    plan.require_provider(manifest, args.provider)
    plan.require(args.approved == validated["identity"], "Approval must identify this exact manifest")
    root = Path(args.root).resolve()
    plan.require(Path(git(root, "rev-parse", "--show-toplevel")).resolve() == root,
                 "Use the repository worktree root")
    feature(root)
    repository = manifest["repository"]
    plan.require(git(root, "remote", "get-url", repository["remote"]) == repository["url"],
                 "Repository remote does not match the approved manifest")
    targets = worktree_targets(root, manifest)
    for item in manifest["prs"]:
        git(root, "check-ref-format", "--branch", item["branch"])
        git(root, "check-ref-format", "--branch", item["target"])
        git(root, "rev-parse", "--verify", item["base"] + "^{commit}")
        target = targets[item["id"]]
        plan.require(not target.exists() and not (root / item["worktree"]).is_symlink(),
                     f"Worktree already exists: {target}")
        plan.require(not git(root, "branch", "--list", item["branch"]), "Owned branch already exists")
    plan.require(not Path(args.store).is_symlink(), "Store cannot be a symlink")
    folder = Path(args.store).resolve()
    plan.require(not folder.exists() and not folder.is_symlink(), "Store already exists; inspect and resume it")
    plan.require(not folder.resolve().is_relative_to(root), "Keep run evidence outside the repository")
    separate_store(folder, root, targets)
    for target in targets.values():
        try:
            review.external_directory(folder / "reviews" / review.root_key(target), target)
        except review.LedgerError as error:
            raise plan.ManifestError(
                f"{error}; choose --store outside every repository before initialization") from error
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
                 "worktree_roots": {key: str(path) for key, path in targets.items()},
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
    result.append(("draft", None))
    if manifest["permissions"].get("publish_audit", False):
        result.append(("audit-initial", None))
    result.extend((role, None) for role in ("review", "commit"))
    if manifest["permissions"]["screenshots"]:
        result.append(("evidence", None))
    if manifest["permissions"].get("publish_audit", False):
        result.append(("audit-final", None))
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


def overlaps(left, right):
    return left.is_relative_to(right) or right.is_relative_to(left)


def worktree_targets(root, manifest, *, strict=True):
    targets = {}
    metadata = Path(common_directory(root))
    for item in manifest["prs"]:
        (plan.executable_worktree if strict else plan.relative)(item["worktree"])
        target = (root / item["worktree"]).resolve()
        plan.require(not root.is_relative_to(target), "Worktree cannot contain the launch repository")
        plan.require(not any(part in (".git", ".review-loop") for part in target.parts) and
                     not target.is_relative_to(metadata),
                     "Worktree cannot be inside Git/review metadata")
        plan.require(not any(overlaps(target, other) for other in targets.values()),
                     "PR worktrees cannot overlap, including resolved aliases")
        targets[item["id"]] = target
    return targets


def separate_store(folder, root, targets):
    plan.require(not overlaps(folder, root) and
                 not any(overlaps(folder, target) for target in targets.values()),
                 "Private store and repository/worktrees cannot overlap")


def roots(state, pr_id):
    root = Path(state["root"])
    targets = worktree_targets(root, state["manifest"], strict="worktree_roots" in state)
    pinned = state.get("worktree_roots")
    if pinned is not None:
        plan.require(pinned == {key: str(path) for key, path in targets.items()}, "Worktree path changed")
    else:
        plan.require(all(path.is_relative_to(root) and path != root for path in targets.values()),
                     "Legacy run worktree path changed")
    separate_store(Path(state["store"]), root, targets)
    return root if pr_id is None else targets[pr_id]


def unchanged(before, after):
    plan.require(before == after, "Worktree drift invalidates this assignment; preserve work and reconcile")


def capture(root):
    return review.fingerprint(None, root)["manifest"]


def check_worktree(state, pr_id):
    root = roots(state, pr_id)
    pr = plan.indexed(state["manifest"]["prs"])[pr_id]
    plan.require(Path(git(root, "rev-parse", "--show-toplevel")).resolve() == root,
                 "Prepared directory is not a worktree root")
    plan.require(common_directory(root) == common_directory(Path(state["root"])),
                 "Prepared worktree belongs to another repository")
    plan.require(git(root, "branch", "--show-current") == pr["branch"], "Unexpected worktree branch")
    return root


def permission(manifest, role):
    required = {"preflight": ["commit", "push", "create_pr", "mark_ready"],
                "commit": ["commit"], "draft": ["push", "create_pr"],
                "ready": ["push", "mark_ready"], "evidence": ["screenshots"],
                "audit-initial": ["publish_audit", "push", "create_pr"],
                "audit-final": ["publish_audit", "push", "create_pr"]}
    for key in required.get(role, []):
        plan.require(manifest["permissions"][key], f"{key} was not approved for this run")


def reserve(state, settings, launch_models=None):
    feature(Path(state["root"]), settings)
    plan.require(state["outcome"] == "running", "Run is stopped; inspect it before resuming")
    plan.require(state["active"] is None, "An assignment is outstanding; collect or reconcile it first")
    if launch_models is not None:
        models.configuration({"models": launch_models})
        plan.require(set(launch_models) == set(models.ROLES), "Provide launch choices for every worker role")
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
    if role in ("commit", "ready", "evidence", "audit-initial", "audit-final"):
        progress = state["prs"][pr_id]
        accepted = progress["accepted"]
        plan.require(accepted is not None, "A completed review is required")
        plan.require(progress.get("review", {}).get("coverage", {}).get("structurally_complete"),
                     "Review lacks category coverage; reconcile this PR for a counted review "
                     "before continuing, preserving existing work and allowances")
        reviewed = progress["review"]
        files = reviewed["coverage"].get("files")
        plan.require(isinstance(files, list) and
                     set(review_files(root, reviewed["base"])) <= set(files),
                     "Review lacks complete file coverage; reconcile this PR for a counted review "
                     "before continuing, preserving existing work and allowances")
        plan.require(before["files"] == accepted["files"], "Reviewed content changed")
        unchanged(accepted, before)
        if role == "ready":
            require_final_audit(state, pr_id, before["head"], settings)
    if role == "implement":
        state["prs"][pr_id].setdefault("task_bases", {}).setdefault(task_id, before["head"])
    state["attempts"][key] = state["attempts"].get(key, 0) + 1
    assignment = {"id": f"A{len(state['history']) + 1:04d}", "key": key, "role": role,
                  "pr": pr_id, "task": task_id, "root": str(root), "before": before,
                  "attempt": state["attempts"][key], "worker": None, "outcome": "reserved"}
    assignment["launch_models"] = launch_models or {}
    assignment["model_selection"] = model_policy(state, settings)
    if role == "review":
        storage = review.external_run_directory(Path(state["store"]), state["id"], root)
        assignment["review_storage"] = str(review.external_directory(
            storage / "reviews" / review.root_key(root), root))
    assignment["configured_model_fallbacks"] = models.consume_fallbacks(state, key)
    state["active"] = assignment
    state["history"].append(assignment)


def preserve_checkout(assignment, after):
    before = assignment["before"]
    plan.require(before["head"] == after["head"] and before["index"] == after["index"],
                 "Implementation and review must not change HEAD or staging")


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


def review_files(root, base):
    changed = review.git(root, ["diff", "--name-only", "--no-renames", "-z", base, "--"])
    untracked = review.git(root, ["ls-files", "--others", "--exclude-standard", "-z"])
    names = {os.fsdecode(name) for name in (changed + untracked).split(b"\0") if name}
    return sorted(names)


def review_coverage(state, assignment, report, data):
    records = {}
    directory = Path(state["store"]) / "reports"
    for key in ("plan", "handoff"):
        path = Path(data[key]).resolve()
        plan.require(path.is_relative_to(directory) and path != directory,
                     "Review records must remain in this run's private reports")
        records[key] = assignments.read_json(path)
    phase = records["plan"]
    checked = assignments.check(phase, records["handoff"])
    request = phase["request"]
    plan.require(request["root"] == assignment["root"] and request["base"] == report["base"] and
                 request["snapshot"] == report["snapshot"] and request["kind"] == "full",
                 "Final category coverage does not match the completed full review")
    omitted = set(review_files(Path(assignment["root"]), report["base"])) - set(request["files"])
    plan.require(not omitted, "Category review omits changed files: " + json.dumps(sorted(omitted)))
    plan.require(checked["structurally_complete"],
                 "Category review is incomplete: " + json.dumps(checked))
    return {"plan": str(Path(data["plan"]).resolve()),
            "handoff": str(Path(data["handoff"]).resolve()),
            "identity": phase["identity"], "files": request["files"], **checked}


def review_result(state, assignment, data):
    root = Path(assignment["root"])
    report = review.status(SimpleNamespace(ledger=data["ledger"]), root)
    if assignment.get("review_storage"):
        plan.require(Path(report["ledger"]).parent.parent == Path(assignment["review_storage"]),
                     "Move the complete review run directory into the pinned review_storage without "
                     "changing history, then report its new absolute ledger path")
    plan.require(report["outcome"] in ("completed", "completed_with_exceptions") and report["drift"] is False,
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
    report["coverage"] = review_coverage(state, assignment, report, data)
    preserve_checkout(assignment, after)
    unchanged(after, capture(root))
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
    initial = next(item["before"] for item in state["history"]
                   if item["pr"] == assignment["pr"] and item["role"] == "implement")
    for name in review.changed(initial, after):
        if name in after["files"]:
            git(root, "ls-files", "--error-unmatch", "--", name)
    progress = state["prs"][assignment["pr"]]
    progress["accepted"] = after
    progress["commit"] = after["head"]


def delivery_result(state, assignment, data, settings):
    progress = state["prs"][assignment["pr"]]
    after = capture(Path(assignment["root"]))
    unchanged(assignment["before"], after)
    plan.require(data["commit"] == after["head"], "Publication receipt is stale")
    plan.text(data["url"])
    plan.text(data["evidence"])
    expected = "draft" if assignment["role"] == "draft" else "ready"
    plan.require(data["state"] == expected, "PR state does not match the assignment")
    if assignment["role"] == "ready":
        require_final_audit(state, assignment["pr"], after["head"], settings)
    if progress["url"]:
        plan.require(progress["url"] == data["url"], "Publication cannot replace the owned PR")
    progress["url"] = data["url"]


def complete(state, report, settings):
    fields = "assignment worker outcome summary evidence artifacts data"
    plan.fields(report, fields + (" model_report" if "model_report" in report else ""))
    active = state["active"]
    plan.require(active is not None and report["assignment"] == active["id"], "Unexpected assignment result")
    if report["worker"] is not None:
        plan.text(report["worker"])
    plan.text(report["summary"])
    plan.strings(report["evidence"])
    expected = {item["id"]: item["sha256"] for item in state["manifest"]["artifacts"]}
    plan.require(report["artifacts"] == expected, "Approved artifact identity or freshness is missing")
    plan.require(report["outcome"] in ("complete", "blocked", "waiting"), "Unknown worker outcome")
    plan.require(isinstance(report["data"], dict), "Result data must be an object")
    if "model_report" in report:
        models.report_reference(state, active, report["model_report"])
    if report["outcome"] == "complete":
        complete_role(state, active, report["data"], settings)
        if active["pr"]:
            state["prs"][active["pr"]]["position"] += 1
        else:
            state["preflight"] = True
    elif report["outcome"] == "waiting" and active["role"] == "prepare":
        state["prs"][active["pr"]]["waiting"] = True
    else:
        state["outcome"] = "blocked"
        state.pop("stop_kind", None)
    active.update(worker=report["worker"], outcome=report["outcome"], report=report)
    state["history"][-1] = active
    state["active"] = None


def complete_role(state, assignment, data, settings):
    role = assignment["role"]
    if assignment["pr"] and role != "prepare":
        check_worktree(state, assignment["pr"])
    if role == "preflight":
        required = ("artifact_access", "native_permissions", "fresh_workers",
                    "independent_review", "result_delivery", "cancellation")
        plan.require(all(data.get(key) is True for key in required), "Required execution capability is unverified")
        if audit_enabled(state, settings):
            audit.repository(state["manifest"]["repository"]["url"])
            plan.require(data.get("audit_publication") is True,
                         "Verify the initialized GitHub wiki, wiki write access and PR-body editing before execution")
    elif role == "prepare":
        prepare_result(state, assignment, data)
    elif role == "implement":
        after = capture(Path(assignment["root"]))
        preserve_checkout(assignment, after)
    elif role == "review":
        review_result(state, assignment, data)
    elif role == "commit":
        commit_result(state, assignment, data)
    elif role in ("draft", "ready"):
        delivery_result(state, assignment, data, settings)
    elif role in ("audit-initial", "audit-final"):
        unchanged(assignment["before"], capture(Path(assignment["root"])))
        if not audit_enabled(state, settings):
            plan.require(data == {"disabled": True}, "Record disabled audit publication explicitly")
            result = {**data, "stage": role, "code_commit": assignment["before"]["head"]}
        else:
            result = audit.validate_receipt(state, assignment, data)
        state["prs"][assignment["pr"]].setdefault("audits", []).append(result)
    else:
        plan.require(role == "evidence", "Unsupported assignment role")
        unchanged(assignment["before"], capture(Path(assignment["root"])))
        plan.require(data["commit"] == assignment["before"]["head"], "UI evidence is for a different revision")
        plan.strings(data["artifacts"])
        state["prs"][assignment["pr"]]["evidence"] = data


def request(state, settings):
    assignment = state["active"]
    if assignment is None:
        return None
    if settings is None:
        settings = feature_settings({"cwd": state["root"]})
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
            "task_plan": task_details(manifest, assignment["task"]),
            "dependencies": {
                key: progress_summary(state["prs"][key])
                for key in (plan.indexed(manifest["prs"])[assignment["pr"]]["dependencies"]
                            if assignment["pr"] else [])
            },
            "progress": progress_summary(state["prs"][assignment["pr"]]) if assignment["pr"] else None,
            "audit": {"enabled": audit_enabled(state, settings),
                      "index_url": audit.wiki_index(state) if audit_enabled(state, settings) else None},
            "monitoring": {"enabled": monitoring.enabled(settings)},
            "model_selection": assignment.get("model_selection", model_policy(state, settings)),
            "result_file": str(Path(state["store"]) / "reports" / (assignment["id"] + ".json"))}


def progress_summary(progress):
    result = {key: value for key, value in progress.items() if key not in ("accepted", "review", "changed")}
    reviewed = progress.get("review")
    if reviewed:
        result["review"] = {"ledger": reviewed["ledger"], "outcome": reviewed["outcome"],
                            "snapshot": reviewed["snapshot"], "coverage": reviewed.get("coverage")}
    return result


def task_details(manifest, task_id):
    task = plan.indexed(manifest["tasks"]).get(task_id)
    return {key: value for key, value in task.items() if key != "paths"} if task else None


def model_policy(state, settings):
    return {
        "enabled": "autonomous-development-model-selection" in settings.catalog and
                   "autonomous-development-model-selection" not in settings.disabled,
        "review_auto_enabled": "review-auto-model-selection" in settings.catalog and
                               "review-auto-model-selection" not in settings.disabled,
        "review_options": models.review_choices(state["manifest"]["configuration"]["execution"]),
    }


def summary(state, settings=None):
    if settings is None:
        settings = feature_settings({"cwd": state["root"]})
    observed = monitoring.snapshot(state)
    return {"run": state["id"], "store": state["store"], "revision": state["revision"],
            "outcome": state["outcome"], "reason": state.get("reason"),
            **{key: observed[key] for key in ("condition", "updated_at", "review_progress", "progress_error")},
            "execution": {**plan.execution(state["manifest"]),
                          "models": state["manifest"]["configuration"]["execution"].get("models", {})},
            "model_selection": model_policy(state, settings),
            "input_error": input_error(state),
            "consumed_assignments": len(state["history"]), "limits": state["manifest"]["limits"],
            "prs": {key: progress_summary(value) for key, value in state["prs"].items()},
            "assignment": request(state, settings),
            "usage": "Model tokens, cost, and native retries are not measured by this ledger"}


def reconcile(state, args, settings):
    feature(Path(state["root"]), settings)
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
    check_worktree(state, args.pr)
    progress.update(position=index, accepted=None, waiting=False, reconciliation=args.reason)
    state["outcome"] = "running"


def mutate(args, folder):
    with locked(folder):
        state = load(folder)
        if args.command not in ("interrupt", "retire"):
            plan.validate(state["manifest"], folder / "inputs")
        report = json.loads(Path(args.report).read_bytes()) if args.command == "record" else None
        settings = feature_settings({"cwd": state["root"]})
        if report is not None and any(item.get("report") == report for item in state["history"]):
            return summary(state, settings)
        plan.require(args.revision == state["revision"], "Stale revision; inspect status before retrying")
        if args.command == "next":
            plan.require_provider(state["manifest"], args.provider,
                                  strict_worktrees="worktree_roots" in state)
            reserve(state, settings, args.models)
        elif args.command == "record":
            feature(Path(state["root"]), settings)
            complete(state, report, settings)
        elif args.command == "interrupt":
            plan.text(args.reason)
            state["outcome"], state["reason"] = "blocked", args.reason
            state["stop_kind"] = "interrupted"
        elif args.command == "resume":
            feature(Path(state["root"]), settings)
            plan.require(state["outcome"] in ("blocked", "waiting"), "Run cannot resume from this outcome")
            plan.require(state["active"] is None, "Collect the outstanding result or retire it after native worker shutdown")
            plan.text(args.reason)
            state["outcome"], state["reason"] = "running", args.reason
            state.pop("stop_kind", None)
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
            reconcile(state, args, settings)
        elif args.command == "model-fallback":
            feature(Path(state["root"]), settings)
            models.schedule_fallback(state, args)
        state["revision"] += 1
        save(folder, state)
        return summary(state, settings)


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="command", required=True)
    monitoring.add_commands(commands)
    models.add_command(commands)
    validate = commands.add_parser("validate")
    validate.add_argument("manifest")
    validate.add_argument("--provider", help="Check the selected packaged execution adapter")
    initialize = commands.add_parser("init")
    initialize.add_argument("manifest")
    initialize.add_argument("--provider", help="Refuse incompatible packaged execution before creating state")
    for name in ("approved", "root", "store"):
        initialize.add_argument("--" + name, required=True)
    for name in ("status", "next", "record", "interrupt", "resume", "retire", "reconcile", "model-fallback"):
        command = commands.add_parser(name)
        command.add_argument("store")
        if name != "status":
            command.add_argument("--revision", type=int, required=True)
        if name == "next":
            command.add_argument("--provider", help="Check the packaged adapter before reserving capacity")
            command.add_argument("--models", type=json.loads,
                                 help="Complete JSON launch choices, retained without changing the manifest")
        if name == "record":
            command.add_argument("--report", required=True)
        if name in ("interrupt", "resume", "retire", "reconcile", "model-fallback"):
            command.add_argument("--reason", required=True)
        if name in ("retire", "model-fallback"):
            command.add_argument("--shutdown-evidence", required=True)
        if name == "model-fallback":
            command.add_argument("--key", required=True)
            command.add_argument("--role", choices=models.ROLES, required=True)
        if name == "reconcile":
            command.add_argument("--pr", required=True)
    return cli


def main():
    args = parser().parse_args()
    try:
        if args.command == "validate":
            result = plan.read(args.manifest)
            plan.require_provider(result["manifest"], args.provider)
        elif args.command == "init":
            result = summary(initialize(args))
        else:
            folder = Path(args.store).resolve()
            if args.command == "watch":
                return monitoring.watch(folder, load, args)
            if args.command == "model-report":
                path = models.write(load(folder), args)
                result = {"model_report": str(path)}
            elif args.command == "progress":
                state = load(folder)
                settings = feature_settings({"cwd": state["root"]})
                result = ({"recorded": True, "progress": monitoring.write(state, args)}
                          if monitoring.enabled(settings) else {"recorded": False, "reason": "disabled"})
            else:
                result = summary(load(folder)) if args.command == "status" else mutate(args, folder)
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"development-run: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
