#!/usr/bin/env python3
"""Project assessed findings for private reports without changing review decisions."""

import argparse
import hashlib
import json
from pathlib import Path
import sys


FEATURE = "review-known-issues"
HEADING = "## Known issues not fixed here"


def enabled(settings):
    return FEATURE in settings.catalog and FEATURE not in settings.disabled


def assessment(item):
    decisions = item.get("decisions", [])
    decision = decisions[-1] if decisions else item
    details = {}
    for value in [decision.get("reason", ""), *decision.get("evidence", [])]:
        if not isinstance(value, str):
            continue
        try:
            decoded = json.loads(value)
        except ValueError:
            continue
        if isinstance(decoded, dict) and ("assessment" in decoded or "report_action" in decoded):
            supplied = decoded.get("assessment", decoded)
            if isinstance(supplied, dict):
                details.update(supplied)
    return {**item, "reason": decision.get("reason"), **details,
            **{name: item[name] for name in ("key", "validation", "disposition", "severity") if name in item}}


def records(document):
    if not isinstance(document, dict) or document and not {"assessments", "findings"} & document.keys():
        raise ValueError("Expected assessed findings or a review handback")
    if "assessments" in document:
        candidates = {item["key"]: item for item in document.get("candidates", [])}
        return [{**candidates.get(item["key"], {}), **item} for item in document["assessments"]]
    findings = document.get("findings", {})
    if not isinstance(findings, (dict, list)):
        raise ValueError("Expected assessed findings or a review handback")
    return [assessment(item) for item in (findings.values() if isinstance(findings, dict) else findings)]


def merge(previous, incoming):
    result = {item["key"]: dict(item) for item in previous}
    for item in incoming:
        key = item["key"]
        prior = result.get(key)
        if prior and item.get("validation") == "pending" and prior.get("validation") in ("valid", "uncertain"):
            item = {**prior, "validation": "uncertain",
                    "reason": "Earlier finding awaits renewed validation after review invalidation.",
                    "disposition": "open", "snapshot": item.get("snapshot")}
        result[key] = {**(prior or {}), **item, "material": item.get("material"),
                       "duplicate_of": item.get("duplicate_of"), "sensitive": item.get("sensitive"),
                       "public": item.get("public")}
    return list(result.values())


def text_list(value):
    if isinstance(value, str):
        return [value] if value.strip() else []
    return [item for item in value if isinstance(item, str) and item.strip()] if isinstance(value, list) else []


def text(value, fallback):
    return value if isinstance(value, str) and value.strip() else fallback


def boolean(value):
    return value if type(value) is bool else None


def public_presentation(value):
    required = ("title", "summary", "reason")
    if not isinstance(value, dict) or not all(text(value.get(name), None) for name in required):
        return None
    locations = value.get("locations")
    if not isinstance(locations, list) or not all(text(item, None) for item in locations):
        return None
    return {**{name: value[name] for name in required}, "locations": list(locations),
            "next_step": text(value.get("next_step"), None)}


def known_issue(item):
    title = text(item.get("title"), text(item.get("summary"), item["key"]))
    evidence = text_list(item.get("evidence"))
    return {
        "key": item["key"], "title": title, "summary": text(item.get("summary"), title),
        "tracking_marker": "<!-- ioncache-follow-up:v1 key=" +
        hashlib.sha256(item["key"].encode()).hexdigest() + " -->",
        "locations": text_list(item.get("locations")),
        "evidence": evidence,
        "validation": item["validation"], "severity": item.get("severity", "Low"),
        "confidence": text(item.get("confidence"), "Not recorded"),
        "basis": text(item.get("basis"), "Not recorded"), "introduced": boolean(item.get("introduced")),
        "material": boolean(item.get("material")), "sensitive": boolean(item.get("sensitive")),
        "disposition": item.get("disposition", "open"),
        "reason": text(item.get("reason"), "No deferral reason recorded; remains unresolved."),
        "next_step": text(item.get("next_step"), None), "done_when": text(item.get("done_when"), None),
        "ledger": item.get("ledger"), "snapshot": item.get("snapshot"),
        "public": public_presentation(item.get("public")),
    }


