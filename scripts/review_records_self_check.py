#!/usr/bin/env python3
"""Exercise shared storage with explicit offline provenance, never native model launches."""

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import review_records as records
import review_options
import review_assignments

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
import pytest
from self_check_support import run_main


class ReviewRecordTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        self.root = self.home / "project"
        self.root.mkdir()
        self.env = {**os.environ, "HOME": str(self.home), "XDG_STATE_HOME": str(self.home / "state"),
                    "CODEX_HOME": str(self.home / ".codex"), "COPILOT_HOME": str(self.home / ".copilot"),
                    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                    "PYTHONDONTWRITEBYTECODE": "1"}
        for key in tuple(self.env):
            if key.startswith("GIT_") and key not in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM"):
                del self.env[key]
        environment = patch.dict(os.environ, self.env, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.git(self.root, "init", "-q")
        self.git(self.root, "remote", "add", "origin", "https://example.invalid/team/project.git")

    def git(self, root, *args):
        return subprocess.run(["git", "-C", str(root), *args], env=self.env, check=True,
                              capture_output=True).stdout

    def initialize(self, harness="copilot", root=None):
        return records.initialize(root or self.root, "pr:84", {"harness": {
            "name": harness, "version": "fixture-version", "source": "native-context",
            "evidence": "Synthetic offline input, not evidence of a native host run",
        }})

    def report(self, run, role="reviewer", assignment="security-initial", document=None):
        path = Path(run["scratch_directory"]) / f"{assignment}.json"
        path.write_text(json.dumps(document or {"candidates": [{"id": "candidate", "action": "No fix"}]}))
        return {"role": role, "assignment": assignment, "worker": f"worker-{assignment}",
                "result_file": str(path)}

    def test_two_harnesses_and_remote_transports_share_target_layout(self):
        before = self.git(self.root, "status", "--porcelain")
        first = self.initialize("claude")
        clone = self.home / "second-checkout"
        clone.mkdir()
        self.git(clone, "init", "-q")
        self.git(clone, "remote", "add", "origin", "git@example.invalid:team/project.git")
        second = self.initialize("copilot", clone)
        self.assertEqual(Path(first["directory"]).parent, Path(second["directory"]).parent)
        self.assertNotEqual(first["run_id"], second["run_id"])
        self.assertEqual(first["record"]["harness"]["name"], "claude")
        self.assertEqual(second["record"]["harness"]["name"], "copilot")
        features = {row["feature"]: True for row in review_assignments.catalog()["categories"]}
        for run in (first, second):
            request = {
                "objective": "Offline cross-harness record fixture", "kind": "full", "target": "pr:84",
                "base": "fixture-base", "snapshot": "fixture-snapshot", "root": run["record"]["root"],
                "files": ["source.py"], "language_inventory": {
                    "source.py": {"languages": ["python"], "evidence": "Offline Python fixture"},
                },
                "constraints": ["No native model launches"], "scratch_directory": run["scratch_directory"],
                "run_id": run["run_id"],
                "review_options": {"configuration": {"skill_enabled": True, "review_features": features}},
            }
            phases = [review_assignments.prepare(request) for _ in range(2)]
            for phase in phases:
                packet = phase["packets"]["correctness"]
                self.assertEqual(packet["run_id"], run["run_id"])
                Path(packet["result_file"]).write_text(json.dumps({
                    "run_id": packet["run_id"], "candidates": [{"id": "C1"}],
                }))
                entry = {
                    "role": "reviewer", "assignment": packet["assignment"], "phase": phase["phase_id"],
                    "worker": phase["phase_id"], "harness": run["record"]["harness"],
                }
                registered = records.record(run["directory"], entry)
                self.assertIsNone(registered["report"])
                saved = records.record(run["directory"], {**entry, "result_file": packet["result_file"]})
                index = json.loads((Path(run["directory"]) / saved["report"]["record"]).read_text())
                self.assertEqual(index["entries"][0]["run_id"], run["run_id"])
                self.assertEqual(index["entries"][0]["phase"], phase["phase_id"])
                self.assertEqual(index["entries"][0]["observation"]["harness"], run["record"]["harness"])
                with self.assertRaisesRegex(ValueError, "Worker changed"):
                    records.record(run["directory"], {**entry, "worker": "different-worker"})
            _, value = records.load(run["directory"])
            self.assertEqual(len(value["roles"]), 3)
            self.assertEqual(len(value["reports"]), 2)
        runs = records.find_runs(self.root, "pr:84")
        self.assertEqual({item["run_id"] for item in runs}, {first["run_id"], second["run_id"]})
        self.assertEqual(records.find_runs(self.root, "pr:85"), [])
        self.assertEqual(self.git(self.root, "status", "--porcelain"), before)
        self.assertFalse(Path(first["directory"]).is_relative_to(self.root))

    def test_reports_keep_rejected_candidates_and_observed_role_provenance(self):
        run = self.initialize()
        document = {
            "selection": {"requested": "requested-model", "selected": "selected-model"},
            "candidates": [{"id": "C1", "action": "Act"}, {"id": "C2", "action": "No fix"}],
            "assessments": [{"candidate": "C1", "valid": True}],
            "rejected_candidates": [{"id": "C3", "reason": "Refuted"}],
        }
        for role in records.ROLES:
            with self.subTest(role=role):
                entry = self.report(run, role, role, document)
                if role == "reviewer":
                    entry["observation"] = {
                        "model": "observed-model", "effort": "observed-effort",
                        "source": "native-context", "evidence": "Explicit offline role observation fixture",
                    }
                original = Path(entry["result_file"]).read_bytes()
                saved = records.record(run["directory"], entry)
                index = json.loads((Path(run["directory"]) / saved["report"]["record"]).read_text())
                self.assertEqual((Path(run["directory"]) / index["original"]).read_bytes(), original)
                self.assertEqual([item["record"] for item in index["entries"]],
                                 document["candidates"] + document["assessments"] + document["rejected_candidates"])
                self.assertTrue(all(item["run_id"] == run["run_id"] for item in index["entries"]))
                self.assertTrue(all(item["role"] == role for item in index["entries"]))
                expected = "observed-model" if role == "reviewer" else "unknown"
                self.assertEqual(index["observation"]["model"], expected)
        folder, value = records.load(run["directory"])
        self.assertEqual({role["role"] for role in value["roles"].values()}, set(records.ROLES))
        self.assertEqual(len(value["reports"]), len(records.ROLES))
        for path in (folder, *folder.rglob("*")):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700 if path.is_dir() else 0o600, path)

    def test_unknown_observations_do_not_erase_observed_identities_or_merge_workers(self):
        run = self.initialize()
        entry = self.report(run)
        observed = {"model": "native-model", "source": "native-transcript",
                    "evidence": "Synthetic transcript fixture"}
        records.record(run["directory"], {**entry, "observation": observed})
        resumed = {"name": "codex", "source": "native-context", "evidence": "Offline resume fixture"}
        records.record(run["directory"], {**entry, "harness": resumed})
        _, value = records.load(run["directory"])
        role = value["roles"]["reviewer:security-initial"]
        self.assertEqual([item["model"] for item in role["observations"]], ["native-model", "unknown"])
        self.assertEqual([item["harness"]["name"] for item in role["observations"]], ["unknown", "codex"])
        self.assertEqual(len(value["reports"]), 2)
        before = (Path(run["directory"]) / "RUN.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "Worker changed"):
            records.record(run["directory"], {**entry, "worker": "different-worker"})
        self.assertEqual((Path(run["directory"]) / "RUN.json").read_bytes(), before)
        with self.assertRaisesRegex(ValueError, "native evidence"):
            records.record(run["directory"], {**entry, "observation": {"model": "selected-only"}})
        self.assertEqual((Path(run["directory"]) / "RUN.json").read_bytes(), before)

    def test_invalid_run_schema_is_reported_without_hiding_other_runs(self):
        good = self.initialize()
        broken = self.initialize()
        path = Path(broken["directory"]) / "RUN.json"
        value = json.loads(path.read_text())
        value["schema"] = 99
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "schema"):
            records.load(broken["directory"])
        runs = {item["run_id"]: item for item in records.find_runs(self.root, "pr:84")}
        self.assertNotIn("error", runs[good["run_id"]])
        self.assertIn("schema", runs[broken["run_id"]]["error"])

    def test_malformed_report_is_retained_and_repair_does_not_replace_history(self):
        run = self.initialize()
        entry = self.report(run)
        path = Path(entry["result_file"])
        original = b'{"candidates": ['
        path.write_bytes(original)
        broken = records.record(run["directory"], entry)["report"]
        self.assertIn("Original retained", broken["error"])
        path.write_text('{"candidates": []}')
        repaired = records.record(run["directory"], entry)["report"]
        records.record(run["directory"], entry)
        _, value = records.load(run["directory"])
        self.assertEqual(len(value["reports"]), 2)
        self.assertIsNone(repaired["error"])
        index = json.loads((Path(run["directory"]) / broken["record"]).read_text())
        self.assertEqual((Path(run["directory"]) / index["original"]).read_bytes(), original)

    def test_ambiguous_json_is_retained_without_silently_dropping_findings(self):
        run = self.initialize()
        entry = self.report(run)
        original = b'{"candidates": [{"id": "lost"}], "candidates": []}'
        Path(entry["result_file"]).write_bytes(original)
        saved = records.record(run["directory"], entry)["report"]
        self.assertIn("duplicate key", saved["error"])
        index = json.loads((Path(run["directory"]) / saved["record"]).read_text())
        self.assertEqual(index["entries"], [])
        self.assertEqual((Path(run["directory"]) / index["original"]).read_bytes(), original)
        Path(entry["result_file"]).write_text('{"candidates": [{"id": "recovered"}]}')
        repaired = records.record(run["directory"], entry)["report"]
        self.assertIsNone(repaired["error"])
        self.assertEqual(len(records.load(run["directory"])[1]["reports"]), 2)

    def test_index_budget_stops_consuming_entries_before_expanding_the_whole_report(self):
        run = self.initialize()
        entry = self.report(run)
        visited = []

        def expanded(document, provenance, pointer=""):
            for number in range(1000):
                visited.append(number)
                yield {**provenance, "kind": "candidates", "pointer": f"/candidates/{number}",
                       "record": {"detail": "x" * 2000}}

        with patch.object(records, "MAX_BYTES", 8192), patch.object(records, "entries", expanded):
            saved = records.record(run["directory"], entry)["report"]
        self.assertIn("index exceeds the size limit", saved["error"])
        self.assertLess(len(visited), 10)
        self.assertEqual(len(records.load(run["directory"])[1]["reports"]), 1)

    def test_run_manifest_growth_is_rejected_without_losing_the_readable_history(self):
        run = self.initialize()
        path = Path(run["directory"]) / "RUN.json"
        with patch.object(records, "MAX_BYTES", 6500):
            for number in range(2):
                records.record(run["directory"], {
                    "role": "reviewer", "assignment": f"role-{number}",
                    "observation": {"evidence": "x" * 1800},
                })
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "Run record exceeds the size limit"):
                records.record(run["directory"], {
                    "role": "reviewer", "assignment": "role-2",
                    "observation": {"evidence": "x" * 1800},
                })
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(len(records.load(run["directory"])[1]["roles"]), 3)
            records.record(run["directory"], {"role": "reviewer", "assignment": "role-2"})
            self.assertEqual(len(records.load(run["directory"])[1]["roles"]), 4)

    def test_oversized_initial_observation_creates_no_unreadable_run(self):
        with patch.object(records, "MAX_BYTES", 8192):
            with self.assertRaisesRegex(ValueError, "Run record exceeds the size limit"):
                records.initialize(self.root, "pr:84", {"lead": {"evidence": "x" * 8192}})
            self.assertEqual(records.find_runs(self.root, "pr:84"), [])
        self.assertTrue(self.initialize()["enabled"])

    def test_git_instead_of_uses_the_effective_remote_and_keeps_legacy_records_discoverable(self):
        first = self.initialize()
        self.git(self.root, "remote", "set-url", "origin", "work:project.git")
        legacy = self.initialize()
        self.git(self.root, "config", "url.https://example.invalid/team/.insteadOf", "work:")
        current = self.initialize()
        self.assertEqual(Path(first["directory"]).parent, Path(current["directory"]).parent)
        runs = {row["run_id"]: row for row in records.find_runs(self.root, "pr:84")}
        self.assertEqual(set(runs), {first["run_id"], legacy["run_id"], current["run_id"]})
        self.assertTrue(runs[legacy["run_id"]]["legacy_repository_key"])
        self.assertNotIn("legacy_repository_key", runs[current["run_id"]])

    def test_near_limit_report_keeps_a_readable_index_and_can_be_recorded_again(self):
        run = self.initialize()
        entry = self.report(run)
        document = {"candidates": [{"detail": ""}]}
        overhead = len(json.dumps(document, separators=(",", ":")).encode())
        document["candidates"][0]["detail"] = "x" * (records.MAX_BYTES - overhead)
        original = json.dumps(document, separators=(",", ":")).encode()
        self.assertEqual(len(original), records.MAX_BYTES)
        Path(entry["result_file"]).write_bytes(original)

        saved = records.record(run["directory"], entry)["report"]
        repeated = records.record(run["directory"], entry)["report"]

        self.assertEqual(saved, repeated)
        folder, value = records.load(run["directory"])
        self.assertEqual(value["reports"], [saved])
        index = json.loads(records.private_file(folder / saved["record"]))
        self.assertEqual(index["entries"], [])
        self.assertIn("index exceeds the size limit", index["error"])
        self.assertEqual(saved["error"], index["error"])
        self.assertEqual(records.private_file(folder / index["original"]), original)

    def test_oversized_index_metadata_preserves_original_and_allows_recovery(self):
        run = self.initialize()
        entry = self.report(run)
        folder = Path(run["directory"])
        before = (folder / "RUN.json").read_bytes()
        original = Path(entry["result_file"]).read_bytes()
        with patch.object(records, "MAX_BYTES", 8192):
            oversized = {**entry, "observation": {"evidence": "x" * records.MAX_BYTES}}
            with self.assertRaisesRegex(ValueError, "metadata exceeds the size limit"):
                records.record(run["directory"], oversized)

        self.assertEqual((folder / "RUN.json").read_bytes(), before)
        self.assertEqual(list((folder / "records").iterdir()), [])
        originals = list((folder / "originals").iterdir())
        self.assertEqual(len(originals), 1)
        self.assertEqual(originals[0].read_bytes(), original)
        saved = records.record(run["directory"], entry)["report"]
        self.assertIsNone(saved["error"])

    def test_storage_in_any_repository_is_rejected_and_external_recovery_works(self):
        other = self.home / "other-repository"
        other.mkdir()
        self.git(other, "init", "-q")
        for root in (self.root, other):
            with self.subTest(root=root), patch.dict(os.environ, {"XDG_STATE_HOME": str(root / "state")}):
                with self.assertRaisesRegex(ValueError, "outside"):
                    self.initialize()
                self.assertFalse((root / "state").exists())
        run = self.initialize()
        self.assertTrue(Path(run["directory"]).is_dir())
        with patch.dict(os.environ, {"XDG_STATE_HOME": str(other / "state")}):
            with self.assertRaisesRegex(ValueError, "outside"):
                self.initialize()

    def test_report_escape_and_symlink_are_rejected_without_losing_allowed_work(self):
        run = self.initialize()
        entry = self.report(run)
        outside = self.home / "outside.json"
        outside.write_text('{"candidates": []}')
        alias = Path(run["scratch_directory"]) / "alias.json"
        alias.symlink_to(outside)
        before = (Path(run["directory"]) / "RUN.json").read_bytes()
        for path in (outside, alias):
            with self.subTest(path=path), self.assertRaises(ValueError):
                records.record(run["directory"], {**entry, "result_file": str(path)})
            self.assertEqual((Path(run["directory"]) / "RUN.json").read_bytes(), before)
        records.record(run["directory"], entry)
        with self.assertRaises(ValueError):
            records.record(run["directory"], {**entry, "result_file": str(alias)})
        self.assertEqual(outside.read_text(), '{"candidates": []}')

    def test_derived_storage_parent_is_checked_before_any_writes(self):
        base = records.private_directory(records.storage.state_directory() / "reviews" / "records")
        repository_path = base / records.repository(self.root)["key"]
        destination = self.root / "redirected"
        destination.mkdir(mode=0o755)
        repository_path.symlink_to(destination, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.initialize()
        self.assertEqual(list(destination.iterdir()), [])
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o755)
        repository_path.unlink()
        repository_path.mkdir()
        self.git(repository_path, "init", "-q")
        with self.assertRaisesRegex(ValueError, "outside"):
            self.initialize()
        self.assertEqual([item.name for item in repository_path.iterdir()], [".git"])
        repository_path.rename(self.home / "detached-state-repository")
        self.assertTrue(self.initialize()["enabled"])

    def test_symlinked_reports_directory_cannot_read_chmod_or_import_into_a_repository(self):
        run = self.initialize()
        reports = Path(run["scratch_directory"])
        reports.rmdir()
        destination = self.root / "redirected-reports"
        destination.mkdir()
        source = destination / "report.json"
        source.write_text('{"candidates": []}')
        source.chmod(0o644)
        reports.symlink_to(destination, target_is_directory=True)
        external = self.home / "external.json"
        external.write_text(source.read_text())
        before = (Path(run["directory"]) / "RUN.json").read_bytes()
        for path, imported in ((reports / source.name, False), (external, True)):
            with self.subTest(imported=imported), self.assertRaises(ValueError):
                records.record(run["directory"], {
                    "role": "reviewer", "assignment": "symlink",
                    "result_file": str(path), "external_report": imported,
                })
            self.assertEqual((Path(run["directory"]) / "RUN.json").read_bytes(), before)
        self.assertEqual(stat.S_IMODE(source.stat().st_mode), 0o644)
        self.assertEqual(list(destination.iterdir()), [source])
        reports.unlink()
        reports.mkdir(mode=0o700)
        self.assertIsNone(records.record(run["directory"], self.report(run))["report"]["error"])

    def test_opt_out_stops_new_persistence_without_disabling_reviews(self):
        run = self.initialize()
        entry = self.report(run)
        before = (Path(run["directory"]) / "RUN.json").read_bytes()
        path = self.root / ".claude/ioncache-ai-tools.local.json"
        path.parent.mkdir()
        path.write_text('{"features": {"review-records": false}}')
        disabled = self.initialize()
        self.assertFalse(disabled["enabled"])
        self.assertIsNone(disabled["directory"])
        nested = self.root / "nested"
        nested.mkdir()
        with patch.object(Path, "cwd", return_value=nested):
            nested_config = review_options.read_configuration("review-code")
        self.assertEqual(self.initialize(root=nested)["enabled"], nested_config["records_enabled"])
        self.assertFalse(records.record(run["directory"], entry)["enabled"])
        self.assertEqual((Path(run["directory"]) / "RUN.json").read_bytes(), before)
        self.assertEqual(len(records.find_runs(self.root, "pr:84")), 2)
        with patch.object(Path, "cwd", return_value=self.root):
            config = review_options.read_configuration("review-code")
        self.assertTrue(config["skill_enabled"])
        self.assertFalse(config["records_enabled"])
        self.assertNotIn("review-records", config["review_features"])
        path.unlink()
        self.assertEqual(self.initialize(root=nested)["record"]["root"], str(self.root))
        self.assertTrue(records.record(run["directory"], entry)["enabled"])

    def test_subdirectory_settings_remain_the_project_identity_after_repository_normalization(self):
        nested = self.root / "package"
        nested.mkdir()
        run = self.initialize(root=nested)
        entry = self.report(run)
        before = (Path(run["directory"]) / "RUN.json").read_bytes()
        setting = nested / ".claude/ioncache-ai-tools.local.json"
        setting.parent.mkdir()
        setting.write_text('{"features": {"review-records": false}}')
        with patch.object(Path, "cwd", return_value=nested):
            self.assertFalse(review_options.read_configuration("review-code")["records_enabled"])
        self.assertFalse(self.initialize(root=nested)["enabled"])
        self.assertFalse(records.record(run["directory"], entry)["enabled"])
        self.assertEqual((Path(run["directory"]) / "RUN.json").read_bytes(), before)
        setting.unlink()
        self.assertIsNone(records.record(run["directory"], entry)["report"]["error"])
        self.assertEqual(run["record"]["root"], str(self.root))

    def test_legacy_runs_without_a_settings_project_keep_root_configuration(self):
        run = self.initialize()
        path = Path(run["directory"]) / "RUN.json"
        legacy = json.loads(path.read_text())
        del legacy["project"]
        path.write_bytes(records.storage.encode(legacy))
        entry = self.report(run)
        self.assertIsNone(records.record(run["directory"], entry)["report"]["error"])
        setting = self.root / ".claude/ioncache-ai-tools.local.json"
        setting.parent.mkdir()
        setting.write_text('{"features": {"review-records": false}}')
        self.assertFalse(records.record(run["directory"], entry)["enabled"])

    def test_nested_index_pointers_resolve_to_complete_original_records(self):
        run = self.initialize()
        document = {kind: [{"id": kind}] for kind in sorted(records.COLLECTIONS)}
        document["nested/~"] = [{"candidates": [{"id": "nested"}]}]
        document["not-a-collection"] = {"duplicates": "not a list"}
        entry = self.report(run, document=document)
        saved = records.record(run["directory"], entry)["report"]
        index = json.loads((Path(run["directory"]) / saved["record"]).read_text())
        self.assertIsNone(index["error"])
        expected = {f"/{kind}/0" for kind in records.COLLECTIONS} | {"/nested~1~0/0/candidates/0"}
        self.assertEqual({item["pointer"] for item in index["entries"]}, expected)
        for item in index["entries"]:
            value = document
            for segment in item["pointer"].split("/")[1:]:
                key = segment.replace("~1", "/").replace("~0", "~")
                value = value[int(key)] if isinstance(value, list) else value[key]
            self.assertEqual(value, item["record"])

    def test_cli_preserves_observed_provenance_and_phase_scoped_registration(self):
        evidence = "Synthetic offline CLI fixture"
        flags = ["--harness", "copilot", "--harness-version", "fixture-version",
                 "--harness-source", "native-context", "--harness-evidence", evidence,
                 "--model", "fixture-model", "--effort", "fixture-effort",
                 "--source", "native-context", "--evidence", evidence]
        started = run_main(records, ["init", "--target", "pr:84", *flags], cwd=self.root, env=self.env)
        self.assertEqual(started.returncode, 0, started.stderr)
        run = json.loads(started.stdout)
        lead = run["record"]["roles"]["lead:lead"]["observations"][0]
        self.assertEqual((lead["model"], lead["effort"]), ("fixture-model", "fixture-effort"))
        self.assertEqual(run["record"]["harness"]["version"], "fixture-version")
        phase = "a" * 32
        registered = run_main(records, ["record", run["directory"], "--role", "reviewer",
                             "--assignment", "correctness-initial", "--phase", phase, *flags],
                             cwd=self.root, env=self.env)
        self.assertEqual(registered.returncode, 0, registered.stderr)
        saved = json.loads(registered.stdout)
        self.assertIsNone(saved["report"])
        self.assertEqual(saved["role"]["phase"], phase)
        self.assertEqual(saved["role"]["observations"], [lead])
        listed = run_main(records, ["list", "--target", "pr:84"], cwd=self.root, env=self.env)
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertEqual([row["run_id"] for row in json.loads(listed.stdout)], [run["run_id"]])

    def test_pinned_external_reports_are_copied_without_mutating_their_originals(self):
        run = self.initialize()
        native = self.home / "development-run"
        native.mkdir(mode=0o700)
        source = native / "reviewer.json"
        source.write_text('{"run_id": null, "candidates": [{"id": "C1"}]}')
        before = source.stat()
        entry = {"role": "reviewer", "assignment": "native-job", "result_file": str(source),
                 "external_report": True}
        result = records.record(run["directory"], entry)
        after = source.stat()
        self.assertEqual((after.st_mtime_ns, after.st_mode), (before.st_mtime_ns, before.st_mode))
        index = json.loads((Path(run["directory"]) / result["report"]["record"]).read_text())
        self.assertEqual(index["source"], str(source))
        self.assertIsNone(index["error"])
        self.assertEqual(index["entries"][0]["record"]["id"], "C1")
        self.assertEqual((Path(run["directory"]) / index["original"]).read_bytes(), source.read_bytes())
        copies = list(Path(run["scratch_directory"]).glob("imported-*.json"))
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0].read_bytes(), source.read_bytes())
        forbidden = self.root / "report.json"
        forbidden.write_text(source.read_text())
        with self.assertRaisesRegex(ValueError, "outside every repository"):
            records.record(run["directory"], {**entry, "result_file": str(forbidden)})

    def test_nonregular_lock_fails_without_waiting_and_can_be_repaired(self):
        run = self.initialize()
        entry = self.report(run)
        lock = Path(run["directory"]) / ".lock"
        os.mkfifo(lock)
        with self.assertRaises(OSError):
            records.record(run["directory"], entry)
        lock.unlink()
        self.assertIsNone(records.record(run["directory"], entry)["report"]["error"])

    @pytest.mark.process
    def test_cli_lock_failure_recovers_without_overwriting_another_writer(self):
        started = run_main(records, ["init", "--target", "pr:84"], cwd=self.root, env=self.env, process=True)
        self.assertEqual(started.returncode, 0, started.stderr)
        run = json.loads(started.stdout)
        entry = self.report(run)
        args = ["record", run["directory"], "--role", "reviewer", "--assignment", "security-initial",
                "--result-file", entry["result_file"]]
        before = (Path(run["directory"]) / "RUN.json").read_bytes()
        with records.locked(Path(run["directory"])):
            rejected = run_main(records, args, cwd=self.root, env=self.env, process=True)
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("busy writer", rejected.stderr)
            self.assertEqual((Path(run["directory"]) / "RUN.json").read_bytes(), before)
        accepted = run_main(records, args, cwd=self.root, env=self.env, process=True)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        status = run_main(records, ["status", run["directory"]], cwd=self.root, env=self.env)
        self.assertEqual(len(json.loads(status.stdout)["reports"]), 1)


if __name__ == "__main__":
    unittest.main()
