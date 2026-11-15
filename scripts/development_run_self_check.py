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
import development_audit as audit
import development_run as development
import review_assignments as assignments


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
        options = subprocess.run(
            [sys.executable, str(SCRIPTS / "review_options.py"), "review-validate-fix-loop"],
            cwd=root, env=self.env, capture_output=True, text=True, check=True)
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

    def review(self, root, *, record=True, files=None, finding=False):
        assignment = self.state["assignment"]
        base = assignment["comparison_base"]
        args = ["init", "--objective", "Fixture review", "--scope", "fixture", "--base", base,
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
             "checks": [{"name": "fixture", "result": "passed", "evidence": "Fixture command exited zero"}]},
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
        self.audit_git_env = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": f"url.file://{self.remote}.insteadOf",
                              "GIT_CONFIG_VALUE_0": self.plan["repository"]["url"]}
        self.audit_comments = []
        self.lose_audit_response = False

    def audit_export(self):
        state = development.load(self.store)
        active = state["active"]
        self.git("push", "origin", f"HEAD:refs/heads/{self.plan['prs'][0]['branch']}",
                 root=Path(active["root"]))
        records = [audit.review_record(path) for path in
                   (Path(active["root"]) / ".review-loop").glob("*/REVIEW_LEDGER.json")]
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
        result = subprocess.run([sys.executable, str(SCRIPTS / "development_audit.py"),
                                 operation, str(self.store), *args],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0 if ok else 2, result.stdout + result.stderr)
        return json.loads(result.stdout) if ok else result.stderr

    def audit_api(self, endpoint, *, data=None, paginate=False):
        if endpoint == "user":
            return {"login": "fixture-bot"}
        if endpoint == "repos/fixture/project/pulls/1":
            head = self.git("ls-remote", "origin", "refs/heads/fixture-feature").split()[0]
            return {"state": "open", "head": {"sha": head, "ref": "fixture-feature",
                                              "repo": {"full_name": "fixture/project"}}}
        if paginate:
            self.assertEqual(endpoint, "repos/fixture/project/issues/1/comments?per_page=100")
            return [copy.deepcopy(self.audit_comments)]
        self.assertEqual(endpoint, "repos/fixture/project/issues/1/comments")
        self.assertIsNotNone(data)
        comment = {"body": data["body"], "user": {"login": "fixture-bot"},
                   "html_url": f"https://github.com/fixture/project/pull/1#issuecomment-{len(self.audit_comments) + 1}"}
        self.audit_comments.append(comment)
        if self.lose_audit_response:
            self.lose_audit_response = False
            raise OSError("Fixture lost response after comment creation")
        return copy.deepcopy(comment)

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
            first = self.git("ls-remote", "origin", "refs/heads/" + exported["branch"])
            receipt = audit.publish(state, active, exported["identity"])
            self.assertEqual(first, self.git("ls-remote", "origin", "refs/heads/" + exported["branch"]))
        self.assertEqual(len(self.audit_comments), 1)
        self.assertEqual(before, self.review_cli(root, ["fingerprint"]))
        self.finish(receipt)
        while self.next():
            self.execute_fixture(self.state["assignment"])
        self.assertEqual(self.state["outcome"], "completed")
        self.assertEqual(len(self.audit_comments), 2)
        self.assertEqual([item["stage"] for item in self.state["prs"]["first"]["audits"]], list(audit.ROLES))
        self.assertIn(receipt["audit_commit"], self.audit_comments[0]["body"])
        final = self.state["prs"]["first"]["audits"][-1]
        self.assertNotEqual(receipt["audit_commit"], final["audit_commit"])
        self.assertEqual(final["code_commit"], self.git("rev-parse", "HEAD", root=root))
        tree = subprocess.run(["git", "--git-dir", str(self.remote), "ls-tree", "-r", "--name-only",
                               receipt["audit_commit"]], env=self.env, capture_output=True, text=True, check=True)
        self.assertEqual(set(tree.stdout.splitlines()), set(audit.FILES))
        parents = subprocess.run(["git", "--git-dir", str(self.remote), "rev-list", "--parents", "-n", "1",
                                  receipt["audit_commit"]], env=self.env, capture_output=True,
                                 text=True, check=True)
        self.assertEqual(parents.stdout.strip(), receipt["audit_commit"])

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

    def test_git_transformations_cannot_publish_unapproved_audit_bytes_or_files(self):
        self.start_audit_fixture()
        state, active, exported = self.audit_export()
        original = audit.command
        for name in ("AUDIT.md", "unexpected.txt"):
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
                self.assertEqual(self.git("ls-remote", "origin", "refs/heads/" + exported["branch"]), "")
                self.assertEqual(self.audit_comments, [])

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
        self.assertIn("receipt.json", self.finish({}, ok=False))
        self.assertEqual(before, (self.store / "RUN.json").read_bytes())
        stale = {"state": "open", "head": {"sha": "0" * 40, "ref": "fixture-feature",
                                           "repo": {"full_name": "fixture/project"}}}
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
        self.assertEqual(self.audit_comments, [])
        self.assertEqual(self.git("ls-remote", "origin"), "")

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
        self.assertEqual(len(self.audit_comments), 2)

    def workflow(self, scenario):
        fixture = {"python": sys.executable, "store": str(self.store), "scenario": scenario,
                   "invocation": f"offline-{self.state['revision']}"}
        result = subprocess.run(
            ["node", str(SCRIPTS / "development_workflow_self_check.js"), "--persisted-controller"],
            input=json.dumps(fixture), cwd=self.root, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout)
        self.state = observed["result"]
        self.assertEqual(self.state, self.cli("status", self.store))
        return observed["roles"]

    def retire_fixture(self):
        self.mutate("retire", "--reason", "Reconciled the local fixture's partial effects",
                    "--shutdown-evidence", "The synchronous fixture process and workers exited")
        self.mutate("resume", "--reason", "Continue within the retained allowance")

    def test_workflow_scope_denial_recovers_in_the_same_persisted_run(self):
        self.plan["limits"]["attempts"] = 3
        self.init()
        self.preflight()
        root = self.prepare()
        for attempt in (1, 2):
            self.workflow("scope")
            self.assertEqual(self.state["outcome"], "blocked")
            self.assertIn("outside the approved scope", self.state["reason"])
            self.assertEqual(self.state["assignment"]["attempt"], attempt)
            self.assertEqual(self.workflow("complete"), ["development-control"])
            self.mutate("resume", "--reason", "Worker still outstanding", ok=False)
            if attempt == 2:
                (root / "unapproved.txt").unlink()
            self.retire_fixture()
        self.workflow("complete")
        saved = json.loads((self.store / "RUN.json").read_bytes())
        implementations = [item for item in saved["history"] if item["role"] == "implement"]
        self.assertEqual([item["outcome"] for item in implementations], ["retired", "retired", "complete"])
        self.assertEqual(self.state["consumed_assignments"], 6)
        self.assertEqual(self.state["prs"]["first"]["position"], 2)
        self.assertEqual((root / "app.txt").read_text(), "after\n")

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
            self.assertEqual(self.workflow("complete"), ["development-control"])
            self.assertEqual(self.state["consumed_assignments"], consumed)
            self.mutate("resume", "--reason", "Worker shutdown not reconciled", ok=False)
            self.retire_fixture()
        self.workflow("complete")
        self.assertEqual(self.state["prs"]["first"]["position"], 2)
        self.assertEqual(self.state["consumed_assignments"], 6)

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
            histories = list((root / ".review-loop").glob("*/REVIEW_LEDGER.json"))
            self.assertEqual(len(histories), 1)
            ledger = histories[0]
            retained = ledger.read_bytes()
            consumed = self.state["consumed_assignments"]
            self.assertEqual(self.workflow("review-complete"), ["development-control"])
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

    def test_workflow_review_path_denial_recovers_with_persisted_history(self):
        self.assert_workflow_review_recovers("review-path", "outside the assigned private directory")

    def test_workflow_review_packet_denial_recovers_with_persisted_history(self):
        self.assert_workflow_review_recovers("review-missing-packet", "frozen single-purpose packet")

    def test_workflow_review_budget_denial_recovers_without_refunding_limits(self):
        self.assert_workflow_review_recovers("review-budget", "allowance cannot cover")

    def test_workflow_review_native_failure_requires_shutdown_before_retry(self):
        self.assert_workflow_review_recovers("review-throw", "Fixture review native call failed")

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
        self.init()
        self.preflight()
        root = self.prepare()
        self.next()
        self.finish()
        self.next()
        data = self.review(root, record=False)
        path = Path(data["ledger"])
        if damage == "missing-ledger":
            path.unlink()
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

    def test_abandoned_review_can_only_continue_as_a_counted_retry(self):
        self.abandoned_review_retry("missing-ledger")

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
    worker.assertEqual(fixture["action"], "finish")
    data = json.loads(saved.read_bytes())
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
