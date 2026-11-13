#!/usr/bin/env python3
"""Exercise the ledger CLI against isolated Git repositories, without host agents."""

import json
from itertools import product
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import review_ledger


HELPER = Path(__file__).with_name("review_ledger.py")
PASSES = [{"name": "correctness", "worker": "independent-reviewer",
           "result": "complete", "evidence": "Traced fixture callers and requirements"}]
CHECKS = [{"name": "fixture check", "result": "passed", "evidence": "Fixture assertion passed"}]


def coordinated_pass(snapshot, mode, strategy="specialists"):
    return {**PASSES[0], "worker": f"{mode}-specialist",
            "evidence": json.dumps({
                "assignment": "correctness", "snapshot": snapshot, "mode": mode,
                "strategy": strategy, "result_file": "/private/review-fixture/correctness.json",
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
        self.root = Path(self.temp.name).resolve()
        self.cwd = self.root
        self.env = {**os.environ, "HOME": str(self.root), "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_CONFIG_GLOBAL": os.devnull, "PYTHONDONTWRITEBYTECODE": "1"}
        for key in list(self.env):
            if key.startswith(("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")):
                self.env.pop(key)
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
            full_pass = coordinated_pass(self.state["snapshot"], mode, strategy)
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
            self.send("review_done", passes=[full_pass], checks=CHECKS)
            self.send("decision", id="F001", validation="valid", disposition="open", severity="High",
                      evidence=["validator=review-adjudicator; traced specialist evidence"])
            self.send("decision", id="F002", validation="invalid", disposition="ignored",
                      severity="High", evidence=["validator=outer-loop; checked integration claim"])
            self.send("decision", id="F003", validation="valid", disposition="ignored",
                      severity="Low", reason="Accurate documentation differs only in presentation",
                      evidence=[json.dumps(style_assessment)])
            self.send("start_fix", findings=["F001"], files=["app.txt"])
            (self.root / "app.txt").write_text(f"corrected {mode} {strategy}\n")
            self.send("fix_done", results={"F001": {"result": "applied", "evidence": "Correction"}},
                      checks=CHECKS)
            focused_pass = coordinated_pass(self.state["snapshot"], mode, strategy)
            self.send("fixes_reviewed", passes=[focused_pass])
            self.decide(disposition="fixed")
            self.send("advance")
            self.review()
            self.send("advance")
            report = self.cli(["status", self.ledger])
            self.assertEqual(report["outcome"], "completed_with_exceptions")
            self.assertEqual(len(report["loops"]), 2)
            self.assertEqual(len(report["loops"][0]["cycles"]), 1)
            self.assertEqual(report["loops"][0]["review"]["passes"], [full_pass])
            self.assertEqual(report["loops"][0]["cycles"][0]["review"]["passes"], [focused_pass])
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
            self.assertIn("validator=outer-loop",
                          report["findings"]["F002"]["decisions"][0]["evidence"][0])
            self.assertEqual(json.loads(Path(self.ledger).read_text())["schema"], 1)

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
            for ledger in (self.ledger, str(Path(self.ledger).relative_to(self.root))):
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

    def test_ledger_paths_reject_outside_worktree(self):
        """Root-relative lookup must not admit traversal or another worktree."""
        nested = self.root / "source"
        nested.mkdir()
        self.init()
        relative = Path(self.ledger).relative_to(self.root)
        self.cwd = nested
        for ledger in (str(Path("..") / relative),
                       str(self.root.parent / relative), str(nested / relative)):
            with self.subTest(ledger=ledger):
                error = self.cli(["status", ledger], ok=False)
                self.assertIn("Ledger must be", error)

    def test_ledger_paths_reject_symlink_run(self):
        """A valid-looking storage path cannot alias a run through a symlink."""
        self.init()
        alias = self.root / ".review-loop" / "alias"
        alias.symlink_to(Path(self.ledger).parent)
        for ledger in (alias / "REVIEW_LEDGER.json",
                       alias.relative_to(self.root) / "REVIEW_LEDGER.json"):
            with self.subTest(ledger=ledger):
                error = self.cli(["status", str(ledger)], ok=False)
                self.assertIn("Symlink not allowed", error)

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
                if stopped == "blocked":
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

    def test_unplanned_edits_and_index_changes_rejected(self):
        """A declared correction cannot legitimize unrelated files or staging changes."""
        self.init()
        self.review()
        self.finding()
        self.decide()
        self.send("start_fix", findings=["F001"], files=["app.txt"])
        (self.root / "other.txt").write_text("unplanned\n")
        results = {"F001": {"result": "applied", "evidence": "Attempt"}}
        self.reject("fix_done", results=results, checks=CHECKS)
        (self.root / "other.txt").unlink()
        self.git("add", "app.txt")
        (self.root / "app.txt").write_text("staged change\n")
        self.git("add", "app.txt")
        self.reject("fix_done", results=results, checks=CHECKS)

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
        (self.root / ".review-loop").rename(self.root / "storage")
        (self.root / ".review-loop").symlink_to("storage")
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
        self.assertEqual(list((self.root / ".review-loop").iterdir()),
                         [self.root / ".review-loop" / ".lock"])

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
        self.assertTrue(list((self.root / ".review-loop").glob("*/objects/*")))
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
        ledgers = list((self.root / ".review-loop").glob("*/REVIEW_LEDGER.json"))
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

    def test_lock_blocks_concurrent_updates(self):
        """An overlapping writer must fail explicitly rather than race a ledger update."""
        self.init()
        with (self.root / ".review-loop" / ".lock").open("a") as handle:
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
