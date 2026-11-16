"""Validate role choices and retain bounded, private native model observations."""

import json
from pathlib import Path
import re
import time

import development_manifest as plan
import review_ledger as review
import review_options


ROLES = ("development-control", "preflight", "prepare", "implement", "review-owner",
         "reviewer", "adjudicator", "validator", "fixer", "commit", "draft",
         "audit-initial", "audit-final", "evidence", "ready")
REVIEW_ROLES = {"review-owner": "lead", "adjudicator": "lead",
                "reviewer": "reviewer", "validator": "validator"}
SOURCES = ("unavailable", "native-context", "native-transcript")
MODEL_FIELDS = ("selected_model", "selected_effort", "actual_model", "actual_effort")


def native_value(value):
    plan.require(value is None or (isinstance(value, str) and 0 < len(value) <= 256 and
                 value == value.strip() and not any(ord(char) < 32 or ord(char) == 127 for char in value)),
                 "Native model/effort identifiers must be nonempty text without controls")
    return value


def configuration(execution):
    choices = execution.get("models", {})
    plan.require(isinstance(choices, dict) and choices.keys() <= set(ROLES), "Unknown model role")
    for choice in choices.values():
        plan.fields(choice, "model effort fallback")
        native_value(choice["model"])
        native_value(choice["effort"])
        plan.require(choice["fallback"] in ("configured", "fail"), "Unknown model fallback")
    values = execution.get("review_options", {})
    plan.require(isinstance(values, dict), "Review options must be an object")
    try:
        review_options.validate_values("review-validate-fix-loop", values)
    except (ValueError, SystemExit) as error:
        raise plan.ManifestError("Invalid execution review_options") from error


def review_choices(execution):
    values = execution.get("review_options", {})
    args = [f"--{name.replace('_', '-')}={value}" for name, value in values.items() if value is not None]
    return review_options.parse_options("review-validate-fix-loop", args)


def fallback_policy(execution, role, assignment=None):
    assignment = assignment or {}
    policy = assignment.get("model_selection") or {}
    review_role = REVIEW_ROLES.get(role)
    options = policy.get("review_options") or review_choices(execution)
    configured = policy.get("enabled") is False or (review_role and (
        policy.get("review_auto_enabled") is False or options.get("model_selection") == "configured"))
    choice = execution.get("models", {}).get(role) or (
        {"fallback": "configured"} if configured else assignment.get("launch_models", {}).get(role, {}))
    if review_role:
        normalized = options["roles"][review_role]
        if (normalized["model"] is not None or normalized["effort"] is not None or
                execution.get("review_options", {}).get("fallback") is not None):
            return normalized["fallback"]
    return choice.get("fallback", "fail")


def schedule_fallback(state, args):
    plan.require(state["outcome"] == "blocked" and state["active"] is None,
                 "Collect or retire the failed worker with native shutdown evidence before model fallback")
    plan.text(args.reason)
    plan.text(args.shutdown_evidence)
    previous = next((item for item in reversed(state["history"]) if item["key"] == args.key), None)
    plan.require(previous is not None and previous["outcome"] in ("blocked", "retired"),
                 "Model fallback needs a failed or retired assignment")
    plan.require(args.role == previous["role"] or
                 (previous["role"] == "review" and args.role in REVIEW_ROLES.keys() | {"fixer"}),
                 "Model fallback role does not match the assignment")
    execution = state["manifest"]["configuration"]["execution"]
    plan.require(fallback_policy(execution, args.role, previous) == "configured",
                 "The selected role requires failure or its launch fallback is unknown; "
                 "do not substitute a configured model")
    key = f"{args.key}:{args.role}"
    records = state.setdefault("model_fallbacks", {})
    plan.require(key not in records, "The role's configured fallback was already scheduled or consumed")
    records[key] = {"key": args.key, "role": args.role, "consumed": False,
                    "reason": args.reason, "shutdown_evidence": args.shutdown_evidence}


def consume_fallbacks(state, key):
    roles = []
    for record in state.get("model_fallbacks", {}).values():
        if record["key"] == key and not record["consumed"]:
            record["consumed"] = True
            roles.append(record["role"])
    return roles


