#!/usr/bin/env python3
"""Keep private review reports and observed provenance in one cross-harness store."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from urllib.parse import urlsplit
from uuid import uuid4

import review_ledger as storage
import review_options


FEATURE = "review-records"
ROLES = ("lead", "coordinator", "reviewer", "adjudicator", "validator")
SOURCES = ("unavailable", "native-context", "native-transcript")
COLLECTIONS = {"findings", "candidates", "assessments", "rejected_candidates", "duplicates"}
MAX_BYTES = 16 * 1024 * 1024


def identifier(value):
    storage.require(isinstance(value, str) and 0 < len(value) <= 512 and
                    value == value.strip() and not any(ord(c) < 32 or ord(c) == 127 for c in value),
                    "Identifiers need bounded nonempty text without controls")
    return value


def observation(value, fields):
    storage.require(isinstance(value, dict) and value.keys() <= {*fields, "source", "evidence"},
                    "Unknown provenance fields")
    result = {name: identifier(value.get(name, "unknown")) for name in fields}
    result.update(source=value.get("source", "unavailable"), evidence=value.get("evidence", ""))
    storage.require(result["source"] in SOURCES and isinstance(result["evidence"], str),
                    "Invalid observation source or evidence")
    known = any(result[name] != "unknown" for name in fields)
    storage.require(not known or (result["source"] != "unavailable" and result["evidence"].strip()),
                    "Observed identities require native evidence; otherwise record unknown")
    return result


def enabled(root):
    config = review_options.plugin_config
    catalog = config.defaults()
    disabled = config.synchronize(str(root), catalog=catalog, persist=False, strict=True)
    return FEATURE in catalog and FEATURE not in disabled


def git_value(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)
    return result.stdout.decode().strip() if result.returncode == 0 else None


def repository(root):
    remote = git_value(root, "config", "--get", "remote.origin.url")
    canonical = None
    if remote:
        scp = re.fullmatch(r"(?:[^/@:]+@)?([^/:]+):(.+)", remote) if "://" not in remote else None
        parsed = urlsplit(f"ssh://{scp[1]}/{scp[2]}" if scp else remote)
        if parsed.scheme in ("https", "http", "ssh", "git") and parsed.hostname:
            port = parsed.port
            default = {"https": 443, "http": 80, "ssh": 22, "git": 9418}[parsed.scheme]
            host = parsed.hostname.lower() + (f":{port}" if port and port != default else "")
            canonical = host + "/" + parsed.path.strip("/").removesuffix(".git")
    if canonical is None:
        common = git_value(root, "rev-parse", "--git-common-dir")
        canonical = str((root / common).resolve()) if common else str(root)
    return {"key": storage.digest(canonical.encode()), "name": Path(canonical).name}


def private_directory(path):
    path = Path(path)
    if not path.exists():
        if not path.parent.exists():
            private_directory(path.parent)
        path.mkdir(mode=0o700, exist_ok=True)
    storage.require(path.is_dir() and not path.is_symlink(), "Private storage needs real directories")
    storage.require(path.stat().st_uid == os.getuid(), "Review storage must belong to the current user")
    os.chmod(path, 0o700)
    return path


def private_file(path):
    info = path.lstat()
    storage.require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid(),
                    "Review records must be owner-owned regular files")
    storage.require(info.st_size <= MAX_BYTES, "Review record exceeds the size limit")
    with path.open("rb") as handle:
        content = handle.read(MAX_BYTES + 1)
    storage.require(len(content) <= MAX_BYTES, "Review record exceeds the size limit")
    return content


def load(run):
    run = Path(os.path.abspath(run))
    storage.external_directory(run)
    storage.require(run.is_dir() and run.stat().st_uid == os.getuid() and
                    stat.S_IMODE(run.stat().st_mode) == 0o700,
                    "Run directory must be owner-only; restore its permissions and retry")
    path = storage.safe_path(run, "RUN.json")
    value = json.loads(private_file(path))
    storage.require(isinstance(value, dict), "Run record must be an object")
    storage.require(value.get("schema") == 1 and value.get("run_id") == run.name and
                    re.fullmatch(r"[a-f0-9]{32}", run.name), "Invalid review run identity or schema")
    storage.require(set(value) == {"schema", "run_id", "root", "repository", "target", "created_at",
                                  "harness", "roles", "reports"}, "Unknown or missing run fields")
    storage.require(Path(value["root"]).is_absolute(), "Run root must be absolute")
    identifier(value["target"])
    identifier(value["created_at"])
    storage.require(isinstance(value["repository"], dict) and
                    set(value["repository"]) == {"key", "name"} and
                    re.fullmatch(r"[a-f0-9]{64}", value["repository"]["key"]),
                    "Invalid repository identity")
    storage.require(isinstance(value.get("roles"), dict) and isinstance(value.get("reports"), list),
                    "Invalid review run records")
    storage.external_directory(run, Path(value["root"]))
    observation(value["harness"], ("name", "version"))
    for key, role in value["roles"].items():
        storage.require(role["role"] in ROLES and key == f"{role['role']}:{role['assignment']}" and
                        isinstance(role["observations"], list), "Invalid role record")
        identifier(role["assignment"])
        for observed in role["observations"]:
            storage.require(isinstance(observed, dict), "Role observation must be an object")
            observation({k: v for k, v in observed.items() if k != "harness"}, ("model", "effort"))
            observation(observed["harness"], ("name", "version"))
    return run, value


def initialize(root, target, context=None):
    root = Path(root).resolve()
    storage.require(root.is_dir(), "Review root must exist")
    worktree = git_value(root, "rev-parse", "--show-toplevel")
    root = Path(worktree).resolve() if worktree else root
    if not enabled(root):
        return {"enabled": False, "run_id": None, "directory": None, "scratch_directory": None}
    context = context or {}
    storage.require(context.keys() <= {"harness", "lead"}, "Unknown run context fields")
    harness = observation(context.get("harness", {}), ("name", "version"))
    lead = observation(context.get("lead", {}), ("model", "effort"))
    target = identifier(target)
    repo = repository(root)
    base = storage.external_directory(storage.state_directory() / "reviews" / "records", root)
    private_directory(base)
    target_key = storage.digest(target.encode())
    parent = private_directory(base / repo["key"] / target_key)
    folder = parent / uuid4().hex
    folder.mkdir(mode=0o700)
    for name in ("reports", "originals", "records"):
        (folder / name).mkdir(mode=0o700)
    value = {
        "schema": 1, "run_id": folder.name, "root": str(root), "repository": repo, "target": target,
        "created_at": datetime.now(timezone.utc).isoformat(), "harness": harness,
        "roles": {"lead:lead": {"role": "lead", "assignment": "lead", "worker": None,
                                "observations": [{**lead, "harness": harness}]}}, "reports": [],
    }
    storage.atomic_write(folder / "RUN.json", storage.encode(value))
    return {"enabled": True, "run_id": folder.name, "directory": str(folder),
            "scratch_directory": str(folder / "reports"), "record": value}


def find_runs(root, target):
    root = Path(root).resolve()
    parent = storage.external_directory(
        storage.state_directory() / "reviews" / "records" / repository(root)["key"] /
        storage.digest(identifier(target).encode()), root)
    result = []
    if not parent.exists():
        return result
    for folder in sorted(parent.iterdir()):
        if not re.fullmatch(r"[a-f0-9]{32}", folder.name):
            continue
        try:
            _, value = load(folder)
            result.append({"directory": str(folder), **{key: value[key] for key in
                           ("run_id", "created_at", "target", "harness")}})
        except (OSError, ValueError, KeyError, TypeError) as error:
            result.append({"directory": str(folder), "run_id": folder.name, "error": str(error)})
    return result


@contextmanager
def locked(folder):
    path = storage.safe_path(folder, ".lock")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(fd, "a") as handle:
        storage.require(stat.S_ISREG(os.fstat(fd).st_mode), "Review writer lock must be a regular file")
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def source_report(folder, entry):
    candidate = Path(os.path.abspath(entry["result_file"]))
    reports = folder / "reports"
    if candidate.is_relative_to(reports):
        path = storage.safe_path(reports, str(candidate.relative_to(reports)))
        content = private_file(path)
        os.chmod(path, 0o600)
        return str(path.relative_to(folder)), content
    storage.require(entry.get("external_report") is True,
                    "Reports must be inside this run's reports directory unless explicitly imported")
    storage.external_directory(candidate.parent)
    path = storage.safe_path(candidate.parent, candidate.name)
    content = private_file(path)
    destination = storage.safe_path(reports, f"imported-{storage.digest(content)}.json")
    if destination.exists():
        storage.require(private_file(destination) == content, "Imported report bytes changed")
    else:
        storage.atomic_write(destination, content)
    return str(path), content


def entries(document, provenance, pointer=""):
    result = []
    if isinstance(document, list):
        for index, item in enumerate(document):
            result.extend(entries(item, provenance, f"{pointer}/{index}"))
    elif isinstance(document, dict):
        for key, value in document.items():
            child = pointer + "/" + key.replace("~", "~0").replace("/", "~1")
            if key in COLLECTIONS and isinstance(value, list):
                result.extend({**provenance, "kind": key, "pointer": f"{child}/{index}", "record": item}
                              for index, item in enumerate(value))
            result.extend(entries(value, provenance, child))
    return result


def archive(folder, run_id, entry):
    source, content = source_report(folder, entry)
    key = storage.digest(content)
    original = storage.safe_path(folder, f"originals/{key}.json")
    if original.exists():
        storage.require(private_file(original) == content, "Retained report bytes changed")
    else:
        storage.atomic_write(original, content)
    provenance = {name: entry[name] for name in ("role", "assignment", "observation")}
    provenance["worker"] = entry.get("worker")
    provenance["run_id"] = run_id
    record = {**provenance, "source": source,
              "original": str(original.relative_to(folder)), "sha256": key, "entries": [], "error": None}
    try:
        document = json.loads(content)
        storage.require(not isinstance(document, dict) or document.get("run_id") in (None, run_id),
                        "Report names another run; retain its original provenance")
        record["entries"] = entries(document, provenance)
    except (ValueError, UnicodeError, RecursionError) as error:
        record["error"] = f"Original retained; report indexing unavailable: {error}"
    encoded = storage.encode(record)
    if len(encoded) > MAX_BYTES:
        record["entries"] = []
        record["error"] = "Original retained; report indexing unavailable: generated index exceeds the size limit"
        encoded = storage.encode(record)
    storage.require(len(encoded) <= MAX_BYTES, "Review record metadata exceeds the size limit")
    identity = storage.digest(encoded)
    destination = storage.safe_path(folder, f"records/{identity}.json")
    if destination.exists():
        storage.require(private_file(destination) == encoded, "Retained report index changed")
    else:
        storage.atomic_write(destination, encoded)
    return {**provenance, "record": str(destination.relative_to(folder)), "sha256": key,
            "error": record["error"]}


def record(run, entry):
    folder, value = load(run)
    if not enabled(value["root"]):
        return {"enabled": False, "run_id": value["run_id"]}
    storage.require(isinstance(entry, dict) and
                    {"role", "assignment"} <= entry.keys() <=
                    {"role", "assignment", "worker", "observation", "harness", "result_file", "external_report"},
                    "Unknown or missing role record fields")
    storage.require(entry["role"] in ROLES, "Unknown review role")
    identifier(entry["assignment"])
    storage.require(type(entry.get("external_report", False)) is bool, "External import must be a boolean")
    worker = entry.get("worker")
    if worker is not None:
        identifier(worker)
    observed = observation(entry.get("observation", {}), ("model", "effort"))
    observed["harness"] = observation(entry.get("harness", {}), ("name", "version"))
    with locked(folder):
        folder, value = load(folder)
        key = f"{entry['role']}:{entry['assignment']}"
        role = value["roles"].setdefault(key, {
            "role": entry["role"], "assignment": entry["assignment"],
            "worker": worker, "observations": [],
        })
        storage.require(role["worker"] in (None, worker) or worker is None,
                        "Worker changed; retain the original and use the new launch's assignment ID")
        role["worker"] = worker if worker is not None else role["worker"]
        if observed not in role["observations"]:
            role["observations"].append(observed)
        report = archive(folder, value["run_id"], {**entry, "observation": observed}) if entry.get(
            "result_file") else None
        if report is not None and report not in value["reports"]:
            value["reports"].append(report)
        storage.atomic_write(folder / "RUN.json", storage.encode(value))
    return {"enabled": True, "run_id": value["run_id"], "role": role, "report": report}


def add_observation_args(parser, names):
    for name in names:
        parser.add_argument("--" + name, default="unknown")
    parser.add_argument("--source", choices=SOURCES, default="unavailable")
    parser.add_argument("--evidence", default="")


def add_harness_args(parser):
    parser.add_argument("--harness", default="unknown")
    parser.add_argument("--harness-version", default="unknown")
    parser.add_argument("--harness-source", choices=SOURCES, default="unavailable")
    parser.add_argument("--harness-evidence", default="")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("init")
    start.add_argument("--root", type=Path, default=Path.cwd())
    start.add_argument("--target", required=True, help="stable target: pr:NUMBER, branch:NAME, or repository")
    add_harness_args(start)
    add_observation_args(start, ("model", "effort"))
    save = commands.add_parser("record")
    save.add_argument("run")
    save.add_argument("--role", required=True, choices=ROLES)
    save.add_argument("--assignment", required=True)
    save.add_argument("--worker")
    save.add_argument("--result-file")
    save.add_argument("--external-report", action="store_true",
                      help="copy a controller-pinned external report without modifying its original")
    add_observation_args(save, ("model", "effort"))
    add_harness_args(save)
    show = commands.add_parser("status")
    show.add_argument("run")
    find = commands.add_parser("list")
    find.add_argument("--root", type=Path, default=Path.cwd())
    find.add_argument("--target", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            _, result = load(args.run)
        elif args.command == "list":
            result = find_runs(args.root, args.target)
        else:
            observed = {name: getattr(args, name) for name in ("model", "effort", "source", "evidence")}
            harness = {name: getattr(args, "harness_" + name) for name in ("version", "source", "evidence")}
            harness["name"] = args.harness
            if args.command == "init":
                result = initialize(args.root, args.target, {"harness": harness, "lead": observed})
            else:
                entry = {name: getattr(args, name) for name in
                         ("role", "assignment", "worker", "result_file", "external_report")}
                result = record(args.run, {**entry, "observation": observed, "harness": harness})
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
        print(f"review-records: {error}. Retain reports in private external scratch and retry after "
              "repairing storage or the observation. A busy writer can be retried after it finishes. "
              "Storage failures do not invalidate review evidence or stop other authorized work.",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
