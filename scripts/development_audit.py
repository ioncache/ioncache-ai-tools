#!/usr/bin/env python3
"""Export selected process evidence and publish explicitly approved bytes to GitHub.

Private inputs, prompts, source objects, raw reports and diagnostic strings never
enter the automatic projection. The assigned worker must review the separate
public narrative and both generated files before approving their digest.
"""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import development_manifest as plan
import review_ledger as review


FILES = ("audit.json", "AUDIT.md")
ROLES = ("audit-initial", "audit-final")


def repository(url):
    match = re.fullmatch(r"(?:https://github\.com/|git@github\.com:)([A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+?)(?:\.git)?", url)
    plan.require(match is not None and match[1].split("/")[1] not in (".", ".."),
                 "Audit publication supports an approved github.com repository URL")
    return match[1]


def branch(state, pr):
    plan.require(re.fullmatch(r"[a-f0-9]{32}", state["id"]), "Invalid development run ID")
    plan.identifier(pr)
    name = f"ioncache-audit/{state['id']}/{pr}"
    target = plan.indexed(state["manifest"]["prs"])[pr]
    plan.require(name not in (target["branch"], target["target"],
                              state["manifest"]["repository"]["default_branch"]),
                 "Audit branch must be separate from implementation and target branches")
    return name


def directory(state, assignment):
    plan.require(assignment["role"] in ROLES and re.fullmatch(r"A[0-9]+", assignment["id"]),
                 "Audit requires a reserved publication assignment")
    return review.safe_path(Path(state["store"]), f"reports/{assignment['id']}/audit")


def timestamp(value):
    try:
        return datetime.fromisoformat(value).isoformat()
    except (ValueError, TypeError):
        return None


def identity(value):
    return plan.digest(plan.encode(value))


def review_record(path):
    result = {"id": path.parent.name, "history_digest": None, "available": False}
    try:
        if path.exists():
            result["history_digest"] = review.digest(path.read_bytes())
        closed = review.abandoned(path)
        if closed is not None:
            result.update(outcome=closed["outcome"], allowance=closed["allowance"],
                          closure_digest=identity(closed))
            return result
        ledger, state = review.load(path)
        review.ensure_owner(ledger, path.parent.parent.parent)
    except (ValueError, OSError, KeyError, TypeError):
        return result
    result.update(available=True, base=ledger["base"], snapshot=state["snapshot"],
                  outcome=state["outcome"], limits=state["limits"],
                  loops=len(state["loops"]),
                  fix_cycles=sum(len(loop["cycles"]) for loop in state["loops"]),
                  findings=[], events=[])
    for item in state["findings"].values():
        result["findings"].append({
            "id": item["id"], "severity": item["severity"], "validation": item["validation"],
            "disposition": item["disposition"],
            "observations": [event["sequence"] for event in item["observations"]],
            "decisions": [{key: event[key] for key in ("sequence", "validation", "disposition", "severity")}
                          for event in item["decisions"]],
        })
    for event in ledger["events"]:
        row = {key: event[key] for key in ("sequence", "type", "snapshot")}
        row["time"] = timestamp(event["time"])
        row["evidence_digest"] = identity(event)
        if "findings" in event:
            row["findings"] = event["findings"]
        if "id" in event:
            row["finding"] = event["id"]
        if "results" in event:
            row["results"] = {key: item["result"] for key, item in event["results"].items()}
        if "checks" in event:
            row["checks"] = [item["result"] for item in event["checks"]]
        if "passes" in event:
            row["passes"] = [{"record_digest": identity(item),
                              "worker_digest": (None if item["worker"].startswith("unobserved")
                                                else identity(item["worker"]))}
                             for item in event["passes"]]
        result["events"].append(row)
    return result


def public_narrative(value, reviews):
    plan.fields(value, "summary method verification findings regressions limitations")
    for key in ("summary", "method", "verification"):
        plan.text(value[key])
    plan.strings(value["limitations"], empty=True)
    known = {(item["id"], finding["id"]) for item in reviews if item["available"]
             for finding in item["findings"]}
    supplied = set()
    plan.require(isinstance(value["findings"], list) and isinstance(value["regressions"], list),
                 "Public findings and regressions must be lists")
    for item in value["findings"]:
        plan.fields(item, "review id summary rationale")
        key = (plan.text(item["review"]), plan.text(item["id"]))
        plan.require(key in known and key not in supplied, "Unknown or duplicate public finding")
        supplied.add(key)
        plan.text(item["summary"])
        plan.text(item["rationale"])
    plan.require(supplied == known, "Public narrative must account for every recorded finding")
    for item in value["regressions"]:
        plan.fields(item, "cause effect basis evidence")
        for key in ("cause", "effect"):
            plan.fields(item[key], "review id")
            plan.require((item[key]["review"], item[key]["id"]) in known, "Unknown regression reference")
        plan.require(item["cause"] != item["effect"] and item["basis"] in ("observed", "inferred"),
                     "A regression needs distinct findings and an explicit evidence basis")
        plan.text(item["evidence"])
    return value


