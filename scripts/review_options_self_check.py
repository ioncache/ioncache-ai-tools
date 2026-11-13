#!/usr/bin/env python3
"""Exercise review option defaults, recovery, and read-only configuration in isolated homes."""

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import review_options


HELPER = Path(__file__).with_name("review_options.py")


class ReviewOptionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.root = self.home / "project"
        self.root.mkdir()
        self.env = {**os.environ, "HOME": str(self.home),
                    "COPILOT_HOME": str(self.home / ".copilot"),
                    "CODEX_HOME": str(self.home / ".codex"),
                    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                    "PYTHONDONTWRITEBYTECODE": "1"}
        for key in list(self.env):
            if key.startswith(("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")):
                self.env.pop(key)

    def run_options(self, *args, cwd=None):
        return subprocess.run([sys.executable, "-B", str(HELPER), *args],
                              cwd=cwd or self.root, env=self.env,
                              capture_output=True, text=True)

    def write_settings(self, relative, features):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"features": features}))
        return path

    def write_context(self, context):
        path = self.home / "review-context.json"
        path.write_text(json.dumps(context))
        return str(path)

    def test_defaults_need_no_prompt_and_write_nothing(self):
        before = sorted(self.home.rglob("*"))
        result = self.run_options("review-code")
        self.assertEqual(result.returncode, 0, result.stderr)
        options = json.loads(result.stdout)
        self.assertEqual(options["target"], [])
        self.assertEqual(options["effective_model_selection"], "auto")
        self.assertEqual(options["roles"]["lead"],
                         {"model": None, "effort": None, "fallback": "configured"})
        self.assertEqual(sorted(self.home.rglob("*")), before)

    def test_explicit_roles_preserve_other_defaults_and_literal_values(self):
        value = "provider/model;$(not-a-command)"
        options = review_options.parse_options("review-code", [
            "src/a file.py", "--lead-model", value, "src/b.py",
            "--reviewer-effort", "host-level", "--model-selection", "configured",
        ])
        self.assertEqual(options["target"], ["src/a file.py", "src/b.py"])
        self.assertEqual(options["roles"]["lead"],
                         {"model": value, "effort": None, "fallback": "fail"})
        self.assertEqual(options["roles"]["reviewer"]["fallback"], "fail")
        self.assertEqual(options["roles"]["validator"]["fallback"], "configured")
        self.assertEqual(options["specified"], ["lead_model", "model_selection", "reviewer_effort"])

    def test_explicit_fallback_and_strategy(self):
        options = review_options.parse_options("review-code", [
            "--lead-model=chosen", "--lead-effort=high", "--validator-model=other",
            "--fallback=configured", "--strategy=specialists",
        ])
        self.assertEqual(options["roles"]["lead"]["fallback"], "configured")
        self.assertEqual(options["roles"]["validator"]["model"], "other")
        self.assertEqual(options["strategy"], "specialists")
        self.assertIn("fallback", options["specified"])

    def test_strategy_resolution_is_deterministic_without_losing_requested_values(self):
        for skill in review_options.SKILLS:
            for requested in (None, "auto", "specialists", "sweep-first"):
                with self.subTest(skill=skill, strategy=requested):
                    args = [] if requested is None else ["--strategy", requested]
                    result = self.run_options(skill, *args)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    options = json.loads(result.stdout)
                    self.assertEqual(options["strategy"], requested or "auto")
                    expected = "sweep-first" if requested == "sweep-first" else "specialists"
                    self.assertEqual(options["effective_strategy"], expected)
                    self.assertEqual(options["option_sources"]["strategy"],
                                     "default" if requested is None else "invocation")

    def test_resume_recomputes_strategy_after_context_and_invocation_overrides(self):
        saved = review_options.parse_options("review-validate-fix-loop", [
            "--strategy", "sweep-first", "--lead-model", "chosen",
        ])
        saved["effective_strategy"] = "obsolete-allocation"
        context = self.write_context({"saved": saved, "choices": {
            "strategy": {"value": "auto", "source": "User selected the default strategy"},
        }})
        args = ("--context", context, "review-validate-fix-loop", "--resume", "saved-ledger")
        result = self.run_options(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        options = json.loads(result.stdout)
        self.assertEqual((options["strategy"], options["effective_strategy"]), ("auto", "specialists"))
        self.assertEqual(options["option_sources"]["strategy"], "User selected the default strategy")
        self.assertEqual(options["roles"]["lead"]["model"], "chosen")
        result = self.run_options(*args, "--strategy", "sweep-first")
        self.assertEqual(result.returncode, 0, result.stderr)
        options = json.loads(result.stdout)
        self.assertEqual((options["strategy"], options["effective_strategy"]), ("sweep-first", "sweep-first"))
        self.assertEqual(options["option_sources"]["strategy"], "invocation")
        saved.pop("effective_strategy")
        context = self.write_context({"saved": saved})
        options = json.loads(self.run_options(
            "--context", context, "review-validate-fix-loop", "--resume", "old-ledger",
        ).stdout)
        self.assertEqual(options["effective_strategy"], "sweep-first")

    def test_invalid_arguments_do_not_start_work_and_help_remains_reachable(self):
        cases = [
            ["--non-interactive"], ["--main-model", "chosen"], ["--lead-m", "chosen"],
            ["--lead-model", ""], ["--lead-model", " chosen"], ["--lead-model", "a\nb"],
            ["--lead-model", "one", "--lead-model", "two"],
            ["--strategy", "auto", "--strategy=specialists"], ["--fallback", "silent"],
            ["--model-selection", "guess"], ["--max-loops", "3"], ["--lead-effort"],
        ]
        for args in cases:
            with self.subTest(args=args):
                result = self.run_options("review-code", *args)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
        help_result = self.run_options("review-code", "--help")
        self.assertEqual(help_result.returncode, 0)
        self.assertIn("--validator-effort", help_result.stdout)
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(self.run_options("review-code", "branch").returncode, 0)
        self.assertEqual(self.run_options("review-code", "--main-model=x").returncode, 2)

    def test_loop_limits_and_resume_identify_only_explicit_overrides(self):
        options = review_options.parse_options("review-validate-fix-loop", [
            "branch", "--max-loops", "4", "--max-fix-cycles", "2",
            "--reviewer-model", "chosen",
        ])
        self.assertEqual((options["max_loops"], options["max_fix_cycles"]), (4, 2))
        resumed = review_options.parse_options("review-validate-fix-loop", [
            "--resume", ".review-loop/run/REVIEW_LEDGER.json", "--lead-effort", "high",
        ])
        self.assertEqual(resumed["specified"], ["lead_effort", "resume"])
        for args in (["--resume", "saved", "branch"], ["--resume", "saved", "--max-loops", "3"],
                     ["--max-loops", "0"], ["--max-fix-cycles", "-1"], ["--max-loops", "many"]):
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    review_options.parse_options("review-validate-fix-loop", args)
                self.assertEqual(error.exception.code, 2)

    def test_auto_opt_out_is_independent_at_the_host_project_cwd(self):
        subprocess.run(["git", "init", "-q", str(self.root)], env=self.env, check=True)
        nested = self.root / "src"
        nested.mkdir()
        path = self.write_settings("project/src/.codex/ioncache-ai-tools.local.json",
                                   {"review-auto-model-selection": False})
        original = path.read_bytes()
        result = self.run_options("review-code", "--lead-model", "chosen", cwd=nested)
        self.assertEqual(result.returncode, 0, result.stderr)
        options = json.loads(result.stdout)
        self.assertEqual(options["effective_model_selection"], "configured")
        self.assertEqual(options["effective_strategy"], "specialists")
        self.assertTrue(options["configuration"]["skill_enabled"])
        self.assertEqual(options["roles"]["lead"]["model"], "chosen")
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(path.parent.glob("*.lock")), [])
        self.assertEqual(options["configuration"]["project"], str(nested.resolve()))

    def test_host_union_and_project_override_match_plugin_settings(self):
        self.write_settings(".copilot/ioncache-ai-tools.local.json",
                            {"review-auto-model-selection": False})
        self.write_settings("project/.github/copilot/ioncache-ai-tools.local.json",
                            {"review-auto-model-selection": True})
        self.assertEqual(json.loads(self.run_options("review-code").stdout)
                         ["effective_model_selection"], "auto")
        self.write_settings(".claude/ioncache-ai-tools.local.json",
                            {"review-auto-model-selection": False, "skill:review-code": False})
        options = json.loads(self.run_options("review-code").stdout)
        self.assertEqual(options["effective_model_selection"], "configured")
        self.assertFalse(options["configuration"]["skill_enabled"])

    def test_malformed_configuration_is_not_overwritten_and_help_still_works(self):
        path = self.write_settings(".codex/ioncache-ai-tools.local.json", {})
        path.write_text("{bad")
        result = self.run_options("review-code")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("configuration unavailable", result.stderr)
        self.assertEqual(path.read_text(), "{bad")
        self.assertEqual(self.run_options("review-code", "--help").returncode, 0)
        path.write_text('{"features":{}}')
        self.assertEqual(self.run_options("review-code").returncode, 0)

    def test_package_project_overrides_match_hook_resolution(self):
        subprocess.run(["git", "init", "-q", str(self.root)], env=self.env, check=True)
        package = self.root / "packages" / "api"
        self.write_settings(".copilot/ioncache-ai-tools.local.json", {
            "review-auto-model-selection": False, "skill:review-code": False,
        })
        self.write_settings("project/packages/api/.github/copilot/ioncache-ai-tools.local.json", {
            "review-auto-model-selection": True, "skill:review-code": True,
        })
        options = json.loads(self.run_options("review-code", cwd=package).stdout)
        with mock.patch.dict(os.environ, self.env):
            hook = review_options.plugin_config.feature_settings({
                "cwd": str(package), "_ioncache_harness": "copilot",
            })
        self.assertNotIn("review-auto-model-selection", hook.disabled)
        self.assertNotIn("skill:review-code", hook.disabled)
        self.assertTrue(options["configuration"]["skill_enabled"])
        self.assertEqual(options["effective_model_selection"], "auto")

    def test_conversational_choices_use_explicit_fallback_and_flags_take_precedence(self):
        context = self.write_context({"choices": {
            "reviewer_model": {"value": "chosen", "source": "User explicitly selected chosen"},
            "validator_effort": {"value": "high", "source": "User explicitly selected high effort"},
        }})
        result = self.run_options("--context", context, "review-code")
        options = json.loads(result.stdout)
        self.assertEqual(options["roles"]["reviewer"], {
            "model": "chosen", "effort": None, "fallback": "fail",
        })
        self.assertEqual(options["roles"]["validator"]["fallback"], "fail")
        self.assertEqual(options["roles"]["lead"]["fallback"], "configured")
        self.assertIn("User explicitly", options["option_sources"]["reviewer_model"])
        result = self.run_options("--context", context, "review-code",
                                  "--reviewer-model", "override", "--fallback", "configured")
        options = json.loads(result.stdout)
        self.assertEqual(options["roles"]["reviewer"]["model"], "override")
        self.assertEqual(options["roles"]["reviewer"]["fallback"], "configured")
        self.assertEqual(options["option_sources"]["reviewer_model"], "invocation")

    def test_resume_recomputes_fallback_policy_and_configuration(self):
        saved = review_options.parse_options("review-validate-fix-loop", [
            "--reviewer-model", "chosen", "--reviewer-effort", "high", "--fallback", "configured",
        ])
        saved["effective_model_selection"] = "auto"
        saved["configuration"] = {"auto_selection_enabled": True}
        context = self.write_context({"saved": saved})
        args = ("--context", context, "review-validate-fix-loop", "--resume", "saved-ledger")
        result = self.run_options(*args, "--model-selection", "configured", "--fallback", "fail")
        options = json.loads(result.stdout)
        self.assertEqual(options["model_selection"], "configured")
        self.assertEqual(options["effective_model_selection"], "configured")
        self.assertEqual(options["roles"]["reviewer"],
                         {"model": "chosen", "effort": "high", "fallback": "fail"})
        self.assertIsNone(options["max_loops"])
        self.assertIsNone(options["max_fix_cycles"])
        self.write_settings("project/.codex/ioncache-ai-tools.local.json",
                            {"review-auto-model-selection": False})
        options = json.loads(self.run_options(*args).stdout)
        self.assertEqual(options["model_selection"], "auto")
        self.assertEqual(options["effective_model_selection"], "configured")
        self.assertEqual(options["roles"]["reviewer"]["model"], "chosen")

    def test_context_errors_leave_help_and_corrected_invocations_reachable(self):
        self.assertEqual(self.run_options("review-validate-fix-loop", "--resume", "saved").returncode, 2)
        cases = [
            {"choices": {"unknown": {"value": "model", "source": "User"}}},
            {"choices": {"reviewer_model": {"value": 1, "source": "User"}}},
            {"choices": {"reviewer_model": {"value": "model", "source": ""}}},
            {"saved": {"skill": "review-code", "roles": {}}},
            {"unexpected": True},
        ]
        for context in cases:
            with self.subTest(context=context):
                path = self.write_context(context)
                result = self.run_options("--context", path, "review-code")
                self.assertEqual(result.returncode, 2)
                self.assertNotIn("Traceback", result.stderr)
                self.assertEqual(result.stdout, "")
        result = self.run_options("--context", "missing.json", "review-code", "--help")
        self.assertEqual(result.returncode, 0)
        path = self.write_context({"saved": None})
        result = self.run_options("--context", path, "review-validate-fix-loop", "--resume", "old-ledger")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["option_limitations"])


if __name__ == "__main__":
    unittest.main()
