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
from urllib.parse import quote

import development_audit_data as projection
from development_audit_render import render
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
HOME_START = "<!-- ioncache-audit-index:start -->"
HOME_END = "<!-- ioncache-audit-index:end -->"
HOME_TITLE = r'''(?:"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|\((?:\\.|[^()\\\n])*\))'''
HOME_REFERENCE = (r'^ {0,3}\[([^\]\n]+)\]:[ \t]*(?:\n[ \t]*)?'
                  r'(?:<([^>\n]+)>|([^\s<>]+))'
                  r'(?:[ \t]+' + HOME_TITLE + r')?[ \t]*$')


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
    result["passes"], event_pass = projection.review_passes(ledger, state)
    result["findings"] = projection.review_findings(state, event_pass)
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
    projection.narrative_options(value)
    plan.strings(value["limitations"], empty=True)
    known = {(item["id"], finding["id"]): finding for item in reviews if item["available"]
             for finding in item["findings"]}
    supplied = set()
    plan.require(isinstance(value["findings"], list) and isinstance(value["regressions"], list),
                 "Public findings and regressions must be lists")
    for item in value["findings"]:
        plan.require(isinstance(item, dict), "Public finding must be an object")
        key = (plan.text(item["review"]), plan.text(item["id"]))
        plan.require(key in known and key not in supplied, "Unknown or duplicate public finding")
        supplied.add(key)
        plan.text(item["summary"])
        plan.text(item["rationale"])
        projection.finding_details(item, known[key])
    plan.require(supplied == set(known), "Public narrative must account for every recorded finding")
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


