#!/usr/bin/env python3
"""Check category records offline; these fixtures never launch model workers."""

import copy
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import review_assignments as assignments


HELPER = Path(__file__).with_name("review_assignments.py")


class ReviewAssignmentTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name)
        self.root = self.home / "project"
        self.root.mkdir()
        self.scratch = self.home / "private"
        self.scratch.mkdir()
        features = {row["feature"]: True for row in assignments.catalog()["categories"]}
        self.request = {
            "objective": "Exercise bounded review records", "kind": "full",
            "target": "repository", "base": "fixture-base", "snapshot": "fixture-snapshot",
            "root": str(self.root), "files": ["producer.py", "consumer.py"],
            "language_inventory": {
                name: {"languages": ["python"], "evidence": "Offline Python source fixture"}
                for name in ("producer.py", "consumer.py")
            },
            "constraints": ["Read-only target; no model launches"],
            "scratch_directory": str(self.scratch),
            "review_options": {"configuration": {"skill_enabled": True, "review_features": features}},
        }

    def attempt(self, packet, number=0, outcome="complete"):
        return {
            "id": packet["assignment"], "round": number, "packet": packet,
            "worker": f"fixture-{packet['assignment']}",
            "observation": {"kind": "caller", "source": "Offline fixture, not a native launch"},
            "result": {
                "assignment": packet["assignment"], "review_type": packet["review_type"],
                "instruction_set": packet["instruction_set"]["identity"],
                "packet_identity": packet["identity"], "snapshot": packet["snapshot"],
                "origin": "specialist", "selection": {"actual": "unknown"},
                "worker": f"fixture-{packet['assignment']}", "outcome": outcome,
                "coverage": {"files": packet["scope_files"], "isolation": "uncontaminated"},
                "candidates": [], "limitations": [],
            },
        }

    def handoff(self, plan):
        attempts = [self.attempt(packet) for packet in plan["packets"].values()]
        return {"history_complete": True, "attempts": attempts,
                "active": {item["packet"]["review_type"]: [item["id"]] for item in attempts},
                "other_workers": [{"role": "adjudicator", "worker": "fixture-adjudicator"}]}

    def packet(self, plan, name, files=None):
        return assignments.derive_packet(plan, "security", name, str(self.scratch / f"{name}.json"), files)

    def test_every_category_receives_whole_inventory_without_sibling_instructions(self):
        self.request["files"].append("client.js")
        self.request["language_inventory"]["client.js"] = {
            "languages": ["javascript"], "evidence": "Offline JavaScript source fixture",
        }
        plan = assignments.prepare(self.request)
        self.assertEqual(set(plan["packets"]), set(plan["registry"]))
        for key, packet in plan["packets"].items():
            self.assertEqual(packet["candidate_files"], self.request["files"])
            self.assertEqual(packet["scope_files"], self.request["files"])
            sources = packet["instruction_set"]["sources"]
            domain_paths = [source["source"] for source in sources if "/categories/" in source["source"]]
            self.assertEqual(domain_paths, [str(assignments.RESOURCES / plan["registry"][key]["source"])])
            policy_paths = [source["source"] for source in sources if "/assessment/" in source["source"]]
            expected = ["assessment/COMMON.md", *plan["registry"][key]["assessment"]]
            self.assertEqual(policy_paths, [str(assignments.RESOURCES / name) for name in expected])
            self.assertNotIn("skill_roles", json.dumps(packet))
        result = assignments.check(plan, self.handoff(plan))
        self.assertTrue(result["structurally_complete"], result)
        self.assertIn("do not prove", result["evidence_limit"])

    def test_project_requirements_override_only_within_one_registered_purpose(self):
        source = {"category": "unit-tests", "source": ".github/instructions/testing.md",
                  "source_identity": "original-file-id", "content": "API tests belong in apps/api/test",
                  "applicability": "apps/api/**", "exceptions": ["Use the API-specific test layout"]}
        self.request["project_sources"] = [source]
        self.request["project_categories"] = [{
            "id": "project:localization", "title": "Localization",
            "source": ".github/instructions/localization.md", "source_identity": "source-id",
            "content": "All displayed messages use the translation catalog.",
            "applicability": "apps/web/**", "exceptions": [],
        }]
        plan = assignments.prepare(self.request)
        self.assertIn("project:localization", plan["packets"])
        for key, packet in plan["packets"].items():
            self.assertEqual(source["content"] in json.dumps(packet), key == "unit-tests")
        self.assertIn("declared scope", plan["packets"]["unit-tests"]["instruction_set"]["precedence"])
        self.assertTrue(assignments.check(plan, self.handoff(plan))["structurally_complete"])
        self.request["project_sources"][0]["category"] = "not-registered"
        with self.assertRaisesRegex(ValueError, "unregistered"):
            assignments.prepare(self.request)

    def test_focused_delta_and_history_remain_bound_to_their_scope_and_category(self):
        self.request["kind"] = "focused"
        with self.assertRaisesRegex(ValueError, "focused request needs"):
            assignments.prepare(self.request)
        delta = {"before": "before-fix", "after": self.request["snapshot"],
                 "delta": [{"file": "producer.py", "diff": "complete fixture correction"}]}
        self.request["correction"] = delta
        self.request["category_context"] = {
            "security": {"history": ["security-history-marker"], "settled_decisions": []},
        }
        plan = assignments.prepare(self.request)
        for key, packet in plan["packets"].items():
            self.assertEqual(packet["correction"], delta)
            self.assertEqual("security-history-marker" in json.dumps(packet), key == "security")
        self.request["correction"]["after"] = "wrong-snapshot"
        self.assertEqual(plan["packets"]["security"]["correction"]["after"], "fixture-snapshot")
        with self.assertRaisesRegex(ValueError, "snapshot mismatch"):
            assignments.prepare(self.request)

    def test_user_exclusions_and_review_settings_remain_independent_of_language(self):
        self.request["review_options"]["configuration"]["review_features"]["review-security"] = False
        self.request["exclusions"] = [{"category": "comments", "authority": "user",
                                      "instruction": "Do not review comments", "source": "User turn 1"}]
        plan = assignments.prepare(self.request)
        self.assertNotIn("security", plan["packets"])
        self.assertNotIn("comments", plan["packets"])
        self.assertIn("documentation", plan["packets"])
        self.request["exclusions"][0]["authority"] = "predicted-not-applicable"
        with self.assertRaisesRegex(ValueError, "user-supplied"):
            assignments.prepare(self.request)
        self.request["exclusions"][0]["authority"] = "user"
        self.request["exclusions"][0]["source"] = ""
        with self.assertRaisesRegex(ValueError, "provenance"):
            assignments.prepare(self.request)
        self.request["exclusions"] = []
        self.request.pop("language_inventory")
        self.request["review_options"]["configuration"]["review_features"]["review-jsdoc"] = False
        plan = assignments.prepare(self.request)
        self.assertNotIn("jsdoc", plan["packets"])
        self.assertTrue(assignments.check(plan, self.handoff(plan))["structurally_complete"])

    def test_non_javascript_scopes_keep_general_review_without_a_jsdoc_worker(self):
        for name, languages in (("app.py", ["python"]), ("app.ts", ["typescript"]),
                                ("View.vue", ["html", "typescript"])):
            with self.subTest(name=name):
                request = copy.deepcopy(self.request)
                request["files"] = [name]
                request["language_inventory"] = {
                    name: {"languages": languages, "evidence": "Inspected fixture source language"},
                }
                plan = assignments.prepare(request)
                self.assertNotIn("jsdoc", plan["required"])
                self.assertNotIn("jsdoc", plan["packets"])
                self.assertEqual(plan["technical_applicability"]["jsdoc"]["status"], "not_applicable")
                self.assertTrue({"unit-tests", "documentation", "integration", "test-coverage",
                                 "security", "comments"} <= set(plan["required"]))
                self.assertTrue(assignments.check(plan, self.handoff(plan))["structurally_complete"])

    def test_mixed_and_embedded_javascript_keep_whole_inventory_and_one_purpose(self):
        self.request["files"].extend(["View.vue", "types.ts"])
        self.request["language_inventory"]["View.vue"] = {
            "languages": ["html", "javascript"], "evidence": "Inspected JavaScript script block",
        }
        plan = assignments.prepare(self.request)
        decision = plan["technical_applicability"]["jsdoc"]
        self.assertEqual(decision["status"], "applicable")
        self.assertEqual(decision["matching_files"], ["View.vue"])
        self.assertEqual(decision["unclassified_files"], ["types.ts"])
        packet = plan["packets"]["jsdoc"]
        self.assertEqual(packet["candidate_files"], self.request["files"])
        self.assertEqual(packet["scope_files"], self.request["files"])
        self.assertEqual(packet["technical_applicability"], decision)
        self.assertTrue(assignments.check(plan, self.handoff(plan))["structurally_complete"])

    def test_language_decisions_survive_sorted_serialization_and_preserve_spending(self):
        self.request["language_inventory"] = {
            "consumer.py": {"languages": ["javascript"], "evidence": "Synthetic embedded JavaScript"},
            "producer.py": {"languages": ["javascript"], "evidence": "Synthetic embedded JavaScript"},
        }
        plan = assignments.prepare(self.request)
        plan = json.loads(json.dumps(plan, sort_keys=True))
        handoff = self.handoff(plan)
        failed = next(row for row in handoff["attempts"] if row["packet"]["review_type"] == "security")
        failed["result"]["outcome"] = "failed"
        replacement = self.attempt(self.packet(plan, "security-replacement"), 1)
        handoff["attempts"].append(replacement)
        handoff["active"]["security"] = [replacement["id"]]
        result = assignments.check(plan, handoff)
        self.assertTrue(result["structurally_complete"], result)
        self.assertEqual(result["replacement_rounds_used"]["security"], 1)
        request = copy.deepcopy(self.request)
        request["review_options"]["configuration"]["review_features"]["review-jsdoc"] = False
        revised = assignments.prepare(request, plan)
        handoff["active"].pop("jsdoc")
        result = assignments.check(revised, handoff)
        self.assertTrue(result["structurally_complete"], result)
        self.assertEqual(result["replacement_rounds_used"]["security"], 1)
        self.assertEqual(revised["packets"]["jsdoc"], plan["packets"]["jsdoc"])

    def test_unknown_language_defers_only_specific_worker_and_recovers_without_replay(self):
        self.request["language_inventory"].pop("consumer.py")
        plan = assignments.prepare(self.request)
        handoff = self.handoff(plan)
        original = copy.deepcopy(handoff)
        self.assertNotIn("jsdoc", plan["packets"])
        pending = assignments.check(plan, handoff)
        self.assertFalse(pending["structurally_complete"])
        self.assertEqual(pending["unresolved_applicability"], ["jsdoc"])
        self.assertEqual(pending["missing_categories"], [])
        self.assertIn("other authorized work", " ".join(pending["errors"]))
        for languages in (["python"], ["javascript"]):
            with self.subTest(languages=languages):
                request = copy.deepcopy(self.request)
                request["language_inventory"]["consumer.py"] = {
                    "languages": languages, "evidence": "Completed fixture language inspection",
                }
                revised = assignments.prepare(request, plan)
                recovered = copy.deepcopy(handoff)
                for key, packet in plan["packets"].items():
                    self.assertEqual(revised["packets"][key], packet)
                if languages == ["javascript"]:
                    added = self.attempt(revised["packets"]["jsdoc"])
                    recovered["attempts"].append(added)
                    recovered["active"]["jsdoc"] = [added["id"]]
                result = assignments.check(revised, recovered)
                self.assertTrue(result["structurally_complete"], result)
                self.assertEqual(result["unresolved_applicability"], [])
        self.assertEqual(handoff, original)
        harmless = subprocess.run([sys.executable, "-c", "print('authorized work')"],
                                  cwd=self.root, capture_output=True, text=True, check=True)
        self.assertEqual(harmless.stdout, "authorized work\n")

    def test_language_evidence_is_required_for_absence_and_frozen_across_revisions(self):
        request = copy.deepcopy(self.request)
        request.pop("language_inventory")
        plan = assignments.prepare(request)
        self.assertEqual(plan["technical_applicability"]["jsdoc"]["status"], "unknown")
        request = copy.deepcopy(self.request)
        request["language_inventory"]["producer.py"]["evidence"] = ""
        with self.assertRaisesRegex(ValueError, "evidence"):
            assignments.prepare(request)
        request = copy.deepcopy(self.request)
        request["language_inventory"]["unowned.py"] = {
            "languages": ["python"], "evidence": "Outside inventory",
        }
        with self.assertRaisesRegex(ValueError, "candidate"):
            assignments.prepare(request)
        request = copy.deepcopy(self.request)
        for language in ("jsx", "javascript ", "unknown"):
            request["language_inventory"]["producer.py"]["languages"] = [language]
            with self.assertRaisesRegex(ValueError, "javascript/typescript"):
                assignments.prepare(request)
        plan = assignments.prepare(self.request)
        changed = copy.deepcopy(self.request)
        changed["language_inventory"]["producer.py"]["languages"] = ["javascript"]
        with self.assertRaisesRegex(ValueError, "new phase"):
            assignments.prepare(changed, plan)
        changed.pop("language_inventory")
        with self.assertRaisesRegex(ValueError, "new phase"):
            assignments.prepare(changed, plan)
        tampered = copy.deepcopy(plan)
        tampered["technical_applicability"]["jsdoc"]["status"] = "applicable"
        tampered.pop("identity")
        with self.assertRaisesRegex(ValueError, "applicability"):
            assignments.check(assignments.seal(tampered), self.handoff(plan))

    def test_legacy_plans_require_counted_reconciliation_not_silent_reinterpretation(self):
        plan = assignments.prepare(self.request)
        legacy = {**plan, "schema": 1}
        legacy.pop("identity")
        legacy = assignments.seal(legacy)
        for action in (lambda: assignments.prepare(self.request, legacy),
                       lambda: assignments.check(legacy, self.handoff(plan)),
                       lambda: self.packet(legacy, "legacy-retry")):
            with self.assertRaisesRegex(ValueError, "retain.*history.*new phase"):
                action()

    def test_partial_and_contaminated_passes_recover_with_one_fresh_replacement(self):
        plan = assignments.prepare(self.request)
        handoff = self.handoff(plan)
        first = handoff["attempts"][0]
        first["result"]["coverage"]["isolation"] = "contaminated"
        self.assertFalse(assignments.check(plan, handoff)["structurally_complete"])
        first["result"]["outcome"] = "partial"
        replacement = self.attempt(self.packet(plan, "security-replacement"), 1)
        handoff["attempts"].append(replacement)
        handoff["active"]["security"] = [replacement["id"]]
        recovered = assignments.check(plan, handoff)
        self.assertTrue(recovered["structurally_complete"], recovered)
        self.assertEqual(recovered["replacement_rounds_used"]["security"], 1)
        self.assertEqual(first["result"]["outcome"], "partial")

    def test_replacement_exhaustion_renaming_and_lost_history_do_not_refund_allowance(self):
        plan = assignments.prepare(self.request)
        handoff = self.handoff(plan)
        handoff["attempts"][0]["result"]["outcome"] = "failed"
        replacement = self.attempt(self.packet(plan, "security-replacement"), 1, "failed")
        handoff["attempts"].append(replacement)
        handoff["active"]["security"] = [replacement["id"]]
        result = assignments.check(plan, json.loads(json.dumps(handoff)))
        self.assertFalse(result["structurally_complete"])
        self.assertEqual(result["missing_categories"], ["security"])
        self.assertEqual(result["replacement_rounds_used"]["security"], 1)
        for number in (0, 1, 2):
            replay = copy.deepcopy(handoff)
            replay["attempts"].append(self.attempt(self.packet(plan, "renamed"), number))
            self.assertFalse(assignments.check(plan, replay)["structurally_complete"])
        replay = copy.deepcopy(handoff)
        shards = [self.attempt(self.packet(plan, f"resharded-{index}", [name]), 1)
                  for index, name in enumerate(self.request["files"])]
        replay["attempts"].extend(shards)
        replay["active"]["security"] = [row["id"] for row in shards]
        exhausted = assignments.check(plan, replay)
        self.assertFalse(exhausted["structurally_complete"])
        self.assertTrue(any("Repeated owned files require another replacement round" in error
                            for error in exhausted["errors"]), exhausted)
        handoff["history_complete"] = False
        self.assertIn("do not refund", assignments.check(plan, handoff)["errors"][0])
        harmless = subprocess.run([sys.executable, "-c", "print('authorized work')"],
                                  cwd=self.root, capture_output=True, text=True, check=True)
        self.assertEqual(harmless.stdout, "authorized work\n")

    def test_malformed_results_preserve_history_and_allow_a_fresh_replacement(self):
        plan = assignments.prepare(self.request)
        for field, value in (("selection", "configured default"),
                             ("instruction_set", {"identity": "not a string"})):
            with self.subTest(field=field):
                handoff = self.handoff(plan)
                first = handoff["attempts"][0]
                first["result"][field] = value
                original = copy.deepcopy(first)
                failed = assignments.check(plan, handoff)
                self.assertFalse(failed["structurally_complete"])
                self.assertEqual(failed["replacement_rounds_used"]["security"], 0)
                replacement = self.attempt(self.packet(plan, "security-replacement"), 1)
                handoff["attempts"].append(replacement)
                handoff["active"]["security"] = [replacement["id"]]
                recovered = assignments.check(plan, handoff)
                self.assertTrue(recovered["structurally_complete"], recovered)
                self.assertTrue(any(first["id"] in row for row in recovered["limitations"]))
                self.assertEqual(first, original)
                replacement["result"]["selection"] = "malformed replacement"
                exhausted = assignments.check(plan, handoff)
                self.assertFalse(exhausted["structurally_complete"])
                self.assertEqual(exhausted["replacement_rounds_used"]["security"], 1)
                for number in (0, 1, 2):
                    replay = copy.deepcopy(handoff)
                    replay["attempts"].append(self.attempt(self.packet(plan, "renamed"), number))
                    replay["active"]["security"] = ["renamed"]
                    self.assertFalse(assignments.check(plan, replay)["structurally_complete"])

    def test_discovery_alone_cannot_complete_the_final_handoff(self):
        plan = assignments.prepare(self.request)
        handoff = self.handoff(plan)
        handoff["other_workers"] = []
        pending = assignments.check(plan, handoff)
        self.assertFalse(pending["structurally_complete"])
        self.assertEqual(pending["missing_categories"], [])
        self.assertTrue(any("adjudicator" in error for error in pending["errors"]))
        handoff["other_workers"] = [{"role": "adjudicator", "worker": None}]
        complete = assignments.check(plan, handoff)
        self.assertTrue(complete["structurally_complete"], complete)
        self.assertTrue(any("adjudicator" in note for note in complete["limitations"]))

    def test_shards_share_instructions_and_require_full_union(self):
        plan = assignments.prepare(self.request)
        handoff = self.handoff(plan)
        handoff["attempts"] = handoff["attempts"][1:]
        shards = [self.attempt(self.packet(plan, f"security-shard-{index}", [name]))
                  for index, name in enumerate(self.request["files"])]
        handoff["attempts"].extend(shards)
        handoff["active"]["security"] = [row["id"] for row in shards]
        self.assertEqual(shards[0]["packet"]["instruction_set"], shards[1]["packet"]["instruction_set"])
        result = assignments.check(plan, handoff)
        self.assertTrue(result["structurally_complete"], result)
        self.assertIn("semantic trace", result["evidence_limit"])
        handoff["active"]["security"].pop()
        self.assertEqual(assignments.check(plan, handoff)["missing_categories"], ["security"])
        handoff["active"]["security"] = [row["id"] for row in shards]
        shards[1]["result"]["outcome"] = "partial"
        self.assertFalse(assignments.check(plan, handoff)["structurally_complete"])
        original = copy.deepcopy(shards[1])
        replacement = self.attempt(self.packet(plan, "security-replacement", ["consumer.py"]), 1)
        handoff["attempts"].append(replacement)
        handoff["active"]["security"] = [shards[0]["id"], replacement["id"]]
        recovered = assignments.check(plan, handoff)
        self.assertTrue(recovered["structurally_complete"], recovered)
        self.assertEqual(recovered["replacement_rounds_used"]["security"], 1)
        self.assertEqual(shards[1], original)
        self.assertIn(shards[1], handoff["attempts"])
        handoff["active"]["security"] = [replacement["id"]]
        self.assertEqual(assignments.check(plan, handoff)["missing_categories"], ["security"])

    def test_retired_reused_context_preserves_spending_and_allows_fresh_recovery(self):
        plan = assignments.prepare(self.request)
        handoff = self.handoff(plan)
        first, reused = handoff["attempts"][:2]
        reused["worker"] = reused["result"]["worker"] = first["worker"]
        original = copy.deepcopy(reused)
        category = reused["packet"]["review_type"]
        denied = assignments.check(plan, handoff)
        self.assertFalse(denied["structurally_complete"])
        self.assertEqual(denied["replacement_rounds_used"].get(category), 0)
        packet = assignments.derive_packet(
            plan, category, "fresh-replacement", str(self.scratch / "fresh-replacement.json"))
        replacement = self.attempt(packet, 1)
        handoff["attempts"].append(replacement)
        handoff["active"][category] = [replacement["id"]]
        recovered = assignments.check(plan, handoff)
        self.assertTrue(recovered["structurally_complete"], recovered)
        self.assertEqual(recovered["replacement_rounds_used"][category], 1)
        self.assertEqual(reused, original)
        self.assertTrue(any(reused["id"] in note and "context reused" in note
                            for note in recovered["limitations"]))
        handoff["active"][category] = [reused["id"]]
        self.assertFalse(assignments.check(plan, handoff)["structurally_complete"])
        handoff["active"][category] = [replacement["id"]]
        replacement["worker"] = replacement["result"]["worker"] = first["worker"]
        exhausted = assignments.check(plan, handoff)
        self.assertFalse(exhausted["structurally_complete"])
        self.assertEqual(exhausted["replacement_rounds_used"][category], 1)
        packet = assignments.derive_packet(
            plan, category, "over-budget", str(self.scratch / "over-budget.json"))
        handoff["attempts"].append(self.attempt(packet, 2))
        handoff["active"][category] = ["over-budget"]
        self.assertTrue(any("allowance exceeded" in error
                            for error in assignments.check(plan, handoff)["errors"]))

    def test_unobserved_workers_do_not_share_an_identity(self):
        plan = assignments.prepare(self.request)
        handoff = self.handoff(plan)
        unobserved = handoff["attempts"][:2]
        for attempt in unobserved:
            attempt["worker"] = attempt["result"]["worker"] = None
        result = assignments.check(plan, handoff)
        self.assertTrue(result["structurally_complete"], result)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["replacement_rounds_used"], {key: 0 for key in plan["required"]})
        for attempt in unobserved:
            category = attempt["packet"]["review_type"]
            self.assertTrue(any(note.startswith(f"{category}:") and "native identity" in note
                                for note in result["limitations"]))

    def test_cross_role_context_reuse_wrong_snapshots_and_missing_results_fail(self):
        plan = assignments.prepare(self.request)
        for mutation in ("role-reuse", "worker-reuse", "snapshot", "missing", "instruction", "coverage"):
            with self.subTest(mutation=mutation):
                handoff = self.handoff(plan)
                first, second = handoff["attempts"][:2]
                if mutation == "role-reuse":
                    handoff["other_workers"][0]["worker"] = first["worker"]
                elif mutation == "worker-reuse":
                    second["worker"] = second["result"]["worker"] = first["worker"]
                elif mutation == "missing":
                    first["result"] = None
                elif mutation == "snapshot":
                    first["result"]["snapshot"] = "another"
                elif mutation == "instruction":
                    first["result"]["instruction_set"] = "another"
                else:
                    first["result"]["coverage"]["isolation"] = "contaminated"
                self.assertFalse(assignments.check(plan, handoff)["structurally_complete"])

    def test_child_identity_visibility_is_distinct_from_caller_observation(self):
        plan = assignments.prepare(self.request)
        handoff = self.handoff(plan)
        original = handoff["attempts"][0]
        original["result"]["worker"] = None
        self.assertTrue(assignments.check(plan, handoff)["structurally_complete"])
        self.assertIsNone(original["result"]["worker"])
        original["result"]["worker"] = "a-different-context"
        self.assertFalse(assignments.check(plan, handoff)["structurally_complete"])

    def test_frozen_packets_cannot_be_rewritten_or_use_unsafe_result_paths(self):
        plan = assignments.prepare(self.request)
        changed = copy.deepcopy(plan["packets"]["security"])
        changed["instruction_set"]["sources"][0]["content"] = "Use a second category"
        changed.pop("identity")
        changed = assignments.seal(changed)
        with self.assertRaisesRegex(ValueError, "frozen instructions"):
            assignments.verify_packet(plan, changed)
        with self.assertRaisesRegex(ValueError, "outside"):
            assignments.derive_packet(plan, "security", "bad", str(self.root / "result.json"))
        link = self.scratch / "link"
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "outside"):
            assignments.derive_packet(plan, "security", "bad", str(link / "result.json"))
        with self.assertRaisesRegex(ValueError, "widens"):
            self.packet(plan, "bad", ["unassigned.py"])

    def test_open_phase_addition_and_disable_preserve_frozen_packets_and_attempt_history(self):
        plan = assignments.prepare(self.request)
        handoff = self.handoff(plan)
        first = handoff["attempts"][0]
        first["result"]["outcome"] = "failed"
        replacement = self.attempt(self.packet(plan, "security-replacement"), 1, "failed")
        handoff["attempts"].append(replacement)
        revised = copy.deepcopy(self.request)
        revised["review_options"]["configuration"]["review_features"]["review-security"] = False
        revised["project_categories"] = [{
            "id": "project:localization", "title": "Localization",
            "source": "localization.md", "source_identity": "original", "content": "Translate UI text.",
            "applicability": "web/**", "exceptions": [],
        }]
        next_plan = assignments.prepare(revised, plan)
        for key, packet in plan["packets"].items():
            self.assertEqual(next_plan["packets"][key], packet)
        del handoff["active"]["security"]
        added = self.attempt(next_plan["packets"]["project:localization"])
        handoff["attempts"].append(added)
        handoff["active"]["project:localization"] = [added["id"]]
        result = assignments.check(next_plan, handoff)
        self.assertTrue(result["structurally_complete"], result)
        self.assertEqual(result["replacement_rounds_used"]["security"], 1)
        with self.assertRaisesRegex(ValueError, "not required"):
            self.packet(next_plan, "disabled-retry")
        revised["snapshot"] = "changed"
        with self.assertRaisesRegex(ValueError, "new phase"):
            assignments.prepare(revised, plan)

    def test_cli_round_trip_and_input_recovery_write_no_implicit_state(self):
        request_file, plan_file = self.home / "request.json", self.home / "plan.json"
        request_file.write_text(json.dumps(self.request))
        result = subprocess.run([sys.executable, "-B", str(HELPER), "prepare", str(request_file)],
                                cwd=self.root, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        plan_file.write_text(result.stdout)
        handoff_file = self.home / "handoff.json"
        handoff_file.write_text(json.dumps(self.handoff(json.loads(result.stdout))))
        checked = subprocess.run([sys.executable, "-B", str(HELPER), "check", str(plan_file),
                                  str(handoff_file)], cwd=self.root, text=True, capture_output=True)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertTrue(json.loads(checked.stdout)["structurally_complete"])
        result = subprocess.run([sys.executable, "-B", str(HELPER), "packet", str(plan_file),
                                 "security", "--assignment", "shard", "--result-file",
                                 str(self.scratch / "shard.json"), "--file", "producer.py"],
                                cwd=self.root, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["scope_files"], ["producer.py"])
        request_file.write_text("{invalid")
        result = subprocess.run([sys.executable, "-B", str(HELPER), "prepare", str(request_file)],
                                cwd=self.root, text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("other authorized work remains available", result.stderr)
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_open_phase_freezes_changed_installed_resources_but_new_phase_refreshes_them(self):
        resources = self.home / "resources"
        shutil.copytree(assignments.RESOURCES, resources)
        with patch.object(assignments, "RESOURCES", resources):
            plan = assignments.prepare(self.request)
            handoff = self.handoff(plan)
            source = resources / plan["registry"]["security"]["source"]
            source.write_text(source.read_text() + "\nChanged installed security instruction fixture.\n")
            revised = assignments.prepare(self.request, plan)
            fresh = assignments.prepare(self.request)
        self.assertEqual(revised["registry"], plan["registry"])
        self.assertEqual(revised["packets"], plan["packets"])
        self.assertTrue(assignments.check(revised, handoff)["structurally_complete"])
        self.assertNotEqual(fresh["registry"]["security"]["sources"],
                            plan["registry"]["security"]["sources"])
        self.assertNotEqual(fresh["packets"]["security"]["instruction_set"],
                            plan["packets"]["security"]["instruction_set"])

    def test_shipped_category_dependencies_do_not_reach_other_categories_or_composers(self):
        skills = assignments.RESOURCES.parent
        roles = assignments.catalog()["skill_roles"]
        classified = [name for values in roles.values() for name in values]
        self.assertEqual(len(classified), len(set(classified)))
        self.assertEqual(set(classified), {path.parent.name for path in skills.glob("*/SKILL.md")})
        links = re.compile(r"\[[^]]*\]\(([^)#]+\.md)(?:#[^)]*)?\)")
        for name in roles["category"]:
            allowed = {(skills / name / "SKILL.md").resolve(),
                       (assignments.RESOURCES / "categories" / f"{name}.md").resolve()}
            for path in allowed:
                for target in links.findall(path.read_text()):
                    if "://" not in target:
                        self.assertIn((path.parent / target).resolve(), allowed, str(path))
        for path in (assignments.RESOURCES / "categories").glob("*.md"):
            for target in links.findall(path.read_text()):
                if "://" not in target:
                    self.assertEqual((path.parent / target).resolve(), path.resolve(),
                                     f"{path} loads a composer or another category")

    def test_assessment_consumers_resolve_policy_modules_and_controls_cover_the_registry(self):
        root = assignments.RESOURCES.parent.parent
        consumers = ["review-code/CONTRACTS.md", "review-validate-fix-loop/WORKFLOW.md",
                     "review-triage-loop/WORKFLOW.md", "verify-unresolved-pr-comments/SKILL.md"]
        for name in consumers:
            self.assertIn("ASSESSMENT.md", (root / "skills" / name).read_text())
        for name in ("COMMON", "DOCUMENTATION", "TESTS"):
            self.assertIn(f"assessment/{name}.md", (assignments.RESOURCES / "ASSESSMENT.md").read_text())
            self.assertTrue((assignments.RESOURCES / "assessment" / f"{name}.md").is_file())
        corpus = json.loads((root / "scripts" / "fixtures" / "review_quality.json").read_text())
        self.assertFalse(any(case["split"] == "held-out" for case in corpus["cases"]))
        controls = corpus["category_controls"]
        defaults = json.loads((root / "config" / "defaults.json").read_text())["features"]
        self.assertLessEqual({row["feature"] for row in assignments.catalog()["categories"]},
                             defaults.keys())
        self.assertEqual({row["category"] for row in controls},
                         {row["id"] for row in assignments.catalog()["categories"]})
        self.assertEqual(len(controls), len({row["category"] for row in controls}))
        for row in controls:
            for polarity in ("positive", "negative"):
                self.assertTrue(row[polarity]["files"])
                self.assertTrue(row[polarity]["reference"])
            self.assertTrue(row["positive"]["expected"])
            self.assertEqual(row["negative"]["expected"], [])

    def test_native_test_controls_distinguish_mock_assertions_from_real_regression_protection(self):
        root = assignments.RESOURCES.parent.parent
        corpus = json.loads((root / "scripts/fixtures/review_quality.json").read_text())
        controls = {row["id"]: row for row in corpus["stack_applicability_controls"]}
        runners = [
            ("native-python-tests", "amounts.py",
             [sys.executable, "-B", "-m", "unittest", "-q", "test_amounts"]),
            ("native-node-tests", "amounts.js", ["node", "--test", "amounts.test.js"]),
        ]
        for key, source, command in runners:
            for polarity in ("positive", "negative"):
                with self.subTest(control=key, polarity=polarity):
                    directory = self.home / key / polarity
                    directory.mkdir(parents=True)
                    for name, content in controls[key][polarity]["files"].items():
                        (directory / name).write_text(content)
                    original = subprocess.run(command, cwd=directory, text=True,
                                              capture_output=True, timeout=30)
                    self.assertEqual(original.returncode, 0, original.stdout + original.stderr)
                    path = directory / source
                    content = path.read_text()
                    mutated = content.replace("* 100", "* 10")
                    self.assertNotEqual(content, mutated)
                    path.write_text(mutated)
                    regression = subprocess.run(command, cwd=directory, text=True,
                                                capture_output=True, timeout=30)
                    self.assertEqual(regression.returncode == 0, polarity == "positive",
                                     regression.stdout + regression.stderr)


if __name__ == "__main__":
    unittest.main()
