"""Carry unresolved findings and native publisher receipts without acceptance gates."""

import re

import development_audit as audit
import review_reporting as reporting


FEATURE = "autonomous-development-follow-ups"


def policy(manifest, settings):
    approved = manifest["permissions"].get("create_follow_up_issues", False) is True
    configured = FEATURE in settings.catalog and FEATURE not in settings.disabled
    return {"enabled": approved and configured, "approved": approved,
            "configured": configured, "reporting_enabled": reporting.enabled(settings)}


def retain(progress, report):
    incoming = [{**item, "ledger": report.get("ledger"), "snapshot": report.get("snapshot")}
                for item in reporting.records(report)]
    prior = progress.get("finding_inventory")
    if prior is None:
        prior = reporting.records(progress.get("review") or {})
    progress["finding_inventory"] = reporting.merge(prior, incoming)


def presentation(progress, settings):
    inventory = progress.get("finding_inventory")
    if inventory is None:
        inventory = reporting.records(progress.get("review") or {})
    report = reporting.project(inventory)
    options = {"show": reporting.enabled(settings), "tickets": progress.get("follow_up_issues")}
    return {**report, "known_issues_report": reporting.render(report, **options),
            "known_issues_pr_draft": reporting.public_draft(report, **options)}


def receipt(value, *, allow_create, repository):
    if not isinstance(value, dict) or value.get("status") not in ("created", "reused", "not_filed", "withheld"):
        return {"status": "not_filed", "reason": "No usable publication receipt was supplied.", "url": None}
    reason = value.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        return {"status": "not_filed", "reason": "Publisher did not supply supporting evidence.", "url": None}
    status, url = value["status"], value.get("url")
    if status in ("created", "reused"):
        if status == "created" and not allow_create:
            return {"status": "not_filed", "reason": "Unapproved creation was reported; inspect remote effects.",
                    "url": None}
        try:
            repo = audit.repository(repository)
        except ValueError:
            repo = None
        if not repo or not isinstance(url, str) or not re.fullmatch(
                rf"https://github\.com/{re.escape(repo)}/issues/[1-9][0-9]*", url):
            return {"status": "not_filed", "reason": "Reported issue URL did not identify the approved repository.",
                    "url": None}
    else:
        url = None
    return {"status": status, "reason": reason, "url": url}


def record(progress, data, manifest, settings):
    supplied = data.get("follow_up_issues", {})
    supplied = supplied if isinstance(supplied, dict) else {}
    saved = progress.setdefault("follow_up_issues", {})
    current = presentation(progress, settings)["known_issues"]
    for item in current:
        key = item["key"]
        if key not in supplied and key in saved:
            continue
        attempt = receipt(supplied.get(key), allow_create=policy(manifest, settings)["enabled"],
                          repository=manifest["repository"]["url"])
        if saved.get(key, {}).get("url") and not attempt["url"]:
            attempt = {**saved[key], "reason": attempt["reason"] + " Earlier verified link retained."}
        saved[key] = attempt


def instructions(assignment, role, executor):
    if role not in ("draft", "ready"):
        return ""
    control = assignment.get("follow_ups", {"enabled": False, "reporting_enabled": True})
    publication = ("Create or reuse follow-up issues automatically under the approved run permission. "
                   if control["enabled"] else
                   "Do not create follow-up issues: publication is unapproved or independently disabled. "
                   "Existing issue links may be reused after read-only verification. ")
    display = ("Include Known issues not fixed here from progress.known_issues in the PR and report. "
               if control["reporting_enabled"] else
               "The named known-issue section is disabled; disclose the omission and retain the private inventory. ")
    return (f"Follow {executor}/skills/autonomous-development/FOLLOW_UPS.md for this publication. "
            + publication + display +
            "Do not treat tickets as fixes. "
            "Ticket failures are non-blocking: return not_filed with evidence and continue the PR operation. ")
