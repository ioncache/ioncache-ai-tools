#!/usr/bin/env python3
"""Exercise the ledger CLI against isolated Git repositories, without host agents."""

import json
from itertools import count, product
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import review_ledger
import review_options
import review_assignments


HELPER = Path(__file__).with_name("review_ledger.py")
PASSES = [{"name": "correctness", "worker": "independent-reviewer",
           "result": "complete", "evidence": "Traced fixture callers and requirements"}]
CHECKS = [{"name": "fixture check", "result": "passed", "evidence": "Fixture assertion passed"}]
WORKER_IDS = count()


def coordinated_pass(snapshot, mode, strategy="specialists", *, review_type="correctness"):
    return {**PASSES[0], "name": review_type,
            "worker": f"{mode}-{review_type}-specialist-{next(WORKER_IDS)}",
            "evidence": json.dumps({
                "assignment": review_type, "review_type": review_type,
                "instruction_set": {"sources": [f"fixture/{review_type}.md"],
                                    "identity": f"fixture-{review_type}-instructions"},
                "snapshot": snapshot, "mode": mode, "strategy": strategy,
                "result_file": f"/private/review-fixture/{review_type}.json",
                "review_options": review_options.parse_options("review-validate-fix-loop", [
                    "--model-selection", "configured", "--lead-model", "fixture-lead",
                    "--fallback", "configured", "--strategy", strategy,
                ]),
                "selection": {"requested": "configured default", "selected": "configured default",
                              "actual": "unknown", "reason": "Discovery unavailable in fixture",
                              "availability_source": "unavailable",
                              "suitability_source": "unavailable", "constraints": [],
                              "limitations": ["Actual model not exposed"]},
                "coverage": ["Read app.txt in full; traced fixture callers and requirements"],
                "limitations": []})}


