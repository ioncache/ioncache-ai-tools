#!/usr/bin/env python3
"""Render observed review timings without launching workers or changing review state."""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys

from review_assignments import require, text
import review_options


STAGES = ("setup", "adjudication", "final_merge", "posting")
LABELS = ("Setup", "Adjudication", "Final merge", "Posting")


def timestamp(value, label, limitations):
    if value is None:
        return None
    try:
        require(isinstance(value, dict), "timestamp needs at and source")
        text(value.get("source"), "Timestamp source")
        parsed = datetime.fromisoformat(text(value.get("at"), "Timestamp at"))
        require(parsed.utcoffset() is not None, "timestamp needs an explicit timezone")
        return parsed.timestamp()
    except (ValueError, TypeError, OverflowError, OSError) as error:
        limitations.append(f"{label}: {error}")
        return None


def difference(start, end, label, limitations):
    if start is None or end is None:
        return None
    if end < start:
        limitations.append(f"{label}: timestamps run backwards; duration unavailable")
        return None
    return end - start


def interval(record, label, limitations, bounds):
    start = timestamp(record.get("started"), label + " start", limitations)
    end = timestamp(record.get("finished"), label + " finish", limitations)
    elapsed = difference(start, end, label, limitations)
    known = [value for value in (start, end) if value is not None]
    outside = any((bounds[0] is not None and value < bounds[0]) or
                  (bounds[1] is not None and value > bounds[1]) for value in known)
    if outside or start is not None and end is not None and elapsed is None:
        if outside:
            limitations.append(f"{label}: timestamps are outside the review window")
        return {"start": None, "end": None, "seconds": None}
    return {"start": start, "end": end, "seconds": elapsed}


def reported_duration(value, label, limitations):
    if value is None:
        return None
    if (not isinstance(value, dict) or type(value.get("seconds")) not in (int, float) or
            not math.isfinite(value["seconds"]) or value["seconds"] < 0 or
            not isinstance(value.get("source"), str) or not value["source"].strip()):
        limitations.append(f"{label}: reported duration needs nonnegative seconds and a source")
        return None
    return value["seconds"]


def agent_record(record, limitations, bounds):
    key = text(record.get("id"), "Agent attempt id")
    role = text(record.get("role"), "Agent role")
    span = interval(record, key, limitations, bounds)
    queued = timestamp(record.get("queued"), key + " queue", limitations)
    collected = timestamp(record.get("collected"), key + " collection", limitations)
    reported = reported_duration(record.get("duration"), key, limitations)
    return {
        "id": key, "role": role, "category": record.get("category"), "worker": record.get("worker"),
        "status": record.get("status", "unknown"), **span,
        "reported_seconds": reported,
        "elapsed_seconds": span["seconds"] if span["seconds"] is not None else reported,
        "elapsed_basis": "interval" if span["seconds"] is not None else "reported",
        "queue_seconds": difference(queued, span["start"], key + " queue", limitations),
        "collection_seconds": difference(span["end"], collected, key + " collection", limitations),
    }


def stage_record(record, limitations, bounds):
    name = text(record.get("name"), "Stage name")
    require(name in STAGES, "Unknown timing stage")
    return {"id": text(record.get("id"), "Stage id"), "name": name,
            "status": record.get("status", "unknown"),
            **interval(record, name, limitations, bounds)}


def wait_record(record, limitations, bounds):
    key = text(record.get("id"), "Wait id")
    waiting = text(record.get("waiting"), "Waiting assignment or stage")
    blockers = record.get("blocked_by", [])
    require(isinstance(blockers, list) and all(isinstance(item, str) and item.strip() for item in blockers),
            "Blockers must be a list of identifiers")
    return {"id": key, "waiting": waiting, "blocked_by": blockers,
            "reason": text(record.get("reason"), "Observed wait reason"),
            **interval(record, key, limitations, bounds)}


def collect(values, convert, limitations, bounds):
    require(isinstance(values, list), "Timing records must be lists")
    result, seen = [], set()
    for index, record in enumerate(values):
        try:
            require(isinstance(record, dict), "Timing record must be an object")
            row = convert(record, limitations, bounds)
            require(row["id"] not in seen, "Duplicate timing id; retain separate attempt identities")
            seen.add(row["id"])
            result.append(row)
        except (ValueError, TypeError, KeyError, OverflowError) as error:
            limitations.append(f"{convert.__name__} record {index + 1}: {error}")
    return result


