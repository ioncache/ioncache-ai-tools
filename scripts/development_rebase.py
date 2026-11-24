"""Verify a rebased snapshot using isolated Git objects and the retained review."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace

import development_manifest as plan
import review_ledger as review


def git(context, arguments, content=None):
    try:
        result = subprocess.run(
            ["git", "--no-pager", "-C", str(context["root"]), "-c", "core.splitIndex=false",
             "-c", "core.fsmonitor=false", *arguments],
            input=content, capture_output=True, env=context["environment"], timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise plan.ManifestError(f"Rebase verification unavailable: {error}. "
                                 "Restore Git availability and retry without changing review history.") from error
    plan.require(result.returncode == 0, "Rebase verification unavailable: " +
                 result.stderr.decode(errors="replace").strip() +
                 ". Restore the required Git objects/tools and retry without changing review history.")
    return result.stdout


def context(root, directory):
    objects = directory / "git-objects"
    objects.mkdir()
    source = (root / os.fsdecode(review.git(root, ["rev-parse", "--git-path", "objects"])).strip()).resolve()
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(GIT_INDEX_FILE=str(directory / "index"), GIT_OBJECT_DIRECTORY=str(objects),
                       GIT_ALTERNATE_OBJECT_DIRECTORIES=json.dumps(str(source), ensure_ascii=False),
                       GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
                       GIT_NO_REPLACE_OBJECTS="1", GIT_NO_LAZY_FETCH="1")
    return {"root": root, "environment": environment}


def snapshot_tree(git_context, snapshot, folder):
    entries, objects = [], {}
    for name, entry in sorted(snapshot["files"].items()):
        key = entry["blob"]
        if key not in objects:
            content = review.blob(folder, entry)
            plan.require(review.digest(content) == key, "Snapshot blob changed during rebase verification")
            objects[key] = git(git_context, ["hash-object", "-w", "--stdin"], content).strip()
        entries.append(entry["mode"].encode() + b" " + objects[key] + b"\t" + os.fsencode(name) + b"\0")
    git(git_context, ["read-tree", "--empty"])
    git(git_context, ["update-index", "-z", "--index-info"], b"".join(entries))
    return git(git_context, ["write-tree"]).decode().strip()


def patch_identity(git_context, base, tree):
    patch = git(git_context, [
        "diff", "--binary", "--full-index", "--no-renames", "--no-ext-diff", "--no-textconv",
        "--no-color", "--no-relative", "--src-prefix=a/", "--dst-prefix=b/", "--unified=3",
        "--diff-algorithm=myers", "--no-indent-heuristic", base, tree, "--",
    ])
    output = git(git_context, ["patch-id", "--verbatim"], patch).split()
    plan.require((not patch and not output) or (bool(patch) and len(output) == 2),
                 "Rebase verification unavailable: Git did not return one patch identity; "
                 "restore Git support and retry without changing review history")
    return {"patch_id": output[0].decode() if output else "empty", "diff_sha256": plan.digest(patch)}


def verify(root, reviewed, new_base):
    path = Path(reviewed["ledger"])
    retained = review.status(SimpleNamespace(ledger=str(path)), root)
    plan.require(retained["outcome"] in ("completed", "completed_with_exceptions") and
                 retained["history"] == reviewed["history"] and retained["snapshot"] == reviewed["snapshot"] and
                 retained["base"] == reviewed["base"],
                 "The retained ledger no longer matches accepted review history")
    ledger, _ = review.load(path)
    original = ledger["snapshots"][reviewed["snapshot"]]
    with tempfile.TemporaryDirectory(prefix="rebase-check-", dir=path.parent) as temporary:
        directory = Path(temporary)
        current_folder = directory / "current"
        current_folder.mkdir()
        current = review.snapshot(root, current_folder)
        git_context = context(root, directory)
        old_tree = snapshot_tree(git_context, original, path.parent)
        new_tree = snapshot_tree(git_context, current, current_folder)
        before = patch_identity(git_context, reviewed["base"], old_tree)
        after = patch_identity(git_context, new_base, new_tree)
        plan.require(before["patch_id"] == after["patch_id"],
                     "Rebased patch differs from the reviewed patch; preserve the changes and use "
                     "reconcile for a counted review if allowance remains")
        plan.require(current == review.snapshot(root), "Worktree changed during rebase verification; retry")
    return current, {"method": "git-patch-id-verbatim-with-snapshot-trees",
                     "reviewed_patch": before, "rebased_patch": after}