class ReviewLedgerTests(unittest.TestCase):
    def setUp(self):
        """Isolate Git configuration and files so fixtures cannot affect a real project."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name).resolve()
        self.root = self.folder / "repository"
        self.root.mkdir()
        self.cwd = self.root
        self.env = {**os.environ, "HOME": str(self.folder / "home"),
                    "XDG_STATE_HOME": str(self.folder / "state"),
                    "CODEX_HOME": str(self.folder / "home/.codex"),
                    "COPILOT_HOME": str(self.folder / "home/.copilot"), "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_CONFIG_GLOBAL": os.devnull, "PYTHONDONTWRITEBYTECODE": "1"}
        for key in list(self.env):
            if key.startswith(("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")):
                self.env.pop(key)
        environment = patch.dict(os.environ, self.env, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.storage = review_ledger.storage(self.root)
        self.git("init", "-q")
        self.git("config", "user.name", "Ledger fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.root / "app.txt").write_text("before\n")
        (self.root / ".gitignore").write_text(".review-loop/\nignored.txt\n")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        self.state = None

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, env=self.env,
                              check=True, capture_output=True).stdout

    def cli(self, args, event=None, ok=True):
        """Use a fresh process so assertions depend on persisted state, not memory.

        Successful calls return decoded JSON; expected failures return stderr
        only after checking exit 2 and an empty protocol stream.
        """
        result = subprocess.run([sys.executable, str(HELPER), *args], cwd=self.cwd,
                                env=self.env, text=True, input=json.dumps(event),
                                capture_output=True)
        if not ok:
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertIn("review-ledger:", result.stderr)
            return result.stderr
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def init(self, *args):
        """Retain the helper's run path so later calls exercise the same durable ledger."""
        self.state = self.cli(["init", "--objective", "Correct fixture behavior",
                               "--scope", "repository", *args])
        self.ledger = self.state["ledger"]

    def event(self, kind, **values):
        return {"type": kind, "actor": "fixture-coordinator",
                "reason": "Supported by fixture evidence", **values}

    def send(self, kind, **values):
        """Advance the fixture revision only after the CLI accepts an event."""
        self.state = self.cli(["apply", self.ledger, "--revision",
                               str(self.state["revision"])], self.event(kind, **values))
        return self.state

    def reject(self, kind, **values):
        """Require an explicit protocol failure without advancing fixture state."""
        return self.cli(["apply", self.ledger, "--revision",
                         str(self.state["revision"])], self.event(kind, **values), ok=False)

    def review(self):
        self.send("start_review")
        self.send("review_done", passes=PASSES, checks=CHECKS)

    def finding(self, key="behavior"):
        self.send("finding", key=key, summary="Incorrect fixture behavior",
                  locations=["app.txt:1"], severity="High", evidence=["Reproduced failure"])

    def decide(self, key="F001", disposition="open", validation="valid"):
        self.send("decision", id=key, validation=validation, disposition=disposition,
                  severity="High", evidence=["Compared fixture against its requirement"])

    def fix(self, result="applied"):
        """Give every attempt distinct file bytes so applied-fix checks see a real delta."""
        self.send("start_fix", findings=["F001"], files=["app.txt"])
        (self.root / "app.txt").write_text(f"fixed {self.state['revision']}\n")
        self.send("fix_done", results={"F001": {"result": result, "evidence": "Edited fixture"}},
                  checks=CHECKS)
        self.send("fixes_reviewed", passes=PASSES)

    def test_reconcile_reconfirms_verified_fix_without_another_edit(self):
        self.init("--max-loops", "2", "--max-fix-cycles", "1")
        self.review()
        self.finding()
        self.decide()
        self.fix()
        self.decide(disposition="fixed")
        self.send("advance")
        before = (self.root / "app.txt").read_bytes()
        self.send("reconcile", evidence=["Required category coverage changed"])
        self.review()
        self.decide(disposition="fixed")
        self.send("advance")
        self.assertEqual(self.state["outcome"], "completed")
        self.assertEqual(len(self.state["loops"]), 2)
        self.assertEqual(sum(len(loop["cycles"]) for loop in self.state["loops"]), 1)
        self.assertEqual((self.root / "app.txt").read_bytes(), before)
        self.assertEqual(self.cli(["status", self.ledger])["outcome"], "completed")

    def phase_plan(self, kind):
        features = {row["feature"]: True for row in review_assignments.catalog()["categories"]}
        request = {
            "objective": "Correct fixture behavior", "kind": kind, "target": "repository",
            "base": self.git("rev-parse", "HEAD").decode().strip(),
            "snapshot": self.cli(["fingerprint"])["snapshot"], "root": str(self.root),
            "files": ["app.txt"], "constraints": ["Offline fixture; no model launches"],
            "language_inventory": {
                "app.txt": {"languages": [], "evidence": "Plain-text transition fixture, no source code"},
            },
            "scratch_directory": str(self.root.with_name(self.root.name + "-uncreated-private")),
            "review_options": {"configuration": {"skill_enabled": True, "review_features": features}},
        }
        if kind == "focused":
            cycle = self.state["loops"][-1]["cycles"][-1]
            request["correction"] = {
                "before": cycle["before"], "after": cycle["after"],
                "delta": self.cli(["diff", self.ledger, "--from", cycle["before"],
                                  "--to", cycle["after"]]),
            }
        return review_assignments.prepare(request)

    def test_full_and_focused_phase_plans_resume_without_private_prompt_files(self):
        self.init()
        full = self.phase_plan("full")
        self.send("start_review", reason=json.dumps({"phase_plan": full}))
        stopped = {"phase_plan": full, "attempts": [], "active": {},
                   "consumed_replacements": {}, "history_complete": True}
        self.send("stop", outcome="interrupted", reason=json.dumps(stopped))
        self.send("resume")
        history = self.cli(["status", self.ledger])["history"]
        self.assertEqual(json.loads(history[-2]["reason"]), stopped)
        self.assertEqual(len(self.state["loops"]), 1)
        self.assertFalse(Path(full["request"]["scratch_directory"]).exists())
        passes = [{"name": key, "worker": f"offline-full-{key}", "result": "complete",
                   "evidence": "Offline transition fixture, not native review evidence"}
                  for key in full["required"]]
        self.send("review_done", passes=passes, checks=CHECKS)
        self.finding()
        self.decide()
        self.send("start_fix", findings=["F001"], files=["app.txt"])
        (self.root / "app.txt").write_text("corrected before focused preparation\n")
        after = self.cli(["fingerprint"])["snapshot"]
        self.assertIn("Unknown snapshot", self.cli(
            ["diff", self.ledger, "--from", self.state["snapshot"], "--to", after], ok=False))
        self.send("fix_done", checks=CHECKS,
                  results={"F001": {"result": "applied", "evidence": "Changed fixture bytes"}})
        focused = self.phase_plan("focused")
        self.assertTrue(focused["request"]["correction"]["delta"],
                        "The focused plan must contain the actual correction, not a before-to-before diff")
        self.assertEqual(focused["request"]["correction"]["after"], after)
        self.assertIn("+corrected before focused preparation",
                      focused["request"]["correction"]["delta"][0]["diff"])
        stopped["phase_plan"] = focused
        self.send("stop", outcome="interrupted", reason=json.dumps(stopped))
        self.send("resume")
        restored = json.loads(self.cli(["status", self.ledger])["history"][-2]["reason"])
        self.assertEqual(restored, stopped)
        self.assertEqual(restored["phase_plan"]["technical_applicability"]["jsdoc"]["status"],
                         "not_applicable")
        self.assertNotIn("jsdoc", restored["phase_plan"]["required"])
        self.assertEqual(self.state["phase"], "reviewing_fixes")
        self.assertEqual(len(self.state["loops"][0]["cycles"]), 1)
        self.assertFalse(Path(focused["request"]["scratch_directory"]).exists())
        self.send("stop", outcome="stalled")

    def test_pending_applied_outcome_is_settled_before_reconciliation(self):
        self.init("--max-loops", "2", "--max-fix-cycles", "1")
        self.review()
        self.finding()
        self.decide()
        self.fix()
        self.send("stop", outcome="interrupted")
        self.send("resume")
        self.assertEqual(self.state["phase"], "validating_fixes")
        ledger_before = Path(self.ledger).read_bytes()
        error = self.reject("reconcile", evidence=["Coverage changed before outcome settlement"])
        self.assertIn("Settle", error)
        self.assertEqual(Path(self.ledger).read_bytes(), ledger_before)
        self.assertEqual(self.cli(["status", self.ledger])["phase"], "validating_fixes")
        self.decide(disposition="fixed")
        before = (self.root / "app.txt").read_bytes()
        self.send("reconcile", evidence=["New required category after focused coverage closed"])
        self.review()
        self.decide(disposition="fixed")
        self.send("advance")
        self.assertEqual(self.state["outcome"], "completed")
        self.assertEqual((self.root / "app.txt").read_bytes(), before)

    def test_unsettled_focused_outcome_does_not_prevent_drift_reconciliation(self):
        self.init()
        self.review()
        self.finding()
        self.decide()
        self.fix()
        applied = self.state["loops"][0]["cycles"][0]["result"]
        (self.root / "app.txt").write_text("External source change\n")
        self.assertIn("Worktree drift", self.reject(
            "decision", id="F001", validation="valid", disposition="fixed",
            severity="High", evidence=["Old focused evidence cannot verify changed source"]))
        self.send("reconcile", evidence=["Actual source drift requires fresh coverage"])
        self.assertEqual(self.state["phase"], "ready_review")
        self.assertEqual(self.state["loops"][0]["cycles"][0]["result"], applied)
        self.review()
        self.reject("decision", id="F001", validation="valid", disposition="fixed",
                    severity="High", evidence=["Do not bless the changed snapshot"])
        self.send("stop", outcome="stalled")
        self.assertEqual(self.cli(["status", self.ledger])["outcome"], "stalled")

    def test_failed_outcome_settlement_keeps_reconciliation_available(self):
        self.init()
        self.review()
        self.finding()
        self.decide()
        self.fix()
        self.assertIn("Settle", self.reject("reconcile", evidence=["Unsettled outcome"]))
        self.decide(disposition="fix_failed")
        self.send("reconcile", evidence=["Outcome settled without claiming success"])
        self.assertEqual(self.state["phase"], "ready_review")
        self.assertEqual(self.state["findings"]["F001"]["decisions"][-1]["disposition"], "fix_failed")
        self.send("stop", outcome="stalled")

    def test_historical_unsettled_reconciliation_remains_readable(self):
        self.init()
        self.review()
        self.finding()
        self.decide()
        self.fix()
        path = Path(self.ledger)
        history = json.loads(path.read_text())
        event = self.event("reconcile", evidence=["Historically accepted unsettled reconciliation"])
        event.update(snapshot=self.state["snapshot"], sequence=self.state["revision"] + 1,
                     time="historical fixture")
        history["events"].append(event)
        path.write_text(json.dumps(history))
        original = path.read_bytes()
        self.state = self.cli(["status", self.ledger])
        self.assertEqual(self.state["phase"], "ready_review")
        self.assertEqual(path.read_bytes(), original)
        self.review()
        self.assertIn("No interrupted focused review", self.reject(
            "decision", id="F001", validation="valid", disposition="fixed",
            severity="High", evidence=["Historical acceptance does not establish verification"]))
        self.send("stop", outcome="stalled")

    def test_open_focused_plan_retirement_verifies_applied_fix_without_another_edit(self):
        for retirement in ("language", "schema"):
            with self.subTest(retirement=retirement):
                self.init("--max-loops", "2", "--max-fix-cycles", "1")
                self.review()
                self.finding()
                self.decide()
                self.send("start_fix", findings=["F001"], files=["app.txt"])
                (self.root / "app.txt").write_text(f"module.exports = '{retirement}'\n")
                self.send("fix_done", checks=CHECKS,
                          results={"F001": {"result": "applied", "evidence": "Actual fixture edit"}})
                retained = self.state["loops"][0]["cycles"][0]["result"]
                plan = self.phase_plan("focused")
                request = json.loads(json.dumps(plan["request"]))
                request["language_inventory"]["app.txt"] = {
                    "languages": ["javascript"], "evidence": "Inspected the fixture's JavaScript source",
                }
                if retirement == "schema":
                    plan.pop("identity")
                    plan["schema"] = 1
                    plan = review_assignments.seal(plan)
                with self.assertRaisesRegex(ValueError, "new phase"):
                    review_assignments.prepare(request, plan)
                self.reject("decision", id="F001", validation="valid", disposition="fixed",
                            severity="High", evidence=["Focused coverage is not complete"])
                self.reject("fixes_reviewed", passes=[{**PASSES[0], "result": "partial"}])
                self.send("stop", outcome="interrupted", reason=json.dumps({"phase_plan": plan}))
                self.send("resume")
                self.assertEqual(self.state["phase"], "reviewing_fixes")
                before = (self.root / "app.txt").read_bytes()
                self.send("reconcile", evidence=["Retired invalid focused applicability", json.dumps(plan)])
                request["kind"] = "full"
                request.pop("correction")
                fresh = review_assignments.prepare(request)
                self.send("start_review", reason=json.dumps({"phase_plan": fresh}))
                passes = [{**PASSES[0], "name": key, "worker": f"fresh-full-{key}"}
                          for key in fresh["required"]]
                self.send("review_done", passes=passes, checks=CHECKS)
                self.send("decision", id="F001", validation="valid", disposition="fixed",
                          severity="High",
                          evidence=["Fresh full review and independent outcome assessment verify "
                                    "the retained applied correction at its unchanged after snapshot"])
                self.send("advance")
                replayed = self.cli(["status", self.ledger])
                self.assertEqual(replayed["outcome"], "completed")
                self.assertEqual(len(replayed["loops"]), 2)
                self.assertEqual(sum(len(loop["cycles"]) for loop in replayed["loops"]), 1)
                self.assertEqual(replayed["loops"][0]["cycles"][0]["result"], retained)
                self.assertNotIn("review", replayed["loops"][0]["cycles"][0])
                self.assertEqual((self.root / "app.txt").read_bytes(), before)
            if self.state and self.state["outcome"] in ("running", "interrupted", "blocked"):
                self.send("stop", outcome="stalled")

    def test_interrupted_applied_verification_keeps_snapshot_checks_and_decision_guards(self):
        cases = ("failed-fix", "failed-fix-check", "failed-current-check", "drift", "newer-decision",
                 "outer-limit")
        for case in cases:
            with self.subTest(case=case):
                self.init("--max-loops", "1" if case == "outer-limit" else "3",
                          "--max-fix-cycles", "1")
                self.review()
                self.finding()
                self.decide()
                self.send("start_fix", findings=["F001"], files=["app.txt"])
                (self.root / "app.txt").write_text(f"changed {case}\n")
                fix_checks = [{**CHECKS[0], "result": "failed"}] if case == "failed-fix-check" else CHECKS
                self.send("fix_done", checks=fix_checks, results={
                    "F001": {"result": "failed" if case == "failed-fix" else "applied",
                             "evidence": "Recorded fixture outcome"},
                })
                if case == "drift":
                    (self.root / "app.txt").write_text("unreviewed intervening source\n")
                self.send("reconcile", evidence=["Focused language applicability was invalid"])
                if case == "outer-limit":
                    self.assertEqual(self.state["outcome"], "limit_reached")
                    self.assertEqual(len(self.state["loops"]), 1)
                    self.reject("start_review")
                    continue
                self.send("start_review")
                current_checks = ([{**CHECKS[0], "result": "failed"}]
                                  if case == "failed-current-check" else CHECKS)
                self.send("review_done", passes=PASSES, checks=current_checks)
                if case == "newer-decision":
                    self.decide()
                    self.send("reconcile", evidence=["Another full review cannot erase reopening"])
                    self.review()
                before = Path(self.ledger).read_bytes()
                self.reject("decision", id="F001", validation="valid", disposition="fixed",
                            severity="High", evidence=["Application alone is insufficient"])
                self.assertEqual(Path(self.ledger).read_bytes(), before)
                self.send("stop", outcome="stalled")

    def test_reconfirmation_does_not_bless_unverified_or_reopened_findings(self):
        for case in ("never-fixed", "failed-checks", "recurrence"):
            with self.subTest(case=case):
                (self.root / "app.txt").write_text(f"before {case}\n")
                self.init()
                self.review()
                self.finding()
                self.decide()
                if case != "never-fixed":
                    self.fix()
                    self.decide(disposition="fixed")
                self.send("reconcile", evidence=["Required coverage changed"])
                self.send("start_review")
                checks = [{**CHECKS[0], "result": "failed"}] if case == "failed-checks" else CHECKS
                self.send("review_done", passes=PASSES, checks=checks)
                if case == "recurrence":
                    self.decide()
                before = Path(self.ledger).read_bytes()
                self.reject("decision", id="F001", validation="valid", disposition="fixed",
                            severity="High", evidence=["A prior application alone is not verification"])
                self.assertEqual(Path(self.ledger).read_bytes(), before)
                self.send("stop", outcome="stalled")

    def test_fingerprint_is_storeless_and_root_relative(self):
        before = self.git("status", "--porcelain")
        initial = self.cli(["fingerprint"])
        nested = self.root / "source folder"
        nested.mkdir()
        self.cwd = nested
        self.assertEqual(self.cli(["fingerprint"]), initial)
        self.assertEqual(initial["root"], str(self.root))
        self.assertIn("app.txt", initial["manifest"]["files"])
        self.assertEqual(self.git("status", "--porcelain"), before)
        self.assertFalse((self.root / ".review-loop").exists())

    def test_fingerprint_detects_dirty_added_and_deleted_inputs(self):
        initial = self.cli(["fingerprint"])
        (self.root / "app.txt").write_text("dirty\n")
        dirty = self.cli(["fingerprint"])
        self.assertNotEqual(dirty["snapshot"], initial["snapshot"])
        (self.root / "new.txt").write_text("untracked\n")
        added = self.cli(["fingerprint"])
        self.assertNotEqual(added["snapshot"], dirty["snapshot"])
        self.assertIn("new.txt", added["manifest"]["files"])
        (self.root / "app.txt").unlink()
        deleted = self.cli(["fingerprint"])
        self.assertNotEqual(deleted["snapshot"], added["snapshot"])
        self.assertNotIn("app.txt", deleted["manifest"]["files"])
        (self.root / "ignored.txt").write_text("excluded\n")
        self.assertEqual(self.cli(["fingerprint"]), deleted)
        self.assertFalse((self.root / ".review-loop").exists())

    def test_fingerprint_tracks_index_and_head_without_content_changes(self):
        (self.root / "app.txt").write_text("dirty\n")
        before = self.cli(["fingerprint"])
        self.git("add", "app.txt")
        staged = self.cli(["fingerprint"])
        self.assertEqual(staged["manifest"]["files"], before["manifest"]["files"])
        self.assertNotEqual(staged["snapshot"], before["snapshot"])
        self.git("commit", "-qm", "fixture staging")
        committed = self.cli(["fingerprint"])
        self.assertEqual(committed["manifest"]["files"], staged["manifest"]["files"])
        self.assertNotEqual(committed["snapshot"], staged["snapshot"])
        self.assertFalse((self.root / ".review-loop").exists())

    def test_fingerprint_rejects_drift_and_unsupported_files_without_storage(self):
        with patch("review_ledger.snapshot", side_effect=[{"head": "before"}, {"head": "after"}]):
            with self.assertRaisesRegex(review_ledger.LedgerError, "changed during fingerprint"):
                review_ledger.fingerprint(None, self.root)
        (self.root / "app.txt").unlink()
        os.mkfifo(self.root / "app.txt")
        self.assertIn("Unsupported", self.cli(["fingerprint"], ok=False))
        self.assertFalse((self.root / ".review-loop").exists())

    def test_coordinated_handbacks_preserve_schema_one_evidence(self):
        style_assessment = {
            "validator": "review-adjudicator", "report_action": "None",
            "reachability": "Accurate inline object type violates only a style convention",
            "confidence": "High", "priority": "No correction warranted",
        }
        for mode, strategy in product(("nested", "flat"), ("specialists", "sweep-first")):
            self.init()
            self.send("start_review")
            full_passes = [
                coordinated_pass(self.state["snapshot"], mode, strategy, review_type=purpose)
                for purpose in ("correctness", "documentation", "integration")
            ]
            for origin, basis in (("specialist", "observed"), ("coordinator", "inferred")):
                self.send("finding", key=f"{origin}-boundary", summary="Fixture boundary mismatch",
                          locations=["app.txt:1"], severity="High",
                          evidence=[f"origin={origin}; assignment=correctness; mode={mode}; basis={basis}"])
            self.send("finding", key="specialist-boundary", summary="Same boundary mismatch",
                      locations=["app.txt:1"], severity="High",
                      evidence=["origin=other-specialist; basis=observed; reproduced same failure"])
            self.send("finding", key="docs-style", summary="Accurate inline object type",
                      locations=["app.txt:1"], severity="Low",
                      evidence=["origin=docs; basis=inferred; kind=style; main_min_severity=Medium"])
            self.reject("decision", id="F002", validation="invalid", disposition="ignored",
                        severity="High", evidence=["Caller validation waits for completed passes"])
            self.send("review_done", passes=full_passes, checks=CHECKS)
            self.send("decision", id="F001", validation="valid", disposition="open", severity="High",
                      evidence=["validator=review-adjudicator; traced specialist evidence"])
            self.send("decision", id="F002", validation="invalid", disposition="ignored",
                      severity="High", evidence=["validator=independent-caller-validator; checked adjudicator claim"])
            self.send("decision", id="F003", validation="valid", disposition="ignored",
                      severity="Low", reason="Accurate documentation differs only in presentation",
                      evidence=[json.dumps(style_assessment)])
            self.send("start_fix", findings=["F001"], files=["app.txt"])
            (self.root / "app.txt").write_text(f"corrected {mode} {strategy}\n")
            self.send("fix_done", results={"F001": {"result": "applied", "evidence": "Correction"}},
                      checks=CHECKS)
            focused_passes = [
                coordinated_pass(self.state["snapshot"], mode, strategy, review_type=purpose)
                for purpose in ("correctness", "documentation", "integration")
            ]
            self.send("fixes_reviewed", passes=focused_passes)
            self.decide(disposition="fixed")
            self.send("advance")
            self.review()
            self.send("advance")
            report = self.cli(["status", self.ledger])
            self.assertEqual(report["outcome"], "completed_with_exceptions")
            self.assertEqual(len(report["loops"]), 2)
            self.assertEqual(len(report["loops"][0]["cycles"]), 1)
            self.assertEqual(report["loops"][0]["review"]["passes"], full_passes)
            self.assertEqual(report["loops"][0]["cycles"][0]["review"]["passes"], focused_passes)
            self.assertEqual(len(report["findings"]["F001"]["observations"]), 2)
            self.assertIn("basis=observed", report["findings"]["F001"]["observations"][0]["evidence"][0])
            self.assertIn("origin=other-specialist", report["findings"]["F001"]["observations"][1]["evidence"][0])
            self.assertIn("basis=inferred", report["findings"]["F002"]["observations"][0]["evidence"][0])
            self.assertIn("main_min_severity=Medium", report["findings"]["F003"]["observations"][0]["evidence"][0])
            self.assertEqual(report["findings"]["F003"]["severity"], "Low")
            self.assertEqual(report["findings"]["F003"]["validation"], "valid")
            self.assertEqual(report["findings"]["F003"]["disposition"], "ignored")
            self.assertEqual(json.loads(report["findings"]["F003"]["decisions"][0]["evidence"][0]),
                             style_assessment)
            self.assertEqual(report["findings"]["F003"]["decisions"][0]["reason"],
                             "Accurate documentation differs only in presentation")
            self.assertEqual(report["findings"]["F002"]["validation"], "invalid")
            self.assertIn("validator=independent-caller-validator",
                          report["findings"]["F002"]["decisions"][0]["evidence"][0])
            self.assertEqual(json.loads(Path(self.ledger).read_text())["schema"], 1)

    def test_ledger_accepts_mapped_workers_and_preserves_original_reports(self):
        for observed in (True, False):
            with self.subTest(caller_observes_identity=observed):
                self.init()
                self.send("start_review")
                for kind in ("review_done", "fixes_reviewed"):
                    original = {"assignment": f"{kind}-correctness", "worker": None,
                                "snapshot": self.state["snapshot"]}
                    native_worker = f"fixture-native-{kind}" if observed else None
                    mapped = {**PASSES[0],
                              "worker": native_worker or "unobserved (non-identity marker)",
                              "evidence": json.dumps({
                                  "original_report": original,
                                  "caller_observation": {
                                      "worker": native_worker,
                                      "source": "Synthetic caller fixture" if observed else "Not exposed",
                                  },
                                  "worker_field_kind": "native identity" if observed else "non-identity marker",
                                  "limitations": [] if observed else ["Native identity is unobserved"],
                              })}
                    values = {"checks": CHECKS} if kind == "review_done" else {}
                    self.assertIn("Expected non-empty text",
                                  self.reject(kind, passes=[{**mapped, "worker": None}], **values))
                    self.send(kind, passes=[mapped], **values)
                    saved = self.cli(["status", self.ledger])["history"][-1]["passes"][0]
                    self.assertEqual(saved, mapped)
                    self.assertEqual(json.loads(saved["evidence"])["original_report"], original)
                    if kind == "review_done":
                        self.finding()
                        self.decide()
                        self.send("start_fix", findings=["F001"], files=["app.txt"])
                        (self.root / "app.txt").write_text(f"corrected fixture {observed}\n")
                        self.send("fix_done", checks=CHECKS,
                                  results={"F001": {"result": "applied", "evidence": "Changed fixture"}})
                self.decide(disposition="fixed")
                self.send("advance")
                self.review()
                self.send("advance")
                self.assertEqual(self.state["outcome"], "completed")

    def test_incomplete_handbacks_preserve_diagnostics_and_resumability(self):
        for outcome in ("blocked", "interrupted", "failed", "stalled"):
            self.init()
            self.send("start_review")
            self.finding("received-before-failure")
            reason = json.dumps({"assignment": "correctness", "outcome": "failed",
                                 "selection": "configured default; actual unknown",
                                 "coverage": "partial", "diagnostics": "Fixture worker unavailable"})
            self.send("stop", outcome=outcome, reason=reason)
            report = self.cli(["status", self.ledger])
            self.assertEqual(report["stop_reason"], reason)
            self.assertEqual(report["findings"]["F001"]["validation"], "pending")
            self.assertNotIn("review_done", [event["type"] for event in report["history"]])
            if outcome in ("blocked", "interrupted"):
                self.send("resume")
                self.assertEqual(self.state["phase"], "reviewing")
                self.assertEqual(len(self.state["loops"]), 1)
                self.send("stop", outcome="failed")
            else:
                self.reject("resume")

    def test_incomplete_focused_handback_resumes_the_same_fix_cycle(self):
        self.init()
        self.review()
        self.finding()
        self.decide()
        self.send("start_fix", findings=["F001"], files=["app.txt"])
        (self.root / "app.txt").write_text("corrected\n")
        self.send("fix_done", results={"F001": {"result": "applied", "evidence": "Correction"}},
                  checks=CHECKS)
        self.finding("pending-integration-assessment")
        self.send("stop", outcome="blocked", reason="Focused specialist report unavailable")
        self.send("resume")
        self.assertEqual(self.state["phase"], "reviewing_fixes")
        self.assertEqual(len(self.state["loops"]), 1)
        self.assertEqual(len(self.state["loops"][0]["cycles"]), 1)
        self.reject("start_review")
        self.send("fixes_reviewed", passes=[coordinated_pass(self.state["snapshot"], "flat")])
        self.decide("F002", validation="invalid", disposition="ignored")
        self.decide(disposition="fixed")
        self.send("advance")
        self.assertEqual(self.state["phase"], "ready_review")

    def test_ledger_commands_from_subdirectories(self):
        """Changing the launch directory must not select a different run."""
        nested = self.root / "source folder"
        nested.mkdir()
        self.init()
        before = self.state["snapshot"]
        self.review()
        self.finding()
        self.decide()
        self.fix()
        for directory in (self.root, nested):
            self.cwd = directory
            for ledger in (self.ledger, os.path.relpath(self.ledger, self.root)):
                with self.subTest(directory=directory, ledger=ledger):
                    report = self.cli(["status", ledger])
                    self.assertEqual(report["ledger"], self.ledger)
                    self.assertEqual(report["revision"], self.state["revision"])
                    self.assertFalse(report["drift"])
                    self.state = self.cli(
                        ["apply", ledger, "--revision", str(self.state["revision"])],
                        self.event("stop", outcome="interrupted"))
                    self.assertEqual(self.state["outcome"], "interrupted")
                    self.state = self.cli(
                        ["apply", ledger, "--revision", str(self.state["revision"])],
                        self.event("resume"))
                    self.assertEqual(self.state["outcome"], "running")
                    differences = self.cli(["diff", ledger, "--from", before])
                    self.assertEqual(len(differences), 1)
                    self.assertEqual(differences[0]["file"], "app.txt")
                    self.assertIn("-before", differences[0]["diff"])
                    self.assertIn("+fixed", differences[0]["diff"])

    def test_ledger_paths_accept_external_storage_but_reject_another_owner(self):
        """Storage is external; ownership still binds it to the original checkout."""
        nested = self.root / "source"
        nested.mkdir()
        self.init()
        self.cwd = nested
        self.assertEqual(self.cli(["status", self.ledger])["snapshot"], self.state["snapshot"])
        for ledger in (self.storage.parent / ("a" * 64) / Path(self.ledger).parent.name / "REVIEW_LEDGER.json",
                       self.root / "storage" / Path(self.ledger).parent.name / "REVIEW_LEDGER.json"):
            with self.subTest(ledger=ledger):
                error = self.cli(["status", str(ledger)], ok=False)
                self.assertRegex(error, "different worktree|outside its repository")

    def test_ledger_paths_reject_symlink_run(self):
        """A valid-looking storage path cannot alias a run through a symlink."""
        self.init()
        alias = self.storage / ("b" * 32)
        alias.symlink_to(Path(self.ledger).parent)
        for ledger in (alias / "REVIEW_LEDGER.json",
                       Path(os.path.relpath(alias, self.root)) / "REVIEW_LEDGER.json"):
            with self.subTest(ledger=ledger):
                error = self.cli(["status", str(ledger)], ok=False)
                self.assertIn("Symlink not allowed", error)

    def test_external_storage_rejects_other_repositories_and_recovers(self):
        other = self.folder / "other-repository"
        subprocess.run(["git", "init", "-q", str(other)], env=self.env, check=True)
        for destination in (self.root / "state", other / "state", other / ".git/state"):
            with self.subTest(destination=destination):
                self.env["XDG_STATE_HOME"] = str(destination)
                self.assertIn("outside", self.cli(
                    ["init", "--objective", "Fixture", "--scope", "repository"], ok=False))
                self.assertFalse(destination.exists())
        self.env["XDG_STATE_HOME"] = str(self.folder / "state")
        self.init()
        self.assertFalse(Path(self.ledger).is_relative_to(self.root))

    def test_saved_history_and_diff_survive_missing_worktree(self):
        self.init()
        initial = self.state["snapshot"]
        self.review()
        self.finding()
        self.decide()
        self.fix()
        expected = self.cli(["diff", self.ledger, "--from", initial])
        self.root.rename(self.folder / "removed-worktree")
        self.cwd = self.folder
        saved = self.cli(["inspect", self.ledger])
        self.assertIsNone(saved["drift"])
        self.assertEqual(len(saved["loops"][0]["cycles"]), 1)
        self.assertEqual(expected, self.cli(["diff", self.ledger, "--from", initial]))
        self.cli(["status", self.ledger], ok=False)

    def test_external_run_recovery_keeps_different_runs_separate(self):
        invalid = self.root / "private-run"
        first = review_ledger.external_run_directory(invalid, "a" * 32, self.root)
        first.mkdir(parents=True)
        evidence = first / "retained.json"
        evidence.write_text("Retained first-run evidence\n")
        second = review_ledger.external_run_directory(invalid, "b" * 32, self.root)
        self.assertNotEqual(first, second)
        self.assertTrue(second.is_relative_to(Path(self.env["XDG_STATE_HOME"])))
        self.assertFalse(second.exists())
        self.assertFalse(invalid.exists())
        self.assertEqual(evidence.read_text(), "Retained first-run evidence\n")

    def test_external_run_recovery_preserves_checker_failure(self):
        with patch("review_ledger.subprocess.run", side_effect=FileNotFoundError("Git unavailable")) as command:
            with self.assertRaisesRegex(FileNotFoundError, "Git unavailable"):
                review_ledger.external_run_directory(self.folder / "private-run", "a" * 32, self.root)
        command.assert_called_once()

    def test_external_run_recovery_rejects_failed_git_probes(self):
        destination = self.folder / "private-run"
        failures = [
            (-15, b""),
            (128, b"fatal: detected dubious ownership in repository\n"),
            (1, b"Git probe failed\n"),
        ]
        for returncode, stderr in failures:
            with self.subTest(returncode=returncode):
                result = subprocess.CompletedProcess([], returncode, b"", stderr)
                with patch("review_ledger.subprocess.run", return_value=result) as command:
                    with self.assertRaisesRegex(OSError, "Git storage check unavailable"):
                        review_ledger.external_run_directory(destination, "a" * 32, self.root)
                command.assert_called_once()
                self.assertFalse(destination.exists())
        self.assertEqual(review_ledger.external_run_directory(destination, "a" * 32, self.root), destination)

    def legacy_run(self):
        source = self.root / ".review-loop" / Path(self.ledger).parent.name
        source.parent.mkdir(exist_ok=True)
        Path(self.ledger).parent.rename(source)
        return source

    def test_legacy_migration_preserves_bytes_and_consumed_work(self):
        self.init()
        self.review()
        self.finding()
        self.decide()
        self.send("start_fix", findings=["F001"], files=["app.txt"])
        source = self.legacy_run()
        original = review_ledger.stored_files(source)
        legacy = str(source / "REVIEW_LEDGER.json")
        self.assertIn("migrate", self.cli(["apply", legacy, "--revision", str(self.state["revision"])],
                                        self.event("stop", outcome="interrupted"), ok=False))
        self.assertIn("Legacy", self.cli(["init", "--objective", "Other", "--scope", "all"], ok=False))
        migrated = self.cli(["migrate", legacy, "--shutdown-evidence", "Fixture workers are stopped"])
        self.assertEqual(migrated["ledger"], self.ledger)
        self.assertEqual(original, review_ledger.stored_files(Path(self.ledger).parent))
        self.assertFalse((self.root / ".review-loop").exists())
        self.assertEqual(self.cli(["status", legacy])["revision"], self.state["revision"])
        (self.root / "discovered.txt").write_text("Necessary correction\n")
        self.send("fix_done", results={"F001": {"result": "applied", "evidence": "Fixed dependency"}},
                  checks=CHECKS)
        self.assertEqual(len(self.state["loops"][0]["cycles"]), 1)

    def test_migration_retry_keeps_newer_destination_events(self):
        self.init()
        source = self.legacy_run()
        args = SimpleNamespace(ledger=str(source / "REVIEW_LEDGER.json"), shutdown_evidence="Stopped")
        with patch("review_ledger.shutil.rmtree", side_effect=OSError("interrupted cleanup")):
            with self.assertRaisesRegex(OSError, "interrupted cleanup"):
                review_ledger.migrate(args, self.root)
        self.assertTrue(source.exists())
        self.send("start_review")
        newer = Path(self.ledger).read_bytes()
        self.cli(["migrate", args.ledger, "--shutdown-evidence", "Stopped"])
        self.assertEqual(Path(self.ledger).read_bytes(), newer)
        self.assertFalse(source.exists())
        self.assertFalse(self.cli(["migrate", args.ledger, "--shutdown-evidence", "Stopped"])["migrated"])
        self.assertFalse((self.root / ".review-loop").exists())

    def test_migration_retry_after_partial_source_deletion_preserves_history(self):
        self.init()
        self.send("start_review")
        source = self.legacy_run()
        args = SimpleNamespace(ledger=str(source / "REVIEW_LEDGER.json"), shutdown_evidence="Stopped")
        expected = review_ledger.stored_files(source)
        ledger = json.loads((source / "REVIEW_LEDGER.json").read_bytes())
        blob = next(iter(ledger["snapshots"][ledger["initial"]]["files"].values()))["blob"]

        def interrupted_cleanup(path):
            self.assertEqual(path, source)
            (source / "objects" / blob).unlink()
            raise OSError("interrupted after deleting a referenced object")

        with patch("review_ledger.shutil.rmtree", side_effect=interrupted_cleanup):
            with self.assertRaisesRegex(OSError, "referenced object"):
                review_ledger.migrate(args, self.root)
        self.assertEqual(review_ledger.stored_files(Path(self.ledger).parent), expected)
        self.assertRegex(self.cli(["init", "--objective", "Other", "--scope", "all"], ok=False),
                         "Legacy|Existing active run")
        self.cli(["migrate", args.ledger, "--shutdown-evidence", "Stopped"])
        self.assertFalse(source.exists())
        self.assertEqual(review_ledger.stored_files(Path(self.ledger).parent), expected)
        self.assertEqual(self.cli(["status", self.ledger])["revision"], self.state["revision"])
        self.send("stop", outcome="interrupted")
        self.send("resume")

    def test_migration_cleanup_retry_rejects_changed_destination_and_source(self):
        self.init()
        source = self.legacy_run()
        args = SimpleNamespace(ledger=str(source / "REVIEW_LEDGER.json"), shutdown_evidence="Stopped")
        with patch("review_ledger.shutil.rmtree", side_effect=OSError("interrupted cleanup")):
            with self.assertRaises(OSError):
                review_ledger.migrate(args, self.root)
        target = Path(self.ledger).parent
        obj = next((target / "objects").iterdir())
        original = obj.read_bytes()
        obj.write_bytes(b"damaged destination")
        self.cli(["migrate", args.ledger, "--shutdown-evidence", "Stopped"], ok=False)
        self.assertTrue(source.exists())
        self.assertEqual(obj.read_bytes(), b"damaged destination")
        obj.write_bytes(original)
        unexpected = source / "new-evidence"
        unexpected.write_text("retained source change")
        self.cli(["migrate", args.ledger, "--shutdown-evidence", "Stopped"], ok=False)
        self.assertEqual(unexpected.read_text(), "retained source change")
        unexpected.unlink()
        self.cli(["migrate", args.ledger, "--shutdown-evidence", "Stopped"])
        self.assertFalse(source.exists())

    def test_migration_retry_after_source_removal_preserves_newer_history(self):
        self.init()
        source = self.legacy_run()
        args = SimpleNamespace(ledger=str(source / "REVIEW_LEDGER.json"), shutdown_evidence="Stopped")
        sync_directory = review_ledger.sync_directory

        def interrupted_sync(path):
            if path == source.parent and not source.exists():
                raise OSError("interrupted after source removal")
            sync_directory(path)

        with patch("review_ledger.sync_directory", side_effect=interrupted_sync):
            with self.assertRaisesRegex(OSError, "source removal"):
                review_ledger.migrate(args, self.root)
        self.assertFalse(source.exists())
        self.send("start_review")
        newer = Path(self.ledger).read_bytes()
        self.cli(["migrate", args.ledger, "--shutdown-evidence", "Stopped"])
        self.assertEqual(Path(self.ledger).read_bytes(), newer)
        self.assertFalse(list(self.storage.glob(".migration-*.json")))

    def test_migrated_abandonment_retains_unavailable_spending(self):
        self.init()
        Path(self.ledger).write_bytes(b"{damaged history")
        self.cli(["abandon", self.ledger, "--reason", "Corrupt", "--evidence", "Fixture bytes",
                  "--shutdown-evidence", "Stopped"])
        source = self.legacy_run()
        marker = source / "ABANDONED.json"
        closed = json.loads(marker.read_bytes())
        closed["ledger"] = str(source / "REVIEW_LEDGER.json")
        marker.write_bytes(review_ledger.encode(closed))
        original = review_ledger.stored_files(source)

        def interrupted_cleanup(path):
            self.assertEqual(path, source)
            (source / "REVIEW_LEDGER.json").unlink()
            raise OSError("interrupted cleanup of corrupt history")

        args = SimpleNamespace(ledger=closed["ledger"], shutdown_evidence="Stopped")
        with patch("review_ledger.shutil.rmtree", side_effect=interrupted_cleanup):
            with self.assertRaisesRegex(OSError, "corrupt history"):
                review_ledger.migrate(args, self.root)
        self.cli(["migrate", closed["ledger"], "--shutdown-evidence", "Stopped"])
        self.assertEqual(original, review_ledger.stored_files(Path(self.ledger).parent))
        self.assertEqual(self.cli(["inspect", self.ledger])["allowance"], "unavailable")
        self.reject("resume")
        self.init()
        self.send("start_review")

    def test_tracked_review_loop_named_files_are_not_excluded(self):
        path = self.root / ".review-loop/source.txt"
        path.parent.mkdir()
        path.write_text("Project code, not review storage\n")
        self.git("add", "-f", ".review-loop/source.txt")
        result = self.cli(["fingerprint"])
        self.assertIn(".review-loop/source.txt", result["manifest"]["files"])
        self.assertFalse(self.storage.exists())

    def test_verified_fix_then_final_full_review(self):
        """Completion needs both verified correction and a subsequent whole-scope review."""
        self.init()
        self.review()
        self.finding()
        self.decide()
        self.fix()
        self.decide(disposition="fixed")
        self.send("advance")
        self.assertEqual(self.state["phase"], "ready_review")
        self.review()
        self.send("advance")
        self.assertEqual(self.state["outcome"], "completed")
        self.assertEqual(len(self.state["loops"]), 2)
        self.assertEqual(len(self.state["loops"][0]["cycles"]), 1)
        self.assertEqual(self.state["findings"]["F001"]["disposition"], "fixed")

    def test_inner_limit_stops_whole_run(self):
        """Unused outer allowance cannot bypass an exhausted correction sub-loop."""
        self.init("--max-fix-cycles", "1", "--max-loops", "5")
        self.review()
        self.finding()
        self.decide()
        self.fix("failed")
        self.send("advance")
        self.assertEqual(self.state["outcome"], "limit_reached")
        self.assertEqual(len(self.state["loops"]), 1)
        self.reject("start_review")
        self.reject("resume")
        self.assertEqual(self.state["findings"]["F001"]["disposition"], "fix_failed")

    def test_inner_retries_do_not_start_an_outer_review(self):
        """Repeated correction attempts belong to the review that found the issue."""
        self.init()
        self.review()
        self.finding()
        self.decide()
        self.fix("failed")
        self.send("advance")
        self.fix()
        self.decide(disposition="fixed")
        self.send("advance")
        self.assertEqual(len(self.state["loops"]), 1)
        self.assertEqual(len(self.state["loops"][0]["cycles"]), 2)

    def test_outer_limit_cannot_claim_final_confirmation(self):
        """A focused review alone cannot certify the entire scope after the last loop."""
        self.init("--max-loops", "1")
        self.review()
        self.finding()
        self.decide()
        self.fix()
        self.decide(disposition="fixed")
        self.send("advance")
        self.assertEqual(self.state["outcome"], "limit_reached")
        self.assertIn("Final full-scope", self.state["stop_reason"])

    def test_no_fixes_and_accepted_uncertainty(self):
        """Accepting uncertainty leaves a reported exception, not a clean result."""
        self.init()
        self.review()
        self.finding()
        self.reject("advance")
        self.decide(disposition="ignored", validation="uncertain")
        self.send("advance")
        self.assertEqual(self.state["outcome"], "completed_with_exceptions")
        self.assertEqual(self.state["loops"][0]["cycles"], [])

    def test_duplicate_suppression_and_reopening(self):
        """Repeated observations preserve suppression until an explicit new decision."""
        self.init()
        self.review()
        self.finding()
        self.decide(disposition="ignored")
        self.finding()
        self.assertEqual(len(self.state["findings"]), 1)
        self.assertEqual(len(self.state["findings"]["F001"]["observations"]), 2)
        self.assertEqual(self.state["findings"]["F001"]["disposition"], "ignored")
        self.decide()
        self.assertEqual(self.state["findings"]["F001"]["disposition"], "open")
        self.reject("advance")

    def test_failed_review_and_unverified_fix_are_not_clean(self):
        """Worker failure or failed checks must not become successful review evidence."""
        self.init()
        self.send("start_review")
        self.reject("review_done", passes=[{**PASSES[0], "result": "failed"}], checks=CHECKS)
        self.send("review_done", passes=PASSES, checks=CHECKS)
        self.finding()
        self.decide()
        self.reject("decision", id="F001", validation="valid", disposition="fixed",
                    severity="High", evidence=["No actual edit"])
        self.send("start_fix", findings=["F001"], files=["app.txt"])
        (self.root / "app.txt").write_text("attempted correction\n")
        self.send("fix_done", results={"F001": {"result": "applied", "evidence": "Attempt"}},
                  checks=[{**CHECKS[0], "result": "failed"}])
        self.send("fixes_reviewed", passes=PASSES)
        self.reject("decision", id="F001", validation="valid", disposition="fixed",
                    severity="High", evidence=["Checks did not pass"])
        self.reject("advance")

    def test_new_regression_validated_within_inner_cycle(self):
        """A correction regression must be adjudicated before another fix begins."""
        self.init()
        self.review()
        self.finding()
        self.decide()
        self.fix()
        self.decide(disposition="fixed")
        self.finding("regression")
        self.reject("advance")
        self.decide("F002")
        self.send("advance")
        self.send("start_fix", findings=["F002"], files=["app.txt"])
        self.assertEqual(len(self.state["loops"]), 1)
        self.assertEqual(len(self.state["loops"][0]["cycles"]), 2)

    def test_resume_and_external_drift(self):
        """Resumption keeps allowance use; changed evidence requires a counted review."""
        self.init()
        self.send("start_review")
        self.send("stop", outcome="interrupted")
        self.send("resume")
        self.assertEqual(len(self.state["loops"]), 1)
        (self.root / "app.txt").write_text("external change\n")
        self.assertTrue(self.cli(["status", self.ledger])["drift"])
        self.reject("review_done", passes=PASSES, checks=CHECKS)
        self.send("reconcile", evidence=["External change invalidates review"])
        self.review()
        self.assertEqual(len(self.state["loops"]), 2)

    def test_interrupted_fix_resumes_without_refunding_cycle(self):
        """Declared partial edits remain recoverable without granting a free fix attempt."""
        self.init()
        self.review()
        self.finding()
        self.decide()
        self.send("start_fix", findings=["F001"], files=["app.txt"])
        (self.root / "app.txt").write_text("partly fixed\n")
        self.send("stop", outcome="interrupted")
        self.send("resume")
        self.assertEqual(self.state["phase"], "fixing")
        self.assertEqual(len(self.state["loops"][0]["cycles"]), 1)
        self.send("fix_done", results={"F001": {"result": "applied", "evidence": "Recovered edit"}},
                  checks=CHECKS)

    def test_stopped_fix_can_be_abandoned_without_reverting_drift(self):
        for stopped, terminal in (("interrupted", "failed"), ("blocked", "stalled")):
            with self.subTest(stopped=stopped, terminal=terminal):
                self.init()
                self.review()
                self.finding()
                self.decide()
                self.send("start_fix", findings=["F001"], files=["app.txt"])
                (self.root / "app.txt").write_text(f"partial {stopped}\n")
                self.send("stop", outcome=stopped)
                before = self.state
                history = json.loads(Path(self.ledger).read_text())["events"]
                (self.root / "outside.txt").write_text(f"external {stopped}\n")
                self.git("add", "outside.txt")
                index = self.git("ls-files", "--stage", "-z")
                self.reject("resume")
                self.reject("reconcile", evidence=["Unexpected edits"])
                self.reject("stop", outcome="completed")
                self.reject("stop", outcome="interrupted")
                self.send("stop", outcome=terminal)
                self.assertEqual(self.state["outcome"], terminal)
                for key in ("snapshot", "phase", "loops", "findings", "limits"):
                    self.assertEqual(self.state[key], before[key])
                report = self.cli(["status", self.ledger])
                self.assertTrue(report["drift"])
                self.assertEqual(report["history"][:-1], history)
                self.assertEqual(report["revision"], before["revision"] + 1)
                self.assertEqual((self.root / "app.txt").read_text(), f"partial {stopped}\n")
                self.assertEqual((self.root / "outside.txt").read_text(), f"external {stopped}\n")
                self.assertEqual(self.git("ls-files", "--stage", "-z"), index)
                self.reject("resume")
                self.reject("reconcile", evidence=["Finished run"])
                self.reject("stop", outcome="failed")
        self.init()

    def test_stop_cannot_launder_stale_review(self):
        """Stopping after external edits must not relabel an old review as current."""
        self.init()
        self.send("start_review")
        (self.root / "app.txt").write_text("changed\n")
        self.send("stop", outcome="interrupted")
        self.reject("resume")
        self.send("reconcile", evidence=["Restart against external changes"])
        self.assertEqual(self.state["phase"], "ready_review")
        self.review()
        self.assertEqual(len(self.state["loops"]), 2)

    def test_run_isolation_and_active_writer_exclusion(self):
        """Runs share neither findings nor active write authority, even in one worktree."""
        self.init()
        first = self.ledger
        self.cli(["init", "--objective", "Other review", "--scope", "repository"], ok=False)
        self.review()
        self.send("advance")
        self.init()
        self.assertNotEqual(first, self.ledger)
        self.assertEqual(self.state["findings"], {})
        self.assertEqual(self.cli(["status", first])["outcome"], "completed")

    def test_revision_and_reason_are_required(self):
        """Stale writers and unexplained decisions cannot update durable history."""
        self.init()
        self.send("start_review")
        self.cli(["apply", self.ledger, "--revision", "0"], self.event("stop", outcome="failed"),
                 ok=False)
        self.reject("stop", outcome="failed", reason="")
        self.reject("stop", outcome="completed")

    def test_snapshots_capture_dirty_untracked_deleted_and_symlink(self):
        """Coverage follows Git enumeration without reading ignored or symlink targets."""
        (self.root / "new file.txt").write_text("untracked\n")
        (self.root / "ignored.txt").write_text("excluded\n")
        (self.root / "link").symlink_to("missing-target")
        (self.root / "app.txt").unlink()
        self.init()
        data = json.loads(Path(self.ledger).read_text())
        files = data["snapshots"][data["initial"]]["files"]
        self.assertIn("new file.txt", files)
        self.assertNotIn("ignored.txt", files)
        self.assertNotIn("app.txt", files)
        self.assertEqual(files["link"]["mode"], "120000")
        self.assertFalse(any(name.startswith(".review-loop/") for name in files))

    def test_discovered_fix_files_are_captured_but_index_changes_are_rejected(self):
        """Necessary discovered files enter the actual delta without authorizing staging."""
        self.init()
        self.review()
        self.finding()
        self.decide()
        self.send("start_fix", findings=["F001"], files=[])
        (self.root / "other.txt").write_text("unplanned\n")
        results = {"F001": {"result": "applied", "evidence": "Attempt"}}
        self.git("add", "app.txt")
        (self.root / "app.txt").write_text("staged change\n")
        self.git("add", "app.txt")
        self.reject("fix_done", results=results, checks=CHECKS)
        self.git("restore", "--staged", "app.txt")
        self.send("fix_done", results=results, checks=CHECKS)
        data = json.loads(Path(self.ledger).read_bytes())
        before = data["initial"]
        delta = self.cli(["diff", self.ledger, "--from", before])
        self.assertEqual({item["file"] for item in delta}, {"app.txt", "other.txt"})

    def test_snapshot_diff_and_corrupt_object(self):
        """Saved deltas must remain inspectable, and damaged evidence must fail loudly."""
        self.init()
        before = self.state["snapshot"]
        self.review()
        self.finding()
        self.decide()
        self.fix()
        differences = self.cli(["diff", self.ledger, "--from", before])
        self.assertEqual(differences[0]["file"], "app.txt")
        self.assertIn("-before", differences[0]["diff"])
        objects = Path(self.ledger).parent / "objects"
        next(objects.iterdir()).write_bytes(b"corrupt")
        self.cli(["status", self.ledger], ok=False)

    def test_atomic_failure_preserves_previous_ledger(self):
        """A failed replacement must leave the last durable record and no pending file."""
        path = self.root / "record.json"
        path.write_bytes(b"old")
        with patch("review_ledger.os.replace", side_effect=OSError("fixture failure")):
            with self.assertRaises(OSError):
                review_ledger.atomic_write(path, b"new")
        self.assertEqual(path.read_bytes(), b"old")
        self.assertFalse(list(self.root.glob(".pending-*")))

    def test_invalid_limits_and_storage_symlinks(self):
        """Invalid initialization must not enable unbounded work or redirected storage."""
        self.cli(["init", "--objective", "Fixture", "--scope", "repository",
                  "--max-loops", "0"], ok=False)
        self.storage.rename(self.folder / "storage")
        self.storage.symlink_to(self.folder / "storage")
        self.cli(["init", "--objective", "Fixture", "--scope", "repository"], ok=False)

    def test_applied_fix_requires_actual_edits(self):
        """An agent's applied verdict is insufficient when the snapshot has no delta."""
        self.init()
        self.review()
        self.finding()
        self.decide()
        self.send("start_fix", findings=["F001"], files=["app.txt"])
        self.reject("fix_done", results={"F001": {"result": "applied", "evidence": "No change"}},
                    checks=CHECKS)

    def test_malformed_event_and_ledger_are_explicit_failures(self):
        """Bad input or damaged history must surface as errors, not empty clean runs."""
        self.init()
        self.cli(["apply", self.ledger, "--revision", "0"], ["not an event"], ok=False)
        self.reject("start_review", unexpected=True)
        path = Path(self.ledger)
        path.write_text("{broken")
        self.cli(["status", self.ledger], ok=False)

    def test_symlink_fix_declaration_and_parent_are_rejected(self):
        """Declared targets cannot escape through symlinks or parent traversal."""
        (self.root / "link").symlink_to("app.txt")
        self.init()
        self.review()
        self.finding()
        self.decide()
        self.reject("start_fix", findings=["F001"], files=["link"])
        self.reject("start_fix", findings=["F001"], files=["../outside"])

    def test_unsupported_file_initialization_does_not_leave_a_run(self):
        """Failed capture must not leave a resumable run.

        Replace a tracked file because Git may omit untracked special files.
        """
        (self.root / "app.txt").unlink()
        os.mkfifo(self.root / "app.txt")
        self.cli(["init", "--objective", "Fixture", "--scope", "repository"], ok=False)
        self.assertEqual(list(self.storage.iterdir()), [self.storage / ".lock"])

    def interrupt_init(self, boundary):
        script = """
import os
import sys
import review_ledger

boundary = sys.argv[1]
write = review_ledger.atomic_write
def interrupted_write(path, data):
    write(path, data)
    if (boundary == "object" and path.parent.name == "objects" or
            boundary == "ledger" and path.name == "REVIEW_LEDGER.json"):
        os._exit(75)

rename = review_ledger.os.rename
def interrupted_rename(source, destination):
    rename(source, destination)
    if boundary == "published":
        os._exit(75)

review_ledger.atomic_write = interrupted_write
review_ledger.os.rename = interrupted_rename
sys.argv = ["review_ledger.py", "init", "--objective", "Interrupted fixture",
            "--scope", "repository"]
sys.exit(review_ledger.main())
"""
        result = subprocess.run(
            [sys.executable, "-c", script, boundary], cwd=self.root,
            env={**self.env, "PYTHONPATH": str(HELPER.parent)}, capture_output=True,
        )
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertEqual(result.stdout, b"")

    def test_interrupted_initial_snapshot_allows_retry(self):
        self.interrupt_init("object")
        self.assertTrue(list(self.storage.glob("*/objects/*")))
        self.init()
        self.review()
        self.send("advance")
        self.assertEqual(self.state["outcome"], "completed")
        self.assertEqual((self.root / "app.txt").read_text(), "before\n")

    def test_interrupted_unpublished_ledger_allows_retry(self):
        self.interrupt_init("ledger")
        self.init()
        self.cli(["init", "--objective", "Another run", "--scope", "repository"], ok=False)
        self.send("start_review")
        self.send("stop", outcome="interrupted")
        self.send("resume")
        self.assertEqual(len(self.state["loops"]), 1)

    def test_interruption_after_publication_preserves_the_run(self):
        self.interrupt_init("published")
        ledgers = list(self.storage.glob("*/REVIEW_LEDGER.json"))
        self.assertEqual(len(ledgers), 1)
        self.ledger = str(ledgers[0])
        self.state = self.cli(["status", self.ledger])
        self.assertIn("Existing active run", self.cli(
            ["init", "--objective", "Another run", "--scope", "repository"], ok=False))
        self.review()
        self.send("advance")
        self.assertEqual(self.state["outcome"], "completed")

    def test_missing_published_ledger_is_not_an_unpublished_initialization(self):
        self.init()
        path = Path(self.ledger)
        path.unlink()
        self.cli(["init", "--objective", "Another run", "--scope", "repository"], ok=False)
        self.assertTrue(path.parent.is_dir())

    def test_unrecoverable_history_can_be_closed_without_rewriting_evidence(self):
        for damage in ("missing-ledger", "truncated-ledger", "missing-object", "corrupt-object",
                       "file-map", "snapshot-map"):
            with self.subTest(damage=damage):
                self.init("--max-loops", "2")
                self.send("start_review")
                if damage == "file-map":
                    self.send("review_done", passes=PASSES, checks=CHECKS)
                    self.finding()
                    self.decide()
                    self.fix()
                path = Path(self.ledger)
                arguments = ["abandon", self.ledger, "--reason", "History is unrecoverable",
                             "--evidence", "Inspected surviving objects; no complete history exists",
                             "--shutdown-evidence", "All fixture workers have exited"]
                self.assertIn("use stop", self.cli(arguments, ok=False))
                missing = None
                if damage == "missing-ledger":
                    path.unlink()
                    missing = path
                elif damage == "truncated-ledger":
                    path.write_bytes(b'{"incomplete":')
                elif damage in ("missing-object", "corrupt-object"):
                    obj = next((path.parent / "objects").iterdir())
                    if damage == "missing-object":
                        obj.unlink()
                        missing = obj
                    else:
                        obj.write_bytes(b"corrupt")
                else:
                    ledger = json.loads(path.read_bytes())
                    if damage == "file-map":
                        before = ledger["initial"]
                        item = ledger["snapshots"].pop(before)
                        item["files"] = None
                        key = review_ledger.digest(review_ledger.encode(item))
                        ledger["snapshots"][key] = item
                        ledger["initial"] = key
                        for event in ledger["events"]:
                            if event["snapshot"] == before:
                                event["snapshot"] = key
                    else:
                        ledger["snapshots"] = []
                    path.write_bytes(review_ledger.encode(ledger))
                evidence = {item: item.read_bytes() for item in path.parent.rglob("*") if item.is_file()}
                project = (self.root / "app.txt").read_bytes()
                self.assertIn("abandon", self.cli(
                    ["init", "--objective", "Another run", "--scope", "repository"], ok=False))
                closed = self.cli(arguments)
                self.assertEqual(closed["outcome"], "failed")
                self.assertEqual(closed["allowance"], "unavailable")
                if damage == "file-map":
                    self.assertIn("Invalid snapshot file map", closed["error"])
                self.assertEqual(closed, self.cli(["status", self.ledger]))
                self.assertEqual(closed, self.cli(arguments))
                for item, content in evidence.items():
                    self.assertEqual(item.read_bytes(), content)
                if missing is not None:
                    self.assertFalse(missing.exists())
                for event in ("resume", "start_review"):
                    self.assertIn("abandoned", self.reject(event))
                self.assertEqual((self.root / "app.txt").read_bytes(), project)
        self.init()
        self.review()
        self.send("advance")
        self.assertEqual(self.state["outcome"], "completed")

    def test_symlinked_ledger_can_be_closed_without_following_its_target(self):
        for missing in (True, False):
            with self.subTest(missing=missing):
                self.init()
                path = Path(self.ledger)
                original = path.read_bytes()
                target = self.root / ("missing-history" if missing else "external-history")
                if not missing:
                    target.write_bytes(original)
                path.unlink()
                path.symlink_to(target)
                args = [self.ledger, "--reason", "Ledger entry is an unusable symlink",
                        "--evidence", "Inspected the entry without following its target",
                        "--shutdown-evidence", "All fixture workers have exited"]
                self.assertIn("abandon", self.cli(
                    ["init", "--objective", "Another run", "--scope", "repository"], ok=False))
                self.cli(["status", self.ledger], ok=False)
                self.cli(["recover-closure", *args], ok=False)
                closed = self.cli(["abandon", *args])
                self.assertEqual((closed["outcome"], closed["allowance"]), ("failed", "unavailable"))
                self.assertIn("Symlink", closed["error"])
                self.assertEqual(self.cli(["status", self.ledger]), closed)
                self.assertEqual(self.cli(["abandon", *args]), closed)
                self.reject("resume")
                self.reject("start_review")
                self.assertTrue(path.is_symlink())
                self.assertEqual(path.readlink(), target)
                if missing:
                    self.assertFalse(target.exists())
                else:
                    self.assertEqual(target.read_bytes(), original)
        self.init()
        self.review()
        self.send("advance")
        self.assertEqual(self.state["outcome"], "completed")

    def test_readable_history_survives_damaged_closure_recovery(self):
        self.init("--max-loops", "2")
        self.review()
        self.finding()
        self.decide()
        self.fix()
        path = Path(self.ledger)
        original = json.loads(path.read_bytes())
        prior = self.state
        objects = {item: item.read_bytes() for item in (path.parent / "objects").iterdir()}
        project = (self.root / "app.txt").read_bytes()
        marker = path.parent / "ABANDONED.json"
        marker.write_bytes(b"damaged closure")
        args = ["recover-closure", self.ledger, "--reason", "Cannot restore the closure record",
                "--evidence", "Validated surviving history and inspected the damaged marker",
                "--shutdown-evidence", "All fixture workers have exited"]
        self.assertIn("recover-closure", self.cli(["abandon", *args[1:]], ok=False))
        self.assertEqual(json.loads(path.read_bytes()), original)
        self.assertIn("recover-closure", self.cli(["status", self.ledger], ok=False))
        self.reject("resume")
        self.cli([*args[:-1], ""], ok=False)
        self.assertEqual(marker.read_bytes(), b"damaged closure")
        self.state = self.cli(args)
        self.assertEqual(self.state["outcome"], "failed")
        for key in ("loops", "findings", "limits", "snapshot"):
            self.assertEqual(self.state[key], prior[key])
        saved = json.loads(path.read_bytes())
        self.assertEqual(saved["events"][:-1], original["events"])
        self.assertEqual(saved["snapshots"], original["snapshots"])
        self.assertEqual(saved["events"][-1]["type"], "stop")
        self.assertIn("All fixture workers have exited", saved["events"][-1]["reason"])
        self.assertFalse(marker.exists())
        archives = list(path.parent.glob("ABANDONED-*.json"))
        self.assertEqual([item.read_bytes() for item in archives], [b"damaged closure"])
        self.assertEqual(self.cli(args), self.state)
        self.assertEqual(json.loads(path.read_bytes()), saved)
        self.reject("resume")
        self.reject("start_review")
        for item, content in objects.items():
            self.assertEqual(item.read_bytes(), content)
        self.assertEqual((self.root / "app.txt").read_bytes(), project)
        self.init()
        self.review()
        self.send("advance")
        self.assertEqual(self.state["outcome"], "completed")

    def test_closure_recovery_cannot_reopen_terminal_history_after_interruption(self):
        self.init()
        self.review()
        self.send("advance")
        path = Path(self.ledger)
        original = path.read_bytes()
        path.unlink()
        flags = [self.ledger, "--reason", "Closure recovery fixture",
                 "--evidence", "Inspected persisted fixture evidence",
                 "--shutdown-evidence", "No native workers are running"]
        self.cli(["abandon", *flags])
        path.write_bytes(original)
        self.cli(["recover-closure", *flags], ok=False)
        self.assertEqual(path.read_bytes(), original)
        marker = path.parent / "ABANDONED.json"
        marker.write_bytes(b"damaged terminal closure")
        args = review_ledger.parser().parse_args(["recover-closure", *flags])
        with patch.object(review_ledger.os, "rename", side_effect=OSError("fixture archive failure")):
            with self.assertRaisesRegex(OSError, "fixture archive failure"):
                review_ledger.recover_closure(args, self.root)
        self.assertEqual(marker.read_bytes(), b"damaged terminal closure")
        self.assertEqual(json.loads(path.read_bytes())["events"][-1]["outcome"], "failed")
        self.cli(["status", self.ledger], ok=False)
        self.reject("resume")
        self.state = self.cli(["recover-closure", *flags])
        self.assertEqual(self.state["outcome"], "failed")
        self.reject("resume")
        self.assertEqual(self.cli(["status", self.ledger])["outcome"], "failed")

    def test_abandonment_requires_evidence_and_cannot_be_transplanted(self):
        self.init()
        path = Path(self.ledger)
        path.unlink()
        args = ["abandon", self.ledger, "--reason", "Unrecoverable history",
                "--evidence", "No surviving ledger copy", "--shutdown-evidence", ""]
        self.cli(args, ok=False)
        self.assertFalse((path.parent / "ABANDONED.json").exists())
        args[-1] = "Offline fixture has no running worker"
        self.cli(args)
        marker = path.parent / "ABANDONED.json"
        marker.write_bytes(b"corrupt closure")
        self.cli(["status", self.ledger], ok=False)
        self.cli(["recover-closure", *args[1:]], ok=False)
        recovered = self.cli(args)
        self.assertEqual((path.parent / recovered["previous_record"]).read_bytes(), b"corrupt closure")
        self.assertEqual(self.cli(["status", self.ledger])["outcome"], "failed")
        other = path.parent.parent / ("a" * 32)
        other.mkdir()
        (other / "ABANDONED.json").write_bytes((path.parent / "ABANDONED.json").read_bytes())
        self.assertIn("different run", self.cli(
            ["init", "--objective", "Another run", "--scope", "repository"], ok=False))

    def test_lock_blocks_concurrent_updates(self):
        """An overlapping writer must fail explicitly rather than race a ledger update."""
        self.init()
        with (self.storage / ".lock").open("a") as handle:
            review_ledger.fcntl.flock(handle, review_ledger.fcntl.LOCK_EX)
            self.reject("start_review")
        self.send("start_review")

    def test_unpopulated_submodule_is_explicitly_unsupported(self):
        """Index gitlinks must fail even when no submodule directory can be inspected."""
        with patch("review_ledger.git", return_value=b"160000 abc 0\tvendor\0"):
            with self.assertRaisesRegex(review_ledger.LedgerError, "Submodules"):
                review_ledger.snapshot(self.root)

    def test_replay_rejects_mismatched_evidence_snapshot(self):
        """Loading history must enforce snapshot rules, not merely validate event shapes."""
        self.init()
        self.review()
        self.finding()
        self.decide()
        self.fix()
        path = Path(self.ledger)
        data = json.loads(path.read_text())
        data["events"][0]["snapshot"] = self.state["snapshot"]
        path.write_text(json.dumps(data))
        self.cli(["status", self.ledger], ok=False)

    def test_executable_regression_and_persistent_final_report(self):
        """A durable success report must survive a real failing-then-passing correction."""
        app = self.root / "boundary.py"
        app.write_text("def allowed(value):\n    return value > 0\n")
        self.init()
        self.review()
        command = [sys.executable, "-c",
                   "from boundary import allowed; assert allowed(0); assert not allowed(-1)"]
        failed = subprocess.run(command, cwd=self.root, env=self.env, capture_output=True)
        self.assertNotEqual(failed.returncode, 0)
        self.finding("zero-boundary")
        self.decide()
        self.send("start_fix", findings=["F001"], files=["boundary.py"])
        app.write_text("def allowed(value):\n    return value >= 0\n")
        passed = subprocess.run(command, cwd=self.root, env=self.env, capture_output=True)
        self.assertEqual(passed.returncode, 0, passed.stderr)
        self.send("fix_done", results={"F001": {"result": "applied", "evidence": "Zero accepted"}},
                  checks=[{"name": "zero and negative boundaries", "result": "passed",
                           "evidence": "Python assertion process exited 0; failed before correction"}])
        self.send("fixes_reviewed", passes=PASSES)
        self.decide(disposition="fixed")
        self.send("advance")
        self.review()
        self.send("advance")
        report = self.cli(["status", self.ledger])
        self.assertEqual(report["outcome"], "completed")
        self.assertEqual(report["findings"]["F001"]["disposition"], "fixed")
        self.assertEqual(report["usage"], "not_collected")


class ReviewInstructionTests(unittest.TestCase):
    def test_shared_references_are_packaged(self):
        root = HELPER.parent.parent
        documents = [
            document
            for skill in ("review-code", "review-validate-fix-loop", "review-triage-loop",
                          "verify-unresolved-pr-comments")
            for document in (root / "skills" / skill).glob("*.md")
        ]
        for document in documents:
            for link in re.findall(r"\[[^\]]+\]\(([^)]+)\)", document.read_text()):
                if link.startswith(("https://", "http://", "#")):
                    continue
                target = (document.parent / link.split("#", 1)[0]).resolve()
                self.assertIn(root, target.parents, f"{document}: escaping reference {link}")
                self.assertTrue(target.is_file(), f"{document}: missing reference {link}")


if __name__ == "__main__":
    unittest.main()
