#!/usr/bin/env python3
"""Resolve writing standards from the review registry without launching or judging work."""

import argparse
import copy
import json
from pathlib import Path
import shlex
import sys

import review_assignments as assignments

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks" / "scripts"))
import plugin_config


FEATURE = "writer-quality-guidance"
ROOT = Path(__file__).resolve().parents[1]
WRITING_SKILLS = {
    "security": "security", "code-complexity": "code-complexity",
    "comments": "comments", "jsdoc": "jsdoc", "unit-tests": "unit-tests",
    "documentation": "documentation-writing", "design-coherence": "engineering-judgment",
}


def configuration(root):
    catalog = plugin_config.defaults()
    disabled = plugin_config.synchronize(str(root), catalog=catalog, persist=False, strict=True)
    return {"enabled": FEATURE in catalog and FEATURE not in disabled,
            "disabled_skills": [name for name in disabled if name.startswith("skill:")],
            "review_features": {name: name not in disabled for name in catalog if name.startswith("review-")}}


def phase_request(phase, root):
    assignments.verify_plan(phase)
    assignments.require(Path(phase["request"]["root"]).resolve() == root,
                        "Writing plan belongs to another worktree; supply this fix batch's saved phase")
    return copy.deepcopy(phase["request"])


def prepare(inputs, settings):
    root = Path(inputs["root"]).resolve()
    phase, context = inputs.get("phase"), inputs.get("context")
    request = phase_request(phase, root) if phase is not None else {
        "files": [], "language_inventory": {},
        "review_options": {"configuration": {"review_features": settings["review_features"]}},
    }
    if context is not None:
        allowed = {"files", "language_inventory"} if phase is not None else {
            "files", "language_inventory", "project_sources", "project_categories"}
        assignments.require(isinstance(context, dict) and {"files", "language_inventory"} <= context.keys()
                            <= allowed, "Writing context needs files and language_inventory; "
                            "a fix cannot replace its frozen project standards")
        request.update(context)
    assignments.strings(request["files"], "Writing candidate files")
    registry = (phase["registry"] if phase is not None else
                assignments.effective_registry(request, Path(inputs.get("plugin_root", ROOT)) /
                                               "skills/review-code"))
    applicability = assignments.technical_applicability(request, registry)
    inventoried = phase is not None or context is not None
    standards, deferred, omitted = {}, {}, {}
    for key in assignments.enabled_categories(request, registry):
        entry = registry[key]
        skill = WRITING_SKILLS.get(key)
        if skill and f"skill:{skill}" in settings["disabled_skills"]:
            omitted[key] = f"skill:{skill} is disabled for writing; review coverage is unchanged"
            continue
        decision = applicability[key]
        if entry.get("language") and not inventoried:
            decision = {**decision, "status": "unknown"}
        if decision["status"] != "applicable":
            deferred[key] = decision
            continue
        standards[key] = {
            "applicability": entry["applicability"], "language": entry.get("language"),
            "sources": entry["sources"], "project_sources": entry["project_sources"],
        }
    return assignments.seal({
        "root": str(root), "review_plan": phase["identity"] if phase is not None else None,
        "standards": standards, "deferred": deferred, "omitted": omitted,
        "inventory_supplied": inventoried,
        "precedence": "Approved project requirements override shipped defaults only within their "
                      "declared scope, below host/user authority. Preserve source exceptions; "
                      "do not invent precedence for conflicting equal-authority requirements.",
    })


def read_phase(reference, root):
    assignments.require(isinstance(reference, dict) and set(reference) == {"path", "identity"} and
                        isinstance(reference["path"], str) and Path(reference["path"]).is_absolute(),
                        "Fixer writing_plan needs the saved phase's absolute path and identity. "
                        "Add them to this owner request and resubmit it; do not repeat review or widen the fix.")
    phase = assignments.read_json(Path(reference["path"]))
    phase_request(phase, root)
    assignments.require(phase["identity"] == reference["identity"],
                        "Writing plan changed; restore the referenced frozen phase and retry this request")
    return phase


def render(inputs, settings):
    if not settings["enabled"]:
        return ""
    plugin = Path(inputs.get("plugin_root", ROOT))
    command = ["python3", "-B", str(plugin / "scripts/writing_guidance.py"),
               "--root", str(inputs["root"])]
    reference = inputs.get("reference")
    if reference is not None:
        command.extend(["--plan", reference["path"], "--identity", reference["identity"]])
    command.extend(["--context", "/absolute/private/writing-context.json"])
    contract = (plugin / "skills/review-code/WRITING.md").read_text()
    return (contract + "\nResolve inspected context with: " + shlex.join(command) +
            "\nWriting standards: " + json.dumps(prepare(inputs, settings)))


def unavailable(error):
    return (f"Writing guidance unavailable: {error}. Continue the bounded assignment under its "
            "existing constraints and report this limitation, not a completed standards check.\n")


def job_guidance(assignment, request, executor):
    if request["role"] not in ("fixer", "implement"):
        return ""
    root = Path(assignment["root"]).resolve()
    try:
        settings = configuration(root)
    except (OSError, ValueError) as error:
        return unavailable(error)
    if not settings["enabled"]:
        return ""
    reference = request.get("writing_plan")
    phase = read_phase(reference, root) if request["role"] == "fixer" else None
    if phase is not None:
        assignments.require(phase["request"]["base"] == assignment["comparison_base"],
                            "Writing plan has another comparison base; supply this assignment's saved phase")
    try:
        return render({"root": str(root), "plugin_root": str(executor),
                       "phase": phase, "reference": reference}, settings) + "\n"
    except (OSError, ValueError) as error:
        return unavailable(error)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--identity")
    parser.add_argument("--context", type=Path)
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve()
        settings = configuration(root)
        if not settings["enabled"]:
            print("Writing guidance disabled; existing scope, checks and review obligations still apply.")
            return 0
        reference = {"path": str(args.plan), "identity": args.identity} if args.plan is not None else None
        phase = read_phase(reference, root) if reference is not None else None
        context = assignments.read_json(args.context) if args.context is not None else None
        print(render({"root": str(root), "phase": phase, "reference": reference,
                      "context": context}, settings))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Writing guidance unavailable: {error}. Repair the referenced input and rerun; "
              "retain the assignment and consumed allowances. Report the gap if unavailable; "
              "do not claim a completed standards check or block other authorized work.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