def build(state, assignment, public):
    root = Path(assignment["root"])
    folder = review.safe_path(root, ".review-loop")
    paths = sorted(folder.glob("*/REVIEW_LEDGER.json")) if folder.exists() else []
    # Published run directories with a lost ledger must remain visible as gaps.
    if folder.exists():
        paths = sorted({*paths, *(item / "REVIEW_LEDGER.json" for item in folder.iterdir()
                                 if re.fullmatch(r"[a-f0-9]{32}", item.name))})
    records = [review_record(review.safe_path(root, str(path.relative_to(root))))
               for path in paths if re.fullmatch(r"[a-f0-9]{32}", path.parent.name)]
    for record in records:
        record["assignment_ids"] = []
        for item in state["history"]:
            reference = item.get("report", {}).get("data", {}).get("ledger")
            if item["pr"] == assignment["pr"] and item["role"] == "review" and isinstance(reference, str):
                resolved = Path(os.path.abspath(Path(item["root"]) / reference))
                if resolved == folder / record["id"] / "REVIEW_LEDGER.json":
                    record["assignment_ids"].append(item["id"])
    history = []
    for item in state["history"]:
        if item["pr"] not in (None, assignment["pr"]):
            continue
        history.append({key: item[key] for key in ("id", "role", "task", "attempt", "outcome")} |
                       {"worker_digest": identity(item["worker"]) if item["worker"] else None,
                        "before_snapshot": identity(item["before"]) if item["before"] is not None else None,
                        "code_commit": item["before"]["head"] if item["before"] is not None else None,
                        "report_digest": identity(item["report"]) if item.get("report") else None,
                        "audit_disabled": item.get("report", {}).get("data", {}).get("disabled") is True
                        if item["role"] in ROLES else None})
    return {"schema": 1, "run": state["id"], "pr": assignment["pr"], "assignment": assignment["id"],
            "stage": assignment["role"], "approval": state["approval"],
            "inputs": [{"role": item["role"], "digest": item["sha256"]}
                       for item in state["manifest"]["artifacts"]],
            "code_commit": assignment["before"]["head"], "snapshot": identity(assignment["before"]),
            "limits": state["manifest"]["limits"], "consumed_assignments": len(state["history"]),
            "history": history, "reviews": records, "public": public_narrative(public, records),
            "metrics": {"tokens": None, "cost": None, "worker_durations": None},
            "limitations": [
                "Publication-reviewed narrative is supplied evidence, not independently proven truth.",
                "Private inputs, prompts, source objects and raw reports are excluded.",
                "Missing history remains unavailable; this is not a complete native execution log.",
                "Hashes detect changed evidence but do not authenticate authors or prove isolation.",
                "An empty regression list means no relationship was supplied, not no regressions.",
            ]}


def render(bundle):
    public = bundle["public"]
    lines = ["# Development process audit", "", public["summary"], "",
             f"Stage: `{bundle['stage']}`. Code commit: `{bundle['code_commit']}`.",
             f"Run: `{bundle['run']}`. Assignment: `{bundle['assignment']}`.", "",
             "## Review method", "", public["method"], "", "## Verification", "", public["verification"],
             "", "## Findings and decisions", ""]
    for item in public["findings"]:
        lines.extend([f"### {item['review']}/{item['id']}", "", item["summary"], "", item["rationale"], ""])
    if not public["findings"]:
        lines.extend(["No findings are present in the available recorded histories.", ""])
    lines.extend(["## Regression relationships", ""])
    for item in public["regressions"]:
        cause, effect = (item[key] for key in ("cause", "effect"))
        lines.extend([f"- `{cause['review']}/{cause['id']}` -> `{effect['review']}/{effect['id']}` "
                      f"({item['basis']}): {item['evidence']}"])
    if not public["regressions"]:
        lines.append("No causal relationships were supplied; this does not establish absence of regressions.")
    lines.extend(["", "## Process records", "", f"Consumed assignments across the run: {bundle['consumed_assignments']}.",
                  "See audit.json for iteration history, decisions, checks, limits and evidence identities.",
                  "Token usage, cost and worker durations are not collected.", "", "## Limitations", ""])
    lines.extend(f"- {item}" for item in bundle["limitations"] + public["limitations"])
    if any(not item["available"] for item in bundle["reviews"]):
        lines.append("- Some review history is unavailable. Its findings and counters were not reconstructed.")
    return ("\n".join(lines) + "\n").encode()


