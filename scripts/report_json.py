#!/usr/bin/env python3
"""Decode complete report objects without guessing missing review evidence."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

import development_manifest as plan


FEATURE = "review-report-json-recovery"
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_TRAILING_COMMAS = 4096
WHITESPACE = " \t\r\n"
FENCE = re.compile(r"\A[ \t\r\n]*```(?:json)?[ \t]*\r?\n(.*)\r?\n```[ \t\r\n]*\Z", re.DOTALL)


def read_bytes(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        plan.require(stat.S_ISREG(info.st_mode), f"Expected a regular JSON file: {path}")
        plan.require(info.st_size <= MAX_JSON_BYTES, f"JSON exceeds the size limit: {path}")
        content = stream.read(MAX_JSON_BYTES + 1)
        plan.require(len(content) <= MAX_JSON_BYTES, f"JSON exceeds the size limit: {path}")
        return content


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        plan.require(key not in value, f"Ambiguous report JSON: duplicate key {key!r}")
        value[key] = item
    return value


def reject_constant(value):
    raise plan.ManifestError(f"Invalid report JSON constant: {value}")


def strict_loads(text):
    return json.loads(text, object_pairs_hook=unique_object, parse_constant=reject_constant)


def trailing_commas(text):
    quoted, escaped, previous = False, False, ""
    offsets = []
    for index, char in enumerate(text):
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
                previous = char
            continue
        if char == '"':
            quoted = True
        elif char == "," and previous and previous not in "[{,:":
            following = index + 1
            while following < len(text) and text[following] in WHITESPACE:
                following += 1
            if following < len(text) and text[following] in "]}":
                offsets.append(index)
                plan.require(len(offsets) <= MAX_TRAILING_COMMAS,
                             "Too many trailing commas; restate the report from existing evidence")
        if char not in WHITESPACE:
            previous = char
    parts, start = [], 0
    for index in offsets:
        parts.append(text[start:index])
        start = index + 1
    return "".join([*parts, text[start:]]), offsets


def parse_layer(text, changes, recover):
    try:
        return strict_loads(text)
    except json.JSONDecodeError:
        if not recover:
            raise
    fence = FENCE.fullmatch(text)
    if fence and not any(change["kind"] == "code_fence" for change in changes):
        text = fence.group(1)
        changes.append({"kind": "code_fence"})
    repaired, offsets = trailing_commas(text)
    if offsets:
        changes.append({"kind": "trailing_commas", "offsets": offsets})
    return strict_loads(repaired)


def decode(content, *, recover=False):
    plan.require(len(content) <= MAX_JSON_BYTES, "Report JSON exceeds the size limit")
    changes = []
    try:
        text = content.decode(json.detect_encoding(content))
        value = parse_layer(text, changes, recover)
        if recover and isinstance(value, str):
            changes.append({"kind": "json_string"})
            value = parse_layer(value, changes, recover)
        plan.require(isinstance(value, dict), "Report JSON must contain exactly one object")
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    except RecursionError as error:
        raise plan.ManifestError("Report JSON is too deeply nested; reduce its nesting") from error
    repair = None if not changes else {
        "original_sha256": hashlib.sha256(content).hexdigest(),
        "decoded_identity": hashlib.sha256(encoded.encode()).hexdigest(),
        "changes": changes,
    }
    return value, repair


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks/scripts"))
        import plugin_config

        catalog = plugin_config.defaults()
        disabled = plugin_config.synchronize(str(args.project), catalog=catalog, persist=False, strict=True)
        value, repair = decode(read_bytes(args.report), recover=FEATURE in catalog and FEATURE not in disabled)
        print(json.dumps({"report": value, "json_repairs": repair}, indent=2))
        return 0
    except (OSError, ValueError) as error:
        print(f"report-json: {error}. Preserve the original and restate only its existing evidence; "
              "do not repeat the review.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
