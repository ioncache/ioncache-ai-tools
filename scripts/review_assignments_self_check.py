#!/usr/bin/env python3
"""Check category records offline; these fixtures never launch model workers."""

import copy
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import development_handoff
import development_jobs
import development_run
import review_assignments as assignments
import report_json
import writing_guidance


HELPER = Path(__file__).with_name("review_assignments.py")


class ReviewAssignmentTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name).resolve()
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

    def test_writing_standards_reuse_frozen_sources_and_resolve_discovered_languages(self):
        self.request["project_sources"] = [{
            "category": "unit-tests", "source": "testing.md", "source_identity": "approved-source",
            "content": "Use unittest fixtures.", "applicability": "**/*.py", "exceptions": [],
        }]
        phase = assignments.prepare(self.request)
        settings = {"enabled": True, "disabled_skills": [], "review_features": {}}
        inputs = {"root": str(self.root), "phase": phase}
        with patch.object(assignments, "resource", side_effect=AssertionError("Must use frozen sources")):
            bundle = writing_guidance.prepare(inputs, settings)
        self.assertNotIn("jsdoc", bundle["standards"])
        self.assertEqual(bundle["standards"]["unit-tests"]["project_sources"],
                         phase["packets"]["unit-tests"]["instruction_set"]["project_sources"])
        for key, standard in bundle["standards"].items():
            self.assertEqual(standard["sources"], phase["registry"][key]["sources"])
        context = {"files": ["view.component"], "language_inventory": {
            "view.component": {"languages": ["html", "javascript"], "evidence": "Inspected embedded script"},
        }}
        expanded = writing_guidance.prepare({**inputs, "context": context}, settings)
        self.assertEqual(expanded["standards"]["jsdoc"]["sources"], phase["registry"]["jsdoc"]["sources"])
        context["language_inventory"]["view.component"]["languages"] = ["typescript"]
        self.assertNotIn("jsdoc", writing_guidance.prepare({**inputs, "context": context}, settings)["standards"])
        settings["disabled_skills"] = ["skill:comments"]
        opted_out = writing_guidance.prepare(inputs, settings)
        self.assertNotIn("comments", opted_out["standards"])
        self.assertIn("comments", phase["required"])
        with self.assertRaisesRegex(ValueError, "cannot replace its frozen project standards"):
            writing_guidance.prepare({**inputs, "context": {**context, "project_sources": []}}, settings)

    def test_ambient_instructions_are_ignored_without_invalidating_coverage(self):
        plan = assignments.prepare(self.request)
        handoff = self.handoff(plan)
        coverage = handoff["attempts"][0]["result"]["coverage"]
        coverage.update(isolation="unknown", ambient_sources=["CLAUDE.md", ".claude/rules/testing.md"],
                        context_conflicts=[])
        result = assignments.check(plan, handoff)
        self.assertTrue(result["structurally_complete"], result)
        self.assertTrue(any("excluded from the review ruleset" in item for item in result["limitations"]))
        coverage["isolation"] = "contaminated"
        result = assignments.check(plan, handoff)
        self.assertFalse(result["structurally_complete"], result)
        coverage.update(isolation="unknown", context_conflicts=["Received a sibling review report"])
        result = assignments.check(plan, handoff)
        self.assertFalse(result["structurally_complete"], result)
        self.assertIn("Known context conflicts", json.dumps(result))
        coverage["isolation"] = "contaminated"
        self.assertFalse(assignments.check(plan, handoff)["structurally_complete"])
        coverage.update(isolation="uncontaminated", context_conflicts=[])
        self.assertTrue(assignments.check(plan, handoff)["structurally_complete"])

    def test_project_reference_reads_recover_through_adjudication_without_replacement(self):
        source = ".github/instructions/swr.instructions.md"
        path = self.root / source
        path.parent.mkdir(parents=True)
        path.write_text("Project SWR-specific guidance.")
        self.request["project_categories"] = [{
            "id": "project:swr", "title": "SWR", "source": source,
            "source_identity": assignments.digest(path.read_text()), "content": path.read_text(),
            "applicability": "**/*", "exceptions": [],
        }]
        plan = assignments.prepare(self.request)
        handoff = self.handoff(plan)
        affected = [attempt for attempt in handoff["attempts"]
                    if attempt["packet"]["review_type"] in ("design-coherence", "documentation")]
        for attempt in affected:
            attempt["result"]["coverage"]["reference_sources"] = [source]
        self.assertTrue(assignments.check(plan, handoff)["structurally_complete"])
        corrections = []
        originals = {}
        for attempt in affected:
            result = attempt["result"]
            result["outcome"] = "partial"
            result["coverage"].update(isolation="contaminated", reference_sources=[source],
                                      context_conflicts=["Opened the plan's SWR reference as evidence"])
            originals[attempt["id"]] = copy.deepcopy(result)
            corrections.append({
                "attempt": attempt["id"], "packet_identity": attempt["packet"]["identity"],
                "result_identity": assignments.digest(result), "kind": "evidence-read-only",
                "sources": [source], "assigned_ruleset_only": True, "otherwise_complete": True,
                "evidence": ["The complete original report traces every applicable file; "
                             "the only claimed breach is reading the plan reference, not applying SWR rules."],
            })
        self.assertFalse(assignments.check(plan, handoff)["structurally_complete"])
        handoff["other_workers"][0]["isolation_assessments"] = corrections
        result = assignments.check(plan, handoff)
        self.assertTrue(result["structurally_complete"], result)
        self.assertTrue(any("read-only isolation classification" in item for item in result["limitations"]))
        self.assertEqual(set(result["replacement_rounds_used"].values()), {0})
        for attempt in handoff["attempts"]:
            if attempt["id"] in originals:
                self.assertEqual(attempt["result"], originals[attempt["id"]])
        for field, value in (("result_identity", "stale"), ("packet_identity", "wrong-packet"),
                             ("assigned_ruleset_only", False), ("otherwise_complete", False),
                             ("evidence", [])):
            with self.subTest(field=field):
                broken = copy.deepcopy(handoff)
                broken["other_workers"][0]["isolation_assessments"][0][field] = value
                self.assertFalse(assignments.check(plan, broken)["structurally_complete"])
        reused = copy.deepcopy(handoff)
        reused["other_workers"][0]["worker"] = handoff["attempts"][0]["worker"]
        self.assertFalse(assignments.check(plan, reused)["structurally_complete"])
        for defect in ("failed", "missing-files", "malformed"):
            with self.subTest(defect=defect):
                broken = copy.deepcopy(handoff)
                assessment = broken["other_workers"][0]["isolation_assessments"][0]
                report = next(item["result"] for item in broken["attempts"]
                              if item["id"] == assessment["attempt"])
                if defect == "failed":
                    report["outcome"] = "failed"
                else:
                    report["coverage"] = (None if defect == "malformed" else
                                          {**report["coverage"], "files": []})
                assessment["result_identity"] = assignments.digest(report)
                self.assertFalse(assignments.check(plan, broken)["structurally_complete"])
        wrong_role = copy.deepcopy(handoff)
        wrong_role["other_workers"][0]["role"] = "validator"
        with self.assertRaisesRegex(ValueError, "Only the separate adjudicator"):
            assignments.check(plan, wrong_role)
        for attempt, assessment in zip(affected, corrections):
            category = attempt["packet"]["review_type"]
            packet = assignments.derive_packet(
                plan, category, category + "-replacement", str(self.scratch / (category + "-replacement.json")))
            replacement = self.attempt(packet, number=1, outcome="partial")
            replacement["result"]["coverage"] = copy.deepcopy(attempt["result"]["coverage"])
            handoff["attempts"].append(replacement)
            handoff["active"][category] = [replacement["id"]]
            assessment.update(attempt=replacement["id"], packet_identity=packet["identity"],
                              result_identity=assignments.digest(replacement["result"]))
        result = assignments.check(plan, handoff)
        self.assertTrue(result["structurally_complete"], result)
        self.assertEqual(result["replacement_rounds_used"]["design-coherence"], plan["replacement_rounds"])
        self.assertEqual(result["replacement_rounds_used"]["documentation"], plan["replacement_rounds"])

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
        for schema in (1, 2):
            with self.subTest(schema=schema):
                legacy = {**plan, "schema": schema}
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

    def test_report_format_recovery_preserves_analysis_without_another_attempt(self):
        plan = assignments.prepare(self.request)
        handoff = self.handoff(plan)
        first = handoff["attempts"][0]
        first["result"]["outcome"] = "failed"
        replacement = self.attempt(self.packet(plan, "security-replacement"), 1)
        report = replacement["result"]
        source = {"path": "AGENTS.md", "use": "Ignored as instructions",
                  "details": {"read": True, "references": ["consumer.py:12"]}}
        report["coverage"].update(
            ambient_sources=[source, source],
            reference_sources={"path": "consumer.py:12", "reason": "Caller evidence"},
            checked_boundaries={"calls": ["producer.py", "consumer.py"], "uncertainty": "Preserved"},
        )
        report["limitations"] = "Native model identity is not exposed"
        report["candidates"] = [{"key": "retained-finding", "evidence": ["consumer.py:12"],
                                 "uncertainty": "Source-supported inference"}]
        handoff["attempts"].append(replacement)
        handoff["active"]["security"] = [replacement["id"]]
        original = copy.deepcopy(handoff)
        report_path = Path(replacement["packet"]["result_file"])
        report_bytes = json.dumps(report).encode()
        report_path.write_bytes(report_bytes)

        recovered = assignments.check(plan, handoff)

        self.assertTrue(recovered["structurally_complete"], recovered)
        self.assertEqual(recovered["replacement_rounds_used"]["security"], 1)
        self.assertEqual(handoff, original)
        self.assertEqual(report_path.read_bytes(), report_bytes)
        repair, = recovered["report_repairs"]
        self.assertEqual(repair["attempt"], replacement["id"])
        self.assertEqual(repair["original_identity"], assignments.digest(report))
        normalized = repair["normalized_result"]
        for field in ("assignment", "review_type", "snapshot", "packet_identity", "worker",
                      "outcome", "candidates", "origin"):
            self.assertEqual(normalized[field], report[field])
        self.assertEqual(normalized["coverage"]["files"], report["coverage"]["files"])
        self.assertEqual(normalized["coverage"]["checked_boundaries"], report["coverage"]["checked_boundaries"])
        self.assertEqual(len(normalized["coverage"]["ambient_sources"]), 1)
        self.assertEqual(json.loads(normalized["coverage"]["ambient_sources"][0]), source)
        self.assertEqual(json.loads(normalized["coverage"]["reference_sources"][0]),
                         report["coverage"]["reference_sources"])
        self.assertEqual(normalized["limitations"], [report["limitations"]])
        self.assertEqual(repair["normalized_identity"], assignments.digest(normalized))
        self.assertEqual({change["field"] for change in repair["changes"]},
                         {"coverage.ambient_sources", "coverage.reference_sources", "limitations"})
        sources = next(change for change in repair["changes"] if change["field"] == "coverage.ambient_sources")
        self.assertEqual(sources["original"], [source, source])
        normalized_again, changes = assignments.repair_result({**replacement, "result": normalized})
        self.assertEqual(normalized_again, normalized)
        self.assertEqual(changes, [])
        self.assertEqual(assignments.check(plan, handoff), recovered)
        self.assertTrue(any("reformatted" in note for note in recovered["limitations"]))

    def test_report_format_recovery_preserves_supplied_selection_and_instruction_identity(self):
        plan = assignments.prepare(self.request)
        handoff = self.handoff(plan)
        attempt = handoff["attempts"][0]
        report = attempt["result"]
        report["selection"] = "Configured defaults; actual model not exposed"
        report["instruction_set"] = copy.deepcopy(attempt["packet"]["instruction_set"])
        original = copy.deepcopy(handoff)

        recovered = assignments.check(plan, handoff)

        self.assertTrue(recovered["structurally_complete"], recovered)
        self.assertEqual(handoff, original)
        normalized = recovered["report_repairs"][0]["normalized_result"]
        self.assertEqual(normalized["selection"]["reason"], report["selection"])
        self.assertEqual(normalized["selection"]["actual"], "unknown")
        self.assertEqual(normalized["instruction_set"],
                         attempt["packet"]["instruction_set"]["identity"])
        self.assertEqual(set(recovered["replacement_rounds_used"].values()), {0})

    def test_development_candidates_validate_a_copy_without_rewriting_review_evidence(self):
        plan = assignments.prepare(self.request)
        attempt = self.attempt(plan["packets"]["security"])
        report = attempt["result"]
        report["instruction_set"] = {"identity": attempt["packet"]["instruction_set"]["identity"]}
        report["selection"] = "Native model identity is not exposed"
        report["limitations"] = [{"observation": "Read-only fixture", "details": ["No native launch"]}]
        job = {"role": "reviewer", "packet": attempt["packet"]}
        original = copy.deepcopy(report)

        candidate = development_jobs.candidate_report({}, job, report)
        development_jobs.validate({}, job, candidate)

        self.assertEqual(candidate, original)
        self.assertEqual(report, original)
        report["snapshot"] = "wrong-snapshot"
        with self.assertRaisesRegex(ValueError, "snapshot mismatch"):
            development_jobs.validate({}, job, report)

    def test_report_json_recovers_only_wrappers_and_trailing_commas_without_changing_text(self):
        note = 'Quoted "comma,}" and backslash \\,] stay; literal ``` stays too'
        expected = {"note": note, "candidates": [{"key": "kept"}]}
        strict = json.dumps(expected)
        trailing = '{"note":' + json.dumps(note) + ',"candidates":[{"key":"kept",},],}'
        cases = [
            (strict.encode(), []),
            (strict.encode("utf-16"), []),
            (f"```json\n{strict}\n```\n".encode(), ["code_fence"]),
            (f"```\r\n{strict}\r\n```\r\n".encode(), ["code_fence"]),
            (trailing.encode(), ["trailing_commas"]),
            (json.dumps(strict).encode(), ["json_string"]),
            (f"```json\n{json.dumps(trailing)}\n```".encode(),
             ["code_fence", "json_string", "trailing_commas"]),
            (json.dumps(f"```json\n{trailing}\n```").encode(),
             ["json_string", "code_fence", "trailing_commas"]),
        ]
        for content, kinds in cases:
            with self.subTest(kinds=kinds, content=content):
                value, repair = report_json.decode(content, recover=True)
                self.assertEqual(value, expected)
                if not kinds:
                    self.assertIsNone(repair)
                    continue
                self.assertEqual([change["kind"] for change in repair["changes"]], kinds)
                self.assertEqual(repair["original_sha256"], development_jobs.plan.digest(content))
                self.assertEqual(repair["decoded_identity"], assignments.digest(expected))
                for change in repair["changes"]:
                    if change["kind"] == "trailing_commas":
                        self.assertEqual(len(change["offsets"]), 3)
                        self.assertTrue(all(trailing[index] == "," for index in change["offsets"]))
                with self.assertRaises(ValueError):
                    report_json.decode(content)

    def test_report_json_does_not_guess_truncated_ambiguous_or_non_json_evidence(self):
        cases = [
            b'{"candidates":[', b'{"note":"truncated}', b'{"note":}',
            b'{"candidates":[,]}', b'{,}', b'{"candidates":[1,,]}',
            b'{"outcome":"partial","outcome":"complete"}',
            b'{"outcome":"partial","out\\u0063ome":"complete"}',
            b'{"coverage":{"files":[],"files":["consumer.py"]},}',
            b'{"outcome":"complete"} {"outcome":"partial"}',
            b'Here is the report:\n{"candidates":[]}', b'{"candidates":[]} done',
            b'```json\n{"candidates":[]}', b'```json\n{}\n```\n```json\n{}\n```',
            b'```json\n```json\n{}\n```\n```',
            json.dumps(json.dumps(json.dumps({"candidates": []}))).encode(),
            b'{"candidates": [NaN]}', b'{"note":Infinity}', b'{"value":1e9999}',
            b"{'note':'single quotes'}", b'{"note":undefined}', b'{"note":/*comment*/"x"}',
            b'{"note":"invalid\\q"}', b'{"note":"\xff"}', b'[]', b'null',
        ]
        for content in cases:
            with self.subTest(content=content), self.assertRaises(ValueError):
                report_json.decode(content, recover=True)
        with self.assertRaisesRegex(ValueError, "Too many trailing commas"):
            report_json.decode(b'{"candidates":[' + b"[1,]," * 4097 + b"]}", recover=True)

    def test_standalone_report_decoder_honors_settings_without_rewriting_reports_or_config(self):
        original = b'```json\n{"candidates":[{"key":"kept",},],}\n```'
        path = self.scratch / "report.json"
        path.write_bytes(original)
        config = self.root / ".claude/ioncache-ai-tools.local.json"
        config.parent.mkdir()
        for enabled in (True, False):
            config.write_text(json.dumps({"features": {"review-report-json-recovery": enabled}}))
            configuration = config.read_bytes()
            with patch("sys.stdout", new_callable=io.StringIO) as output, \
                    patch("sys.stderr", new_callable=io.StringIO) as errors:
                code = report_json.main([str(path), "--project", str(self.root)])
            self.assertEqual(code, 0 if enabled else 2, errors.getvalue())
            if enabled:
                result = json.loads(output.getvalue())
                self.assertEqual(result["report"]["candidates"], [{"key": "kept"}])
                self.assertEqual(result["json_repairs"]["original_sha256"],
                                 development_jobs.plan.digest(original))
            else:
                self.assertIn("do not repeat the review", errors.getvalue())
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(config.read_bytes(), configuration)
        with self.assertRaises(json.JSONDecodeError):
            development_jobs.decode_json(original)
        with self.assertRaises(json.JSONDecodeError):
            development_handoff.read_json(path)

    def development_report_fixture(self, submission, transform=None):
        store = self.scratch / (submission + ("-syntax" if transform else ""))
        reports = store / "reports"
        reports.mkdir(parents=True)
        self.request["scratch_directory"] = str(reports)
        plan = assignments.prepare(self.request)
        handoff = self.handoff(plan)
        report = handoff["attempts"][0]["result"]
        report["selection"] = "Model identity not exposed"
        report["coverage"]["reference_sources"] = {"path": "consumer.py:12", "use": "Evidence"}
        report["limitations"] = "No model launched by this offline fixture"
        report["candidates"] = [{"key": "original-observation", "evidence": ["consumer.py:12"]}]
        assignment = {"id": "A1", "root": str(self.root), "store": str(store),
                      "report_json_recovery_enabled": True}
        jobs = [{"role": "reviewer", "packet": item["packet"], "result_file": item["packet"]["result_file"]}
                for item in handoff["attempts"]]
        batch = {"id": "B1", "assignment": "A1", "status": "collected", "submitted": {},
                 "spec": {"store": str(store), "jobs": jobs}}
        for number, attempt in enumerate(handoff["attempts"], 1):
            path = Path(attempt["packet"]["result_file"])
            original = json.dumps(attempt["result"], indent=3).encode()
            if transform and number == 1:
                original = transform(original)
            if submission == "submit":
                candidate = path.with_suffix(".candidate.json")
                candidate.write_bytes(original)
                development_handoff.write_candidate(
                    assignment, batch, SimpleNamespace(job=number, candidate=str(candidate)))
                self.assertEqual(candidate.read_bytes(), original)
            else:
                path.write_bytes(original)
            snapshot = development_handoff.report_for(assignment, batch, number)
            batch["submitted"][str(number)] = snapshot["receipt"]
            self.assertEqual(snapshot["report"], attempt["result"])
            archive = store / "handoffs" / "B1" / f"{number}-{development_jobs.plan.digest(original)}.json"
            self.assertEqual(archive.read_bytes(), original)
        data = {"plan": str(reports / "plan.json"), "handoff": str(reports / "handoff.json")}
        Path(data["plan"]).write_text(json.dumps(plan))
        Path(data["handoff"]).write_text(json.dumps(handoff))
        return assignment, {"store": str(store), "handoffs": {"B1": batch}}, data, plan, handoff

    def test_development_syntax_recovery_retains_byte_identity_through_final_acceptance(self):
        def malformed(content):
            trailing = content.decode()[:-1] + ",}"
            return f"```json\n{json.dumps(trailing)}\n```".encode()

        for submission in ("finish", "submit"):
            with self.subTest(submission=submission):
                assignment, state, data, plan, handoff = self.development_report_fixture(submission, malformed)
                batch = state["handoffs"]["B1"]
                stored, = batch["report_json_repairs"]["1"].values()
                ledger_report = {key: self.request[key] for key in ("base", "snapshot")}
                with patch.object(development_run, "review_files", return_value=self.request["files"]):
                    checked = development_run.review_coverage(state, assignment, ledger_report, data)
                self.assertTrue(checked["structurally_complete"], checked)
                repair, = checked["report_json_repairs"]
                self.assertEqual(repair["decoded_identity"], assignments.digest(handoff["attempts"][0]["result"]))
                self.assertEqual(development_jobs.plan.digest(Path(repair["archive"]).read_bytes()),
                                 repair["original_sha256"])
                self.assertEqual(repair["changes"], stored["changes"])
                self.assertEqual(set(checked["replacement_rounds_used"].values()), {0})
                assignment["report_json_recovery_enabled"] = False
                replay = development_handoff.report_for(assignment, batch, 1, expected=batch["submitted"]["1"])
                self.assertEqual(replay["report"], handoff["attempts"][0]["result"])
                handoff["attempts"][0]["result"]["snapshot"] = "wrong-snapshot"
                with self.assertRaisesRegex(ValueError, "differs from the collected"):
                    development_jobs.require_collected_review(state, assignment, handoff)
                if submission == "finish":
                    receipt = batch["submitted"]["1"]
                    batch["report_json_repairs"]["1"][receipt["sha256"]]["changes"] = []
                    with self.assertRaisesRegex(development_jobs.review.EvidenceUnavailable, "repair record changed"):
                        development_jobs.retained_report(batch, 1)

    def test_development_report_recovery_preserves_collection_and_final_acceptance_bindings(self):
        for submission in ("finish", "submit"):
            with self.subTest(submission=submission):
                assignment, state, data, plan, handoff = self.development_report_fixture(submission)
                original = copy.deepcopy(handoff)
                paths = [Path(data[key]) for key in ("plan", "handoff")]
                bytes_before = [path.read_bytes() for path in paths]
                ledger_report = {key: self.request[key] for key in ("base", "snapshot")}

                with patch.object(development_run, "review_files", return_value=self.request["files"]):
                    checked = development_run.review_coverage(state, assignment, ledger_report, data)

                self.assertTrue(checked["structurally_complete"], checked)
                repair, = checked["report_repairs"]
                self.assertEqual(repair["original_identity"], assignments.digest(handoff["attempts"][0]["result"]))
                self.assertEqual(repair["normalized_result"]["candidates"],
                                 handoff["attempts"][0]["result"]["candidates"])
                self.assertEqual(set(checked["replacement_rounds_used"].values()), {0})
                self.assertEqual([path.read_bytes() for path in paths], bytes_before)
                handoff["attempts"][0]["result"] = repair["normalized_result"]
                with self.assertRaisesRegex(ValueError, "differs from the collected reviewer report"):
                    development_jobs.require_collected_review(state, assignment, handoff)
                handoff["attempts"][0]["result"] = original["attempts"][0]["result"]
                development_jobs.require_collected_review(state, assignment, handoff)
                self.assertEqual(assignments.check(plan, handoff)["report_repairs"], checked["report_repairs"])

    def test_format_recovery_keeps_isolation_assessment_bound_to_original_report(self):
        plan = assignments.prepare(self.request)
        handoff = self.handoff(plan)
        attempt = handoff["attempts"][0]
        report = attempt["result"]
        report["outcome"] = "partial"
        report["coverage"].update(
            isolation="contaminated",
            reference_sources={"path": "consumer.py", "use": "Evidence only"},
            context_conflicts={"reason": "Classified an evidence read as instructions"},
        )
        assessment = {
            "attempt": attempt["id"], "packet_identity": attempt["packet"]["identity"],
            "result_identity": assignments.digest(report), "kind": "evidence-read-only",
            "sources": ["consumer.py"], "assigned_ruleset_only": True, "otherwise_complete": True,
            "evidence": ["Offline adjudication fixture: complete work with only an evidence read"],
        }
        handoff["other_workers"][0]["isolation_assessments"] = [assessment]
        original = copy.deepcopy(handoff)

        checked = assignments.check(plan, handoff)

        self.assertTrue(checked["structurally_complete"], checked)
        repair, = checked["report_repairs"]
        self.assertEqual(repair["normalized_result"]["outcome"], "partial")
        self.assertEqual(handoff, original)
        assessment["result_identity"] = repair["normalized_identity"]
        stale = assignments.check(plan, handoff)
        self.assertFalse(stale["structurally_complete"], stale)
        self.assertIn("Isolation assessment is stale", "\n".join(stale["errors"]))

    def test_report_repair_does_not_hide_missing_work_or_conflicting_evidence(self):
        plan = assignments.prepare(self.request)
        for defect, expected in (
                ("snapshot", "snapshot mismatch"),
                ("instruction", "instruction identity mismatch"),
                ("instruction-extra", "instruction identity mismatch"),
                ("worker", "worker contradicts"),
                ("packet", "packet identity mismatch"),
                ("purpose", "review_type mismatch"),
                ("partial", "reported partial"),
                ("failed", "reported failed"),
                ("missing", "no report"),
                ("files", "coverage differs"),
                ("conflict", "Known context conflicts"),
                ("contaminated", "reported contaminated"),
                ("empty-source", "needs nonempty text")):
            with self.subTest(defect=defect):
                handoff = self.handoff(plan)
                attempt = handoff["attempts"][0]
                report = attempt["result"]
                report["coverage"]["ambient_sources"] = [{"path": "AGENTS.md"}]
                if defect == "snapshot":
                    report["snapshot"] = "other-snapshot"
                elif defect == "instruction":
                    report["instruction_set"] = {"identity": "wrong-instruction"}
                elif defect == "instruction-extra":
                    report["instruction_set"] = {
                        **attempt["packet"]["instruction_set"], "extra": "Not frozen instructions"}
                elif defect == "worker":
                    report["worker"] = "another-worker"
                elif defect == "packet":
                    report["packet_identity"] = "another-packet"
                elif defect == "purpose":
                    report["review_type"] = "another-purpose"
                elif defect in ("partial", "failed"):
                    report["outcome"] = defect
                elif defect == "missing":
                    attempt["result"] = None
                elif defect == "files":
                    report["coverage"]["files"] = ["producer.py"]
                elif defect == "conflict":
                    report["coverage"]["context_conflicts"] = [{"reason": "Read sibling findings"}]
                elif defect == "contaminated":
                    report["coverage"].update(
                        isolation="contaminated",
                        context_conflicts=[{"reason": "Adopted another ruleset"}])
                else:
                    report["coverage"]["ambient_sources"] = [{}]
                original = copy.deepcopy(handoff)

                result = assignments.check(plan, handoff)

                self.assertFalse(result["structurally_complete"], result)
                self.assertEqual(result["missing_categories"], ["security"])
                self.assertIn(expected, "\n".join(result["errors"]))
                self.assertEqual(handoff, original)
                self.assertEqual(result["replacement_rounds_used"]["security"], 0)

    def test_unrecoverable_results_preserve_history_and_allow_a_fresh_replacement(self):
        plan = assignments.prepare(self.request)
        for field, value in (("selection", None),
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
                replacement["result"]["selection"] = None
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

    def test_deferred_categories_keep_frozen_protocol_and_assessment_resources(self):
        resources = (self.home / "resources").resolve()
        shutil.copytree(assignments.RESOURCES, resources)
        self.request["language_inventory"].pop("consumer.py")
        self.request["review_options"]["configuration"]["review_features"]["review-unit-tests"] = False
        names = ("PROTOCOL.md", "assessment/COMMON.md", "assessment/DOCUMENTATION.md",
                 "assessment/TESTS.md")
        original = {str(resources / name): (resources / name).read_text() for name in names}
        with patch.object(assignments, "RESOURCES", resources):
            plan = assignments.prepare(self.request)
            self.assertNotIn("jsdoc", plan["packets"])
            self.assertNotIn("unit-tests", plan["packets"])
            for name in names:
                path = resources / name
                path.write_text(original[str(path)] + "\nChanged installed policy fixture.\n")
            request = copy.deepcopy(self.request)
            request["language_inventory"]["consumer.py"] = {
                "languages": ["javascript"], "evidence": "Completed fixture language inspection",
            }
            request["review_options"]["configuration"]["review_features"]["review-unit-tests"] = True
            revised = assignments.prepare(request, json.loads(json.dumps(plan)))
            fresh = assignments.prepare(request)
        for category in ("jsdoc", "unit-tests"):
            for source in revised["packets"][category]["instruction_set"]["sources"]:
                if source["source"] in original:
                    self.assertEqual(source["content"], original[source["source"]], source["source"])
            self.assertNotEqual(revised["packets"][category]["instruction_set"],
                                fresh["packets"][category]["instruction_set"])
        for category, packet in plan["packets"].items():
            self.assertEqual(revised["packets"][category], packet)
        self.assertTrue(assignments.check(revised, self.handoff(revised))["structurally_complete"])

    def test_new_phases_in_shared_scratch_preserve_previous_reports(self):
        plan = assignments.prepare(self.request)
        path = Path(plan["packets"]["security"]["result_file"])
        path.write_text("Original immutable report\n")
        revised = assignments.prepare(self.request, json.loads(json.dumps(plan)))
        self.assertEqual(revised["packets"], plan["packets"])
        paths = {packet["result_file"] for packet in plan["packets"].values()}
        for snapshot in (self.request["snapshot"], "after-correction"):
            with self.subTest(snapshot=snapshot):
                fresh = assignments.prepare({**self.request, "snapshot": snapshot})
                Path(fresh["packets"]["security"]["result_file"]).write_text("New phase report\n")
                self.assertEqual(path.read_text(), "Original immutable report\n")
                fresh_paths = {packet["result_file"] for packet in fresh["packets"].values()}
                self.assertTrue(paths.isdisjoint(fresh_paths))
                paths.update(fresh_paths)

    def test_frozen_policy_resources_and_phase_identity_are_checked(self):
        plan = assignments.prepare(self.request)
        for case in ("missing-policy", "changed-policy", "different-packet-policy", "missing-phase"):
            with self.subTest(case=case):
                changed = json.loads(json.dumps(plan))
                if case == "missing-policy":
                    del changed["policy_resources"]["assessment/TESTS.md"]
                elif case == "changed-policy":
                    changed["policy_resources"]["PROTOCOL.md"]["content"] += "\nUnsealed change\n"
                elif case == "different-packet-policy":
                    instructions = changed["packets"]["security"]["instruction_set"]
                    instructions["sources"][0]["content"] += "\nDifferent packet policy\n"
                    instructions.pop("identity")
                    changed["packets"]["security"]["instruction_set"] = assignments.seal(instructions)
                else:
                    del changed["phase_id"]
                changed.pop("identity")
                changed = assignments.seal(changed)
                with self.assertRaisesRegex(ValueError, "frozen instruction|resource identity|phase identity"):
                    assignments.check(changed, self.handoff(changed))

    def test_new_policy_resource_requires_a_new_phase(self):
        resources = (self.home / "resources").resolve()
        shutil.copytree(assignments.RESOURCES, resources)
        with patch.object(assignments, "RESOURCES", resources):
            plan = assignments.prepare(self.request)
            catalog = assignments.catalog()
            catalog["categories"].append({
                "id": "additional", "source": "categories/comments.md", "feature": "review-additional",
                "applicability": "Fixture source", "assessment": ["assessment/ADDITIONAL.md"],
            })
            request = copy.deepcopy(self.request)
            request["review_options"]["configuration"]["review_features"]["review-additional"] = True
            (resources / "assessment/ADDITIONAL.md").write_text("New policy fixture.\n")
            with patch.object(assignments, "catalog", return_value=catalog):
                with self.assertRaisesRegex(ValueError, "New instruction resources.*new phase"):
                    assignments.prepare(request, plan)
                fresh = assignments.prepare(request)
            self.assertIn("additional", fresh["required"])
            self.assertTrue(assignments.check(fresh, self.handoff(fresh))["structurally_complete"])

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