def build(state, assignment, public, *, model_snapshot=None, publication_snapshot=None):
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
    records.sort(key=lambda item: (item["assignment_ids"] or ["~"], item["id"]))
    if len(records) > 1:
        for number, record in enumerate(records, 1):
            for finding in record.get("findings", []):
                finding["pass"] = f"Review {number}: {finding['pass']}"
    public = public_narrative(public, records)
    projection.add_public_findings(records, public)
    publication = publication_snapshot or default_publication(state, assignment)
    return {"schema": 2, "run": state["id"], "pr": assignment["pr"], "assignment": assignment["id"],
            "stage": assignment["role"], "approval": state["approval"],
            "inputs": [{"role": item["role"], "digest": item["sha256"]}
                       for item in state["manifest"]["artifacts"]],
            "code_commit": assignment["before"]["head"], "snapshot": identity(assignment["before"]),
            "limits": state["manifest"]["limits"], "consumed_assignments": len(state["history"]),
            "history": history, "reviews": records, "public": public,
            "publication": publication, "requested_models": projection.requested_models(state, assignment["pr"]),
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


def contents(bundle):
    return {"audit.json": plan.encode(bundle), "AUDIT.md": render(bundle)}


def bundle_identity(files):
    return identity({name: review.digest(data) for name, data in files.items()})


def export(state, assignment, public):
    bundle = build(state, assignment, public)
    pull = checked_pull(state, assignment, bundle)
    repo, number = target(state, assignment)
    bundle["publication"] = {
        "title": plan.text(pull["title"]), "pr_url": f"https://github.com/{repo}/pull/{number}",
        "head": pull["head"]["sha"], "date": datetime.now(timezone.utc).date().isoformat(),
    }
    page_name(number, bundle["publication"]["title"])
    folder = directory(state, assignment)
    folder.parent.mkdir(exist_ok=True, mode=0o700)
    folder.mkdir(exist_ok=True, mode=0o700)
    files = contents(bundle)
    for name, data in files.items():
        review.atomic_write(review.safe_path(folder, name), data)
    return {"directory": str(folder), "identity": bundle_identity(files),
            "index_url": wiki_index(state), "files": list(FILES)}


def archive_assignment(state, pr):
    plan.require(pr in state["prs"], "Archive requires a known --pr")
    saved = next((item for item in reversed(state["history"])
                  if item["pr"] == pr and item.get("before") is not None), None)
    plan.require(saved is not None, "No saved PR snapshot is available")
    return {**saved, "role": "archive", "before": state["prs"][pr]["accepted"] or saved["before"]}


def accepted_archive_commit(state, pr, *, required=False):
    progress = state["prs"][pr]
    snapshot = progress["accepted"]
    if snapshot is None:
        return None
    for item in reversed(state["history"]):
        if (item["pr"] == pr and item["role"] == "commit" and item["outcome"] == "complete" and
                item["report"]["data"]["commit"] == snapshot["head"] and
                item["before"]["files"] == snapshot["files"]):
            return snapshot["head"]
    snapshot_id = identity(snapshot)
    rebased = next((item for item in reversed(progress.get("review_rebases", []))
                    if item["new_head"] == snapshot["head"] and item["after"] == snapshot_id), None)
    if rebased is not None:
        try:
            tree = command(["git", "--no-replace-objects", "rev-parse", "--verify", "--end-of-options",
                            snapshot["head"] + "^{tree}"], cwd=Path(state["root"])).decode().strip()
        except (plan.ManifestError, OSError, subprocess.TimeoutExpired) as error:
            if required:
                raise plan.ManifestError("Rebase commit evidence is unavailable; restore Git and the retained "
                                         "commit objects, then retry the same archive") from error
            return None
        if tree == rebased["expected_tree"]:
            return snapshot["head"]
    return None


def archive_bundle(state, pr, public, *, model_snapshot=None, require_commit_evidence=False):
    bundle = build(state, archive_assignment(state, pr), public, model_snapshot=model_snapshot)
    bundle["run_outcome"] = state["outcome"]
    bundle["accepted_code_commit"] = accepted_archive_commit(state, pr, required=require_commit_evidence)
    bundle["limitations"].append(
        "Historical evidence: the worktree was not checked. Publication does not establish "
        "current PR review acceptance, readiness, or coverage of later changes.")
    return bundle


def archive_directory(state, pr, key):
    plan.require(pr in state["prs"], "Archive requires a known --pr")
    plan.require(isinstance(key, str) and re.fullmatch(r"[a-f0-9]{64}", key),
                 "Publication approval must identify both exact exported files")
    storage = review.external_run_directory(Path(state["store"]), state["id"], Path(state["root"]))
    return review.external_directory(review.safe_path(storage, f"archives/{pr}/{key}"))


def archive(state, pr, public):
    bundle = archive_bundle(state, pr, public)
    files = contents(bundle)
    key = bundle_identity(files)
    folder = archive_directory(state, pr, key)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name, data in files.items():
        review.atomic_write(review.safe_path(folder, name), data)
    return {"directory": str(folder), "identity": key, "files": list(FILES), "historical": True}


def read_archive(state, pr, approved):
    folder = archive_directory(state, pr, approved)
    plan.require(folder.is_dir(), "Archive unavailable; run archive --pr with the reviewed narrative first")
    files = {name: review.safe_path(folder, name).read_bytes() for name in FILES}
    plan.require(bundle_identity(files) == approved,
                 "Publication approval must identify both exact exported files; export and inspect again")
    bundle = json.loads(files["audit.json"])
    plan.require(bundle["stage"] == "archive" and bundle["run"] == state["id"] and
                 bundle["pr"] == pr and bundle["approval"] == state["approval"] and files == contents(bundle),
                 "Archive does not match this run's approved historical export; export and inspect again")
    return folder, bundle, files


def prepared_archive(state, pr, approved):
    folder, bundle, files = read_archive(state, pr, approved)
    expected = archive_bundle(state, pr, bundle["public"],
                              model_snapshot=(bundle["models"], bundle["models_unavailable"]),
                              require_commit_evidence=True)
    plan.require(bundle == expected and files == contents(bundle),
                 "Archive evidence changed; run archive again and inspect both new files before publishing")
    plan.require(bundle["accepted_code_commit"] == bundle["code_commit"],
                 "No accepted code commit is established for this snapshot. Keep the local archive; "
                 "complete the accepted commit handoff, restore retained Git objects for rebase evidence, "
                 "or reconcile the PR's review within its approved allowances before publishing")
    return folder, bundle, files


def prepared(state, assignment):
    folder = directory(state, assignment)
    files = {name: review.safe_path(folder, name).read_bytes() for name in FILES}
    bundle = json.loads(files["audit.json"])
    plan.require(bundle.get("schema") == 2,
                 "Audit export uses an older format; regenerate and review it before publishing")
    publication = bundle["publication"]
    plan.fields(publication, "title pr_url head date")
    repo, number = target(state, assignment)
    plan.require(publication["head"] == assignment["before"]["head"] and
                 match_repository_url(publication["pr_url"], repo, f"pull/{number}") and
                 re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", publication["date"]) and
                 timestamp(publication["date"]) is not None,
                 "Audit publication metadata changed; regenerate and review the export")
    expected = build(state, assignment, bundle["public"],
                     model_snapshot=(bundle["models"], bundle["models_unavailable"]),
                     publication_snapshot=bundle["publication"])
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
    recorded = state["prs"][assignment["pr"]]["url"]
    url = assignment.get("pr_url") or recorded
    match = match_repository_url(url, repo, r"pull/([1-9][0-9]*)")
    plan.require(match is not None, "Audit must attach to this run's PR in the approved repository; "
                 "if its URL was not recorded, supply --pull-request https://github.com/OWNER/REPO/pull/NUMBER")
    previous = match_repository_url(recorded, repo, r"pull/([1-9][0-9]*)") if recorded else None
    plan.require(not recorded or (previous is not None and previous[1] == match[1]),
                 "Preserve the recorded PR target; --pull-request cannot replace this run's PR")
    return repo, match[1]


def default_publication(state, assignment):
    try:
        repo, number = target(state, assignment)
        url = f"https://github.com/{repo}/pull/{number}"
    except plan.ManifestError:
        url = None
    return {"title": "Development process audit", "pr_url": url, "head": None,
            "date": datetime.now(timezone.utc).date().isoformat()}


def page_name(number, title):
    title = " ".join(plan.text(title).split())
    word = re.match(r"[A-Za-z]+", title)
    if word and not any(char.isupper() for char in word[0][1:]):
        title = title[:1].lower() + title[1:]
    title = re.sub(r'[\\/*?"<>|\x00-\x1f\x7f]', " ", title).replace("-", chr(0x2010))
    title = "-".join(title.split())
    title = title.encode("utf-8")[:180].decode("utf-8", errors="ignore").rstrip("-.")
    plan.require(bool(title), "Use a PR title with readable text before exporting an audit")
    return f"Audit:-PR-#{number},-{title}"


def publication_links(state, assignment, title):
    repo, number = target(state, assignment)
    page = page_name(number, title)
    url = f"https://github.com/{repo}/wiki/{quote(page, safe=':,')}"
    return {"page": page, "url": url, "data_url": url + ".json",
            "index_url": wiki_index(state), "pr_url": f"https://github.com/{repo}/pull/{number}"}


def audit_links(publication):
    return (f"[Report]({publication['url']}) &#183; [Data (audit.json)]({publication['data_url']})"
            f" &#183; [Automated Pull Request Audits]({publication['index_url']})")


def index_html_block_end(line, paragraph):
    starts = (
        (r"(?i:<(?:script|pre|style)(?=[ >]|$))", r"(?i:</(?:script|pre|style)>)"),
        (r"<!--", r"-->"), (r"<\?", r"\?>"),
        (r"<![A-Z]", r">"), (r"<!\[CDATA\[", r"\]\]>"),
    )
    for opening, ending in starts:
        if re.match(r" {0,3}" + opening, line):
            return ending
    block_tags = (
        "address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|"
        "details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|"
        "h[1-6]|head|header|hr|html|iframe|legend|li|link|main|menu|menuitem|nav|noframes|ol|"
        "optgroup|option|p|param|section|source|summary|table|tbody|td|tfoot|th|thead|title|tr|track|ul"
    )
    if re.match(r" {0,3}(?i:</?(?:" + block_tags + r")(?=[ >]|/>|$))", line):
        return r"^ *$"
    value = r"""(?:[^ "'=<>`]+|'[^']*'|"[^"]*")"""
    attribute = r" +[A-Za-z_:][A-Za-z0-9_.:-]*(?: *= *" + value + r")?"
    tag = r"(?:<[A-Za-z][A-Za-z0-9-]*(?:" + attribute + r")* */?>|</[A-Za-z][A-Za-z0-9-]* *>)"
    if not paragraph and re.fullmatch(r" {0,3}" + tag + r" *", line):
        return r"^ *$"
    return None


def index_list_indent(line, paragraph):
    marker = re.match(r" {0,3}(?:[-+*]|([0-9]{1,9})[.)])( +|$)", line)
    if marker is None or (paragraph and (marker[1] not in (None, "1") or not line[marker.end():])):
        return None
    padding = len(marker[2])
    return marker.end() if 1 <= padding <= 4 else marker.end() - padding + 1


class IndexBlock:
    def __init__(self):
        self.fence = None
        self.html_end = None
        self.list_indent = None
        self.child = None
        self.paragraph = False

    def container_line(self, line):
        if self.list_indent is not None:
            if not line.strip(" ") or len(line) - len(line.lstrip(" ")) >= self.list_indent:
                return line[self.list_indent:]
            return None
        quote = re.match(r" {0,3}> ?", line)
        return line[quote.end():] if quote else None

    def header(self, line):
        marker = re.fullmatch(r" {0,3}(`{3,}|~{3,})(.*)", line)
        if self.fence is not None:
            if (marker and marker[1][0] == self.fence[0] and len(marker[1]) >= len(self.fence)
                    and not marker[2].strip(" ")):
                self.fence = None
            return False
        if self.html_end is not None:
            if re.search(self.html_end, line):
                self.html_end = None
            return False
        if self.child is not None:
            content = self.container_line(line)
            if content is not None:
                self.child.header(content)
                self.paragraph = self.child.paragraph
                return False
            self.child = None
            self.list_indent = None
        if re.fullmatch(r" {0,3}(?:(?:\* *){3,}|(?:- *){3,}|(?:_ *){3,})", line):
            self.paragraph = False
            return False
        self.list_indent = index_list_indent(line, self.paragraph)
        quote = re.match(r" {0,3}> ?", line)
        if self.list_indent is not None or quote:
            self.child = IndexBlock()
            self.child.header(line[self.list_indent:] if self.list_indent is not None else line[quote.end():])
            self.paragraph = self.child.paragraph
            return False
        self.html_end = index_html_block_end(line, self.paragraph)
        if self.html_end is not None:
            if re.search(self.html_end, line):
                self.html_end = None
            self.paragraph = False
            return False
        if marker and (marker[1][0] == "~" or "`" not in marker[2]):
            self.fence = marker[1]
            self.paragraph = False
            return False
        heading = re.match(r" {0,3}#{1,6}(?: |$)", line) or (
            self.paragraph and re.fullmatch(r" {0,3}=+ *", line))
        reference = not self.paragraph and re.fullmatch(
            r""" {0,3}\[(?:\\.|[^\]\\])+\]: *(?:<[^<>]*>|[^ <>\t]+)"""
            r"""(?: +(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\((?:\\.|[^)\\])*\)))? *""", line)
        self.paragraph = bool(line.strip(" ") and (self.paragraph or not line.startswith("    ")) and
                              not (heading or reference))
        return bool(re.fullmatch(r"\|\s*Date\s*\|\s*Pull request\s*\|\s*Audit records\s*\|", line.rstrip()))


def index_table_headers(lines):
    block = IndexBlock()
    return [index for index, line in enumerate(lines) if block.header(line.expandtabs(4).rstrip("\r\n"))]


def index_table(text, publication):
    lines = text.splitlines(keepends=True)
    headers = index_table_headers(lines)
    plan.require(len(headers) == 1, "Preserve the wiki index and restore one unindented Date / Pull request / "
                 "Audit records table outside fenced code blocks and HTML blocks before retrying")
    start = headers[0] + 1
    plan.require(start < len(lines) and re.fullmatch(r"\|(?:\s*:?-{3,}:?\s*\|){3}", lines[start].strip()),
                 "Preserve the wiki index and repair its audit table separator before retrying")
    start += 1
    end = start
    while end < len(lines) and lines[end].lstrip().startswith("|"):
        end += 1
    destination = re.escape(publication["pr_url"])
    pr_cell = (r"^\|[^|]*\|\s*\[(?:\\.|[^\]\\])*\]\("
               + rf"(?:{destination}|<{destination}>)\)\s*\|")
    matches = [i for i in range(start, end) if re.match(pr_cell, lines[i], re.IGNORECASE)]
    plan.require(len(matches) <= 1, "Preserve duplicate wiki audit records and consolidate this PR's row before retrying")
    return lines, start, matches


def index_entry(text, publication, *, unchanged=False):
    lines, start, matches = index_table(text, publication)
    title = html.escape(" ".join(publication["title"].split()), quote=False).replace("|", "&#124;")
    title = re.sub(r"([\\`*_\[\]])", r"\\\1", title)
    number = publication["pr_url"].rsplit("/", 1)[1]
    date = publication.get("date") or datetime.now(timezone.utc).date().isoformat()
    row = (f"| {date} | [#{number} {title}]({publication['pr_url']}) | "
           f"[Report]({publication['url']}) &#183; [Data (audit.json)]({publication['data_url']}) |\n")
    if matches and unchanged and lines[matches[0]].strip() == row.strip():
        return text
    if matches:
        del lines[matches[0]]
    lines[start - 1] = lines[start - 1].rstrip("\r\n") + "\n"
    lines.insert(start, row)
    return "".join(lines)


def home_visible_text(text, *, markers=False):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    hidden = (r"^ {0,3}(?P<backticks>`{3,})[^`\n]*\n.*?"
              r"(?:(?P<backtick_end>^ {0,3}(?P=backticks)`*[ \t]*$)|\Z)|"
              r"^ {0,3}(?P<tildes>~{3,})[^\n]*\n.*?"
              r"(?:(?P<tilde_end>^ {0,3}(?P=tildes)~*[ \t]*$)|\Z)|"
              r"(?P<comment><!--).*?(?:(?P<comment_end>-->)|\Z)|"
              r"(?P<reference>" + HOME_REFERENCE + r")|"
              r"(?<!`)(?P<inline>`+)(?!`).*?(?<!`)(?P=inline)(?!`)|"
              r"^(?: {4}|\t)[^\n]*$")
    closed = True

    def mask(match):
        nonlocal closed
        if match["reference"] is not None and not markers:
            return match[0]
        if markers and match["comment"] and match[0] in (HOME_START, HOME_END):
            return match[0]
        if ((match["backticks"] and not match["backtick_end"]) or
                (match["tildes"] and not match["tilde_end"]) or
                (match["comment"] and not match["comment_end"])):
            closed = False
        return re.sub(r"[^\n]", " ", match[0])

    visible = re.sub(hidden, mask, text, flags=re.MULTILINE | re.DOTALL)
    return visible, closed


def markdown_escaped(text, offset):
    return (offset - len(text[:offset].rstrip("\\"))) % 2 == 1


def home_link_destinations(visible):
    definitions = {}
    definition_end = -1

    def retain_definition(match):
        nonlocal definition_end
        previous_end = match.start() - 1
        previous = visible[visible.rfind("\n", 0, previous_end) + 1:previous_end]
        block_end = re.fullmatch(r" {0,3}(?:#{1,6}(?:[ \t]+.*)?|"
                                r"(?P<rule>[-*_])(?:[ \t]*(?P=rule)){2,}|[=-]+)[ \t]*", previous)
        if match.start() and previous.strip() and previous_end != definition_end and not block_end:
            return match[0]
        definition_end = match.end()
        label = " ".join(match[1].split()).casefold()
        definitions.setdefault(label, match[2] or match[3])
        return "\n" * match[0].count("\n")

    visible = re.sub(HOME_REFERENCE, retain_definition, visible, flags=re.MULTILINE)
    link = re.compile(r'(!?)\[([^\]\n]+)\](?:'
                      r'\(\s*<?([^>\s)]+)>?(?:\s+' + HOME_TITLE + r')?\s*\)|'
                      r'\[([^\]\n]*)\])?')
    offset = 0
    while match := link.search(visible, offset):
        offset = match.end()
        if markdown_escaped(visible, match.start() + len(match[1])):
            offset = match.start() + len(match[1]) + 1
            continue
        if match[1] and not markdown_escaped(visible, match.start()):
            continue
        if match[3] is not None:
            yield match[3]
        else:
            label = " ".join((match[4] or match[2]).split()).casefold()
            if label in definitions:
                yield definitions[label]


def home_has_index_link(text, index_url):
    visible, _ = home_visible_text(text)
    repo = repository(index_url.split("/wiki/")[0])
    for destination in home_link_destinations(visible):
        path = destination.split("#", 1)[0]
        if path in (INDEX_PAGE, "./" + INDEX_PAGE) or match_repository_url(path, repo, f"wiki/{INDEX_PAGE}"):
            return True
    wiki_links = re.finditer(r"\[\[" + re.escape(INDEX_PAGE) + r"(?:\|[^|\]\n]+)?\]\]", visible)
    return any(not markdown_escaped(visible, match.start()) for match in wiki_links)


def home_page(text, index_url):
    link = f"[Automated Pull Request Audits]({index_url})"
    markers, _ = home_visible_text(text, markers=True)
    if HOME_START in markers or HOME_END in markers:
        plan.require(markers.count(HOME_START) == markers.count(HOME_END) == 1,
                     "Preserve Home content and restore one managed audit-index link block before retrying")
        start, end = markers.index(HOME_START), markers.index(HOME_END)
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        plan.require(end > start and normalized[start + len(HOME_START):end].strip() == link,
                     "Home audit-index block was edited; preserve manual text outside the block before retrying")
        plan.require(home_has_index_link(text, index_url),
                     "Move the Home audit-index block outside code or comments before retrying")
        return text
    if home_has_index_link(text, index_url):
        return text
    _, closed = home_visible_text(text)
    plan.require(closed, "Preserve Home content and close its unfinished code or comment block before retrying")
    separator = "" if not text else ("\n" if text.endswith("\n") else "\n\n")
    updated = text + separator + f"{HOME_START}\n{link}\n{HOME_END}\n"
    plan.require(home_has_index_link(updated, index_url),
                 "Preserve Home content and close its unfinished code or comment block before retrying")
    return updated


def wiki_pages(root, parent, publication):
    filenames = (publication["page"] + ".md", publication["page"] + ".json",
                 INDEX_PAGE + ".md", "Home.md", "Home.markdown")
    entries = command(["git", "ls-tree", "-z", parent], cwd=root)
    pages = {}
    for entry in entries.split(b"\0")[:-1]:
        metadata, name = entry.split(b"\t", 1)
        filename = name.decode("utf-8", "surrogateescape")
        if filename not in filenames and not audit_page_names((Path(filename),), publication):
            continue
        plan.require(metadata.startswith(b"100644 blob "),
                     "Preserve the wiki and restore regular page files before retrying")
        pages[filename] = command(["git", "show", f"{parent}:{filename}"], cwd=root)
    return pages


def audit_page_names(entries, publication):
    number = publication["pr_url"].rsplit("/", 1)[1]
    pattern = rf"(?:Audit:-PR-\#{number},-.+|Audit-PR-{number}-run-[a-f0-9]{{32}}-A[0-9]+-[a-f0-9]{{64}})"
    return {entry.stem for entry in entries
            if entry.suffix in (".md", ".json") and re.fullmatch(pattern, entry.stem)}


def previous_pages(root, publication):
    pages = audit_page_names(root.iterdir(), publication)
    for page in sorted(pages):
        data = review.safe_path(root, page + ".json")
        report = review.safe_path(root, page + ".md")
        plan.require(data.is_file() and report.is_file(),
                     "Audit page lacks its matching report/data pair; restore the pair from wiki history before retrying")
        try:
            old = json.loads(data.read_bytes())
        except (ValueError, OSError) as error:
            raise plan.ManifestError("Existing audit data is unreadable; restore its JSON from wiki history "
                                     "or preserve the pair under another page name before retrying") from error
        plan.require(isinstance(old, dict) and old.get("schema") in (1, 2) and
                     old.get("stage") in (*ROLES, "archive") and
                     isinstance(old.get("run"), str) and re.fullmatch(r"[a-f0-9]{32}", old["run"]),
                     "Existing page is not a recognized audit; preserve it under another page name before retrying")
        if page.startswith("Audit:-PR-"):
            plan.require(old["schema"] == 2,
                         "Title-based audit lacks PR ownership metadata; restore its schema-2 data from wiki "
                         "history or preserve the pair under another page name before retrying")
        if old["schema"] == 2:
            metadata = old.get("publication")
            plan.require(isinstance(metadata, dict) and isinstance(metadata.get("pr_url"), str) and
                         metadata["pr_url"].casefold() ==
                         publication["pr_url"].casefold(),
                         "Existing audit belongs to another PR; preserve it under another page name before retrying")
    return pages


def approved_files_present(root, publication, files):
    for extension, source in ((".md", "AUDIT.md"), (".json", "audit.json")):
        path = review.safe_path(root, publication["page"] + extension)
        if not path.is_file() or path.read_bytes() != files[source]:
            return False
    return True


def wiki_files(root, publication, files):
    expected = {publication["page"] + ".md": files["AUDIT.md"],
                publication["page"] + ".json": files["audit.json"]}
    previous = previous_pages(root, publication)
    unchanged = previous == {publication["page"]} and approved_files_present(root, publication, files)
    for page in previous - {publication["page"]}:
        expected[page + ".md"] = None
        expected[page + ".json"] = None
    path = review.safe_path(root, INDEX_PAGE + ".md")
    text = (path.read_text() if path.exists() else
            "Development process audit records, one row per pull request. Newest first.\n\n"
            f"{INDEX_HEADER}\n{INDEX_SEPARATOR}\n")
    expected[path.name] = index_entry(text, publication, unchanged=unchanged).encode()
    homes = [name for name in ("Home.md", "Home.markdown") if (root / name).exists()] or ["Home.md"]
    for name in homes:
        path = review.safe_path(root, name)
        text = path.read_text() if path.exists() else ""
        expected[name] = home_page(text, publication["index_url"]).encode()
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
        if data is None:
            plan.require(not entry, f"Git retained superseded audit {filename}; inspect hooks before retrying")
            continue
        plan.require(entry.startswith(b"100644 blob ") and
                     command(["git", "show", f"{commit}:{filename}"], cwd=root) == data,
                     f"Git changed approved wiki bytes for {filename}; inspect filters/hooks before retrying")
    return commit


def published_index_matches(content, publication):
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return index_entry(text, publication, unchanged=True) == text


def confirm_publication(root, publication, expected):
    commit = command(["git", "rev-parse", "FETCH_HEAD"], cwd=root).decode().strip()
    for filename, data in expected.items():
        entry = command(["git", "--literal-pathspecs", "ls-tree", commit, "--", filename], cwd=root)
        if data is None:
            plan.require(not entry, f"Superseded audit reappeared at {filename}; inspect the wiki and retry "
                         "the reviewed export to remove superseded pages")
            continue
        is_index = filename == INDEX_PAGE + ".md"
        message = ("Published audit index changed; restore an unreadable index from wiki history or retry "
                   "the reviewed export to repair this PR's entry, preserving unrelated content" if is_index else
                   "Published audit pair changed; restore the approved pair from wiki history or preserve "
                   "conflicting pages, then retry the reviewed export")
        plan.require(entry.startswith(b"100644 blob "), message)
        content = command(["git", "show", f"{commit}:{filename}"], cwd=root)
        matches = published_index_matches(content, publication) if is_index else content == data
        plan.require(matches, message)
    names = command(["git", "ls-tree", "--full-tree", "--name-only", "-z", commit], cwd=root)
    pages = audit_page_names((Path(name) for name in names.decode("utf-8", "surrogateescape").split("\0")[:-1]),
                             publication)
    plan.require(not (pages - {publication["page"]}),
                 "Superseded audit reappeared; inspect the wiki, restore any incomplete report/data pairs "
                 "or preserve conflicting pages under other names, then retry the reviewed export")
    return commit


def check_publication_date(publication, already_published):
    plan.require(already_published or publication["date"] == datetime.now(timezone.utc).date().isoformat(),
                 "Publication day changed; regenerate and review an export for today's UTC date")


def publish_files(state, publication, files, *, storage=None, recovery=None):
    url = state["manifest"]["repository"]["url"]
    remote = url.removesuffix(".git") + ".wiki.git"
    with tempfile.TemporaryDirectory(prefix="audit-publish-", dir=storage or state["store"]) as temporary:
        root = Path(temporary)
        command(["git", "init", "-q", "-b", "wiki"], cwd=root)
        command(["git", "config", "user.name", "Autonomous development audit"], cwd=root)
        command(["git", "config", "user.email", "audit@users.noreply.github.com"], cwd=root)
        command(["git", "config", "--add", "credential.https://github.com.helper", ""], cwd=root)
        command(["git", "config", "--add", "credential.https://github.com.helper",
                 "!gh auth git-credential"], cwd=root)
        for attempt in range(3):
            ref, parent = wiki_head(root, remote)
            pages = wiki_pages(root, parent, publication)
            # Checkout filters must not change the source bytes used for publication.
            for filename, data in pages.items():
                review.atomic_write(review.safe_path(root, filename), data)
            expected = wiki_files(root, publication, files)
            if recovery is not None:
                archive_wiki_recovery(recovery, publication, pages, expected)
            already_published = approved_files_present(root, publication, files)
            check_publication_date(publication, already_published)
            deletions = [name for name, data in expected.items() if data is None]
            writes = {name: data for name, data in expected.items() if data is not None}
            # Stage removals before writes so old spellings cannot alias replacements.
            if deletions:
                command(["git", "--literal-pathspecs", "rm", "-q", "--", *deletions], cwd=root)
            for filename, data in writes.items():
                review.atomic_write(review.safe_path(root, filename), data)
            command(["git", "--literal-pathspecs", "add", "--", *writes], cwd=root)
            if not command(["git", "diff", "--cached", "--name-only"], cwd=root).strip():
                return verify_wiki_commit(root, parent, expected)
            command(["git", "commit", "-qm", "docs: publish development process audit"], cwd=root)
            commit = verify_wiki_commit(root, parent, expected)
            check_publication_date(publication, already_published)
            try:
                command(["git", "push", "--no-follow-tags", remote, f"{commit}:{ref}"], cwd=root)
            except plan.ManifestError:
                observed = command(["git", "ls-remote", "--refs", remote, ref], cwd=root).decode().split()
                if not observed or observed[0] == parent:
                    raise
                continue
            command(["git", "fetch", "-q", "--no-tags", remote, ref], cwd=root)
            command(["git", "merge-base", "--is-ancestor", commit, "FETCH_HEAD"], cwd=root)
            return confirm_publication(root, publication, expected)
    raise plan.ManifestError("Wiki kept changing during publication; retry the same export without force-pushing")


def pr_body(body, publication):
    block = f"{LINK_START}\n{audit_links(publication)}\n{LINK_END}"
    if LINK_START in body or LINK_END in body:
        plan.require(body.count(LINK_START) == body.count(LINK_END) == 1,
                     "Preserve PR text and restore one audit link block before retrying")
        start, end = body.index(LINK_START), body.index(LINK_END)
        previous = body[start + len(LINK_START):end].strip()
        match = re.match(r"\[Report\]\((https://github\.com/[^)\s]+/wiki/"
                         r"(?:Audit-PR-|Audit:-PR-%23)[^)\s#]+)\)", previous)
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
    plan.require(pull["state"] == "open", "Audit publication requires an open PR; keep the local archive")
    plan.require(pull["head"]["ref"] == pr["branch"] and
                 (pull["head"]["repo"] or {}).get("full_name", "").casefold() == repo.casefold() and
                 (pull["base"]["repo"] or {}).get("full_name", "").casefold() == repo.casefold() and
                 match_repository_url(pull.get("html_url"), repo, rf"pull/{number}"),
                 "Publish the accepted implementation commit only to the run's owned branch and repository")
    plan.require(pull["head"]["sha"] == bundle["code_commit"],
                 f"PR head {pull['head']['sha']} differs from the accepted implementation commit "
                 f"{bundle['code_commit']}. Do not relabel the archive or force-push. Reconcile the review "
                 "within approved allowances (rebase-review for an identical target rebase), then export "
                 "and inspect new evidence; otherwise retain the local archive")
    if "publication" in bundle and bundle["publication"]["head"] is not None:
        plan.require(pull["title"] == bundle["publication"]["title"],
                     "PR title changed; regenerate and review the audit export before publishing")
    return pull


def publish_bundle(state, assignment, payload, *, storage=None, recovery=None):
    bundle, files = payload
    exported = bundle_identity(files)
    repo, number = target(state, assignment)
    pull = checked_pull(state, assignment, bundle)
    publication = publication_links(state, assignment, bundle["publication"]["title"])
    pr_body(pull.get("body") or "", publication)
    if recovery is not None:
        archive_pr_recovery(recovery, publication, pull.get("body") or "")
    commit = publish_files(state, {**publication, "title": bundle["publication"]["title"],
                                   "date": bundle["publication"]["date"]}, files,
                           storage=storage, recovery=recovery)
    pull = checked_pull(state, assignment, bundle)
    original = pull.get("body") or ""
    body = pr_body(original, publication)
    if recovery is not None:
        archive_pr_recovery(recovery, publication, original)
    if body != original:
        api(f"repos/{repo}/pulls/{number}", method="PATCH", data={"body": body})
    observed = checked_pull(state, assignment, bundle)
    plan.require(observed.get("body") == body, "PR audit links were not confirmed; reread the PR and retry")
    return {"stage": assignment["role"], "code_commit": bundle["code_commit"],
            "bundle": exported, "wiki_commit": commit,
            **{key: value for key, value in publication.items() if key != "page"}}


def publish(state, assignment, approved):
    payload = prepared(state, assignment)
    plan.require(approved == bundle_identity(payload[1]),
                 "Publication approval must identify both exact exported files")
    result = publish_bundle(state, assignment, payload)
    review.atomic_write(directory(state, assignment) / "receipt.json", plan.encode(result))
    return result


def archive_receipt(state, publication, payload):
    bundle, receipt = payload
    plan.fields(receipt, "stage code_commit bundle wiki_commit url data_url index_url pr_url authorization")
    expected = {key: value for key, value in publication.items() if key != "page"}
    expected.update(stage="archive", code_commit=bundle["code_commit"],
                    authorization={"approval": state["approval"], "permission": "publish_audit"})
    plan.require(all(receipt[key] == value for key, value in expected.items()) and
                 bundle["accepted_code_commit"] == receipt["code_commit"] and
                 isinstance(receipt["code_commit"], str) and
                 re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", receipt["code_commit"]) and
                 isinstance(receipt["wiki_commit"], str) and
                 re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", receipt["wiki_commit"]),
                 "Archive receipt does not match the approved bundle, target and authorization. "
                 "Preserve it; use --republish only when intentionally restoring this archive")
    return receipt


def archive_recovery(folder, binding, *, republish):
    path = review.safe_path(folder, "publication-attempt.json")
    record = None
    if path.exists() and not republish:
        record = json.loads(path.read_bytes())
        plan.fields(record, "bundle pr_url approval before")
        plan.fields(record["before"], "pr wiki")
        plan.require(all(record[key] == value for key, value in binding.items()) and
                     all(isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value)
                         for value in record["before"].values()),
                     "Archive attempt does not match the approved publication; preserve it and use "
                     "--republish only when intentionally restoring this archive")
    return {"path": path, "binding": binding, "record": record, "republish": republish}


