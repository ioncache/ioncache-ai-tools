"""Project review structure and explicitly publication-reviewed finding details."""

import re

import development_manifest as plan
import review_assignments
from development_audit_render import first_sentence, human_title


def category(value, categories):
    if value in categories or review_assignments.PROJECT_ID.fullmatch(value):
        return value
    return None


def finding_categories(item, categories):
    values = set()
    for observation in item["observations"]:
        for evidence in observation["evidence"]:
            for match in re.findall(r"(?:^|\s)review_type=([a-z][a-z0-9:-]*)", evidence):
                if category(match, categories):
                    values.add(match)
    return sorted(values)


def review_passes(ledger, state):
    categories = {item["id"] for item in review_assignments.catalog()["categories"]}
    phases, event_pass = [], {}
    loop, cycle, current = 0, 0, None
    for event in ledger["events"]:
        kind = event["type"]
        if kind in ("start_review", "start_fix", "fix_done"):
            if kind == "start_review":
                loop, cycle = loop + 1, 0
                name = {1: "First review", 2: "Second review"}.get(loop, f"Review pass {loop}")
            elif kind == "start_fix":
                current["settled"] = True
                cycle += 1
                name = "Fix cycle" + (f" {cycle}" if cycle > 1 else "")
            else:
                current["complete"] = True
                current["results"] = [value["result"] for value in event["results"].values()]
                current["checks"] = [item["result"] for item in event["checks"]]
                name = "Check of the fixes" + (f" {cycle}" if cycle > 1 else "")
            if kind != "start_review" and loop > 1:
                name += f" (review {loop})"
            current = {"name": name, "kind": "fix" if kind == "start_fix" else "review",
                       "categories": [], "complete": False, "settled": False, "decisions": {},
                       "assigned": len(event.get("findings", [])), "results": [],
                       "checks": [],
                       "invalidated": bool(state["loops"][loop - 1].get("invalidated"))}
            phases.append(current)
        if current is None:
            continue
        event_pass[event["sequence"]] = current["name"]
        if kind in ("review_done", "fixes_reviewed"):
            current["complete"] = True
            current["checks"] = [item["result"] for item in event.get("checks", [])]
            current["categories"] = sorted({value for item in event["passes"]
                                             if (value := category(item["name"], categories))})
        if kind == "decision":
            current["decisions"][event["id"]] = event
        if kind == "advance":
            current["settled"] = True
    for phase in phases:
        decisions = phase.pop("decisions")
        phase["assessed"] = len(decisions)
        phase["to_fix"] = sum(item["validation"] == "valid" and item["disposition"] == "open"
                              for item in decisions.values())
    return phases, event_pass


def review_findings(state, event_pass):
    categories = {item["id"] for item in review_assignments.catalog()["categories"]}
    return [{
        "id": item["id"], "severity": item["severity"], "validation": item["validation"],
        "disposition": item["disposition"], "category": finding_categories(item, categories),
        "pass": event_pass.get(item["observations"][0]["sequence"], "Not recorded"),
        "observations": [event["sequence"] for event in item["observations"]],
        "decisions": [{key: event[key] for key in ("sequence", "validation", "disposition", "severity")}
                      for event in item["decisions"]],
    } for item in state["findings"].values()]


def issue_urls(values):
    plan.strings(values, empty=True)
    for value in values:
        plan.require(re.fullmatch(r"https://github\.com/[A-Za-z0-9][A-Za-z0-9-]*/"
                                  r"[A-Za-z0-9_.-]+/issues/[1-9][0-9]*", value),
                     "Public issue references must be github.com issue URLs")


def finding_details(item, finding):
    base = {"review", "id", "summary", "rationale"}
    extra = {"key", "locations", "decisions", "tracking_issues"}
    plan.require(set(item) in (base, base | extra),
                 "Public finding needs review/id/summary/rationale and, for structured details, "
                 "key/locations/decisions/tracking_issues")
    if set(item) == base:
        return
    plan.require(bool(human_title(plan.text(item["key"]))), "Public finding key must contain a readable title")
    plan.strings(item["locations"], empty=True)
    for location in item["locations"]:
        plan.require(not re.match(r"^[A-Za-z]:", location) and
                     not any(ord(char) < 32 or ord(char) == 127 for char in location),
                     "Public finding locations must be repository-relative, without controls")
        plan.relative(re.split(r":(?=[0-9])", location, maxsplit=1)[0])
    issue_urls(item["tracking_issues"])
    plan.require(isinstance(item["decisions"], list), "Public decisions must be a list")
    for decision in item["decisions"]:
        plan.fields(decision, "sequence reason")
        plan.require(type(decision["sequence"]) is int, "Decision sequence must be an integer")
        plan.text(decision["reason"])
    plan.require([entry["sequence"] for entry in item["decisions"]] ==
                 [entry["sequence"] for entry in finding["decisions"]],
                 "Public decisions must account for every recorded decision, in order")


def narrative_options(value):
    base = {"summary", "method", "verification", "findings", "regressions", "limitations"}
    plan.require(isinstance(value, dict) and base <= value.keys() <=
                 base | {"issues", "planning", "not_verified"},
                 "Public narrative has missing or unsupported fields")
    for key in ("summary", "method"):
        plan.text(value[key])
    verification = value["verification"]
    if isinstance(verification, str):
        plan.text(verification)
    else:
        plan.require(isinstance(verification, list) and verification,
                     "Public verification needs at least one check")
        for item in verification:
            plan.fields(item, "check result runner")
            for field in item:
                plan.text(item[field])
    if "issues" in value:
        issue_urls(value["issues"])
    if "not_verified" in value:
        plan.text(value["not_verified"])
    if "planning" in value:
        planning = value["planning"]
        plan.fields(planning, "model effort human_approved")
        for key in ("model", "effort"):
            if planning[key] is not None:
                plan.text(planning[key])
        plan.require(type(planning["human_approved"]) is bool, "Planning approval must be explicit")


def add_public_findings(records, public):
    supplied = {(item["review"], item["id"]): item for item in public["findings"]}
    for record in records:
        for finding in record.get("findings", []):
            item = supplied[(record["id"], finding["id"])]
            reasons = {entry["sequence"]: entry["reason"] for entry in item.get("decisions", [])}
            for decision in finding["decisions"]:
                decision["reason"] = reasons.get(decision["sequence"], "Public decision reason not supplied.")
            final = finding["decisions"][-1]["reason"] if reasons else item["rationale"]
            finding.update(title=human_title(item["key"]) if "key" in item else first_sentence(item["summary"]),
                           summary=item["summary"], reason=first_sentence(final),
                           locations=item.get("locations", []), tracking_issues=item.get("tracking_issues", []),
                           details_available="key" in item)
