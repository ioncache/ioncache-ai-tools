"""Render the publication-safe audit projection without reading private evidence."""

from collections import Counter, defaultdict
import html
import re

import development_manifest as plan


STATUS = {
    ("valid", "open"): "Confirmed, to be fixed",
    ("valid", "fixed"): "Confirmed, fixed",
    ("valid", "out_of_scope"): "Confirmed, outside this PR",
    ("valid", "ignored"): "Confirmed, no change needed",
    ("invalid", "ignored"): "Rejected, not a defect",
    ("valid", "fix_applied"): "Confirmed, fix awaiting verification",
    ("valid", "fix_failed"): "Confirmed, fix failed",
}
SECTIONS = (
    ("fixed", "Fixed", "Real problems found and corrected in this PR."),
    ("outside", "Real problems not fixed in this PR",
     "Confirmed problems left outside this PR or still awaiting a verified correction."),
    ("no_change", "Accurate observations, no change needed",
     "True observations judged not to require a change, with the recorded reason."),
    ("rejected", "Rejected", "Claims judged not to be defects, including rejected duplicates."),
    ("unresolved", "Unresolved findings", "Claims whose validity has not been established."),
)
MODEL_STAGES = (
    ("Implementation and fixes", ("implement", "fixer")),
    ("Review and judgment", ("reviewer", "adjudicator", "validator")),
    ("Review coordination", ("review-owner",)),
    ("Setup and delivery", ("preflight", "prepare", "commit", "draft", "ready",
                            "evidence", "audit-initial", "audit-final", "development-control")),
)
ROLE_NAMES = {
    "implement": "Implementer", "fixer": "Fixer", "reviewer": "Category reviewers",
    "adjudicator": "Adjudicator", "validator": "Validator", "review-owner": "Review owner",
    "preflight": "Host checks (preflight)", "prepare": "Worktree and branch setup (prepare)",
    "commit": "Commit", "draft": "Draft PR", "ready": "Readiness",
    "evidence": "UI evidence", "audit-initial": "Initial audit", "audit-final": "Final audit",
    "development-control": "Run bookkeeping",
}


def text(value):
    value = html.escape(" ".join(str(value).split()), quote=False)
    return re.sub(r"([\\`*_\[\]#|])", r"\\\1", value)


def code(value):
    fence = "`" * (1 + max((len(part) for part in re.findall(r"`+", value)), default=0))
    return f"{fence} {value} {fence}" if "`" in value else f"`{value}`"


def table(headers, rows):
    return ["| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
            *("| " + " | ".join(row) + " |" for row in rows), ""]


def status(item):
    label = STATUS.get((item["validation"], item["disposition"]))
    if label:
        return label
    if item["validation"] == "invalid":
        return "Rejected, not a defect"
    return "Uncertain, needs assessment" if item["validation"] == "uncertain" else "Not yet assessed"


def group(item):
    if item["validation"] == "invalid":
        return "rejected"
    if item["validation"] != "valid":
        return "unresolved"
    return {"fixed": "fixed", "ignored": "no_change"}.get(item["disposition"], "outside")


def first_sentence(value):
    parts = re.split(r"(?<=[.;])\s+(?=[A-Z(])", value.strip(), maxsplit=1)
    return parts[0].rstrip(";")


def human_title(key):
    key = re.split(r"[/:]", key)[-1]
    key = re.sub(r"^(?:security|perf|performance|privacy|comments|unit-tests|test-coverage|"
                 r"code-complexity|design-coherence|documentation|correctness|integration)-", "", key)
    words = key.replace("_", " ").replace("-", " ").split()
    aliases = {"pr": "PR", "prs": "PRs", "json": "JSON", "api": "API", "cli": "CLI",
               "url": "URL", "urls": "URLs", "html": "HTML", "cwd": "working directory",
               "vs": "versus"}
    result = " ".join(aliases.get(word.lower(), word) for word in words)
    return result[:1].upper() + result[1:]


def category_name(value):
    return value.removeprefix("project:").replace("-", " ").capitalize()