def require_archive_navigation(allowed):
    plan.require(allowed, "Archive publication is partial or superseded; newer wiki or PR navigation was "
                 "preserved. Inspect both remote effects and retain the archive. Use --republish only "
                 "when intentionally restoring this exact approved archive; otherwise keep the newer audit")


def archive_pr_recovery(recovery, publication, body):
    matches = pr_body(body, publication) == body
    block = (body[body.index(LINK_START):body.index(LINK_END) + len(LINK_END)]
             if LINK_START in body else "")
    current = review.digest(block.encode())
    if recovery["record"] is not None:
        require_archive_navigation(matches or current == recovery["record"]["before"]["pr"])
    recovery["pr"] = current
    recovery["pr_matches"] = matches


def archive_wiki_recovery(recovery, publication, pages, expected):
    index = INDEX_PAGE + ".md"
    text = pages.get(index, b"").decode()
    row = ""
    if text:
        lines, _, matches = index_table(text, publication)
        row = lines[matches[0]] if matches else ""
    current = review.digest(row.encode())
    matches = pages.get(index) == expected[index]
    if recovery["record"] is None:
        existing = any(publication["page"] + suffix in pages for suffix in (".md", ".json"))
        require_archive_navigation(recovery["republish"] or not existing or
                                   (matches and recovery["pr_matches"]))
        record = {**recovery["binding"], "before": {"pr": recovery["pr"], "wiki": current}}
        review.atomic_write(recovery["path"], plan.encode(record))
        recovery["record"] = record
    require_archive_navigation(matches or current == recovery["record"]["before"]["wiki"])


