"""Exercise named unresolved reporting and the existing publishers' follow-up contract."""

import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import development_followups as followups
import review_reporting as reporting
import review_options
from self_check_support import run_main


def finding(key="settings-path", **changes):
    return {
        "key": key, "title": "Settings lookup uses a different path",
        "summary": "Symlinked project paths select inconsistent overrides.",
        "validation": "valid", "disposition": "ignored", "report_action": "None",
        "material": True, "sensitive": False, "introduced": False,
        "severity": "Low", "confidence": "High", "basis": "observed",
        "locations": ["hooks/scripts/plugin_config.py:42"],
        "evidence": ["The isolated symlink fixture selected different overrides."],
        "reason": "Pre-existing defect outside this change.",
        "next_step": "Use the same path identity at both entry points.",
        **changes,
    }


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.settings = SimpleNamespace(
            catalog={reporting.FEATURE, followups.FEATURE}, disabled=set())
        self.manifest = {"permissions": {"create_follow_up_issues": True},
                         "repository": {"url": "https://github.com/fixture/project.git"}}

    def test_valid_no_action_findings_are_named_not_counted_as_noise(self):
        cases = [finding(), finding("uncertain", validation="uncertain", disposition="out_of_scope"),
                 finding("invalid", validation="invalid", title="Refuted claim"),
                 finding("style", material=False, title="Cosmetic preference"),
                 finding("duplicate", duplicate_of="settings-path"),
                 finding("fixed", disposition="fixed"), finding("pending", validation="pending")]
        report = reporting.project(cases)
        text = reporting.render(report)
        self.assertEqual([item["key"] for item in report["known_issues"]], ["settings-path", "uncertain"])
        self.assertIn("## Known issues not fixed here", text)
        self.assertIn("Settings lookup uses a different path", text)
        self.assertIn("plugin_config.py:42", text)
        self.assertIn("selected different overrides", text)
        self.assertIn("Pre-existing defect outside this change", text)
        self.assertIn("uncertain; Low; pre-existing", text)
        self.assertNotIn("Refuted claim", text)
        self.assertNotIn("Cosmetic preference", text)
        self.assertEqual((report["counted_only"], report["fixed"], report["pending"]), (3, 1, 1))

    def test_handback_and_schema_one_evidence_produce_the_same_report(self):
        value = finding()
        handback = {"candidates": [{"key": value["key"], "locations": value["locations"]}],
                    "assessments": [value]}
        state = {"findings": {"F001": {
            "key": value["key"], "summary": value["title"], "validation": "valid",
            "disposition": "ignored", "severity": "Low",
            "decisions": [{"validation": "valid", "disposition": "ignored", "severity": "Low",
                           "reason": "Assessment recorded", "evidence": [
                               json.dumps({"assessment": value})]}],
        }}}
        expected = reporting.project(reporting.records(handback))
        self.assertEqual(reporting.project(reporting.records(state)), expected)
        state["findings"]["F001"]["disposition"] = "fixed"
        self.assertEqual(reporting.project(reporting.records(state))["known_issues"], [])
        state["findings"]["F001"].update(validation="pending", disposition="open")
        self.assertEqual(reporting.records(state)[0]["validation"], "pending")

    def test_later_empty_reviews_do_not_erase_findings_but_resolutions_do(self):
        progress = {}
        followups.retain(progress, {"assessments": [finding()]})
        followups.retain(progress, {"assessments": []})
        self.assertEqual(len(followups.presentation(progress, self.settings)["known_issues"]), 1)
        followups.retain(progress, {"assessments": [finding(disposition="fixed")]})
        self.assertEqual(followups.presentation(progress, self.settings)["known_issues"], [])
        followups.retain(progress, {"assessments": [finding(validation="uncertain")]})
        self.assertEqual(len(followups.presentation(progress, self.settings)["known_issues"]), 1)
        followups.retain(progress, {"assessments": [finding(validation="invalid")]})
        self.assertEqual(followups.presentation(progress, self.settings)["known_issues"], [])

    def test_missing_or_rejected_duplicate_target_does_not_hide_a_valid_defect(self):
        for target in ("missing", "invalid", "style", "self"):
            with self.subTest(target=target):
                report = reporting.project([
                    finding("self", duplicate_of=target),
                    finding("invalid", validation="invalid"), finding("style", material=False)])
                self.assertEqual([item["key"] for item in report["known_issues"]], ["self"])

    def test_new_assessment_does_not_inherit_old_suppression(self):
        prior = [finding("duplicate", material=False, duplicate_of="canonical"), finding("canonical")]
        current = reporting.merge(prior, [{"key": "duplicate", "validation": "valid"}])
        self.assertEqual(len(reporting.project(current)["known_issues"]), 2)

    def test_legacy_materiality_and_invalidation_remain_visible_as_gaps(self):
        legacy = finding()
        del legacy["material"]
        progress = {}
        followups.retain(progress, {"assessments": [legacy]})
        followups.retain(progress, {"assessments": [
            {"key": legacy["key"], "validation": "pending", "snapshot": "new"}]})
        result = followups.presentation(progress, self.settings)
        self.assertEqual(result["known_issues"][0]["validation"], "uncertain")
        self.assertIn("awaits renewed validation", result["known_issues_report"])
        self.assertIn("materiality was not recorded", result["known_issues_report"])

    def test_publication_and_reporting_opt_outs_are_independent(self):
        progress = {}
        followups.retain(progress, {"assessments": [finding()]})
        self.settings.disabled.add(followups.FEATURE)
        self.assertFalse(followups.policy(self.manifest, self.settings)["enabled"])
        self.assertIn("Settings lookup", followups.presentation(progress, self.settings)["known_issues_report"])
        self.settings.disabled = {reporting.FEATURE}
        self.assertTrue(followups.policy(self.manifest, self.settings)["enabled"])
        report = followups.presentation(progress, self.settings)
        self.assertEqual(len(report["known_issues"]), 1)
        self.assertNotIn("Settings lookup", report["known_issues_report"])
        self.assertIn("disabled", report["known_issues_report"])

    def test_permission_is_not_inferred_from_pr_or_audit_approval(self):
        self.manifest["permissions"] = {"create_pr": True, "publish_audit": True}
        before = copy.deepcopy(self.manifest)
        self.assertFalse(followups.policy(self.manifest, self.settings)["enabled"])
        self.assertEqual(self.manifest, before)
        assignment = {"role": "draft", "follow_ups": followups.policy(self.manifest, self.settings)}
        prompt = followups.instructions(assignment, "/pinned")
        self.assertIn("Do not create follow-up issues", prompt)
        self.assertIn("Known issues not fixed here", prompt)
        self.manifest["permissions"]["create_follow_up_issues"] = True
        assignment["follow_ups"] = followups.policy(self.manifest, self.settings)
        self.assertIn("Create or reuse follow-up issues automatically",
                      followups.instructions(assignment, "/pinned"))
        self.assertEqual(followups.instructions({"role": "reviewer"}, "/pinned"), "")

    def test_failed_or_missing_ticket_receipts_do_not_hide_findings(self):
        progress = {}
        followups.retain(progress, {"assessments": [finding()]})
        for supplied in ({}, {"settings-path": {"status": "not_filed", "reason": "GitHub unavailable"}},
                         {"settings-path": {"status": "created", "url": "https://elsewhere.invalid/1"}},
                         {"settings-path": {"status": "created",
                                            "url": "https://github.com/fixture/project/issues/7"}}):
            followups.record(progress, {"follow_up_issues": supplied}, self.manifest, self.settings)
            result = followups.presentation(progress, self.settings)
            self.assertEqual(len(result["known_issues"]), 1)
            self.assertEqual(progress["follow_up_issues"]["settings-path"]["status"], "not_filed")
            self.assertIn("Settings lookup", result["known_issues_report"])

    def test_existing_links_survive_replay_and_failed_later_publication(self):
        progress = {}
        followups.retain(progress, {"assessments": [finding()]})
        url = "https://github.com/fixture/project/issues/7"
        supplied = {"settings-path": {"status": "created", "url": url, "reason": "Read back issue 7"}}
        followups.record(progress, {"follow_up_issues": supplied}, self.manifest, self.settings)
        followups.record(progress, {}, self.manifest, self.settings)
        failed = {"settings-path": {"status": "not_filed", "reason": "Search unavailable"}}
        followups.record(progress, {"follow_up_issues": failed}, self.manifest, self.settings)
        text = followups.presentation(progress, self.settings)["known_issues_report"]
        self.assertIn(url, text)
        self.assertIn("Earlier verified link retained", text)
        self.assertNotIn("Fixes #7", text)
        marker = followups.presentation(progress, self.settings)["known_issues"][0]["tracking_marker"]
        self.assertNotIn("settings-path", marker)
        self.assertEqual(marker, reporting.project([finding()])["known_issues"][0]["tracking_marker"])

    def test_unapproved_creation_is_not_acknowledged_as_success(self):
        progress = {}
        followups.retain(progress, {"assessments": [finding()]})
        self.manifest["permissions"]["create_follow_up_issues"] = False
        value = {"status": "created", "url": "https://github.com/fixture/project/issues/7",
                 "reason": "Claimed creation"}
        followups.record(progress, {"follow_up_issues": {"settings-path": value}}, self.manifest, self.settings)
        self.assertEqual(progress["follow_up_issues"]["settings-path"]["status"], "not_filed")
        self.assertIn("Unapproved creation", progress["follow_up_issues"]["settings-path"]["reason"])
        value["status"] = "reused"
        followups.record(progress, {"follow_up_issues": {"settings-path": value}}, self.manifest, self.settings)
        self.assertEqual(progress["follow_up_issues"]["settings-path"]["url"], value["url"])

    def test_unrecognized_input_is_not_an_empty_successful_report(self):
        with self.assertRaisesRegex(ValueError, "Expected assessed findings"):
            reporting.records({"outcome": "complete"})

    def test_pr_draft_withholds_sensitive_or_unassessed_disclosures_not_private_report(self):
        progress = {}
        followups.retain(progress, {"assessments": [
            finding("sensitive", sensitive=True, title="PRIVATE EXPLOIT", locations=["private.py:7"]),
            finding("unknown", sensitive=None, title="UNASSESSED DISCLOSURE", locations=["secret.py:8"]),
            finding("public"),
        ]})
        progress["follow_up_issues"] = {
            "public": {"status": "not_filed", "url": None, "reason": "PRIVATE API DIAGNOSTIC"}}
        result = followups.presentation(progress, self.settings)
        private, public = result["known_issues_report"], result["known_issues_pr_draft"]
        self.assertIn("PRIVATE EXPLOIT", private)
        self.assertIn("UNASSESSED DISCLOSURE", private)
        self.assertIn("PRIVATE API DIAGNOSTIC", private)
        for value in ("PRIVATE", "UNASSESSED DISCLOSURE", "private.py", "secret.py"):
            self.assertNotIn(value, public)
        self.assertEqual(public.count("### Finding withheld pending safe disclosure"), 2)
        self.assertIn("Settings lookup", public)

    def test_cli_and_review_options_honor_the_real_project_opt_out(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "handback.json"
            path.write_text(json.dumps({"assessments": [finding()]}))
            result = run_main(reporting, [str(path), "--format", "markdown"], cwd=root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Settings lookup", result.stdout)
            config = root / ".claude/ioncache-ai-tools.local.json"
            config.parent.mkdir()
            config.write_text(json.dumps({"features": {"review-known-issues": False}}))
            result = run_main(reporting, [str(path), "--format", "markdown"], cwd=root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("reporting is disabled", result.stdout)
            self.assertNotIn("Settings lookup", result.stdout)
            options = run_main(review_options, ["review-code"], cwd=root)
            self.assertEqual(options.returncode, 0, options.stderr)
            configured = json.loads(options.stdout)["configuration"]
            self.assertFalse(configured["known_issues_enabled"])
            self.assertNotIn("review-known-issues", configured["review_features"])
            self.assertTrue(configured["review_features"]["review-correctness"])


class ReportingInstructionTests(unittest.TestCase):
    def test_removing_the_named_section_requirement_breaks_each_caller_contract(self):
        root = Path(__file__).resolve().parents[1] / "skills"
        paths = ("review-code/ASSESSMENT.md", "review-validate-fix-loop/WORKFLOW.md",
                 "review-triage-loop/WORKFLOW.md", "autonomous-development/SKILL.md",
                 "autonomous-development/WORKERS.md", "autonomous-development/FOLLOW_UPS.md")
        requirement = "Known issues not fixed here"
        for name in paths:
            with self.subTest(caller=name):
                text = (root / name).read_text()
                self.assertIn(requirement, text)
                with self.assertRaises(AssertionError):
                    self.assertIn(requirement, text.replace(requirement, ""))


if __name__ == "__main__":
    unittest.main()