def union_seconds(spans):
    end, total = None, 0
    for start, finish in sorted(spans):
        total += max(0, finish - max(start, end if end is not None else start))
        end = max(finish, end if end is not None else finish)
    return total


def stage_duration(stages, name):
    selected = [row for row in stages if row["name"] == name]
    if not selected:
        return {"seconds": None, "status": "unavailable"}
    active = [row for row in selected if row["status"] != "skipped"]
    if not active:
        return {"seconds": 0, "status": "skipped"}
    if any(row["seconds"] is None for row in active):
        return {"seconds": None, "status": "unavailable"}
    return {"seconds": union_seconds((row["start"], row["end"]) for row in active), "status": "measured"}


def project(document):
    require(isinstance(document, dict) and type(document.get("schema")) is int and
            document["schema"] == 1, "Expected schema-1 timing evidence")
    key = text(document.get("review"), "Review identity")
    notes = document.get("limitations", [])
    require(isinstance(notes, list) and all(isinstance(item, str) for item in notes), "Invalid timing limitations")
    limitations = list(notes)
    review = interval(document, "Review", limitations, (None, None))
    bounds = (review["start"], review["end"])
    agents = collect(document.get("agents", []), agent_record, limitations, bounds)
    stages = collect(document.get("stages", []), stage_record, limitations, bounds)
    waits = collect(document.get("waits", []), wait_record, limitations, bounds)
    reviewers = [row for row in agents if row["role"] == "reviewer"]
    known = [row["elapsed_seconds"] for row in reviewers if row["elapsed_seconds"] is not None]
    longest = max(known) if known and len(known) == len(reviewers) else None
    if len(agents) != len(document.get("agents", [])):
        longest = None
    if any(row["elapsed_seconds"] is None for row in agents):
        limitations.append("Some agent durations are unavailable; do not infer them from other agents.")
    summary = {name: stage_duration(stages, name) for name in STAGES}
    if len(stages) != len(document.get("stages", [])):
        summary = {name: {"seconds": None, "status": "unavailable"} for name in STAGES}
    return {
        "review": key, "enabled": True, **review,
        "summary": summary,
        "longest_reviewer_seconds": longest, "agents": agents, "stages": stages, "waits": waits,
        "limitations": limitations,
    }


def duration(seconds, *, total=False):
    if seconds is None:
        return "unavailable"
    seconds = round(seconds)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if hours:
        return f"{hours}h {minutes:02}m {seconds:02}s"
    if minutes:
        return f"{minutes}m {seconds:02}s" if seconds or total else f"{minutes}m"
    return f"{seconds}s"


def plain(value):
    value = "unknown" if value is None else str(value)
    return "".join(char if ord(char) >= 32 and ord(char) != 127 else " " for char in value).replace(
        "|", "/").replace("`", "'")


def offset(value, origin):
    return "unavailable" if value is None or origin is None else "+" + duration(value - origin, total=True)


