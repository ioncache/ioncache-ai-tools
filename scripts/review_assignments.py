#!/usr/bin/env python3
"""Build bounded review packets without launching workers or granting authority."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import sys


RESOURCES = Path(__file__).resolve().parent.parent / "skills" / "review-code"
PROJECT_ID = re.compile(r"project:[a-z0-9]+(?:-[a-z0-9]+)*\Z")
PLAN_SCHEMA = 2


def require(condition, message):
    if not condition:
        raise ValueError(message)


def text(value, name):
    require(isinstance(value, str) and bool(value.strip()), f"{name} needs nonempty text")
    return value


def strings(value, name):
    require(isinstance(value, list), f"{name} needs a list")
    for item in value:
        text(item, name)
    require(len(value) == len(set(value)), f"{name} contains duplicates")
    return value


def digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


def seal(value):
    return {**value, "identity": digest(value)}


def verify_identity(value):
    require(isinstance(value, dict), "Expected an object with an identity")
    require(value.get("identity") == digest({k: v for k, v in value.items() if k != "identity"}),
            "Artifact identity mismatch; recover the original or prepare a corrected record")


def verify_plan(plan):
    verify_identity(plan)
    require(plan.get("schema") == PLAN_SCHEMA,
            "Unsupported phase plan; retain original history and use a counted new phase "
            "for the changed applicability contract; other authorized work remains available")


def resource(name):
    path = (RESOURCES / name).resolve()
    require(path.is_relative_to(RESOURCES.resolve()), "Resource escapes the shipped directory")
    content = path.read_text()
    text(content, "Resource content")
    return {"source": str(path), "content": content, "identity": digest(content)}


def catalog():
    value = json.loads((RESOURCES / "categories.json").read_text())
    require(value["schema"] == 1, "Unsupported category catalog")
    ids = [item["id"] for item in value["categories"]]
    strings(ids, "Category IDs")
    return value


def project_source(value):
    require(isinstance(value, dict), "A project source must be an object")
    for key in ("source", "source_identity", "content", "applicability"):
        text(value.get(key), key)
    strings(value.get("exceptions"), "Project exceptions")
    return {**value, "content_identity": digest(value["content"])}


def effective_registry(request):
    features = request["review_options"]["configuration"]["review_features"]
    require(isinstance(features, dict), "Normalize current review configuration first")
    registry = {}
    for item in catalog()["categories"]:
        require(type(features.get(item["feature"])) is bool,
                f"Missing current configuration for {item['feature']}")
        registry[item["id"]] = {
            **item, "enabled": features[item["feature"]],
            "sources": [resource(item["source"])], "project_sources": [],
        }
    for descriptor in request.get("project_categories", []):
        require(isinstance(descriptor, dict), "Project category needs a descriptor")
        key = text(descriptor.get("id"), "Project category ID")
        require(PROJECT_ID.fullmatch(key) and key not in registry, "Invalid or duplicate project ID")
        text(descriptor.get("title"), "Project category title")
        registry[key] = {**descriptor, "enabled": True, "sources": [],
                         "assessment": [], "project_sources": [project_source(descriptor)]}
    for source in request.get("project_sources", []):
        require(isinstance(source, dict) and source.get("category") in registry,
                "Project source has an unregistered category")
        registry[source["category"]]["project_sources"].append(project_source(source))
    return registry


def exclusions(request, registry):
    values = request.get("exclusions", [])
    require(isinstance(values, list), "Exclusions must be a list")
    seen = set()
    for item in values:
        require(isinstance(item, dict) and item.get("category") in registry,
                "Exclusion has an unregistered category")
        require(item.get("authority") == "user", "Only a user-supplied instruction can exclude")
        text(item.get("instruction"), "Original user exclusion")
        text(item.get("source"), "Exclusion provenance")
        require(item["category"] not in seen, "Duplicate exclusion")
        seen.add(item["category"])
    return seen


def language_inventory(request):
    inventory = request.get("language_inventory", {})
    require(isinstance(inventory, dict) and inventory.keys() <= set(request["files"]),
            "Language inventory must name candidate files")
    for record in inventory.values():
        require(isinstance(record, dict) and set(record) == {"languages", "evidence"},
                "Language records need languages and evidence; omit unclassified files")
        languages = strings(record["languages"], "Source languages")
        require(all(name == name.strip().lower() and name not in ("unknown", "js", "jsx", "ts", "tsx")
                    for name in languages),
                "Use lowercase language names, including javascript/typescript; omit unknown files")
        text(record["evidence"], "Language evidence")
    return inventory


def technical_applicability(request, registry):
    inventory = language_inventory(request)
    unknown = [name for name in request["files"] if name not in inventory]
    decisions = {}
    for key, entry in registry.items():
        language = entry.get("language")
        if language is None:
            decisions[key] = {"status": "applicable", "language": None}
            continue
        text(language, "Category language prerequisite")
        require(language == language.strip().lower() and language not in ("unknown", "js", "jsx", "ts", "tsx"),
                "Use a lowercase language prerequisite, including javascript/typescript")
        matches = [name for name in request["files"]
                   if name in inventory and language in inventory[name]["languages"]]
        status = "applicable" if matches else "unknown" if unknown else "not_applicable"
        decisions[key] = {"status": status, "language": language,
                          "matching_files": matches, "unclassified_files": unknown}
    return decisions


def enabled_categories(request, registry):
    excluded = exclusions(request, registry)
    return [key for key, entry in registry.items() if entry["enabled"] and key not in excluded]


def private_result(request, filename):
    root = Path(request["root"]).resolve()
    scratch = Path(request["scratch_directory"]).resolve()
    path = Path(filename)
    require(path.is_absolute(), "Result path must be absolute")
    path = path.resolve()
    require(path.is_relative_to(scratch) and path != scratch and not path.is_relative_to(root),
            "Result must stay inside private scratch and outside the reviewed tree")
    return str(path)


def instruction_set(entry):
    sources = [resource("PROTOCOL.md"), *entry["sources"]]
    sources.append(resource("assessment/COMMON.md"))
    sources.extend(resource(name) for name in entry["assessment"])
    return seal({
        "category": entry["id"], "applicability": entry["applicability"],
        "sources": sources, "project_sources": entry["project_sources"],
        "precedence": "Approved project requirements override shipped defaults only in their "
                      "declared scope, below host/user authority. Unresolved equal-authority "
                      "conflicts remain evidence gaps, not invented exceptions.",
    })


def validate_context(request, registry):
    contexts = request.get("category_context", {})
    require(isinstance(contexts, dict) and contexts.keys() <= registry.keys(),
            "Category context must name registered purposes")
    for context in contexts.values():
        require(isinstance(context, dict) and set(context) == {"history", "settled_decisions"},
                "Category context needs history and settled_decisions")
        require(all(isinstance(value, list) for value in context.values()), "Context values need lists")
    correction = request.get("correction")
    if request["kind"] == "full":
        require(correction is None, "A full review must not inherit a focused correction delta")
        return
    require(isinstance(correction, dict) and set(correction) == {"before", "after", "delta"},
            "A focused request needs correction before, after and delta")
    text(correction["before"], "Correction before snapshot")
    require(correction["after"] == request["snapshot"], "Correction after snapshot mismatch")
    require(isinstance(correction["delta"], list), "Correction delta must contain the complete diff records")


def freeze_existing(registry, previous, request):
    if previous is None:
        return {}
    verify_plan(previous)
    for key in ("objective", "kind", "target", "base", "snapshot", "root", "files", "constraints",
                "scratch_directory"):
        require(request[key] == previous["request"][key],
                f"Changed {key} requires a new phase, not relabeled coverage")
    require(request.get("replacement_rounds", 1) == previous["replacement_rounds"],
            "A phase revision cannot reset replacement bounds")
    require(request.get("correction") == previous["request"].get("correction"),
            "Changed correction requires a new phase")
    inventory = language_inventory(request)
    for name, old in language_inventory(previous["request"]).items():
        require(inventory.get(name) == old,
                "Retain frozen language evidence or request a counted new phase")
    require(previous["registry"].keys() <= registry.keys(),
            "Retain prior descriptors and use an explicit exclusion instead of deleting a category")
    for key, old in previous["registry"].items():
        require(request.get("category_context", {}).get(key) ==
                previous["request"].get("category_context", {}).get(key),
                "Retain frozen category context or request a counted new phase")
        require(registry[key]["project_sources"] == old["project_sources"],
                "Retain frozen project instructions or request a counted new phase")
        registry[key] = {**copy.deepcopy(old), "enabled": registry[key]["enabled"]}
    return copy.deepcopy(previous["packets"])


def prepare(request, previous=None):
    require(isinstance(request, dict), "Request must be an object")
    request = copy.deepcopy(request)
    required = {"objective", "kind", "target", "base", "snapshot", "root", "files",
                "constraints", "scratch_directory", "review_options"}
    optional = {"project_categories", "project_sources", "exclusions", "replacement_rounds",
                "correction", "category_context", "language_inventory"}
    require(required <= request.keys() <= required | optional, "Unknown or missing request fields")
    for key in ("objective", "target", "base", "snapshot", "root", "scratch_directory"):
        text(request[key], key)
    require(request["kind"] in ("full", "focused"), "Review kind must be full or focused")
    strings(request["files"], "Candidate files")
    strings(request["constraints"], "Constraints")
    require(Path(request["root"]).is_absolute() and Path(request["root"]).is_dir(),
            "Review root must be an existing absolute directory")
    require(Path(request["scratch_directory"]).is_absolute(), "Scratch must be absolute")
    require(request["review_options"]["configuration"]["skill_enabled"] is True,
            "The requested review workflow is disabled; do not launch it")
    rounds = request.get("replacement_rounds", 1)
    require(type(rounds) is int and rounds >= 0, "Replacement rounds must be a finite nonnegative integer")
    registry = effective_registry(request)
    validate_context(request, registry)
    packets = freeze_existing(registry, previous, request)
    applicability = technical_applicability(request, registry)
    required_categories = []
    for key in enabled_categories(request, registry):
        entry = registry[key]
        if applicability[key]["status"] != "applicable":
            continue
        required_categories.append(key)
        if key in packets:
            continue
        filename = Path(request["scratch_directory"]) / f"{key.replace(':', '-')}-initial.json"
        packets[key] = seal({
            **{k: request[k] for k in required - {"review_options", "scratch_directory", "files"}},
            "candidate_files": request["files"], "scope_files": request["files"],
            "review_type": key, "assignment": f"{key}-initial",
            "instruction_set": instruction_set(entry),
            "technical_applicability": applicability[key],
            "correction": request.get("correction"),
            "context": request.get("category_context", {}).get(
                key, {"history": [], "settled_decisions": []}),
            "result_file": private_result(request, filename),
        })
    return seal({"schema": PLAN_SCHEMA, "request": request, "registry": registry,
                 "technical_applicability": applicability, "packets": packets,
                 "required": required_categories, "replacement_rounds": rounds})


def derive_packet(plan, category, assignment, filename, files=None, *, archived=False):
    verify_plan(plan)
    require(category in plan["packets"] and (archived or category in plan["required"]),
            "Category is not required by this phase plan")
    value = copy.deepcopy(plan["packets"][category])
    value.pop("identity")
    value["assignment"] = text(assignment, "Assignment")
    value["result_file"] = private_result(plan["request"], filename)
    value["scope_files"] = value["candidate_files"] if files is None else strings(files, "Shard files")
    require(set(value["scope_files"]) <= set(value["candidate_files"]), "Shard widens candidate scope")
    require(bool(value["scope_files"]) or not value["candidate_files"], "An empty shard cannot skip work")
    return seal(value)


def verify_packet(plan, packet):
    verify_identity(packet)
    category = packet["review_type"]
    require(category in plan["packets"], "Packet category is not required or registered")
    expected = derive_packet(plan, category, packet["assignment"], packet["result_file"],
                             packet["scope_files"], archived=True)
    require(packet == expected, "Packet changed frozen instructions, constraints or scope")


def checked_attempt(plan, attempt):
    require(isinstance(attempt, dict), "Attempt must be an object")
    text(attempt.get("id"), "Attempt ID")
    packet = attempt["packet"]
    verify_packet(plan, packet)
    number = attempt["round"]
    require(type(number) is int and 0 <= number <= plan["replacement_rounds"],
            "Replacement allowance exceeded; report incomplete and continue other authorized work")
    source = attempt["observation"]
    require(source["kind"] in ("native", "caller"), "Observation must distinguish native from caller")
    text(source["source"], "Observation source")
    worker = attempt["worker"]
    require(worker is None or (isinstance(worker, str) and bool(worker.strip())),
            "Worker identity must be observed text or null")
    require("result" in attempt, "Attempt must retain its result or explicit null")
    return attempt


def checked_result(attempt):
    packet, worker = attempt["packet"], attempt["worker"]
    result = attempt["result"]
    if result is not None:
        require(isinstance(result, dict), "Result must be an object or null")
        for field in ("assignment", "review_type", "snapshot"):
            require(result.get(field) == packet[field], f"Result {field} mismatch")
        require(result.get("instruction_set") == packet["instruction_set"]["identity"],
                "Result instruction identity mismatch")
        require(result.get("packet_identity") == packet["identity"], "Result packet identity mismatch")
        require("worker" in result and (result["worker"] is None or result["worker"] == worker),
                "Result worker contradicts the observed identity")
        require(result.get("origin") == "specialist", "Category results require specialist origin")
        require(isinstance(result.get("selection"), dict), "Missing selection observations")
        require(result.get("outcome") in ("complete", "partial", "failed"), "Invalid result outcome")
        require(isinstance(result.get("candidates"), list), "Missing candidate records")
        strings(result.get("limitations"), "Result limitations")
        require(isinstance(result.get("coverage"), dict), "Missing coverage record")
        require(result["coverage"].get("isolation") in
                ("uncontaminated", "contaminated", "unknown"), "Missing isolation observation")
        owned = strings(result["coverage"].get("files"), "Coverage files")
        require(set(owned) == set(packet["scope_files"]), "Shard coverage differs from assignment")


def attempt_index(plan, records, errors):
    require(isinstance(records, list), "Attempts must be a chronological list")
    indexed, workers, paths, assignments, partitions, rounds = {}, set(), set(), set(), set(), {}
    owned = {}
    for record in records:
        try:
            attempt = checked_attempt(plan, record)
            key, packet, worker = attempt["id"], attempt["packet"], attempt["worker"]
            category, number = packet["review_type"], attempt["round"]
            partition = (category, number, tuple(sorted(packet["scope_files"])))
            require(key not in indexed, "Duplicate attempt ID")
            require(packet["assignment"] not in assignments, "Assignment reused for another attempt")
            reused_worker = worker is not None and worker in workers
            require(packet["result_file"] not in paths, "Result path reused")
            require(partition not in partitions, "Renaming an identical attempt cannot reset allowance")
            require(not owned.get((category, number), set()).intersection(packet["scope_files"]),
                    "Repeated owned files require another replacement round, not renamed shards")
            require(number >= rounds.get(category, 0), "Category replacement round was reset")
            require(number <= rounds.get(category, -1) + 1, "Missing earlier attempt history")
            indexed[key] = dict(attempt, result_error=None)
            if worker is not None:
                workers.add(worker)
            paths.add(packet["result_file"])
            assignments.add(packet["assignment"])
            partitions.add(partition)
            owned.setdefault((category, number), set()).update(packet["scope_files"])
            rounds[category] = number
            try:
                require(not reused_worker, "Observed worker context reused")
                checked_result(attempt)
            except (KeyError, TypeError, ValueError) as error:
                indexed[key]["result_error"] = str(error)
        except (KeyError, TypeError, ValueError) as error:
            errors.append(f"Attempt record: {error}")
    return indexed, workers, rounds


def active_coverage(plan, active, indexed, errors, limitations):
    require(isinstance(active, dict), "Active map must be a caller-owned object")
    require(set(active) <= set(plan["required"]), "Active map contains an unrequired category")
    missing = []
    for category in plan["required"]:
        files, complete = set(), bool(active.get(category))
        for key in strings(active.get(category, []), "Active attempts"):
            attempt = indexed.get(key)
            if attempt is None or attempt["packet"]["review_type"] != category:
                errors.append("Active attempt is missing or belongs to another category")
                complete = False
                continue
            if attempt["result_error"]:
                errors.append(f"Active attempt {key}: {attempt['result_error']}")
                complete = False
                continue
            result = attempt["result"]
            if result is None or result["outcome"] != "complete":
                complete = False
                continue
            coverage = result["coverage"]
            files.update(coverage["files"])
            complete &= coverage["isolation"] != "contaminated"
            if coverage["isolation"] == "unknown" or attempt["worker"] is None:
                limitations.append(f"{category}: native identity or hidden-context visibility is limited")
            limitations.extend(result["limitations"])
        if not complete or files != set(plan["request"]["files"]):
            missing.append(category)
    return missing


def check(plan, handoff):
    verify_plan(plan)
    require(isinstance(handoff, dict) and set(handoff) ==
            {"history_complete", "attempts", "active", "other_workers"}, "Invalid handoff fields")
    applicability = technical_applicability(plan["request"], plan["registry"])
    require(plan["technical_applicability"] == applicability, "Technical applicability mismatch")
    enabled = enabled_categories(plan["request"], plan["registry"])
    required = {key for key in enabled if applicability[key]["status"] == "applicable"}
    unresolved = [key for key in enabled if applicability[key]["status"] == "unknown"]
    require(required == set(strings(plan["required"], "Required categories")) and
            required <= plan["packets"].keys() <= plan["registry"].keys(),
            "Required category roster mismatch")
    errors, limitations = [], []
    if unresolved:
        errors.append("Inspect unclassified source languages and extend language_inventory using "
                      "prepare --previous before dispatching: " + ", ".join(unresolved) +
                      "; completed categories and other authorized work remain available")
    if handoff["history_complete"] is not True:
        errors.append("Attempt history is incomplete; do not refund unknown spending")
    indexed, workers, rounds = attempt_index(plan, handoff["attempts"], errors)
    limitations.extend(f"{key}: unusable attempt retained: {attempt['result_error']}"
                       for key, attempt in indexed.items() if attempt["result_error"])
    require(isinstance(handoff["other_workers"], list), "Other workers must be a list")
    roles = set()
    for other in handoff["other_workers"]:
        require(other["role"] in ("coordinator", "adjudicator", "validator"), "Invalid other-worker role")
        roles.add(other["role"])
        worker = other["worker"]
        require(worker is None or (isinstance(worker, str) and bool(worker.strip())),
                "Invalid other-worker identity")
        if worker is not None and worker in workers:
            errors.append("Observed worker context reused across review roles")
        if worker is not None:
            workers.add(worker)
        else:
            limitations.append(f"{other['role']}: native worker identity is not exposed")
    if "adjudicator" not in roles:
        errors.append("Record the separately completed adjudicator, then check the final handoff; "
                      "do not repeat completed discovery categories")
    missing = active_coverage(plan, handoff["active"], indexed, errors, limitations)
    return {"structurally_complete": not errors and not missing,
            "missing_categories": missing, "errors": errors, "limitations": limitations,
            "unresolved_applicability": unresolved,
            "replacement_rounds_used": rounds,
            "evidence_limit": "Record checks do not prove native launches, instruction purity, "
                              "semantic trace completeness, adjudication or evidence truth."}


def read_json(path):
    return json.loads(Path(path).read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("request")
    prepare_parser.add_argument("--previous")
    packet_parser = commands.add_parser("packet")
    packet_parser.add_argument("plan")
    packet_parser.add_argument("category")
    packet_parser.add_argument("--assignment", required=True)
    packet_parser.add_argument("--result-file", required=True)
    packet_parser.add_argument("--file", action="append")
    check_parser = commands.add_parser("check")
    check_parser.add_argument("plan")
    check_parser.add_argument("handoff")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            previous = read_json(args.previous) if args.previous else None
            value = prepare(read_json(args.request), previous)
        elif args.command == "packet":
            value = derive_packet(read_json(args.plan), args.category, args.assignment,
                                  args.result_file, args.file)
        else:
            value = check(read_json(args.plan), read_json(args.handoff))
        print(json.dumps(value, indent=2))
        return 1 if value.get("structurally_complete") is False else 0
    except (OSError, KeyError, TypeError, ValueError) as error:
        print(f"review-assignments: {error}. Repair the request/evidence or report incomplete; "
              "other authorized work remains available.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
