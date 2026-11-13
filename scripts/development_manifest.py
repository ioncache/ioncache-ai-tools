"""Validate approved development inputs without choosing services or running tools."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from graphlib import CycleError, TopologicalSorter


class ManifestError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ManifestError(message)


def fields(value, names):
    require(isinstance(value, dict) and set(value) == set(names.split()),
            f"Expected fields: {names}")


def text(value):
    require(isinstance(value, str) and bool(value.strip()), "Expected non-empty text")
    return value


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9-]*", value),
            "IDs must start with a lowercase letter and contain only letters, digits, and hyphens")
    return value


def strings(value, *, empty=False):
    require(isinstance(value, list) and (empty or bool(value)), "Expected a text list")
    for item in value:
        text(item)
    require(len(value) == len(set(value)), "Duplicate list entries")
    return value


def relative(value, *, root=False):
    text(value)
    if value == "." and root:
        return value
    path = PurePosixPath(value)
    require(bool(path.parts) and not path.is_absolute() and path.as_posix() == value and
            all(part not in (".", "..", ".git", ".review-loop") for part in path.parts),
            f"Unsafe or non-normalized relative path: {value}")
    require("\\" not in value and not any(char in value for char in "\0\r\n"),
            f"Unsupported path: {value!r}")
    return value


def encode(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def indexed(items):
    require(isinstance(items, list) and bool(items), "Expected a non-empty record list")
    result = {}
    for item in items:
        require(isinstance(item, dict) and "id" in item, "Record needs an ID")
        key = identifier(item["id"])
        require(key not in result, f"Duplicate ID: {key}")
        result[key] = item
    return result


def dependency_order(records):
    for key, item in records.items():
        strings(item["dependencies"], empty=True)
        require(set(item["dependencies"]) <= records.keys(), f"Unknown dependency for {key}")
        require(key not in item["dependencies"], f"Self dependency: {key}")
    try:
        return list(TopologicalSorter({key: item["dependencies"]
                                     for key, item in records.items()}).static_order())
    except CycleError as error:
        raise ManifestError("Dependency graph contains a cycle") from error


def checks(value):
    require(isinstance(value, list) and bool(value), "Acceptance checks are required")
    names = set()
    for check in value:
        fields(check, "name command cwd expected")
        for key in ("name", "command", "expected"):
            text(check[key])
        relative(check["cwd"], root=True)
        require(check["name"] not in names, "Duplicate acceptance check")
        names.add(check["name"])


def configuration(value):
    fields(value, "planning design execution")
    for concern in ("planning", "design"):
        fields(value[concern], "provider location")
        for item in value[concern].values():
            text(item)
    fields(value["execution"], "provider environment")
    for item in value["execution"].values():
        text(item)


def artifacts(value, folder):
    records = indexed(value)
    roles = set()
    for item in records.values():
        fields(item, "id role source snapshot sha256")
        require(item["role"] in ("requirements", "design", "plan"), "Unknown artifact role")
        roles.add(item["role"])
        text(item["source"])
        relative(item["snapshot"])
        require(isinstance(item["sha256"], str) and
                re.fullmatch(r"[a-f0-9]{64}", item["sha256"]), "Invalid artifact digest")
        path = folder / item["snapshot"]
        require(path.resolve().is_relative_to(folder.resolve()), "Artifact escapes its bundle")
        require(path.is_file() and not path.is_symlink(), "Artifact snapshot must be a regular file")
        require(digest(path.read_bytes()) == item["sha256"], f"Artifact changed: {item['id']}")
    require(roles == {"requirements", "design", "plan"}, "Requirements, design, and plan snapshots are required")
    return records


def pull_requests(value):
    records = indexed(value)
    branches, worktrees = set(), set()
    for item in records.values():
        fields(item, "id goal branch worktree base target dependencies checks rollout")
        text(item["goal"])
        text(item["rollout"])
        relative(item["worktree"])
        require(item["worktree"] not in worktrees, "PR worktrees must be distinct")
        worktrees.add(item["worktree"])
        for key in ("branch", "target"):
            text(item[key])
            require(not item[key].startswith("-"), "Branch cannot be an option")
        require(item["branch"] not in branches, "PR branches must be distinct")
        branches.add(item["branch"])
        require(isinstance(item["base"], str) and
                re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", item["base"]), "Pin a full base commit")
        checks(item["checks"])
    dependency_order(records)
    roots = [PurePosixPath(item["worktree"]) for item in records.values()]
    require(all(not left.is_relative_to(right) for left in roots for right in roots if left != right),
            "PR worktrees cannot overlap")
    return records


def tasks(value, prs, sources):
    records = indexed(value)
    for item in records.values():
        fields(item, "id pr goal paths dependencies artifacts checks compatibility completion")
        require(item["pr"] in prs, "Unknown PR")
        for key in ("goal", "compatibility", "completion"):
            text(item[key])
        strings(item["paths"])
        for path in item["paths"]:
            relative(path, root=True)
        strings(item["artifacts"])
        require(set(item["artifacts"]) <= sources.keys(), "Unknown task artifact")
        checks(item["checks"])
    dependency_order(records)
    require({item["pr"] for item in records.values()} == prs.keys(), "Every PR needs a task")
    for item in records.values():
        for dependency in item["dependencies"]:
            other = records[dependency]["pr"]
            require(other == item["pr"] or other in prs[item["pr"]]["dependencies"],
                    "Cross-PR task dependencies also require an explicit PR dependency")
    return records


def validate(manifest, folder):
    fields(manifest, "schema objective configuration repository artifacts tasks prs limits permissions constraints")
    require(type(manifest["schema"]) is int and manifest["schema"] == 1, "Unsupported manifest schema")
    text(manifest["objective"])
    strings(manifest["constraints"])
    configuration(manifest["configuration"])
    fields(manifest["repository"], "remote url default_branch")
    for value in manifest["repository"].values():
        text(value)
        require(not value.startswith("-") and not any(char in value for char in "\0\r\n"),
                "Repository values cannot be options or contain control characters")
    fields(manifest["limits"], "assignments attempts review_loops fix_cycles review_dispatches")
    for value in manifest["limits"].values():
        require(type(value) is int and value > 0, "Limits must be positive integers")
    fields(manifest["permissions"], "commit push create_pr mark_ready screenshots")
    require(all(type(value) is bool for value in manifest["permissions"].values()),
            "Permissions must be explicit booleans")
    sources = artifacts(manifest["artifacts"], folder)
    prs = pull_requests(manifest["prs"])
    require(all(item["branch"] != manifest["repository"]["default_branch"] and
                item["branch"] != item["target"] for item in prs.values()),
            "Owned branches cannot be the default or target branch")
    tasks(manifest["tasks"], prs, sources)
    return {"manifest": manifest, "identity": digest(encode(manifest))}


def read(path):
    path = Path(path).resolve()
    return validate(json.loads(path.read_bytes()), path.parent)