def project(inventory):
    known, counted, fixed, pending = [], 0, 0, 0
    canonical = {item["key"]: item for item in merge([], inventory)}
    for item in canonical.values():
        reference = item.get("duplicate_of")
        duplicate = canonical.get(reference) if isinstance(reference, str) and reference != item["key"] else None
        if (item.get("validation") == "invalid" or item.get("material") is False or
                duplicate and duplicate.get("validation") in ("valid", "uncertain") and
                duplicate.get("material") is not False and not duplicate.get("duplicate_of")):
            counted += 1
        elif item.get("disposition") == "fixed":
            fixed += 1
        elif item.get("validation") in ("valid", "uncertain"):
            known.append(known_issue(item))
        else:
            pending += 1
    order = {"High": 0, "Medium": 1, "Low": 2}
    known.sort(key=lambda item: (order.get(item["severity"], 3), item["key"]))
    return {"known_issues": known, "counted_only": counted, "fixed": fixed, "pending": pending}


def render(report, *, show=True, tickets=None, include_evidence=True):
    if not show:
        return "Known-issue reporting is disabled; assessed findings remain in private storage."
    lines = [HEADING, ""]
    for item in report["known_issues"]:
        scope = {True: "introduced by this change", False: "pre-existing"}.get(
            item["introduced"], "origin not established")
        lines.extend([f"### {item['title']}", "", f"- ID: {item['key']}",
                      f"- Location: {', '.join(item['locations']) or 'not recorded'}.",
                      f"- Assessment: {item['validation']}; {item['severity']}; {scope}.",
                      f"- Confidence: {item['confidence']}.",
                      f"- Problem: {item['summary']}"])
        if include_evidence:
            lines.append(f"- Evidence ({item['basis']}): {'; '.join(item['evidence']) or 'not recorded'}.")
        lines.append(f"- Why not fixed: {item['reason']}")
        if item["material"] is None:
            lines.append("- Limitation: materiality was not recorded; do not silently suppress this finding.")
        if item["next_step"]:
            lines.append(f"- Next action: {item['next_step']}")
        ticket = (tickets or {}).get(item["key"])
        if ticket:
            lines.append(f"- Follow-up: {ticket.get('url') or ticket['status']}. {ticket['reason']}")
        lines.append("")
    if not report["known_issues"]:
        lines.extend(["No assessed unresolved material findings recorded; this is not proof of no defects.", ""])
    lines.append(f"Counted-only observations: {report['counted_only']}. "
                 f"Awaiting assessment: {report['pending']}.")
    return "\n".join(lines)


def public_draft(report, *, show=True, tickets=None):
    issues, links = [], {}
    for item in report["known_issues"]:
        identity = hashlib.sha256(item["key"].encode()).hexdigest()[:12]
        severity = item["severity"] if item["severity"] in ("High", "Medium", "Low") else "Not recorded"
        if item["sensitive"] is False and item["public"] is not None:
            key = "finding-" + identity
            issues.append(known_issue({
                **{name: item[name] for name in ("validation", "introduced", "material")},
                "severity": severity,
                "confidence": item["confidence"] if item["confidence"] in
                ("High", "Medium", "Low") else "Not recorded",
                **item["public"], "key": key,
            }))
            ticket = (tickets or {}).get(item["key"])
            if ticket:
                links[key] = {"status": ticket["status"], "url": ticket.get("url"), "reason": ""}
            continue
        issues.append(known_issue({
            "key": "withheld-" + identity, "title": "Finding withheld pending safe disclosure",
            "summary": "Details remain in the private report.",
            "validation": item["validation"], "severity": severity, "material": True,
            "reason": "Public disclosure has not been cleared.",
        }))
    return render({**report, "known_issues": issues}, show=show, tickets=links, include_evidence=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Private handback or review-ledger status JSON")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args(argv)
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks/scripts"))
        import plugin_config

        catalog = plugin_config.defaults()
        disabled = plugin_config.synchronize(str(Path.cwd()), catalog=catalog, persist=False, strict=True)
        report = project(records(json.loads(args.input.read_bytes())))
        report["reporting_enabled"] = FEATURE in catalog and FEATURE not in disabled
        print(json.dumps(report, indent=2) if args.format == "json" else
              render(report, show=report["reporting_enabled"]))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f"review-reporting: unavailable: {error}; retain and report the original findings", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
