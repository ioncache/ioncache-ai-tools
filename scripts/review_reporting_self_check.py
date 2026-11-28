"""Exercise named unresolved reporting and the existing publishers' follow-up contract."""

import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import development_followups as followups
import review_reporting as reporting
import review_options
import review_timing as timing
from self_check_support import run_main


def finding(key="settings-path", **changes):
    result = {
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
    result.setdefault("public", {name: result[name] for name in
                                 ("title", "summary", "locations", "reason", "next_step")})
    return result


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

    def test_reassessment_requires_its_own_disclosure_clearance(self):
        for separate_reviews in (False, True):
            for cleared in (False, True):
                with self.subTest(separate_reviews=separate_reviews, cleared=cleared):
                    updated = finding(title="Updated disclosure", evidence=["New private evidence"])
                    del updated["sensitive"]
                    if cleared:
                        updated["sensitive"] = False
                    progress = {}
                    if separate_reviews:
                        followups.retain(progress, {"assessments": [finding()]})
                        followups.retain(progress, {"assessments": [updated]})
                    else:
                        followups.retain(progress, {"assessments": [finding(), updated]})
                    result = followups.presentation(progress, self.settings)
                    self.assertIn("New private evidence", result["known_issues_report"])
                    self.assertNotIn("New private evidence", result["known_issues_pr_draft"])
                    self.assertEqual("Updated disclosure" in result["known_issues_pr_draft"], cleared)

    def test_public_draft_uses_only_the_explicit_public_presentation(self):
        private = finding("PRIVATE-KEY", title="PRIVATE-TITLE", summary="PRIVATE-SUMMARY",
                          locations=["/private/location.py:9"], evidence=["PRIVATE-EVIDENCE"],
                          confidence="High: PRIVATE-INVESTIGATION",
                          reason="PRIVATE-REASON", next_step="PRIVATE-NEXT-STEP", public={
                              "title": "Safe title", "summary": "Safe consequence",
                              "locations": ["src/app.py:9"], "reason": "Deferred follow-up",
                              "next_step": "Investigate the public symptom",
                              "evidence": ["PRIVATE-EXTRA-FIELD"],
                          })
        for presentation in (private["public"], None, {"title": "Incomplete presentation"}):
            with self.subTest(presentation=presentation):
                progress = {}
                followups.retain(progress, {"assessments": [{**private, "public": presentation}]})
                result = followups.presentation(progress, self.settings)
                self.assertIn("PRIVATE-EVIDENCE", result["known_issues_report"])
                self.assertNotIn("PRIVATE-", result["known_issues_pr_draft"])
                self.assertNotIn("/private/", result["known_issues_pr_draft"])
                if presentation == private["public"]:
                    self.assertIn("Safe consequence", result["known_issues_pr_draft"])
                    self.assertIn("src/app.py:9", result["known_issues_pr_draft"])
                else:
                    self.assertIn("Finding withheld", result["known_issues_pr_draft"])

    def test_reassessment_does_not_inherit_an_earlier_public_presentation(self):
        progress = {}
        followups.retain(progress, {"assessments": [finding()]})
        updated = finding(summary="Changed finding")
        del updated["public"]
        followups.retain(progress, {"assessments": [updated]})
        result = followups.presentation(progress, self.settings)
        self.assertIn("Changed finding", result["known_issues_report"])
        self.assertIn("Finding withheld", result["known_issues_pr_draft"])

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
        assignment = {"follow_ups": followups.policy(self.manifest, self.settings)}
        prompt = followups.instructions(assignment, "draft", "/pinned")
        self.assertIn("Do not create follow-up issues", prompt)
        self.assertIn("Known issues not fixed here", prompt)
        self.manifest["permissions"]["create_follow_up_issues"] = True
        assignment["follow_ups"] = followups.policy(self.manifest, self.settings)
        approved = followups.instructions(assignment, "draft", "/pinned")
        self.assertIn("Create or reuse follow-up issues automatically", approved)
        # Confirmed defects are classified with the repository's own bug type and label.
        self.assertIn("existing bug issue type and bug label", approved)
        self.assertNotIn("bug issue type", prompt)
        self.assertEqual(followups.instructions(assignment, "reviewer", "/pinned"), "")

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
        result = followups.presentation(progress, self.settings)
        text = result["known_issues_report"]
        self.assertIn(url, text)
        self.assertIn(url, result["known_issues_pr_draft"])
        self.assertNotIn("settings-path", result["known_issues_pr_draft"])
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

    def test_revoked_creation_retains_only_validated_private_diagnostics(self):
        self.assertTrue(followups.policy(self.manifest, self.settings)["enabled"])
        self.settings.disabled.add(followups.FEATURE)
        for url, valid in (
            ("https://github.com/fixture/project/issues/7", True),
            ("https://github.com/fixture/other/issues/7", False),
            ("https://github.com/fixture/project/issues/7?private=diagnostic", False),
        ):
            with self.subTest(url=url):
                progress = {}
                followups.retain(progress, {"assessments": [finding()]})
                value = {"status": "created", "url": url, "reason": "Observed before settings changed"}
                followups.record(progress, {"follow_up_issues": {"settings-path": value}},
                                 self.manifest, self.settings)
                receipt = progress["follow_up_issues"]["settings-path"]
                self.assertEqual(receipt["status"], "not_filed")
                self.assertIsNone(receipt["url"])
                result = followups.presentation(progress, self.settings)
                self.assertEqual(url in result["known_issues_report"], valid)
                self.assertNotIn(url, result["known_issues_pr_draft"])
                self.assertIn("not_filed", result["known_issues_pr_draft"])
        self.assertFalse(followups.policy(self.manifest, self.settings)["enabled"])

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


class TimingTests(unittest.TestCase):
    def stamp(self, seconds):
        start = datetime(2026, 11, 28, tzinfo=timezone.utc)
        return {"at": (start + timedelta(seconds=seconds)).isoformat(),
                "source": "Offline fixture observation, not a native review"}

    def span(self, start, end):
        return {"started": self.stamp(start), "finished": self.stamp(end)}

    def fixture(self):
        agents = [
            ("COR", "reviewer", "correctness", 60, 360),
            ("SEC", "reviewer", "security", 60, 300),
            ("DOC", "reviewer", "documentation", 60, 180),
            ("DOC-assess", "adjudicator", None, 180, 240),
            ("SEC-assess", "adjudicator", None, 330, 390),
            ("COR-assess", "adjudicator", None, 360, 450),
            ("merge", "adjudicator", None, 450, 510),
        ]
        return {
            "schema": 1, "review": "fixture-review", **self.span(0, 540),
            "agents": [{"id": key, "role": role, "category": category, "worker": None,
                        "status": "complete", "queued": self.stamp(300 if key == "SEC-assess" else start),
                        "collected": self.stamp(end), **self.span(start, end)}
                       for key, role, category, start, end in agents],
            "stages": [{"id": name, "name": name, "status": "complete", **self.span(start, end)}
                       for name, start, end in (("setup", 0, 60), ("adjudication", 360, 450),
                                               ("final_merge", 450, 510), ("posting", 510, 540))],
            "waits": [{"id": "merge-wait", "waiting": "merge", "blocked_by": ["COR-assess", "SEC-assess"],
                       "reason": "Awaiting report assessments", **self.span(240, 450)}],
            "limitations": [],
        }

    def test_compact_summary_and_detailed_timeline_share_retained_measurements(self):
        document = self.fixture()
        original = copy.deepcopy(document)
        report = timing.project(document)
        self.assertEqual(report["seconds"], 540)
        self.assertEqual(report["longest_reviewer_seconds"], 300)
        summary = timing.render(report)
        self.assertEqual(summary.splitlines(), [
            "Total elapsed: 9m 00s",
            "Setup: 1m \u00b7 Longest reviewer: 5m \u00b7 Adjudication: 1m 30s \u00b7 "
            "Final merge: 1m \u00b7 Posting: 30s",
        ])
        details = timing.render(report, details=True)
        self.assertTrue(details.startswith(summary))
        self.assertIn("### Agents", details)
        self.assertIn("### Timeline", details)
        self.assertIn("### Recorded waits", details)
        self.assertIn("merge: 3m 30s; waiting on COR-assess, SEC-assess", details)
        self.assertIn("not added to elapsed time", details)
        for agent in document["agents"]:
            self.assertIn("| " + agent["id"] + " |", details)
        security = next(row for row in report["agents"] if row["id"] == "SEC-assess")
        self.assertEqual(security["queue_seconds"], 30)
        self.assertEqual(security["collection_seconds"], 0)
        self.assertEqual(document, original)
        self.assertEqual(report, timing.project(document))
        document["limitations"] = ["Observed window excludes earlier setup."]
        self.assertIn("Observed window excludes earlier setup.", timing.render(timing.project(document)))

    def test_overlap_is_not_added_twice_and_staggered_reviewers_are_not_summed(self):
        document = self.fixture()
        document["agents"][2].update(self.span(120, 240))
        document["agents"][2]["queued"] = self.stamp(120)
        document["agents"][2]["collected"] = self.stamp(250)
        document["stages"] += [
            {"id": "second-observation", "name": "adjudication", **self.span(400, 470)},
        ]
        report = timing.project(document)
        self.assertEqual(report["summary"]["adjudication"]["seconds"], 110)
        self.assertEqual(report["longest_reviewer_seconds"], 300)
        self.assertEqual(report["agents"][2]["collection_seconds"], 10)
        self.assertEqual(report["seconds"], 540)
        document["stages"].append({"name": "adjudication", **self.span(470, 480)})
        partial = timing.project(document)
        self.assertIsNone(partial["summary"]["adjudication"]["seconds"])
        self.assertEqual(partial["longest_reviewer_seconds"], 300)

    def test_unknown_observations_stay_unknown_without_hiding_other_agents(self):
        document = self.fixture()
        document["agents"][0]["finished"] = None
        document["agents"][1]["started"] = {"at": "2026-11-28T00:01:00", "source": "No timezone"}
        document["stages"][-1] = {"id": "posting", "name": "posting", "status": "skipped"}
        report = timing.project(document)
        self.assertIsNone(report["longest_reviewer_seconds"])
        self.assertIsNone(report["agents"][0]["elapsed_seconds"])
        self.assertIsNone(report["agents"][1]["elapsed_seconds"])
        self.assertEqual(report["agents"][2]["elapsed_seconds"], 120)
        self.assertIn("Posting: not run", timing.render(report))
        details = timing.render(report, details=True)
        self.assertIn("COR: interval unavailable", details)
        self.assertIn("explicit timezone", details)
        document["started"] = None
        unknown = timing.project(document)
        self.assertIn("Total elapsed: unavailable", timing.render(unknown))
        self.assertIn("Timeline scale unavailable", timing.render(unknown, details=True))
        self.assertEqual(unknown["agents"][2]["elapsed_seconds"], 120)

    def test_duration_only_evidence_does_not_invent_timeline_positions(self):
        document = self.fixture()
        first = document["agents"][0]
        first.update(started=None, finished=None, duration={"seconds": 300, "source": "Native completion"})
        report = timing.project(document)
        self.assertEqual(report["longest_reviewer_seconds"], 300)
        self.assertIn("5m (reported)", timing.render(report, details=True))
        self.assertIn("COR: interval unavailable", timing.render(report, details=True))
        for seconds in (-1, True, float("inf"), float("nan")):
            with self.subTest(seconds=seconds):
                first["duration"]["seconds"] = seconds
                report = timing.project(document)
                self.assertIsNone(report["agents"][0]["elapsed_seconds"])

    def test_bad_timestamps_and_duplicate_records_preserve_valid_partial_output(self):
        for change in ("backwards", "outside", "unsourced", "duplicate"):
            with self.subTest(change=change):
                document = self.fixture()
                first = document["agents"][0]
                if change == "backwards":
                    first.update(self.span(360, 60))
                elif change == "outside":
                    first.update(self.span(-30, 360))
                elif change == "unsourced":
                    first["started"] = {"at": self.stamp(60)["at"]}
                else:
                    document["agents"].append(copy.deepcopy(first))
                report = timing.project(document)
                self.assertTrue(report["limitations"])
                self.assertIsNone(report["longest_reviewer_seconds"])
                self.assertIn("SEC", timing.render(report, details=True))
                self.assertEqual(report["seconds"], 540)

    def test_failed_cancelled_and_unfinished_attempts_are_not_dropped(self):
        document = self.fixture()
        for row, state in zip(document["agents"], ("failed", "cancelled", "running")):
            row["status"] = state
        document["agents"][2]["finished"] = None
        report = timing.project(document)
        details = timing.render(report, details=True)
        for state in ("failed", "cancelled", "running"):
            self.assertIn("| " + state + " |", details)
        self.assertEqual(report["agents"][0]["elapsed_seconds"], 300)
        self.assertIsNone(report["agents"][2]["elapsed_seconds"])
        self.assertIn("unavailable", details)

    def test_reporting_opt_out_and_malformed_input_never_write_or_launch_work(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "timing.json"
            path.write_text(json.dumps(self.fixture()))
            original = path.read_bytes()
            result = run_main(timing, ["report", str(path)], cwd=root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("### Agents", result.stdout)
            detailed = run_main(timing, ["report", str(path), "--run-details"], cwd=root)
            self.assertEqual(detailed.returncode, 0, detailed.stderr)
            self.assertIn("### Agents", detailed.stdout)
            self.assertEqual(path.read_bytes(), original)
            path.write_text("{")
            failed = run_main(timing, ["report", str(path)], cwd=root)
            self.assertEqual(failed.returncode, 2)
            self.assertIn("Total elapsed: unavailable", failed.stdout)
            self.assertEqual(path.read_text(), "{")
            failed_json = run_main(timing, ["report", str(path), "--format", "json"], cwd=root)
            self.assertEqual(failed_json.returncode, 2)
            self.assertIsNone(json.loads(failed_json.stdout)["seconds"])
            config = root / ".claude/ioncache-ai-tools.local.json"
            config.parent.mkdir()
            config.write_text(json.dumps({"features": {"review-timing": False}}))
            before = config.read_bytes()
            disabled = run_main(timing, ["report", str(path), "--run-details"], cwd=root)
            self.assertEqual(disabled.returncode, 0, disabled.stderr)
            self.assertIn("Total elapsed: unavailable (timing reporting disabled)", disabled.stdout)
            self.assertEqual(config.read_bytes(), before)
            options = run_main(review_options, ["review-code", "--run-details"], cwd=root)
            normalized = json.loads(options.stdout)
            self.assertTrue(normalized["run_details"])
            self.assertFalse(normalized["configuration"]["timing_enabled"])
            self.assertNotIn("review-timing", normalized["configuration"]["review_features"])
            path.write_bytes(original)
            config.write_text('{"features": {"review-timing": true}}')
            recovered = run_main(timing, ["report", str(path), "--format", "json"], cwd=root)
            self.assertEqual(recovered.returncode, 0, recovered.stderr)
            self.assertEqual(json.loads(recovered.stdout)["seconds"], 540)
            clock = run_main(timing, ["stamp"], cwd=root)
            self.assertEqual(clock.returncode, 0, clock.stderr)
            observed = json.loads(clock.stdout)
            self.assertIsNotNone(datetime.fromisoformat(observed["at"]).utcoffset())
            self.assertIn("caller clock", observed["source"])
            config.write_text("{")
            unavailable = run_main(timing, ["stamp"], cwd=root)
            self.assertEqual(unavailable.returncode, 2)
            self.assertIsNone(json.loads(unavailable.stdout))
            self.assertEqual(config.read_text(), "{")


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