def agent_table(report):
    lines = ["### Agents", "",
             "| Agent | Purpose | Status | Start | Finish | Duration | Queue | Collection lag |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for row in report["agents"]:
        elapsed = duration(row["elapsed_seconds"])
        if row["elapsed_basis"] == "reported" and row["elapsed_seconds"] is not None:
            elapsed += " (reported)"
        purpose = row["role"] + (f" / {row['category']}" if row["category"] else "")
        cells = [row["id"], purpose, row["status"], offset(row["start"], report["start"]),
                 offset(row["end"], report["start"]), elapsed,
                 duration(row["queue_seconds"]), duration(row["collection_seconds"])]
        lines.append("| " + " | ".join(plain(cell) for cell in cells) + " |")
    if not report["agents"]:
        lines.extend(["", "No agent timing records available."])
    return lines


def timeline(report):
    rows = [(row, "#") for row in report["agents"]]
    rows += [(row, "=") for row in report["stages"] if row["status"] != "skipped"]
    rows += [(row, "w") for row in report["waits"]]
    lines = ["### Timeline", "", "`#` agent interval; `=` stage; `w` recorded wait. "
             "Intervals can overlap and include time spent waiting, not just model execution."]
    if report["start"] is None or report["end"] is None or report["seconds"] <= 0:
        return lines + ["", "Timeline scale unavailable; retain known durations in the agent table."]
    width, total = 48, report["seconds"]
    lines += ["", f"Each cell is approximately {total / width:.1f}s; offsets are from review start.", "", "```text"]
    for row, marker in sorted(rows, key=lambda item: (
            item[0]["start"] is None, item[0]["start"] or 0, item[0]["id"])):
        label = plain(row["id"])
        if row["start"] is None or row["end"] is None:
            lines.append(f"{label}: interval unavailable")
            continue
        start = row["start"] - report["start"]
        end = row["end"] - report["start"]
        left = min(width - 1, math.floor(start / total * width))
        right = min(width, max(left + 1, math.ceil(end / total * width)))
        bar = " " * left + (marker if end > start else "|") * (right - left)
        lines.append(f"{label}: {offset(row['start'], report['start'])} to {offset(row['end'], report['start'])}")
        lines.append("[" + bar.ljust(width) + "]")
    return lines + ["```"]


def render(report, *, details=False):
    if not report.get("enabled", True):
        return "Total elapsed: unavailable (timing reporting disabled)"
    stages = report["summary"]
    measures = [f"{label}: " + ("not run" if stages[name]["status"] == "skipped" else
                              duration(stages[name]["seconds"])) for name, label in zip(STAGES, LABELS)]
    measures.insert(1, "Longest reviewer: " + duration(report["longest_reviewer_seconds"]))
    lines = ["Total elapsed: " + duration(report["seconds"], total=True), " \u00b7 ".join(measures)]
    if details:
        lines += ["", *agent_table(report), "", *timeline(report), "", "### Recorded waits", ""]
        for row in sorted(report["waits"], key=lambda item: (
                item["seconds"] is None, -(item["seconds"] or 0), item["id"])):
            blockers = ", ".join(row["blocked_by"]) or "unavailable"
            lines.append(f"- {plain(row['waiting'])}: {duration(row['seconds'])}; "
                         f"waiting on {plain(blockers)}. {plain(row['reason'])}")
        if not report["waits"]:
            lines.append("No waits recorded; this does not establish that none occurred.")
        lines.append("\nQueue and collection gaps alone do not establish their cause. "
                     "Waits overlap other work and are not added to elapsed time.")
    if report["limitations"]:
        notes = report["limitations"]
        explanation = " ".join(plain(item) for item in notes) if details else plain(notes[0])
        if not details and len(notes) > 1:
            explanation += f" ({len(notes) - 1} more retained in the private timing evidence.)"
        lines.append("\nTiming limitations: " + explanation)
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("stamp", help="Print a sourced caller-clock observation")
    report = commands.add_parser("report", help="Render private timing evidence")
    report.add_argument("input", type=Path)
    report.add_argument("--run-details", action="store_true")
    report.add_argument("--format", choices=("json", "markdown"), default="markdown")
    args = parser.parse_args(argv)
    try:
        enabled = review_options.read_configuration("review-code")["timing_enabled"]
        if args.command == "stamp":
            value = {"at": datetime.now(timezone.utc).isoformat(),
                     "source": "review_timing.py caller clock"} if enabled else None
            print(json.dumps(value))
        else:
            value = project(json.loads(args.input.read_bytes())) if enabled else {"enabled": False}
            print(json.dumps(value, indent=2) if args.format == "json" else
                  render(value, details=args.run_details))
        return 0
    except (OSError, ValueError, KeyError, TypeError, OverflowError) as error:
        print(f"review-timing: unavailable: {error}; retain the review results and original timing evidence",
              file=sys.stderr)
        if args.command == "stamp":
            print("null")
        elif args.format == "json":
            print(json.dumps({"error": str(error), "seconds": None}))
        else:
            print("Total elapsed: unavailable")
        return 2


if __name__ == "__main__":
    sys.exit(main())
