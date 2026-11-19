#!/usr/bin/env python3
"""Export selected process evidence and publish explicitly approved bytes to GitHub.

Private inputs, prompts, source objects, raw reports and diagnostic strings never
enter the automatic projection. The assigned worker must review the separate
public narrative and both generated files before approving their digest.
"""

import argparse
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import development_manifest as plan
import development_models as models
import review_history
import review_ledger as review


FILES = ("audit.json", "AUDIT.md")
ROLES = ("audit-initial", "audit-final")
INDEX_PAGE = "Automated-Pull-Request-Audits"
INDEX_HEADER = "| Date | Pull request | Audit records |"
INDEX_SEPARATOR = "| --- | --- | --- |"
LINK_START = "<!-- ioncache-audit:start -->"
LINK_END = "<!-- ioncache-audit:end -->"


def repository(url):
    match = re.fullmatch(r"(?:https://github\.com/|git@github\.com:)([A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+?)(?:\.git)?", url)
    plan.require(match is not None and match[1].split("/")[1] not in (".", ".."),
                 "Audit publication supports an approved github.com repository URL")
    return match[1]


def wiki_index(state):
    repo = repository(state["manifest"]["repository"]["url"])
    return f"https://github.com/{repo}/wiki/{INDEX_PAGE}"


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


def review_identity(path):
    name = path.parent.name
    return name if re.fullmatch(r"[a-f0-9]{32}", name) else identity(str(path))


def review_record(path, root=None):
    result = {"id": review_identity(path), "history_digest": None, "available": False}
    try:
        path = review.ledger_path(root, str(path), allow_unavailable=True, historical=True)
        if not path.is_symlink() and path.is_file():
            result["history_digest"] = review.digest(path.read_bytes())
        loaded = None
        if root is None:
            closed = review.abandoned(path)
            if closed is not None:
                root = Path(closed["root"])
            else:
                loaded = review.load(path)
                root = Path(loaded[0]["root"])
        witness = review_history.read(root, path.parent.name)
        if witness is not None and witness["outcome"] == "failed":
            result.update(outcome="failed", allowance="unavailable", closure_digest=identity(witness))
        if witness is not None and witness["unavailable"]:
            return result
        from review_ownership import release_path

        stores = [path.parent.parent, *(Path(base) for base in witness["stores"])] if witness else [path.parent.parent]
        for base in dict.fromkeys(stores):
            released = release_path(root, base)
            if released.exists():
                result.update(outcome="failed", allowance="unavailable",
                              closure_digest=review.digest(released.read_bytes()))
                return result
        closed = review.abandoned(path)
        if closed is not None:
            result.update(outcome=closed["outcome"], allowance=closed["allowance"],
                          closure_digest=identity(closed))
            return result
        ledger, state = loaded if loaded is not None else review.load(path)
        if witness is not None and witness["digest"] != review.digest(review.encode(ledger)):
            return result
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


def stored_review_paths(root, folders):
    for folder in dict.fromkeys(folders):
        try:
            folder = Path(os.path.abspath(folder))
            folder = review.safe_path(Path(folder.anchor), str(folder.relative_to(folder.anchor)))
            plan.require(folder.name == review.root_key(root), "Review storage belongs to another worktree")
            entries = list(folder.iterdir())
        except (ValueError, OSError):
            continue
        for entry in entries:
            if re.fullmatch(r"[a-f0-9]{32}", entry.name):
                yield entry / "REVIEW_LEDGER.json"


def review_locations(state, assignment):
    root = Path(assignment["root"])
    folders = []
    referenced = {}
    for item in state["history"]:
        if item["pr"] != assignment["pr"] or item["role"] != "review":
            continue
        if item.get("review_storage"):
            folders.append(Path(item["review_storage"]))
        reference = item.get("report", {}).get("data", {}).get("ledger")
        if isinstance(reference, str):
            path = Path(os.path.abspath(root / reference))
            try:
                path = review.ledger_path(root, reference, allow_unavailable=True, historical=True)
            except (ValueError, OSError, KeyError, TypeError):
                pass
            referenced[review_identity(path)] = path
    for path in stored_review_paths(root, folders):
        referenced.setdefault(review_identity(path), path)
    return sorted(referenced.values(), key=review_identity)


