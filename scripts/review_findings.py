"""Assign public IDs from discovery provenance, without changing assessments."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re

import review_assignments as records


PREFIXES = {
    "correctness": "COR", "security": "SEC", "integration": "INT",
    "code-complexity": "CPL", "comments": "CMT", "jsdoc": "JSD",
    "unit-tests": "UNT", "test-coverage": "TST", "documentation": "DOC",
    "design-coherence": "DSG", "privacy": "PRV", "performance": "PERF",
}


def prefix(category):
    records.text(category, "Finding category")
    if category in PREFIXES:
        return PREFIXES[category]
    records.require(isinstance(category, str) and records.PROJECT_ID.fullmatch(category),
                    "Finding category must be a registered discovery purpose")
    suffix = hashlib.sha256(category.encode()).hexdigest()[:8]
    return "PRJ" + suffix.translate(str.maketrans("0123456789abcdef", "ABCDEFGHIJKLMNOP"))


def valid_id(value, category):
    return isinstance(value, str) and re.fullmatch(re.escape(prefix(category)) + r"[1-9][0-9]*", value)


def discovery_index(attempts, references):
    records.require(isinstance(attempts, list), "Discovery attempts must be a list")
    result, seen = {}, set()
    needed = {attempt for attempt, _ in references}
    for attempt in attempts:
        records.require(isinstance(attempt, dict), "Discovery attempt must be an object")
        if attempt.get("id") not in needed:
            continue
        records.require(attempt["id"] not in seen, "Duplicate referenced attempt ID")
        seen.add(attempt["id"])
        report = attempt["result"]
        if report is None:
            continue
        records.require(isinstance(report, dict), "Discovery report must be an object")
        records.verify_identity(attempt["packet"])
        records.require(report.get("packet_identity") == attempt["packet"]["identity"] and
                        report.get("review_type") == attempt["packet"]["review_type"],
                        "Discovery report differs from its packet")
        records.require(report["assignment"] == attempt["packet"]["assignment"] and
                        report["snapshot"] == attempt["packet"]["snapshot"],
                        "Discovery report differs from its packet")
        records.require(isinstance(report["candidates"], list), "Candidates must be a list")
        for candidate in report["candidates"]:
            records.require(isinstance(candidate, dict), "Candidate must be an object")
            key = (attempt["id"], records.text(candidate.get("key"), "Candidate key"))
            if key not in references:
                continue
            records.require(key not in result, "Duplicate discovery candidate reference")
            records.require(candidate.get("origin", report.get("origin")) == "specialist",
                            "New adjudicator discoveries need independent category validation")
            result[key] = attempt["packet"]["review_type"]
    return result


def assign(attempts, assessments):
    records.require(isinstance(assessments, list), "Canonical assessments must be a list")
    items, prefixes, references = {}, {}, set()
    for assessment in assessments:
        records.require(isinstance(assessment, dict), "Canonical assessment must be an object")
        if assessment.get("duplicate_of") or assessment.get("validation") == "invalid":
            continue
        if assessment.get("material") is False:
            continue
        records.require(assessment.get("validation") in ("valid", "uncertain"),
                        "Resolve pending findings before assigning public IDs")
        item = copy.deepcopy(assessment)
        key = records.text(item.get("key"), "Issue key")
        records.require(key not in items, "Duplicate canonical issue key")
        sources = item.get("sources")
        records.require(isinstance(sources, list) and bool(sources), "Retain each issue's discovery sources")
        for source in sources:
            records.require(isinstance(source, dict), "Discovery source must be an object")
            references.add((records.text(source.get("attempt"), "Source attempt"),
                            records.text(source.get("key"), "Source candidate key")))
        items[key] = item
    discovery = discovery_index(attempts, references)
    for item in items.values():
        origins = []
        for source in item["sources"]:
            reference = (source["attempt"], source["key"])
            records.require(reference in discovery, "Issue references an unknown discovery candidate")
            origins.append((discovery[reference], *reference))
        category = min(origins)[0]
        code = prefix(category)
        records.require(code not in prefixes or prefixes[code] == category, "Category prefix collision")
        prefixes[code] = category
        item.update(category=category, categories=sorted({origin[0] for origin in origins}))
    counts, mapping = {}, {}
    for key, item in sorted(items.items()):
        category = item["category"]
        counts[category] = counts.get(category, 0) + 1
        mapping[key] = f"{prefix(category)}{counts[category]}"
        item["id"] = mapping[key]
    for item in items.values():
        related = records.strings(item.get("related_keys", []), "Related issue keys")
        records.require(set(related) <= items.keys() and item["key"] not in related,
                        "Relationships must name other canonical issues")
        item["related"] = [mapping[key] for key in related]
    order = {"P1": 0, "P2": 1, "P3": 2, "High": 0, "Medium": 1, "Low": 2}
    findings = sorted(items.values(), key=lambda item: (
        order.get(item.get("priority_level"), 3), order.get(item.get("severity"), 3), item["id"]))
    return {"ids": mapping, "findings": findings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("handoff", type=Path, help="Checked private handoff with attempts and assessments")
    args = parser.parse_args()
    try:
        value = json.loads(args.handoff.read_text())
        print(json.dumps(assign(value["attempts"], value["assessments"]), indent=2))
        return 0
    except (OSError, KeyError, TypeError, ValueError) as error:
        parser.exit(2, f"review-findings: {error}; retain evidence and repair provenance, not findings\n")


if __name__ == "__main__":
    raise SystemExit(main())
