#!/usr/bin/env python3
"""Run all checks, or pass CodexAdapterTests.test_name for one test."""
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import runpy
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
import uuid

import codex_adapter
import docs_cache
import guidance
from turn_guard_self_check import install_reviewers

ROOT = Path(__file__).resolve().parents[2]
EM_DASH = chr(0x2014)
CLEAN_PATCH = '*** Begin Patch\n*** Add File: safe.txt\n+clean\n*** End Patch'


class CodexAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='codex-adapter-check-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / 'project with spaces'
        self.project.mkdir()
        self.home = self.root / 'home'
        self.home.mkdir()
        settings = self.home / '.claude/ioncache-ai-tools.local.json'
        settings.parent.mkdir()
        settings.write_text(json.dumps({'features': {}}))
        self.env = {
            **os.environ,
            'HOME': str(self.home),
            'CODEX_HOME': str(self.home / '.codex'),
            'COPILOT_HOME': str(self.home / '.copilot'),
            'XDG_CACHE_HOME': str(self.home / '.cache'),
            'PYTHONDONTWRITEBYTECODE': '1',
            'PATH': install_reviewers(self.root),
        }
        patcher = mock.patch.dict(os.environ, self.env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.payload = {
            'session_id': f'self-check-{uuid.uuid4()}',
            'cwd': str(self.project),
            'turn_id': 'turn-1',
        }
        self.marker = Path(f'/tmp/.ioncache-pending-question-{self.payload["session_id"]}')
        self.addCleanup(lambda: self.marker.unlink(missing_ok=True))

    def entries(self, event):
        manifest = json.loads((ROOT / '.codex-plugin/plugin.json').read_text())
        hooks = json.loads((ROOT / manifest['hooks']).read_text())
        return [entry for group in hooks['hooks'][event] for entry in group['hooks']]

    def run_entry(self, entry, payload):
        command = [
            arg.replace('${CLAUDE_PLUGIN_ROOT}', str(ROOT)).replace('${PLUGIN_ROOT}', str(ROOT))
            for arg in shlex.split(entry['command'])
        ]
        result = subprocess.run(
            command, input=json.dumps(payload), text=True, capture_output=True,
            env=self.env, cwd=self.root, timeout=entry.get('timeout', 15),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def invoke(self, event, **fields):
        payload = {**self.payload, 'hook_event_name': event, **fields}
        with ThreadPoolExecutor() as executor:
            futures = [executor.submit(self.run_entry, entry, payload) for entry in self.entries(event)]
            return [future.result() for future in futures]

    def test_adapter_stays_out_of_docs_distiller_runs(self):
        self.assertIn('documentation-backed', self.prompt('Implement it'))
        self.env['IONCACHE_DOCS_DISTILLER'] = '1'
        self.assertEqual(self.prompt('Implement it'), '')

    def prompt(self, text):
        outputs = self.invoke('UserPromptSubmit', prompt=text)
        return '\n\n'.join(
            output.get('hookSpecificOutput', {}).get('additionalContext', '')
            for output in outputs
        )

    def tool(self, name, args):
        outputs = self.invoke('PreToolUse', tool_name=name, tool_input=args)
        return next((
            output['hookSpecificOutput'] for output in outputs
            if output.get('hookSpecificOutput', {}).get('permissionDecision') == 'deny'
        ), {})

    def test_autonomous_work_does_not_need_turn_or_task_permission_state(self):
        (self.home / '.claude/ioncache-ai-tools.local.json').write_text('{"features": {}}')
        self.prompt('Implement the requested change')
        self.marker.write_text('stale question')
        self.assertEqual(self.tool('spawn_agent', {'message': 'Implement the assigned change'}), {})
        for identity in (None, 'first', 'second'):
            self.invoke('UserPromptSubmit', agent_id=identity, prompt='Why did that change?')
            self.invoke('PreCompact', agent_id=identity)
            self.invoke('SessionStart', agent_id=identity, source='resume')
            for worker in (None, 'first', 'second'):
                self.assertEqual(self.invoke('PreToolUse', agent_id=worker, tool_name='apply_patch',
                                             tool_input={'command': CLEAN_PATCH}), [{}])
        self.assertFalse((self.home / '.cache/ioncache-ai-tools/claim-evidence').exists())


    def test_manifest_serializes_dependent_hooks(self):
        for event in ('UserPromptSubmit', 'PreToolUse', 'PostToolUse'):
            entries = self.entries(event)
            self.assertEqual(len(entries), 1)
            self.assertIn('codex_adapter.py', entries[0]['command'])
            self.assertTrue(entries[0]['command'].endswith(event))

    def test_lifecycle_and_stop_do_not_create_question_permission_state(self):
        self.assertIn('documentation-backed', str(self.invoke('SessionStart', source='startup')))
        self.assertEqual(self.prompt('Why does this happen?').count('Question guidance:'), 1)
        output = self.invoke('Stop', last_assistant_message=f'Bad{EM_DASH}punctuation.')[0]
        self.assertEqual(output, {})
        self.assertFalse(self.marker.exists())
        self.invoke('PreCompact')
        self.assertIn('documentation-backed', str(self.invoke('SessionStart', source='compact')))
        output = self.invoke('Stop', last_assistant_message='Corrected punctuation.', stop_hook_active=True)[0]
        self.assertEqual(output, {})
        self.assertEqual(self.tool('apply_patch', {'command': CLEAN_PATCH}), {})

    def test_scope_and_reply_checks_do_not_launch_a_reviewer(self):
        capture = self.root / 'unexpected-review.txt'
        self.env.update(REVIEW_FIXTURE_CAPTURE=str(capture), REVIEW_FIXTURE_ERROR='Reviewer unavailable')
        self.prompt('Implement the requested change')
        self.assertEqual(self.tool('apply_patch', {'command': CLEAN_PATCH}), {})
        self.assertEqual(self.tool('task', {'prompt': 'Inspect the requested code'}), {})
        self.assertEqual(self.invoke('Stop', last_assistant_message='The change is ready.'), [{}])
        self.assertFalse(capture.exists())


    def test_configuration_deadline_reports_failure_without_blocking_work(self):
        self.prompt('Implement the requested change')
        self.payload['turn_id'] = 'turn-2'
        data = {**self.payload, 'prompt': 'Implement the revised change'}
        with (
            mock.patch.object(codex_adapter, 'ADAPTER_TIMEOUT_SECONDS', 0.02),
            mock.patch.object(codex_adapter, 'synchronize', side_effect=lambda *_: time.sleep(1)),
            mock.patch.object(sys, 'argv', ['codex_adapter.py', 'UserPromptSubmit']),
            mock.patch.object(sys, 'stdin', io.StringIO(json.dumps(data))),
            mock.patch.object(sys, 'stderr', io.StringIO()) as stderr,
            mock.patch.object(sys, 'stdout', io.StringIO()) as notices,
        ):
            codex_adapter.main()
        self.assertNotIn('permissionDecision', notices.getvalue())
        self.assertIn('invocation deadline', stderr.getvalue())
        self.assertEqual(self.tool('apply_patch', {'command': CLEAN_PATCH}), {})
        self.assertEqual(self.tool('request_user_input', {}), {})
        self.prompt('Implement the revised change')
        self.assertEqual(self.tool('apply_patch', {'command': CLEAN_PATCH}), {})

    def test_native_web_open_uses_shared_cache_without_granting_permission(self):
        args = {'open': [{'ref_id': 'https://git-scm.com/docs/git-commit'}], 'response_length': 'long'}
        self.assertEqual(self.invoke('PreToolUse', tool_name='webrun', tool_input=args), [{}])
        with mock.patch.dict(os.environ, self.env):
            url = args['open'][0]['ref_id']
            docs_cache.store_fact(docs_cache.cache_key(url, None), url, 'shared Claude answer', 'claude',
                                  source={'reference_only': True, 'question': 'Explain --dry-run.'})
        output = self.tool('webrun', args)
        self.assertEqual(output['permissionDecision'], 'deny')
        self.assertIn('shared Claude answer', output['permissionDecisionReason'])
        self.assertEqual(self.invoke('PreToolUse', tool_name='webrun', tool_input=args), [{}])
        self.assertEqual(self.invoke('PreToolUse', tool_name='webrun',
                                     tool_input={'search_query': [{'q': 'git commit'}]}), [{}])

    def test_native_cache_failure_preserves_tool_permissions(self):
        with mock.patch.object(docs_cache, 'codex_pre', side_effect=PermissionError('unavailable')), \
                mock.patch.object(sys, 'stderr', io.StringIO()):
            output = codex_adapter.run_hook('PreToolUse', {
                **self.payload, 'tool_name': 'webrun', 'tool_input': {'open': [{'ref_id': 'https://example.com'}]},
            })
        self.assertIsNone(output)

    def test_native_distiller_notice_is_display_only_and_deduplicated(self):
        with mock.patch.dict(os.environ, self.env):
            docs_cache.set_status('worker unavailable')
        output = self.invoke('PostToolUse', tool_name='Bash', tool_input={'command': 'true'},
                             tool_response='')[0]
        self.assertIn('worker unavailable', output['systemMessage'])
        self.assertNotIn('hookSpecificOutput', output)
        for _ in range(2):
            self.assertEqual(self.invoke('Stop', last_assistant_message='Done.'), [{}])
        self.assertEqual(self.invoke('PostToolUse', tool_name='Bash', tool_input={'command': 'true'},
                                     tool_response=''), [{}])


    def test_null_stop_response_does_not_require_a_cache_notice_in_prose(self):
        with mock.patch.dict(os.environ, self.env):
            docs_cache.set_status('worker unavailable')
        output = self.invoke('Stop', last_assistant_message=None)[0]
        self.assertIn('worker unavailable', output['systemMessage'])
        self.assertNotIn('decision', output)
        self.assertEqual(self.invoke('Stop', last_assistant_message=None), [{}])
        self.assertEqual(self.invoke('PostToolUse', tool_name='Bash', tool_input={'command': 'true'},
                                     tool_response=''), [{}])

    def test_prompt_order_survives_concurrent_host_dispatch(self):
        text = self.prompt('why is this different')
        self.assertIn('Question guidance:', text)
        self.assertFalse(self.marker.exists())
        self.assertNotIn('Question guidance:', self.prompt('Implement the change'))
        self.assertFalse(self.marker.exists())

    def test_prompt_preserves_all_reminders_and_consumer_cwd(self):
        text = self.prompt('Implement the change')
        self.assertIn('documentation-backed', text)
        for name in ('engineering-judgment', 'scope-exactly-what-asked'):
            rule = json.loads((ROOT / f'hooks/rules/{name}.json').read_text())
            self.assertIn(rule['message'], text)
        self.assertIn('documentation-backed', self.prompt('Continue the implementation'))


    def test_engineering_reminder_can_be_disabled_and_reenabled(self):
        name = 'engineering-judgment'
        rule = json.loads((ROOT / f'hooks/rules/{name}.json').read_text())
        scope = json.loads((ROOT / 'hooks/rules/scope-exactly-what-asked.json').read_text())
        config = self.home / '.codex/config.toml'
        config.parent.mkdir()
        disabled = f'[ioncache-ai-tools]\ndisabled_rules = ["{name}"]\n'
        config.write_text(disabled)
        text = self.prompt('Implement the feature')
        self.assertNotIn(rule['message'], text)
        self.assertIn(scope['message'], text)
        project_config = self.project / '.codex/ioncache-ai-tools.local.json'
        project_config.parent.mkdir()
        project_config.write_text(json.dumps({'features': {name: True}}))
        self.invoke('PreCompact')
        self.assertIn(rule['message'], self.prompt('Implement the feature'))
        self.assertIn(rule['message'], self.prompt('Continue the feature'))


    def test_patch_checks_all_targets_and_move_destinations(self):
        targets = (
            '*** Add File: package-lock.json\n+new',
            '*** Update File: pnpm-lock.yaml\n@@\n-old\n+new',
            '*** Delete File: yarn.lock',
            '*** Update File: old.txt\n*** Move to: yarn.lock\n@@\n-old\n+new',
            '*** Update File: yarn.lock\n*** Move to: safe.lock\n@@\n-old\n+new',
        )
        for target in targets:
            patch = f'*** Begin Patch\n*** Add File: safe.txt\n+clean\n{target}\n*** End Patch'
            with self.subTest(target=target):
                output = self.tool('apply_patch', {'command': patch})
                self.assertEqual(output.get('permissionDecision'), 'deny', output)
                self.assertIn('lockfile', output['permissionDecisionReason'])
                self.assertNotIn('updatedInput', output)

    def test_patch_checks_added_text_without_rewriting_context(self):
        patch = (
            f'*** Begin Patch\n*** Update File: safe.txt\n@@\n context{EM_DASH}text\n'
            f'-old{EM_DASH}text\n+clean\n*** End Patch'
        )
        outputs = self.invoke('PreToolUse', tool_name='apply_patch', tool_input={'command': patch})
        self.assertTrue(all(output == {} for output in outputs), outputs)
        for added in (f'+new{EM_DASH}text', f'+prefix\n+later{EM_DASH}text'):
            with self.subTest(added=added):
                output = self.tool('apply_patch', {'command': patch.replace('+clean', added)})
                self.assertEqual(output.get('permissionDecision'), 'deny', output)
                self.assertNotIn('updatedInput', output)

    def test_later_file_denial_wins_over_earlier_rewrite(self):
        patch = (
            f'*** Begin Patch\n*** Add File: safe.txt\n+new{EM_DASH}text\n'
            '*** Delete File: yarn.lock\n*** End Patch'
        )
        output = self.tool('apply_patch', {'command': patch})
        self.assertEqual(output.get('permissionDecision'), 'deny', output)
        self.assertIn('lockfile', output['permissionDecisionReason'])
        self.assertNotIn('updatedInput', output)

    def test_large_patch_checks_last_target_within_hook_budget(self):
        patch = '*** Begin Patch\n' + ''.join(
            f'*** Add File: safe-{index}.txt\n+x\n' for index in range(1000)
        ) + '*** Delete File: yarn.lock\n*** End Patch'
        started = time.monotonic()
        output = self.tool('apply_patch', {'command': patch})
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual(output['permissionDecision'], 'deny')
        self.assertIn('lockfile', output['permissionDecisionReason'])

    def test_workflows_ship_as_native_skills(self):
        for name in (
            'create-worktree', 'engineering-judgment', 'investigate', 'review-code',
            'triage-errors', 'verify-unresolved-pr-comments',
        ):
            with self.subTest(name=name):
                path = ROOT / 'skills' / name / 'SKILL.md'
                self.assertTrue(path.is_file())
                text = path.read_text()
                self.assertIn(f'name: {name}\n', text)
                self.assertNotIn('$ARGUMENTS', text)
                self.assertNotIn('!`', text)
        worktree_skill = (ROOT / 'skills/create-worktree/SKILL.md').read_text()
        self.assertIn('"', worktree_skill)
        self.assertIn('../../scripts/create-worktree.py', worktree_skill)

    def test_worktree_skill_example_quotes_installed_helper_path(self):
        install = self.root / 'plugin with spaces'
        install.symlink_to(ROOT, target_is_directory=True)
        skill = (install / 'skills/create-worktree/SKILL.md').read_text()
        command = skill.split('```bash\n', 1)[1].splitlines()[0]
        command = command.replace('/absolute/plugin root', str(install))
        env = {**self.env, 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'}
        git = [
            'git', '-c', 'init.templateDir=', '-c', 'user.name=Self-check',
            '-c', 'user.email=self-check@example.invalid', '-c', 'commit.gpgsign=false',
        ]
        for args in (['init', '-q'], ['commit', '--allow-empty', '-qm', 'fixture']):
            subprocess.run(git + args, cwd=self.project, env=env, check=True, capture_output=True)
        config = self.project / '.claude/ioncache-ai-tools.local.json'
        config.parent.mkdir()
        config.write_text('{"enabledRules":["no_broad_process_kill"]}\n')
        runtime = self.root / 'runtime with spaces'
        runtime.mkdir()
        (runtime / 'python3').symlink_to(sys.executable)
        bash = shutil.which('bash')
        for attempt in range(2):
            with self.subTest(missing_node_attempt=attempt):
                result = subprocess.run(
                    [bash, '-c', command], cwd=self.project,
                    env={**env, 'PATH': str(runtime)},
                    text=True, capture_output=True, timeout=15,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Node.js', result.stderr)
                self.assertIn('PATH', result.stderr)
                self.assertIn('retry', result.stderr)
                self.assertFalse((self.root / 'feature worktree').exists())
                self.assertFalse((self.project / '.worktree-setup.json').exists())
        node = runtime / 'node'
        node.write_text(
            '#!/bin/sh\nif [ "$1" = "--version" ]; then\n'
            '  printf "v22.11.9\\n"\n  exit 0\nfi\n'
            f'exec {shlex.quote(shutil.which("node"))} "$@"\n'
        )
        node.chmod(0o755)
        result = subprocess.run(
            [bash, '-c', command], cwd=self.project,
            env={**env, 'PATH': str(runtime) + os.pathsep + env['PATH']},
            text=True, capture_output=True, timeout=15,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('22.11.9', result.stderr)
        self.assertIn('22.12.0', result.stderr)
        self.assertIn('retry', result.stderr)
        self.assertFalse((self.root / 'feature worktree').exists())
        self.assertFalse((self.project / '.worktree-setup.json').exists())
        result = subprocess.run(
            [bash, '-c', command], cwd=self.project, env=env,
            text=True, capture_output=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        copied_config = self.root / 'feature worktree/.claude/ioncache-ai-tools.local.json'
        self.assertTrue(copied_config.is_symlink())
        self.assertEqual(copied_config.read_text(), config.read_text())

    def test_worktree_launcher_does_not_invoke_missing_node(self):
        launcher = runpy.run_path(str(ROOT / 'scripts/create-worktree.py'))
        with mock.patch.object(shutil, 'which', return_value=None), \
                mock.patch.object(subprocess, 'run') as probe, \
                mock.patch.object(os, 'execv') as invoke, \
                mock.patch.object(sys, 'stderr', io.StringIO()):
            self.assertEqual(launcher['main'](), 1)
            probe.assert_not_called()
            invoke.assert_not_called()

    def test_worktree_launcher_rejects_unsupported_node_versions(self):
        launcher = runpy.run_path(str(ROOT / 'scripts/create-worktree.py'))
        for version in ('v14.21.3', 'v22.11.9', 'v22.12.0-rc.1', 'not a version', ''):
            with self.subTest(version=version), \
                    mock.patch.object(shutil, 'which', return_value='/fixture/node'), \
                    mock.patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess(
                        ['/fixture/node', '--version'], 0, stdout=version, stderr='',
                    )), \
                    mock.patch.object(os, 'execv') as invoke, \
                    mock.patch.object(sys, 'stderr', io.StringIO()) as stderr:
                self.assertEqual(launcher['main'](), 1)
                self.assertIn('22.12.0', stderr.getvalue())
                self.assertIn('retry', stderr.getvalue())
                invoke.assert_not_called()

    def test_worktree_launcher_handles_version_probe_failure(self):
        launcher = runpy.run_path(str(ROOT / 'scripts/create-worktree.py'))
        command = ['/fixture/node', '--version']
        for error in (
            subprocess.CalledProcessError(2, command),
            subprocess.TimeoutExpired(command, 5),
        ):
            with self.subTest(error=type(error).__name__), \
                    mock.patch.object(shutil, 'which', return_value=command[0]), \
                    mock.patch.object(subprocess, 'run', side_effect=error), \
                    mock.patch.object(os, 'execv') as invoke, \
                    mock.patch.object(sys, 'stderr', io.StringIO()) as stderr:
                self.assertEqual(launcher['main'](), 1)
                self.assertIn('22.12.0', stderr.getvalue())
                self.assertIn('retry', stderr.getvalue())
                invoke.assert_not_called()

    def test_worktree_launcher_reports_launch_failure_and_allows_retry(self):
        launcher = runpy.run_path(str(ROOT / 'scripts/create-worktree.py'))
        command = ['/fixture/node', '--version']
        error = PermissionError(13, 'Permission denied', command[0])
        with mock.patch.object(shutil, 'which', return_value=command[0]), \
                mock.patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess(
                    command, 0, stdout='v22.12.0\n', stderr='',
                )), \
                mock.patch.object(os, 'execv', side_effect=[error, None]) as invoke, \
                mock.patch.object(sys, 'stderr', io.StringIO()) as stderr:
            self.assertEqual(launcher['main'](), 1)
            self.assertIn('could not launch Node.js', stderr.getvalue())
            self.assertIn(str(error), stderr.getvalue())
            self.assertIn('retry', stderr.getvalue())
            self.assertIn('No worktree was created', stderr.getvalue())
            self.assertNotIn('or later is required', stderr.getvalue())
            self.assertNotIn('Install or upgrade', stderr.getvalue())
            invoke.assert_called_once()

            stderr.seek(0)
            stderr.truncate()
            launcher['main']()
            self.assertEqual(invoke.call_count, 2)
            self.assertEqual(stderr.getvalue(), '')

    def test_worktree_launcher_preserves_arguments_and_exit_status(self):
        runtime = self.root / 'runtime with spaces'
        runtime.mkdir()
        node = runtime / 'node'
        args = ['-b', 'branch with spaces', '../worktree; printf injected']
        for version in ('v22.12.0', 'v22.12.1', 'v24.0.0'):
            with self.subTest(version=version):
                node.write_text(
                    '#!/bin/sh\nif [ "$1" = "--version" ]; then\n'
                    f'  printf "{version}\\n"\n  exit 0\nfi\n'
                    'printf "%s\\n" "$@"\nprintf "node diagnostic\\n" >&2\nexit 23\n'
                )
                node.chmod(0o755)
                result = subprocess.run(
                    [sys.executable, str(ROOT / 'scripts/create-worktree.py'), *args],
                    cwd=self.project, env={**self.env, 'PATH': str(runtime)},
                    text=True, capture_output=True, timeout=15,
                )
                self.assertEqual(result.returncode, 23)
                self.assertEqual(
                    result.stdout.splitlines(), [str(ROOT / 'scripts/create-worktree.js'), *args],
                )
                self.assertEqual(result.stderr, 'node diagnostic\n')

    def test_worktree_launcher_reports_unusable_node(self):
        runtime = self.root / 'broken runtime'
        runtime.mkdir()
        node = runtime / 'node'
        node.write_text('not an executable format\n')
        node.chmod(0o755)
        result = subprocess.run(
            [sys.executable, str(ROOT / 'scripts/create-worktree.py'), '-b', 'feature', '../feature'],
            cwd=self.project, env={**self.env, 'PATH': str(runtime)},
            text=True, capture_output=True, timeout=15,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Node.js 22.12.0', result.stderr)
        self.assertIn('retry', result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        self.assertEqual(list(self.project.iterdir()), [])
        self.assertFalse((self.root / 'feature').exists())

    def test_safe_calls_do_not_override_permissions(self):
        for name, args in (
            ('apply_patch', {'command': CLEAN_PATCH}),
            ('Bash', {'command': 'git status'}),
            ('mcp__files__read', {'path': 'safe.txt'}),
        ):
            with self.subTest(name=name):
                self.assertEqual(self.invoke('PreToolUse', tool_name=name, tool_input=args), [{}])

    def test_patch_rewrite_from_any_shared_hook_is_denied(self):
        rewrite = {'hookSpecificOutput': {
            'hookEventName': 'PreToolUse', 'updatedInput': {'command': CLEAN_PATCH},
        }}
        with mock.patch.object(codex_adapter, 'run_shared_hooks', return_value=[rewrite]):
            output = codex_adapter.pre_tool_use({
                **self.payload, 'tool_name': 'apply_patch', 'tool_input': {'command': CLEAN_PATCH},
            })
        self.assertEqual(output['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertNotIn('updatedInput', output['hookSpecificOutput'])

    def test_codex_non_patch_rewrite_uses_required_protocol(self):
        rewrite = {'hookSpecificOutput': {
            'hookEventName': 'PreToolUse', 'updatedInput': {'command': 'echo rewritten'},
        }}
        with mock.patch.object(codex_adapter, 'run_shared_hooks', return_value=[rewrite]):
            output = codex_adapter.pre_tool_use({
                **self.payload, 'tool_name': 'Bash', 'tool_input': {'command': 'echo original'},
            })
        self.assertEqual(output['hookSpecificOutput']['permissionDecision'], 'allow')
        self.assertEqual(output['hookSpecificOutput']['updatedInput'], {'command': 'echo rewritten'})

    def test_native_shell_rules(self):
        for command in ('pkill worker', 'git worktree add /tmp/new', 'printf x > package-lock.json',
                        'MODE=review pkill worker', "if true; then sed -i 's/a/b/' package-lock.json; fi",
                        f'echo a{EM_DASH}b', 'echo ready # status\npkill worker',
                        "echo ready; pkill worker\nprintf 'unfinished"):
            with self.subTest(command=command):
                output = self.tool('Bash', {'command': command})
                self.assertEqual(output.get('permissionDecision'), 'deny', output)
        self.assertEqual(self.tool('Bash', {'command': 'echo kill'}), {})
        self.assertEqual(self.tool('Bash', {'command': "echo ';' pkill worker"}), {})
        self.assertEqual(self.tool('Bash', {'command': "echo '>' package-lock.json"}), {})


    def test_patch_header_whitespace_is_denied(self):
        for target in ('Add File: yarn.lock\f\n+x', 'Update File: yarn.lock\f\n@@\n-old\n+new',
                       'Delete File: yarn.lock\f', 'Update File: safe.txt\n*** Move to: yarn.lock\f\n@@\n-old\n+new'):
            patch = f'*** Begin Patch\n*** {target}\n*** End Patch'
            with self.subTest(target=target):
                output = self.tool('apply_patch', {'command': patch})
                self.assertEqual(output.get('permissionDecision'), 'deny')
                self.assertIn('header whitespace', output['permissionDecisionReason'])
                self.assertNotIn('updatedInput', output)

    def test_patch_checks_text_after_non_lf_separators(self):
        for separator in ('\f', chr(0x2028), chr(0x2029)):
            with self.subTest(separator=repr(separator)):
                patch = CLEAN_PATCH.replace('clean', f'before{separator}after{EM_DASH}text')
                output = self.tool('apply_patch', {'command': patch})
                self.assertEqual(output.get('permissionDecision'), 'deny', output)
                self.assertNotIn('updatedInput', output)
                self.assertEqual(self.tool('apply_patch', {'command': patch.replace(EM_DASH, ',')}), {})

    def test_codex_config_overrides_apply_to_normalized_patches(self):
        path = self.home / '.codex/config.toml'
        path.parent.mkdir()
        global_config = '[ioncache-ai-tools]\ndisabled_rules = ["no-manual-lockfile-edit", "fix_emdash"]\n'
        path.write_text(global_config)
        patch = CLEAN_PATCH.replace('safe.txt', 'yarn.lock').replace('clean', EM_DASH)
        self.assertEqual(self.tool('apply_patch', {'command': patch}), {})
        project_config = self.project / '.codex/ioncache-ai-tools.local.json'
        project_config.parent.mkdir()
        project_config.write_text(json.dumps({'features': {'no-manual-lockfile-edit': True, 'fix_emdash': True}}))
        output = self.tool('apply_patch', {'command': patch})
        self.assertEqual(output.get('permissionDecision'), 'deny', output)
        self.assertIn('lockfile', output['permissionDecisionReason'])

    def test_stop_does_not_retry_already_visible_responses(self):
        self.assertEqual(self.invoke('Stop', last_assistant_message='clean response'), [{}])
        outputs = self.invoke('Stop', last_assistant_message=f'bad{EM_DASH}text')
        self.assertEqual(outputs, [{}])
        self.assertEqual(self.invoke('Stop', last_assistant_message='corrected', stop_hook_active=True), [{}])

    def test_invalid_payloads_report_unavailability_without_granting_permission(self):
        valid = {**self.payload, 'tool_name': 'apply_patch', 'tool_input': {'command': CLEAN_PATCH}}
        cases = (
            ('PreToolUse', [], 'must be an object'),
            ('PreToolUse', {**valid, 'session_id': '../escape'}, 'session_id'),
            ('PreToolUse', {**valid, 'cwd': None}, 'cwd'),
            ('PreToolUse', {**valid, 'tool_input': {'command': 1}}, 'must be a string'),
            ('PreToolUse', {**valid, 'tool_input': {'command': 'malformed'}}, 'no recognized file headers'),
            ('UserPromptSubmit', {**self.payload, 'prompt': []}, 'prompt'),
        )
        for event, data, message in cases:
            with self.subTest(event=event, message=message):
                result = subprocess.run(
                    [sys.executable, str(ROOT / 'hooks/scripts/codex_adapter.py'), event],
                    input=json.dumps(data), text=True, capture_output=True,
                    env=self.env, cwd=self.root, timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn('permissionDecision', result.stdout)
                self.assertIn('checks unavailable', result.stderr)
                self.assertIn(message, result.stderr)

    def test_shared_hook_errors_report_unavailability_without_blocking(self):
        data = {**self.payload, 'tool_name': 'Bash', 'tool_input': {'command': 'git status'}}
        for error in (RuntimeError('fixture failure'), subprocess.TimeoutExpired('fixture', 5)):
            with (
                self.subTest(error=type(error).__name__),
                mock.patch.object(codex_adapter, 'run_shared_hooks', side_effect=error),
                mock.patch.object(sys, 'argv', ['codex_adapter.py', 'PreToolUse']),
                mock.patch.object(sys, 'stdin', io.StringIO(json.dumps(data))),
                mock.patch.object(sys, 'stderr', new_callable=io.StringIO) as stderr,
                mock.patch.object(sys, 'stdout', new_callable=io.StringIO) as stdout,
            ):
                codex_adapter.main()
            self.assertIn('checks unavailable', stderr.getvalue())
            self.assertNotIn('permissionDecision', stdout.getvalue())


if __name__ == '__main__':
    unittest.main()