def publish_archive(state, pr, approved, *, pull_request=None, republish=False):
    folder = archive_directory(state, pr, approved)
    receipt = review.safe_path(folder, "receipt.json")
    acknowledge = receipt.exists() and not republish
    loader = read_archive if acknowledge else prepared_archive
    folder, bundle, files = loader(state, pr, approved)
    assignment = {"id": bundle["assignment"], "role": "archive", "pr": pr, "pr_url": pull_request}
    publication = publication_links(state, assignment, approved)
    if acknowledge:
        return archive_receipt(state, {**publication, "bundle": approved},
                               (bundle, json.loads(receipt.read_bytes())))
    recovery = archive_recovery(folder, {"bundle": approved, "pr_url": publication["pr_url"],
                                        "approval": state["approval"]}, republish=republish)
    result = publish_bundle(state, assignment, (bundle, files), storage=folder, recovery=recovery)
    result["authorization"] = {"approval": state["approval"], "permission": "publish_audit"}
    review.atomic_write(receipt, plan.encode(result))
    return result


def validate_receipt(state, assignment, data):
    bundle, files = prepared(state, assignment)
    receipt = json.loads(review.safe_path(directory(state, assignment), "receipt.json").read_bytes())
    exported = bundle_identity(files)
    publication = publication_links(state, assignment, bundle["publication"]["title"])
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
    cli.add_argument("operation", choices=("export", "publish", "archive", "publish-archive"))
    cli.add_argument("store")
    cli.add_argument("--public", help="Publication-reviewed narrative JSON, required for export and archive")
    cli.add_argument("--approved", help="Exact bundle identity, required for publish and publish-archive")
    cli.add_argument("--pr", help="PR plan ID, required for archive and publish-archive")
    cli.add_argument("--pull-request", help="Existing PR URL for publish-archive when the run did not record it")
    cli.add_argument("--republish", action="store_true",
                     help="Intentionally restore an approved archive's navigation, rather than acknowledge a retry")
    args = cli.parse_args()
    try:
        plan.require(args.pull_request is None or args.operation == "publish-archive",
                     "--pull-request is supported only by publish-archive")
        plan.require(not args.republish or args.operation == "publish-archive",
                     "--republish is supported only by publish-archive")
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
            if args.operation == "publish-archive":
                development.permission(state["manifest"], "audit-initial")
                result = publish_archive(state, args.pr, args.approved,
                                         pull_request=args.pull_request, republish=args.republish)
                print(json.dumps(result, indent=2))
                return 0
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