def build(state, assignment, public, *, model_snapshot=None):
    root = Path(assignment["root"])
    records = [review_record(path, root) for path in review_locations(state, assignment)]
    for record in records:
        record["assignment_ids"] = []
        for item in state["history"]:
            reference = item.get("report", {}).get("data", {}).get("ledger")
            if item["pr"] == assignment["pr"] and item["role"] == "review" and isinstance(reference, str):
                path = Path(os.path.abspath(root / reference))
                if review_identity(path) == record["id"]:
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
    model_records, models_unavailable = (models.observations(state, assignment["pr"])
                                       if model_snapshot is None else model_snapshot)
    return {"schema": 1, "run": state["id"], "pr": assignment["pr"], "assignment": assignment["id"],
            "stage": assignment["role"], "approval": state["approval"],
            "inputs": [{"role": item["role"], "digest": item["sha256"]}
                       for item in state["manifest"]["artifacts"]],
            "code_commit": assignment["before"]["head"], "snapshot": identity(assignment["before"]),
            "limits": state["manifest"]["limits"], "consumed_assignments": len(state["history"]),
            "history": history, "reviews": records, "public": public_narrative(public, records),
            "models": model_records, "models_unavailable": models_unavailable,
            "metrics": {"tokens": None, "cost": None, "worker_durations": None},
            "limitations": [
                "Publication-reviewed narrative is supplied evidence, not independently proven truth.",
                "Private inputs, prompts, source objects and raw reports are excluded.",
                "Missing history remains unavailable; this is not a complete native execution log.",
                "Hashes detect changed evidence but do not authenticate authors or prove isolation.",
                "An empty regression list means no relationship was supplied, not no regressions.",
                "Selected models are requests, not observations; null actual identities remain unknown.",
                "Native model observations are supplied evidence, not independently authenticated.",
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
            "index_url": wiki_index(state), "files": list(FILES)}


def archive(state, pr, public):
    plan.require(pr in state["prs"], "Archive requires a known --pr")
    saved = next((item for item in reversed(state["history"])
                  if item["pr"] == pr and item.get("before") is not None), None)
    plan.require(saved is not None, "No saved PR snapshot is available")
    bundle = build(state, {**saved, "role": "archive"}, public)
    bundle["limitations"].append(
        "Historical export only: the worktree was not checked and this does not authorize publication.")
    files = contents(bundle)
    key = bundle_identity(files)
    storage = review.external_run_directory(Path(state["store"]), state["id"], Path(state["root"]))
    folder = review.external_directory(storage / "archives" / pr / key)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name, data in files.items():
        review.atomic_write(review.safe_path(folder, name), data)
    return {"directory": str(folder), "identity": key, "files": list(FILES), "historical": True}


def prepared(state, assignment):
    folder = directory(state, assignment)
    files = {name: review.safe_path(folder, name).read_bytes() for name in FILES}
    bundle = json.loads(files["audit.json"])
    expected = build(state, assignment, bundle["public"],
                     model_snapshot=(bundle["models"], bundle["models_unavailable"]))
    plan.require(bundle == expected and files == contents(bundle),
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


def api(endpoint, *, data=None, method=None):
    args = ["gh", "api", "--hostname", "github.com", endpoint]
    if data is not None:
        args.extend(["--method", method or "POST", "--input", "-"])
    return json.loads(command(args, data=plan.encode(data) if data is not None else None))


def match_repository_url(value, repo, resource):
    return re.fullmatch(rf"https://github\.com/(?ai:{re.escape(repo)})/{resource}", value or "")


def target(state, assignment):
    repo = repository(state["manifest"]["repository"]["url"])
    url = state["prs"][assignment["pr"]]["url"]
    match = match_repository_url(url, repo, r"pull/([1-9][0-9]*)")
    plan.require(match is not None, "Audit must attach to this run's PR in the approved repository")
    return repo, match[1]


def publication_links(state, assignment, exported):
    repo, number = target(state, assignment)
    plan.require(re.fullmatch(r"[a-f0-9]{32}", state["id"]), "Invalid development run ID")
    plan.require(re.fullmatch(r"A[0-9]+", assignment["id"]) and
                 re.fullmatch(r"[a-f0-9]{64}", exported), "Invalid audit publication identity")
    page = f"Audit-PR-{number}-run-{state['id']}-{assignment['id']}-{exported}"
    url = f"https://github.com/{repo}/wiki/{page}"
    return {"page": page, "url": url, "data_url": url + ".json",
            "index_url": wiki_index(state), "pr_url": f"https://github.com/{repo}/pull/{number}"}


def audit_links(publication):
    return (f"[Report]({publication['url']}) &#183; [Data (audit.json)]({publication['data_url']})"
            f" &#183; [Automated Pull Request Audits]({publication['index_url']})")


def index_entry(text, publication):
    lines = text.splitlines(keepends=True)
    headers = [i for i, line in enumerate(lines)
               if re.fullmatch(r"\|\s*Date\s*\|\s*Pull request\s*\|\s*Audit records\s*\|", line.strip())]
    plan.require(len(headers) == 1, "Preserve the wiki index and restore one Date / Pull request / Audit records table")
    start = headers[0] + 1
    plan.require(start < len(lines) and re.fullmatch(r"\|(?:\s*:?-{3,}:?\s*\|){3}", lines[start].strip()),
                 "Preserve the wiki index and repair its audit table separator before retrying")
    start += 1
    end = start
    while end < len(lines) and lines[end].lstrip().startswith("|"):
        end += 1
    pr_cell = (r"^\|[^|]*\|\s*\[(?:\\.|[^\]\\])*\]\("
               + re.escape(publication["pr_url"]) + r"\)\s*\|")
    matches = [i for i in range(start, end) if re.match(pr_cell, lines[i], re.IGNORECASE)]
    plan.require(len(matches) <= 1, "Preserve duplicate wiki audit records and consolidate this PR's row before retrying")
    if matches and all(f"]({publication[key]})" in lines[matches[0]] for key in ("url", "data_url")):
        return text
    if matches:
        del lines[matches[0]]
    title = html.escape(" ".join(publication["title"].split()), quote=False).replace("|", "&#124;")
    title = re.sub(r"([\\`*_\[\]])", r"\\\1", title)
    number = publication["pr_url"].rsplit("/", 1)[1]
    date = datetime.now(timezone.utc).date().isoformat()
    row = (f"| {date} | [#{number} {title}]({publication['pr_url']}) | "
           f"[Report]({publication['url']}) &#183; [Data (audit.json)]({publication['data_url']}) |\n")
    lines[start - 1] = lines[start - 1].rstrip("\r\n") + "\n"
    lines.insert(start, row)
    return "".join(lines)


def wiki_files(root, publication, files):
    expected = {publication["page"] + ".md": files["AUDIT.md"],
                publication["page"] + ".json": files["audit.json"]}
    for filename, data in expected.items():
        path = review.safe_path(root, filename)
        plan.require(not path.exists() or path.read_bytes() == data,
                     f"Published audit differs at {filename}; preserve it and inspect the export and wiki history")
    path = review.safe_path(root, INDEX_PAGE + ".md")
    text = (path.read_text() if path.exists() else
            "Development process audit records, one row per pull request. Newest first.\n\n"
            f"{INDEX_HEADER}\n{INDEX_SEPARATOR}\n")
    expected[path.name] = index_entry(text, publication).encode()
    return expected


def wiki_head(root, remote):
    advertised = command(["git", "ls-remote", "--symref", remote, "HEAD"], cwd=root).decode()
    refs = re.findall(r"^ref: (refs/heads/[^\s]+)\tHEAD$", advertised, re.MULTILINE)
    plan.require(len(refs) == 1,
                 "The repository wiki must already be initialized and accessible; no audit was published")
    command(["git", "fetch", "-q", "--no-tags", remote, refs[0]], cwd=root)
    command(["git", "checkout", "-q", "-B", "wiki", "FETCH_HEAD"], cwd=root)
    return refs[0], command(["git", "rev-parse", "HEAD"], cwd=root).decode().strip()


def verify_wiki_commit(root, parent, expected):
    commit = command(["git", "rev-parse", "HEAD"], cwd=root).decode().strip()
    changed = command(["git", "diff", "--name-only", "-z", parent, commit], cwd=root).decode().split("\0")[:-1]
    plan.require(set(changed) <= set(expected), "Git changed unrelated wiki files; inspect commit hooks before retrying")
    for filename, data in expected.items():
        entry = command(["git", "ls-tree", commit, "--", filename], cwd=root)
        plan.require(entry.startswith(b"100644 blob ") and
                     command(["git", "show", f"{commit}:{filename}"], cwd=root) == data,
                     f"Git changed approved wiki bytes for {filename}; inspect filters/hooks before retrying")
    return commit


def publish_files(state, publication, files):
    url = state["manifest"]["repository"]["url"]
    remote = url.removesuffix(".git") + ".wiki.git"
    with tempfile.TemporaryDirectory(prefix="audit-publish-", dir=state["store"]) as temporary:
        root = Path(temporary)
        command(["git", "init", "-q", "-b", "wiki"], cwd=root)
        command(["git", "config", "user.name", "Autonomous development audit"], cwd=root)
        command(["git", "config", "user.email", "audit@users.noreply.github.com"], cwd=root)
        command(["git", "config", "--add", "credential.https://github.com.helper", ""], cwd=root)
        command(["git", "config", "--add", "credential.https://github.com.helper",
                 "!gh auth git-credential"], cwd=root)
        for attempt in range(3):
            ref, parent = wiki_head(root, remote)
            expected = wiki_files(root, publication, files)
            for filename, data in expected.items():
                review.atomic_write(review.safe_path(root, filename), data)
            command(["git", "add", "--", *expected], cwd=root)
            if not command(["git", "diff", "--cached", "--name-only"], cwd=root).strip():
                return verify_wiki_commit(root, parent, expected)
            command(["git", "commit", "-qm", "docs: publish development process audit"], cwd=root)
            commit = verify_wiki_commit(root, parent, expected)
            try:
                command(["git", "push", "--no-follow-tags", remote, f"{commit}:{ref}"], cwd=root)
            except plan.ManifestError:
                observed = command(["git", "ls-remote", "--refs", remote, ref], cwd=root).decode().split()
                if not observed or observed[0] == parent:
                    raise
                continue
            command(["git", "fetch", "-q", "--no-tags", remote, ref], cwd=root)
            command(["git", "merge-base", "--is-ancestor", commit, "FETCH_HEAD"], cwd=root)
            return commit
    raise plan.ManifestError("Wiki kept changing during publication; retry the same export without force-pushing")


def pr_body(body, publication):
    block = f"{LINK_START}\n{audit_links(publication)}\n{LINK_END}"
    if LINK_START in body or LINK_END in body:
        plan.require(body.count(LINK_START) == body.count(LINK_END) == 1,
                     "Preserve PR text and restore one audit link block before retrying")
        start, end = body.index(LINK_START), body.index(LINK_END)
        previous = body[start + len(LINK_START):end].strip()
        match = re.match(r"\[Report\]\((https://github\.com/[^)\s]+/wiki/Audit-PR-[^)\s]+)\)", previous)
        old = {**publication, "url": match[1], "data_url": match[1] + ".json"} if match else {}
        plan.require(end > start and match and previous == audit_links(old),
                     "Audit link block was edited; preserve manual text outside the block before retrying")
        return body[:start] + block + body[end + len(LINK_END):]
    heading = re.search(r"^## Audit[ \t]*\r?$", body, re.MULTILINE)
    if heading:
        return body[:heading.end()] + "\n\n" + block + "\n" + body[heading.end():]
    checklist = re.search(r"^## Checklist[ \t]*\r?$", body, re.MULTILINE)
    offset = checklist.start() if checklist else len(body)
    return body[:offset] + ("\n\n" if offset else "") + f"## Audit\n\n{block}\n\n" + body[offset:]


def checked_pull(state, assignment, bundle):
    repo, number = target(state, assignment)
    pull = api(f"repos/{repo}/pulls/{number}")
    pr = plan.indexed(state["manifest"]["prs"])[assignment["pr"]]
    plan.require(pull["state"] == "open" and pull["head"]["sha"] == bundle["code_commit"] and
                 pull["head"]["ref"] == pr["branch"] and
                 pull["head"]["repo"]["full_name"].casefold() == repo.casefold(),
                 "Push the accepted implementation commit to its existing PR before audit publication")
    return pull


def publish(state, assignment, approved):
    bundle, files = prepared(state, assignment)
    exported = bundle_identity(files)
    plan.require(approved == exported, "Publication approval must identify both exact exported files")
    repo, number = target(state, assignment)
    pull = checked_pull(state, assignment, bundle)
    publication = publication_links(state, assignment, exported)
    pr_body(pull.get("body") or "", publication)
    commit = publish_files(state, {**publication, "title": plan.text(pull["title"])}, files)
    pull = checked_pull(state, assignment, bundle)
    original = pull.get("body") or ""
    body = pr_body(original, publication)
    if body != original:
        api(f"repos/{repo}/pulls/{number}", method="PATCH", data={"body": body})
    observed = checked_pull(state, assignment, bundle)
    plan.require(observed.get("body") == body, "PR audit links were not confirmed; reread the PR and retry")
    result = {"stage": assignment["role"], "code_commit": bundle["code_commit"],
              "bundle": exported, "wiki_commit": commit,
              **{key: value for key, value in publication.items() if key != "page"}}
    review.atomic_write(directory(state, assignment) / "receipt.json", plan.encode(result))
    return result


def validate_receipt(state, assignment, data):
    bundle, files = prepared(state, assignment)
    receipt = json.loads(review.safe_path(directory(state, assignment), "receipt.json").read_bytes())
    exported = bundle_identity(files)
    publication = publication_links(state, assignment, exported)
    plan.fields(receipt, "stage code_commit bundle wiki_commit url data_url index_url pr_url")
    plan.require(data == receipt and receipt["stage"] == assignment["role"] and
                 receipt["code_commit"] == bundle["code_commit"] and receipt["bundle"] == exported and
                 re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", receipt["wiki_commit"]) and
                 all(receipt[key] == value for key, value in publication.items() if key != "page"),
                 "Audit receipt does not match this assignment's reviewed export")
    return receipt


def main():
    import development_run as development

    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("operation", choices=("export", "publish", "archive"))
    cli.add_argument("store")
    cli.add_argument("--public", help="Publication-reviewed narrative JSON, required for export")
    cli.add_argument("--approved", help="Exact exported bundle identity, required for publish")
    cli.add_argument("--pr", help="PR plan ID for a historical archive; never publishes")
    args = cli.parse_args()
    try:
        folder = Path(args.store).resolve()
        with development.locked(folder):
            state = development.load(folder)
            if args.operation == "archive":
                plan.require(args.public is not None, "Archive requires --public")
                result = archive(state, args.pr, json.loads(Path(args.public).read_bytes()))
                print(json.dumps(result, indent=2))
                return 0
            settings = development.feature(Path(state["root"]))
            plan.require(development.audit_enabled(state, settings), "Audit publication is disabled or not approved")
            plan.validate(state["manifest"], folder / "inputs")
            assignment = state["active"]
            plan.require(assignment is not None and assignment["role"] in ROLES,
                         "Reserve an audit assignment before exporting or publishing")
            development.permission(state["manifest"], assignment["role"])
            root = development.check_worktree(state, assignment["pr"])
            development.require_cached_review_usable(state, assignment["pr"], root)
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