def findings(bundle):
    result = []
    for record in bundle["reviews"]:
        for item in record.get("findings", []):
            result.append({**item, "review": record["id"], "number": len(result) + 1})
    return result


def issue_link(url, repo):
    parts = url.split("/")
    owner = "/".join(parts[3:5])
    label = f"#{parts[-1]}" if owner.casefold() == repo.casefold() else f"{owner}#{parts[-1]}"
    return f"[{label}]({url})"


def finding_entry(item, repo):
    categories = ", ".join(category_name(value) for value in item["category"]) or "Category unavailable"
    line = (f"**{status(item)}** &#183; {item['severity'].lower()} impact &#183; "
            f"{text(categories)} &#183; found in: {text(item['pass'])}")
    if item["tracking_issues"]:
        line += " &#183; tracked in " + ", ".join(issue_link(url, repo) for url in item["tracking_issues"])
    lines = [f"#### Finding {item['number']}: {text(item['title'])}", "", line, "",
             f"**What was reported:** {text(item['summary'])}", ""]
    if group(item) == "fixed":
        initial = item["decisions"][0]["reason"] if item["decisions"] else item["reason"]
        lines += [f"**Why it mattered:** {text(first_sentence(initial))}", "",
                  f"**How it was fixed:** {text(item['reason'])}", ""]
    else:
        lines += [f"**Why:** {text(item['reason'])}", ""]
    if item["locations"] and group(item) != "rejected":
        lines += ["**Where:** " + "; ".join(code(value) for value in item["locations"][:4]) +
                  (" and more" if len(item["locations"]) > 4 else ""), ""]
    lines += ["<details><summary>Full decision history</summary>", ""]
    for index, decision in enumerate(item["decisions"]):
        label = "Initial decision" if index == 0 else "Then"
        lines += [f"- {label}: {status(decision)}. {text(decision['reason'])}", ""]
    if not item["decisions"]:
        lines += ["No adjudication decision was recorded.", ""]
    lines += ["</details>", ""]
    return lines


def outcome_rows(items):
    counts = Counter(group(item) for item in items)
    rows = [
        ["Fixed", str(counts["fixed"]), "Confirmed problems with verified corrections"],
        ["Real but not fixed here", str(counts["outside"]), "Confirmed problems without a verified correction here"],
        ["Accurate with no change needed", str(counts["no_change"]), "Confirmed observations explicitly left unchanged"],
        ["Rejected", str(counts["rejected"]), "Claims judged not to be defects"],
    ]
    if counts["unresolved"]:
        rows.append(["Unresolved", str(counts["unresolved"]), "Validity has not been established"])
    rows.append(["**Total**", f"**{len(items)}**", "Available recorded findings only"])
    return rows


def review_rows(bundle):
    rows = []
    for number, record in enumerate(bundle["reviews"], 1):
        prefix = f"Review {number}: " if len(bundle["reviews"]) > 1 else ""
        if not record["available"]:
            rows.append([prefix + "Unavailable", "Recorded review history", "Not reconstructed"])
        for phase in record.get("passes", []):
            label = prefix + phase["name"]
            if phase["kind"] == "fix":
                results = Counter(phase["results"])
                noun = "correction" if phase["assigned"] == 1 else "corrections"
                ran = f"Fixer assigned {phase['assigned']} {noun}"
                result = (f"{results['applied']} applied; {results['failed']} failed"
                          if phase["complete"] else "Incomplete; no fix result recorded")
            else:
                noun = "pass" if len(phase["categories"]) == 1 else "passes"
                ran = (f"{len(phase['categories'])} recorded category {noun}"
                       if phase["complete"] else "Review started; completion not recorded")
                noun = "finding" if phase["assessed"] == 1 else "findings"
                result = (f"{phase['assessed']} {noun} assessed; {phase['to_fix']} to fix"
                          if phase["complete"] else "Incomplete")
                if phase["complete"] and not phase["settled"]:
                    result += "; adjudication completion not recorded"
            if phase["invalidated"]:
                result += "; superseded after reconciliation"
            rows.append([text(label), text(ran), text(result)])
    return rows or [["No review recorded", "Unavailable", "No coverage inferred"]]


