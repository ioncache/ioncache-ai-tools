#!/usr/bin/env python3
"""Exercise development contracts and persisted execution without model or network calls."""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import development_manifest as manifest
import development_run as development


SCRIPTS = Path(__file__).resolve().parent
CHECK = {"name": "fixture", "command": "python3 -c 'assert True'",
         "cwd": ".", "expected": "Exit zero"}


class DevelopmentRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name).resolve()
        self.root = self.folder / "repository"
        self.root.mkdir()
        self.bundle = self.folder / "bundle"
        self.bundle.mkdir()
        self.store = self.folder / "run"
        self.env = {**os.environ, "HOME": str(self.folder / "home"),
                    "CODEX_HOME": str(self.folder / "home/.codex"),
                    "COPILOT_HOME": str(self.folder / "home/.copilot"),
                    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                    "PYTHONDONTWRITEBYTECODE": "1"}
        for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
            self.env.pop(key, None)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Development fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("remote", "add", "origin", "https://example.invalid/project.git")
        (self.root / "app.txt").write_text("before\n")
        (self.root / ".gitignore").write_text(".review-loop/\n.worktrees/\n")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        artifacts = []
        for role in ("requirements", "design", "plan"):
            content = f"Approved {role} fixture\n".encode()
            (self.bundle / (role + ".md")).write_bytes(content)
            artifacts.append({"id": role, "role": role, "source": f"https://example.invalid/{role}",
                              "snapshot": role + ".md", "sha256": manifest.digest(content)})
        self.plan = {
            "schema": 1, "objective": "Implement the approved fixture",
            "configuration": {"planning": {"provider": "github", "location": "issue"},
                              "design": {"provider": "notion", "location": "page"},
                              "execution": {"provider": "claude-workflows", "environment": "local"}},
            "repository": {"remote": "origin", "url": "https://example.invalid/project.git",
                           "default_branch": "main"},
            "artifacts": artifacts, "constraints": ["Preserve unrelated user changes"],
            "limits": {"assignments": 30, "attempts": 2, "review_loops": 2,
                       "fix_cycles": 2, "review_dispatches": 20},
            "permissions": {"commit": True, "push": True, "create_pr": True,
                            "mark_ready": True, "screenshots": False},
            "prs": [{"id": "first", "goal": "Fixture increment", "branch": "fixture-feature",
                     "worktree": ".worktrees/fixture-feature", "base": self.git("rev-parse", "HEAD"),
                     "target": "main", "dependencies": [], "checks": [CHECK],
                     "rollout": "Compatible without a flag"}],
            "tasks": [{"id": "change", "pr": "first", "goal": "Change fixture behavior",
                       "paths": ["app.txt"], "dependencies": [], "artifacts": ["requirements", "design", "plan"],
                       "checks": [CHECK], "compatibility": "Preserve fixture format",
                       "completion": "The fixture has the approved content"}],
        }
        self.path = self.bundle / "manifest.json"
        self.state = None

    def git(self, *args, root=None):
        return subprocess.run(["git", *args], cwd=root or self.root, env=self.env,
                              check=True, capture_output=True, text=True).stdout.strip()

    def cli(self, *args, ok=True):
        result = subprocess.run([sys.executable, str(SCRIPTS / "development_run.py"), *map(str, args)],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0 if ok else 2, result.stdout + result.stderr)
        if not ok:
            self.assertEqual(result.stdout, "")
            return result.stderr
        return json.loads(result.stdout)

    def init(self):
        self.path.write_bytes(manifest.encode(self.plan))
        identity = self.cli("validate", self.path)["identity"]
        self.state = self.cli("init", self.path, "--approved", identity,
                              "--root", self.root, "--store", self.store)

    def mutate(self, command, *args, ok=True):
        result = self.cli(command, self.store, "--revision", self.state["revision"], *args, ok=ok)
        if ok:
            self.state = result
        return result

    def next(self):
        self.mutate("next")
        return self.state["assignment"]

    def report(self, data=None, outcome="complete"):
        assignment = self.state["assignment"]
        result = {"assignment": assignment["id"], "worker": "fixture-" + assignment["id"],
                  "outcome": outcome, "summary": "Offline fixture result",
                  "evidence": ["Executed isolated fixture operations"],
                  "artifacts": {item["id"]: item["sha256"] for item in self.plan["artifacts"]},
                  "data": data or {}}
        path = Path(assignment["result_file"])
        path.write_bytes(manifest.encode(result))
        return path

    def finish(self, data=None, outcome="complete", ok=True):
        return self.mutate("record", "--report", self.report(data, outcome), ok=ok)

    def preflight(self):
        self.assertEqual(self.next()["role"], "preflight")
        self.finish({name: True for name in ("artifact_access", "native_permissions", "fresh_workers",
                                             "independent_review", "result_delivery", "cancellation")})

    def prepare(self):
        assignment = self.next()
        self.assertEqual(assignment["role"], "prepare")
        pr = assignment["pr_plan"]
        subprocess.run([sys.executable, str(SCRIPTS / "create-worktree.py"), "-b",
                        pr["branch"], assignment["root"], pr["base"]], cwd=self.root,
                       env=self.env, check=True, capture_output=True)
        self.finish({"base": pr["base"], "merged_dependencies": pr["dependencies"]})
        return Path(assignment["root"])

    def review(self, root):
        assignment = self.state["assignment"]
        base = assignment["comparison_base"]
        args = ["init", "--objective", "Fixture review", "--scope", "fixture", "--base", base,
                "--max-loops", str(self.plan["limits"]["review_loops"]),
                "--max-fix-cycles", str(self.plan["limits"]["fix_cycles"])]
        result = self.review_cli(root, args)
        ledger = result["ledger"]
        events = [
            {"type": "start_review"},
            {"type": "review_done", "passes": [{"name": "fixture", "worker": "fixture-reviewer",
              "result": "complete", "evidence": "Read fixture and caller requirements"}],
             "checks": [{"name": "fixture", "result": "passed", "evidence": "Fixture command exited zero"}]},
            {"type": "advance"},
        ]
        subprocess.run([sys.executable, "-c", "assert True"], env=self.env, cwd=root, check=True)
        for event in events:
            event.update(actor="fixture-owner", reason="Offline regression evidence")
            result = self.review_cli(root, ["apply", ledger, "--revision", str(result["revision"])], event)
        self.finish({"ledger": ledger})

    def review_cli(self, root, args, event=None):
        result = subprocess.run([sys.executable, str(SCRIPTS / "review_ledger.py"), *args],
                                input=json.dumps(event), env=self.env, cwd=root,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def execute_fixture(self, assignment):
        root = Path(assignment["root"])
        role = assignment["role"]
        if role == "implement":
            (root / "app.txt").write_text("after\n")
            self.finish()
        elif role == "review":
            self.review(root)
        elif role == "commit":
            if self.git("status", "--porcelain", "--", "app.txt", root=root):
                self.git("add", "app.txt", root=root)
                self.git("commit", "-qm", "fixture implementation", root=root)
            self.finish({"commit": self.git("rev-parse", "HEAD", root=root)})
        else:
            self.finish({"commit": self.git("rev-parse", "HEAD", root=root),
                         "url": "https://example.invalid/pull/1",
                         "state": "draft" if role == "draft" else "ready",
                         "evidence": "Offline simulated remote receipt; no network used"})

    def test_sequential_run_requires_task_and_full_pr_reviews(self):
        self.init()
        self.preflight()
        root = self.prepare()
        roles = []
        while self.next():
            assignment = self.state["assignment"]
            role = assignment["role"]
            roles.append(role)
            self.execute_fixture(assignment)
        self.assertEqual(roles, ["implement", "review", "commit", "draft", "review", "commit", "ready"])
        self.assertEqual(self.state["outcome"], "completed")
        durable = json.loads((self.store / "RUN.json").read_text())
        self.assertTrue(all(item["outcome"] == "complete" for item in durable["history"]))
        self.assertEqual((self.root / "app.txt").read_text(), "before\n")

    def test_configuration_choices_are_independent_and_artifacts_are_pinned(self):
        for planning, design, execution in (("files", "notion", "claude-workflows"),
                                            ("github", "files", "copilot-workflows")):
            self.plan["configuration"]["planning"]["provider"] = planning
            self.plan["configuration"]["design"]["provider"] = design
            self.plan["configuration"]["execution"]["provider"] = execution
            manifest.validate(self.plan, self.bundle)
        (self.bundle / "design.md").write_text("Unapproved change")
        with self.assertRaisesRegex(manifest.ManifestError, "Artifact changed"):
            manifest.validate(self.plan, self.bundle)

    def test_invalid_graph_scope_and_limits_are_rejected(self):
        mutations = [
            ("limit", lambda value: value["limits"].update(assignments=True)),
            ("cycle", lambda value: value["tasks"][0]["dependencies"].append("change")),
            ("scope", lambda value: value["tasks"][0]["paths"].append("../outside")),
            ("worktree", lambda value: value["prs"][0].update(worktree=".")),
            ("branch", lambda value: value["prs"][0].update(branch="main")),
        ]
        for label, change in mutations:
            with self.subTest(label=label):
                value = copy.deepcopy(self.plan)
                change(value)
                with self.assertRaises(manifest.ManifestError):
                    manifest.validate(value, self.bundle)

    def test_failed_or_missing_results_preserve_attempts_and_require_shutdown(self):
        self.plan["limits"]["attempts"] = 1
        self.init()
        self.next()
        self.mutate("next", ok=False)
        self.mutate("interrupt", "--reason", "Lost worker result")
        self.mutate("resume", "--reason", "Try again", ok=False)
        self.mutate("retire", "--reason", "Worker stopped without a result",
                    "--shutdown-evidence", "Offline fixture has no live worker")
        self.mutate("resume", "--reason", "Reconciled partial work")
        self.next()
        self.assertEqual(self.state["outcome"], "failed")
        self.assertEqual(self.state["consumed_assignments"], 1)

    def test_freshness_scope_and_completed_report_replay(self):
        self.init()
        self.preflight()
        saved = self.store / "reports/A0001.json"
        revision = self.state["revision"]
        self.mutate("record", "--report", saved)
        self.assertEqual(self.state["revision"], revision)
        root = self.prepare()
        self.next()
        (root / "unapproved.txt").write_text("outside scope")
        self.assertIn("outside the approved scope", self.finish(ok=False))
        (root / "unapproved.txt").unlink()
        path = self.report()
        report = json.loads(path.read_text())
        report["artifacts"]["design"] = "0" * 64
        path.write_bytes(manifest.encode(report))
        self.assertIn("artifact identity", self.mutate("record", "--report", path, ok=False))
        self.assertEqual(self.cli("status", self.store)["assignment"]["id"], self.state["assignment"]["id"])

    def test_disabled_controller_does_not_block_status_or_interruption(self):
        self.init()
        config = self.root / ".claude/ioncache-ai-tools.local.json"
        config.parent.mkdir(exist_ok=True)
        for setting in ("autonomous-development", "skill:autonomous-development"):
            config.write_text(json.dumps({"features": {setting: False}}))
            self.assertIn("disabled", self.mutate("next", ok=False))
            self.cli("status", self.store)
        self.mutate("interrupt", "--reason", "Feature disabled")
        self.assertEqual(self.state["outcome"], "blocked")

    def test_review_failure_and_post_review_drift_prevent_commit(self):
        self.init()
        self.preflight()
        root = self.prepare()
        self.next()
        (root / "app.txt").write_text("after\n")
        self.finish()
        self.next()
        self.finish({"ledger": str(root / ".review-loop/missing/REVIEW_LEDGER.json")}, ok=False)
        self.review(root)
        (root / "app.txt").write_text("unreviewed\n")
        self.assertIn("Reviewed content changed", self.mutate("next", ok=False))
        (root / "app.txt").write_text("after\n")
        self.assertEqual(self.next()["role"], "commit")

    def test_reconciliation_preserves_base_budget_and_intervening_work(self):
        self.init()
        self.preflight()
        root = self.prepare()
        self.next()
        (root / "app.txt").write_text("after\n")
        self.finish()
        original = self.next()["comparison_base"]
        self.review(root)
        (root / "app.txt").write_text("intervening change\n")
        self.git("add", "app.txt", root=root)
        self.git("commit", "-qm", "fixture intervening work", root=root)
        self.mutate("next", ok=False)
        consumed = self.state["consumed_assignments"]
        self.mutate("reconcile", "--pr", "first", "--reason", "Within approved app.txt scope")
        assignment = self.next()
        self.assertEqual(assignment["comparison_base"], original)
        self.assertEqual(assignment["attempt"], 2)
        self.assertEqual(self.state["consumed_assignments"], consumed + 1)
        self.assertEqual((root / "app.txt").read_text(), "intervening change\n")
        self.review(root)
        self.assertEqual(self.next()["role"], "commit")

    def test_commit_receipt_cannot_omit_an_added_file(self):
        self.plan["tasks"][0]["paths"] = ["new.txt"]
        self.init()
        self.preflight()
        root = self.prepare()
        self.next()
        (root / "new.txt").write_text("approved new file\n")
        self.finish()
        self.next()
        self.review(root)
        self.assertEqual(self.next()["role"], "commit")
        self.finish({"commit": self.git("rev-parse", "HEAD", root=root)}, ok=False)
        self.git("add", "new.txt", root=root)
        self.git("commit", "-qm", "fixture added file", root=root)
        self.finish({"commit": self.git("rev-parse", "HEAD", root=root)})

    def test_private_inputs_survive_intake_removal_but_reject_tampering(self):
        self.init()
        for item in self.plan["artifacts"]:
            (self.bundle / item["snapshot"]).unlink()
        self.cli("status", self.store)
        shared = self.store / "MANIFEST.json"
        shared.write_text("{}")
        self.assertIn("Shared approved manifest changed", self.cli("status", self.store, ok=False))
        shared.write_bytes(manifest.encode(self.plan))
        (self.store / "inputs/design.md").write_text("Changed private snapshot")
        self.assertIn("Artifact changed", self.cli("status", self.store, ok=False))

    def test_readiness_permissions_are_required_before_implementation_starts(self):
        self.plan["permissions"]["mark_ready"] = False
        self.init()
        self.assertIn("mark_ready was not approved", self.mutate("next", ok=False))
        self.assertFalse((self.root / ".worktrees").exists())

    def test_review_cannot_accept_changes_after_its_snapshot_check(self):
        self.init()
        self.preflight()
        root = self.prepare()
        self.next()
        (root / "app.txt").write_text("after\n")
        self.finish()
        self.next()
        active = json.loads((self.store / "RUN.json").read_text())["active"]
        self.review(root)
        state = json.loads((self.store / "RUN.json").read_text())
        report = state["prs"]["first"]["review"]
        (root / "app.txt").write_text("not part of the review\n")
        with patch.dict(os.environ, self.env, clear=True), \
                patch.object(development.review, "status", return_value=report):
            with self.assertRaisesRegex(manifest.ManifestError, "completed review snapshot"):
                development.review_result(state, active, {"ledger": report["ledger"]})

    def test_ui_evidence_is_bound_to_the_accepted_commit(self):
        self.plan["permissions"]["screenshots"] = True
        self.init()
        self.preflight()
        root = self.prepare()
        while self.next()["role"] != "evidence":
            self.execute_fixture(self.state["assignment"])
        self.finish({"commit": "0" * 40, "artifacts": ["private fixture image"]}, ok=False)
        commit = self.git("rev-parse", "HEAD", root=root)
        self.finish({"commit": commit, "artifacts": ["private fixture image"]})
        ready = self.next()
        self.assertEqual(ready["role"], "ready")
        self.assertEqual(ready["progress"]["evidence"]["commit"], commit)

    def test_waiting_dependencies_leave_independent_prs_eligible(self):
        second = copy.deepcopy(self.plan["prs"][0])
        second.update(id="second", branch="second", worktree=".worktrees/second", dependencies=["first"])
        third = copy.deepcopy(second)
        third.update(id="third", branch="third", worktree=".worktrees/third", dependencies=[])
        self.plan["prs"].extend([second, third])
        for pr in ("second", "third"):
            task = copy.deepcopy(self.plan["tasks"][0])
            task.update(id=pr, pr=pr)
            self.plan["tasks"].append(task)
        self.init()
        self.preflight()
        root = self.prepare()
        while self.next()["role"] != "prepare":
            self.execute_fixture(self.state["assignment"])
        waiting = self.state["assignment"]
        self.assertEqual(waiting["pr"], "third")
        self.finish(outcome="waiting")
        dependent = self.next()
        self.assertEqual(dependent["pr"], "second")
        self.finish(outcome="waiting")
        self.next()
        self.assertEqual(self.state["outcome"], "waiting")
        self.assertEqual(self.state["prs"]["first"]["url"], "https://example.invalid/pull/1")
        consumed = self.state["consumed_assignments"]
        self.mutate("resume", "--reason", "Prerequisite merge observed by caller")
        self.assertIsNotNone(self.next())
        self.assertEqual(self.state["consumed_assignments"], consumed + 1)


if __name__ == "__main__":
    unittest.main()