def write(state, args):
    plan.require(args.call > 0, "Model observation needs a positive call number")
    plan.text(args.invocation)
    assignment = next((item for item in state["history"] if item["id"] == args.assignment), None)
    if args.role == "development-control":
        plan.require(args.assignment is None, "Control calls are not assignment workers")
    else:
        plan.require(assignment is not None and
                     (args.role == assignment["role"] or
                      (assignment["role"] == "review" and args.role in REVIEW_ROLES.keys() | {"fixer"})),
                     "Model observation does not match an assigned role")
    values = {name: native_value(getattr(args, name)) for name in MODEL_FIELDS}
    plan.require(args.source != "unavailable" or not (values["actual_model"] or values["actual_effort"]),
                 "An actual model/effort requires a native observation source")
    invocation = plan.digest(args.invocation.encode())
    folder = review.safe_path(Path(state["store"]), f"models/{invocation}")
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = review.safe_path(folder, f"{args.call:06d}.json")
    value = {"assignment": args.assignment, "role": args.role, "call": args.call,
             "source": args.source, "updated_at": time.time(), **values}
    if path.exists():
        old = read(path)
        plan.require(all(old[key] == value[key] for key in
                         ("assignment", "role", "call", "selected_model", "selected_effort")),
                     "Native call identity changed")
        if args.source == "unavailable" and old["source"] != "unavailable":
            return path
    review.atomic_write(path, plan.encode(value))
    return path


def read(path):
    plan.require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 8192,
                 "Model observation is not a regular bounded file")
    content = path.read_bytes()
    item = json.loads(content)
    plan.require(item["role"] in ROLES and item["source"] in SOURCES, "Invalid model observation")
    for name in MODEL_FIELDS:
        native_value(item[name])
    plan.require(item["source"] != "unavailable" or not (item["actual_model"] or item["actual_effort"]),
                 "Actual model lacks a native observation source")
    return {**item, "record_digest": plan.digest(content)}


def report_reference(state, assignment, reference):
    folder = Path(state["store"])
    candidate = Path(reference)
    plan.require(candidate.is_absolute() and candidate.is_relative_to(folder / "models"),
                 "Model report must be inside the private model directory")
    path = review.safe_path(folder, str(candidate.relative_to(folder)))
    item = read(path)
    plan.require(item["assignment"] == assignment["id"] and
                 item["role"] == ("review-owner" if assignment["role"] == "review" else assignment["role"]),
                 "Model report belongs to another assignment")


def observations(state, pr):
    folder = Path(state["store"])
    output, unavailable = [], False
    allowed = {item["id"] for item in state["history"] if item["pr"] in (None, pr)}
    try:
        base = review.safe_path(folder, "models")
        if not base.exists():
            return [], False
        for invocation in sorted(base.iterdir()):
            if not re.fullmatch(r"[a-f0-9]{64}", invocation.name):
                continue
            directory = review.safe_path(base, invocation.name)
            for entry in sorted(directory.iterdir()):
                if not re.fullmatch(r"[0-9]{6,}\.json", entry.name):
                    continue
                item = read(review.safe_path(directory, entry.name))
                if item["assignment"] is None or item["assignment"] in allowed:
                    output.append({"record_digest": item["record_digest"],
                                   **{name: item[name] for name in
                                      ("assignment", "role", "source", *MODEL_FIELDS)}})
    except (OSError, ValueError, KeyError, TypeError):
        unavailable = True
    return output, unavailable


def add_command(commands):
    command = commands.add_parser("model-report", help="Record requested and observed native model identity")
    command.add_argument("store")
    command.add_argument("--invocation", required=True)
    command.add_argument("--call", type=int, required=True)
    command.add_argument("--role", choices=ROLES, required=True)
    command.add_argument("--assignment")
    command.add_argument("--source", choices=SOURCES, default="unavailable")
    for name in MODEL_FIELDS:
        command.add_argument("--" + name.replace("_", "-"))