def model_rows(bundle):
    planning = bundle["public"].get("planning")
    rows = [["Planning and design",
             "Prepare in the launching session, before the run; " +
             ("human approval recorded" if planning and planning["human_approved"] else "approval not recorded"),
             text(planning["model"] or "Not recorded") if planning else "Not recorded",
             text(planning["effort"] or "Not recorded") if planning else "Not recorded"]]
    for stage, roles in MODEL_STAGES:
        grouped = defaultdict(list)
        for role in roles:
            records = [item for item in bundle["models"] if item["role"] == role]
            selections = {(item["selected_model"], item["selected_effort"]) for item in records}
            if not selections:
                selections.update((choice["model"], choice["effort"])
                                  for choice in bundle["requested_models"].get(role, []))
            if not selections:
                selections.add((None, None))
            for selection in sorted(selections, key=lambda pair: (pair[0] or "", pair[1] or "")):
                grouped[selection].append(ROLE_NAMES[role])
        for (model, effort), names in grouped.items():
            rows.append([stage, text(", ".join(names)), text(model or "Not recorded"),
                         text(effort or "Not recorded")])
    return rows


def verification_rows(bundle):
    value = bundle["public"]["verification"]
    rows = []
    for number, record in enumerate(bundle["reviews"], 1):
        prefix = f"Review {number}: " if len(bundle["reviews"]) > 1 else ""
        for phase in record.get("passes", []):
            if not phase["checks"]:
                continue
            counts = Counter(phase["checks"])
            result = ", ".join(f"{count} {label.replace('_', ' ')}" for label, count in sorted(counts.items()))
            runner = "fixer" if phase["kind"] == "fix" else "review"
            rows.append([text(prefix + phase["name"] + " recorded checks"), f"{result} ({runner})"])
    if isinstance(value, str):
        return rows + [["Supplied verification account", text(value) + " (runner not recorded)"]]
    return rows + [[text(item["check"]), text(item["result"]) + f" ({text(item['runner'])})"] for item in value]


def identifiers(bundle, items):
    publication = bundle["publication"]
    lines = ["## Identifiers", "", "For tooling and cross-checking only; not needed to read this report.", "",
             f"- Development run: {code(bundle['run'])}",
             f"- Publication assignment: {code(bundle['assignment'])}",
             f"- Reviewed commit: {code(bundle['code_commit'])}",
             "- PR head at publication: " + (code(publication["head"]) if publication["head"] else "Not observed")]
    if publication["head"] and publication["head"] != bundle["code_commit"]:
        lines.append("- Commit mismatch: the PR head differs from the reviewed commit. "
                     "This audit does not establish review coverage for the newer head.")
    for record in bundle["reviews"]:
        numbers = [str(item["number"]) for item in items if item["review"] == record["id"]]
        lines.append(f"- Review ledger: {code(record['id'])}" +
                     (f" (findings {', '.join(numbers)})" if numbers else " (no available findings)"))
    lines += [f"- Exported evidence bundle identity (audit.json SHA-256): {code(plan.digest(plan.encode(bundle)))}",
              "- Exact two-file approval identity is retained in the publication receipt.", ""]
    return lines


def review_section(bundle):
    public = bundle["public"]
    lines = ["## How it was reviewed", ""]
    lines += table(["Pass", "What ran", "Result"], review_rows(bundle))
    categories = sorted({category for record in bundle["reviews"] for phase in record.get("passes", [])
                         for category in phase["categories"]})
    lines += ["Review categories: " + (", ".join(text(category_name(value)) for value in categories) or
                                      "Not recorded") + ".", ""]
    lines += table(["Review notes", "Details"], [["Supplied account", text(public["method"])]])
    lines += table(["Stage", "Roles", "Model", "Effort"], model_rows(bundle))
    lines += ["- Setup and delivery roles make no design decisions.",
              "- These are requested models, not observed identities. Actual observations remain separate in audit.json.",
              "", "## What was verified", ""]
    lines += table(["Check", "Result"], verification_rows(bundle))
    lines += ["Not verified: " + text(public.get("not_verified",
              "Anything beyond the recorded checks; native execution, token usage, cost and durations are not inferred.")), ""]
    return lines


