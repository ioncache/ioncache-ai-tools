#!/usr/bin/env python3
"""Exercise development contracts and persisted execution without model or network calls."""

import copy
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import development_manifest as manifest
import development_audit as audit
import development_run as development
import development_progress as monitoring
import development_models as models
import development_handoff as handoffs
import review_assignments as assignments
import review_options

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
import pytest
from self_check_support import run_main, uses_process
from workflow_support import run_workflow


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
                    "XDG_STATE_HOME": str(self.folder / "state"),
                    "CODEX_HOME": str(self.folder / "home/.codex"),
                    "COPILOT_HOME": str(self.folder / "home/.copilot"),
                    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                    "PYTHONDONTWRITEBYTECODE": "1"}
        for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
            self.env.pop(key, None)
        environment = patch.dict(os.environ, self.env, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        if hasattr(self, "repository_seed"):
            shutil.copytree(self.repository_seed, self.root, dirs_exist_ok=True)
        else:
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

    def cli(self, *args, ok=True, stdin=None):
        result = run_main(development, args, env=self.env, process=uses_process(self),
                          input=None if stdin is None else json.dumps(stdin))
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

    def mutate(self, command, *args, ok=True, stdin=None):
        result = self.cli(command, self.store, "--revision", self.state["revision"], *args, ok=ok, stdin=stdin)
        if ok:
            self.state = result
        return result

    def next(self):
        self.mutate("next")
        return self.state["assignment"]

    def report(self, data=None, outcome="complete"):
        assignment = self.state["assignment"]
        result = {"assignment": assignment["id"], "worker": None,
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
                                             "independent_review", "result_delivery", "cancellation",
                                             "audit_publication")})

    def test_preflight_discloses_ambient_instructions_without_blocking_progress(self):
        self.init()
        self.assertEqual(self.next()["role"], "preflight")
        data = {name: True for name in ("artifact_access", "native_permissions", "fresh_workers",
                                       "independent_review", "result_delivery", "cancellation")}
        data["ambient_sources"] = ["CLAUDE.md", "AGENTS.md", ".claude/rules/testing.md"]
        self.finish(data)
        self.assertEqual(self.state["outcome"], "running")
        self.assertEqual(self.state["consumed_assignments"], 1)
        self.assertEqual([item["role"] for item in development.load(self.store)["history"]], ["preflight"])
        self.assertEqual(self.next()["role"], "prepare")

    @staticmethod
    def capability_records(**overrides):
        """Returns an honest leaf preflight: read-only checks plus capabilities later steps establish."""
        records = {
            "artifact_access": ("verified", "Every pinned snapshot matched its approved digest"),
            "native_permissions": ("available", "Authenticated; repository API reports push permission"),
            "fresh_workers": ("deferred", "A leaf cannot launch agents; the handoff helper observes launch"),
            "independent_review": ("deferred", "Category-coverage checks at review acceptance establish it"),
            "result_delivery": ("deferred", "The handoff helper validates this report on submission"),
            "cancellation": ("available", "The launcher holds native workflow and agent stop controls"),
        }
        records.update(overrides)
        return {name: {"status": status, "evidence": evidence} for name, (status, evidence) in records.items()}

    @pytest.mark.stable_storage
    def test_honest_preflight_completes_and_helper_records_launch_evidence(self):
        self.init()
        launch = self.folder / "launch"
        launch.mkdir(mode=0o700)
        batch = self.handoff("prepare", "--launch-dir", launch)
        claimed = self.handoff("claim", "--batch", batch["batch"], "--launch-dir", launch)
        self.assertEqual(Path(claimed["script"]).parent, launch.resolve())
        store_script = self.store / "handoffs" / f"{batch['batch']}.js"
        self.assertEqual(Path(claimed["script"]).read_bytes(), store_script.read_bytes())
        self.assertEqual(claimed["script_sha256"], manifest.digest(store_script.read_bytes()))
        self.assertIn("Disclose ambient instructions that appear to conflict", store_script.read_text())
        self.handoff("start", "--batch", batch["batch"], "--job", "1")
        # The workflow template names this candidate path, inside the store, in the worker prompt.
        job = development.load(self.store)["handoffs"][batch["batch"]]["spec"]["jobs"][0]
        candidate = Path(f"{job['result_file']}.candidate.json")
        candidate.write_text(json.dumps({"outcome": "complete", "summary": "Honest leaf preflight",
                                         "evidence": ["Offline fixture"],
                                         "data": self.capability_records()}))
        self.handoff("submit", "--batch", batch["batch"], "--job", "1", "--candidate", candidate)
        self.handoff("collect", "--batch", batch["batch"])
        saved = development.load(self.store)
        self.assertTrue(saved["preflight"])
        self.assertEqual(saved["capabilities"]["fresh_workers"]["status"], "verified")
        self.assertEqual(saved["capabilities"]["result_delivery"]["status"], "verified")
        self.assertEqual(saved["capabilities"]["independent_review"]["status"], "deferred")
        self.assertEqual(self.handoff("prepare")["assignment"], "A0002")

    def test_restarted_worker_reconciles_instead_of_failing_its_job(self):
        self.init()
        batch = self.handoff("prepare")
        self.claim_handoff(batch)
        # Claude restarts a stalled agent from the same prompt; its replacement calls start again.
        for count in range(1, handoffs.MAX_RESTARTS + 1):
            restarted = self.handoff("start", "--batch", batch["batch"], "--job", "1")
            self.assertEqual((restarted["restart"], restarted["reported"]), (count, False))
            self.assertIn("reconcile", restarted["instruction"])
        exhausted = self.handoff("start", "--batch", batch["batch"], "--job", "1", ok=False)
        self.assertIn("restart allowance exhausted", exhausted["error"])
        job = development.load(self.store)["handoffs"][batch["batch"]]["spec"]["jobs"][0]
        candidate = Path(f"{job['result_file']}.candidate.json")
        candidate.write_text(json.dumps({"outcome": "complete", "summary": "Restarted leaf preflight",
                                         "evidence": ["Offline fixture"], "data": self.capability_records()}))
        self.handoff("submit", "--batch", batch["batch"], "--job", "1", "--candidate", candidate)
        self.handoff("collect", "--batch", batch["batch"])
        self.assertTrue(development.load(self.store)["preflight"])
        self.assertEqual(self.cli("status", self.store)["consumed_assignments"], 1)

    def test_external_effect_roles_never_restart(self):
        # A restart cannot be told apart from a second launch, so these never run twice.
        for role in development.REVIEW_DEPENDENT_ROLES:
            with self.subTest(role=role), self.assertRaisesRegex(ValueError, "has external effects"):
                handoffs.restart(None, None, None, {"role": role}, "1", None)
        self.assertEqual(set(development.REVIEW_DEPENDENT_ROLES),
                         {"commit", "draft", "ready", "evidence", "audit-initial", "audit-final"})

    def test_restart_after_a_report_returns_or_corrects_it(self):
        self.init()
        batch = self.handoff("prepare")
        self.claim_handoff(batch)
        job = development.load(self.store)["handoffs"][batch["batch"]]["spec"]["jobs"][0]
        candidate = Path(f"{job['result_file']}.candidate.json")
        candidate.write_text(json.dumps({"outcome": "complete", "summary": "Leaf preflight",
                                         "evidence": ["Offline fixture"], "data": self.capability_records()}))
        self.handoff("submit", "--batch", batch["batch"], "--job", "1", "--candidate", candidate)
        restarted = self.handoff("start", "--batch", batch["batch"], "--job", "1")
        self.assertTrue(restarted["reported"])
        self.assertIn("return without repeating work", restarted["instruction"])
        # A report that collection rejected still needs correction, so a replacement must not skip it.
        with patch.dict(os.environ, self.env), \
                patch.object(handoffs.run, "complete", side_effect=ValueError("Fixture rejection")), \
                self.assertRaisesRegex(ValueError, "Fixture rejection"):
            handoffs.collect(self.store, SimpleNamespace(batch=batch["batch"]))
        restarted = self.handoff("start", "--batch", batch["batch"], "--job", "1")
        self.assertFalse(restarted["reported"])
        self.assertIn("Fixture rejection", restarted["instruction"])
        self.assertIn("Correct only the report", restarted["instruction"])
        candidate.write_text(json.dumps({"outcome": "complete", "summary": "Corrected leaf preflight",
                                         "evidence": ["Offline fixture"], "data": self.capability_records()}))
        self.handoff("submit", "--batch", batch["batch"], "--job", "1", "--candidate", candidate)
        self.handoff("collect", "--batch", batch["batch"])
        self.assertTrue(development.load(self.store)["preflight"])

    def test_unsupported_effort_is_rejected_before_reservation(self):
        self.init()
        choices = {role: {"model": None, "effort": "high", "fallback": "configured"} for role in models.ROLES}
        choices["preflight"]["effort"] = "ultra"
        path = self.folder / "efforts.json"
        path.write_text(json.dumps(choices))
        denied = self.handoff("prepare", "--models-file", path, ok=False)
        self.assertIn("Effort must be null or one of low, medium, high, xhigh, max", denied["error"])
        self.assertEqual(self.cli("status", self.store)["consumed_assignments"], 0)
        choices["preflight"]["effort"] = "xhigh"
        path.write_text(json.dumps(choices))
        self.assertEqual(self.handoff("prepare", "--models-file", path)["action"], "launch")

    @pytest.mark.stable_storage
    def test_missing_capability_blocks_with_recovery_and_retry_proceeds(self):
        self.init()
        batch = self.handoff("prepare")
        self.claim_handoff(batch)
        candidate = self.store / "candidate.json"
        denied = self.capability_records(native_permissions=("missing", "gh is not authenticated"))
        candidate.write_text(json.dumps({"outcome": "complete", "summary": "Claims success",
                                         "evidence": ["Offline fixture"], "data": denied}))
        failure = self.handoff("submit", "--batch", batch["batch"], "--job", "1",
                               "--candidate", candidate, ok=False)
        self.assertIn("Report outcome blocked", failure["error"])
        deferred = self.capability_records(native_permissions=("deferred", "Not checked"))
        candidate.write_text(json.dumps({"outcome": "complete", "summary": "Defers a checkable capability",
                                         "evidence": ["Offline fixture"], "data": deferred}))
        failure = self.handoff("submit", "--batch", batch["batch"], "--job", "1",
                               "--candidate", candidate, ok=False)
        self.assertIn("read-only evidence", failure["error"])
        candidate.write_text(json.dumps({"outcome": "blocked", "summary": "Authentication missing",
                                         "evidence": ["gh auth status failed"], "data": denied}))
        self.handoff("submit", "--batch", batch["batch"], "--job", "1", "--candidate", candidate)
        self.handoff("collect", "--batch", batch["batch"])
        self.state = self.cli("status", self.store)
        self.assertEqual(self.state["outcome"], "blocked")
        self.mutate("resume", "--reason", "Authentication restored")
        retry = self.handoff("prepare")
        self.assertEqual(development.load(self.store)["active"]["attempt"], 2)
        self.claim_handoff(retry)
        self.finish(self.capability_records())
        self.assertTrue(development.load(self.store)["preflight"])

    def test_audit_preflight_defers_pr_body_editing_until_a_pr_exists(self):
        self.plan["repository"]["url"] = "https://github.com/fixture/project.git"
        self.plan["permissions"]["publish_audit"] = True
        self.git("remote", "set-url", "origin", self.plan["repository"]["url"])
        self.init()
        self.assertEqual(self.next()["role"], "preflight")
        records = self.capability_records()
        self.finish(records, ok=False)
        records.update(self.capability_records(audit_publication=(
            "missing", "Wiki is not initialized")))
        self.finish(records, ok=False)
        records.update(self.capability_records(audit_publication=(
            "available", "Wiki reachable, dry-run push authenticated; PR-body editing deferred to audit-initial")))
        self.finish(records)
        self.assertEqual(self.state["outcome"], "running")
        self.assertEqual(self.next()["role"], "prepare")

    def test_launch_copy_is_verified_private_and_outside_planned_worktrees(self):
        self.init()
        launch = self.folder / "launch"
        launch.mkdir(mode=0o700)
        batch = self.handoff("prepare", "--launch-dir", launch)
        copy_path = Path(batch["script"])
        expected = copy_path.read_bytes()
        self.assertEqual(copy_path.stat().st_mode & 0o077, 0)
        copy_path.chmod(0o644)
        self.assertEqual(self.handoff("prepare", "--launch-dir", launch)["script"], str(copy_path))
        self.assertEqual(copy_path.stat().st_mode & 0o077, 0)
        copy_path.write_text("throw new Error('tampered launch copy')\n")
        # A rejected launch directory leaves the batch claimable.
        self.assertIn("absolute path", self.handoff("claim", "--batch", batch["batch"],
                                                    "--launch-dir", "relative", ok=False)["error"])
        claimed = self.handoff("claim", "--batch", batch["batch"], "--launch-dir", launch)
        self.assertEqual(Path(claimed["script"]).read_bytes(), expected)
        self.assertEqual(len(list(launch.glob("*-changed-*.js"))), 1)
        # A refused launch of a claimed batch recovers the same verified copy without another reservation.
        again = self.handoff("prepare", "--launch-dir", launch)
        self.assertEqual((again["action"], again["script"]), ("collect", claimed["script"]))
        self.assertEqual(self.cli("status", self.store)["consumed_assignments"], 1)
        shared = self.folder / "shared"
        shared.mkdir()
        shared.chmod(0o777)
        inside = self.root / ".worktrees"
        inside.mkdir()
        for directory, message in ((shared, "not group- or world-writable"),
                                   (inside, "outside the launch repository"),
                                   ("relative", "absolute path")):
            self.assertIn(message, self.handoff("prepare", "--launch-dir", directory, ok=False)["error"])

    def test_delivery_prompts_state_approved_authorization_only_for_granted_operations(self):
        granted = {"permissions": {"commit": True, "push": True, "create_pr": True,
                                   "mark_ready": False, "screenshots": False}}
        draft = handoffs.jobs.authorization(granted, "draft")
        self.assertIn("approved push, create_pr", draft)
        self.assertIn("explicit authorization for this draft operation", draft)
        self.assertIn("host permission denial still means blocked", draft)
        self.assertEqual(handoffs.jobs.authorization(granted, "ready"), "")
        self.assertEqual(handoffs.jobs.authorization(granted, "implement"), "")
        self.assertIn("Disclose ambient instructions", handoffs.jobs.authorization(granted, "preflight"))

    @pytest.mark.stable_storage
    def test_writer_prompts_reach_native_workers_without_readonly_contamination(self):
        root, batch, owner_path = self.review_handoff_fixture()
        data = self.review(root, record=False)
        phase = json.loads(Path(data["plan"]).read_text())
        assignment = self.state["assignment"]
        reference = {"path": data["plan"], "identity": phase["identity"]}
        requests = [
            {"role": role, "prompt": "Correct only validated F001", "result_file": f"/private/{role}.json",
             **({"writing_plan": reference} if role == "fixer" else {})}
            for role in ("implement", "fixer", "adjudicator", "validator")
        ]
        packet = next(iter(phase["packets"].values()))
        requests.append({"role": "reviewer", "prompt": "", "result_file": packet["result_file"], "packet": packet})
        jobs = [handoffs.jobs.job(assignment, request, self.store / "executor") for request in requests]
        for job in jobs:
            writer = job["role"] in ("implement", "fixer")
            self.assertEqual("# Writing quality" in job["prompt"], writer)
            self.assertEqual("Before reporting, self-check your actual diff" in job["prompt"], writer)
            if writer:
                self.assertIn("read and reconcile the surrounding context", job["prompt"])
                standards = json.loads(job["prompt"].split("\nWriting standards: ", 1)[1].split("\n", 1)[0])
                for key, entry in standards["standards"].items():
                    self.assertEqual(entry["sources"][0]["content"], phase["registry"][key]["sources"][0]["content"])
                self.assertNotIn("jsdoc", standards["standards"])
                self.assertNotIn("PROTOCOL.md", job["prompt"])
        result = subprocess.run(["node", str(SCRIPTS / "development_workflow_self_check.js"), "--writer-prompts"],
                                input=json.dumps(jobs), capture_output=True, text=True, env=self.env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        jobs[1]["prompt"] = jobs[1]["prompt"].replace("Writing standards: ", "Missing standards: ")
        rejected = subprocess.run(
            ["node", str(SCRIPTS / "development_workflow_self_check.js"), "--writer-prompts"],
            input=json.dumps(jobs), capture_output=True, text=True, env=self.env)
        self.assertNotEqual(rejected.returncode, 0, "Native prompt assertions were swallowed")

    @pytest.mark.stable_storage
    def test_fixer_plan_reference_can_be_corrected_without_repeating_review(self):
        root, batch, owner_path = self.review_handoff_fixture()
        data = self.review(root, record=False)
        phase = json.loads(Path(data["plan"]).read_text())
        request = {"role": "fixer", "prompt": "Correct only validated F001",
                   "result_file": str(self.store / "reports" / self.state["assignment"]["id"] / "fixer.json")}
        response = {"outcome": "dispatch", "requests": [request], "result_file": ""}
        owner_path.write_text(json.dumps(response))
        rejected = self.handoff("finish", "--batch", batch["batch"], "--job", 1, ok=False)
        self.assertIn("writing_plan needs", rejected["error"])
        consumed = self.cli("status", self.store)["consumed_assignments"]
        request["writing_plan"] = {"path": data["plan"], "identity": phase["identity"]}
        owner_path.write_text(json.dumps(response))
        self.handoff("finish", "--batch", batch["batch"], "--job", 1)
        self.handoff("collect", "--batch", batch["batch"])
        fixer = self.handoff("prepare")
        self.assertLessEqual(Path(fixer["script"]).stat().st_size, handoffs.SCRIPT_BYTES)
        job = self.claim_handoff(fixer)[0]
        self.assertIn("# Writing quality", job["prompt"])
        self.assertEqual(self.cli("status", self.store)["consumed_assignments"], consumed)
        self.assertEqual(development.load(self.store)["handoffs"][batch["batch"]]["failures"]["1"], 1)

    def test_writer_optout_and_unavailable_settings_do_not_change_other_roles(self):
        assignment = {"root": str(self.root)}
        request = {"role": "fixer", "prompt": "Validated F001 only"}
        config = self.root / ".codex/ioncache-ai-tools.local.json"
        config.parent.mkdir()
        config.write_text(json.dumps({"features": {"writer-quality-guidance": False}}))
        before = config.read_bytes()
        self.assertEqual(handoffs.jobs.writing_guidance.job_guidance(assignment, request, SCRIPTS.parent), "")
        self.assertEqual(config.read_bytes(), before)
        config.write_text("{")
        message = handoffs.jobs.writing_guidance.job_guidance(assignment, request, SCRIPTS.parent)
        self.assertIn("Writing guidance unavailable", message)
        self.assertIn("Continue the bounded assignment", message)
        self.assertEqual(config.read_text(), "{")
        for role in ("reviewer", "validator", "adjudicator"):
            self.assertEqual(handoffs.jobs.writing_guidance.job_guidance(
                assignment, {"role": role}, SCRIPTS.parent), "")

    @pytest.mark.stable_storage
    def test_missing_optional_guidance_keeps_the_bounded_implementation_launchable(self):
        self.init()
        self.preflight()
        self.prepare()
        self.mutate("interrupt", "--reason", "Exercise optional resource loss before a new pin")
        state = development.load(self.store)
        self.assertIsNone(state["active"])
        source = self.folder / "executor-without-writing-contract"
        shutil.copytree(handoffs.executor.ROOT, source)
        (source / "skills/review-code/WRITING.md").unlink()
        self.mutate("resume", "--reason", "Continue with the available installed resources")
        with patch.object(handoffs.executor, "ROOT", source):
            batch = self.handoff("prepare")
            job = self.claim_handoff(batch)[0]
        self.assertIn("Writing guidance unavailable", job["prompt"])
        self.assertIn("Perform the bounded implement assignment", job["prompt"])
        self.assertIn("Development report contract", job["prompt"])
        self.assertEqual(development.load(self.store)["active"]["attempt"], 1)

    def prepare(self):
        assignment = self.next()
        self.assertEqual(assignment["role"], "prepare")
        pr = assignment["pr_plan"]
        subprocess.run([sys.executable, str(SCRIPTS / "create-worktree.py"), "-b",
                        pr["branch"], assignment["root"], pr["base"]], cwd=self.root,
                       env=self.env, check=True, capture_output=True)
        self.finish({"base": pr["base"], "merged_dependencies": pr["dependencies"]})
        return Path(assignment["root"])

    def review_records(self, root, snapshot, files=None):
        assignment = self.state["assignment"]
        scratch = self.store / "reports" / assignment["id"]
        scratch.mkdir(exist_ok=True)
        options = run_main(
            review_options, ["review-validate-fix-loop"],
            cwd=root, env=self.env, process=uses_process(self))
        self.assertEqual(options.returncode, 0, options.stderr)
        if files is None:
            files = development.review_files(root, assignment["comparison_base"])
        phase = assignments.prepare({
            "objective": "Fixture review", "kind": "full", "target": "branch",
            "root": str(root), "base": assignment["comparison_base"], "snapshot": snapshot,
            "files": files, "constraints": ["Offline fixture; no model launches"],
            "scratch_directory": str(scratch), "review_options": json.loads(options.stdout),
            "language_inventory": {
                name: {"languages": [], "evidence": "Inspected plain-text fixture content"}
                for name in files},
        })
        attempts = []
        for packet in phase["packets"].values():
            result = {
                "assignment": packet["assignment"], "review_type": packet["review_type"],
                "instruction_set": packet["instruction_set"]["identity"],
                "packet_identity": packet["identity"], "snapshot": snapshot,
                "worker": None, "origin": "specialist", "selection": {"actual": "unknown"},
                "coverage": {"files": packet["scope_files"], "isolation": "unknown"},
                "outcome": "complete", "candidates": [], "limitations": [],
            }
            Path(packet["result_file"]).write_bytes(manifest.encode(result))
            attempts.append({"id": packet["assignment"], "round": 0, "packet": packet,
                             "worker": None, "result": result,
                             "observation": {"kind": "caller", "source": "Offline fixture"}})
        handoff = {"history_complete": True, "attempts": attempts,
                   "active": {item["packet"]["review_type"]: [item["id"]] for item in attempts},
                   "other_workers": [{"role": "adjudicator", "worker": None}]}
        paths = {"plan": str(scratch / "phase.json"), "handoff": str(scratch / "handoff.json")}
        for key, value in (("plan", phase), ("handoff", handoff)):
            Path(paths[key]).write_bytes(manifest.encode(value))
        return paths, phase

    def review(self, root, *, record=True, files=None, finding=False, advance=True, checks=None):
        assignment = self.state["assignment"]
        base = assignment["comparison_base"]
        args = ["init", "--objective", "Fixture review", "--scope", "fixture", "--base", base,
                "--storage", assignment["review_storage"],
                "--max-loops", str(self.plan["limits"]["review_loops"]),
                "--max-fix-cycles", str(self.plan["limits"]["fix_cycles"])]
        result = self.review_cli(root, args)
        ledger = result["ledger"]
        records, phase = self.review_records(root, result["snapshot"], files)
        events = [
            {"type": "start_review", "reason": json.dumps(phase)},
            {"type": "review_done", "passes": [
                {"name": category, "worker": "unobserved (non-identity marker)",
                 "result": "complete", "evidence": "Offline fixture; native identity not observed"}
                for category in phase["required"]],
             "checks": checks if checks is not None else [
                 {"name": "fixture", "result": "passed", "evidence": "Fixture command exited zero"}]},
            {"type": "advance"},
        ]
        if finding:
            events[-1:-1] = [
                {"type": "finding", "key": "private-fixture-key", "summary": "PRIVATE-AUDIT-SENTINEL",
                 "locations": [str(root / "app.txt")], "severity": "Low",
                 "evidence": ["PRIVATE-AUDIT-SENTINEL"]},
                {"type": "decision", "id": "F001", "validation": "invalid", "disposition": "ignored",
                 "severity": "Low", "evidence": ["PRIVATE-AUDIT-SENTINEL"]},
            ]
        if not advance:
            events.pop()
        subprocess.run([sys.executable, "-c", "assert True"], env=self.env, cwd=root, check=True)
        for event in events:
            event.update(actor="fixture-owner")
            event.setdefault("reason", "Offline regression evidence")
            result = self.review_cli(root, ["apply", ledger, "--revision", str(result["revision"])], event)
        data = {"ledger": ledger, **records}
        if record:
            self.finish(data)
        return data

    def review_cli(self, root, args, event=None):
        result = run_main(development.review, args, input=json.dumps(event),
                          env=self.env, cwd=root, process=uses_process(self))
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    @pytest.mark.stable_storage
    def test_preexisting_no_action_finding_reaches_pr_draft_and_final_report(self):
        self.plan["permissions"]["create_follow_up_issues"] = True
        self.init()
        self.preflight()
        root = self.prepare()
        self.execute_fixture(self.next())
        self.assertEqual(self.next()["role"], "review")
        data = self.review(root, record=False, advance=False)
        state = self.review_cli(root, ["status", data["ledger"]])
        for index, (key, validation, material) in enumerate(
                (("preexisting", "valid", True), ("invalid", "invalid", True), ("style", "valid", False)), 1):
            details = {"key": key, "title": f"{key} issue", "summary": f"{key} evidence summary",
                       "validation": validation, "material": material, "sensitive": False,
                       "introduced": False, "report_action": "None", "locations": ["app.txt:1"],
                       "reason": "Not introduced by this change", "evidence": ["Verified fixture premise"]}
            details["public"] = {name: details[name] for name in ("title", "summary", "locations", "reason")}
            events = [
                {"type": "finding", "key": key, "summary": details["title"], "severity": "Low",
                 "locations": ["app.txt:1"], "evidence": ["Fixture observation"]},
                {"type": "decision", "id": f"F{index:03}", "validation": validation,
                 "disposition": "ignored", "severity": "Low",
                 "evidence": [json.dumps({"assessment": details})]},
            ]
            for event in events:
                event.update(actor="fixture-owner", reason="Not introduced by this change")
                state = self.review_cli(root, ["apply", data["ledger"], "--revision", str(state["revision"])], event)
        self.review_cli(root, ["apply", data["ledger"], "--revision", str(state["revision"])],
                        {"type": "advance", "actor": "fixture-owner", "reason": "No in-scope corrections"})
        status = self.review_cli(root, ["status", data["ledger"]])
        self.assertEqual([item["key"] for item in status["known_issues"]], ["preexisting"])
        self.finish(data)
        self.execute_fixture(self.next())
        draft = self.next()
        self.assertEqual(draft["role"], "draft")
        self.assertTrue(draft["follow_ups"]["enabled"])
        self.assertIn("preexisting issue", draft["progress"]["known_issues_report"])
        self.assertIn("preexisting issue", draft["progress"]["known_issues_pr_draft"])
        self.assertIn("Not introduced by this change", draft["progress"]["known_issues_pr_draft"])
        prompt = handoffs.jobs.instructions(draft, {"role": "draft"}, "/pinned")
        self.assertIn("Known issues not fixed here", prompt)
        self.assertIn("Create or reuse follow-up issues automatically", prompt)
        self.execute_fixture(draft)
        while self.next():
            self.execute_fixture(self.state["assignment"])
        self.assertEqual(self.state["outcome"], "completed")
        result = self.cli("status", self.store)["prs"]["first"]
        self.assertIn("preexisting issue", result["known_issues_report"])
        self.assertNotIn("invalid issue", result["known_issues_report"])
        self.assertNotIn("style issue", result["known_issues_report"])
        self.assertEqual(result["counted_only"], 2)
        self.assertEqual(result["follow_up_issues"]["preexisting"]["status"], "not_filed")
        self.assertIn("not_filed", result["known_issues_report"])

    def test_follow_up_approval_remains_optional_and_strictly_boolean(self):
        self.init()
        self.assertFalse(self.next()["follow_ups"]["enabled"])
        self.assertNotIn("create_follow_up_issues", development.load(self.store)["manifest"]["permissions"])
        self.plan["permissions"]["create_follow_up_issues"] = "true"
        self.path.write_bytes(manifest.encode(self.plan))
        self.assertIn("explicit booleans", self.cli("validate", self.path, ok=False))

    def stopped_review_with_finding(self, outcome="blocked", root=None):
        root = root or self.start_review_fixture()
        data = self.review(root, record=False, finding=True, advance=False)
        state = self.review_cli(root, ["status", data["ledger"]])
        events = [
            {"type": "decision", "id": "F001", "validation": "valid", "disposition": "out_of_scope",
             "severity": "Low", "evidence": ["Established a real pre-existing problem"]},
            {"type": "stop", "outcome": outcome},
        ]
        for event in events:
            event.update(actor="fixture-owner", reason="Remaining investigation unavailable")
            state = self.review_cli(root, ["apply", data["ledger"], "--revision", str(state["revision"])], event)
        return root, data

    @pytest.mark.stable_storage
    def test_blocked_review_still_retains_named_findings_for_the_final_report(self):
        _, data = self.stopped_review_with_finding()
        self.finish(data, outcome="blocked")
        self.assertEqual(self.state["outcome"], "blocked")
        report = self.state["prs"]["first"]["known_issues_report"]
        self.assertIn("PRIVATE-AUDIT-SENTINEL", report)
        self.assertIn("Remaining investigation unavailable", report)
        self.assertIsNone(development.load(self.store)["prs"]["first"]["accepted"])

    @pytest.mark.stable_storage
    def test_blocked_review_without_a_ledger_retains_findings_without_acceptance(self):
        root, data = self.stopped_review_with_finding("failed")
        self.finish({}, outcome="blocked")
        self.assertEqual(self.state["outcome"], "blocked")
        self.assertIn("PRIVATE-AUDIT-SENTINEL", self.state["prs"]["first"]["known_issues_report"])
        saved = development.load(self.store)
        self.assertIsNone(saved["active"])
        self.assertIsNone(saved["prs"]["first"]["accepted"])
        self.assertEqual(saved["history"][-1]["finding_ledger"], data["ledger"])
        self.mutate("resume", "--reason", "Retry after the blocked review")
        self.assertEqual(self.next()["attempt"], 2)
        _, retry = self.stopped_review_with_finding(root=root)
        self.finish({}, outcome="blocked")
        saved = development.load(self.store)
        self.assertNotIn("finding_reporting_error", saved["prs"]["first"])
        self.assertEqual(saved["history"][-1]["finding_ledger"], retry["ledger"])
        self.assertNotEqual(retry["ledger"], data["ledger"])
        self.assertIsNone(saved["prs"]["first"]["accepted"])

    @pytest.mark.stable_storage
    def test_blocked_review_without_a_ledger_reports_an_inventory_gap(self):
        _, data = self.stopped_review_with_finding()
        Path(data["ledger"]).unlink()
        self.finish({}, outcome="blocked")
        self.assertEqual(self.state["outcome"], "blocked")
        self.assertIn("Inventory gap:", self.state["prs"]["first"]["known_issues_report"])
        saved = development.load(self.store)
        self.assertIsNone(saved["active"])
        self.assertIsNone(saved["prs"]["first"]["accepted"])
        self.mutate("resume", "--reason", "Continue after recording the gap")
        self.assertEqual(self.next()["attempt"], 2)

    @pytest.mark.stable_storage
    def test_resumed_review_retains_new_findings_without_a_reported_ledger(self):
        root, data = self.stopped_review_with_finding()
        self.finish({}, outcome="blocked")
        self.mutate("resume", "--reason", "Retry the retained review")
        self.assertEqual(self.next()["attempt"], 2)
        self.mutate("resume-review", "--ledger", data["ledger"], "--reason", "Resume retained evidence",
                    "--shutdown-evidence", "Synchronous fixture workers exited")
        self.mutate("claim-review", "--provider", "claude-workflows")
        status = self.review_cli(root, ["status", data["ledger"]])
        events = [
            {"type": "resume"},
            {"type": "finding", "key": "retry-finding", "summary": "Finding discovered during retry",
             "locations": ["app.txt:1"], "severity": "Low", "evidence": ["New retry evidence"]},
            {"type": "decision", "id": "F002", "validation": "valid", "disposition": "out_of_scope",
             "severity": "Low", "evidence": ["Confirmed another pre-existing issue"]},
            {"type": "stop", "outcome": "blocked"},
        ]
        for event in events:
            event.update(actor="fixture-owner", reason="Retained retry evidence")
            status = self.review_cli(root, ["apply", data["ledger"], "--revision", str(status["revision"])], event)
        before = development.load(self.store)
        self.assertEqual(before["active"]["resume_ledger"], before["history"][-2]["finding_ledger"])
        for action in ("record", "retire"):
            with self.subTest(action=action):
                development.save(self.store, copy.deepcopy(before))
                self.state = self.cli("status", self.store)
                self.assertNotIn("Finding discovered during retry", self.state["prs"]["first"]["known_issues_report"])
                if action == "record":
                    self.finish({}, outcome="blocked")
                else:
                    self.mutate("retire", "--reason", "Retry worker stopped",
                                "--shutdown-evidence", "Synchronous fixture workers exited")
                saved = development.load(self.store)
                self.assertIsNone(saved["active"])
                self.assertIsNone(saved["prs"]["first"]["accepted"])
                self.assertNotIn("finding_reporting_error", saved["prs"]["first"])
                self.assertIn("Finding discovered during retry", self.state["prs"]["first"]["known_issues_report"])
                self.assertEqual(saved["history"][-1]["finding_ledger"], data["ledger"])

    @pytest.mark.process(helpers=False)
    def test_fifo_review_ledger_does_not_block_collection_or_retirement(self):
        root, data = self.stopped_review_with_finding()
        path = Path(data["ledger"])
        path.unlink()
        os.mkfifo(path)
        before = development.load(self.store)
        for action in ("record", "retire"):
            with self.subTest(action=action):
                development.save(self.store, copy.deepcopy(before))
                self.state = self.cli("status", self.store)
                arguments = (["--report", str(self.report({}, outcome="blocked"))] if action == "record" else
                             ["--reason", "Unreadable review evidence", "--shutdown-evidence",
                              "Synchronous fixture workers exited"])
                result = subprocess.run(
                    [sys.executable, str(SCRIPTS / "development_run.py"), action, str(self.store),
                     "--revision", str(self.state["revision"]), *arguments],
                    env=self.env, capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.state = json.loads(result.stdout)
                self.assertIn("Inventory gap:", self.state["prs"]["first"]["known_issues_report"])
                saved = development.load(self.store)
                self.assertIsNone(saved["active"])
                self.assertIsNone(saved["prs"]["first"]["accepted"])
                self.mutate("resume", "--reason", "Continue with unavailable evidence recorded")
                self.assertEqual(self.next()["attempt"], 2)
                if action == "retire":
                    self.review_cli(root, ["abandon", data["ledger"], "--reason", "Ledger is a FIFO",
                                          "--evidence", "Inspected the non-regular ledger entry",
                                          "--shutdown-evidence", "Synchronous fixture workers exited"])
                    self.review(root)
                    self.assertIsNotNone(development.load(self.store)["prs"]["first"]["accepted"])

    @pytest.mark.stable_storage
    def test_retired_review_retains_findings_without_acceptance_and_retry_keeps_them(self):
        root, data = self.stopped_review_with_finding("failed")
        before = development.load(self.store)
        self.mutate("retire", "--reason", "Worker stopped before submitting its report",
                    "--shutdown-evidence", "Synchronous fixture workers exited")
        result = self.state["prs"]["first"]
        self.assertIn("PRIVATE-AUDIT-SENTINEL", result["known_issues_report"])
        self.assertNotIn("finding_reporting_error", result)
        saved = development.load(self.store)
        self.assertIsNone(saved["active"])
        self.assertIsNone(saved["prs"]["first"]["accepted"])
        self.assertEqual(saved["attempts"], before["attempts"])
        self.assertEqual(saved["history"][-1]["finding_ledger"], data["ledger"])
        self.mutate("resume", "--reason", "Retry within the retained allowance")
        self.assertEqual(self.next()["attempt"], 2)
        self.review(root)
        self.assertIn("PRIVATE-AUDIT-SENTINEL", self.state["prs"]["first"]["known_issues_report"])

    @pytest.mark.stable_storage
    def test_retirement_ignores_previously_collected_ledgers(self):
        root = self.start_review_fixture()
        self.review(root)
        self.execute_fixture(self.next())
        self.execute_fixture(self.next())
        self.assertEqual(self.next()["role"], "review")
        _, data = self.stopped_review_with_finding("failed", root)
        self.mutate("retire", "--reason", "Full review worker stopped",
                    "--shutdown-evidence", "Synchronous fixture workers exited")
        self.assertNotIn("finding_reporting_error", self.state["prs"]["first"])
        self.assertIn("PRIVATE-AUDIT-SENTINEL", self.state["prs"]["first"]["known_issues_report"])
        self.assertEqual(development.load(self.store)["history"][-1]["finding_ledger"], data["ledger"])

    @pytest.mark.stable_storage
    def test_retirement_reports_unavailable_findings_without_blocking_recovery(self):
        _, data = self.stopped_review_with_finding("failed")
        path = Path(data["ledger"])
        original = path.read_bytes()
        before = development.load(self.store)
        other = path.parent.parent / ("0" * 32)
        for condition in ("missing", "corrupt", "ambiguous"):
            with self.subTest(condition=condition):
                development.save(self.store, copy.deepcopy(before))
                self.state = self.cli("status", self.store)
                if condition == "missing":
                    path.unlink()
                elif condition == "corrupt":
                    path.write_text("{")
                else:
                    other.mkdir()
                self.mutate("retire", "--reason", "Review evidence unavailable",
                            "--shutdown-evidence", "Synchronous fixture workers exited")
                self.assertIn("Incomplete review findings unavailable",
                              self.state["prs"]["first"]["finding_reporting_error"])
                self.assertIn("Inventory gap: Incomplete review findings unavailable",
                              self.state["prs"]["first"]["known_issues_report"])
                self.assertIn("Inventory gap:", self.state["prs"]["first"]["known_issues_pr_draft"])
                self.assertIsNone(development.load(self.store)["active"])
                self.mutate("resume", "--reason", "Continue after recording the inventory gap")
                self.assertEqual(self.next()["attempt"], 2)
                path.write_bytes(original)
                if other.exists():
                    other.rmdir()

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
        elif role in audit.ROLES:
            if not assignment["audit"]["enabled"]:
                self.finish({"disabled": True})
            else:
                state, active, exported = self.audit_export()
                with patch.dict(os.environ, self.env, clear=True), patch.object(audit, "api", self.audit_api):
                    receipt = audit.publish(state, active, exported["identity"])
                self.finish(receipt)
        else:
            self.finish({"commit": self.git("rev-parse", "HEAD", root=root),
                         "url": ("https://github.com/fixture/project/pull/1"
                                 if self.plan["permissions"].get("publish_audit")
                                 else "https://example.invalid/pull/1"),
                         "state": "draft" if role == "draft" else "ready",
                         "evidence": "Offline simulated remote receipt; no network used"})

    def configure_audit(self):
        self.plan["permissions"]["publish_audit"] = True
        self.plan["constraints"].append("PRIVATE-AUDIT-SENTINEL")
        self.plan["repository"]["url"] = "https://github.com/fixture/project.git"
        self.git("remote", "set-url", "origin", self.plan["repository"]["url"])
        self.remote = self.folder / "audit-remote.git"
        self.git("init", "--bare", "-q", str(self.remote))
        self.wiki_remote = self.folder / "wiki-remote.git"
        self.git("init", "--bare", "-q", "-b", "docs", str(self.wiki_remote))
        self.wiki = self.folder / "wiki"
        self.wiki.mkdir()
        self.git("init", "-q", "-b", "docs", root=self.wiki)
        self.git("config", "user.name", "Wiki fixture", root=self.wiki)
        self.git("config", "user.email", "fixture@example.invalid", root=self.wiki)
        (self.wiki / "Home.md").write_text("Existing wiki content\n")
        self.git("add", "Home.md", root=self.wiki)
        self.git("commit", "-qm", "Existing wiki", root=self.wiki)
        self.git("push", str(self.wiki_remote), "HEAD:refs/heads/docs", root=self.wiki)
        self.wiki_initial = self.git("rev-parse", "HEAD", root=self.wiki)
        self.audit_git_env = {
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": f"url.file://{self.remote}.insteadOf",
            "GIT_CONFIG_VALUE_0": self.plan["repository"]["url"],
            "GIT_CONFIG_KEY_1": f"url.file://{self.wiki_remote}.insteadOf",
            "GIT_CONFIG_VALUE_1": "https://github.com/fixture/project.wiki.git",
        }
        self.audit_body = "# Fixture PR\n\nA human description.\n\n## Checklist\n\n- [ ] Human check\n"
        self.audit_body_updates = []
        self.lose_audit_response = False

    def audit_export(self):
        state = development.load(self.store)
        active = state["active"]
        self.git("push", "origin", f"HEAD:refs/heads/{self.plan['prs'][0]['branch']}",
                 root=Path(active["root"]))
        with patch.dict(os.environ, self.env, clear=True):
            records = [audit.review_record(path) for path in audit.review_locations(state, active)]
        public = {"summary": "Fixture process audit", "method": "Isolated offline category fixtures",
                  "verification": "Fixture checks passed; no native model was launched.",
                  "findings": [{"review": row["id"], "id": item["id"], "summary": "A fixture concern",
                                "rationale": "Rejected by the fixture's independent assessment"}
                               for row in records if row["available"] for item in row["findings"]],
                  "regressions": [], "limitations": ["Offline evidence only"]}
        folder = self.store / "reports" / active["id"]
        folder.mkdir(exist_ok=True)
        path = folder / "public.json"
        path.write_bytes(manifest.encode(public))
        exported = self.audit_cli("export", "--public", str(path))
        return state, active, exported

    def audit_cli(self, operation, *args, ok=True):
        result = run_main(audit, [operation, str(self.store), *args],
                          env=self.env, process=uses_process(self))
        self.assertEqual(result.returncode, 0 if ok else 2, result.stdout + result.stderr)
        return json.loads(result.stdout) if ok else result.stderr

    def audit_api(self, endpoint, *, data=None, method=None):
        self.assertEqual(endpoint, "repos/fixture/project/pulls/1")
        if data is not None:
            self.assertEqual(method, "PATCH")
            self.assertEqual(set(data), {"body"})
            self.audit_body = data["body"]
            self.audit_body_updates.append(copy.deepcopy(data))
            if self.lose_audit_response:
                self.lose_audit_response = False
                raise OSError("Fixture lost response after PR update")
        head = self.git("ls-remote", "origin", "refs/heads/fixture-feature").split()[0]
        return {"state": "open", "title": "Fixture pull request", "body": self.audit_body,
                "html_url": "https://github.com/fixture/project/pull/1",
                "base": {"repo": {"full_name": "fixture/project"}},
                "head": {"sha": head, "ref": "fixture-feature", "repo": {"full_name": "fixture/project"}}}

    def start_audit_fixture(self):
        self.configure_audit()
        self.init()
        self.env.update(self.audit_git_env)
        self.preflight()
        root = self.prepare()
        self.next()
        (root / "app.txt").write_text("after\n")
        self.finish({"private_diagnostics": "PRIVATE-AUDIT-SENTINEL"})
        self.next()
        self.review(root, finding=True)
        while self.next()["role"] != "audit-initial":
            self.execute_fixture(self.state["assignment"])
        return root

    @pytest.mark.stable_storage
    def test_audit_publication_preserves_code_and_recovers_lost_response(self):
        root = self.start_audit_fixture()
        before = self.review_cli(root, ["fingerprint"])
        state, active, exported = self.audit_export()
        for name in audit.FILES:
            content = (Path(exported["directory"]) / name).read_text()
            self.assertNotIn("PRIVATE-AUDIT-SENTINEL", content)
            self.assertNotIn(str(self.folder), content)
        bundle = json.loads((Path(exported["directory"]) / "audit.json").read_bytes())
        linked = bundle["reviews"][0]["assignment_ids"]
        self.assertEqual(linked, [item["id"] for item in bundle["history"] if item["role"] == "review"])
        self.assertEqual(bundle["reviews"][0]["findings"][0]["validation"], "invalid")
        self.lose_audit_response = True
        with patch.dict(os.environ, self.env, clear=True), patch.object(audit, "api", self.audit_api):
            with self.assertRaisesRegex(OSError, "lost response"):
                audit.publish(state, active, exported["identity"])
            self.assertFalse((Path(exported["directory"]) / "receipt.json").exists())
            first = self.git("ls-remote", str(self.wiki_remote), "HEAD")
            receipt = audit.publish(state, active, exported["identity"])
            self.assertEqual(first, self.git("ls-remote", str(self.wiki_remote), "HEAD"))
        self.assertEqual(len(self.audit_body_updates), 1)
        self.assertEqual(before, self.review_cli(root, ["fingerprint"]))
        self.assertTrue(self.audit_body.startswith("# Fixture PR\n\nA human description.\n"))
        self.assertTrue(self.audit_body.endswith("## Checklist\n\n- [ ] Human check\n"))
        self.assertIn(receipt["url"], self.audit_body)
        self.finish(receipt)
        while self.next():
            self.execute_fixture(self.state["assignment"])
        self.assertEqual(self.state["outcome"], "completed")
        self.assertEqual(len(self.audit_body_updates), 2)
        self.assertEqual([item["stage"] for item in self.state["prs"]["first"]["audits"]], list(audit.ROLES))
        final = self.state["prs"]["first"]["audits"][-1]
        self.assertNotEqual(receipt["wiki_commit"], final["wiki_commit"])
        self.assertNotEqual(receipt["url"], final["url"])
        self.assertNotIn(receipt["url"], self.audit_body)
        self.assertIn(final["url"], self.audit_body)
        self.assertEqual(final["code_commit"], self.git("rev-parse", "HEAD", root=root))
        self.git("fetch", str(self.wiki_remote), "docs", root=self.wiki)
        table = self.git("show", f"FETCH_HEAD:{audit.INDEX_PAGE}.md", root=self.wiki)
        self.assertEqual(table.count("](https://github.com/fixture/project/pull/1)"), 1)
        self.assertIn(final["url"], table)
        self.assertNotIn(receipt["url"], table)
        home = self.git("show", "FETCH_HEAD:Home.md", root=self.wiki)
        self.assertTrue(home.startswith("Existing wiki content\n"))
        self.assertEqual(home.count(final["index_url"]), 1)
        for published in (receipt, final):
            page = published["url"].rsplit("/", 1)[1]
            content = self.git("show", f"FETCH_HEAD:{page}.json", root=self.wiki)
            self.assertEqual(json.loads(content)["stage"], published["stage"])
            self.assertNotIn("PRIVATE-AUDIT-SENTINEL", content)
        self.assertEqual(self.git("for-each-ref", "--format=%(refname)", root=self.remote),
                         "refs/heads/fixture-feature")
        self.git("push", "origin", "--delete", "fixture-feature")
        self.assertIn(final["wiki_commit"], self.git("ls-remote", str(self.wiki_remote), "HEAD"))

    @pytest.mark.stable_storage
    def test_failed_audit_retries_without_refunding_or_consuming_the_final_audit_attempt(self):
        root = self.start_audit_fixture()
        before = self.review_cli(root, ["fingerprint"])
        consumed = self.state["consumed_assignments"]
        self.finish(outcome="blocked")
        self.mutate("resume", "--reason", "Recovered publication capability within approved limits")
        retried = self.next()
        self.assertEqual(retried["role"], "audit-initial")
        self.assertEqual(retried["attempt"], 2)
        self.assertEqual(self.state["consumed_assignments"], consumed + 1)
        self.execute_fixture(retried)
        while self.next():
            if self.state["assignment"]["role"] == "audit-final":
                self.assertEqual(self.state["assignment"]["attempt"], 1)
            self.execute_fixture(self.state["assignment"])
        self.assertEqual(self.state["outcome"], "completed")
        self.assertEqual(before, self.review_cli(root, ["fingerprint"]))

    @pytest.mark.stable_storage
    def test_published_audit_survives_later_worker_and_control_model_observations(self):
        self.start_audit_fixture()
        active = self.state["assignment"]
        observation = ("model-report", self.store, "--invocation", "audit-observations", "--call", "1",
                       "--role", active["role"], "--assignment", active["id"],
                       "--selected-model", "requested-audit", "--actual-model", "observed-audit",
                       "--source", "native-context")
        self.cli(*observation)
        state, active, exported = self.audit_export()
        files = {name: (Path(exported["directory"]) / name).read_bytes() for name in audit.FILES}
        with patch.dict(os.environ, self.env, clear=True), patch.object(audit, "api", self.audit_api):
            receipt = audit.publish(state, active, exported["identity"])
        self.cli(*observation)
        self.cli("model-report", self.store, "--invocation", "audit-observations", "--call", "2",
                 "--role", "development-control", "--actual-model", "observed-control",
                 "--source", "native-context")
        self.finish(receipt)
        self.assertEqual(len(self.audit_body_updates), 1)
        self.assertEqual(files, {name: (Path(exported["directory"]) / name).read_bytes()
                                 for name in audit.FILES})
        records, unavailable = models.observations(development.load(self.store), "first")
        self.assertFalse(unavailable)
        self.assertEqual(len(records), 2)
        self.assertEqual(self.next()["role"], "review")

    def test_complete_review_store_and_archive_survive_worktree_cleanup(self):
        root = self.start_audit_fixture()
        while self.state["assignment"]:
            self.execute_fixture(self.state["assignment"])
            self.next()
        saved = development.load(self.store)
        final = next(item for item in reversed(saved["history"]) if item["role"] == "audit-final")
        public = self.store / "reports" / final["id"] / "public.json"
        with patch.dict(os.environ, self.env, clear=True):
            paths = audit.review_locations(saved, final)
        originals = {path: path.read_bytes() for path in paths}
        self.assertTrue(paths)
        self.assertTrue(all(path.is_relative_to(self.store / "reviews") for path in paths))
        self.assertFalse((root / ".review-loop").exists())
        before = (self.store / "RUN.json").read_bytes()
        updates = len(self.audit_body_updates)
        self.git("worktree", "remove", str(root))
        self.assertFalse(root.exists())
        result = self.audit_cli("archive", "--pr", "first", "--public", str(public))
        exported = json.loads((Path(result["directory"]) / "audit.json").read_bytes())
        self.assertTrue(result["historical"])
        self.assertEqual(exported["stage"], "archive")
        self.assertTrue(all(record["available"] for record in exported["reviews"]))
        self.assertEqual(originals, {path: path.read_bytes() for path in paths})
        self.assertEqual(before, (self.store / "RUN.json").read_bytes())
        self.assertEqual(updates, len(self.audit_body_updates))
        self.assertIn("Reserve an audit", self.audit_cli("publish", "--approved", result["identity"], ok=False))
        with patch.object(audit, "api", self.audit_api):
            receipt = self.audit_cli("publish-archive", "--pr", "first", "--approved", result["identity"])
        self.assertEqual(receipt["stage"], "archive")
        self.assertEqual(before, (self.store / "RUN.json").read_bytes())
        self.assertFalse(root.exists())
        last_review = next(item for item in reversed(saved["history"]) if item["role"] == "review")
        missing = Path(last_review["report"]["data"]["ledger"])
        missing.parent.rename(self.store / ("missing-review-" + missing.parent.name))
        archived = self.audit_cli("archive", "--pr", "first", "--public", str(public))
        records = json.loads((Path(archived["directory"]) / "audit.json").read_bytes())["reviews"]
        self.assertEqual(len(records), len(paths))
        self.assertFalse(next(item for item in records if item["id"] == missing.parent.name)["available"])
        missing.parent.symlink_to(self.store / "unavailable-directory", target_is_directory=True)
        archived = self.audit_cli("archive", "--pr", "first", "--public", str(public))
        records = json.loads((Path(archived["directory"]) / "audit.json").read_bytes())["reviews"]
        unavailable = next(item for item in records if item["id"] == missing.parent.name)
        self.assertFalse(unavailable["available"])
        self.assertIn(last_review["id"], unavailable["assignment_ids"])
        self.assertEqual(len(records), len(paths))
        self.assertTrue(any(item["available"] for item in records))
        self.assertTrue(missing.parent.is_symlink())

    def archive_fixture(self):
        root = self.start_audit_fixture()
        _, active, _ = self.audit_export()
        public = self.store / "reports" / active["id"] / "public.json"
        self.mutate("interrupt", "--reason", "Stop fixture scheduling")
        self.mutate("retire", "--reason", "Fixture worker is gone",
                    "--shutdown-evidence", "No native worker was launched")
        exported = self.audit_cli("archive", "--pr", "first", "--public", str(public))
        return root, public, exported

    @pytest.mark.stable_storage
    def test_archive_publication_preserves_stopped_run_and_is_idempotent(self):
        root, _, exported = self.archive_fixture()
        before = (self.store / "RUN.json").read_bytes()
        fingerprint = self.review_cli(root, ["fingerprint"])
        args = ("publish-archive", "--pr", "first", "--approved", exported["identity"])
        with patch.object(audit, "api", self.audit_api):
            receipt = self.audit_cli(*args)
            wiki_head = self.git("ls-remote", str(self.wiki_remote), "HEAD")
            receipt_bytes = (Path(exported["directory"]) / "receipt.json").read_bytes()
            self.assertEqual(self.audit_cli(*args), receipt)
        self.assertEqual(receipt, json.loads(receipt_bytes))
        self.assertEqual((Path(exported["directory"]) / "receipt.json").read_bytes(), receipt_bytes)
        self.assertEqual(wiki_head, self.git("ls-remote", str(self.wiki_remote), "HEAD"))
        self.assertEqual(len(self.audit_body_updates), 1)
        self.assertEqual(before, (self.store / "RUN.json").read_bytes())
        self.assertEqual(fingerprint, self.review_cli(root, ["fingerprint"]))
        state = development.load(self.store)
        self.assertEqual(receipt["authorization"],
                         {"approval": state["approval"], "permission": "publish_audit"})
        self.assertIsNone(state["active"])
        self.assertEqual(state["outcome"], "blocked")
        with self.assertRaisesRegex(manifest.ManifestError, "Final audit is missing"):
            development.require_final_audit(state, "first", receipt["code_commit"], development.feature(root))
        self.git("fetch", str(self.wiki_remote), "docs", root=self.wiki)
        page = receipt["url"].rsplit("/", 1)[1]
        for name, published in (("audit.json", page + ".json"), ("AUDIT.md", page + ".md")):
            expected = (Path(exported["directory"]) / name).read_bytes()
            self.assertEqual(audit.command(["git", "show", f"FETCH_HEAD:{published}"], cwd=self.wiki), expected)
            self.assertNotIn(b"PRIVATE-AUDIT-SENTINEL", expected)
            self.assertNotIn(str(self.folder).encode(), expected)
        markdown = (Path(exported["directory"]) / "AUDIT.md").read_text()
        self.assertIn("Historical run outcome: `blocked`.", markdown)
        self.assertIn("This publication does not establish current PR review acceptance.", markdown)
        home = self.git("show", "FETCH_HEAD:Home.md", root=self.wiki)
        self.assertTrue(home.startswith("Existing wiki content\n"))
        self.assertEqual(home.count(receipt["index_url"]), 1)
        index = self.git("show", f"FETCH_HEAD:{audit.INDEX_PAGE}.md", root=self.wiki)
        self.assertEqual(index.count(receipt["pr_url"]), 1)
        self.assertIn(receipt["url"], index)

    @pytest.mark.stable_storage
    def test_archive_publication_also_works_with_active_and_exhausted_runs(self):
        self.start_audit_fixture()
        _, active, _ = self.audit_export()
        public = self.store / "reports" / active["id"] / "public.json"
        with patch.object(audit, "api", self.audit_api):
            for outcome in ("running", "failed"):
                with self.subTest(outcome=outcome):
                    self.assertEqual(development.load(self.store)["outcome"], outcome)
                    exported = self.audit_cli("archive", "--pr", "first", "--public", str(public))
                    before = (self.store / "RUN.json").read_bytes()
                    self.audit_cli("publish-archive", "--pr", "first", "--approved", exported["identity"])
                    self.assertEqual(before, (self.store / "RUN.json").read_bytes())
                if outcome == "running":
                    self.finish(outcome="blocked")
                    self.mutate("resume", "--reason", "Retry fixture audit")
                    self.next()
                    self.finish(outcome="blocked")
                    self.mutate("resume", "--reason", "Inspect exhausted fixture")
                    self.assertIsNone(self.next())

    def superseded_archive_fixture(self):
        self.start_audit_fixture()
        _, active, live = self.audit_export()
        public = self.store / "reports" / active["id"] / "public.json"
        archived = self.audit_cli("archive", "--pr", "first", "--public", str(public))
        args = ("publish-archive", "--pr", "first", "--approved", archived["identity"])
        with patch.object(audit, "api", self.audit_api):
            receipt = self.audit_cli(*args)
            newer = self.audit_cli("publish", "--approved", live["identity"])
        self.assertNotEqual(receipt["url"], newer["url"])
        self.assertIn(newer["url"], self.audit_body)
        return args, Path(archived["directory"]), receipt, newer

    @pytest.mark.stable_storage
    def test_archive_retry_acknowledges_history_without_replacing_newer_publication(self):
        args, folder, receipt, newer = self.superseded_archive_fixture()
        self.finish(newer)
        before = (self.store / "RUN.json").read_bytes()
        saved = (folder / "receipt.json").read_bytes()
        head = self.git("ls-remote", str(self.wiki_remote), "HEAD")
        updates = copy.deepcopy(self.audit_body_updates)
        attempt = (folder / "publication-attempt.json").read_bytes()
        self.assertEqual(development.load(self.store)["prs"]["first"]["accepted"]["head"], receipt["code_commit"])
        self.assertEqual(self.audit_api("repos/fixture/project/pulls/1")["head"]["sha"], receipt["code_commit"])
        with patch.object(audit, "api", side_effect=AssertionError("Historical acknowledgement contacted GitHub")), \
                patch.object(audit, "command", side_effect=AssertionError("Historical acknowledgement ran Git")):
            self.assertEqual(self.audit_cli(*args), receipt)
            self.assertIn("Archive evidence changed", self.audit_cli(*args, "--republish", ok=False))
        self.assertEqual((folder / "receipt.json").read_bytes(), saved)
        self.assertEqual((folder / "publication-attempt.json").read_bytes(), attempt)
        self.assertEqual((self.store / "RUN.json").read_bytes(), before)
        self.assertEqual(self.git("ls-remote", str(self.wiki_remote), "HEAD"), head)
        self.assertEqual(self.audit_body_updates, updates)
        self.assertIn(newer["url"], self.audit_body)

    @pytest.mark.stable_storage
    def test_archive_acknowledgement_validates_receipt_target_bytes_and_opt_outs(self):
        args, folder, receipt, _ = self.superseded_archive_fixture()
        path = folder / "receipt.json"
        saved = path.read_bytes()
        before = (self.store / "RUN.json").read_bytes()
        with patch.object(audit, "api", side_effect=AssertionError("Invalid acknowledgement contacted GitHub")):
            for field, value in (("bundle", "0" * 64), ("code_commit", "0" * 40),
                                 ("wiki_commit", "invalid"), ("pr_url", "https://github.com/fixture/project/pull/2"),
                                 ("authorization", {"approval": "0" * 64, "permission": "publish_audit"})):
                with self.subTest(field=field):
                    path.write_bytes(manifest.encode({**receipt, field: value}))
                    self.assertIn("receipt does not match", self.audit_cli(*args, ok=False))
            path.write_bytes(saved)
            self.assertIn("recorded PR target", self.audit_cli(
                *args, "--pull-request", "https://github.com/fixture/project/pull/2", ok=False))
            report = folder / "AUDIT.md"
            original = report.read_bytes()
            report.write_bytes(original + b"Changed")
            self.assertIn("exact exported files", self.audit_cli(*args, ok=False))
            report.write_bytes(original)
            config = Path(self.env["HOME"]) / ".claude/ioncache-ai-tools.local.json"
            config.write_text('{"features": {"autonomous-development-audit": false}}')
            self.assertIn("disabled", self.audit_cli(*args, ok=False))
            config.write_text('{"features": {}}')
            state = development.load(self.store)
            changed = copy.deepcopy(state)
            changed["manifest"]["permissions"]["publish_audit"] = False
            changed["approval"] = manifest.digest(manifest.encode(changed["manifest"]))
            (self.store / "MANIFEST.json").write_bytes(manifest.encode(changed["manifest"]))
            (self.store / "RUN.json").write_bytes(manifest.encode(changed))
            self.assertIn("approved", self.audit_cli(*args, ok=False))
            (self.store / "RUN.json").write_bytes(before)
            (self.store / "MANIFEST.json").write_bytes(manifest.encode(state["manifest"]))
            self.assertIn("--republish is supported only", self.audit_cli("export", "--republish", ok=False))
            self.assertEqual(self.audit_cli(*args), receipt)
        self.assertEqual(path.read_bytes(), saved)
        self.assertEqual((self.store / "RUN.json").read_bytes(), before)
        self.assertEqual(len(self.audit_body_updates), 2)

    @pytest.mark.stable_storage
    def test_missing_archive_receipt_preserves_newer_links_until_explicit_republication(self):
        args, folder, receipt, newer = self.superseded_archive_fixture()
        (folder / "receipt.json").unlink()
        attempt = (folder / "publication-attempt.json").read_bytes()
        head = self.git("ls-remote", str(self.wiki_remote), "HEAD")
        before = (self.store / "RUN.json").read_bytes()
        with patch.object(audit, "api", self.audit_api):
            for legacy in (False, True):
                with self.subTest(legacy=legacy):
                    if legacy:
                        (folder / "publication-attempt.json").unlink()
                    self.assertIn("partial or superseded", self.audit_cli(*args, ok=False))
                    self.assertFalse((folder / "receipt.json").exists())
                    self.assertIn(newer["url"], self.audit_body)
                    self.assertEqual(self.git("ls-remote", str(self.wiki_remote), "HEAD"), head)
                    self.assertEqual(len(self.audit_body_updates), 2)
            (folder / "publication-attempt.json").write_bytes(attempt)
            restored = self.audit_cli(*args, "--republish")
            self.assertEqual(restored["url"], receipt["url"])
            self.assertNotEqual(restored["wiki_commit"], receipt["wiki_commit"])
            self.assertIn(receipt["url"], self.audit_body)
            self.assertEqual(self.audit_cli(*args), restored)
        self.assertEqual(len(self.audit_body_updates), 3)
        self.assertEqual((self.store / "RUN.json").read_bytes(), before)

    @pytest.mark.stable_storage
    def test_archive_retry_preserves_changed_wiki_row_even_when_pr_links_still_match(self):
        args, folder, receipt, newer = self.superseded_archive_fixture()
        (folder / "receipt.json").unlink()
        self.audit_body = audit.pr_body(self.audit_body, receipt)
        head = self.git("ls-remote", str(self.wiki_remote), "HEAD")
        with patch.object(audit, "api", self.audit_api):
            self.assertIn("partial or superseded", self.audit_cli(*args, ok=False))
        self.assertEqual(head, self.git("ls-remote", str(self.wiki_remote), "HEAD"))
        self.assertEqual(len(self.audit_body_updates), 2)
        self.git("fetch", str(self.wiki_remote), "docs", root=self.wiki)
        self.assertIn(newer["url"], self.git("show", f"FETCH_HEAD:{audit.INDEX_PAGE}.md", root=self.wiki))

    @pytest.mark.stable_storage
    def test_archive_attempt_is_durable_before_remote_writes_and_validated_on_retry(self):
        _, _, exported = self.archive_fixture()
        folder = Path(exported["directory"])
        path = folder / "publication-attempt.json"
        args = ("publish-archive", "--pr", "first", "--approved", exported["identity"])
        original_write = audit.review.atomic_write

        def unavailable_attempt(target, data):
            if target == path:
                raise OSError("Attempt storage unavailable")
            return original_write(target, data)

        with patch.object(audit, "api", self.audit_api), \
                patch.object(audit.review, "atomic_write", side_effect=unavailable_attempt):
            self.assertIn("Attempt storage unavailable", self.audit_cli(*args, ok=False))
        self.assertIn(self.wiki_initial, self.git("ls-remote", str(self.wiki_remote), "HEAD"))
        self.assertEqual(self.audit_body_updates, [])
        with patch.object(audit, "api", side_effect=AssertionError("Invalid attempt contacted GitHub")):
            for record in (None, {}, {"bundle": "0" * 64, "pr_url": "wrong", "approval": "wrong",
                                      "before": {"pr": "0" * 64, "wiki": "0" * 64}}):
                path.write_bytes(manifest.encode(record))
                self.audit_cli(*args, ok=False)
        with patch.object(audit, "api", self.audit_api):
            receipt = self.audit_cli(*args, "--republish")
        self.assertEqual(receipt, json.loads((folder / "receipt.json").read_bytes()))
        self.assertEqual(len(self.audit_body_updates), 1)

    @pytest.mark.stable_storage
    def test_archive_recovers_matching_legacy_publication_without_local_records(self):
        _, _, exported = self.archive_fixture()
        args = ("publish-archive", "--pr", "first", "--approved", exported["identity"])
        folder = Path(exported["directory"])
        before = (self.store / "RUN.json").read_bytes()
        with patch.object(audit, "api", self.audit_api):
            receipt = self.audit_cli(*args)
            head = self.git("ls-remote", str(self.wiki_remote), "HEAD")
            body = self.audit_body
            (folder / "receipt.json").unlink()
            (folder / "publication-attempt.json").unlink()
            recovered = self.audit_cli(*args)
        self.assertEqual(recovered, receipt)
        self.assertEqual(json.loads((folder / "receipt.json").read_bytes()), receipt)
        self.assertTrue((folder / "publication-attempt.json").is_file())
        self.assertEqual(self.git("ls-remote", str(self.wiki_remote), "HEAD"), head)
        self.assertEqual(self.audit_body, body)
        self.assertEqual(len(self.audit_body_updates), 1)
        with patch.object(audit, "api", side_effect=AssertionError("Acknowledgement contacted GitHub")), \
                patch.object(audit, "command", side_effect=AssertionError("Acknowledgement ran Git")):
            self.assertEqual(self.audit_cli(*args), receipt)
        self.assertEqual((self.store / "RUN.json").read_bytes(), before)

    @pytest.mark.stable_storage
    def test_archive_retry_preserves_unrelated_navigation_edits_with_a_saved_attempt(self):
        _, _, exported = self.archive_fixture()
        args = ("publish-archive", "--pr", "first", "--approved", exported["identity"])
        folder = Path(exported["directory"])
        before = (self.store / "RUN.json").read_bytes()
        original = audit.command

        def unavailable_push(argv, **kwargs):
            if argv[1] == "push":
                raise OSError("Publication push unavailable")
            return original(argv, **kwargs)

        with patch.object(audit, "api", self.audit_api), \
                patch.object(audit, "command", side_effect=unavailable_push):
            self.assertIn("Publication push unavailable", self.audit_cli(*args, ok=False))
        attempt = (folder / "publication-attempt.json").read_bytes()
        self.assertFalse((folder / "receipt.json").exists())
        self.assertEqual(self.audit_body_updates, [])
        self.assertIn(self.wiki_initial, self.git("ls-remote", str(self.wiki_remote), "HEAD"))
        body = self.audit_body + "\nUnrelated PR notes.\n"
        self.audit_body = body
        other_row = "| 2026-01-01 | [#9 Other PR](https://github.com/fixture/project/pull/9) | Other audit |\n"
        index = f"Human introduction\n\n{audit.INDEX_HEADER}\n{audit.INDEX_SEPARATOR}\n{other_row}\nHuman footer\n"
        (self.wiki / (audit.INDEX_PAGE + ".md")).write_text(index)
        self.git("add", ".", root=self.wiki)
        self.git("commit", "-qm", "Unrelated navigation edits", root=self.wiki)
        self.git("push", str(self.wiki_remote), "HEAD:refs/heads/docs", root=self.wiki)
        with patch.object(audit, "api", self.audit_api):
            receipt = self.audit_cli(*args)
        self.assertEqual((folder / "publication-attempt.json").read_bytes(), attempt)
        self.assertEqual(json.loads((folder / "receipt.json").read_bytes()), receipt)
        self.assertEqual(len(self.audit_body_updates), 1)
        block = f"\n\n## Audit\n\n{audit.LINK_START}\n{audit.audit_links(receipt)}\n{audit.LINK_END}\n\n"
        self.assertEqual(self.audit_body.replace(block, "", 1), body)
        self.git("fetch", str(self.wiki_remote), "docs", root=self.wiki)
        published = audit.command(["git", "show", f"FETCH_HEAD:{audit.INDEX_PAGE}.md"], cwd=self.wiki).decode()
        own_row = next(line for line in published.splitlines(keepends=True)
                       if "](https://github.com/fixture/project/pull/1)" in line)
        self.assertEqual(published.replace(own_row, "", 1), index)
        self.assertIn(receipt["url"], own_row)
        self.assertEqual((self.store / "RUN.json").read_bytes(), before)

    def archive_contention_fixture(self, *, superseded):
        _, _, exported = self.archive_fixture()
        state = development.load(self.store)
        publication = audit.publication_links(state, audit.archive_assignment(state, "first"), "0" * 64)
        if not superseded:
            publication = {key: value.replace("/pull/1", "/pull/9").replace("Audit-PR-1-", "Audit-PR-9-")
                           for key, value in publication.items()}
        index = audit.index_entry(f"{audit.INDEX_HEADER}\n{audit.INDEX_SEPARATOR}\n",
                                  {**publication, "title": "Concurrent audit"})
        original = audit.command
        pushes = 0
        raced_head = None

        def concurrent_update(argv, **kwargs):
            nonlocal pushes, raced_head
            if argv[1] == "push":
                pushes += 1
                if pushes == 1:
                    (self.wiki / (audit.INDEX_PAGE + ".md")).write_text(index)
                    self.git("add", ".", root=self.wiki)
                    self.git("commit", "-qm", "Concurrent archive navigation", root=self.wiki)
                    self.git("push", str(self.wiki_remote), "HEAD:refs/heads/docs", root=self.wiki)
                    raced_head = self.git("rev-parse", "HEAD", root=self.wiki)
            return original(argv, **kwargs)

        before = (self.store / "RUN.json").read_bytes()
        body = self.audit_body
        with patch.object(audit, "api", self.audit_api), \
                patch.object(audit, "command", side_effect=concurrent_update):
            result = self.audit_cli("publish-archive", "--pr", "first", "--approved", exported["identity"],
                                    ok=not superseded)
        self.assertEqual((self.store / "RUN.json").read_bytes(), before)
        self.git("fetch", str(self.wiki_remote), "docs", root=self.wiki)
        return {"result": result, "pushes": pushes, "raced_head": raced_head, "index": index,
                "body": body, "folder": Path(exported["directory"])}

    @pytest.mark.stable_storage
    def test_archive_refetch_preserves_newer_own_navigation(self):
        raced = self.archive_contention_fixture(superseded=True)
        self.assertIn("partial or superseded", raced["result"])
        self.assertEqual(raced["pushes"], 1)
        self.assertEqual(self.git("rev-parse", "FETCH_HEAD", root=self.wiki), raced["raced_head"])
        self.assertEqual(audit.command(["git", "show", f"FETCH_HEAD:{audit.INDEX_PAGE}.md"], cwd=self.wiki),
                         raced["index"].encode())
        self.assertEqual(self.audit_body, raced["body"])
        self.assertEqual(self.audit_body_updates, [])
        self.assertFalse((raced["folder"] / "receipt.json").exists())

    @pytest.mark.stable_storage
    def test_archive_refetch_preserves_other_pr_navigation_and_completes(self):
        raced = self.archive_contention_fixture(superseded=False)
        receipt = raced["result"]
        self.assertEqual(raced["pushes"], 2)
        self.assertNotEqual(receipt["wiki_commit"], raced["raced_head"])
        self.assertEqual(self.git("rev-parse", "FETCH_HEAD", root=self.wiki), receipt["wiki_commit"])
        published = audit.command(["git", "show", f"FETCH_HEAD:{audit.INDEX_PAGE}.md"], cwd=self.wiki).decode()
        own_row = next(line for line in published.splitlines(keepends=True)
                       if "](https://github.com/fixture/project/pull/1)" in line)
        self.assertEqual(published.replace(own_row, "", 1), raced["index"])
        self.assertIn(receipt["url"], own_row)
        self.assertEqual(len(self.audit_body_updates), 1)
        self.assertIn(receipt["url"], self.audit_body)
        self.assertEqual(json.loads((raced["folder"] / "receipt.json").read_bytes()), receipt)

    @pytest.mark.stable_storage
    def test_archive_rechecks_pr_navigation_after_wiki_publication(self):
        _, _, exported = self.archive_fixture()
        args = ("publish-archive", "--pr", "first", "--approved", exported["identity"])
        state = development.load(self.store)
        newer = audit.publication_links(state, audit.archive_assignment(state, "first"), "0" * 64)
        reads = 0

        def changed_navigation(endpoint, **kwargs):
            nonlocal reads
            if not kwargs:
                reads += 1
                if reads == 2:
                    self.audit_body = audit.pr_body(self.audit_body, newer)
            return self.audit_api(endpoint, **kwargs)

        with patch.object(audit, "api", changed_navigation):
            self.assertIn("partial or superseded", self.audit_cli(*args, ok=False))
        self.assertEqual(self.audit_body_updates, [])
        self.assertIn(newer["url"], self.audit_body)
        self.assertFalse((Path(exported["directory"]) / "receipt.json").exists())
        head = self.git("ls-remote", str(self.wiki_remote), "HEAD")
        with patch.object(audit, "api", self.audit_api):
            self.assertIn("partial or superseded", self.audit_cli(*args, ok=False))
            receipt = self.audit_cli(*args, "--republish")
        self.assertEqual(head, self.git("ls-remote", str(self.wiki_remote), "HEAD"))
        self.assertEqual(len(self.audit_body_updates), 1)
        self.assertIn(receipt["url"], self.audit_body)

    @pytest.mark.stable_storage
    def test_archive_requires_committing_full_pr_review_fixes(self):
        root = self.start_audit_fixture()
        _, active, _ = self.audit_export()
        public = self.store / "reports" / active["id"] / "public.json"
        self.execute_fixture(self.state["assignment"])
        reviewed = self.next()
        self.assertEqual((reviewed["role"], reviewed["task"]), ("review", None))
        (root / "app.txt").write_text("Full-PR review correction\n")
        self.review(root)
        old_head = self.git("rev-parse", "HEAD", root=root)
        self.assertEqual(self.next()["role"], "commit")
        self.mutate("interrupt", "--reason", "Commit handoff interrupted")
        self.mutate("retire", "--reason", "Fixture worker stopped",
                    "--shutdown-evidence", "No native worker was launched")
        exported = self.audit_cli("archive", "--pr", "first", "--public", str(public))
        before = (self.store / "RUN.json").read_bytes()
        wiki_head = self.git("ls-remote", str(self.wiki_remote), "HEAD")
        updates = len(self.audit_body_updates)
        with patch.object(audit, "api", side_effect=AssertionError("Uncommitted review was published")):
            for _ in range(2):
                self.assertIn("No accepted code commit", self.audit_cli(
                    "publish-archive", "--pr", "first", "--approved", exported["identity"], ok=False))
        self.assertEqual(before, (self.store / "RUN.json").read_bytes())
        self.assertEqual(wiki_head, self.git("ls-remote", str(self.wiki_remote), "HEAD"))
        self.assertEqual(len(self.audit_body_updates), updates)
        self.assertFalse((Path(exported["directory"]) / "receipt.json").exists())
        self.git("stash", "push", "-m", "Retain accepted review correction", root=root)
        new_base = self.advance_rebase_target(root)
        self.git("stash", "pop", root=root)
        self.mutate("rebase-review", "--pr", "first", "--new-base", new_base,
                    "--reason", "Replay the accepted review before its commit handoff")
        rebased = self.audit_cli("archive", "--pr", "first", "--public", str(public))
        with patch.object(audit, "api", side_effect=AssertionError("Uncommitted rebased review was published")):
            self.assertIn("No accepted code commit", self.audit_cli(
                "publish-archive", "--pr", "first", "--approved", rebased["identity"], ok=False))
        before_commit = self.git("rev-parse", "HEAD", root=root)
        assignment = self.next()
        self.assertEqual(assignment["role"], "commit")
        self.execute_fixture(assignment)
        head = self.git("rev-parse", "HEAD", root=root)
        self.assertNotEqual(head, before_commit)
        self.assertNotEqual(head, old_head)
        refreshed = self.audit_cli("archive", "--pr", "first", "--public", str(public))

        def committed_pull(endpoint, **kwargs):
            pull = self.audit_api(endpoint, **kwargs)
            pull["head"]["sha"] = head
            return pull

        with patch.object(audit, "api", committed_pull):
            receipt = self.audit_cli("publish-archive", "--pr", "first", "--approved", refreshed["identity"])
        self.assertEqual(receipt["code_commit"], self.git("rev-parse", "HEAD", root=root))
        self.assertEqual(len(self.audit_body_updates), updates + 1)

    @pytest.mark.stable_storage
    def test_archive_publication_rejects_changed_pr_head(self):
        root, public, exported = self.archive_fixture()
        accepted = json.loads((Path(exported["directory"]) / "audit.json").read_bytes())["code_commit"]
        (root / "app.txt").write_text("Unreviewed later change\n")
        self.git("add", "app.txt", root=root)
        self.git("commit", "-qm", "Later implementation", root=root)
        self.git("push", "origin", "HEAD:refs/heads/fixture-feature", root=root)
        head = self.git("rev-parse", "HEAD", root=root)
        self.assertNotEqual(head, accepted)
        before = (self.store / "RUN.json").read_bytes()
        with patch.object(audit, "api", self.audit_api):
            error = self.audit_cli("publish-archive", "--pr", "first",
                                   "--approved", exported["identity"], ok=False)
        self.assertIn(head, error)
        self.assertIn(accepted, error)
        self.assertIn("Reconcile the review", error)
        self.assertIn(self.wiki_initial, self.git("ls-remote", str(self.wiki_remote), "HEAD"))
        self.assertEqual(self.audit_body_updates, [])
        self.assertFalse((Path(exported["directory"]) / "receipt.json").exists())
        self.assertEqual(before, (self.store / "RUN.json").read_bytes())
        self.mutate("reconcile", "--pr", "first", "--reason", "Review the later change")
        unaccepted = self.audit_cli("archive", "--pr", "first", "--public", str(public))
        with patch.object(audit, "api", side_effect=AssertionError("Unaccepted commit published")):
            self.assertIn("No accepted code commit", self.audit_cli(
                "publish-archive", "--pr", "first", "--approved", unaccepted["identity"], ok=False))
        self.assertEqual(self.next()["role"], "review")
        self.review(root)
        while self.next()["role"] != "audit-initial":
            self.execute_fixture(self.state["assignment"])
        refreshed = self.audit_cli("archive", "--pr", "first", "--public", str(public))
        with patch.object(audit, "api", self.audit_api):
            receipt = self.audit_cli("publish-archive", "--pr", "first", "--approved", refreshed["identity"])
        self.assertEqual(receipt["code_commit"], head)
        self.assertEqual(len(self.audit_body_updates), 1)

    @pytest.mark.stable_storage
    def test_archive_after_rebase_uses_accepted_snapshot_without_new_assignment(self):
        root, public, exported = self.archive_fixture()
        before = development.load(self.store)
        new_base = self.advance_rebase_target(root)
        rebased_head = self.git("rev-parse", "HEAD", root=root)

        def rebased_pull(endpoint, **kwargs):
            pull = self.audit_api(endpoint, **kwargs)
            pull["head"]["sha"] = rebased_head
            return pull

        with patch.object(audit, "api", rebased_pull):
            self.assertIn("differs from", self.audit_cli(
                "publish-archive", "--pr", "first", "--approved", exported["identity"], ok=False))
            self.mutate("rebase-review", "--pr", "first", "--new-base", new_base,
                        "--reason", "Verified unchanged target rebase")
            self.assertEqual(len(development.load(self.store)["history"]), len(before["history"]))
            refreshed = self.audit_cli("archive", "--pr", "first", "--public", str(public))
            state_bytes = (self.store / "RUN.json").read_bytes()
            self.git("worktree", "remove", str(root))
            self.assertFalse(root.exists())
            original_command = audit.command

            def unavailable_commit(arguments, **kwargs):
                if arguments == ["git", "--no-replace-objects", "rev-parse", "--verify", "--end-of-options",
                                 rebased_head + "^{tree}"]:
                    raise manifest.ManifestError("Fixture commit object unavailable")
                return original_command(arguments, **kwargs)

            with patch.object(audit, "command", side_effect=unavailable_commit):
                local = self.audit_cli("archive", "--pr", "first", "--public", str(public))
                bundle = json.loads((Path(local["directory"]) / "audit.json").read_bytes())
                self.assertIsNone(bundle["accepted_code_commit"])
                for _ in range(2):
                    self.assertIn("Rebase commit evidence is unavailable", self.audit_cli(
                        "publish-archive", "--pr", "first", "--approved", refreshed["identity"], ok=False))
                self.assertEqual(self.audit_body_updates, [])
                self.assertFalse((Path(refreshed["directory"]) / "receipt.json").exists())
            receipt = self.audit_cli("publish-archive", "--pr", "first", "--approved", refreshed["identity"])
        self.assertEqual(receipt["code_commit"], rebased_head)
        self.assertEqual(state_bytes, (self.store / "RUN.json").read_bytes())
        bundle = json.loads((Path(refreshed["directory"]) / "audit.json").read_bytes())
        self.assertEqual(bundle["accepted_code_commit"], rebased_head)
        self.assertEqual(bundle["snapshot"], audit.identity(development.load(self.store)["prs"]["first"]["accepted"]))

    @pytest.mark.stable_storage
    def test_archive_publication_refuses_wrong_targets_and_closed_prs(self):
        _, _, exported = self.archive_fixture()
        args = ("publish-archive", "--pr", "first", "--approved", exported["identity"])
        for field in ("state", "head_repo", "base_repo", "branch", "url", "deleted_head"):
            with self.subTest(field=field):
                def wrong_pull(endpoint, **kwargs):
                    pull = self.audit_api(endpoint, **kwargs)
                    if field == "state":
                        pull["state"] = "closed"
                    elif field in ("head_repo", "base_repo"):
                        pull[field.split("_")[0]]["repo"]["full_name"] = "fixture/other"
                    elif field == "branch":
                        pull["head"]["ref"] = "other-branch"
                    elif field == "url":
                        pull["html_url"] = "https://github.com/fixture/other/pull/1"
                    else:
                        pull["head"]["repo"] = None
                    return pull

                with patch.object(audit, "api", wrong_pull), \
                        patch.object(audit, "publish_files", side_effect=AssertionError("Wrong target published")):
                    self.audit_cli(*args, ok=False)
        with patch.object(audit, "api", side_effect=AssertionError("Unapproved PR requested")):
            for url in ("https://github.com/fixture/other/pull/1", "https://github.com/fixture/project/pull/2"):
                self.audit_cli(*args, "--pull-request", url, ok=False)
        self.assertFalse((Path(exported["directory"]) / "receipt.json").exists())

    @pytest.mark.stable_storage
    def test_archive_publication_uses_explicit_pr_after_lost_draft_report(self):
        _, _, exported = self.archive_fixture()
        state = development.load(self.store)
        state["prs"]["first"]["url"] = None
        development.save(self.store, state)
        before = (self.store / "RUN.json").read_bytes()
        args = ("publish-archive", "--pr", "first", "--approved", exported["identity"])
        with patch.object(audit, "api", self.audit_api):
            self.assertIn("--pull-request", self.audit_cli(*args, ok=False))
            receipt = self.audit_cli(*args, "--pull-request", "https://github.com/Fixture/Project/pull/1")
        self.assertEqual(receipt["pr_url"], "https://github.com/fixture/project/pull/1")
        self.assertEqual(before, (self.store / "RUN.json").read_bytes())

    @pytest.mark.stable_storage
    def test_archive_publication_checks_bytes_evidence_and_receipt_paths_before_remote_writes(self):
        _, public, exported = self.archive_fixture()
        folder = Path(exported["directory"])
        args = ("publish-archive", "--pr", "first", "--approved", exported["identity"])
        with patch.object(audit, "api", side_effect=AssertionError("Unchecked archive published")):
            for name in audit.FILES:
                original = (folder / name).read_bytes()
                (folder / name).write_bytes(original + b" ")
                self.assertIn("exact exported files", self.audit_cli(*args, ok=False))
                (folder / name).write_bytes(original)
            receipt = folder / "receipt.json"
            receipt.symlink_to(self.folder / "unrelated-receipt")
            self.assertIn("Symlink not allowed", self.audit_cli(*args, ok=False))
            receipt.unlink()
            self.mutate("resume", "--reason", "Resume independently of archival publication")
            self.assertIn("Archive evidence changed", self.audit_cli(*args, ok=False))
        refreshed = self.audit_cli("archive", "--pr", "first", "--public", str(public))
        with patch.object(audit, "api", self.audit_api):
            self.audit_cli("publish-archive", "--pr", "first", "--approved", refreshed["identity"])

    @pytest.mark.stable_storage
    def test_archive_publication_retains_authorization_and_opt_outs(self):
        _, _, exported = self.archive_fixture()
        args = ("publish-archive", "--pr", "first", "--approved", exported["identity"])
        config = Path(self.env["HOME"]) / ".claude/ioncache-ai-tools.local.json"
        before = (self.store / "RUN.json").read_bytes()
        with patch.object(audit, "api", side_effect=AssertionError("Unauthorized publication")):
            for setting in ("autonomous-development-audit", "autonomous-development",
                            "skill:autonomous-development"):
                config.write_text(json.dumps({"features": {setting: False}}))
                self.assertIn("disabled", self.audit_cli(*args, ok=False))
            config.write_text("{invalid")
            self.assertIn("disabled", self.audit_cli(*args, ok=False))
            config.write_text('{"features": {}}')
            state = development.load(self.store)
            for permission in ("publish_audit", "push", "create_pr"):
                changed = copy.deepcopy(state)
                changed["manifest"]["permissions"][permission] = False
                changed["approval"] = manifest.digest(manifest.encode(changed["manifest"]))
                (self.store / "MANIFEST.json").write_bytes(manifest.encode(changed["manifest"]))
                (self.store / "RUN.json").write_bytes(manifest.encode(changed))
                self.assertIn("approved", self.audit_cli(*args, ok=False))
            (self.store / "RUN.json").write_bytes(before)
            (self.store / "MANIFEST.json").write_bytes(manifest.encode(state["manifest"]))
        with patch.object(audit, "api", self.audit_api):
            self.audit_cli(*args)
        self.assertEqual(before, (self.store / "RUN.json").read_bytes())

    @pytest.mark.stable_storage
    def test_archive_publication_requires_restored_approved_inputs(self):
        _, _, exported = self.archive_fixture()
        args = ("publish-archive", "--pr", "first", "--approved", exported["identity"])
        snapshot = self.store / "inputs/design.md"
        original = snapshot.read_bytes()
        before = (self.store / "RUN.json").read_bytes()
        for missing in (True, False):
            with self.subTest(missing=missing), \
                    patch.object(audit, "api", side_effect=AssertionError("Invalid inputs reached publication")):
                if missing:
                    snapshot.unlink()
                else:
                    snapshot.write_bytes(b"Unapproved input\n")
                for _ in range(2):
                    error = self.audit_cli(*args, ok=False)
                    self.assertIn("regular file" if missing else "Artifact changed", error)
                    self.assertEqual(before, (self.store / "RUN.json").read_bytes())
                    self.assertFalse((Path(exported["directory"]) / "receipt.json").exists())
                snapshot.write_bytes(original)
        self.assertIn(self.wiki_initial, self.git("ls-remote", str(self.wiki_remote), "HEAD"))
        self.assertEqual(self.audit_body_updates, [])
        with patch.object(audit, "api", self.audit_api):
            self.audit_cli(*args)
        self.assertEqual(before, (self.store / "RUN.json").read_bytes())
        self.assertEqual(len(self.audit_body_updates), 1)

    @pytest.mark.stable_storage
    def test_archive_publication_freezes_model_observations_across_retries(self):
        _, public, _ = self.archive_fixture()
        assignment = development.load(self.store)["history"][-1]
        observation = ("model-report", self.store, "--invocation", "archive-observations", "--call", "1",
                       "--role", assignment["role"], "--assignment", assignment["id"],
                       "--selected-model", "requested-audit", "--source", "native-context")
        self.cli(*observation, "--actual-model", "initial-observation")
        exported = self.audit_cli("archive", "--pr", "first", "--public", str(public))
        folder = Path(exported["directory"])
        files = {name: (folder / name).read_bytes() for name in audit.FILES}
        self.assertEqual(json.loads(files["audit.json"])["models"][0]["actual_model"], "initial-observation")
        before = (self.store / "RUN.json").read_bytes()
        self.cli(*observation, "--actual-model", "later-observation")
        args = ("publish-archive", "--pr", "first", "--approved", exported["identity"])
        with patch.object(audit, "api", self.audit_api):
            receipt = self.audit_cli(*args)
            wiki_head = self.git("ls-remote", str(self.wiki_remote), "HEAD")
            self.cli("model-report", self.store, "--invocation", "archive-observations", "--call", "2",
                     "--role", "development-control", "--actual-model", "observed-control",
                     "--source", "native-context")
            self.assertEqual(self.audit_cli(*args), receipt)
        records, unavailable = models.observations(development.load(self.store), "first")
        self.assertFalse(unavailable)
        self.assertEqual({item["actual_model"] for item in records}, {"later-observation", "observed-control"})
        self.assertEqual(files, {name: (folder / name).read_bytes() for name in audit.FILES})
        self.assertEqual(before, (self.store / "RUN.json").read_bytes())
        self.assertEqual(wiki_head, self.git("ls-remote", str(self.wiki_remote), "HEAD"))
        self.assertEqual(len(self.audit_body_updates), 1)

    @pytest.mark.stable_storage
    def test_archive_receipt_requires_confirmation_and_recovers_lost_response(self):
        _, _, exported = self.archive_fixture()
        args = ("publish-archive", "--pr", "first", "--approved", exported["identity"])
        receipt_path = Path(exported["directory"]) / "receipt.json"
        reads = 0

        def unconfirmed(endpoint, **kwargs):
            nonlocal reads
            pull = self.audit_api(endpoint, **kwargs)
            if not kwargs:
                reads += 1
                if reads == 3:
                    pull["body"] = "Unconfirmed body"
            return pull

        before = (self.store / "RUN.json").read_bytes()
        with patch.object(audit, "api", unconfirmed):
            self.assertIn("not confirmed", self.audit_cli(*args, ok=False))
        self.assertFalse(receipt_path.exists())
        wiki_head = self.git("ls-remote", str(self.wiki_remote), "HEAD")
        original_write = audit.review.atomic_write

        def lost_receipt(path, data):
            if path == receipt_path:
                raise OSError("Receipt storage unavailable")
            return original_write(path, data)

        with patch.object(audit, "api", self.audit_api):
            with patch.object(audit.review, "atomic_write", side_effect=lost_receipt):
                self.assertIn("Receipt storage unavailable", self.audit_cli(*args, ok=False))
            self.assertFalse(receipt_path.exists())
            receipt = self.audit_cli(*args)
        self.assertEqual(receipt, json.loads(receipt_path.read_bytes()))
        self.assertEqual(len(self.audit_body_updates), 1)
        self.assertEqual(wiki_head, self.git("ls-remote", str(self.wiki_remote), "HEAD"))
        self.assertEqual(before, (self.store / "RUN.json").read_bytes())

    @pytest.mark.stable_storage
    def test_archive_refuses_pr_head_drift_during_publication(self):
        _, _, exported = self.archive_fixture()
        args = ("publish-archive", "--pr", "first", "--approved", exported["identity"])
        original_body = self.audit_body
        for changed_read in (2, 3):
            reads = 0

            def changing_pull(endpoint, **kwargs):
                nonlocal reads
                pull = self.audit_api(endpoint, **kwargs)
                if not kwargs:
                    reads += 1
                    if reads == changed_read:
                        pull["head"]["sha"] = "0" * 40
                return pull

            with self.subTest(changed_read=changed_read), patch.object(audit, "api", changing_pull):
                self.assertIn("differs from", self.audit_cli(*args, ok=False))
                self.assertFalse((Path(exported["directory"]) / "receipt.json").exists())
                if changed_read == 2:
                    self.assertEqual(self.audit_body, original_body)
                    self.assertEqual(self.audit_body_updates, [])
                else:
                    self.assertNotEqual(self.audit_body, original_body)
                    self.assertEqual(len(self.audit_body_updates), 1)
        with patch.object(audit, "api", self.audit_api):
            self.audit_cli(*args)
        self.assertEqual(len(self.audit_body_updates), 1)

    def test_wiki_home_preserves_content_and_existing_links(self):
        url = "https://github.com/fixture/project/wiki/" + audit.INDEX_PAGE
        for original in ("", "Human notes", "# Home\r\n\r\nHuman notes\r\n",
                         "```md\r\nExample\r\n```\r\n", "~~~\r\nExample\r\n~~~~\r\n",
                         "```md\nExample\n````\n", "```\n<!--\n```\n",
                         "<!--\n```\n-->\n", "`<!--` is literal code\n"):
            with self.subTest(original=original):
                updated = audit.home_page(original, url)
                self.assertTrue(updated.startswith(original))
                self.assertEqual(updated.count(url), 1)
                self.assertIn(audit.HOME_START, updated)
                self.assertEqual(audit.home_page(updated, url), updated)
        for link in (f"[Audit index]({url})", f"[Audits]({audit.INDEX_PAGE})",
                     f'[{audit.INDEX_PAGE}](<{url}#records> "Audit records")',
                     f"[Audits]({audit.INDEX_PAGE} 'Audit records')",
                     f"[Audits]({audit.INDEX_PAGE} (Audit records))",
                     f'''[Audits]({audit.INDEX_PAGE} 'Audit \\'records\\'')''',
                     f"[Audits]({audit.INDEX_PAGE} (Audit \\(records\\)))",
                     "\\\\" + f"[Audits]({url})", "\\!" + f"[Audits]({url})",
                     f"[Audits]({url.replace('fixture/project', 'Fixture/Project')})",
                     f"[[{audit.INDEX_PAGE}|Audits]]",
                     f'[Audits][index]\n\n[index]: <{url}> "Audit records"',
                     f"[Audits][]\n\n[Audits]: {url}",
                     f"[Audit index]\n\n[audit INDEX]:\n  {url}",
                     f"[Audit index]\n\n[audit index]:\n      {url}",
                     f"# Audits\n[index]: {audit.INDEX_PAGE}\n\n[Audits][index]",
                     f"[Audits][index]\n\n[other]: Another-page\n[index]: {audit.INDEX_PAGE}",
                     f"[Audits][index]\r\n\r\n[index]: {url}\r\n"):
            original = "# Home\n\n## Audits\n\n" + link + "\n\nHuman footer\n"
            self.assertEqual(audit.home_page(original, url), original)
            self.assertEqual(audit.home_page(audit.home_page(original, url), url), original)
        managed = audit.home_page("Human notes\n", url)
        for invalid in (managed + audit.HOME_START, managed.replace(audit.HOME_END, ""),
                        managed.replace(audit.HOME_END, "Human note\n" + audit.HOME_END)):
            with self.assertRaisesRegex(manifest.ManifestError, "Preserve|preserve"):
                audit.home_page(invalid, url)
        for example in ("```\n" + managed + "```\n", f"```md\n{audit.HOME_START}\n```\n",
                        f"~~~\r\n{audit.HOME_END}\r\n~~~~\r\n", f"`{audit.HOME_START}`\n",
                        f"    {audit.HOME_START}\n"):
            with self.subTest(example=example):
                updated = audit.home_page(example, url)
                self.assertTrue(updated.startswith(example))
                self.assertEqual(updated[len(example):].count(url), 1)
                self.assertEqual(audit.home_page(updated, url), updated)
                self.assertEqual(audit.home_page(managed + example, url), managed + example)
        for unfinished in ("```markdown\nUnfinished code block", "<!-- Unfinished comment",
                           "````\nExample\n```\n", "~~~\r\nExample\r\n~~\r\n"):
            with self.subTest(unfinished=unfinished), self.assertRaisesRegex(manifest.ManifestError, "unfinished"):
                audit.home_page(unfinished, url)
        unrelated = f"[Other wiki](https://github.com/fixture/other/wiki/{audit.INDEX_PAGE})"
        self.assertIn(audit.HOME_START, audit.home_page(unrelated, url))
        link = f"[Audits]({url})"
        for hidden in (f"<!-- {link} -->", f"`{link}`", f"```md\n{link}\n```",
                       f"~~~\n{link}\n~~~", f"    {link}", f"![Image]({url})",
                       "\\" + link, "\\\\\\" + link, "\\\\" + f"![Image]({url})",
                       "\\" + f"[[{audit.INDEX_PAGE}]]",
                       f"[[Another-page|{audit.INDEX_PAGE}]]",
                       f"[Audits][index]\n\n[index]: Other-page",
                       f"[index]: {url}",
                       f"![Image][index]\n\n[index]: {url}",
                       f"[Audits][index]\n[index]: {audit.INDEX_PAGE}",
                       f"[Audits][index]\n\n```\n[index]: {url}\n```",
                       f"[Audits][index]\n\n[index]: Other-page\n[index]: {url}"):
            with self.subTest(hidden=hidden):
                self.assertIn(audit.HOME_START, audit.home_page(hidden, url))

    def test_wiki_home_rescans_links_inside_escaped_outer_brackets(self):
        url = "https://github.com/fixture/project/wiki/" + audit.INDEX_PAGE
        link = f"[Audits]({url})"
        for visible in ("\\[See " + link + "\\]", "\\[" + link + "\\]",
                        "\\[\\[See " + link + "\\]\\]",
                        "\\[See [Audits][index]\\]\n\n[index]: " + url,
                        "\\[See [Audits][]\\]\n\n[Audits]: " + url,
                        "\\[See [Audits]\\]\n\n[Audits]: " + url,
                        "[\\[Audits](" + url + ")"):
            with self.subTest(visible=visible):
                original = "# Home\n\n" + visible + "\n"
                self.assertEqual(audit.home_page(original, url), original)
        for hidden in ("\\[See \\" + link + "\\]", "\\[See !" + link + "\\]",
                       "![Image " + link + "](picture.png)"):
            with self.subTest(hidden=hidden):
                updated = audit.home_page(hidden, url)
                self.assertTrue(updated.startswith(hidden))
                self.assertEqual(updated[len(hidden):].count(url), 1)
                self.assertIn(audit.HOME_START, updated)
                self.assertEqual(audit.home_page(updated, url), updated)

    @pytest.mark.stable_storage
    def test_archive_publication_preserves_existing_markdown_home_files(self):
        _, _, exported = self.archive_fixture()
        self.git("mv", "Home.md", "Home.markdown", root=self.wiki)
        self.git("commit", "-qm", "Existing alternate Markdown Home", root=self.wiki)
        originals = {"Home.markdown": b"Existing wiki content\n"}
        args = ("publish-archive", "--pr", "first", "--approved", exported["identity"])
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate):
                if duplicate:
                    originals["Home.md"] = b"Other existing Home content\r\n"
                    (self.wiki / "Home.md").write_bytes(originals["Home.md"])
                    self.git("add", "Home.md", root=self.wiki)
                    self.git("commit", "-qm", "Existing duplicate Home", root=self.wiki)
                self.git("push", str(self.wiki_remote), "HEAD:refs/heads/docs", root=self.wiki)
                with patch.object(audit, "api", self.audit_api):
                    receipt = self.audit_cli(*args, *(("--republish",) if duplicate else ()))
                    wiki_head = self.git("ls-remote", str(self.wiki_remote), "HEAD")
                    self.assertEqual(self.audit_cli(*args), receipt)
                self.assertEqual(wiki_head, self.git("ls-remote", str(self.wiki_remote), "HEAD"))
                self.git("fetch", str(self.wiki_remote), "docs", root=self.wiki)
                names = self.git("ls-tree", "--name-only", "FETCH_HEAD", root=self.wiki).splitlines()
                self.assertEqual({name for name in names if name.startswith("Home.")}, set(originals))
                for name, original in originals.items():
                    published = audit.command(["git", "show", f"FETCH_HEAD:{name}"], cwd=self.wiki)
                    self.assertTrue(published.startswith(original))
                    self.assertEqual(published.count(receipt["index_url"].encode()), 1)
                self.git("merge", "--ff-only", "FETCH_HEAD", root=self.wiki)
        self.assertEqual(len(self.audit_body_updates), 1)

    @pytest.mark.stable_storage
    def test_archive_publication_creates_missing_home(self):
        _, _, exported = self.archive_fixture()
        self.git("rm", "Home.md", root=self.wiki)
        (self.wiki / "Other.md").write_text("Retained wiki content\n")
        self.git("add", "Other.md", root=self.wiki)
        self.git("commit", "-qm", "Wiki without Home", root=self.wiki)
        self.git("push", str(self.wiki_remote), "HEAD:refs/heads/docs", root=self.wiki)
        with patch.object(audit, "api", self.audit_api):
            receipt = self.audit_cli("publish-archive", "--pr", "first", "--approved", exported["identity"])
        self.git("fetch", str(self.wiki_remote), "docs", root=self.wiki)
        home = self.git("show", "FETCH_HEAD:Home.md", root=self.wiki)
        self.assertEqual(home, f"{audit.HOME_START}\n[Automated Pull Request Audits]"
                              f"({receipt['index_url']})\n{audit.HOME_END}")
        self.assertEqual(self.git("show", "FETCH_HEAD:Other.md", root=self.wiki), "Retained wiki content")

    @pytest.mark.stable_storage
    def test_archive_publication_preserves_handwritten_home_link_bytes(self):
        _, _, exported = self.archive_fixture()
        original = (b"# Home\r\n\r\n## Audits\r\n\r\n[Automated Pull Request Audits]"
                    b"(https://github.com/fixture/project/wiki/Automated-Pull-Request-Audits)"
                    b"\r\n\r\nHuman notes\r\n")
        (self.wiki / "Home.md").write_bytes(original)
        self.git("add", "Home.md", root=self.wiki)
        self.git("commit", "-qm", "Handwritten audit navigation", root=self.wiki)
        self.git("push", str(self.wiki_remote), "HEAD:refs/heads/docs", root=self.wiki)
        with patch.object(audit, "api", self.audit_api):
            args = ("publish-archive", "--pr", "first", "--approved", exported["identity"])
            self.audit_cli(*args)
            self.audit_cli(*args)
        self.git("fetch", str(self.wiki_remote), "docs", root=self.wiki)
        self.assertEqual(audit.command(["git", "show", "FETCH_HEAD:Home.md"], cwd=self.wiki), original)
        self.assertEqual(len(self.audit_body_updates), 1)

    @pytest.mark.stable_storage
    def test_archive_home_hooks_and_filters_cannot_change_approved_bytes(self):
        _, _, exported = self.archive_fixture()
        original = audit.command
        for transformation in ("filter", "hook"):
            with self.subTest(transformation=transformation):
                def transform(argv, **kwargs):
                    root = Path(kwargs["cwd"])
                    if argv[1] == "add" and transformation == "filter":
                        (root / ".git/info/attributes").write_text("Home.md filter=audit\n")
                        original(["git", "config", "filter.audit.clean", "sed s/Existing/Changed/"], cwd=root)
                    if argv[1] == "commit" and transformation == "hook":
                        (root / "Home.md").write_text("Unapproved Home replacement\n")
                        original(["git", "add", "--", "Home.md"], cwd=root)
                    return original(argv, **kwargs)

                with patch.object(audit, "api", self.audit_api), \
                        patch.object(audit, "command", side_effect=transform):
                    error = self.audit_cli("publish-archive", "--pr", "first",
                                           "--approved", exported["identity"], ok=False)
                self.assertIn("approved wiki bytes for Home.md", error)
                self.assertIn(self.wiki_initial, self.git("ls-remote", str(self.wiki_remote), "HEAD"))
                self.assertEqual(self.audit_body_updates, [])

    @pytest.mark.stable_storage
    def test_archive_navigation_uses_fetched_blobs_despite_smudge_filters(self):
        _, _, exported = self.archive_fixture()
        index = audit.INDEX_PAGE + ".md"
        originals = {"Home.md": (self.wiki / "Home.md").read_bytes(),
                     index: f"Existing index notes\n\n{audit.INDEX_HEADER}\n{audit.INDEX_SEPARATOR}\n".encode()}
        (self.wiki / index).write_bytes(originals[index])
        self.git("add", index, root=self.wiki)
        self.git("commit", "-qm", "Existing index navigation", root=self.wiki)
        self.git("push", str(self.wiki_remote), "HEAD:refs/heads/docs", root=self.wiki)
        original_command = audit.command
        smudged = []

        def smudge_checkout(argv, **kwargs):
            root = Path(kwargs["cwd"])
            if argv[1] == "checkout":
                (root / ".git/info/attributes").write_text(f"Home.md filter=audit\n{index} filter=audit\n")
                original_command(["git", "config", "filter.audit.smudge", "sed s/Existing/Changed/"], cwd=root)
            result = original_command(argv, **kwargs)
            if argv[1] == "checkout":
                smudged.append({name: (root / name).read_bytes() for name in originals})
            return result

        with patch.object(audit, "api", self.audit_api), \
                patch.object(audit, "command", side_effect=smudge_checkout):
            receipt = self.audit_cli("publish-archive", "--pr", "first", "--approved", exported["identity"])
        self.assertEqual(len(smudged), 1)
        self.assertTrue(all(data.startswith(b"Changed") for data in smudged[0].values()))
        self.git("fetch", str(self.wiki_remote), "docs", root=self.wiki)
        for name in originals:
            published = audit.command(["git", "show", f"FETCH_HEAD:{name}"], cwd=self.wiki)
            self.assertTrue(published.startswith(b"Existing"))
            self.assertNotIn(b"Changed", published)
            if name == "Home.md":
                self.assertTrue(published.startswith(originals[name]))
                self.assertEqual(published.count(receipt["index_url"].encode()), 1)
            else:
                self.assertIn(receipt["url"].encode(), published)
                rows = [line for line in published.splitlines(keepends=True) if receipt["pr_url"].encode() in line]
                self.assertEqual(len(rows), 1)
                self.assertEqual(published.replace(rows[0], b"", 1), originals[index])

    def test_audit_export_isolates_unusable_recorded_paths(self):
        root = self.start_audit_fixture()
        state, active, exported = self.audit_export()
        public = json.loads((Path(exported["directory"]) / "audit.json").read_bytes())["public"]
        recorded = next(item for item in state["history"] if item["role"] == "review")
        path = Path(recorded["report"]["data"]["ledger"])
        path.parent.rename(self.store / "retained-history")
        path.parent.symlink_to(self.store / "missing-history", target_is_directory=True)
        public["findings"] = []
        public_path = self.store / "reports" / active["id"] / "public.json"
        public_path.write_bytes(manifest.encode(public))
        exported = self.audit_cli("export", "--public", str(public_path))
        bundle = json.loads((Path(exported["directory"]) / "audit.json").read_bytes())
        unavailable = next(item for item in bundle["reviews"] if item["id"] == path.parent.name)
        self.assertFalse(unavailable["available"])
        self.assertEqual(unavailable["assignment_ids"], [recorded["id"]])
        self.assertTrue(root.exists())
        recorded["report"]["data"]["ledger"] = "/PRIVATE-AUDIT-PATH/invalid"
        with patch.dict(os.environ, self.env, clear=True):
            bundle = audit.build(state, active, public)
        self.assertNotIn("PRIVATE-AUDIT-PATH", json.dumps(bundle))
        self.assertTrue(any(recorded["id"] in item["assignment_ids"] and not item["available"]
                            for item in bundle["reviews"]))
        other_root = self.folder / "another-worktree"
        other = self.store / "reviews" / development.review.root_key(other_root) / ("a" * 32)
        other.parent.mkdir(parents=True)
        (self.store / "retained-history").rename(other)
        ledger_path = other / "REVIEW_LEDGER.json"
        ledger = json.loads(ledger_path.read_bytes())
        ledger.update(root=str(other_root), run_id=other.name)
        ledger_path.write_bytes(manifest.encode(ledger))
        recorded["report"]["data"]["ledger"] = str(ledger_path)
        with patch.dict(os.environ, self.env, clear=True), \
                patch.object(audit.review, "load", side_effect=AssertionError("Read a foreign review")):
            bundle = audit.build(state, active, public)
        foreign = next(item for item in bundle["reviews"] if item["id"] == other.name)
        self.assertFalse(foreign["available"])
        self.assertEqual(foreign["assignment_ids"], [recorded["id"]])

    def test_archive_preserves_completed_reviews_after_storage_becomes_a_repository(self):
        self.store = self.folder / "later-repository" / "private-run"
        root = self.start_audit_fixture()
        state, active, exported = self.audit_export()
        original = json.loads((Path(exported["directory"]) / "audit.json").read_bytes())
        public = self.store / "reports" / active["id"] / "public.json"
        recorded = next(item for item in state["history"] if item["role"] == "review")
        ledger = Path(recorded["report"]["data"]["ledger"])
        ledger_bytes = ledger.read_bytes()
        run_bytes = (self.store / "RUN.json").read_bytes()
        self.assertTrue(original["reviews"][0]["available"])
        self.assertTrue(original["reviews"][0]["findings"])
        self.git("init", "-q", str(self.store.parent))

        archived = self.audit_cli("archive", "--pr", "first", "--public", str(public))
        bundle = json.loads((Path(archived["directory"]) / "audit.json").read_bytes())
        self.assertEqual(bundle["reviews"], original["reviews"])
        self.assertEqual(bundle["public"], original["public"])
        self.assertTrue(Path(archived["directory"]).is_relative_to(Path(self.env["XDG_STATE_HOME"])))
        self.assertEqual(ledger.read_bytes(), ledger_bytes)
        self.assertEqual((self.store / "RUN.json").read_bytes(), run_bytes)
        self.assertEqual(self.audit_body_updates, [])
        with patch.object(audit, "api", self.audit_api):
            receipt = self.audit_cli("publish-archive", "--pr", "first", "--approved", archived["identity"])
        self.assertEqual(json.loads((Path(archived["directory"]) / "receipt.json").read_bytes()), receipt)
        self.assertEqual((self.store / "RUN.json").read_bytes(), run_bytes)
        self.assertEqual(ledger.read_bytes(), ledger_bytes)
        with patch.dict(os.environ, self.env, clear=True):
            with self.assertRaisesRegex(development.review.LedgerError, "outside every repository"):
                development.review.ledger_path(root, str(ledger))

    def archive_with_reused_worktree(self, legacy):
        root = self.start_audit_fixture()
        state, active, exported = self.audit_export()
        public = self.store / "reports" / active["id"] / "public.json"
        original = json.loads((Path(exported["directory"]) / "audit.json").read_bytes())
        recorded = next(item for item in state["history"] if item["role"] == "review")
        if legacy:
            path = Path(recorded["report"]["data"]["ledger"])
            with patch.dict(os.environ, self.env, clear=True):
                target = development.review.storage(root) / path.parent.name
            target.parent.mkdir(parents=True, exist_ok=True)
            path.parent.rename(target)
            recorded.pop("review_storage")
            recorded["report"]["data"]["ledger"] = str(
                root / ".review-loop" / target.name / "REVIEW_LEDGER.json")
            development.save(self.store, state)
        self.git("worktree", "remove", str(root))
        subprocess.run([sys.executable, str(SCRIPTS / "create-worktree.py"),
                        str(root), self.plan["prs"][0]["branch"]],
                       cwd=self.root, env=self.env, check=True, capture_output=True)
        unrelated = self.review_cli(root, ["init", "--objective", "Unrelated review",
                                          "--scope", "Another run", "--base", "HEAD"])
        for event in (
            {"type": "start_review", "reason": "Unrelated review"},
            {"type": "finding", "key": "unrelated", "summary": "Not part of the saved run",
             "locations": ["app.txt"], "severity": "Low", "evidence": ["Separate review"]},
        ):
            event["actor"] = "fixture-owner"
            event.setdefault("reason", "Unrelated review")
            unrelated = self.review_cli(
                root, ["apply", unrelated["ledger"], "--revision", str(unrelated["revision"])], event)
        before = (self.store / "RUN.json").read_bytes()
        for operation in ("export", "archive"):
            with self.subTest(operation=operation):
                args = ("--pr", "first") if operation == "archive" else ()
                result = self.audit_cli(operation, *args, "--public", str(public))
                bundle = json.loads((Path(result["directory"]) / "audit.json").read_bytes())
                self.assertEqual(bundle["reviews"], original["reviews"])
                self.assertEqual(bundle["public"], original["public"])
                self.assertEqual((self.store / "RUN.json").read_bytes(), before)
        outside = Path(unrelated["ledger"]).parent
        inside = root / ".review-loop" / outside.name
        inside.parent.mkdir(exist_ok=True)
        outside.rename(inside)
        result = self.audit_cli("archive", "--pr", "first", "--public", str(public))
        bundle = json.loads((Path(result["directory"]) / "audit.json").read_bytes())
        self.assertEqual(bundle["reviews"], original["reviews"])
        inside.rename(outside)
        self.git("worktree", "remove", str(root))
        result = self.audit_cli("archive", "--pr", "first", "--public", str(public))
        bundle = json.loads((Path(result["directory"]) / "audit.json").read_bytes())
        self.assertEqual(bundle["reviews"], original["reviews"])

    def test_archive_excludes_unrelated_reviews_at_a_reused_worktree_path(self):
        self.archive_with_reused_worktree(legacy=False)

    def test_legacy_archive_uses_only_recorded_review_ids(self):
        self.archive_with_reused_worktree(legacy=True)

    @pytest.mark.stable_storage
    def test_audit_repository_identity_accepts_casing_but_rejects_other_targets(self):
        self.start_audit_fixture()
        state, active, exported = self.audit_export()
        state["prs"]["first"]["url"] = "https://github.com/Fixture/Project/pull/1"

        def canonical_api(endpoint, **kwargs):
            result = self.audit_api(endpoint, **kwargs)
            if endpoint.endswith("/pulls/1"):
                result["head"]["repo"]["full_name"] = "FIXTURE/Project"
            if "html_url" in result:
                result["html_url"] = result["html_url"].replace("fixture/project", "Fixture/PROJECT")
            return result

        with patch.dict(os.environ, self.env, clear=True), patch.object(audit, "api", canonical_api):
            receipt = audit.publish(state, active, exported["identity"])
        self.assertEqual(audit.validate_receipt(state, active, receipt), receipt)
        self.finish(receipt)
        for url in ("https://github.com/fixture/other/pull/1",
                    "https://github.com/fixture/project/PULL/1"):
            with self.subTest(url=url):
                state["prs"]["first"]["url"] = url
                with patch.object(audit, "api", side_effect=AssertionError("Wrong publication target")):
                    with self.assertRaisesRegex(manifest.ManifestError, "approved repository"):
                        audit.publish(state, active, exported["identity"])
        state["prs"]["first"]["url"] = "https://github.com/fixture/project/pull/1"
        for field in ("repository", "branch"):
            with self.subTest(field=field):
                def mismatched_api(endpoint, **kwargs):
                    result = self.audit_api(endpoint, **kwargs)
                    if field == "repository":
                        result["head"]["repo"]["full_name"] = "fixture/other"
                    else:
                        result["head"]["ref"] = "Fixture-Feature"
                    return result

                with patch.dict(os.environ, self.env, clear=True), \
                        patch.object(audit, "api", mismatched_api), \
                        patch.object(audit, "publish_files", side_effect=AssertionError("Wrong branch")):
                    with self.assertRaisesRegex(manifest.ManifestError, "accepted implementation commit"):
                        audit.publish(state, active, exported["identity"])
        receipt_path = Path(exported["directory"]) / "receipt.json"
        for key, value in (("pr_url", receipt["pr_url"].replace("fixture/project", "fixture/other")),
                           ("url", receipt["url"].replace("fixture/project", "fixture/other")),
                           ("index_url", receipt["index_url"].replace("fixture/project", "fixture/other")),
                           ("data_url", receipt["data_url"].replace("Audit-PR-1", "Audit-PR-2"))):
            with self.subTest(receipt_field=key):
                changed = {**receipt, key: value}
                receipt_path.write_bytes(manifest.encode(changed))
                with self.assertRaisesRegex(manifest.ManifestError, "receipt does not match"):
                    audit.validate_receipt(state, active, changed)

    @pytest.mark.stable_storage
    def test_unavailable_wiki_recovers_without_changing_the_pr_or_consuming_an_assignment(self):
        self.start_audit_fixture()
        state, active, exported = self.audit_export()
        before = (self.store / "RUN.json").read_bytes()
        saved = self.folder / "unavailable-wiki.git"
        self.wiki_remote.rename(saved)
        with patch.dict(os.environ, self.env, clear=True), patch.object(audit, "api", self.audit_api):
            with self.assertRaises(manifest.ManifestError):
                audit.publish(state, active, exported["identity"])
            self.assertEqual(self.audit_body_updates, [])
            self.assertFalse((Path(exported["directory"]) / "receipt.json").exists())
            self.assertEqual((self.store / "RUN.json").read_bytes(), before)
            saved.rename(self.wiki_remote)
            receipt = audit.publish(state, active, exported["identity"])
        self.assertEqual(len(self.audit_body_updates), 1)
        self.finish(receipt)

    def test_wiki_index_keeps_other_rows_and_prepends_one_current_row_per_pr(self):
        publication = {
            "title": "Fix | [links] <safely>\nwithout an extra row",
            "pr_url": "https://github.com/fixture/project/pull/1",
            "url": "https://github.com/fixture/project/wiki/Audit-PR-1-initial",
            "data_url": "https://github.com/fixture/project/wiki/Audit-PR-1-initial.json",
        }
        previous = ("| 2026-01-01 | [#9 Existing PR](https://github.com/fixture/project/pull/9) | "
                    "[Related PR](https://github.com/fixture/project/pull/1) |\n")
        original = f"Human introduction\n\n{audit.INDEX_HEADER}\n{audit.INDEX_SEPARATOR}\n{previous}\nHuman footer\n"
        initial = audit.index_entry(original, publication)
        self.assertTrue(initial.startswith("Human introduction\n\n"))
        self.assertTrue(initial.endswith(previous + "\nHuman footer\n"))
        self.assertLess(initial.index(publication["pr_url"]), initial.index("/pull/9"))
        self.assertIn(r"Fix &#124; \[links\] &lt;safely&gt; without an extra row", initial)
        self.assertEqual(audit.index_entry(initial, publication), initial)
        final = {**publication, "url": publication["url"].replace("initial", "final"),
                 "data_url": publication["data_url"].replace("initial", "final")}
        updated = audit.index_entry(initial, final)
        self.assertEqual(updated.count("[#1 "), 1)
        self.assertNotIn(publication["url"], updated)
        self.assertIn(final["url"], updated)
        self.assertTrue(updated.endswith(previous + "\nHuman footer\n"))
        with self.assertRaisesRegex(manifest.ManifestError, "restore one"):
            audit.index_entry("Human notes without an audit table", publication)

    @pytest.mark.stable_storage
    def test_wiki_concurrent_update_is_preserved_and_pr_body_is_reread(self):
        self.start_audit_fixture()
        state, active, exported = self.audit_export()
        original = audit.command
        raced = False
        other_row = "| 2026-01-01 | [#9 Other PR](https://github.com/fixture/project/pull/9) | Other audit |\n"

        def concurrent_update(argv, **kwargs):
            nonlocal raced
            if argv[1] == "push" and not raced:
                raced = True
                (self.wiki / (audit.INDEX_PAGE + ".md")).write_text(
                    f"Existing introduction\n\n{audit.INDEX_HEADER}\n{audit.INDEX_SEPARATOR}\n"
                    f"{other_row}\nExisting footer\n")
                (self.wiki / "Other-page.md").write_text("Concurrent wiki edit\n")
                self.git("add", ".", root=self.wiki)
                self.git("commit", "-qm", "Another wiki publication", root=self.wiki)
                self.git("push", str(self.wiki_remote), "HEAD:refs/heads/docs", root=self.wiki)
                self.audit_body += "\nHuman edit during wiki publication.\n"
            return original(argv, **kwargs)

        with patch.dict(os.environ, self.env, clear=True), patch.object(audit, "api", self.audit_api), \
                patch.object(audit, "command", side_effect=concurrent_update):
            receipt = audit.publish(state, active, exported["identity"])
            repeated = audit.publish(state, active, exported["identity"])
        self.assertTrue(raced)
        self.assertEqual(receipt, repeated)
        self.assertEqual(len(self.audit_body_updates), 1)
        self.assertTrue(self.audit_body.endswith("Human edit during wiki publication.\n"))
        self.git("fetch", str(self.wiki_remote), "docs", root=self.wiki)
        index = self.git("show", f"FETCH_HEAD:{audit.INDEX_PAGE}.md", root=self.wiki)
        self.assertTrue(index.startswith("Existing introduction\n"))
        self.assertIn(other_row, index)
        self.assertTrue(index.endswith("Existing footer"))
        self.assertLess(index.index("/pull/1)"), index.index("/pull/9)"))
        self.assertEqual(self.git("show", "FETCH_HEAD:Other-page.md", root=self.wiki), "Concurrent wiki edit")
        self.finish(receipt)

    @pytest.mark.stable_storage
    def test_wiki_contention_stops_after_three_attempts_and_can_resume(self):
        self.start_audit_fixture()
        state, active, exported = self.audit_export()
        original = audit.command
        pushes = 0

        def concurrent_update(argv, **kwargs):
            nonlocal pushes
            if argv[1] == "push":
                pushes += 1
                (self.wiki / f"Concurrent-{pushes}.md").write_text(f"Concurrent edit {pushes}\n")
                self.git("add", ".", root=self.wiki)
                self.git("commit", "-qm", "Concurrent wiki update", root=self.wiki)
                self.git("push", str(self.wiki_remote), "HEAD:refs/heads/docs", root=self.wiki)
            return original(argv, **kwargs)

        before = (self.store / "RUN.json").read_bytes()
        with patch.dict(os.environ, self.env, clear=True), patch.object(audit, "api", self.audit_api):
            with patch.object(audit, "command", side_effect=concurrent_update):
                with self.assertRaisesRegex(manifest.ManifestError, "Wiki kept changing"):
                    audit.publish(state, active, exported["identity"])
            self.assertEqual(pushes, 3)
            self.assertEqual(self.audit_body_updates, [])
            self.assertEqual((self.store / "RUN.json").read_bytes(), before)
            receipt = audit.publish(state, active, exported["identity"])
        self.git("fetch", str(self.wiki_remote), "docs", root=self.wiki)
        for number in range(1, 4):
            self.assertEqual(self.git("show", f"FETCH_HEAD:Concurrent-{number}.md", root=self.wiki),
                             f"Concurrent edit {number}")
        self.finish(receipt)

    @pytest.mark.stable_storage
    def test_lost_wiki_push_response_does_not_duplicate_the_publication(self):
        self.start_audit_fixture()
        state, active, exported = self.audit_export()
        original = audit.command

        def lost_push(argv, **kwargs):
            result = original(argv, **kwargs)
            if argv[1] == "push":
                raise OSError("Lost wiki push response")
            return result

        with patch.dict(os.environ, self.env, clear=True), patch.object(audit, "api", self.audit_api):
            with patch.object(audit, "command", side_effect=lost_push):
                with self.assertRaisesRegex(OSError, "Lost wiki push"):
                    audit.publish(state, active, exported["identity"])
            first = self.git("ls-remote", str(self.wiki_remote), "HEAD")
            self.assertEqual(self.audit_body_updates, [])
            receipt = audit.publish(state, active, exported["identity"])
            self.assertEqual(first, self.git("ls-remote", str(self.wiki_remote), "HEAD"))
        self.assertEqual(len(self.audit_body_updates), 1)
        self.finish(receipt)

    def test_pr_audit_block_preserves_manual_text_and_allows_repair(self):
        publication = {
            "url": "https://github.com/fixture/project/wiki/Audit-PR-1-first",
            "data_url": "https://github.com/fixture/project/wiki/Audit-PR-1-first.json",
            "index_url": "https://github.com/fixture/project/wiki/Automated-Pull-Request-Audits",
        }
        body = "## Audit\n\nExisting human notes.\n\n## Checklist\n\n- [ ] Keep me\n"
        initial = audit.pr_body(body, publication)
        self.assertEqual(initial.count("## Audit\n"), 1)
        self.assertTrue(initial.endswith(body[len("## Audit"):]))
        changed = initial.replace(audit.LINK_END, "Human addition\n" + audit.LINK_END)
        with self.assertRaisesRegex(manifest.ManifestError, "preserve manual text"):
            audit.pr_body(changed, publication)
        repaired = initial + "\nHuman addition\n"
        final = {**publication, "url": publication["url"].replace("first", "final"),
                 "data_url": publication["data_url"].replace("first", "final")}
        updated = audit.pr_body(repaired, final)
        self.assertNotIn(publication["url"], updated)
        self.assertIn(final["url"], updated)
        self.assertTrue(updated.endswith("Human addition\n"))
        self.assertIn("Existing human notes.", updated)
        self.assertEqual(audit.pr_body(updated, final), updated)

    def mutation_during_settings_failure(self, command, *extra):
        original = development.feature_settings
        config = Path(self.env["HOME"]) / ".claude/ioncache-ai-tools.local.json"

        def failing_after_read(data):
            settings = original(data)
            config.write_text("{broken")
            return settings

        args = development.parser().parse_args(
            [command, str(self.store), "--revision", str(self.state["revision"]), *map(str, extra)])
        with patch.dict(os.environ, self.env, clear=True), \
                patch.object(development, "feature_settings", side_effect=failing_after_read):
            return development.mutate(args, self.store)

    def test_settings_snapshot_keeps_assignment_consistent_and_shutdown_reachable(self):
        self.configure_audit()
        self.init()
        self.state = self.mutation_during_settings_failure("next")
        self.assertTrue(self.state["assignment"]["audit"]["enabled"])
        before = (self.store / "RUN.json").read_bytes()
        self.assertIn("disabled", self.finish(outcome="blocked", ok=False))
        self.assertEqual((self.store / "RUN.json").read_bytes(), before)
        self.assertEqual(self.cli("status", self.store)["assignment"]["id"], self.state["assignment"]["id"])
        self.mutate("interrupt", "--reason", "Settings became unreadable")
        self.mutate("retire", "--reason", "Stopped the outstanding worker",
                    "--shutdown-evidence", "Offline fixture has no running worker")
        config = Path(self.env["HOME"]) / ".claude/ioncache-ai-tools.local.json"
        config.write_text('{"features": {}}')
        self.mutate("resume", "--reason", "Repaired settings")
        self.assertEqual(self.next()["attempt"], 2)

    @pytest.mark.stable_storage
    def test_settings_failure_cannot_waive_audit_completion(self):
        self.start_audit_fixture()
        state, active, exported = self.audit_export()
        with patch.dict(os.environ, self.env, clear=True), patch.object(audit, "api", self.audit_api):
            receipt = audit.publish(state, active, exported["identity"])
        before = (self.store / "RUN.json").read_bytes()
        with self.assertRaisesRegex(manifest.ManifestError, "Missing audit-initial data fields"):
            self.mutation_during_settings_failure("record", "--report", self.report({"disabled": True}))
        self.assertEqual((self.store / "RUN.json").read_bytes(), before)
        config = Path(self.env["HOME"]) / ".claude/ioncache-ai-tools.local.json"
        config.write_text('{"features": {}}')
        self.finish(receipt)

    @pytest.mark.stable_storage
    def test_settings_failure_cannot_waive_final_audit_at_reservation_or_delivery(self):
        root = self.start_audit_fixture()
        self.execute_fixture(self.state["assignment"])
        while self.next()["role"] != "audit-final":
            self.execute_fixture(self.state["assignment"])
        config = Path(self.env["HOME"]) / ".claude/ioncache-ai-tools.local.json"
        disabled = json.dumps({"features": {"autonomous-development-audit": False}})
        config.write_text(disabled)
        self.finish({"disabled": True})
        config.write_text('{"features": {}}')
        before = (self.store / "RUN.json").read_bytes()
        with self.assertRaisesRegex(manifest.ManifestError, "Final audit is missing"):
            self.mutation_during_settings_failure("next")
        self.assertEqual((self.store / "RUN.json").read_bytes(), before)
        config.write_text(disabled)
        self.assertEqual(self.next()["role"], "ready")
        config.write_text('{"features": {}}')
        report = self.report({"commit": self.git("rev-parse", "HEAD", root=root),
                              "url": "https://github.com/fixture/project/pull/1",
                              "state": "ready", "evidence": "Offline fixture receipt"})
        before = (self.store / "RUN.json").read_bytes()
        with self.assertRaisesRegex(manifest.ManifestError, "Final audit is missing"):
            self.mutation_during_settings_failure("record", "--report", report)
        self.assertEqual((self.store / "RUN.json").read_bytes(), before)

    def test_git_transformations_cannot_publish_unapproved_audit_bytes_or_files(self):
        self.start_audit_fixture()
        state, active, exported = self.audit_export()
        original = audit.command
        page = audit.publication_links(state, active, exported["identity"])["page"]
        for name in (page + ".md", "Home.md", "unexpected.txt"):
            with self.subTest(file=name):
                def changed_by_hook(argv, **kwargs):
                    if argv[1] == "commit":
                        root = Path(kwargs["cwd"])
                        (root / name).write_bytes(b"PRIVATE-AUDIT-SENTINEL")
                        original(["git", "add", "--", name], cwd=root)
                    return original(argv, **kwargs)

                with patch.dict(os.environ, self.env, clear=True), \
                        patch.object(audit, "api", self.audit_api), \
                        patch.object(audit, "command", side_effect=changed_by_hook):
                    with self.assertRaisesRegex(manifest.ManifestError, "inspect .*hooks"):
                        audit.publish(state, active, exported["identity"])
                self.assertIn(self.wiki_initial, self.git("ls-remote", str(self.wiki_remote), "HEAD"))
                self.assertEqual(self.audit_body_updates, [])

    @pytest.mark.stable_storage
    def test_audit_export_requires_complete_narrative_and_exact_publication_approval(self):
        self.start_audit_fixture()
        state, active, exported = self.audit_export()
        folder = Path(exported["directory"])
        public = json.loads((folder / "audit.json").read_bytes())["public"]
        incomplete = {**public, "findings": []}
        with self.assertRaisesRegex(manifest.ManifestError, "every recorded finding"):
            audit.export(state, active, incomplete)
        public["regressions"] = [{"cause": {"review": "unknown", "id": "F001"},
                                  "effect": {"review": "unknown", "id": "F002"},
                                  "basis": "inferred", "evidence": "Fixture hypothesis"}]
        with self.assertRaisesRegex(manifest.ManifestError, "Unknown regression"):
            audit.export(state, active, public)
        before = (self.store / "RUN.json").read_bytes()
        self.assertIn("Missing audit-initial data fields", self.finish({}, ok=False))
        self.assertEqual(before, (self.store / "RUN.json").read_bytes())
        stale = {"state": "open", "head": {"sha": "0" * 40, "ref": "fixture-feature",
                                           "repo": {"full_name": "fixture/project"}},
                 "html_url": "https://github.com/fixture/project/pull/1",
                 "base": {"repo": {"full_name": "fixture/project"}}}
        with patch.object(audit, "api", return_value=stale), \
                patch.object(audit, "publish_files", side_effect=AssertionError("No stale publication")):
            with self.assertRaisesRegex(manifest.ManifestError, "accepted implementation commit"):
                audit.publish(state, active, exported["identity"])
        with patch.object(audit, "api", side_effect=AssertionError("Publication must not start")):
            with self.assertRaisesRegex(manifest.ManifestError, "exact exported files"):
                audit.publish(state, active, "not-approved")
            (folder / "AUDIT.md").write_text("Unreviewed replacement")
            with self.assertRaisesRegex(manifest.ManifestError, "evidence changed"):
                audit.publish(state, active, exported["identity"])

    @pytest.mark.stable_storage
    def test_audit_opt_out_keeps_development_available_without_publication(self):
        self.configure_audit()
        config = Path(self.env["HOME"]) / ".claude/ioncache-ai-tools.local.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"features": {"autonomous-development-audit": False}}))
        self.init()
        self.env.update(self.audit_git_env)
        self.preflight()
        self.prepare()
        while self.next():
            if self.state["assignment"]["role"] in audit.ROLES:
                self.assertIn("disabled", self.audit_cli("publish", "--approved", "unused", ok=False))
            self.execute_fixture(self.state["assignment"])
        self.assertEqual(self.state["outcome"], "completed")
        self.assertTrue(all(item["disabled"] for item in self.state["prs"]["first"]["audits"]))
        self.assertEqual(self.audit_body_updates, [])
        self.assertEqual(self.git("ls-remote", "origin"), "")
        self.assertIn(self.wiki_initial, self.git("ls-remote", str(self.wiki_remote), "HEAD"))

    @pytest.mark.stable_storage
    def test_reenabled_audit_requires_counted_reconciliation_before_readiness(self):
        self.start_audit_fixture()
        self.execute_fixture(self.state["assignment"])
        while self.next()["role"] != "audit-final":
            self.execute_fixture(self.state["assignment"])
        config = Path(self.env["HOME"]) / ".claude/ioncache-ai-tools.local.json"
        config.write_text(json.dumps({"features": {"autonomous-development-audit": False}}))
        self.finish({"disabled": True})
        config.write_text(json.dumps({"features": {"autonomous-development-audit": True}}))
        before = (self.store / "RUN.json").read_bytes()
        self.assertIn("Final audit is missing", self.mutate("next", ok=False))
        self.assertEqual(before, (self.store / "RUN.json").read_bytes())
        self.mutate("reconcile", "--pr", "first", "--reason", "Audit publication reenabled")
        while self.next():
            if self.state["assignment"]["role"] == "audit-final":
                self.assertEqual(self.state["assignment"]["attempt"], 2)
            self.execute_fixture(self.state["assignment"])
        self.assertEqual(self.state["outcome"], "completed")
        self.assertEqual(len(self.audit_body_updates), 2)

    def workflow(self, scenario, expected_models=None):
        fixture = {"python": sys.executable, "store": str(self.store), "scenario": scenario,
                   "invocation": f"offline-{self.state['revision']}", "expected_models": expected_models}
        command = ["node", str(SCRIPTS / "development_workflow_self_check.js")]
        if uses_process(self):
            result = subprocess.run(
                [*command, "--persisted-controller"], input=json.dumps(fixture),
                cwd=self.root, env=self.env, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            observed = json.loads(result.stdout)
        else:
            observed = run_workflow(
                [*command, "--inprocess-controller"], fixture, self.workflow_command,
                cwd=self.root, env=self.env,
            )
        self.state = observed["result"]
        self.assertEqual(self.state, self.cli("status", self.store))
        return observed["roles"]

    def workflow_command(self, request):
        script, *args = request["argv"]
        path = Path(script)
        modules = {Path(module.__file__).name: module for module in
                   (development, handoffs, development.review)}
        module = modules.get(path.name)
        if path == SCRIPTS / "development_run_self_check.py":
            self.assertEqual(args, ["--workflow-review-fixture"])
            module = SimpleNamespace(
                __file__=str(path),
                main=lambda: print(json.dumps(workflow_review_fixture(json.load(sys.stdin)))),
            )
        if module is None or not path.is_file() or path.read_bytes() != Path(module.__file__).read_bytes():
            return subprocess.run(
                [sys.executable, script, *args], cwd=request["cwd"], env=self.env,
                input=request["input"], capture_output=True, text=True, timeout=30,
            )
        return run_main(module, args, cwd=request["cwd"], env=self.env, input=request["input"])

    def retire_fixture(self):
        self.mutate("retire", "--reason", "Reconciled the local fixture's partial effects",
                    "--shutdown-evidence", "The synchronous fixture process and workers exited")
        self.mutate("resume", "--reason", "Continue within the retained allowance")

    def handoff(self, command, *args, ok=True):
        if command == "prepare" and "--models-file" not in args:
            args = (*args, "--configured-models")
        result = run_main(handoffs, [command, str(self.store), *args],
                          env=self.env, process=uses_process(self))
        self.assertEqual(result.returncode, 0 if ok else 2, result.stdout + result.stderr)
        return json.loads(result.stdout)

    @pytest.mark.stable_storage
    def test_handoff_lost_prepare_reply_reuses_unlaunched_reservation(self):
        self.init()
        first = self.handoff("prepare")
        repeated = self.handoff("prepare")
        self.assertEqual(first, repeated)
        self.assertEqual(self.cli("status", self.store)["consumed_assignments"], 1)
        self.assertTrue(Path(first["script"]).is_file())
        self.handoff("claim", "--batch", first["batch"])
        self.assertEqual(self.handoff("prepare")["action"], "collect")
        denied = self.handoff("claim", "--batch", first["batch"], ok=False)
        self.assertIn("already claimed", denied["error"])
        self.assertEqual(self.cli("status", self.store)["consumed_assignments"], 1)

    def claim_handoff(self, batch):
        self.handoff("claim", "--batch", batch["batch"])
        record = development.load(self.store)["handoffs"][batch["batch"]]
        for number in range(1, len(record["spec"]["jobs"]) + 1):
            self.handoff("start", "--batch", batch["batch"], "--job", number)
        self.state = self.cli("status", self.store)
        return record["spec"]["jobs"]

    def review_handoff_fixture(self):
        self.init()
        self.preflight()
        root = self.prepare()
        self.next()
        (root / "app.txt").write_text("after\n")
        self.finish()
        batch = self.handoff("prepare")
        job = self.claim_handoff(batch)[0]
        return root, batch, Path(job["result_file"])

    def dispatch_review_fixture(self, batch, owner_path, data):
        handoff = json.loads(Path(data["handoff"]).read_bytes())
        requests = []
        results = {}
        for attempt in handoff["attempts"]:
            packet = attempt["packet"]
            path = Path(packet["result_file"])
            results[str(path)] = path.read_bytes()
            path.unlink()
            requests.append({"role": "reviewer", "prompt": "", "result_file": str(path), "packet": packet})
        owner_path.write_bytes(manifest.encode({"outcome": "dispatch", "result_file": "", "requests": requests}))
        self.handoff("finish", "--batch", batch["batch"], "--job", 1)
        self.handoff("collect", "--batch", batch["batch"])
        leaves = self.handoff("prepare")
        for number, job in enumerate(self.claim_handoff(leaves), 1):
            Path(job["result_file"]).write_bytes(results[job["result_file"]])
            self.handoff("finish", "--batch", leaves["batch"], "--job", number)
        self.handoff("collect", "--batch", leaves["batch"])
        owner = self.handoff("prepare")
        path = Path(self.claim_handoff(owner)[0]["result_file"])
        path.write_bytes(manifest.encode({
            "outcome": "complete", "result_file": str(self.report(data)), "requests": []}))
        return owner, path

    def dispatched_reviewers_fixture(self):
        root, batch, owner_path = self.review_handoff_fixture()
        data = self.review(root, record=False)
        handoff = json.loads(Path(data["handoff"]).read_bytes())
        requests, results = [], {}
        for attempt in handoff["attempts"]:
            path = Path(attempt["packet"]["result_file"])
            results[str(path)] = path.read_bytes()
            path.unlink()
            requests.append({"role": "reviewer", "prompt": "", "result_file": str(path),
                             "packet": attempt["packet"]})
        self.assertGreater(len(requests), 1)
        owner_path.write_bytes(manifest.encode({"outcome": "dispatch", "result_file": "", "requests": requests}))
        return batch, requests, results

    def pending_reviewers_script(self):
        state = development.load(self.store)
        assignment = development.request(state, development.feature(Path(state["root"])))
        pinned = self.store / "executor"
        reservations = state["active"]["review_dispatch"]["reservations"]
        spec = {"batch": "B000000", "assignment": assignment["id"], "store": str(self.store),
                "pluginRoot": str(pinned), "jobs": [handoffs.jobs.job(assignment, {
                    **item, "dispatch": reservations[item["result_file"]]["dispatch"]}, pinned)
                    for item in state["active"]["pending_requests"]]}
        one = len(handoffs.script_text(self.store, {**spec, "jobs": spec["jobs"][:1]}).encode())
        return spec, handoffs.script_text(self.store, spec), one

    def test_size_limited_batches_collect_each_queued_reviewer_once(self):
        batch, requests, results = self.dispatched_reviewers_fixture()
        self.handoff("finish", "--batch", batch["batch"], "--job", 1)
        self.handoff("collect", "--batch", batch["batch"])
        _, _, one = self.pending_reviewers_script()
        args = SimpleNamespace(models_file=None, configured_models=True, launch_dir=None)
        queued = [item["result_file"] for item in requests]
        launched = []
        # The reduced limit stays in force, so every batch holds one reviewer and the rest stay queued.
        for remaining in range(len(requests), 0, -1):
            pending = [item["result_file"] for item in development.load(self.store)["active"]["pending_requests"]]
            self.assertEqual(pending, queued[len(requests) - remaining:])
            with patch.dict(os.environ, self.env), patch.object(handoffs, "SCRIPT_BYTES", one + 64):
                leaves = handoffs.prepare(self.store, args)
            jobs = self.claim_handoff(leaves)
            self.assertEqual([job["result_file"] for job in jobs], pending[:1])
            launched.append(jobs[0]["result_file"])
            Path(jobs[0]["result_file"]).write_bytes(results[jobs[0]["result_file"]])
            self.handoff("finish", "--batch", leaves["batch"], "--job", 1)
            self.handoff("collect", "--batch", leaves["batch"])
        self.assertEqual(launched, queued)
        state = development.load(self.store)
        self.assertEqual(state["active"]["pending_requests"], [])
        self.assertEqual([item["result_file"] for item in state["active"]["review_dispatch"]["reports"]
                          if item["role"] == "reviewer"], queued)
        with patch.dict(os.environ, self.env), patch.object(handoffs, "SCRIPT_BYTES", one + 64):
            owner = handoffs.prepare(self.store, args)
        self.assertEqual(development.load(self.store)["handoffs"][owner["batch"]]["spec"]["jobs"][0]["role"],
                         "review-owner")

    def test_review_batches_fit_the_script_limit_and_a_refused_claim_releases(self):
        batch, requests, results = self.dispatched_reviewers_fixture()
        # A request too large to launch alone is a correctable owner report error, not a queued dead end.
        with patch.dict(os.environ, self.env), patch.object(handoffs, "SCRIPT_BYTES", 1):
            oversized = SimpleNamespace(batch=batch["batch"], job=1, command="finish")
            with self.assertRaisesRegex(ValueError, "too large to launch in one Workflow script"):
                handoffs.submit(self.store, oversized)
        self.assertNotIn("1", development.load(self.store)["handoffs"][batch["batch"]]["submitted"])
        self.handoff("finish", "--batch", batch["batch"], "--job", 1)
        self.handoff("collect", "--batch", batch["batch"])
        _, script, one = self.pending_reviewers_script()
        self.assertEqual(script.count("Frozen packet: "), len(requests))
        self.assertNotIn('"packet"', script)
        args = SimpleNamespace(models_file=None, configured_models=True, launch_dir=None)
        before = (self.store / "RUN.json").read_bytes()
        with patch.dict(os.environ, self.env), patch.object(handoffs, "SCRIPT_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "exceeds the Workflow tool's size limit"):
                handoffs.prepare(self.store, args)
        self.assertEqual((self.store / "RUN.json").read_bytes(), before)
        with patch.dict(os.environ, self.env), patch.object(handoffs, "SCRIPT_BYTES", one + 64):
            first = handoffs.prepare(self.store, args)
        self.assertLessEqual(Path(first["script"]).stat().st_size, one + 64)
        self.assertEqual(len(development.load(self.store)["handoffs"][first["batch"]]["spec"]["jobs"]), 1)
        # The host refuses the claimed script before starting it; release returns its job to the queue.
        consumed = self.cli("status", self.store)["consumed_assignments"]
        self.handoff("claim", "--batch", first["batch"])
        released = self.handoff("release", "--batch", first["batch"],
                                "--evidence", "Workflow tool refused the script; no run ID was returned")
        self.assertEqual(released["action"], "prepare")
        saved = development.load(self.store)
        self.assertEqual(saved["handoffs"][first["batch"]]["status"], "released")
        self.assertFalse(any(item["started"] for item in saved["active"]["review_dispatch"]["reservations"]
                             .values() if item["role"] == "reviewer"))
        stale = self.handoff("start", "--batch", first["batch"], "--job", 1, ok=False)
        self.assertIn("claimed active batch", stale["error"])
        leaves = self.handoff("prepare")
        self.assertNotEqual(leaves["batch"], first["batch"])
        jobs = self.claim_handoff(leaves)
        self.assertEqual(len(jobs), len(requests))
        denied = self.handoff("release", "--batch", leaves["batch"], "--evidence", "Started", ok=False)
        self.assertIn("A worker started this batch", denied["error"])
        for number, job in enumerate(jobs, 1):
            Path(job["result_file"]).write_bytes(results[job["result_file"]])
            self.handoff("finish", "--batch", leaves["batch"], "--job", number)
        self.handoff("collect", "--batch", leaves["batch"])
        owner = self.handoff("prepare")
        self.assertEqual(development.load(self.store)["handoffs"][owner["batch"]]["spec"]["jobs"][0]["role"],
                         "review-owner")
        self.assertEqual(self.cli("status", self.store)["consumed_assignments"], consumed)

    def completed_review_handoff_fixture(self):
        root, batch, path = self.review_handoff_fixture()
        data = self.review(root, record=False)
        batch, path = self.dispatch_review_fixture(batch, path, data)
        return root, batch, path, data

    @pytest.mark.stable_storage
    def test_handoff_final_acceptance_binds_collected_category_contents(self):
        _, batch, _, data = self.completed_review_handoff_fixture()
        self.handoff("finish", "--batch", batch["batch"], "--job", 1)
        path = Path(data["handoff"])
        original = path.read_bytes()
        handoff = json.loads(original)
        attempt = handoff["attempts"][0]
        attempt["result"]["coverage"]["isolation"] = "uncontaminated"
        attempt["result"]["limitations"] = ["Changed after collection"]
        report_path = Path(attempt["packet"]["result_file"])
        changed = manifest.encode(attempt["result"])
        report_path.write_bytes(changed)
        path.write_bytes(manifest.encode(handoff))
        before = development.load(self.store)
        error = self.handoff("collect", "--batch", batch["batch"], ok=False)
        self.assertIn("collected reviewer report", error["error"])
        self.assertEqual(development.load(self.store)["prs"], before["prs"])
        path.write_bytes(original)
        self.handoff("collect", "--batch", batch["batch"])
        self.assertEqual(report_path.read_bytes(), changed)
        saved = development.load(self.store)
        self.assertEqual(saved["attempts"], before["attempts"])
        self.assertTrue(saved["prs"]["first"]["review"]["coverage"]["structurally_complete"])

    @pytest.mark.stable_storage
    def test_handoff_uncollected_category_requires_existing_report_collection(self):
        root, batch, path = self.review_handoff_fixture()
        data = self.review(root, record=False)
        path.write_bytes(manifest.encode({
            "outcome": "complete", "result_file": str(self.report(data)), "requests": []}))
        self.handoff("finish", "--batch", batch["batch"], "--job", 1)
        error = self.handoff("collect", "--batch", batch["batch"], ok=False)
        self.assertIn("collected reviewer report", error["error"])
        batch, _ = self.dispatch_review_fixture(batch, path, data)
        self.handoff("finish", "--batch", batch["batch"], "--job", 1)
        self.handoff("collect", "--batch", batch["batch"])
        self.assertTrue(development.load(self.store)["prs"]["first"]["review"]["coverage"]["structurally_complete"])

    def test_handoff_unavailable_ledger_does_not_spend_report_correction(self):
        _, batch, _, data = self.completed_review_handoff_fixture()
        self.handoff("finish", "--batch", batch["batch"], "--job", 1)
        before = (self.store / "RUN.json").read_bytes()
        path = Path(data["ledger"])
        retained = path.with_suffix(".unavailable")
        path.rename(retained)
        error = self.handoff("collect", "--batch", batch["batch"], ok=False)
        self.assertEqual(error["kind"], "state_unavailable")
        self.assertEqual((self.store / "RUN.json").read_bytes(), before)
        retained.rename(path)
        self.handoff("collect", "--batch", batch["batch"])
        self.assertEqual(development.load(self.store)["handoffs"][batch["batch"]]["failures"], {})

    def test_handoff_corrupt_collected_archive_requires_restoration_not_report_correction(self):
        _, batch, _, _ = self.completed_review_handoff_fixture()
        self.handoff("finish", "--batch", batch["batch"], "--job", 1)
        state = development.load(self.store)
        leaves = next(item for item in state["handoffs"].values()
                      if item["spec"]["jobs"][0]["role"] == "reviewer")
        archive = self.store / "handoffs" / leaves["id"] / f"1-{leaves['submitted']['1']['sha256']}.json"
        original = archive.read_bytes()
        archive.write_text('{"corrupt": true}')
        before = (self.store / "RUN.json").read_bytes()
        error = self.handoff("collect", "--batch", batch["batch"], ok=False)
        self.assertEqual(error["kind"], "state_unavailable")
        self.assertEqual((self.store / "RUN.json").read_bytes(), before)
        archive.write_bytes(original)
        self.handoff("collect", "--batch", batch["batch"])

    def test_handoff_collection_reuses_retained_archive_when_staging_is_unavailable(self):
        self.init()
        batch = self.handoff("prepare")
        self.claim_handoff(batch)
        self.report(outcome="blocked")
        self.handoff("finish", "--batch", batch["batch"], "--job", 1)
        write = handoffs.review.atomic_write
        archives = self.store / "handoffs" / batch["batch"]
        original = {path.name: path.read_bytes() for path in archives.iterdir()}

        def cannot_stage_archive(path, content):
            if path.parent == archives:
                raise OSError("No space for another report copy")
            return write(path, content)

        with patch.object(handoffs.review, "atomic_write", side_effect=cannot_stage_archive):
            handoffs.collect(self.store, SimpleNamespace(batch=batch["batch"]))
        self.assertEqual({path.name: path.read_bytes() for path in archives.iterdir()}, original)
        self.assertEqual(development.load(self.store)["handoffs"][batch["batch"]]["status"], "collected")

    @pytest.mark.stable_storage
    def test_handoff_nested_json_returns_correction_and_retains_candidate(self):
        self.init()
        batch = self.handoff("prepare")
        self.claim_handoff(batch)
        candidate = self.store / "candidate.json"
        content = b"[" * 2000 + b"0" + b"]" * 2000
        candidate.write_bytes(content)
        error = self.handoff("submit", "--batch", batch["batch"], "--job", 1,
                             "--candidate", candidate, ok=False)
        self.assertEqual(error["kind"], "invalid_report")
        self.assertEqual(development.load(self.store)["handoffs"][batch["batch"]]["failures"]["1"], 1)
        archive = self.store / "handoffs" / batch["batch"] / f"1-{manifest.digest(content)}.json"
        self.assertEqual(archive.read_bytes(), content)
        candidate.write_bytes(manifest.encode({
            "outcome": "blocked", "summary": "Corrected", "evidence": ["Fixture"], "data": {}}))
        self.handoff("submit", "--batch", batch["batch"], "--job", 1, "--candidate", candidate)
        self.handoff("collect", "--batch", batch["batch"])

    def test_handoff_decoder_recursion_uses_report_correction(self):
        self.init()
        batch = self.handoff("prepare")
        self.claim_handoff(batch)
        candidate = self.store / "candidate.json"
        content = b"[" * 2000 + b"0" + b"]" * 2000
        candidate.write_bytes(content)
        decode = json.loads

        def decoder_with_recursion_error(value, *args, **kwargs):
            if value == content:
                raise RecursionError("Python JSON decoder recursion limit")
            return decode(value, *args, **kwargs)

        with patch.object(handoffs.json, "loads", side_effect=decoder_with_recursion_error):
            with self.assertRaises(handoffs.HandoffError) as caught:
                handoffs.submit(self.store, SimpleNamespace(
                    command="submit", batch=batch["batch"], job=1, candidate=str(candidate)))
        self.assertEqual(caught.exception.kind, "invalid_report")
        self.assertEqual(development.load(self.store)["handoffs"][batch["batch"]]["failures"]["1"], 1)
        candidate.write_bytes(manifest.encode({
            "outcome": "blocked", "summary": "Corrected", "evidence": ["Fixture"], "data": {}}))
        self.handoff("submit", "--batch", batch["batch"], "--job", 1, "--candidate", candidate)
        self.handoff("collect", "--batch", batch["batch"])

    @pytest.mark.stable_storage
    def test_handoff_reviewer_category_is_required_before_dispatch(self):
        root, batch, path = self.review_handoff_fixture()
        data = self.review(root, record=False)
        packet = json.loads(Path(data["handoff"]).read_bytes())["attempts"][0]["packet"]
        Path(packet["result_file"]).unlink()
        request = {"role": "reviewer", "prompt": "", "result_file": packet["result_file"], "packet": packet}
        for category in (None, " "):
            with self.subTest(category=category):
                changed = copy.deepcopy(packet)
                changed.pop("identity")
                changed["instruction_set"].pop("identity")
                if category is None:
                    changed.pop("review_type")
                    changed["instruction_set"].pop("category")
                else:
                    changed["review_type"] = changed["instruction_set"]["category"] = category
                changed["instruction_set"] = assignments.seal(changed["instruction_set"])
                changed = assignments.seal(changed)
                path.write_bytes(manifest.encode({
                    "outcome": "dispatch", "result_file": "", "requests": [{**request, "packet": changed}]}))
                error = self.handoff("finish", "--batch", batch["batch"], "--job", 1, ok=False)
                self.assertEqual(error["kind"], "invalid_report")
                self.assertEqual(development.load(self.store)["active"]["review_dispatch"]["reservations"], {})
        path.write_bytes(manifest.encode({"outcome": "dispatch", "result_file": "", "requests": [request]}))
        self.handoff("finish", "--batch", batch["batch"], "--job", 1)
        self.handoff("collect", "--batch", batch["batch"])
        self.assertEqual(len(development.load(self.store)["active"]["pending_requests"]), 1)

    @pytest.mark.stable_storage
    def test_handoff_owner_paths_cannot_overwrite_reserved_leaf_evidence(self):
        root, owner, owner_path = self.review_handoff_fixture()
        leaf = self.store / "reports" / self.state["assignment"]["id"] / "owner-3.json"
        request = {"role": "validator", "prompt": "Validate retained evidence", "result_file": str(leaf)}
        owner_path.write_bytes(manifest.encode({"outcome": "dispatch", "result_file": "", "requests": [request]}))
        self.handoff("finish", "--batch", owner["batch"], "--job", 1)
        self.handoff("collect", "--batch", owner["batch"])
        batch = self.handoff("prepare")
        self.claim_handoff(batch)
        evidence = manifest.encode({"outcome": "complete", "summary": "Original validator evidence"})
        leaf.write_bytes(evidence)
        self.handoff("finish", "--batch", batch["batch"], "--job", 1)
        self.handoff("collect", "--batch", batch["batch"])
        next_owner = self.handoff("prepare")
        path = Path(self.claim_handoff(next_owner)[0]["result_file"])
        self.assertNotEqual(path, leaf)
        report = self.report(outcome="blocked")
        path.write_bytes(manifest.encode({"outcome": "blocked", "result_file": str(report), "requests": []}))
        self.handoff("finish", "--batch", next_owner["batch"], "--job", 1)
        self.handoff("collect", "--batch", next_owner["batch"])
        self.assertEqual(leaf.read_bytes(), evidence)

    def test_handoff_continuation_failure_preserves_armed_state_and_lock(self):
        from review_ownership import locked as review_locked

        root, batch, _ = self.review_handoff_fixture()
        data = self.review(root, record=False, advance=False)
        self.mutate("interrupt", "--reason", "Fixture shutdown")
        self.mutate("resume-review", "--ledger", data["ledger"], "--reason", "Resume retained review",
                    "--shutdown-evidence", "Fixture worker exited")
        before = (self.store / "RUN.json").read_bytes()

        def fail_before_batch(*args):
            with self.assertRaises(BlockingIOError):
                with review_locked(root):
                    pass
            raise OSError("Fixture failure before replacement batch")

        with patch.object(handoffs.jobs, "job", side_effect=fail_before_batch):
            with self.assertRaisesRegex(OSError, "before replacement"):
                handoffs.prepare(self.store, SimpleNamespace(models_file=None, configured_models=True))
        self.assertEqual((self.store / "RUN.json").read_bytes(), before)
        resumed = self.handoff("prepare")
        self.assertEqual(self.handoff("prepare"), resumed)
        state = development.load(self.store)
        self.assertEqual(state["handoffs"][batch["batch"]]["status"], "reconciled")
        self.assertEqual(state["active"]["review_dispatch"]["calls"], 2)

    @pytest.mark.stable_storage
    def test_handoff_owner_outcomes_must_match_on_finish(self):
        _, batch, path, data = self.completed_review_handoff_fixture()
        for outer, inner in (("blocked", "complete"), ("complete", "blocked")):
            report = self.report(data, outcome=inner)
            path.write_bytes(manifest.encode({"outcome": outer, "result_file": str(report), "requests": []}))
            error = self.handoff("finish", "--batch", batch["batch"], "--job", 1, ok=False)
            self.assertIn("outcomes differ", error["error"])
        self.report(data)
        self.handoff("finish", "--batch", batch["batch"], "--job", 1)
        self.handoff("collect", "--batch", batch["batch"])
        self.state = self.cli("status", self.store)
        self.assertEqual(self.next()["role"], "commit")

    @pytest.mark.stable_storage
    def test_handoff_owner_receipt_binds_referenced_report_and_legacy_rebind(self):
        _, batch, path, data = self.completed_review_handoff_fixture()
        report = self.report(data)
        original = report.read_bytes()
        path.write_bytes(manifest.encode({"outcome": "complete", "result_file": str(report), "requests": []}))
        self.handoff("finish", "--batch", batch["batch"], "--job", 1)
        changed = json.loads(original)
        changed["summary"] = "Replaced after validation"
        report.write_bytes(manifest.encode(changed))
        for command in ("finish", "collect"):
            extra = ("--job", 1) if command == "finish" else ()
            error = self.handoff(command, "--batch", batch["batch"], *extra, ok=False)
            self.assertIn("Submitted report changed", error["error"])
        report.write_bytes(original)
        state = development.load(self.store)
        state["handoffs"][batch["batch"]]["submitted"]["1"].pop("development_sha256")
        development.save(self.store, state)
        error = self.handoff("collect", "--batch", batch["batch"], ok=False)
        self.assertIn("finish", error["error"])
        self.handoff("finish", "--batch", batch["batch"], "--job", 1)
        receipt = self.handoff("collect", "--batch", batch["batch"])
        self.assertEqual(self.handoff("collect", "--batch", batch["batch"]), receipt)

    @pytest.mark.stable_storage
    def test_handoff_missing_report_does_not_spend_disabled_correction(self):
        self.init()
        config = Path(self.env["HOME"]) / ".claude/ioncache-ai-tools.local.json"
        config.write_text(json.dumps({"features": {"autonomous-development-report-correction": False}}))
        batch = self.handoff("prepare")
        self.claim_handoff(batch)
        error = self.handoff("finish", "--batch", batch["batch"], "--job", 1, ok=False)
        self.assertEqual(error["kind"], "missing_report")
        self.report(outcome="blocked")
        self.handoff("finish", "--batch", batch["batch"], "--job", 1)
        self.handoff("collect", "--batch", batch["batch"])
        self.assertEqual(development.load(self.store)["handoffs"][batch["batch"]]["failures"], {})

    def test_handoff_candidate_archive_and_validation_use_one_snapshot(self):
        self.init()
        batch = self.handoff("prepare")
        self.claim_handoff(batch)
        candidate = self.store / "candidate.json"
        original = manifest.encode({"outcome": "blocked", "summary": "Original candidate",
                                    "evidence": ["Fixture"], "data": {}})
        candidate.write_bytes(original)
        write = handoffs.review.atomic_write

        def replace_after_archive(path, content):
            write(path, content)
            if path.parent.name == batch["batch"] and content == original:
                candidate.write_text("invalid replacement")

        with patch.object(handoffs.review, "atomic_write", side_effect=replace_after_archive):
            handoffs.submit(self.store, SimpleNamespace(command="submit", batch=batch["batch"],
                                                       job=1, candidate=str(candidate)))
        self.assertEqual(candidate.read_text(), "invalid replacement")
        archive = self.store / "handoffs" / batch["batch"] / f"1-{manifest.digest(original)}.json"
        self.assertEqual(archive.read_bytes(), original)
        self.handoff("collect", "--batch", batch["batch"])
        self.assertEqual(development.load(self.store)["history"][-1]["report"]["summary"], "Original candidate")

    @pytest.mark.process
    def test_handoff_fifo_candidate_returns_without_blocking_and_recovers(self):
        self.init()
        batch = self.handoff("prepare")
        self.claim_handoff(batch)
        candidate = self.store / "candidate.json"
        os.mkfifo(candidate)
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "development_handoff.py"), "submit", str(self.store),
             "--batch", batch["batch"], "--job", "1", "--candidate", str(candidate)],
            env=self.env, capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("regular", json.loads(result.stdout)["error"])
        candidate.unlink()
        candidate.write_text('{"outcome":"blocked","summary":"Recovered","evidence":["Fixture"],"data":{}}')
        self.handoff("submit", "--batch", batch["batch"], "--job", 1, "--candidate", candidate)
        self.handoff("collect", "--batch", batch["batch"])

    def test_handoff_null_instruction_set_has_structured_correction(self):
        _, batch, path = self.review_handoff_fixture()
        result = str(self.store / "reports" / self.state["assignment"]["id"] / "leaf.json")
        request = {"role": "reviewer", "prompt": "", "result_file": result,
                   "packet": {"identity": "fixture", "instruction_set": None}}
        path.write_bytes(manifest.encode({"outcome": "dispatch", "result_file": "", "requests": [request]}))
        error = self.handoff("finish", "--batch", batch["batch"], "--job", 1, ok=False)
        self.assertEqual(error["kind"], "invalid_report")
        request = {"role": "validator", "prompt": "Check existing evidence", "result_file": result}
        path.write_bytes(manifest.encode({"outcome": "dispatch", "result_file": "", "requests": [request]}))
        self.handoff("finish", "--batch", batch["batch"], "--job", 1)
        self.handoff("collect", "--batch", batch["batch"])
        self.assertEqual(len(development.load(self.store)["active"]["pending_requests"]), 1)

    @pytest.mark.stable_storage
    def test_handoff_semantic_rejection_allows_report_correction_without_another_commit(self):
        root = self.start_review_fixture()
        (root / "app.txt").write_text("after\n")
        self.review(root)
        batch = self.handoff("prepare")
        self.claim_handoff(batch)
        self.git("add", "app.txt", root=root)
        self.git("commit", "-qm", "One fixture commit", root=root)
        head = self.git("rev-parse", "HEAD", root=root)
        report = self.report({"commit": "0" * 40})
        rejected = report.read_bytes()
        self.handoff("finish", "--batch", batch["batch"], "--job", 1)
        before = development.load(self.store)
        for _ in range(2):
            error = self.handoff("collect", "--batch", batch["batch"], ok=False)
            self.assertIn("HEAD", error["error"])
        state = development.load(self.store)
        self.assertEqual(state["active"], before["active"])
        self.assertEqual(state["prs"], before["prs"])
        self.assertEqual(state["handoffs"][batch["batch"]]["failures"]["1"], 1)
        self.report({"commit": head})
        self.handoff("finish", "--batch", batch["batch"], "--job", 1)
        collected = self.handoff("collect", "--batch", batch["batch"])
        self.assertEqual(self.handoff("collect", "--batch", batch["batch"]), collected)
        self.assertEqual(self.git("rev-parse", "HEAD", root=root), head)
        self.assertEqual(development.load(self.store)["attempts"], before["attempts"])
        retained = list((self.store / "handoffs" / batch["batch"]).glob("1-*.json"))
        self.assertIn(rejected, [item.read_bytes() for item in retained])

    def test_handoff_changed_script_does_not_partially_resume(self):
        self.init()
        batch = self.handoff("prepare")
        self.state = self.cli("status", self.store)
        self.mutate("interrupt", "--reason", "Fixture interruption")
        Path(batch["script"]).write_text("changed script")
        before = (self.store / "RUN.json").read_bytes()
        self.handoff("resume-prepared", "--batch", batch["batch"], "--reason", "Resume", ok=False)
        self.assertEqual((self.store / "RUN.json").read_bytes(), before)
        self.handoff("repair-script", "--batch", batch["batch"])
        self.handoff("resume-prepared", "--batch", batch["batch"], "--reason", "Repaired")
        self.handoff("claim", "--batch", batch["batch"])

    def test_handoff_bounded_reader_rejects_growth_and_oversized_candidates(self):
        self.init()
        batch = self.handoff("prepare")
        self.claim_handoff(batch)
        candidate = self.store / "candidate.json"
        with candidate.open("wb") as stream:
            stream.truncate(handoffs.MAX_JSON_BYTES + 1)
        error = self.handoff("submit", "--batch", batch["batch"], "--job", 1,
                             "--candidate", candidate, ok=False)
        self.assertIn("size limit", error["error"])
        self.assertFalse(list((self.store / "handoffs" / batch["batch"]).glob("1-*.json")))
        before_growth = SimpleNamespace(st_mode=candidate.stat().st_mode, st_size=0)
        with patch.object(handoffs.jobs.os, "fstat", return_value=before_growth):
            with self.assertRaisesRegex(ValueError, "size limit"):
                handoffs.read_bytes(candidate)
        candidate.write_text('{"outcome":"blocked","summary":"Recovered","evidence":["Fixture"],"data":{}}')
        self.handoff("submit", "--batch", batch["batch"], "--job", 1, "--candidate", candidate)
        self.handoff("collect", "--batch", batch["batch"])

    def test_handoff_collect_uses_checked_owner_snapshot_without_rereading(self):
        _, batch, path, data = self.completed_review_handoff_fixture()
        reference = self.report(data)
        original = json.loads(reference.read_bytes())
        path.write_bytes(manifest.encode({"outcome": "complete", "result_file": str(reference), "requests": []}))
        self.handoff("finish", "--batch", batch["batch"], "--job", 1)
        validate = handoffs.jobs.development_report

        def replace_after_validation(assignment, report):
            validate(assignment, report)
            reference.write_bytes(manifest.encode({**original, "outcome": "blocked"}))

        with patch.object(handoffs.jobs, "development_report", side_effect=replace_after_validation):
            handoffs.collect(self.store, SimpleNamespace(batch=batch["batch"]))
        state = development.load(self.store)
        self.assertIsNone(state["active"])
        self.assertEqual(state["outcome"], "running")
        self.assertEqual(state["history"][-1]["report"], original)

    @pytest.mark.stable_storage
    def test_handoff_late_controller_failure_rolls_back_state_and_rechecks_same_receipt(self):
        self.init()
        batch = self.handoff("prepare")
        self.claim_handoff(batch)
        data = {key: True for key in ("artifact_access", "native_permissions", "fresh_workers",
                                      "independent_review", "result_delivery", "cancellation")}
        self.report(data)
        self.handoff("finish", "--batch", batch["batch"], "--job", 1)
        before = development.load(self.store)
        complete = handoffs.run.complete

        @contextmanager
        def fail_after_checks(*args):
            with complete(*args):
                manifest.require(args[0]["active"] is not None, "Fixture late acceptance failure")
                yield

        with patch.object(handoffs.run, "complete", side_effect=fail_after_checks):
            with self.assertRaisesRegex(ValueError, "late acceptance"):
                handoffs.collect(self.store, SimpleNamespace(batch=batch["batch"]))
        state = development.load(self.store)
        for key in ("active", "history", "prs", "preflight", "attempts"):
            self.assertEqual(state[key], before[key])
        self.handoff("collect", "--batch", batch["batch"])
        self.assertTrue(development.load(self.store)["preflight"])
        self.assertEqual(development.load(self.store)["handoffs"][batch["batch"]]["failures"]["1"], 1)

    @pytest.mark.stable_storage
    def test_handoff_controller_corrections_share_the_bound_and_respect_optout(self):
        self.init()
        batch = self.handoff("prepare")
        self.claim_handoff(batch)
        config = Path(self.env["HOME"]) / ".claude/ioncache-ai-tools.local.json"
        config.write_text(json.dumps({"features": {"autonomous-development-report-correction": False}}))
        data = {key: True for key in ("artifact_access", "native_permissions", "fresh_workers",
                                      "independent_review", "result_delivery", "cancellation")}
        report = self.report(data)
        original = report.read_bytes()
        self.handoff("finish", "--batch", batch["batch"], "--job", 1)
        with patch.object(handoffs.run, "complete", side_effect=manifest.ManifestError("Fixture rejection")):
            for attempt in range(1, 4):
                with self.assertRaisesRegex(ValueError, "Fixture rejection"):
                    handoffs.collect(self.store, SimpleNamespace(batch=batch["batch"]))
                self.assertEqual(development.load(self.store)["handoffs"][batch["batch"]]["failures"]["1"], attempt)
                changed = json.loads(original)
                changed["summary"] = f"Correction {attempt}"
                report.write_bytes(manifest.encode(changed))
                if attempt in (1, 3):
                    error = self.handoff("finish", "--batch", batch["batch"], "--job", 1, ok=False)
                    self.assertIn("allowance exhausted", error["error"])
                if attempt == 1:
                    config.write_text('{"features": {}}')
                if attempt < 3:
                    self.handoff("finish", "--batch", batch["batch"], "--job", 1)
        self.assertFalse(development.load(self.store)["preflight"])

    @pytest.mark.stable_storage
    def test_handoff_invalid_legacy_owner_binding_can_be_corrected_without_relaunch(self):
        _, batch, path, data = self.completed_review_handoff_fixture()
        reference = self.report(data)
        envelope = {"outcome": "blocked", "result_file": str(reference), "requests": []}
        path.write_bytes(manifest.encode(envelope))
        state = development.load(self.store)
        calls = state["active"]["review_dispatch"]["calls"]
        record = state["handoffs"][batch["batch"]]
        record["submitted"]["1"] = {"result_file": str(path), "sha256": manifest.digest(path.read_bytes())}
        development.save(self.store, state)
        error = self.handoff("finish", "--batch", batch["batch"], "--job", 1, ok=False)
        self.assertIn("outcomes differ", error["error"])
        path.write_bytes(manifest.encode({**envelope, "outcome": "complete"}))
        self.handoff("finish", "--batch", batch["batch"], "--job", 1)
        self.handoff("collect", "--batch", batch["batch"])
        saved = development.load(self.store)
        self.assertEqual(saved["history"][-1]["review_dispatch"]["calls"], calls)
        self.assertEqual(saved["history"][-1]["outcome"], "complete")

    def test_handoff_owner_namespace_rejects_symlink_before_reserving(self):
        self.init()
        self.preflight()
        self.prepare()
        self.next()
        self.finish()
        outside = self.folder / "outside-reports"
        outside.mkdir()
        link = self.store / "reports/owners"
        link.symlink_to(outside, target_is_directory=True)
        before = (self.store / "RUN.json").read_bytes()
        error = self.handoff("prepare", ok=False)
        self.assertIn("Symlink", error["error"])
        self.assertEqual((self.store / "RUN.json").read_bytes(), before)
        self.assertEqual(list(outside.iterdir()), [])
        link.unlink()
        batch = self.handoff("prepare")
        self.claim_handoff(batch)

    @pytest.mark.process
    def test_workflow_collects_persisted_report_after_losing_native_reply(self):
        self.init()
        self.preflight()
        root = self.prepare()
        roles = self.workflow("lost-finished-reply")
        self.assertEqual(roles.count("implement"), 1)
        self.assertIn("review-owner", roles)
        self.assertEqual((root / "app.txt").read_text(), "after\n")
        implementations = [item for item in development.load(self.store)["history"] if item["role"] == "implement"]
        self.assertEqual([item["outcome"] for item in implementations], ["complete"])

    @pytest.mark.stable_storage
    def test_workflow_restart_collects_saved_submission_without_relaunch(self):
        self.init()
        self.preflight()
        root = self.prepare()
        batch = self.handoff("prepare")
        self.claim_handoff(batch)
        (root / "app.txt").write_text("after\n")
        self.report()
        self.handoff("finish", "--batch", batch["batch"], "--job", 1)
        started = development.load(self.store)["handoffs"][batch["batch"]]["started"]
        roles = self.workflow("restart-finished")
        self.assertNotIn("implement", roles)
        self.assertIn("review-owner", roles)
        saved = development.load(self.store)["handoffs"][batch["batch"]]
        self.assertEqual(saved["status"], "collected")
        self.assertEqual(saved["started"], started)
        self.assertEqual((root / "app.txt").read_text(), "after\n")

    @pytest.mark.stable_storage
    def test_workflow_restart_without_submission_still_requires_recovery(self):
        self.init()
        self.preflight()
        self.prepare()
        batch = self.handoff("prepare")
        self.claim_handoff(batch)
        self.assertEqual(self.workflow("restart-missing"), [])
        self.assertEqual(self.state["outcome"], "blocked")
        self.assertIn("missing_report", self.state["reason"])
        self.assertEqual(development.load(self.store)["handoffs"][batch["batch"]]["status"], "claimed")

    @pytest.mark.stable_storage
    def test_handoff_generates_identity_and_corrects_report_without_repeating_work(self):
        self.init()
        batch = self.handoff("prepare")
        self.handoff("claim", "--batch", batch["batch"])
        self.handoff("start", "--batch", batch["batch"], "--job", "1")
        candidate = self.store / "candidate.json"
        candidate.write_text(json.dumps({"outcome": "complete", "data": {}}))
        invalid = self.handoff("submit", "--batch", batch["batch"], "--job", "1",
                               "--candidate", candidate, ok=False)
        self.assertIn("summary", invalid["error"])
        candidate.write_text(json.dumps({
            "outcome": "complete", "worker": None, "summary": "Verified fixture prerequisites",
            "evidence": ["Offline fixture, not a live-host qualification"],
            "data": {key: True for key in ("artifact_access", "native_permissions", "fresh_workers",
                                          "independent_review", "result_delivery", "cancellation")},
        }))
        self.handoff("submit", "--batch", batch["batch"], "--job", "1", "--candidate", candidate)
        report = json.loads((self.store / "reports/A0001.json").read_bytes())
        self.assertEqual(report["assignment"], "A0001")
        self.assertEqual(report["artifacts"], {item["id"]: item["sha256"] for item in self.plan["artifacts"]})
        collected = self.handoff("collect", "--batch", batch["batch"])
        self.assertEqual(collected["action"], "prepare")
        before = (self.store / "RUN.json").read_bytes()
        self.assertEqual(self.handoff("collect", "--batch", batch["batch"]), collected)
        self.assertEqual((self.store / "RUN.json").read_bytes(), before)
        self.assertTrue(development.load(self.store)["preflight"])
        self.assertEqual(self.handoff("prepare")["assignment"], "A0002")

    def test_report_diagnostics_identify_only_missing_or_mistyped_fields(self):
        self.init()
        assignment = self.next()
        report = json.loads(self.report({
            "commit": "fixture", "url": "https://example.invalid/pull/1", "state": "draft",
        }).read_text())
        with self.assertRaisesRegex(ValueError, r"Missing draft data fields: evidence$"):
            handoffs.jobs.validate(assignment, {"role": "draft"}, report)
        report["data"]["evidence"] = ["Observed the existing PR"]
        with self.assertRaisesRegex(ValueError, r"data\.evidence.*text"):
            handoffs.jobs.validate(assignment, {"role": "draft"}, report)
        report["data"]["evidence"] = "Observed the existing PR"
        report["worker"] = ""
        with self.assertRaisesRegex(ValueError, "worker must be nonempty text or null"):
            handoffs.jobs.validate(assignment, {"role": "draft"}, report)
        report["worker"] = None
        report["outcome"] = "completed"
        with self.assertRaisesRegex(ValueError, "completed.*complete, blocked, waiting"):
            handoffs.jobs.validate(assignment, {"role": "draft"}, report)

    def test_development_prompts_carry_the_role_report_contract(self):
        assignment = {"root": str(self.root), "audit": {"enabled": True}}
        expected = {
            "preflight": ("artifact_access", "audit_publication"),
            "prepare": ("base", "merged_dependencies"), "implement": (),
            "commit": ("commit",), "draft": ("commit", "url", "evidence", "state"),
            "ready": ("commit", "url", "evidence", "state"), "evidence": ("commit", "artifacts"),
            "audit-initial": ("stage", "code_commit", "bundle", "wiki_commit", "url", "data_url", "index_url", "pr_url"),
            "audit-final": ("stage", "code_commit", "bundle", "wiki_commit", "url", "data_url", "index_url", "pr_url"),
            "review-owner": ("ledger", "plan", "handoff"),
        }
        for role, fields in expected.items():
            with self.subTest(role=role):
                prompt = handoffs.jobs.instructions(assignment, {"role": role}, SCRIPTS.parent)
                self.assertEqual("FOLLOW_UPS.md" in prompt, role in ("draft", "ready"))
                self.assertIn("outcome must be exactly one of: complete, blocked, waiting", prompt)
                schema = json.loads(prompt.split("Required data fields for outcome complete: ", 1)[1]
                                    .split(". text means", 1)[0])
                self.assertTrue(set(fields) <= schema.keys())
                if role in ("draft", "ready"):
                    self.assertIn("from progress.known_issues_pr_draft in the PR", prompt)
                    self.assertIn("from progress.known_issues_report in the private report", prompt)
                    self.assertNotIn("from progress.known_issues in", prompt)
                    self.assertEqual(schema["evidence"]["type"], "text")
                    self.assertEqual(schema["state"]["type"], role)
        disabled = {**assignment, "report_contract_enabled": False}
        self.assertNotIn("Development report contract", handoffs.jobs.instructions(
            disabled, {"role": "draft"}, SCRIPTS.parent))
        self.assertEqual(handoffs.jobs.data_contract(disabled, "draft"),
                         handoffs.jobs.data_contract(assignment, "draft"))

    @pytest.mark.stable_storage
    def test_relative_report_candidate_stays_inside_store_without_spending_corrections(self):
        self.init()
        batch = self.handoff("prepare")
        self.claim_handoff(batch)
        candidate = self.store / "candidate.json"
        candidate.write_text(json.dumps({
            "outcome": "blocked", "summary": "Observed missing capability",
            "evidence": ["Existing observations"], "data": {},
        }))
        self.handoff("submit", "--batch", batch["batch"], "--job", 1, "--candidate", "candidate.json")
        record = development.load(self.store)["handoffs"][batch["batch"]]
        self.assertEqual(record["failures"], {})

    @pytest.mark.stable_storage
    def test_report_precheck_and_recovery_keep_invalid_paths_and_reports_rejected(self):
        self.init()
        batch = self.handoff("prepare")
        self.claim_handoff(batch)
        candidate = self.store / "candidate.json"
        candidate.write_text('{"invalid":')
        base = ("--batch", batch["batch"], "--job", 1)
        config = self.root / ".claude/ioncache-ai-tools.local.json"
        config.parent.mkdir(exist_ok=True)
        config.write_text('{"features": {"retired-fixture-feature": false}}')
        configuration = config.read_bytes()
        original = (self.store / "RUN.json").read_bytes()
        self.handoff("check-report", *base, "--candidate", candidate, ok=False)
        self.assertEqual((self.store / "RUN.json").read_bytes(), original)
        self.assertEqual(config.read_bytes(), configuration)
        outside = self.folder / "outside.json"
        outside.write_text("{}")
        link = self.store / "linked.json"
        link.symlink_to(outside)
        for path in (outside, "../outside.json", link):
            self.handoff("check-report", *base, "--candidate", path, ok=False)
            self.assertEqual((self.store / "RUN.json").read_bytes(), original)
        for _ in range(3):
            self.handoff("submit", *base, "--candidate", candidate, ok=False)
        exhausted = development.load(self.store)
        recovery = (*base, "--candidate", candidate, "--evidence", "Preserved evidence",
                    "--shutdown-evidence", "No native worker remains")
        config.write_text('{"features": {"autonomous-development-report-recovery": false}}')
        self.assertIn("disabled", self.handoff("recover-report", *recovery, ok=False)["error"])
        self.assertNotIn("report_recoveries", development.load(self.store)["handoffs"][batch["batch"]])
        config.write_text('{"features": {}}')
        self.assertIn("recovery was consumed", self.handoff("recover-report", *recovery, ok=False)["error"])
        candidate.write_text(json.dumps({
            "outcome": "blocked", "summary": "Corrected schema", "evidence": ["Observed failure"], "data": {},
        }))
        self.assertTrue(self.handoff("check-report", *base, "--candidate", candidate)["valid"])
        self.assertIn("already used", self.handoff("recover-report", *recovery, ok=False)["error"])
        saved = development.load(self.store)
        self.assertEqual(saved["attempts"], exhausted["attempts"])
        self.assertEqual(saved["handoffs"][batch["batch"]]["failures"]["1"], 3)
        self.assertNotIn("1", saved["handoffs"][batch["batch"]]["submitted"])

    @pytest.mark.stable_storage
    def test_interrupted_report_recovery_remains_consumed(self):
        self.init()
        batch = self.handoff("prepare")
        self.claim_handoff(batch)
        candidate = self.store / "candidate.json"
        candidate.write_text("{}")
        arguments = ("--batch", batch["batch"], "--job", 1, "--candidate", candidate)
        for _ in range(3):
            self.handoff("submit", *arguments, ok=False)
        candidate.write_text(json.dumps({
            "outcome": "blocked", "summary": "Existing failure",
            "evidence": ["Retained observation"], "data": {},
        }))
        recovery = (*arguments, "--evidence", "Inspected preserved candidate",
                    "--shutdown-evidence", "Original worker exited")
        with patch.object(handoffs, "write_candidate", side_effect=OSError("Fixture storage interruption")):
            self.assertIn("Fixture storage interruption",
                          self.handoff("recover-report", *recovery, ok=False)["error"])
        self.assertTrue(self.handoff("check-report", *arguments)["valid"])
        self.assertIn("already used", self.handoff("recover-report", *recovery, ok=False)["error"])
        record = development.load(self.store)["handoffs"][batch["batch"]]
        self.assertEqual(record["report_recoveries"]["1"]["outcome"], "attempted")
        self.assertEqual(record["failures"]["1"], 3)
        self.assertNotIn("1", record["submitted"])

    @pytest.mark.stable_storage
    def test_exhausted_report_can_be_recovered_once_without_repeating_effects(self):
        self.init()
        self.preflight()
        root = self.prepare()
        self.next()
        (root / "app.txt").write_text("after\n")
        self.finish()
        self.next()
        self.review(root)
        self.execute_fixture(self.next())
        batch = self.handoff("prepare")
        job = self.claim_handoff(batch)[0]
        self.assertEqual(job["role"], "draft")
        candidate = self.store / "draft-candidate.json"
        candidate.write_text(json.dumps({
            "outcome": "completed", "summary": "Existing draft found",
            "evidence": ["PR already exists; no push or creation repeated"], "data": {},
        }))
        for _ in range(3):
            self.handoff("submit", "--batch", batch["batch"], "--job", 1, "--candidate", candidate, ok=False)
        candidate.write_text(json.dumps({
            "outcome": "complete", "summary": "Existing draft found",
            "evidence": ["PR already exists; no push or creation repeated"],
            "data": {"commit": self.git("rev-parse", "HEAD", root=root),
                     "url": "https://example.invalid/pull/1", "state": "draft",
                     "evidence": "Observed existing draft at the current head"},
        }))
        rejected = self.handoff("submit", "--batch", batch["batch"], "--job", 1,
                                "--candidate", candidate, ok=False)
        self.assertIn("allowance exhausted", rejected["error"])
        before = development.load(self.store)
        head = self.git("rev-parse", "HEAD", root=root)
        arguments = ("--batch", batch["batch"], "--job", 1, "--candidate", candidate,
                     "--evidence", "Inspected existing PR and preserved candidate",
                     "--shutdown-evidence", "Offline worker has exited")
        checked = self.handoff("check-report", *arguments[:6])
        self.assertFalse(checked["accepted"])
        recovered = self.handoff("recover-report", *arguments)
        self.assertTrue(recovered["valid"])
        self.assertEqual(self.handoff("recover-report", *arguments), recovered)
        self.handoff("collect", "--batch", batch["batch"])
        saved = development.load(self.store)
        self.assertEqual(saved["attempts"], before["attempts"])
        self.assertEqual(len(saved["history"]), len(before["history"]))
        self.assertEqual(saved["history"][-1]["outcome"], "complete")
        self.assertEqual(saved["handoffs"][batch["batch"]]["failures"]["1"], 3)
        self.assertEqual(len(saved["handoffs"][batch["batch"]]["report_recoveries"]), 1)
        self.assertEqual(self.git("rev-parse", "HEAD", root=root), head)

    @pytest.mark.stable_storage
    def test_handoff_missing_report_cannot_become_success_or_repeat_dispatch(self):
        self.init()
        batch = self.handoff("prepare")
        self.handoff("claim", "--batch", batch["batch"])
        self.handoff("start", "--batch", batch["batch"], "--job", "1")
        result = self.handoff("collect", "--batch", batch["batch"], ok=False)
        self.assertEqual(result["kind"], "missing_report")
        self.assertFalse(development.load(self.store)["preflight"])
        self.assertEqual(self.handoff("prepare")["action"], "collect")
        self.assertEqual(self.cli("status", self.store)["consumed_assignments"], 1)

    @pytest.mark.stable_storage
    def test_handoff_correction_allowance_persists_and_optout_is_independent(self):
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                self.store = self.folder / ("correction-on" if enabled else "correction-off")
                config = Path(self.env["HOME"]) / ".claude/ioncache-ai-tools.local.json"
                config.parent.mkdir(parents=True, exist_ok=True)
                config.write_text(json.dumps({"features": {"autonomous-development-report-correction": enabled}}))
                self.init()
                batch = self.handoff("prepare")
                self.handoff("claim", "--batch", batch["batch"])
                self.handoff("start", "--batch", batch["batch"], "--job", "1")
                candidate = self.store / "candidate.json"
                candidate.write_text('{"invalid":')
                for _ in range(3 if enabled else 1):
                    failure = self.handoff("submit", "--batch", batch["batch"], "--job", "1",
                                           "--candidate", candidate, ok=False)
                    self.assertEqual(failure["kind"], "invalid_report")
                failed = self.handoff("submit", "--batch", batch["batch"], "--job", "1",
                                      "--candidate", candidate, ok=False)
                self.assertIn("allowance exhausted", failed["error"])
                self.assertEqual(self.handoff("prepare")["action"], "collect")
                self.assertEqual(self.cli("status", self.store)["consumed_assignments"], 1)
                archives = list((self.store / "handoffs" / batch["batch"]).glob("1-*.json"))
                self.assertEqual([item.read_text() for item in archives], ['{"invalid":'])
                self.assertFalse(development.load(self.store)["preflight"])

    @pytest.mark.process
    def test_handoff_script_and_executor_repairs_preserve_reservations(self):
        self.init()
        batch = self.handoff("prepare")
        script = Path(batch["script"])
        expected = script.read_bytes()
        script.write_text("throw new Error('changed script')\n")
        self.assertIn("Generated script changed", self.handoff("prepare", ok=False)["error"])
        self.handoff("repair-script", "--batch", batch["batch"])
        self.assertEqual(script.read_bytes(), expected)
        pinned = self.store / "executor/workflows/autonomous-development.js"
        expected_executor = pinned.read_bytes()
        pinned.write_text("changed executor\n")
        self.assertIn("Pinned executor changed", self.handoff("prepare", ok=False)["error"])
        self.state = self.cli("status", self.store)
        self.mutate("interrupt", "--reason", "Repair the pinned fixture with native workers stopped")
        self.handoff("restore-executor", "--source", SCRIPTS.parent,
                     "--shutdown-evidence", "Offline fixture, no native workers launched")
        self.assertEqual(pinned.read_bytes(), expected_executor)
        saved = development.load(self.store)
        self.assertEqual(len(saved["history"]), 1)
        self.assertEqual(saved["handoffs"][batch["batch"]]["status"], "prepared")
        self.assertTrue(list((self.store / "executor-recovery").glob("retained-*")))
        self.handoff("resume-prepared", "--batch", batch["batch"], "--reason", "Exact executor restored")
        self.handoff("claim", "--batch", batch["batch"])
        self.state = self.cli("status", self.store)
        self.mutate("interrupt", "--reason", "Claimed transport outcome unknown")
        self.assertIn("provably unclaimed", self.handoff(
            "resume-prepared", "--batch", batch["batch"], "--reason", "Cannot infer no launch", ok=False)["error"])

    @pytest.mark.stable_storage
    def test_handoff_rejects_unstarted_and_changed_reports(self):
        self.init()
        batch = self.handoff("prepare")
        self.handoff("claim", "--batch", batch["batch"])
        self.state = self.cli("status", self.store)
        self.report(outcome="blocked")
        self.assertIn("actually started", self.handoff("finish", "--batch", batch["batch"],
                                                       "--job", "1", ok=False)["error"])
        self.handoff("start", "--batch", batch["batch"], "--job", "1")
        self.handoff("finish", "--batch", batch["batch"], "--job", "1")
        self.report(outcome="complete")
        self.assertIn("Submitted report changed", self.handoff("collect", "--batch", batch["batch"], ok=False)["error"])
        self.assertIn("Submitted report changed", self.handoff("finish", "--batch", batch["batch"],
                                                              "--job", "1", ok=False)["error"])
        self.assertFalse(development.load(self.store)["preflight"])

    def test_handoff_claim_recovers_after_exact_worktree_restoration(self):
        self.init()
        batch = self.handoff("prepare")
        (self.root / "app.txt").write_text("unreviewed change\n")
        self.assertIn("Worktree drift", self.handoff("claim", "--batch", batch["batch"], ok=False)["error"])
        (self.root / "app.txt").write_text("before\n")
        self.handoff("claim", "--batch", batch["batch"])
        self.assertEqual(self.cli("status", self.store)["consumed_assignments"], 1)

    @pytest.mark.stable_storage
    def test_handoff_fixers_run_alone_and_return_to_owner_without_refunding_reservations(self):
        self.init()
        self.preflight()
        root = self.prepare()
        self.next()
        self.finish()
        owner = self.handoff("prepare")
        state = development.load(self.store)
        assignment = state["active"]["id"]
        requests = [{"role": role, "prompt": "Bounded fixture purpose",
                     "result_file": str(self.store / "reports" / assignment / f"leaf-{index}.json")}
                    for index, role in enumerate(("validator", "validator", "fixer", "validator"))]
        self.state = self.cli("status", self.store)
        records, phase = self.review_records(root, "fixture-snapshot")
        requests[2]["writing_plan"] = {"path": records["plan"], "identity": phase["identity"]}

        def finish_batch(batch, reports):
            self.handoff("claim", "--batch", batch["batch"])
            record = development.load(self.store)["handoffs"][batch["batch"]]
            for number, (job, report) in enumerate(zip(record["spec"]["jobs"], reports), 1):
                self.handoff("start", "--batch", batch["batch"], "--job", number)
                if job["role"] == "fixer":
                    (root / "app.txt").write_text("corrected\n")
                Path(job["result_file"]).write_bytes(manifest.encode(report))
                self.handoff("finish", "--batch", batch["batch"], "--job", number)
            self.handoff("collect", "--batch", batch["batch"])

        finish_batch(owner, [{"outcome": "dispatch", "requests": requests, "result_file": ""}])
        readers = self.handoff("prepare")
        record = development.load(self.store)["handoffs"][readers["batch"]]
        self.assertEqual([job["role"] for job in record["spec"]["jobs"]], ["validator", "validator"])
        finished = {"outcome": "complete", "summary": "Existing fixture evidence checked"}
        finish_batch(readers, [finished, finished])
        fixer = self.handoff("prepare")
        record = development.load(self.store)["handoffs"][fixer["batch"]]
        self.assertEqual([job["role"] for job in record["spec"]["jobs"]], ["fixer"])
        finish_batch(fixer, [finished])
        checkpoint = development.load(self.store)["active"]["review_dispatch"]
        reserved = checkpoint["reservations"][requests[-1]["result_file"]]
        self.assertFalse(reserved["started"])
        self.assertEqual(checkpoint["reports"][-1]["outcome"], "not_started")
        next_owner = self.handoff("prepare")
        record = development.load(self.store)["handoffs"][next_owner["batch"]]
        self.assertEqual([job["role"] for job in record["spec"]["jobs"]], ["review-owner"])
        finish_batch(next_owner, [{"outcome": "dispatch", "requests": [requests[-1]], "result_file": ""}])
        latest = development.load(self.store)["active"]["review_dispatch"]
        self.assertEqual(latest["calls"], checkpoint["calls"] + 1)
        self.assertEqual(latest["reservations"][requests[-1]["result_file"]], reserved)

    @pytest.mark.stable_storage
    def test_workflow_accepts_required_files_absent_from_legacy_hints(self):
        self.init()
        self.preflight()
        root = self.prepare()
        self.workflow("scope")
        saved = json.loads((self.store / "RUN.json").read_bytes())
        implementations = [item for item in saved["history"] if item["role"] == "implement"]
        self.assertEqual([item["outcome"] for item in implementations], ["complete"])
        self.assertEqual(self.state["consumed_assignments"], 4)
        self.assertEqual(self.state["prs"]["first"]["position"], 2)
        self.assertEqual((root / "unapproved.txt").read_text(), "after\n")
        self.assertEqual((root / "app.txt").read_text(), "before\n")
        self.assertEqual(saved["manifest"]["tasks"][0]["paths"], ["app.txt"])

    @pytest.mark.stable_storage
    def test_tasks_without_predicted_paths_review_all_discovered_changes(self):
        del self.plan["tasks"][0]["paths"]
        self.init()
        self.preflight()
        root = self.prepare()
        self.assertNotIn("paths", self.next()["task_plan"])
        (root / "dependency.txt").write_text("Required by the task\n")
        self.finish()
        self.next()
        self.review(root)
        self.assertEqual(self.next()["role"], "commit")

    def test_review_storage_recovery_moves_complete_evidence_without_another_attempt(self):
        root = self.start_review_fixture()
        data = self.review(root, record=False)
        original = Path(data["ledger"])
        alternate = self.folder / "other-reviews" / original.parent.parent.name / original.parent.name
        alternate.parent.mkdir(parents=True)
        original.parent.rename(alternate)
        before = self.state["consumed_assignments"]
        data["ledger"] = str(alternate / original.name)
        self.assertIn("pinned review_storage", self.finish(data, ok=False))
        alternate.rename(original.parent)
        data["ledger"] = str(original)
        self.finish(data)
        self.assertEqual(self.state["consumed_assignments"], before)
        self.assertEqual(self.next()["role"], "commit")

    def test_active_review_recovers_ineligible_storage_without_another_attempt(self):
        self.store = self.folder / "later-repository" / "run"
        root = self.start_review_fixture()
        data = self.review(root, record=False, finding=True, advance=False)
        original = Path(data["ledger"])
        before = development.load(self.store)
        files = development.review.stored_files(original.parent)
        self.git("init", "-q", str(self.store.parent))
        self.assertIn("recover-review-storage", self.finish(data, ok=False))
        self.mutate("recover-review-storage", "--ledger", str(original),
                    "--reason", "Storage became a repository", "--shutdown-evidence", "Workers exited")
        recovered = Path(self.state["assignment"]["recovered_ledger"])
        self.assertTrue(recovered.is_relative_to(Path(self.env["XDG_STATE_HOME"])))
        self.assertEqual(development.review.stored_files(recovered.parent), files)
        after = development.load(self.store)
        self.assertEqual(after["attempts"], before["attempts"])
        self.assertEqual(after["approval"], before["approval"])
        self.assertEqual(after["manifest"], before["manifest"])
        self.assertEqual(after["history"][:-1], before["history"][:-1])
        self.assertEqual(after["active"]["id"], before["active"]["id"])
        self.assertEqual(after["active"], after["history"][-1])
        self.assertEqual(self.state["consumed_assignments"], len(before["history"]))
        saved = self.review_cli(root, ["status", str(recovered)])
        self.review_cli(root, ["apply", str(recovered), "--revision", str(saved["revision"])],
                        {"type": "advance", "actor": "fixture-owner", "reason": "Resume retained review"})
        data["ledger"] = str(recovered)
        self.finish(data)
        self.assertEqual(self.state["consumed_assignments"], len(before["history"]))
        self.assertEqual(self.next()["role"], "commit")
        with patch.dict(os.environ, self.env, clear=True):
            with self.assertRaisesRegex(development.review.LedgerError, "outside every repository"):
                development.review.ledger_path(root, str(original))
        self.assertEqual(development.review.stored_files(original.parent), files)

    def assert_workflow_storage_continues(self, progress_enabled):
        self.store = self.folder / "later-repository" / "run"
        self.init()
        config = Path(self.env["HOME"]) / ".claude/ioncache-ai-tools.local.json"
        config.write_text(json.dumps({"features": {"autonomous-development-progress": progress_enabled}}))
        self.preflight()
        root = self.prepare()
        self.next()
        self.execute_fixture(self.state["assignment"])
        self.workflow("review-throw")
        before = development.load(self.store)
        spent = before["active"]["review_dispatch"]
        self.assertGreater(spent["calls"], 1)
        original = Path(json.loads((self.store / "reports/workflow-review.json").read_bytes())["ledger"])
        evidence = development.review.stored_files(original.parent)
        self.assertEqual(self.state["outcome"], "blocked")
        self.git("init", "-q", str(self.store.parent))
        self.mutate("recover-review-storage", "--ledger", str(original),
                    "--reason", "Storage became a repository", "--shutdown-evidence", "Fixture workers exited")
        recovered = Path(self.state["assignment"]["recovered_ledger"])
        self.handoff("prepare")
        previous = before["handoffs"][before["active"]["handoff"]]
        self.handoff("claim", "--batch", previous["id"], ok=False)
        self.handoff("start", "--batch", previous["id"], "--job", 1, ok=False)
        self.handoff("submit", "--batch", previous["id"], "--job", 1,
                     "--candidate", previous["spec"]["jobs"][0]["result_file"], ok=False)
        roles = self.workflow("review-recovered")
        self.assertIn("review-owner", roles)
        self.assertNotIn("reviewer", roles)
        self.assertIn("commit", roles)
        saved = development.load(self.store)
        reviewed = next(item for item in saved["history"] if item["id"] == before["active"]["id"])
        self.assertEqual(reviewed["outcome"], "complete")
        self.assertEqual(reviewed["attempt"], before["active"]["attempt"])
        self.assertEqual(reviewed["review_dispatch"]["calls"], spent["calls"] + 1)
        self.assertEqual(reviewed["review_dispatch"]["reservations"], spent["reservations"])
        self.assertFalse(reviewed["review_resume_ready"])
        self.assertEqual(reviewed["report"]["data"]["ledger"], str(recovered))
        self.assertEqual(saved["attempts"][reviewed["key"]], before["attempts"][reviewed["key"]])
        self.assertEqual(development.review.stored_files(original.parent), evidence)
        with patch.dict(os.environ, self.env, clear=True):
            with self.assertRaisesRegex(development.review.LedgerError, "outside every repository"):
                development.review.ledger_path(root, str(original))

    def test_workflow_continues_recovered_review_without_retirement(self):
        self.assert_workflow_storage_continues(True)

    def test_workflow_storage_recovery_keeps_accounting_when_progress_disabled(self):
        self.assert_workflow_storage_continues(False)

    def test_review_continuation_claim_requires_shutdown_and_is_one_use(self):
        root = self.start_review_fixture()
        data = self.review(root, record=False, advance=False)
        original = (self.store / "RUN.json").read_bytes()
        self.assertIn("shutdown evidence", self.mutate("claim-review", ok=False))
        arguments = ("--ledger", data["ledger"], "--reason", "Reconciled interruption",
                     "--shutdown-evidence", "Native fixture workers exited")
        for setting in ("autonomous-development", "skill:autonomous-development"):
            config = Path(self.env["HOME"]) / ".claude/ioncache-ai-tools.local.json"
            config.write_text(json.dumps({"features": {setting: False}}))
            self.assertIn("disabled", self.mutate("resume-review", *arguments, ok=False))
        self.assertEqual((self.store / "RUN.json").read_bytes(), original)
        config.write_text('{"features": {}}')
        self.mutate("interrupt", "--reason", "Native worker stopped")
        self.mutate("resume-review", *arguments)
        assignment = self.state["assignment"]
        self.assertTrue(assignment["review_resume_ready"])
        self.mutate("claim-review", "--provider", "claude-workflows")
        self.assertEqual(self.state["outcome"], "running")
        self.assertFalse(self.state["assignment"]["review_resume_ready"])
        self.assertIn("shutdown evidence", self.mutate("claim-review", ok=False))
        self.mutate("interrupt", "--reason", "Lost claim response before dispatch")
        self.mutate("resume-review", *arguments)
        self.mutate("claim-review", "--provider", "claude-workflows")
        self.assertEqual(self.state["assignment"]["id"], assignment["id"])
        self.assertEqual(self.state["assignment"]["review_dispatch"], assignment["review_dispatch"])
        self.assertEqual(len(self.state["assignment"]["review_resumptions"]), 2)

    def assert_unwitnessed_continuation_recovers(self, damage, *, relocate=False):
        import review_history

        if relocate:
            self.store = self.folder / "later-repository" / "run"
        root = self.start_review_fixture()
        data = self.review(root, record=False, advance=False)
        path = Path(data["ledger"])
        original = path.read_bytes()
        checkpoint = {"assignment": self.state["assignment"]["id"], "calls": 3,
                      "reservations": {}, "reports": []}
        self.mutate("review-checkpoint", stdin=checkpoint)
        arguments = ("--ledger", str(path), "--reason", "Recover interrupted review",
                     "--shutdown-evidence", "Synchronous fixture workers exited")
        self.mutate("resume-review", *arguments)
        if damage == "stale":
            saved = self.review_cli(root, ["status", str(path)])
            self.review_cli(root, ["apply", str(path), "--revision", str(saved["revision"])], {
                "type": "stop", "outcome": "failed", "actor": "fixture-owner",
                "reason": "A newer terminal event must not disappear during recovery",
            })
            path.write_bytes(original)
        else:
            with patch.dict(os.environ, self.env, clear=True):
                review_history.witness_path(root, path.parent.name).unlink()
        before = (self.store / "RUN.json").read_bytes()
        if relocate:
            self.git("init", "-q", str(self.store.parent))
            self.assertIn("freshness", self.mutate("recover-review-storage", *arguments, ok=False))
            target = self.folder / "retained" / path.parent.parent.name / path.parent.name
            development.shutil.copytree(path.parent, target)
            path = target / path.name
        else:
            self.assertIn("freshness", self.mutate("resume-review", *arguments, ok=False))
            self.assertIn("freshness", self.mutate("claim-review", ok=False))
        self.assertEqual((self.store / "RUN.json").read_bytes(), before)
        self.assertEqual(self.state["assignment"]["review_dispatch"]["calls"], 3)
        closed = self.review_cli(root, [
            "abandon", str(path), "--reason", "Freshness cannot be established",
            "--evidence", "The independent witness is missing or newer than this copy",
            "--shutdown-evidence", "Synchronous fixture workers exited",
        ])
        self.assertEqual(closed["allowance"], "unavailable")
        if relocate:
            self.review_cli(root, [
                "recover-ownership", str(path), "--reason", "Retain the closed external copy",
                "--shutdown-evidence", "Synchronous fixture workers exited",
            ])
        else:
            self.assertIn("abandoned", self.mutate("claim-review", ok=False))
        self.finish(outcome="blocked")
        self.mutate("resume", "--reason", "A separate counted review is permitted")
        retry = self.next()
        self.assertEqual((retry["role"], retry["attempt"]), ("review", 2))
        previous = development.load(self.store)["history"][-2]
        self.assertEqual(previous["review_dispatch"]["calls"], 3)
        self.assertEqual(path.read_bytes(), original)
        self.review(root)
        self.assertEqual(self.next()["role"], "commit")

    def test_stale_review_cannot_arm_or_consume_continuation(self):
        self.assert_unwitnessed_continuation_recovers("stale")

    def test_missing_witness_cannot_arm_or_consume_continuation(self):
        self.assert_unwitnessed_continuation_recovers("missing")

    def test_stale_review_cannot_recover_storage_as_ready(self):
        self.assert_unwitnessed_continuation_recovers("stale", relocate=True)

    def test_missing_witness_cannot_recover_storage_as_ready(self):
        self.assert_unwitnessed_continuation_recovers("missing", relocate=True)

    def test_review_continuation_keeps_ownership_through_save(self):
        self.store = self.folder / "later-repository" / "run"
        root = self.start_review_fixture()
        data = self.review(root, record=False, advance=False)
        original = Path(data["ledger"])
        revision = len(json.loads(original.read_bytes())["events"])
        save = development.save
        attempts = []

        def save_with_competing_closure(folder, state):
            active = state["active"]
            ledger = active["storage_recoveries"][-1]["ledger"] if active.get("storage_recoveries") else str(original)
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "review_ledger.py"), "apply", ledger,
                 "--revision", str(revision)], cwd=root, env=self.env, text=True,
                input=json.dumps({"type": "stop", "outcome": "failed", "actor": "fixture-owner",
                                  "reason": "Competing with continuation publication"}),
                capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("temporarily unavailable", result.stderr)
            attempts.append(ledger)
            save(folder, state)

        arguments = ["--ledger", str(original), "--reason", "Reconcile interrupted review",
                     "--shutdown-evidence", "Synchronous fixture workers exited"]
        with patch.dict(os.environ, self.env, clear=True), \
                patch.object(development, "save", save_with_competing_closure):
            for command in ("resume-review", "claim-review", "recover-review-storage"):
                if command == "recover-review-storage":
                    self.git("init", "-q", str(self.store.parent))
                args = development.parser().parse_args([
                    command, str(self.store), "--revision", str(self.state["revision"]),
                    *(arguments if command != "claim-review" else [])])
                self.state = development.mutate(args, self.store)
        self.assertEqual(len(attempts), 3)
        recovered = self.state["assignment"]["recovered_ledger"]
        self.mutate("claim-review")
        saved = self.review_cli(root, ["status", recovered])
        self.assertEqual(saved["revision"], revision)
        self.review_cli(root, ["apply", recovered, "--revision", str(revision)], {
            "type": "advance", "actor": "fixture-owner", "reason": "Continue the retained review",
        })
        self.finish({**data, "ledger": recovered})
        self.assertEqual(self.next()["role"], "commit")

    def test_review_dispatch_checkpoints_retain_spending_and_reservations(self):
        root = self.start_review_fixture()
        ledger = self.review(root, record=False, advance=False)["ledger"]
        assignment = self.state["assignment"]
        path = str(self.store / "reports" / assignment["id"] / "reserved.json")
        checkpoint = {"assignment": assignment["id"], "calls": 2, "reservations": {
            path: {"dispatch": 2, "started": True, "role": "reviewer", "identity": "frozen-request"},
        }, "reports": [{"role": "reviewer", "result_file": path, "outcome": "interrupted"}]}
        self.mutate("review-checkpoint", stdin=checkpoint)
        saved = (self.store / "RUN.json").read_bytes()
        invalid = []
        for calls in (1, self.plan["limits"]["review_dispatches"] + 1):
            invalid.append({**checkpoint, "calls": calls})
        invalid.extend(({**checkpoint, "reservations": {}}, {**checkpoint, "reports": []}))
        for key, value in (("dispatch", 1), ("started", False), ("identity", "replacement")):
            changed = copy.deepcopy(checkpoint)
            changed["reservations"][path][key] = value
            invalid.append(changed)
        for payload in invalid:
            with self.subTest(payload=payload):
                self.mutate("review-checkpoint", stdin=payload, ok=False)
                self.assertEqual((self.store / "RUN.json").read_bytes(), saved)
        checkpoint["calls"] = self.plan["limits"]["review_dispatches"]
        self.mutate("review-checkpoint", stdin=checkpoint)
        self.mutate("interrupt", "--reason", "All remaining calls were consumed")
        self.mutate("resume-review", "--ledger", ledger, "--reason", "Collect retained outcome",
                    "--shutdown-evidence", "Native workers exited")
        roles = self.workflow("review-recovered")
        self.assertNotIn("review-owner", roles)
        self.assertIn("allowance exhausted", self.state["reason"])
        self.assertEqual(self.state["assignment"]["review_dispatch"]["calls"], checkpoint["calls"])

    def test_review_dispatch_rejects_filesystem_aliases_before_reserving(self):
        self.start_review_fixture()
        assignment = self.state["assignment"]
        path = str(self.store / "reports" / assignment["id"] / "pass.json")
        checkpoint = {"assignment": assignment["id"], "calls": 3, "reservations": {
            path: {"dispatch": 2, "started": True, "role": "reviewer", "identity": "first"},
            path.replace("/pass.json", "//pass.json"): {
                "dispatch": 3, "started": True, "role": "reviewer", "identity": "second"},
        }, "reports": []}
        before = (self.store / "RUN.json").read_bytes()
        self.assertIn("normalized", self.mutate("review-checkpoint", stdin=checkpoint, ok=False))
        self.assertEqual((self.store / "RUN.json").read_bytes(), before)
        checkpoint["reservations"][path.replace("pass.json", "other.json")] = (
            checkpoint["reservations"].pop(path.replace("/pass.json", "//pass.json")))
        self.mutate("review-checkpoint", stdin=checkpoint)
        self.assertEqual(len(self.state["assignment"]["review_dispatch"]["reservations"]), 2)

    def test_existing_aliased_reservation_keeps_its_spending_without_blocking_recovery(self):
        self.start_review_fixture()
        state = development.load(self.store)
        active = state["active"]
        path = str(self.store / "reports" / active["id"]) + "//pass.json"
        checkpoint = {"calls": 2, "reservations": {
            path: {"dispatch": 2, "started": False, "role": "reviewer",
                   "identity": development.review.digest(b"older frozen request")},
        }, "reports": []}
        active["review_dispatch"] = copy.deepcopy(checkpoint)
        state["history"][-1] = active
        development.save(self.store, state)
        checkpoint.update(assignment=active["id"], calls=3)
        self.mutate("review-checkpoint", stdin=checkpoint)
        canonical = str(Path(path))
        checkpoint["calls"] = 4
        checkpoint["reservations"][canonical] = {
            "dispatch": 4, "started": True, "role": "reviewer", "identity": "replacement"}
        self.assertIn("already reserved", self.mutate("review-checkpoint", stdin=checkpoint, ok=False))
        checkpoint["reservations"][canonical.replace("pass.json", "replacement.json")] = (
            checkpoint["reservations"].pop(canonical))
        self.mutate("review-checkpoint", stdin=checkpoint)
        self.assertEqual(self.state["assignment"]["review_dispatch"]["calls"], 4)
        self.assertIn(path, self.state["assignment"]["review_dispatch"]["reservations"])

    def test_legacy_review_reentry_requires_explicit_dispatch_reconciliation(self):
        root = self.start_review_fixture()
        ledger = self.review(root, record=False, advance=False)["ledger"]
        state = development.load(self.store)
        del state["active"]["review_dispatch"]
        state["history"][-1] = state["active"]
        development.save(self.store, state)
        args = ("--ledger", ledger, "--reason", "Reconcile retained native history",
                "--shutdown-evidence", "Native workers exited")
        self.mutate("resume-review", *args, ok=False)
        self.mutate("resume-review", *args, "--used-dispatches", "4",
                    "--dispatch-evidence", "Native history retains four charged owner/leaf slots")
        self.assertEqual(self.state["assignment"]["review_dispatch"]["calls"], 4)
        self.assertIn("cannot be replaced", self.mutate(
            "resume-review", *args, "--used-dispatches", "0", "--dispatch-evidence", "Reset", ok=False))
        self.mutate("claim-review", "--provider", "claude-workflows")
        self.assertEqual(self.state["assignment"]["review_dispatch"]["calls"], 4)

    def test_active_storage_recovery_retries_after_run_save_failure(self):
        self.store = self.folder / "later-repository" / "run"
        root = self.start_review_fixture()
        data = self.review(root, record=False, finding=True)
        original = Path(data["ledger"])
        files = development.review.stored_files(original.parent)
        run_bytes = (self.store / "RUN.json").read_bytes()
        self.git("init", "-q", str(self.store.parent))
        args = SimpleNamespace(command="recover-review-storage", revision=self.state["revision"],
                               ledger=str(original), reason="Storage moved", shutdown_evidence="Workers exited")
        with patch.dict(os.environ, self.env, clear=True), patch.object(
                development, "save", side_effect=OSError("Interrupted state publication")):
            with self.assertRaisesRegex(OSError, "Interrupted state publication"):
                development.mutate(args, self.store)
        self.assertEqual((self.store / "RUN.json").read_bytes(), run_bytes)
        self.mutate("recover-review-storage", "--ledger", str(original),
                    "--reason", args.reason, "--shutdown-evidence", args.shutdown_evidence)
        recovered = Path(self.state["assignment"]["recovered_ledger"])
        self.assertEqual(development.review.stored_files(recovered.parent), files)
        self.assertEqual(len(self.state["assignment"]["storage_recoveries"]), 1)
        self.assertEqual(development.review.stored_files(original.parent), files)
        data["ledger"] = str(recovered)
        self.finish(data)
        self.assertEqual(self.next()["role"], "commit")

    def test_active_storage_recovery_rejects_corruption_and_invalid_destination(self):
        self.store = self.folder / "later-repository" / "run"
        root = self.start_review_fixture()
        data = self.review(root, record=False)
        original = Path(data["ledger"])
        run_bytes = (self.store / "RUN.json").read_bytes()
        self.git("init", "-q", str(self.store.parent))
        arguments = ("--ledger", str(original), "--reason", "Storage moved",
                     "--shutdown-evidence", "Workers exited")
        xdg = self.env["XDG_STATE_HOME"]
        self.env["XDG_STATE_HOME"] = str(self.store.parent / "state")
        self.assertIn("outside every repository", self.mutate(
            "recover-review-storage", *arguments, ok=False))
        self.env["XDG_STATE_HOME"] = xdg
        blob = next((original.parent / "objects").iterdir())
        contents = blob.read_bytes()
        blob.write_bytes(b"corrupt")
        self.assertIn("history unavailable", self.mutate("recover-review-storage", *arguments, ok=False))
        self.assertEqual((self.store / "RUN.json").read_bytes(), run_bytes)
        blob.write_bytes(contents)
        self.mutate("recover-review-storage", *arguments)
        data["ledger"] = self.state["assignment"]["recovered_ledger"]
        self.finish(data)
        self.assertEqual(self.next()["role"], "commit")

    def test_active_storage_recovery_requires_owned_ineligible_storage_and_enabled_feature(self):
        self.store = self.folder / "later-repository" / "run"
        root = self.start_review_fixture()
        data = self.review(root, record=False)
        original = Path(data["ledger"])
        arguments = ("--reason", "Storage moved", "--shutdown-evidence", "Workers exited")
        before = (self.store / "RUN.json").read_bytes()
        self.assertIn("already eligible", self.mutate(
            "recover-review-storage", "--ledger", str(original), *arguments, ok=False))
        other = self.folder / "other" / original.parent.parent.name / original.parent.name
        development.shutil.copytree(original.parent, other)
        self.assertIn("pinned review_storage", self.mutate(
            "recover-review-storage", "--ledger", str(other / original.name), *arguments, ok=False))
        self.git("init", "-q", str(self.store.parent))
        config = Path(self.env["HOME"]) / ".claude/ioncache-ai-tools.local.json"
        for setting in ("autonomous-development", "skill:autonomous-development"):
            config.write_text(json.dumps({"features": {setting: False}}))
            self.assertIn("disabled", self.mutate(
                "recover-review-storage", "--ledger", str(original), *arguments, ok=False))
        self.assertEqual((self.store / "RUN.json").read_bytes(), before)
        config.write_text('{"features": {}}')
        self.mutate("recover-review-storage", "--ledger", str(original), *arguments)
        data["ledger"] = self.state["assignment"]["recovered_ledger"]
        self.finish(data)

    def test_active_storage_recovery_preserves_busy_source_and_conflicting_destination(self):
        self.store = self.folder / "later-repository" / "run"
        root = self.start_review_fixture()
        data = self.review(root, record=False)
        original = Path(data["ledger"])
        before = (self.store / "RUN.json").read_bytes()
        self.git("init", "-q", str(self.store.parent))
        arguments = ("--ledger", str(original), "--reason", "Storage moved",
                     "--shutdown-evidence", "Workers exited")
        destination = (Path(self.env["XDG_STATE_HOME"]) / "ioncache-ai-tools/development-recovery" /
                       self.state["run"] / "reviews" / original.parent.parent.name / original.parent.name)
        with (original.parent.parent / ".lock").open("rb") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.mutate("recover-review-storage", *arguments, ok=False)
            self.assertFalse(destination.exists())
        destination.mkdir(parents=True)
        conflicting = destination / original.name
        conflicting.write_bytes(b"Retained conflicting evidence\n")
        self.assertIn("conflicts", self.mutate("recover-review-storage", *arguments, ok=False))
        self.assertEqual(conflicting.read_bytes(), b"Retained conflicting evidence\n")
        self.assertEqual((self.store / "RUN.json").read_bytes(), before)
        self.env["XDG_STATE_HOME"] = str(self.folder / "recovery-state")
        self.mutate("recover-review-storage", *arguments)
        data["ledger"] = self.state["assignment"]["recovered_ledger"]
        self.finish(data)
        self.assertEqual(conflicting.read_bytes(), b"Retained conflicting evidence\n")

    @pytest.mark.stable_storage
    def test_workflow_native_failures_preserve_workers_effects_and_allowance(self):
        self.plan["limits"]["attempts"] = 3
        self.init()
        self.preflight()
        root = self.prepare()
        for scenario in ("throw", "missing"):
            self.workflow(scenario)
            self.assertEqual(self.state["outcome"], "blocked")
            self.assertIsNotNone(self.state["assignment"])
            self.assertEqual((root / "app.txt").read_text(), "after\n")
            consumed = self.state["consumed_assignments"]
            self.assertEqual(self.workflow("complete"), [])
            self.assertEqual(self.state["consumed_assignments"], consumed)
            self.mutate("resume", "--reason", "Worker shutdown not reconciled", ok=False)
            self.retire_fixture()
        self.workflow("complete")
        self.assertEqual(self.state["prs"]["first"]["position"], 2)
        self.assertEqual(self.state["consumed_assignments"], 6)

    @pytest.mark.stable_storage
    def test_workflow_input_loss_keeps_shutdown_and_corrected_work_reachable(self):
        self.init()
        self.preflight()
        self.prepare()
        self.workflow("missing-input")
        self.assertEqual(self.state["outcome"], "blocked")
        self.assertIn("regular file", self.state["input_error"])
        self.mutate("retire", "--reason", "Reconciled the interrupted fixture",
                    "--shutdown-evidence", "The synchronous fixture process exited")
        self.mutate("resume", "--reason", "Inputs still missing", ok=False)
        (self.store / "inputs/design.md").write_bytes((self.bundle / "design.md").read_bytes())
        self.mutate("resume", "--reason", "Restored exact approved input")
        self.workflow("complete")
        self.assertEqual(self.state["prs"]["first"]["position"], 2)
        self.assertEqual(self.state["consumed_assignments"], 5)

    def assert_workflow_review_recovers(self, scenario, reason):
        self.plan["limits"].update(attempts=3, review_loops=3)
        self.init()
        self.preflight()
        root = self.prepare()
        self.next()
        self.execute_fixture(self.state["assignment"])
        ledger = None
        for attempt in (1, 2):
            roles = self.workflow(scenario)
            self.assertEqual(self.state["outcome"], "blocked")
            self.assertIn(reason, self.state["reason"])
            self.assertEqual(self.state["assignment"]["attempt"], attempt)
            if scenario != "review-throw":
                self.assertNotIn("reviewer", roles)
            with patch.dict(os.environ, self.env, clear=True):
                histories = audit.review_locations(development.load(self.store), self.state["assignment"])
            self.assertEqual(len(histories), 1)
            ledger = histories[0]
            retained = ledger.read_bytes()
            consumed = self.state["consumed_assignments"]
            self.assertEqual(self.workflow("review-complete"), [])
            self.assertEqual(ledger.read_bytes(), retained)
            self.assertEqual(self.state["consumed_assignments"], consumed)
            self.mutate("resume", "--reason", "Worker shutdown not reconciled", ok=False)
            self.retire_fixture()
            self.assertEqual(ledger.read_bytes(), retained)
        roles = self.workflow("review-complete")
        self.assertIn("reviewer", roles)
        self.assertIn("commit", roles, self.state["reason"])
        self.assertEqual(self.state["prs"]["first"]["position"], 3)
        self.assertEqual(self.state["consumed_assignments"], 7)
        self.assertEqual(self.state["limits"], self.plan["limits"])
        saved = json.loads((self.store / "RUN.json").read_bytes())
        reviews = [item for item in saved["history"] if item["role"] == "review"]
        self.assertEqual([item["outcome"] for item in reviews], ["retired", "retired", "complete"])
        status = self.review_cli(root, ["status", str(ledger)])
        self.assertEqual(status["outcome"], "completed")
        self.assertEqual(len(status["loops"]), 3)
        self.assertTrue(all(loop["invalidated"] for loop in status["loops"][:2]))
        self.assertEqual((root / "app.txt").read_text(), "after\n")

    @pytest.mark.stable_storage
    def test_workflow_review_path_denial_recovers_with_persisted_history(self):
        self.assert_workflow_review_recovers("review-path", "outside the assigned private directory")

    @pytest.mark.stable_storage
    def test_workflow_review_packet_denial_recovers_with_persisted_history(self):
        self.assert_workflow_review_recovers("review-missing-packet", "frozen single-purpose packet")

    @pytest.mark.stable_storage
    def test_workflow_review_budget_denial_recovers_without_refunding_limits(self):
        self.assert_workflow_review_recovers("review-budget", "allowance cannot cover")

    @pytest.mark.stable_storage
    def test_workflow_review_native_failure_requires_shutdown_before_retry(self):
        self.assert_workflow_review_recovers("review-throw", "Fixture review native call failed")

    def test_workflow_lost_review_store_requires_release_and_counted_retry(self):
        self.init()
        self.preflight()
        root = self.prepare()
        self.next()
        self.execute_fixture(self.state["assignment"])
        self.workflow("review-throw")
        before = development.load(self.store)
        old = before["active"]
        source = Path(old["review_storage"])
        development.shutil.rmtree(source)
        destination = self.folder / "replacement" / source.name
        self.review_cli(root, ["release-ownership", "--storage", str(source),
                              "--replacement-storage", str(destination),
                              "--reason", "Whole fixture store was lost",
                              "--shutdown-evidence", "Synchronous fixture workers exited"])
        self.assertEqual(self.workflow("review-complete"), [])
        self.assertEqual(development.load(self.store)["active"], old)
        self.retire_fixture()
        saved_report = self.store / "reports/workflow-review.json"
        saved_report.rename(saved_report.with_name("lost-workflow-review.json"))
        roles = self.workflow("review-complete")
        self.assertIn("reviewer", roles)
        self.assertIn("commit", roles)
        after = development.load(self.store)
        reviews = [item for item in after["history"] if item["role"] == "review"]
        self.assertEqual([item["attempt"] for item in reviews], [1, 2])
        self.assertEqual([item["outcome"] for item in reviews], ["retired", "complete"])
        self.assertEqual(reviews[0]["review_dispatch"], old["review_dispatch"])
        self.assertNotEqual(reviews[1]["review_storage"], str(source))
        self.assertEqual(after["manifest"]["limits"], before["manifest"]["limits"])
        self.assertFalse(source.exists())

    def test_returning_released_review_cannot_resume_or_satisfy_acceptance(self):
        root = self.start_review_fixture()
        data = self.review(root, record=False)
        path = Path(data["ledger"])
        original = path.read_bytes()
        source = path.parent.parent
        hidden = self.folder / "unmounted-review-store"
        source.rename(hidden)
        self.review_cli(root, ["release-ownership", "--storage", str(source),
                              "--replacement-storage", str(self.folder / "replacement" / source.name),
                              "--reason", "Review store unavailable",
                              "--shutdown-evidence", "Synchronous fixture workers exited"])
        hidden.rename(source)
        self.assertIn("released", self.finish(data, ok=False))
        self.assertIn("released", self.mutate(
            "resume-review", "--ledger", str(path), "--reason", "Old store reappeared",
            "--shutdown-evidence", "Fixture workers exited", ok=False))
        with patch.dict(os.environ, self.env, clear=True):
            exported = audit.review_record(path, root)
        self.assertFalse(exported["available"])
        self.assertEqual(exported["outcome"], "failed")
        self.assertEqual(exported["allowance"], "unavailable")
        self.retire_fixture()
        self.assertEqual(self.next()["attempt"], 2)
        self.review(root)
        self.assertEqual(self.next()["role"], "commit")
        self.assertEqual(path.read_bytes(), original)

    def release_accepted_review(self, root, *, ledger=None):
        reviewed = development.load(self.store)["prs"]["first"]["review"]
        source = Path(ledger or reviewed["ledger"]).parent.parent
        development.shutil.rmtree(source)
        return self.review_cli(root, [
            "release-ownership", "--storage", str(source),
            "--replacement-storage", str(self.folder / "replacement" / source.name),
            "--reason", "Accepted review history was lost",
            "--shutdown-evidence", "Synchronous fixture workers exited",
        ])

    def close_accepted_review(self, root, closure="stop", *, ledger=None):
        reviewed = development.load(self.store)["prs"]["first"]["review"]
        path = Path(ledger or reviewed["ledger"])
        if closure == "release":
            return self.release_accepted_review(root, ledger=path)
        if closure != "stop":
            if closure == "abandon":
                path.unlink()
            else:
                (path.parent / "ABANDONED.json").write_bytes(b"damaged closure")
            return self.review_cli(root, [
                closure, str(path),
                "--reason", "Invalidate accepted fixture evidence",
                "--evidence", "Inspected fixture history and closure",
                "--shutdown-evidence", "Synchronous fixture workers exited",
            ])
        status = self.review_cli(root, ["status", str(path)])
        return self.review_cli(root, ["apply", str(path), "--revision", str(status["revision"])], {
            "type": "stop", "outcome": "failed", "actor": "fixture-owner",
            "reason": "Withdraw accepted fixture review",
        })

    def assert_closed_cached_review_recovers(self, closure="stop", *, missing_blob=False, recovered=False):
        root = self.start_review_fixture()
        (root / "app.txt").write_text("reviewed change\n")
        data = self.review(root)
        path = Path(data["ledger"])
        original = development.load(self.store)
        if recovered:
            target = self.folder / "retained-review" / path.parent.parent.name / path.parent.name
            target.parent.mkdir(parents=True)
            path.parent.rename(target)
            path = target / path.name
            self.review_cli(root, [
                "recover-ownership", str(path), "--reason", "Relocate retained completed history",
                "--shutdown-evidence", "Synchronous fixture workers exited",
            ])
        self.close_accepted_review(root, closure, ledger=path)
        if recovered:
            other = self.review_cli(root, [
                "init", "--objective", "Separate fixture review", "--scope", "fixture",
                "--storage", str(self.folder / "other-review" / path.parent.parent.name),
            ])
            self.review_cli(root, ["apply", other["ledger"], "--revision", str(other["revision"])], {
                "type": "stop", "outcome": "failed", "actor": "fixture-owner",
                "reason": "Finish the separately owned fixture without approval",
            })
            self.env["XDG_STATE_HOME"] = str(self.folder / "changed-state-home")
        if missing_blob:
            next((path.parent / "objects").iterdir()).unlink()
        before = (self.store / "RUN.json").read_bytes()
        self.assertIn("reconcile --pr first", self.mutate("next", ok=False))
        self.assertEqual((self.store / "RUN.json").read_bytes(), before)
        if missing_blob:
            self.review_cli(root, ["abandon", str(path), "--reason", "Fixture object was lost",
                                  "--evidence", "No usable copy remains",
                                  "--shutdown-evidence", "Synchronous fixture workers exited"])
        self.mutate("reconcile", "--pr", "first", "--reason", "Replace failed acceptance")
        retry = self.next()
        self.assertEqual((retry["role"], retry["attempt"]), ("review", 2))
        self.assertEqual(retry["comparison_base"], original["prs"]["first"]["task_bases"]["change"])
        self.review(root)
        while self.next():
            self.execute_fixture(self.state["assignment"])
        saved = development.load(self.store)
        self.assertEqual(saved["outcome"], "completed")
        self.assertEqual(saved["history"][:len(original["history"])], original["history"])
        self.assertEqual(saved["prs"]["first"]["task_bases"], original["prs"]["first"]["task_bases"])
        self.assertEqual(saved["manifest"]["limits"], original["manifest"]["limits"])

    @pytest.mark.stable_storage
    def test_stopped_cached_review_requires_counted_reconciliation(self):
        self.assert_closed_cached_review_recovers()

    @pytest.mark.stable_storage
    def test_observed_revocation_survives_unavailable_history(self):
        root = self.start_review_fixture()
        data = self.review(root)
        source = Path(data["ledger"]).parent.parent
        self.close_accepted_review(root)
        self.assertIn("reconcile --pr first", self.mutate("next", ok=False))
        hidden = self.folder / "offline-revoked-review"
        source.rename(hidden)
        self.assertIn("reconcile --pr first", self.mutate("next", ok=False))
        hidden.rename(source)
        self.mutate("reconcile", "--pr", "first", "--reason", "Replace revoked acceptance")
        self.assertEqual(self.next()["attempt"], 2)
        self.review(root)
        self.assertEqual(self.next()["role"], "commit")

    @pytest.mark.stable_storage
    def test_workflow_rejects_closure_between_reservation_and_launch(self):
        root = self.start_review_fixture()
        self.review(root)
        before = self.git("rev-parse", "HEAD", root=root)
        roles = self.workflow("close-before-dispatch")
        self.assertNotIn("commit", roles)
        self.assertEqual(self.git("rev-parse", "HEAD", root=root), before)
        self.assertIn("reconcile --pr first", self.state["reason"])
        self.mutate("retire", "--reason", "The commit worker never launched",
                    "--shutdown-evidence", "The synchronous fixture returned without a commit launch")
        self.mutate("reconcile", "--pr", "first", "--reason", "Replace revoked acceptance")
        self.assertIn("commit", self.workflow("review-complete"))

    def test_dispatch_claim_holds_ownership_through_save_and_cannot_replay(self):
        root = self.start_review_fixture()
        data = self.review(root)
        assignment = self.next()
        arguments = ("claim-dispatch", str(self.store), "--revision", str(self.state["revision"]),
                     "--assignment", assignment["id"], "--provider", "claude-workflows")
        original = development.save
        ledger_revision = len(json.loads(Path(data["ledger"]).read_bytes())["events"])

        def save_with_competing_closure(folder, state):
            competing = subprocess.run(
                [sys.executable, str(SCRIPTS / "review_ledger.py"), "apply", data["ledger"],
                 "--revision", str(ledger_revision)], cwd=root, env=self.env,
                input=json.dumps({"type": "stop", "outcome": "failed", "actor": "fixture",
                                  "reason": "Closure competing with a dispatch claim"}),
                text=True, capture_output=True, timeout=5)
            self.assertEqual(competing.returncode, 2, competing.stdout + competing.stderr)
            self.assertIn("temporarily unavailable", competing.stderr)
            original(folder, state)

        with patch.dict(os.environ, self.env, clear=True), \
                patch.object(development, "save", save_with_competing_closure):
            self.state = development.mutate(development.parser().parse_args(arguments), self.store)
        self.assertIn("already claimed", self.mutate(
            "claim-dispatch", "--assignment", assignment["id"], "--provider", "claude-workflows", ok=False))
        consumed = self.state["consumed_assignments"]
        self.mutate("retire", "--reason", "Reconcile a lost claim response without replay",
                    "--shutdown-evidence", "Fixture did not launch a worker or create external effects")
        self.mutate("resume", "--reason", "Counted retry after confirming native shutdown")
        retry = self.next()
        self.assertEqual((retry["role"], retry["attempt"]), ("commit", 2))
        self.assertEqual(self.state["consumed_assignments"], consumed + 1)
        self.mutate("claim-dispatch", "--assignment", retry["id"], "--provider", "claude-workflows")
        self.execute_fixture(self.state["assignment"])
        self.assertEqual(self.next()["role"], "draft")

    def test_workflow_preserves_claimed_dispatch_effects_after_closure(self):
        root = self.start_review_fixture()
        (root / "app.txt").write_text("reviewed change\n")
        self.review(root)
        before = self.git("rev-parse", "HEAD", root=root)
        roles = self.workflow("close-after-dispatch")
        self.assertIn("commit", roles)
        self.assertNotEqual(self.git("rev-parse", "HEAD", root=root), before)
        self.assertIn("reconcile --pr first", self.state["reason"])
        self.assertIsNotNone(self.state["assignment"]["dispatch_claim"])

    def ready_fixture(self):
        root = self.start_review_fixture()
        reviewed = self.review(root)
        assignment = self.next()
        while assignment["role"] != "ready":
            self.execute_fixture(assignment)
            assignment = self.next()
        return root, reviewed

    def advance_rebase_target(self, root, content=None):
        name = "app.txt" if content is not None else "upstream.txt"
        (self.root / name).write_text(content if content is not None else "Target branch change\n")
        self.git("add", name)
        self.git("commit", "-qm", "Fixture target update")
        new_base = self.git("rev-parse", "HEAD")
        self.git("rebase", "main", root=root)
        return new_base

    def accepted_rebase_fixture(self, content="after\n"):
        root = self.start_review_fixture()
        (root / "app.txt").write_text(content)
        self.review(root)
        self.execute_fixture(self.next())
        self.execute_fixture(self.next())
        self.next()
        (root / "untracked.txt").write_text("reviewed untracked content\n")
        (root / "binary.dat").write_bytes(b"\x00reviewed\xff")
        (root / "link").symlink_to("app.txt")
        (root / "tool.sh").write_text("#!/bin/sh\nexit 0\n")
        (root / "tool.sh").chmod(0o755)
        self.review(root)
        self.mutate("reconcile", "--pr", "first", "--reason", "Exercise the last counted review")
        self.next()
        self.review(root)
        before = development.load(self.store)
        new_base = self.advance_rebase_target(root)
        return root, before, new_base

    @pytest.mark.stable_storage
    def test_rebase_rejects_relocated_edits_with_matching_patch_ids(self):
        section = "pad1\npad2\npad3\ntimeout = 30\npad4\npad5\npad6\n"
        base = "[first]\n" + section + "[second]\n" + section
        (self.root / "app.txt").write_text(base)
        self.git("add", "app.txt")
        self.git("commit", "-qm", "Repeated-section fixture")
        self.plan["prs"][0]["base"] = self.git("rev-parse", "HEAD")
        reviewed = base.replace("timeout = 30", "timeout = 60", 1)
        root, before, new_base = self.accepted_rebase_fixture(reviewed)
        (root / "app.txt").write_text("timeout = 60".join(base.rsplit("timeout = 30", 1)))
        original = (self.store / "RUN.json").read_bytes()
        self.assertIn("patch differs", self.mutate(
            "rebase-review", "--pr", "first", "--new-base", new_base,
            "--reason", "The same-looking edit moved to another section", ok=False))
        self.assertEqual((self.store / "RUN.json").read_bytes(), original)
        (root / "app.txt").write_text(reviewed)
        new_base = self.advance_rebase_target(root, base.replace("pad1", "upstream pad1", 1))
        self.mutate("rebase-review", "--pr", "first", "--new-base", new_base,
                    "--reason", "Preserve both the reviewed edit and nearby target changes")
        saved = development.load(self.store)
        self.assertEqual(saved["attempts"], before["attempts"])
        self.assertEqual((root / "app.txt").read_text(), reviewed.replace("pad1", "upstream pad1", 1))

    @pytest.mark.stable_storage
    def test_rebase_uses_existing_shared_checkout_trust_without_widening_it(self):
        root, before, new_base = self.accepted_rebase_fixture()
        config = self.folder / "trusted-git-config"
        self.env["GIT_CONFIG_GLOBAL"] = str(config)
        self.git("config", "--global", "safe.directory", str(root))
        original_run = subprocess.run

        def shared_checkout(command, *args, **kwargs):
            if command[0] == "git" and "-C" in command and Path(command[command.index("-C") + 1]) == root:
                kwargs["env"] = {**kwargs.get("env", os.environ), "GIT_TEST_ASSUME_DIFFERENT_OWNER": "1"}
            return original_run(command, *args, **kwargs)

        with patch.object(subprocess, "run", shared_checkout):
            self.mutate("rebase-review", "--pr", "first", "--new-base", new_base,
                        "--reason", "Already trusted shared checkout")
            config.write_text("")
            self.assertIn("dubious ownership", self.mutate(
                "rebase-review", "--pr", "first", "--new-base", new_base,
                "--reason", "Removed trust must still be refused", ok=False))
        self.assertEqual(development.load(self.store)["attempts"], before["attempts"])

    def completed_delivery_rebase_fixture(self, *, auditing=False, screenshots=True, fail_evidence=False):
        self.plan["permissions"]["screenshots"] = screenshots
        root = self.start_audit_fixture() if auditing else self.start_review_fixture()
        while True:
            assignment = self.state["assignment"] or self.next()
            if assignment["role"] == "evidence":
                if fail_evidence:
                    self.finish(outcome="blocked")
                    self.mutate("resume", "--reason", "Retry failed UI capture within its remaining allowance")
                    fail_evidence = False
                    continue
                self.finish({"commit": self.git("rev-parse", "HEAD", root=root),
                             "artifacts": ["Original UI evidence"]})
            else:
                self.execute_fixture(assignment)
            if assignment["role"] == "review" and assignment["task"] is None and assignment["attempt"] == 1:
                self.mutate("reconcile", "--pr", "first", "--reason", "Consume the last review attempt")
            if assignment["role"] == ("audit-final" if auditing else "evidence"):
                break
        before = development.load(self.store)
        new_base = self.advance_rebase_target(root)
        if auditing:
            old_head = before["prs"]["first"]["accepted"]["head"]
            self.git("push", f"--force-with-lease=refs/heads/fixture-feature:{old_head}",
                     "origin", "HEAD:refs/heads/fixture-feature", root=root)
        return root, before, new_base

    @pytest.mark.stable_storage
    def test_rebase_refreshes_completed_evidence_without_another_review(self):
        root, before, new_base = self.completed_delivery_rebase_fixture()
        self.mutate("rebase-review", "--pr", "first", "--new-base", new_base,
                    "--reason", "Refresh screenshots for the rebased commit")
        self.assertEqual(self.next()["role"], "evidence")
        self.finish({"commit": self.git("rev-parse", "HEAD", root=root), "artifacts": ["Updated UI evidence"]})
        self.assertEqual(self.next()["role"], "ready")
        self.execute_fixture(self.state["assignment"])
        self.assertIsNone(self.next())
        saved = development.load(self.store)
        self.assertEqual(saved["prs"]["first"]["review"], before["prs"]["first"]["review"])
        self.assertEqual(saved["attempts"]["first:review:pr"], 2)
        self.assertEqual(saved["attempts"]["first:evidence:pr"], 2)
        self.assertEqual(saved["history"][:len(before["history"])], before["history"])

    @pytest.mark.stable_storage
    def test_rebase_refreshes_final_audit_after_refreshing_evidence(self):
        root, before, new_base = self.completed_delivery_rebase_fixture(auditing=True)
        self.mutate("rebase-review", "--pr", "first", "--new-base", new_base,
                    "--reason", "Refresh completed delivery evidence without a counted review")
        self.assertEqual(self.next()["role"], "evidence")
        self.finish({"commit": self.git("rev-parse", "HEAD", root=root), "artifacts": ["Updated UI evidence"]})
        self.assertEqual(self.next()["role"], "audit-final")
        self.execute_fixture(self.state["assignment"])
        self.assertEqual(self.next()["role"], "ready")
        self.execute_fixture(self.state["assignment"])
        self.assertIsNone(self.next())
        saved = development.load(self.store)
        self.assertEqual(saved["attempts"]["first:review:pr"], 2)
        self.assertEqual(saved["attempts"]["first:audit-final:pr"], 2)
        self.assertEqual(saved["prs"]["first"]["audits"][:-1], before["prs"]["first"]["audits"])
        self.assertEqual(saved["prs"]["first"]["audits"][-1]["code_commit"],
                         self.git("rev-parse", "HEAD", root=root))

    @pytest.mark.stable_storage
    def test_rebase_refreshes_final_audit_without_scheduled_screenshots(self):
        root, before, new_base = self.completed_delivery_rebase_fixture(auditing=True, screenshots=False)
        self.mutate("rebase-review", "--pr", "first", "--new-base", new_base,
                    "--reason", "Refresh the final audit only")
        self.assertEqual(self.next()["role"], "audit-final")
        self.execute_fixture(self.state["assignment"])
        self.assertEqual(self.next()["role"], "ready")
        self.execute_fixture(self.state["assignment"])
        self.assertIsNone(self.next())
        self.assertEqual(development.load(self.store)["prs"]["first"]["review"],
                         before["prs"]["first"]["review"])

    @pytest.mark.stable_storage
    def test_rebase_delivery_refresh_preserves_state_when_assignments_cannot_finish(self):
        self.plan["limits"]["assignments"] = 11
        root, before, new_base = self.completed_delivery_rebase_fixture()
        original = (self.store / "RUN.json").read_bytes()
        self.assertIn("Not enough assignment allowance", self.mutate(
            "rebase-review", "--pr", "first", "--new-base", new_base,
            "--reason", "Insufficient capacity for refreshed evidence and readiness", ok=False))
        self.assertEqual((self.store / "RUN.json").read_bytes(), original)

    @pytest.mark.stable_storage
    def test_rebase_delivery_refresh_does_not_refund_exhausted_evidence_attempts(self):
        root, before, new_base = self.completed_delivery_rebase_fixture(fail_evidence=True)
        original = (self.store / "RUN.json").read_bytes()
        self.assertIn("No attempts remain for first:evidence:pr", self.mutate(
            "rebase-review", "--pr", "first", "--new-base", new_base,
            "--reason", "UI capture already used its retry", ok=False))
        self.assertEqual((self.store / "RUN.json").read_bytes(), original)

    @pytest.mark.stable_storage
    def test_stale_ui_evidence_is_rejected_at_readiness_reservation_and_handback(self):
        root, before, new_base = self.completed_delivery_rebase_fixture()
        self.mutate("rebase-review", "--pr", "first", "--new-base", new_base,
                    "--reason", "Reject stale evidence retained by an older executor")
        saved = development.load(self.store)
        saved["prs"]["first"]["position"] = before["prs"]["first"]["position"]
        with patch.dict(os.environ, self.env, clear=True):
            settings = development.feature(root)
            with self.assertRaisesRegex(manifest.ManifestError, "UI evidence is missing or stale"):
                development.reserve(saved, settings)
            accepted = saved["prs"]["first"]["accepted"]
            assignment = {"role": "ready", "pr": "first", "root": str(root), "before": accepted}
            data = {"commit": accepted["head"], "url": saved["prs"]["first"]["url"],
                    "state": "ready", "evidence": "Offline receipt for the current commit"}
            with self.assertRaisesRegex(manifest.ManifestError, "UI evidence is missing or stale"):
                development.delivery_result(saved, assignment, data, settings)

    @pytest.mark.stable_storage
    def test_clean_target_rebase_preserves_review_and_continues_at_exhausted_review_limit(self):
        root, before, new_base = self.accepted_rebase_fixture()
        denied = self.mutate("next", ok=False)
        self.assertIn("Review lacks complete file coverage", denied)
        ledger = Path(before["prs"]["first"]["review"]["ledger"])
        history = ledger.read_bytes()
        index = self.git("ls-files", "--stage", root=root)
        object_store = (root / self.git("rev-parse", "--git-path", "objects", root=root)).resolve()
        objects = {str(path.relative_to(object_store)) for path in object_store.rglob("*") if path.is_file()}
        config = self.root / ".claude/ioncache-ai-tools.local.json"
        config.parent.mkdir(exist_ok=True)
        config.write_text('{"features": {"autonomous-development-rebase-review": false}}')
        self.assertIn("disabled", self.mutate(
            "rebase-review", "--pr", "first", "--new-base", new_base, "--reason", "Disabled", ok=False))
        self.assertEqual(development.load(self.store)["attempts"], before["attempts"])
        config.write_text('{"features": {}}')
        self.mutate("rebase-review", "--pr", "first", "--new-base", new_base,
                    "--reason", "Clean target rebase with unchanged reviewed patch")
        saved = development.load(self.store)
        self.assertEqual(saved["attempts"], before["attempts"])
        self.assertEqual(len(saved["history"]), len(before["history"]))
        self.assertEqual(ledger.read_bytes(), history)
        self.assertEqual(saved["prs"]["first"]["review"], before["prs"]["first"]["review"])
        self.assertEqual(saved["prs"]["first"]["base"], new_base)
        self.assertEqual(self.git("ls-files", "--stage", root=root), index)
        self.assertEqual({str(path.relative_to(object_store))
                          for path in object_store.rglob("*") if path.is_file()}, objects)
        self.assertIn("previously accepted bases", self.mutate(
            "rebase-review", "--pr", "first", "--new-base", before["prs"]["first"]["base"],
            "--reason", "Cannot roll back accepted target ancestry", ok=False))
        self.assertEqual(self.next()["role"], "commit")
        self.git("add", "untracked.txt", "binary.dat", "link", "tool.sh", root=root)
        self.git("commit", "-qm", "Commit already reviewed fixture artifacts", root=root)
        self.finish({"commit": self.git("rev-parse", "HEAD", root=root)})
        self.assertEqual(self.next()["role"], "ready")
        self.execute_fixture(self.state["assignment"])
        self.assertIsNone(self.next())
        self.assertEqual(self.state["outcome"], "completed")

    @pytest.mark.stable_storage
    def test_rebase_recovery_rejects_changed_patch_foreign_base_and_closed_ledger(self):
        root, before, new_base = self.accepted_rebase_fixture()
        arguments = ("--pr", "first", "--new-base", new_base, "--reason", "Verify unchanged patch")
        original = (self.store / "RUN.json").read_bytes()
        for name, changed in (("app.txt", b"after \n"), ("binary.dat", b"\x00different\xff"),
                              ("untracked.txt", b"unreviewed content\n")):
            path = root / name
            content = path.read_bytes()
            path.write_bytes(changed)
            self.assertIn("patch differs", self.mutate("rebase-review", *arguments, ok=False))
            self.assertEqual((self.store / "RUN.json").read_bytes(), original)
            path.write_bytes(content)
        (root / "tool.sh").chmod(0o644)
        self.assertIn("patch differs", self.mutate("rebase-review", *arguments, ok=False))
        (root / "tool.sh").chmod(0o755)
        (root / "link").unlink()
        (root / "link").symlink_to("untracked.txt")
        self.assertIn("patch differs", self.mutate("rebase-review", *arguments, ok=False))
        (root / "link").unlink()
        (root / "link").symlink_to("app.txt")
        foreign = self.git("rev-parse", "HEAD", root=root)
        self.assertIn("target branch", self.mutate(
            "rebase-review", "--pr", "first", "--new-base", foreign, "--reason", "Not a target base", ok=False))
        self.close_accepted_review(root)
        self.assertIn("Cached review cannot", self.mutate("rebase-review", *arguments, ok=False))
        self.assertEqual((self.store / "RUN.json").read_bytes(), original)

    @pytest.mark.stable_storage
    def test_rebase_recovery_rejects_a_resolved_conflict_without_counted_review(self):
        root, before, _ = self.accepted_rebase_fixture()
        (self.root / "app.txt").write_text("upstream changed the same line\n")
        self.git("add", "app.txt")
        self.git("commit", "-qm", "Conflicting target edit")
        new_base = self.git("rev-parse", "HEAD")
        conflict = subprocess.run(["git", "merge", "--no-commit", "main"], cwd=root,
                                  env=self.env, capture_output=True, text=True)
        self.assertEqual(conflict.returncode, 1, conflict.stdout + conflict.stderr)
        (root / "app.txt").write_text("after\n")
        self.git("add", "app.txt", root=root)
        self.git("commit", "-qm", "Fixture resolves the target conflict", root=root)
        original = (self.store / "RUN.json").read_bytes()
        self.assertIn("cannot be replayed without conflicts", self.mutate(
            "rebase-review", "--pr", "first", "--new-base", new_base,
            "--reason", "A conflict resolution is not an unchanged reviewed patch", ok=False))
        self.assertEqual((self.store / "RUN.json").read_bytes(), original)

    @pytest.mark.stable_storage
    def test_reconcile_exhaustion_preserves_acceptance_for_clean_rebase_recovery(self):
        root, before, new_base = self.accepted_rebase_fixture()
        original = (self.store / "RUN.json").read_bytes()
        self.assertIn("No review attempts remain", self.mutate(
            "reconcile", "--pr", "first", "--reason", "No counted review remains", ok=False))
        self.assertEqual((self.store / "RUN.json").read_bytes(), original)
        self.mutate("rebase-review", "--pr", "first", "--new-base", new_base,
                    "--reason", "Use the unchanged-patch recovery instead")
        self.assertEqual(development.load(self.store)["attempts"], before["attempts"])

    def test_ready_handback_serializes_acceptance_through_save(self):
        root, reviewed = self.ready_fixture()
        report = self.report({"commit": self.git("rev-parse", "HEAD", root=root),
                              "url": "https://example.invalid/pull/1", "state": "ready",
                              "evidence": "Offline ready receipt"})
        arguments = development.parser().parse_args([
            "record", str(self.store), "--revision", str(self.state["revision"]), "--report", str(report)])
        original = development.save
        closures = []

        def save_with_competing_closure(folder, state):
            closures.append(subprocess.run(
                [sys.executable, str(SCRIPTS / "review_ledger.py"), "apply", reviewed["ledger"],
                 "--revision", str(len(json.loads(Path(reviewed["ledger"]).read_bytes())["events"]))],
                cwd=root, env=self.env, text=True, capture_output=True, timeout=5,
                input=json.dumps({"type": "stop", "outcome": "failed", "actor": "fixture",
                                  "reason": "Close between authority validation and handback persistence"})))
            original(folder, state)

        with patch.dict(os.environ, self.env, clear=True), \
                patch.object(development, "save", save_with_competing_closure):
            self.state = development.mutate(arguments, self.store)
        self.assertIsNone(self.next())
        self.assertEqual(self.state["outcome"], "completed")
        self.assertEqual(len(closures), 1)
        self.assertEqual(closures[0].returncode, 2,
                         "The run completed although closure won before its final handback was saved")
        self.assertIn("temporarily unavailable", closures[0].stderr)
        self.close_accepted_review(root)
        with patch.dict(os.environ, self.env, clear=True):
            import review_ownership

            with review_ownership.locked(root):
                replayed = self.mutate("record", "--report", report)
        self.assertEqual(replayed["outcome"], "completed")

    @pytest.mark.stable_storage
    def test_closure_before_ready_handback_requires_counted_reconciliation(self):
        root, _ = self.ready_fixture()
        prior = [item for item in development.load(self.store)["history"] if item["role"] == "review"]
        self.close_accepted_review(root)
        before = (self.store / "RUN.json").read_bytes()
        self.assertIn("reconcile --pr first", self.finish(
            {"commit": self.git("rev-parse", "HEAD", root=root),
             "url": "https://example.invalid/pull/1", "state": "ready",
             "evidence": "Already-published offline fixture effect"}, ok=False))
        self.assertEqual((self.store / "RUN.json").read_bytes(), before)
        self.mutate("retire", "--reason", "Retain the existing published effects",
                    "--shutdown-evidence", "Synchronous ready worker exited")
        self.mutate("reconcile", "--pr", "first", "--reason", "Review before accepting readiness")
        while self.next():
            self.execute_fixture(self.state["assignment"])
        self.assertEqual(self.state["outcome"], "completed")
        reviews = [item for item in development.load(self.store)["history"] if item["role"] == "review"]
        self.assertEqual(reviews[:-1], prior)
        self.assertEqual(reviews[-1]["attempt"], 2)

    def test_locked_ready_handback_keeps_failure_and_retirement_reachable(self):
        self.plan["limits"]["attempts"] = 3
        root, _ = self.ready_fixture()
        data = {"commit": self.git("rev-parse", "HEAD", root=root),
                "url": "https://example.invalid/pull/1", "state": "ready",
                "evidence": "Offline ready receipt"}
        with patch.dict(os.environ, self.env, clear=True):
            import review_ownership

            with review_ownership.locked(root):
                report = self.report(data)
                malformed = json.loads(report.read_bytes())
                malformed["assignment"] = "not-the-active-assignment"
                report.write_bytes(manifest.encode(malformed))
                self.assertIn("Unexpected assignment", self.mutate("record", "--report", report, ok=False))
                before = (self.store / "RUN.json").read_bytes()
                self.assertIn("temporarily unavailable", self.finish(data, ok=False))
                self.assertEqual((self.store / "RUN.json").read_bytes(), before)
                self.mutate("interrupt", "--reason", "Collect the completed worker before retrying")
                self.mutate("retire", "--reason", "No live ready worker",
                            "--shutdown-evidence", "Synchronous fixture has exited")
                self.mutate("resume", "--reason", "Count a fresh ready assignment")
                self.assertEqual(self.next()["attempt"], 2)
                self.finish(outcome="blocked")
        self.mutate("resume", "--reason", "Ownership is available again")
        self.assertEqual(self.next()["attempt"], 3)
        self.finish(data)
        self.assertIsNone(self.next())
        self.assertEqual(self.state["outcome"], "completed")

    @pytest.mark.stable_storage
    def test_abandoned_cached_review_requires_counted_reconciliation(self):
        self.assert_closed_cached_review_recovers("abandon")

    @pytest.mark.stable_storage
    def test_recovered_closure_invalidates_cached_review(self):
        self.assert_closed_cached_review_recovers("recover-closure")

    @pytest.mark.stable_storage
    def test_missing_blob_does_not_hide_cached_review_invalidation(self):
        self.assert_closed_cached_review_recovers(missing_blob=True)

    @pytest.mark.stable_storage
    def test_recovered_cached_review_closure_survives_later_ownership_change(self):
        self.assert_closed_cached_review_recovers(recovered=True)

    @pytest.mark.stable_storage
    def test_recovered_cached_review_release_survives_later_ownership_change(self):
        self.assert_closed_cached_review_recovers("release", recovered=True)

    def assert_workflow_rechecks_cached_invalidation(self, invalidate):
        root = self.start_review_fixture()
        (root / "app.txt").write_text("reviewed change\n")
        self.review(root)
        before = development.load(self.store)
        invalidate(root)
        self.assertEqual(self.workflow("complete"), [])
        self.assertIn("reconcile --pr first", self.state["reason"])
        self.assertEqual(self.state["consumed_assignments"], len(before["history"]))
        self.assertEqual(development.load(self.store)["prs"], before["prs"])
        self.mutate("reconcile", "--pr", "first", "--reason", "Replace released acceptance")
        roles = self.workflow("review-complete")
        self.assertIn("reviewer", roles)
        self.assertIn("commit", roles)
        after = development.load(self.store)
        reviews = [item for item in after["history"] if item["role"] == "review"]
        self.assertEqual([item["attempt"] for item in reviews], [1, 2])
        self.assertEqual(reviews[0], before["history"][-1])
        self.assertEqual(after["prs"]["first"]["task_bases"], before["prs"]["first"]["task_bases"])
        self.assertEqual(after["manifest"]["limits"], before["manifest"]["limits"])
        self.assertEqual((root / "app.txt").read_text(), "reviewed change\n")

    @pytest.mark.stable_storage
    def test_workflow_rechecks_cached_release_before_commit_and_recovers(self):
        self.assert_workflow_rechecks_cached_invalidation(self.release_accepted_review)

    @pytest.mark.stable_storage
    def test_workflow_rechecks_cached_closure_before_commit_and_recovers(self):
        self.assert_workflow_rechecks_cached_invalidation(self.close_accepted_review)

    def assert_invalidated_acceptance_preserves_dispatched_commit(self, invalidate):
        root = self.start_review_fixture()
        original_base = self.state["assignment"]["comparison_base"]
        (root / "app.txt").write_text("reviewed change\n")
        self.review(root)
        first_commit = self.next()
        self.assertEqual(first_commit["role"], "commit")
        self.mutate("claim-dispatch", "--assignment", first_commit["id"], "--provider", "claude-workflows")
        self.git("add", "app.txt", root=root)
        self.git("commit", "-qm", "fixture dispatched commit", root=root)
        committed = self.git("rev-parse", "HEAD", root=root)
        invalidate(root)
        before = (self.store / "RUN.json").read_bytes()
        self.assertIn("reconcile --pr first", self.finish({"commit": committed}, ok=False))
        self.assertEqual((self.store / "RUN.json").read_bytes(), before)
        self.assertEqual(self.git("rev-parse", "HEAD", root=root), committed)
        self.mutate("retire", "--reason", "Retain the worker's existing commit",
                    "--shutdown-evidence", "Synchronous commit worker exited")
        consumed = self.state["consumed_assignments"]
        self.mutate("reconcile", "--pr", "first", "--reason", "Recheck the retained commit")
        retry = self.next()
        self.assertEqual((retry["role"], retry["attempt"], retry["comparison_base"]),
                         ("review", 2, original_base))
        self.assertEqual(self.state["consumed_assignments"], consumed + 1)
        self.review(root)
        retry_commit = self.next()
        self.assertEqual((retry_commit["role"], retry_commit["attempt"]), ("commit", 2))
        self.mutate("claim-dispatch", "--assignment", retry_commit["id"], "--provider", "claude-workflows")
        self.execute_fixture(retry_commit)
        self.assertEqual(self.git("rev-parse", "HEAD", root=root), committed)
        self.assertEqual(self.next()["role"], "draft")

    def test_released_acceptance_rejects_commit_handback_without_undoing_effects(self):
        self.assert_invalidated_acceptance_preserves_dispatched_commit(self.release_accepted_review)

    def test_stopped_acceptance_rejects_commit_handback_without_undoing_effects(self):
        self.assert_invalidated_acceptance_preserves_dispatched_commit(self.close_accepted_review)

    def test_released_acceptance_cannot_complete_a_dispatched_draft(self):
        root = self.start_review_fixture()
        self.review(root)
        self.execute_fixture(self.next())
        self.assertEqual(self.next()["role"], "draft")
        self.release_accepted_review(root)
        before = (self.store / "RUN.json").read_bytes()
        data = {"commit": self.git("rev-parse", "HEAD", root=root),
                "url": "https://example.invalid/pull/1", "state": "draft",
                "evidence": "Offline receipt; no remote publication"}
        self.assertIn("reconcile --pr first", self.finish(data, ok=False))
        self.assertEqual((self.store / "RUN.json").read_bytes(), before)
        self.finish(outcome="blocked")
        self.mutate("reconcile", "--pr", "first", "--reason", "Replace released acceptance")
        self.assertEqual(self.next()["role"], "review")

    def test_unreleased_cached_review_does_not_require_live_history(self):
        root = self.start_review_fixture()
        (root / "app.txt").write_text("reviewed change\n")
        data = self.review(root)
        source = Path(data["ledger"]).parent.parent
        next((Path(data["ledger"]).parent / "objects").iterdir()).unlink()
        assignment = self.next()
        self.assertEqual(assignment["role"], "commit")
        self.execute_fixture(assignment)
        source.rename(self.folder / "offline-review-history")
        source.symlink_to(self.folder / "missing-review-history", target_is_directory=True)
        self.assertEqual(self.next()["role"], "draft")
        self.assertFalse(source.exists())

    def test_nonregular_cached_history_and_recovery_records_do_not_hang_dispatch(self):
        root = self.start_review_fixture()
        data = self.review(root)
        path = Path(data["ledger"])
        path.unlink()
        os.mkfifo(path)
        os.mkfifo(path.parent / "ABANDONED.json")
        ownership = (Path(self.env["HOME"]) / ".local/state/ioncache-ai-tools/review-ownership" /
                     development.review.root_key(root))
        os.mkfifo(ownership / ("RECOVERY-" + "0" * 32 + ".json"))
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "development_run.py"), "next", str(self.store),
             "--revision", str(self.state["revision"])],
            env=self.env, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["assignment"]["role"], "commit")

    def test_stopped_cached_review_blocks_live_audits_but_not_archives(self):
        root = self.start_audit_fixture()
        _, active, exported = self.audit_export()
        public_path = self.store / "reports" / active["id"] / "public.json"
        self.close_accepted_review(root)
        before = (self.store / "RUN.json").read_bytes()
        bundle = Path(exported["directory"]) / "audit.json"
        old_bundle = bundle.read_bytes()
        for operation, arguments in (
                ("export", ("--public", str(public_path))),
                ("publish", ("--approved", exported["identity"]))):
            with self.subTest(operation=operation):
                self.assertIn("reconcile --pr first", self.audit_cli(operation, *arguments, ok=False))
        self.assertEqual(bundle.read_bytes(), old_bundle)
        archive = self.audit_cli("archive", "--pr", "first", "--public", str(public_path))
        archived = json.loads((Path(archive["directory"]) / "audit.json").read_bytes())
        self.assertTrue(archive["historical"])
        self.assertEqual(archived["reviews"][0]["outcome"], "failed")
        with patch.object(audit, "api", self.audit_api):
            receipt = self.audit_cli("publish-archive", "--pr", "first", "--approved", archive["identity"])
        self.assertEqual(receipt["stage"], "archive")
        source = Path(self.state["prs"]["first"]["review"]["ledger"]).parent.parent
        source.rename(self.folder / "offline-audit-review")
        self.assertIn("reconcile --pr first", self.audit_cli("export", "--public", str(public_path), ok=False))
        self.assertEqual((self.store / "RUN.json").read_bytes(), before)
        self.assertEqual(len(self.audit_body_updates), 1)

    def test_archive_retains_witnessed_stop_when_ledger_publication_fails(self):
        import review_history
        import review_ownership

        root = self.start_audit_fixture()
        _, active, exported = self.audit_export()
        path = Path(self.state["prs"]["first"]["review"]["ledger"])
        original = path.read_bytes()
        public_path = self.store / "reports" / active["id"] / "public.json"
        public = json.loads(public_path.read_bytes())
        public["findings"] = []
        public_path.write_bytes(manifest.encode(public))
        args = development.review.parser().parse_args([
            "apply", str(path), "--revision", str(len(json.loads(original)["events"]))])
        args.event = {"type": "stop", "outcome": "failed", "actor": "fixture-owner",
                      "reason": "Withdraw the accepted fixture review"}
        write = development.review.atomic_write

        def interrupted_write(target, content):
            if target == path:
                raise OSError("Fixture interrupted ledger publication")
            write(target, content)

        with patch.dict(os.environ, self.env, clear=True), \
                review_ownership.guard(root, [path.parent.parent], args), \
                patch.object(development.review, "atomic_write", interrupted_write):
            with self.assertRaisesRegex(OSError, "interrupted ledger publication"):
                development.review.append(args, root)
            witness = review_history.read(root, path.parent.name)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(witness["outcome"], "failed")
        self.assertEqual(len(witness["events"]), len(json.loads(original)["events"]) + 1)
        self.assertIn("reconcile --pr first", self.audit_cli(
            "export", "--public", str(public_path), ok=False))
        before = (self.store / "RUN.json").read_bytes()
        archived = self.audit_cli("archive", "--pr", "first", "--public", str(public_path))
        record = json.loads((Path(archived["directory"]) / "audit.json").read_bytes())["reviews"][0]
        self.assertFalse(record["available"])
        self.assertEqual(record["outcome"], "failed")
        self.assertEqual(record["allowance"], "unavailable")
        self.assertEqual(record["closure_digest"], audit.identity(witness))
        self.assertNotIn("loops", record)
        self.assertEqual((self.store / "RUN.json").read_bytes(), before)
        self.assertEqual(self.audit_body_updates, [])
        self.review_cli(root, [
            "abandon", str(path), "--reason", "Close interrupted failed publication",
            "--evidence", "The witnessed failure supersedes the retained completed ledger",
            "--shutdown-evidence", "Synchronous fixture workers exited",
        ])
        self.mutate("retire", "--reason", "The audit cannot publish revoked acceptance",
                    "--shutdown-evidence", "Synchronous fixture workers exited")
        self.mutate("reconcile", "--pr", "first", "--reason", "Counted review after revoked acceptance")
        self.assertEqual(self.next()["attempt"], 2)
        self.review(root)
        for role in ("commit", "draft"):
            self.assertEqual(self.next()["role"], role)
            self.execute_fixture(self.state["assignment"])
        self.assertEqual(self.next()["role"], "audit-initial")
        _, _, current = self.audit_export()
        records = json.loads((Path(current["directory"]) / "audit.json").read_bytes())["reviews"]
        historical = next(item for item in records if item["id"] == path.parent.name)
        self.assertFalse(historical["available"])
        self.assertEqual(historical["outcome"], "failed")
        self.assertTrue(any(item["available"] and item["outcome"] == "completed" for item in records))
        with patch.dict(os.environ, self.env, clear=True):
            inferred_root = audit.review_record(path)
        self.assertFalse(inferred_root["available"])
        self.assertEqual(inferred_root["outcome"], "failed")

    def assert_archive_retains_recovered_closure(self, closure):
        root = self.start_audit_fixture()
        state, active, exported = self.audit_export()
        path = Path(self.state["prs"]["first"]["review"]["ledger"])
        original = path.read_bytes()
        target = self.folder / "recovered" / path.parent.parent.name / path.parent.name
        development.shutil.copytree(path.parent, target)
        recovered = target / path.name
        self.review_cli(root, [
            "recover-ownership", str(recovered), "--reason", "Recover completed review",
            "--shutdown-evidence", "Synchronous fixture workers exited",
        ])
        self.close_accepted_review(root, closure, ledger=recovered)
        public_path = self.store / "reports" / active["id"] / "public.json"
        public = json.loads(public_path.read_bytes())
        public["findings"] = []
        public_path.write_bytes(manifest.encode(public))
        archived = self.audit_cli("archive", "--pr", "first", "--public", str(public_path))
        record = json.loads((Path(archived["directory"]) / "audit.json").read_bytes())["reviews"][0]
        self.assertFalse(record["available"])
        self.assertEqual(record["outcome"], "failed")
        self.assertEqual(record["allowance"], "unavailable")
        self.assertTrue(record["closure_digest"])
        self.assertNotIn("loops", record)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(development.load(self.store), state)
        self.assertEqual(self.audit_body_updates, [])

    def test_archive_retains_recovered_store_release(self):
        self.assert_archive_retains_recovered_closure("release")

    def test_archive_retains_recovered_history_abandonment(self):
        self.assert_archive_retains_recovered_closure("abandon")

    def test_legacy_cached_acceptance_requires_counted_rebinding_across_xdg_changes(self):
        root = self.start_review_fixture()
        data = self.review(root)
        path = Path(data["ledger"])
        legacy = root / ".review-loop" / path.parent.name
        legacy.parent.mkdir(exist_ok=True)
        path.parent.rename(legacy)
        state = development.load(self.store)
        reference = str(legacy / "REVIEW_LEDGER.json")
        state["prs"]["first"]["review"]["ledger"] = reference
        state["history"][-1].pop("review_storage")
        state["history"][-1]["report"]["data"]["ledger"] = reference
        development.save(self.store, state)
        migrated = self.review_cli(root, [
            "migrate", reference, "--shutdown-evidence", "Legacy fixture writers exited"])
        before = (self.store / "RUN.json").read_bytes()
        self.assertIn("reconcile --pr first", self.mutate("next", ok=False))
        self.assertEqual((self.store / "RUN.json").read_bytes(), before)
        source = Path(migrated["ledger"]).parent.parent
        development.shutil.rmtree(source)
        self.review_cli(root, [
            "release-ownership", "--storage", str(source),
            "--replacement-storage", str(self.folder / "replacement" / source.name),
            "--reason", "Migrated fixture history was lost",
            "--shutdown-evidence", "Fixture workers exited",
        ])
        self.env["XDG_STATE_HOME"] = str(self.folder / "changed-state-home")
        self.assertIn("reconcile --pr first", self.mutate("next", ok=False))
        self.assertEqual((self.store / "RUN.json").read_bytes(), before)
        consumed = self.state["consumed_assignments"]
        self.mutate("reconcile", "--pr", "first", "--reason", "Bind acceptance to its actual store")
        retry = self.next()
        self.assertEqual((retry["role"], retry["attempt"]), ("review", 2))
        self.assertEqual(retry["comparison_base"], state["prs"]["first"]["task_bases"]["change"])
        self.assertEqual(self.state["consumed_assignments"], consumed + 1)
        self.review(root)
        self.assertEqual(self.next()["role"], "commit")

    def test_released_cached_review_cannot_authorize_audit_export(self):
        root = self.start_audit_fixture()
        _, active, exported = self.audit_export()
        public_path = self.store / "reports" / active["id"] / "public.json"
        public = json.loads(public_path.read_bytes())
        public["findings"] = []
        public_path.write_bytes(manifest.encode(public))
        self.release_accepted_review(root)
        before = (self.store / "RUN.json").read_bytes()
        bundle = Path(exported["directory"]) / "audit.json"
        old_bundle = bundle.read_bytes()
        self.assertIn("reconcile --pr first", self.audit_cli(
            "export", "--public", str(public_path), ok=False))
        self.assertEqual(bundle.read_bytes(), old_bundle)
        archive = self.audit_cli("archive", "--pr", "first", "--public", str(public_path))
        self.assertTrue(archive["historical"])
        self.assertEqual((self.store / "RUN.json").read_bytes(), before)
        self.assertEqual(self.audit_body_updates, [])

    @pytest.mark.process
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

    def test_provider_diagnostics_preserve_identity_and_reject_before_reservation(self):
        self.plan["configuration"]["execution"]["provider"] = "Claude Workflow ioncache-ai-tools:autonomous-development-run"
        original = copy.deepcopy(self.plan)
        self.path.write_bytes(manifest.encode(self.plan))
        validated = self.cli("validate", self.path)
        self.assertEqual(validated["identity"], manifest.digest(manifest.encode(original)))
        self.assertEqual(validated["manifest"], original)
        self.assertIn("claude-workflows", " ".join(validated["warnings"]))
        self.assertIn("provider", self.cli("validate", self.path, "--provider", "claude-workflows", ok=False))
        self.assertIn("provider", self.cli(
            "init", self.path, "--approved", validated["identity"], "--root", self.root,
            "--store", self.store, "--provider", "claude-workflows", ok=False))
        self.assertFalse(self.store.exists())
        self.init()
        saved = (self.store / "RUN.json").read_bytes()
        self.assertIn("provider", self.mutate("next", "--provider", "claude-workflows", ok=False))
        self.assertEqual((self.store / "RUN.json").read_bytes(), saved)
        self.workflow("provider-mismatch")
        self.assertEqual(self.state["outcome"], "blocked")
        self.assertEqual(self.state["consumed_assignments"], 0)
        self.assertIsNone(self.state["assignment"])
        self.mutate("resume", "--reason", "Use an executor for the approved provider")
        self.assertEqual(self.next()["role"], "preflight")

    def test_external_worktree_supports_review_and_audit_lifecycle(self):
        self.configure_audit()
        self.plan["prs"][0]["worktree"] = "../project.worktrees/fixture"
        self.init()
        self.preflight()
        root = self.prepare()
        assignment = self.next()
        self.cli("model-report", self.store, "--invocation", "external-audit-fixture", "--call", "1",
                 "--role", "implement", "--assignment", assignment["id"], "--selected-model", "requested",
                 "--actual-model", "observed", "--source", "native-transcript")
        self.execute_fixture(assignment)
        with patch.dict(os.environ, self.audit_git_env):
            self.env.update(self.audit_git_env)
            self.assertEqual(root, self.folder / "project.worktrees/fixture")
            while self.next():
                self.execute_fixture(self.state["assignment"])
        self.assertEqual(self.state["outcome"], "completed")
        self.assertEqual(len(self.audit_body_updates), 2)
        self.assertEqual((self.root / "app.txt").read_text(), "before\n")
        records = list((self.store / "reports").glob("*/audit/audit.json"))
        self.assertEqual(len(records), 2)
        for path in records:
            exported = json.loads(path.read_bytes())
            self.assertEqual(exported["models"][0]["selected_model"], "requested")
            self.assertEqual(exported["models"][0]["actual_model"], "observed")
            self.assertNotIn("external-audit-fixture", path.read_text())

    def test_absolute_worktree_and_store_separation(self):
        self.plan["prs"][0]["worktree"] = str(self.folder / "external")
        self.path.write_bytes(manifest.encode(self.plan))
        identity = self.cli("validate", self.path)["identity"]
        for store in (self.folder / "external/private", self.folder / "external", self.folder):
            error = self.cli("init", self.path, "--approved", identity, "--root", self.root,
                             "--store", store, ok=False)
            self.assertTrue("overlap" in error or "already exists" in error, error)
        self.init()
        self.preflight()
        self.assertEqual(self.prepare(), self.folder / "external")

    def test_initialization_rejects_review_storage_inside_another_repository(self):
        other = self.folder / "another-repository"
        self.git("init", "-q", str(other))
        self.path.write_bytes(manifest.encode(self.plan))
        identity = self.cli("validate", self.path)["identity"]
        invalid = other / "private" / "run"
        error = self.cli("init", self.path, "--approved", identity, "--root", self.root,
                         "--store", invalid, ok=False)
        self.assertIn("outside every repository", error)
        self.assertFalse(invalid.parent.exists())
        self.assertFalse((self.root / self.plan["prs"][0]["worktree"]).exists())
        self.init()
        self.assertEqual(self.state["consumed_assignments"], 0)
        self.assertEqual(self.next()["role"], "preflight")

    def test_existing_run_recovers_external_storage_without_resetting_history(self):
        self.configure_audit()
        other = self.folder / "another-repository"
        self.store = other / "private-run"
        self.init()
        self.env.update(self.audit_git_env)
        self.preflight()
        root = self.prepare()
        self.next()
        (root / "app.txt").write_text("after\n")
        self.finish()
        self.git("init", "-q", str(other))
        saved = development.load(self.store)
        original = (self.store / "RUN.json").read_bytes()
        xdg = self.env["XDG_STATE_HOME"]
        self.env["XDG_STATE_HOME"] = str(other / "state")
        self.assertIn("outside every repository", self.mutate("next", ok=False))
        self.assertEqual((self.store / "RUN.json").read_bytes(), original)
        self.env["XDG_STATE_HOME"] = xdg
        assignment = self.next()
        recovered = Path(assignment["review_storage"])
        self.assertTrue(recovered.is_relative_to(Path(xdg)))
        self.assertIn(saved["id"], recovered.parts)
        self.assertFalse(recovered.is_relative_to(self.store))
        self.assertEqual(self.state["consumed_assignments"], len(saved["history"]) + 1)
        continued = development.load(self.store)
        self.assertEqual(continued["history"][:-1], saved["history"])
        self.assertEqual(continued["approval"], saved["approval"])
        self.assertTrue(all(continued["attempts"][key] == value
                            for key, value in saved["attempts"].items()))
        while self.state["assignment"]:
            self.execute_fixture(self.state["assignment"])
            self.next()
        self.assertEqual(self.state["outcome"], "completed")
        self.assertEqual(len(self.audit_body_updates), 2)
        final = next(item for item in reversed(development.load(self.store)["history"])
                     if item["role"] == "audit-final")
        public = self.store / "reports" / final["id"] / "public.json"
        self.git("worktree", "remove", str(root))
        archived = self.audit_cli("archive", "--pr", "first", "--public", str(public))
        self.assertTrue(Path(archived["directory"]).is_relative_to(Path(xdg)))
        bundle = json.loads((Path(archived["directory"]) / "audit.json").read_bytes())
        self.assertTrue(bundle["reviews"])
        self.assertTrue(all(item["available"] for item in bundle["reviews"]))

    def test_external_worktree_aliases_and_path_drift_are_rejected(self):
        parent = self.folder / "worktrees"
        parent.mkdir()
        alias = self.folder / "alias"
        alias.symlink_to(parent, target_is_directory=True)
        self.plan["prs"].append({**self.plan["prs"][0], "id": "second", "branch": "second",
                                 "worktree": "../alias/first/nested"})
        self.plan["prs"][0]["worktree"] = "../worktrees/first"
        self.plan["tasks"].append({**self.plan["tasks"][0], "id": "second", "pr": "second"})
        self.path.write_bytes(manifest.encode(self.plan))
        identity = self.cli("validate", self.path)["identity"]
        self.assertIn("overlap", self.cli("init", self.path, "--approved", identity,
                                        "--root", self.root, "--store", self.store, ok=False))
        self.plan["prs"].pop()
        self.plan["tasks"].pop()
        self.plan["prs"][0]["worktree"] = "../alias/first"
        self.init()
        self.preflight()
        alias.unlink()
        alias.symlink_to(self.folder / "elsewhere", target_is_directory=True)
        self.assertIn("path changed", self.mutate("next", ok=False))
        alias.unlink()
        alias.symlink_to(parent, target_is_directory=True)
        self.assertEqual(self.prepare(), parent / "first")

    def test_external_metadata_alias_is_rejected_with_safe_sibling_recovery(self):
        self.init()
        self.preflight()
        linked = self.prepare()
        for index, target in enumerate((self.root / ".git", self.root / ".git/worktrees",
                                        self.folder / ".review-loop")):
            with self.subTest(target=target):
                alias = self.folder / f"destination-{index}"
                alias.symlink_to(target, target_is_directory=True)
                candidate = copy.deepcopy(self.plan)
                candidate["prs"][0]["worktree"] = str(alias / "child")
                with self.assertRaisesRegex(manifest.ManifestError, "metadata"):
                    development.worktree_targets(linked, candidate)
                alias.unlink()
        candidate["prs"][0]["worktree"] = str(self.folder / "siblings/child")
        self.assertEqual(development.worktree_targets(linked, candidate),
                         {"first": self.folder / "siblings/child"})
        separate = self.folder / "separate-repository"
        administration = self.folder / "administration"
        subprocess.run(["git", "init", "-q", "--separate-git-dir", str(administration), str(separate)],
                       env=self.env, check=True)
        candidate["prs"][0]["worktree"] = str(administration / "child")
        with self.assertRaisesRegex(manifest.ManifestError, "metadata"):
            development.worktree_targets(separate, candidate)

    def test_worktree_controls_and_options_do_not_relax_task_paths(self):
        for value in (".", "/", "../.git/tree"):
            with self.subTest(value=value):
                candidate = copy.deepcopy(self.plan)
                candidate["prs"][0]["worktree"] = value
                with self.assertRaises(manifest.ManifestError):
                    manifest.validate(candidate, self.bundle)
        for value in ("-checkout", "bad\tpath", "bad" + chr(127)):
            candidate = copy.deepcopy(self.plan)
            candidate["prs"][0]["worktree"] = value
            validated = manifest.validate(candidate, self.bundle)
            self.assertEqual(validated["identity"], manifest.digest(manifest.encode(candidate)))
            self.path.write_bytes(manifest.encode(candidate))
            self.assertIn("Worktree path", self.cli(
                "init", self.path, "--approved", validated["identity"], "--root", self.root,
                "--store", self.store, ok=False))
        self.plan["prs"][0]["worktree"] = "../external"
        self.plan["tasks"][0]["paths"] = ["../outside"]
        with self.assertRaises(manifest.ManifestError):
            manifest.validate(self.plan, self.bundle)

    def legacy_worktree_recovery(self, destination):
        self.plan["prs"][0]["worktree"] = destination
        self.path.write_bytes(manifest.encode(self.plan))
        approved = self.cli("validate", self.path)["identity"]
        args = SimpleNamespace(manifest=str(self.path), root=str(self.root), store=str(self.store),
                               approved=approved, provider=None)
        with patch.dict(os.environ, self.env, clear=True), \
                patch.object(manifest, "executable_worktree", side_effect=manifest.relative):
            saved = development.initialize(args)
            saved.pop("worktree_roots")
            development.save(self.store, saved)
        original = (self.store / "MANIFEST.json").read_bytes()
        self.state = self.cli("status", self.store)
        self.mutate("next", "--provider", "claude-workflows")
        self.assertEqual(self.state["assignment"]["role"], "preflight")
        self.finish({name: True for name in ("artifact_access", "native_permissions", "fresh_workers",
                                             "independent_review", "result_delivery", "cancellation")})
        root = self.prepare()
        self.execute_fixture(self.next())
        self.next()
        self.review(root)
        self.mutate("reconcile", "--pr", "first", "--reason", "Repeat review within the original allowance")
        self.mutate("next", "--provider", "claude-workflows")
        self.assertEqual(self.state["assignment"]["role"], "review")
        self.review(root)
        self.assertEqual(self.next()["role"], "commit")
        self.assertEqual((self.store / "MANIFEST.json").read_bytes(), original)
        self.assertEqual(development.load(self.store)["approval"], approved)
        self.assertEqual(root, self.root / destination)

    def test_legacy_option_like_worktree_continues_without_changing_approval(self):
        self.legacy_worktree_recovery("-legacy-checkout")

    def test_legacy_control_character_worktree_continues_without_changing_approval(self):
        self.legacy_worktree_recovery("legacy\tcheckout")

    def watch_process(self, *args):
        process = subprocess.Popen(
            [sys.executable, str(SCRIPTS / "development_run.py"), "watch", str(self.store),
             "--interval", "0.02", *args], cwd=self.bundle, env=self.env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self.stop_watch, process)
        return process

    def stop_watch(self, process):
        if process.poll() is None:
            process.terminate()
        process.communicate(timeout=5)

    def watch_line(self, process):
        ready, _, _ = select.select([process.stdout], [], [], 5)
        self.assertTrue(ready, "Monitor did not report promptly")
        line = process.stdout.readline()
        self.assertTrue(line, process.stderr.read() if process.poll() is not None else "Monitor closed stdout")
        return json.loads(line)

    @pytest.mark.process(helpers=False)
    def test_watch_reports_changes_and_stalls_without_state_or_config_writes(self):
        self.init()
        before = {str(path): (path.read_bytes(), path.stat().st_mtime_ns)
                  for base in (self.store, self.folder / "home")
                  for path in base.rglob("*") if path.is_file()}
        with (self.store / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            watcher = self.watch_process("--stale-after", "0.1")
            initial = self.watch_line(watcher)
            self.assertEqual(initial["condition"], "running")
            self.assertEqual(self.watch_line(watcher)["event"], "stalled")
            self.assertEqual(watcher.wait(timeout=5), 3)
        after = {str(path): (path.read_bytes(), path.stat().st_mtime_ns)
                 for base in (self.store, self.folder / "home")
                 for path in base.rglob("*") if path.is_file() and path.name != ".lock"}
        self.assertEqual(after, {key: value for key, value in before.items() if not key.endswith("/.lock")})
        watcher = self.watch_process()
        self.watch_line(watcher)
        self.next()
        self.assertEqual(self.watch_line(watcher)["assignment"]["role"], "preflight")
        self.mutate("interrupt", "--reason", "Fixture native interruption")
        terminal = self.watch_line(watcher)
        self.assertEqual(terminal["condition"], "interrupted")
        self.assertEqual(terminal["outcome"], "blocked")
        self.assertEqual(watcher.wait(timeout=5), 1)

    def start_review_fixture(self):
        self.init()
        self.preflight()
        root = self.prepare()
        self.next()
        self.finish()
        self.next()
        return root

    @pytest.mark.process(helpers=False)
    def test_watch_hides_private_rejection_diagnostics_but_retains_recovery_reference(self):
        root = self.start_review_fixture()
        data = self.review(root, record=False)
        path = Path(data["handoff"])
        handoff = json.loads(path.read_bytes())
        handoff["attempts"][0]["result"]["limitations"].append("PRIVATE-REVIEW-DIAGNOSTIC")
        handoff["active"].pop("documentation")
        path.write_bytes(manifest.encode(handoff))
        error = self.finish(data, ok=False)
        self.assertIn("PRIVATE-REVIEW-DIAGNOSTIC", error)
        self.mutate("interrupt", "--reason", error)
        process = self.watch_process()
        output = self.watch_line(process)
        self.assertNotIn("PRIVATE-REVIEW-DIAGNOSTIC", json.dumps(output))
        self.assertEqual(output["diagnostic_reference"], str(self.store / "RUN.json") + "#/reason")
        self.assertEqual(output["condition"], "interrupted")
        self.assertEqual(process.wait(timeout=5), 1)
        self.assertIn("PRIVATE-REVIEW-DIAGNOSTIC", self.cli("status", self.store)["reason"])

    @pytest.mark.process(helpers=False)
    def test_watch_reconnect_uses_persisted_age_and_legacy_uses_observer_age(self):
        self.init()
        args = SimpleNamespace(interval=1, stale_after=5)
        for legacy, clocks, sleeps in ((False, [0, 0], 0), (True, [0, 0, 6], 1)):
            with self.subTest(legacy=legacy):
                state = development.load(self.store)
                if legacy:
                    state.pop("updated_at")
                else:
                    state["updated_at"] = 990
                original = copy.deepcopy(state)
                with patch.object(monitoring.time, "time", return_value=1000), \
                     patch.object(monitoring.time, "monotonic", side_effect=clocks), \
                     patch.object(monitoring.time, "sleep") as sleep, \
                     patch.object(monitoring, "emit") as emit:
                    self.assertEqual(monitoring.watch(self.store, lambda _: state, args), 3)
                self.assertEqual(sleep.call_count, sleeps)
                self.assertEqual(emit.call_args.args[0]["event"], "stalled")
                self.assertEqual(state, original)

    def progress(self, dispatch, role, event, *args, ok=True):
        return self.cli("progress", self.store, "--assignment", self.state["assignment"]["id"],
                        "--dispatch", dispatch, "--role", role, "--event", event, *args, ok=ok)

    @pytest.mark.process(helpers=False)
    def test_watch_reports_review_dispatches_cycles_and_unavailable_progress(self):
        self.start_review_fixture()
        watcher = self.watch_process()
        self.watch_line(watcher)
        original = (self.store / "RUN.json").read_bytes()
        self.progress(1, "review-owner", "checkpoint", "--loop", 1, "--cycle", 1)
        observed = self.watch_line(watcher)
        self.assertEqual(observed["review_progress"][0]["cycle"], 1)
        self.progress(2, "reviewer", "started", "--category", "correctness")
        self.assertEqual(self.watch_line(watcher)["review_progress"][-1]["event"], "started")
        self.progress(2, "reviewer", "reported", "--category", "correctness")
        self.assertEqual(self.watch_line(watcher)["review_progress"][-1]["event"], "reported")
        self.assertEqual((self.store / "RUN.json").read_bytes(), original)
        self.assertIn("identity changed", self.progress(2, "fixer", "started", ok=False))
        self.assertIn("allowance", self.progress(21, "reviewer", "started", ok=False))
        path = self.store / "progress" / self.state["assignment"]["id"] / "000002.json"
        private = self.folder / "private.json"
        private.write_text('{"private":"DO-NOT-PRINT"}')
        replacement = path.with_name(".invalid-progress")
        replacement.symlink_to(private)
        replacement.replace(path)
        observed = self.watch_line(watcher)
        self.assertIsNotNone(observed["progress_error"])
        self.assertNotIn("DO-NOT-PRINT", json.dumps(observed))
        self.assertEqual(watcher.wait(timeout=5), 2)
        self.assertIn("Symlink", self.progress(2, "reviewer", "reported", "--category", "correctness", ok=False))
        self.assertEqual(private.read_text(), '{"private":"DO-NOT-PRINT"}')
        path.unlink()
        self.progress(2, "reviewer", "reported", "--category", "correctness")
        self.assertIsNone(monitoring.snapshot(development.load(self.store))["progress_error"])

    def test_progress_opt_out_does_not_disable_execution_or_monitoring(self):
        self.start_review_fixture()
        config = self.root / ".claude/ioncache-ai-tools.local.json"
        config.parent.mkdir(exist_ok=True)
        config.write_text(json.dumps({"features": {"autonomous-development-progress": False}}))
        self.assertFalse(self.cli("status", self.store)["assignment"]["monitoring"]["enabled"])
        self.assertFalse(self.progress(1, "review-owner", "started")["recorded"])
        self.assertFalse((self.store / "progress").exists())
        watcher = self.watch_process()
        self.assertEqual(self.watch_line(watcher)["condition"], "running")
        self.finish(outcome="blocked")
        self.assertEqual(self.watch_line(watcher)["condition"], "blocked")
        self.assertEqual(watcher.wait(timeout=5), 1)
        self.mutate("resume", "--reason", "Continue without optional progress")
        self.assertEqual(self.next()["attempt"], 2)

    @pytest.mark.process(helpers=False)
    def test_watch_classifies_all_terminal_outcomes_and_unreadable_state(self):
        self.init()
        initial = development.load(self.store)
        for outcome, reason, condition, code in (
            ("completed", None, "complete", 0),
            ("blocked", "Fixture blocked", "blocked", 1),
            ("waiting", "Fixture prerequisite", "waiting", 1),
            ("failed", "Assignment allowance exhausted: run:preflight:pr", "exhausted", 1),
            ("failed", "Other failure", "failed", 1),
        ):
            with self.subTest(condition=condition):
                development.save(self.store, {**initial, "outcome": outcome, "reason": reason})
                process = self.watch_process()
                self.assertEqual(self.watch_line(process)["condition"], condition)
                self.assertEqual(process.wait(timeout=5), code)
        (self.store / "RUN.json").write_text('{"unfinished":')
        process = self.watch_process()
        self.assertEqual(self.watch_line(process)["event"], "unavailable")
        self.assertEqual(process.wait(timeout=5), 2)

    @pytest.mark.stable_storage
    def test_workflow_writes_private_progress_for_actual_flat_dispatches(self):
        self.init()
        self.preflight()
        self.prepare()
        self.next()
        self.finish()
        roles = self.workflow("review-complete")
        self.assertIn("reviewer", roles)
        saved = development.load(self.store)
        review = next(item for item in saved["history"] if item["role"] == "review")
        records, error = monitoring.records(saved, review)
        self.assertIsNone(error)
        self.assertEqual(len(records), roles.count("reviewer") + roles.count("review-owner"))
        self.assertEqual(records[0]["role"], "review-owner")
        self.assertEqual(records[-1]["role"], "review-owner")
        self.assertTrue(all(item["event"] == "reported" for item in records))
        self.assertEqual({item["category"] for item in records if item["role"] == "reviewer"},
                         monitoring.category_names() - {"jsdoc"})
        observations, unavailable = models.observations(saved, "first")
        self.assertFalse(unavailable)
        self.assertEqual(len(observations), len(roles))
        for item in observations:
            self.assertEqual(item["actual_model"], "observed-" + item["role"])
            self.assertNotEqual(item["actual_model"], item["selected_model"])

    def test_manifest_native_choices_and_review_overrides_keep_old_identity(self):
        original = manifest.validate(self.plan, self.bundle)
        self.assertEqual(original["identity"], manifest.digest(manifest.encode(self.plan)))
        execution = self.plan["configuration"]["execution"]
        execution["models"] = {
            "development-control": {"model": "native-cheap", "effort": "low", "fallback": "fail"},
            "implement": {"model": "native-capable", "effort": "high", "fallback": "fail"},
        }
        execution["review_options"] = {"reviewer_model": "native-reviewer", "reviewer_effort": "high"}
        self.init()
        self.next()
        options = self.state["assignment"]["model_selection"]["review_options"]
        self.assertEqual(options["roles"]["reviewer"]["model"], "native-reviewer")
        self.assertEqual(options["roles"]["reviewer"]["fallback"], "fail")
        self.assertIn("reviewer_model", options["specified"])
        with self.assertRaises(manifest.ManifestError):
            manifest.validate({**self.plan, "configuration": {
                **self.plan["configuration"], "execution": {**execution, "models": {"unknown": {}}}
            }}, self.bundle)

    def test_native_model_observation_requires_a_source_and_stays_separate_from_selection(self):
        self.init()
        self.next()
        args = ("model-report", self.store, "--invocation", "private-fixture", "--call", "1",
                "--role", "preflight", "--assignment", self.state["assignment"]["id"],
                "--selected-model", "requested-model", "--selected-effort", "high")
        result = self.cli(*args)
        path = Path(result["model_report"])
        self.assertIsNone(json.loads(path.read_bytes())["actual_model"])
        self.assertIn("native observation source", self.cli(*args, "--actual-model", "claimed-model", ok=False))
        self.cli(*args, "--actual-model", "observed-model", "--source", "native-transcript")
        self.cli(*args)
        item = json.loads(path.read_bytes())
        self.assertEqual(item["actual_model"], "observed-model")
        self.assertEqual(item["selected_model"], "requested-model")
        report_path = self.report(outcome="blocked")
        report = json.loads(report_path.read_bytes())
        report["model_report"] = str(path)
        report_path.write_bytes(manifest.encode(report))
        self.mutate("record", "--report", report_path)
        records, unavailable = models.observations(development.load(self.store), "first")
        self.assertFalse(unavailable)
        self.assertEqual(records[0]["source"], "native-transcript")
        self.assertNotIn("private-fixture", json.dumps(records))

    def test_configured_model_recovery_is_counted_and_not_repeatable(self):
        self.plan["limits"]["attempts"] = 3
        self.plan["configuration"]["execution"]["models"] = {
            "preflight": {"model": "native-explicit", "effort": "high", "fallback": "configured"}
        }
        self.init()
        first = self.next()
        args = ("--key", first["key"], "--role", "preflight", "--reason", "Native model rejected",
                "--shutdown-evidence", "Native fixture exited without effects")
        self.assertIn("Collect or retire", self.mutate("model-fallback", *args, ok=False))
        self.finish(outcome="blocked")
        self.mutate("model-fallback", *args)
        self.mutate("resume", "--reason", "Use the permitted configured retry")
        second = self.next()
        self.assertEqual(second["configured_model_fallbacks"], ["preflight"])
        self.assertEqual(second["attempt"], 2)
        self.assertEqual(self.state["consumed_assignments"], 2)
        self.finish(outcome="blocked")
        self.assertIn("already scheduled", self.mutate("model-fallback", *args, ok=False))
        self.mutate("resume", "--reason", "Keep other authorized recovery available")
        self.assertEqual(self.next()["configured_model_fallbacks"], [])

    def test_explicit_review_fallback_failure_cannot_be_waived(self):
        self.plan["configuration"]["execution"]["review_options"] = {"fallback": "fail"}
        self.start_review_fixture()
        assignment = self.state["assignment"]
        self.finish(outcome="blocked")
        self.assertIn("requires failure", self.mutate(
            "model-fallback", "--key", assignment["key"], "--role", "reviewer",
            "--reason", "Model rejected", "--shutdown-evidence", "Fixture exited", ok=False))
        self.assertEqual(self.state["consumed_assignments"], 4)

    def test_launch_only_fallback_policy_survives_durable_recovery(self):
        self.plan["limits"]["attempts"] = 3
        self.init()
        choices = {role: {"model": "native-" + role, "effort": "high", "fallback": "fail"}
                   for role in models.ROLES}
        self.mutate("next", "--models", json.dumps(choices))
        first = self.state["assignment"]
        self.finish(outcome="blocked")
        flags = ("--key", first["key"], "--role", "preflight", "--reason", "Native model unavailable",
                 "--shutdown-evidence", "The fixture worker exited without effects")
        self.assertIn("requires failure", self.mutate("model-fallback", *flags, ok=False))
        self.mutate("resume", "--reason", "Retry with the newly selected configured-fallback policy")
        choices["preflight"]["fallback"] = "configured"
        self.mutate("next", "--models", json.dumps(choices))
        self.finish(outcome="blocked")
        self.mutate("model-fallback", *flags)
        self.mutate("resume", "--reason", "Consume the allowed configured retry")
        self.mutate("next", "--models", json.dumps(choices))
        self.assertEqual(self.state["assignment"]["configured_model_fallbacks"], ["preflight"])
        self.assertEqual(self.state["consumed_assignments"], 3)

    def model_optout_dispatch(self, feature):
        self.plan["configuration"]["execution"]["models"] = {
            "reviewer": {"model": "explicit-reviewer", "effort": "medium", "fallback": "fail"}}
        config = Path(self.env["HOME"]) / ".claude/ioncache-ai-tools.local.json"
        config.parent.mkdir(parents=True)
        config.write_bytes(manifest.encode({"features": {feature: False}}))
        self.init()
        self.preflight()
        self.prepare()
        implementation = ({} if feature == "autonomous-development-model-selection"
                          else {"model": "fixture-implement", "effort": "high"})
        observed = self.workflow("review-model-policy", {
            "implement": implementation, "review-owner": {},
            "reviewer": {"model": "explicit-reviewer", "effort": "medium"}})
        self.assertIn("implement", observed)
        self.assertIn("reviewer", observed)
        self.assertEqual(observed[-1:], ["commit"])

    @pytest.mark.stable_storage
    def test_review_model_optout_preserves_implementation_and_explicit_review_choices(self):
        self.model_optout_dispatch("review-auto-model-selection")

    @pytest.mark.stable_storage
    def test_development_model_optout_preserves_explicit_review_choices(self):
        self.model_optout_dispatch("autonomous-development-model-selection")

    def test_model_observations_do_not_cross_pr_boundaries(self):
        self.start_review_fixture()
        state = development.load(self.store)
        first = next(item for item in state["history"] if item["role"] == "implement")
        second = {**first, "id": "A9000", "pr": "second"}
        state["history"].append(second)
        for call, assignment, role, actual in (
            (1, first["id"], "implement", "first-pr-only"),
            (2, second["id"], "implement", "second-pr-only"),
            (3, None, "development-control", "shared-control"),
        ):
            models.write(state, SimpleNamespace(
                call=call, invocation="multi-pr-models", assignment=assignment, role=role,
                source="native-context", selected_model=None, selected_effort=None,
                actual_model=actual, actual_effort=None))
        for pr, expected in (("first", "first-pr-only"), ("second", "second-pr-only")):
            records, unavailable = models.observations(state, pr)
            self.assertFalse(unavailable)
            self.assertEqual({item["actual_model"] for item in records}, {expected, "shared-control"})

    def test_category_handback_is_required_and_recoverable_without_resetting_work(self):
        self.init()
        self.preflight()
        root = self.prepare()
        self.next()
        self.finish()
        self.next()
        data = self.review(root, record=False)
        path = Path(data["handoff"])
        original = json.loads(path.read_text())
        incomplete = copy.deepcopy(original)
        incomplete["active"].pop("security")
        path.write_bytes(manifest.encode(incomplete))
        self.assertIn("Category review is incomplete", self.finish(data, ok=False))
        self.assertEqual(self.state["assignment"]["role"], "review")
        path.write_bytes(manifest.encode(original))
        self.finish(data)
        coverage = self.state["prs"]["first"]["review"]["coverage"]
        self.assertTrue(coverage["structurally_complete"])
        self.assertTrue(coverage["limitations"])
        self.assertEqual(self.next()["role"], "commit")

    def test_source_read_assessment_recovers_review_without_restarting_assignment(self):
        root = self.start_review_fixture()
        data = self.review(root, record=False)
        path = Path(data["handoff"])
        handoff = json.loads(path.read_text())
        attempt = next(item for item in handoff["attempts"]
                       if item["packet"]["review_type"] == "documentation")
        report = attempt["result"]
        source = ".github/instructions/swr.instructions.md"
        report["outcome"] = "partial"
        report["coverage"].update(isolation="contaminated", reference_sources=[source],
                                  context_conflicts=["Read a project:swr source referenced by the plan"])
        original = manifest.encode(report)
        report_path = Path(attempt["packet"]["result_file"])
        report_path.write_bytes(original)
        path.write_bytes(manifest.encode(handoff))
        frozen = Path(data["plan"]).read_bytes()
        consumed = self.state["consumed_assignments"]
        self.assertIn("Category review is incomplete", self.finish(data, ok=False))
        handoff["other_workers"][0]["isolation_assessments"] = [{
            "attempt": attempt["id"], "packet_identity": attempt["packet"]["identity"],
            "result_identity": assignments.digest(report), "kind": "evidence-read-only",
            "sources": [source], "assigned_ruleset_only": True, "otherwise_complete": True,
            "evidence": ["Offline assessment: the original documentation pass is complete; "
                         "only its classification of the reference read is mistaken."],
        }]
        path.write_bytes(manifest.encode(handoff))
        self.finish(data)
        self.assertEqual(report_path.read_bytes(), original)
        self.assertEqual(Path(data["plan"]).read_bytes(), frozen)
        self.assertEqual(self.state["consumed_assignments"], consumed)
        self.assertTrue(self.state["prs"]["first"]["review"]["coverage"]["structurally_complete"])
        self.assertEqual(self.next()["role"], "commit")

    def test_legacy_review_requires_counted_reconciliation_before_commit(self):
        self.init()
        self.preflight()
        root = self.prepare()
        self.next()
        self.finish()
        self.next()
        self.review(root)
        path = self.store / "RUN.json"
        saved = json.loads(path.read_text())
        saved["prs"]["first"]["review"].pop("coverage")
        path.write_bytes(manifest.encode(saved))
        consumed = self.state["consumed_assignments"]
        self.assertIn("reconcile this PR", self.mutate("next", ok=False))
        self.mutate("reconcile", "--pr", "first", "--reason", "Replace legacy coverage")
        self.assertEqual(self.next()["role"], "review")
        self.assertEqual(self.state["consumed_assignments"], consumed + 1)
        self.review(root)
        self.assertEqual(self.next()["role"], "commit")

    def test_final_category_plan_must_match_the_completed_full_review(self):
        self.init()
        self.preflight()
        root = self.prepare()
        self.next()
        self.finish()
        self.next()
        data = self.review(root, record=False)
        path = Path(data["plan"])
        original = json.loads(path.read_text())
        for field, value in (("kind", "focused"), ("snapshot", "different-revision"),
                             ("base", "different-base"), ("root", str(self.root))):
            with self.subTest(field=field):
                changed = copy.deepcopy(original)
                changed["request"][field] = value
                changed.pop("identity")
                path.write_bytes(manifest.encode(assignments.seal(changed)))
                self.assertIn("does not match the completed full review", self.finish(data, ok=False))
        path.write_bytes(manifest.encode(original))
        self.finish(data)

    @pytest.mark.stable_storage
    def test_named_acceptance_checks_cannot_be_skipped_or_substituted(self):
        root = self.start_review_fixture()
        for scope in ("task", "pr"):
            for check in (
                    {"name": "fixture", "result": "not_applicable", "evidence": "Incorrectly skipped"},
                    {"name": "unrelated", "result": "passed", "evidence": "Different command passed"}):
                with self.subTest(scope=scope, check=check):
                    data = self.review(root, record=False, checks=[check])
                    self.assertEqual(self.review_cli(root, ["status", data["ledger"]])["outcome"], "completed")
                    before = (self.store / "RUN.json").read_bytes()
                    self.assertIn("Required acceptance checks did not all pass", self.finish(data, ok=False))
                    self.assertEqual((self.store / "RUN.json").read_bytes(), before)
            self.review(root)
            self.assertEqual(self.next()["role"], "commit")
            self.execute_fixture(self.state["assignment"])
            if scope == "task":
                self.assertEqual(self.next()["role"], "draft")
                self.execute_fixture(self.state["assignment"])
                self.assertEqual(self.next()["role"], "review")
                self.assertIsNone(self.state["assignment"]["task"])
        self.assertEqual(self.next()["role"], "ready")

    def test_legacy_coverage_without_file_inventory_requires_counted_review(self):
        self.init()
        self.preflight()
        root = self.prepare()
        self.next()
        self.finish()
        self.next()
        self.review(root)
        path = self.store / "RUN.json"
        saved = json.loads(path.read_text())
        saved["prs"]["first"]["review"]["coverage"].pop("files")
        path.write_bytes(manifest.encode(saved))
        consumed = self.state["consumed_assignments"]
        self.assertIn("complete file coverage", self.mutate("next", ok=False))
        self.mutate("reconcile", "--pr", "first", "--reason", "Bind legacy coverage to changed files")
        self.assertEqual(self.next()["role"], "review")
        self.assertEqual(self.state["consumed_assignments"], consumed + 1)
        self.review(root)
        self.assertEqual(self.next()["role"], "commit")

    def abandoned_review_retry(self, damage):
        if damage == "symlink-ledger":
            self.configure_audit()
        self.init()
        if damage == "symlink-ledger":
            self.env.update(self.audit_git_env)
        self.preflight()
        root = self.prepare()
        self.next()
        self.finish()
        self.next()
        data = self.review(root, record=False)
        path = Path(data["ledger"])
        if damage == "missing-ledger":
            path.unlink()
        elif damage == "symlink-ledger":
            path.unlink()
            path.symlink_to("unavailable-history.json")
            for _ in range(2):
                self.assertIn("Symlink", self.finish(data, ok=False))
        elif damage == "file-map":
            ledger = json.loads(path.read_bytes())
            ledger["snapshots"][ledger["initial"]]["files"] = []
            path.write_bytes(manifest.encode(ledger))
        elif damage == "closure-marker":
            (path.parent / "ABANDONED.json").write_bytes(b"damaged closure")
            for _ in range(2):
                self.assertIn("recover-closure", self.finish(data, ok=False))
        else:
            obj = next((path.parent / "objects").iterdir())
            if damage == "missing-object":
                obj.unlink()
            else:
                obj.write_bytes(b"corrupt")
        command = "recover-closure" if damage == "closure-marker" else "abandon"
        self.review_cli(root, [command, data["ledger"], "--reason", "Damaged review evidence",
                              "--evidence", "Inspected surviving ledger, objects and closure record",
                              "--shutdown-evidence", "Offline review fixture has exited"])
        for _ in range(2):
            self.assertIn("Review is incomplete", self.finish(data, ok=False))
        self.finish(outcome="blocked")
        consumed = self.state["consumed_assignments"]
        self.mutate("resume", "--reason", "Separate review attempt within approved limits")
        assignment = self.next()
        self.assertEqual(assignment["role"], "review")
        self.assertEqual(assignment["attempt"], 2)
        self.assertEqual(self.state["consumed_assignments"], consumed + 1)
        self.review(root)
        self.assertEqual(self.next()["role"], "commit")
        if damage == "symlink-ledger":
            self.execute_fixture(self.state["assignment"])
            while self.next():
                self.execute_fixture(self.state["assignment"])
            self.assertTrue(path.is_symlink())
            self.assertEqual(path.readlink(), Path("unavailable-history.json"))
            self.assertEqual(self.state["outcome"], "completed")
            final = development.load(self.store)
            audit_assignment = next(item for item in final["history"] if item["role"] == "audit-final")
            bundle = json.loads((audit.directory(final, audit_assignment) / "audit.json").read_bytes())
            record = next(item for item in bundle["reviews"] if item["id"] == path.parent.name)
            self.assertFalse(record["available"])
            self.assertEqual(record["allowance"], "unavailable")
            self.assertTrue(record["closure_digest"])

    def test_abandoned_review_can_only_continue_as_a_counted_retry(self):
        self.abandoned_review_retry("missing-ledger")

    def test_symlinked_review_requires_counted_retry_and_remains_in_final_audit(self):
        self.abandoned_review_retry("symlink-ledger")

    def test_missing_review_object_requires_counted_retry(self):
        self.abandoned_review_retry("missing-object")

    def test_corrupt_review_object_requires_counted_retry(self):
        self.abandoned_review_retry("corrupt-object")

    def test_malformed_review_snapshot_requires_counted_retry(self):
        self.abandoned_review_retry("file-map")

    def test_damaged_review_closure_requires_counted_retry(self):
        self.abandoned_review_retry("closure-marker")

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
        (root / "discovered.txt").write_text("required implementation dependency")
        self.git("add", "discovered.txt", root=root)
        self.assertIn("HEAD or staging", self.finish(ok=False))
        self.git("restore", "--staged", "discovered.txt", root=root)
        path = self.report()
        report = json.loads(path.read_text())
        report["artifacts"]["design"] = "0" * 64
        path.write_bytes(manifest.encode(report))
        self.assertIn("artifact identity", self.mutate("record", "--report", path, ok=False))
        self.assertEqual(self.cli("status", self.store)["assignment"]["id"], self.state["assignment"]["id"])
        consumed = self.state["consumed_assignments"]
        self.finish()
        self.assertEqual(self.state["consumed_assignments"], consumed)
        self.assertEqual((root / "discovered.txt").read_text(), "required implementation dependency")
        self.assertEqual(self.next()["role"], "review")

    def test_worker_owned_commit_can_be_unstaged_and_recorded_without_losing_edits(self):
        self.init()
        self.preflight()
        root = self.prepare()
        assignment = self.next()
        (root / "app.txt").write_text("required implementation\n")
        self.git("add", "app.txt", root=root)
        self.git("commit", "-qm", "fixture accidental worker commit", root=root)
        self.assertIn("HEAD or staging", self.finish(ok=False))
        baseline = self.cli("status", self.store)["assignment"]["before"]
        self.assertEqual(baseline, assignment["before"])
        self.git("reset", "--soft", baseline["head"], root=root)
        self.assertIn("HEAD or staging", self.finish(ok=False))
        self.git("restore", "--staged", "app.txt", root=root)
        consumed = self.state["consumed_assignments"]
        self.finish()
        self.assertEqual(self.state["consumed_assignments"], consumed)
        self.assertEqual((root / "app.txt").read_text(), "required implementation\n")
        self.assertEqual(self.git("rev-parse", "HEAD", root=root), baseline["head"])
        self.assertEqual(self.next()["role"], "review")

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

    def test_retry_cannot_omit_a_file_left_by_a_blocked_implementation(self):
        self.plan["tasks"][0]["paths"] = ["new.txt"]
        self.init()
        self.preflight()
        root = self.prepare()
        (root / "setup.txt").write_text("unrelated setup\n")
        self.next()
        (root / "new.txt").write_text("approved new file\n")
        self.finish(outcome="blocked")
        self.mutate("resume", "--reason", "Continue the retained partial implementation")
        self.next()
        self.finish()
        self.next()
        self.review(root)
        self.next()
        for _ in range(2):
            self.finish({"commit": self.git("rev-parse", "HEAD", root=root)}, ok=False)
        self.git("add", "new.txt", root=root)
        self.git("commit", "-qm", "fixture recovered file", root=root)
        self.finish({"commit": self.git("rev-parse", "HEAD", root=root)})
        self.assertEqual(self.git("ls-files", "--others", "--exclude-standard", root=root), "setup.txt")
        self.assertEqual((root / "setup.txt").read_text(), "unrelated setup\n")

    def test_category_coverage_cannot_omit_local_additions_or_deletions(self):
        self.plan["tasks"][0]["paths"] = ["."]
        self.init()
        self.preflight()
        root = self.prepare()
        self.next()
        (root / "app.txt").unlink()
        (root / "new\nfile.txt").write_text("approved addition\n")
        self.finish()
        self.next()
        self.assertEqual(development.review_files(root, self.state["assignment"]["comparison_base"]),
                         ["app.txt", "new\nfile.txt"])
        files = [".gitignore"]
        data = self.review(root, record=False, files=files)
        for _ in range(2):
            self.assertIn("omits changed files", self.finish(data, ok=False))
        consumed = self.state["consumed_assignments"]
        self.mutate("interrupt", "--reason", "Retain the incomplete category review")
        self.mutate("retire", "--reason", "Review omitted changed files",
                    "--shutdown-evidence", "Offline review fixture has exited")
        self.mutate("resume", "--reason", "Perform a counted complete review")
        self.next()
        self.assertEqual(self.state["consumed_assignments"], consumed + 1)
        self.review(root, files=["app.txt", "new\nfile.txt"])
        self.assertEqual(self.next()["role"], "commit")

    def test_full_pr_coverage_cannot_omit_committed_changes(self):
        self.init()
        self.preflight()
        root = self.prepare()
        while True:
            assignment = self.next()
            if assignment["role"] == "review" and assignment["task"] is None:
                break
            self.execute_fixture(assignment)
        self.assertEqual(self.git("status", "--porcelain", root=root), "")
        data = self.review(root, record=False, files=[".gitignore"])
        self.assertIn("omits changed files", self.finish(data, ok=False))

    def test_missing_inputs_allow_shutdown_but_not_execution_or_acceptance(self):
        self.init()
        self.next()
        report = self.report({name: True for name in (
            "artifact_access", "native_permissions", "fresh_workers",
            "independent_review", "result_delivery", "cancellation")})
        snapshot = self.store / "inputs/design.md"
        snapshot.unlink()
        self.state = self.cli("status", self.store)
        self.assertIn("regular file", self.state["input_error"])
        self.mutate("record", "--report", report, ok=False)
        self.mutate("interrupt", "--reason", "Snapshot temporarily unavailable")
        self.mutate("resume", "--reason", "Still unavailable", ok=False)
        self.mutate("retire", "--reason", "Stopped the incomplete fixture",
                    "--shutdown-evidence", "No native worker remains in this offline fixture")
        consumed = self.state["consumed_assignments"]
        self.mutate("resume", "--reason", "Still unavailable", ok=False)
        snapshot.write_bytes((self.bundle / "design.md").read_bytes())
        self.mutate("resume", "--reason", "Restored the exact approved snapshot")
        self.preflight()
        self.assertIsNone(self.state["input_error"])
        self.assertEqual(self.state["consumed_assignments"], consumed + 1)

    def test_private_inputs_survive_intake_removal_but_reject_tampering(self):
        self.init()
        for item in self.plan["artifacts"]:
            (self.bundle / item["snapshot"]).unlink()
        self.cli("status", self.store)
        run = self.store / "RUN.json"
        original = run.read_bytes()
        changed = json.loads(original)
        changed["manifest"]["limits"]["attempts"] += 1
        run.write_bytes(manifest.encode(changed))
        self.assertIn("Approved manifest changed", self.cli("status", self.store, ok=False))
        run.write_bytes(original)
        shared = self.store / "MANIFEST.json"
        shared.write_text("{}")
        self.assertIn("Shared approved manifest changed", self.cli("status", self.store, ok=False))
        shared.write_bytes(manifest.encode(self.plan))
        (self.store / "inputs/design.md").write_text("Changed private snapshot")
        self.assertIn("Artifact changed", self.cli("status", self.store)["input_error"])
        self.assertIn("Artifact changed", self.mutate("next", ok=False))

    def test_unreadable_inputs_keep_shutdown_bookkeeping_available(self):
        self.init()
        self.next()
        snapshot = self.store / "inputs/design.md"
        original_read = Path.read_bytes

        def unreadable(path):
            if path == snapshot:
                raise PermissionError("Fixture cannot read approved snapshot")
            return original_read(path)

        with patch.object(Path, "read_bytes", unreadable):
            state = development.summary(development.load(self.store))
            self.assertIn("cannot read approved snapshot", state["input_error"])
            for command in ("interrupt", "retire"):
                extra = ["--shutdown-evidence", "Fixture workers exited"] if command == "retire" else []
                args = development.parser().parse_args([
                    command, str(self.store), "--revision", str(state["revision"]),
                    "--reason", "Inputs unavailable", *extra])
                state = development.mutate(args, self.store)
                self.assertIn("cannot read approved snapshot", state["input_error"])
        self.state = self.cli("status", self.store)
        self.mutate("resume", "--reason", "Snapshot readable again")
        self.preflight()

    def test_inprocess_checks_preserve_invoking_user_configuration(self):
        caller = self.folder / "invoking-user"
        originals = {}
        for host in (".claude", ".codex", ".copilot"):
            path = caller / host / "ioncache-ai-tools.local.json"
            path.parent.mkdir(parents=True)
            contents = b'{"features":{"autonomous-development":false,"retired-fixture-setting":true}}\n'
            path.write_bytes(contents)
            originals[path] = contents
        environment = {**self.env, "HOME": str(caller), "CODEX_HOME": str(caller / ".codex"),
                       "COPILOT_HOME": str(caller / ".copilot")}
        with patch.dict(os.environ, environment, clear=True):
            result = unittest.TestResult()
            type(self)("test_unreadable_inputs_keep_shutdown_bookkeeping_available").run(result)
        self.assertTrue(result.wasSuccessful(), result.errors + result.failures)
        self.assertEqual({path: path.read_bytes() for path in originals}, originals)

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

    def test_review_rejects_drift_during_coverage_without_publishing_acceptance(self):
        self.init()
        self.preflight()
        root = self.prepare()
        self.next()
        (root / "app.txt").write_text("after\n")
        self.finish()
        self.next()
        data = self.review(root, record=False)
        args = development.parser().parse_args([
            "record", str(self.store), "--revision", str(self.state["revision"]),
            "--report", str(self.report(data))])
        path = self.store / "RUN.json"
        before = path.read_bytes()
        check = assignments.check

        def change_during_coverage(phase, handoff):
            result = check(phase, handoff)
            self.assertTrue(result["structurally_complete"])
            (root / "app.txt").write_text("changed during coverage\n")
            return result

        with patch.dict(os.environ, self.env, clear=True), \
                patch.object(assignments, "check", side_effect=change_during_coverage) as checked:
            with self.assertRaisesRegex(manifest.ManifestError, "Worktree drift"):
                development.mutate(args, self.store)
            checked.assert_called_once()
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.cli("status", self.store), self.state)
        self.assertIn("incomplete or stale", self.finish(data, ok=False))
        self.assertEqual(path.read_bytes(), before)
        self.review(root)
        self.assertEqual(self.next()["role"], "commit")

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


def workflow_review_fixture(fixture):
    """Supply offline native review work through the real persisted ledger helpers."""
    worker = DevelopmentRunTests()
    worker.env = dict(os.environ)
    worker.store = Path(fixture["store"])
    worker.plan = development.load(worker.store)["manifest"]
    worker.state = worker.cli("status", worker.store)
    assignment = worker.state["assignment"]
    root = Path(assignment["root"])
    saved = worker.store / "reports" / "workflow-review.json"
    if fixture["action"] == "prepare":
        if saved.exists():
            data = json.loads(saved.read_bytes())
            status = worker.review_cli(root, ["status", data["ledger"]])
            worker.review_cli(root, ["apply", data["ledger"], "--revision", str(status["revision"])],
                              {"type": "reconcile", "actor": "fixture-owner",
                               "reason": "Counted retry after worker shutdown",
                               "evidence": ["Retained prior phase; correcting its request contract"]})
        else:
            status = worker.review_cli(root, [
                "init", "--objective", "Persisted workflow review", "--scope", "fixture",
                "--storage", assignment["review_storage"],
                "--base", assignment["comparison_base"],
                "--max-loops", str(worker.plan["limits"]["review_loops"]),
                "--max-fix-cycles", str(worker.plan["limits"]["fix_cycles"])])
            data = {"ledger": status["ledger"]}
        status = worker.review_cli(root, ["status", data["ledger"]])
        records, phase = worker.review_records(root, status["snapshot"])
        data.update(records)
        for packet in phase["packets"].values():
            Path(packet["result_file"]).unlink()
        worker.review_cli(root, ["apply", data["ledger"], "--revision", str(status["revision"])],
                          {"type": "start_review", "actor": "fixture-owner", "reason": json.dumps(phase)})
        saved.write_bytes(manifest.encode(data))
        return {"packets": list(phase["packets"].values()), **data}
    worker.assertIn(fixture["action"], ("finish", "finish-recovered"))
    data = json.loads(saved.read_bytes())
    if fixture["action"] == "finish-recovered":
        data["ledger"] = assignment["recovered_ledger"]
        for batch in development.load(worker.store).get("handoffs", {}).values():
            if batch["assignment"] != assignment["id"] or batch["status"] != "reconciled":
                continue
            for number, job in enumerate(batch["spec"]["jobs"], 1):
                if job["role"] == "reviewer":
                    worker.handoff("finish", "--batch", batch["id"], "--job", number)
    handoff = json.loads(Path(data["handoff"]).read_bytes())
    for attempt in handoff["attempts"]:
        attempt["result"] = json.loads(Path(attempt["packet"]["result_file"]).read_bytes())
    Path(data["handoff"]).write_bytes(manifest.encode(handoff))
    phase = json.loads(Path(data["plan"]).read_bytes())
    subprocess.run([sys.executable, "-c", "assert True"], cwd=root, env=worker.env, check=True)
    for event in [
        {"type": "review_done", "passes": [
            {"name": category, "worker": "unobserved (non-identity marker)", "result": "complete",
             "evidence": "Offline native fixture wrote its complete result"}
            for category in phase["required"]],
         "checks": [{"name": "fixture", "result": "passed", "evidence": "Fixture command exited zero"}]},
        {"type": "advance"},
    ]:
        status = worker.review_cli(root, ["status", data["ledger"]])
        worker.review_cli(root, ["apply", data["ledger"], "--revision", str(status["revision"])],
                          {"actor": "fixture-owner", "reason": "Persisted offline review", **event})
    return {"outcome": "complete", "result_file": str(worker.report(data)), "requests": []}


if __name__ == "__main__":
    if sys.argv[1:] == ["--workflow-review-fixture"]:
        print(json.dumps(workflow_review_fixture(json.load(sys.stdin))))
    else:
        unittest.main()