def contents(bundle):
    return {"audit.json": plan.encode(bundle), "AUDIT.md": render(bundle)}


def bundle_identity(files):
    return identity({name: review.digest(data) for name, data in files.items()})


def export(state, assignment, public):
    bundle = build(state, assignment, public)
    folder = directory(state, assignment)
    folder.parent.mkdir(exist_ok=True, mode=0o700)
    folder.mkdir(exist_ok=True, mode=0o700)
    files = contents(bundle)
    for name, data in files.items():
        review.atomic_write(review.safe_path(folder, name), data)
    return {"directory": str(folder), "identity": bundle_identity(files),
            "branch": branch(state, assignment["pr"]), "files": list(FILES)}


def prepared(state, assignment):
    folder = directory(state, assignment)
    files = {name: review.safe_path(folder, name).read_bytes() for name in FILES}
    bundle = json.loads(files["audit.json"])
    plan.require(bundle == build(state, assignment, bundle["public"]) and files == contents(bundle),
                 "Audit evidence changed; regenerate and review a new export before publishing")
    return bundle, files


def command(argv, *, cwd=None, data=None):
    env = {key: value for key, value in os.environ.items() if key not in {
        "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    }}
    result = subprocess.run(argv, cwd=cwd, input=data, env=env, capture_output=True, timeout=120)
    plan.require(result.returncode == 0, result.stderr.decode(errors="replace"))
    return result.stdout


def api(endpoint, *, data=None, paginate=False):
    args = ["gh", "api", "--hostname", "github.com", endpoint]
    if paginate:
        args.extend(["--paginate", "--slurp"])
    if data is not None:
        args.extend(["--method", "POST", "--input", "-"])
    return json.loads(command(args, data=plan.encode(data) if data is not None else None))


def target(state, assignment):
    repo = repository(state["manifest"]["repository"]["url"])
    url = state["prs"][assignment["pr"]]["url"]
    match = re.fullmatch(rf"https://github\.com/{re.escape(repo)}/pull/([1-9][0-9]*)", url or "")
    plan.require(match is not None, "Audit must attach to this run's PR in the approved repository")
    return repo, match[1]


def publish_files(state, assignment, files):
    remote = state["manifest"]["repository"]["url"]
    name = branch(state, assignment["pr"])
    ref = "refs/heads/" + name
    with tempfile.TemporaryDirectory(prefix="audit-publish-", dir=state["store"]) as temporary:
        root = Path(temporary)
        command(["git", "init", "-q", "-b", "audit"], cwd=root)
        command(["git", "config", "user.name", "Autonomous development audit"], cwd=root)
        command(["git", "config", "user.email", "audit@users.noreply.github.com"], cwd=root)
        existing = command(["git", "ls-remote", "--refs", remote, ref], cwd=root).decode().strip()
        if existing:
            command(["git", "fetch", "-q", "--no-tags", remote, ref], cwd=root)
            command(["git", "checkout", "-q", "-B", "audit", "FETCH_HEAD"], cwd=root)
            names = command(["git", "ls-files", "-z"], cwd=root).decode().split("\0")[:-1]
            plan.require(set(names) == set(FILES), "Audit branch has unexpected files; preserve it and inspect")
            old = json.loads(review.safe_path(root, "audit.json").read_bytes())
            plan.require(all(old.get(key) == state[value] for key, value in
                             (("run", "id"), ("approval", "approval"))) and old.get("pr") == assignment["pr"],
                         "Audit branch belongs to different approved work; preserve it and inspect")
        for filename, data in files.items():
            review.atomic_write(review.safe_path(root, filename), data)
        command(["git", "add", "--", *FILES], cwd=root)
        if not existing or command(["git", "diff", "--cached", "--name-only"], cwd=root).strip():
            command(["git", "commit", "-qm",
                     "docs: publish development process audit"], cwd=root)
        commit = command(["git", "rev-parse", "HEAD"], cwd=root).decode().strip()
        names = command(["git", "ls-tree", "-r", "--name-only", "-z", commit], cwd=root).decode().split("\0")[:-1]
        plan.require(set(names) == set(FILES), "Git added unexpected audit files; inspect commit hooks before retrying")
        for filename, expected in files.items():
            plan.require(command(["git", "show", f"{commit}:{filename}"], cwd=root) == expected,
                         f"Git changed approved audit bytes for {filename}; inspect filters/hooks before retrying")
        command(["git", "push", "--no-follow-tags", remote, f"{commit}:{ref}"], cwd=root)
        observed = command(["git", "ls-remote", "--refs", remote, ref], cwd=root).decode().split()
        plan.require(observed and observed[0] == commit, "Audit branch publication is not confirmed")
        return commit


def publish(state, assignment, approved):
    bundle, files = prepared(state, assignment)
    exported = bundle_identity(files)
    plan.require(approved == exported, "Publication approval must identify both exact exported files")
    repo, number = target(state, assignment)
    pull = api(f"repos/{repo}/pulls/{number}")
    pr = plan.indexed(state["manifest"]["prs"])[assignment["pr"]]
    plan.require(pull["state"] == "open" and pull["head"]["sha"] == bundle["code_commit"] and
                 pull["head"]["ref"] == pr["branch"] and pull["head"]["repo"]["full_name"] == repo,
                 "Push the accepted implementation commit to its existing PR before audit publication")
    commit = publish_files(state, assignment, files)
    url = f"https://github.com/{repo}/tree/{commit}"
    marker = f"<!-- ioncache-audit:{state['id']}:{assignment['id']}:{exported} -->"
    body = (f"{marker}\nDevelopment audit ({assignment['role']}) for `{bundle['code_commit']}`:\n\n"
            f"https://github.com/{repo}/blob/{commit}/AUDIT.md\n\n"
            f"https://github.com/{repo}/blob/{commit}/audit.json\n\nBundle identity: `{exported}`")
    login = api("user")["login"]
    pages = api(f"repos/{repo}/issues/{number}/comments?per_page=100", paginate=True)
    matches = [item for page in pages for item in page
               if marker in item.get("body", "") and (item.get("user") or {}).get("login") == login]
    plan.require(len(matches) <= 1, "Multiple audit comments found; inspect before retrying publication")
    if matches:
        comment = matches[0]
        plan.require(comment["body"] == body, "Existing audit comment changed; preserve it and inspect")
    else:
        comment = api(f"repos/{repo}/issues/{number}/comments", data={"body": body})
    plan.require(comment["body"] == body, "Audit comment publication is not confirmed")
    result = {"stage": assignment["role"], "code_commit": bundle["code_commit"],
              "bundle": exported, "audit_commit": commit, "branch": branch(state, assignment["pr"]),
              "url": url, "comment_url": comment["html_url"]}
    review.atomic_write(directory(state, assignment) / "receipt.json", plan.encode(result))
    return result


def validate_receipt(state, assignment, data):
    bundle, files = prepared(state, assignment)
    receipt = json.loads(review.safe_path(directory(state, assignment), "receipt.json").read_bytes())
    repo, number = target(state, assignment)
    plan.fields(receipt, "stage code_commit bundle audit_commit branch url comment_url")
    plan.require(data == receipt and receipt["stage"] == assignment["role"] and
                 receipt["code_commit"] == bundle["code_commit"] and receipt["bundle"] == bundle_identity(files) and
                 re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", receipt["audit_commit"]) and
                 receipt["branch"] == branch(state, assignment["pr"]) and
                 receipt["url"] == f"https://github.com/{repo}/tree/{receipt['audit_commit']}" and
                 re.fullmatch(rf"https://github\.com/{re.escape(repo)}/pull/{number}#issuecomment-[0-9]+",
                              receipt["comment_url"]),
                 "Audit receipt does not match this assignment's reviewed export")
    return receipt


def main():
    import development_run as development

    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("operation", choices=("export", "publish"))
    cli.add_argument("store")
    cli.add_argument("--public", help="Publication-reviewed narrative JSON, required for export")
    cli.add_argument("--approved", help="Exact exported bundle identity, required for publish")
    args = cli.parse_args()
    try:
        folder = Path(args.store).resolve()
        with development.locked(folder):
            state = development.load(folder)
            development.feature(Path(state["root"]))
            plan.require(development.audit_enabled(state), "Audit publication is disabled or not approved")
            plan.validate(state["manifest"], folder / "inputs")
            assignment = state["active"]
            plan.require(assignment is not None and assignment["role"] in ROLES,
                         "Reserve an audit assignment before exporting or publishing")
            development.permission(state["manifest"], assignment["role"])
            root = development.check_worktree(state, assignment["pr"])
            development.unchanged(assignment["before"], development.capture(root))
            if args.operation == "export":
                plan.require(args.public is not None, "Export requires --public")
                result = export(state, assignment, json.loads(Path(args.public).read_bytes()))
            else:
                result = publish(state, assignment, args.approved)
            development.unchanged(assignment["before"], development.capture(root))
            print(json.dumps(result, indent=2))
    except (ValueError, OSError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        print(f"development-audit: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