def gaps_section(bundle, items):
    lines = ["## Known gaps", ""]
    lines += ["- " + text(value) for value in bundle["limitations"] + bundle["public"]["limitations"]]
    if any(not record["available"] for record in bundle["reviews"]):
        lines.append("- Some review histories are unavailable; their findings and counters were not reconstructed.")
    if bundle["models_unavailable"]:
        lines.append("- Some model records are unavailable.")
    if any(not item["details_available"] for item in items):
        lines.append("- Legacy narrative lacks structured public finding details; missing locations and decision reasons are explicit.")
    return lines + [""]


def finding_sections(items, repo):
    lines = []
    for key, heading, blurb in SECTIONS:
        selected = [item for item in items if group(item) == key]
        if key == "unresolved" and not selected:
            continue
        lines += [f"## {heading} ({len(selected)})", "", blurb, ""]
        if key == "rejected":
            lines += ["<details><summary>Show all rejected findings</summary>", ""]
        selected.sort(key=lambda item: ({"High": 0, "Medium": 1, "Low": 2}[item["severity"]],
                                        item["category"], item["number"]))
        for index, item in enumerate(selected):
            if index:
                lines += ["---", ""]
            lines += finding_entry(item, repo)
        if key == "rejected":
            lines += ["</details>", ""]
    return lines


def regression_section(regressions, items):
    if not regressions:
        return []
    numbers = {(item["review"], item["id"]): item["number"] for item in items}
    lines = ["## Regression relationships", ""]
    for item in regressions:
        cause, effect = (numbers[(item[key]["review"], item[key]["id"])] for key in ("cause", "effect"))
        lines += [f"- Finding {cause} to finding {effect} ({item['basis']}): {text(item['evidence'])}"]
    return lines + [""]


def render(bundle):
    public, publication = bundle["public"], bundle["publication"]
    items = findings(bundle)
    repo = publication["pr_url"].split("/pull/")[0].removeprefix("https://github.com/") if publication["pr_url"] else ""
    link = issue_link(publication["pr_url"], repo) if publication["pr_url"] else "Not recorded"
    stage = {"audit-initial": "an initial audit", "audit-final": "a final audit", "archive": "a historical export"}[bundle["stage"]]
    top = f"Pull request: {link}"
    if public.get("issues"):
        top += " &#183; Issue: " + ", ".join(issue_link(url, repo) for url in public["issues"])
    top += f" &#183; {'Exported' if bundle['stage'] == 'archive' else 'Published'} {publication['date']} as {stage}"
    lines = [top, "", "## Outcome", "", text(public["summary"]), ""]
    lines += table(["Result", "Findings", "Meaning"], outcome_rows(items))
    lines += ["### How to read each finding", "",
              "- **Confirmed / Rejected:** whether the adjudicator accepted the claim.",
              "- **Fixed / outside this PR / no change needed / not a defect:** the recorded action.",
              "- **Impact:** low, medium or high consequence if left as is.",
              "- **Category:** the reporting specialist. **Found in:** the first recorded review pass.", ""]
    lines += review_section(bundle)
    lines += gaps_section(bundle, items)
    lines += finding_sections(items, repo)
    lines += regression_section(public["regressions"], items)
    lines += ["## Process record", ""]
    lines += table(["Step", "Role", "Attempt", "Result"],
                   [[text(item["id"]), text(ROLE_NAMES.get(item["role"], item["role"].capitalize())),
                     str(item["attempt"]), text(item["outcome"] or "Reserved")]
                    for item in bundle["history"]])
    lines += identifiers(bundle, items)
    return ("\n".join(lines) + "\n").encode()
