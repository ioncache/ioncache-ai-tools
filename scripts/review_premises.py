"""Seal scoped source evidence for reuse, without certifying its truth or fetching it."""

import argparse
import json
from pathlib import Path

from review_assignments import require, seal, strings, text, verify_identity


def validate(record):
    require(isinstance(record, dict), "Premise must be an object")
    require(set(record) == {"key", "claim", "scope", "version", "source", "content",
                           "status", "limitations", "identity"}, "Unknown or missing premise fields")
    verify_identity(record)
    for field in ("key", "claim", "scope", "version", "source", "content"):
        text(record[field], f"Premise {field}")
    require(record["status"] in ("supported", "unresolved", "contradicted"), "Invalid premise status")
    strings(record["limitations"], "Premise limitations")
    return record


def lookup(records, key, scope, version):
    matches = []
    for record in records:
        validate(record)
        if (record["key"], record["scope"], record["version"]) == (key, scope, version):
            matches.append(record)
    require(len(matches) <= 1, "Conflicting premise records; preserve both sources and resolve the conflict")
    if not matches:
        return {"status": "missing", "premise": None}
    return {"status": matches[0]["status"], "premise": matches[0]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("seal")
    create.add_argument("input", type=Path)
    find = commands.add_parser("lookup")
    find.add_argument("input", type=Path)
    for name in ("key", "scope", "version"):
        find.add_argument("--" + name, required=True)
    args = parser.parse_args()
    try:
        value = json.loads(args.input.read_text())
        if args.command == "seal":
            require(isinstance(value, dict) and "identity" not in value, "Seal an unsealed premise object")
            result = validate(seal(value))
        else:
            require(isinstance(value, list), "Lookup needs a list of retained premises")
            result = lookup(value, args.key, args.scope, args.version)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, KeyError, TypeError, ValueError) as error:
        parser.exit(2, f"review-premises: {error}; retain uncertainty and continue independent work\n")


if __name__ == "__main__":
    raise SystemExit(main())
