#!/usr/bin/env python3
"""Run all checks, or pass CodexAdapterTests.test_name for one test."""
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
import uuid

import codex_adapter

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
        self.env = {
            **os.environ,
            'HOME': str(self.home),
            'CODEX_HOME': str(self.home / '.codex'),
            'COPILOT_HOME': str(self.home / '.copilot'),
            'PYTHONDONTWRITEBYTECODE': '1',
        }
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

    def test_manifest_serializes_dependent_hooks(self):
        for event in ('UserPromptSubmit', 'PreToolUse'):
            entries = self.entries(event)
            self.assertEqual(len(entries), 1)
            self.assertIn('codex_adapter.py', entries[0]['command'])
            self.assertTrue(entries[0]['command'].endswith(event))

    def test_prompt_order_survives_concurrent_host_dispatch(self):
        text = self.prompt('why is this different')
        self.assertIn('answer-questions skill', text)
        self.assertTrue(self.marker.exists())
        self.assertNotIn('answer-questions skill', self.prompt('Implement the change'))
        self.assertFalse(self.marker.exists())

    def test_prompt_preserves_all_reminders_and_consumer_cwd(self):
        graph = self.project / 'graphify-out/graph.json'
        graph.parent.mkdir()
        graph.write_text('{}')
        text = self.prompt('Implement the change')
        self.assertIn('graphify query', text)
        self.assertIn('Never state or rely on specifics', text)
        for name in ('scope-exactly-what-asked', 'verify-state-before-claiming'):
            rule = json.loads((ROOT / f'hooks/rules/{name}.json').read_text())
            self.assertIn(rule['message'], text)

    def test_question_blocks_patch_until_non_question_prompt(self):
        self.prompt('why is this different')
        output = self.tool('apply_patch', {'command': CLEAN_PATCH})
        self.assertEqual(output.get('permissionDecision'), 'deny', output)
        self.assertIn('classified as a question', output['permissionDecisionReason'])
        self.assertEqual(self.tool('Bash', {'command': 'git status --short'}), {})
        self.assertEqual(self.tool('mcp__files__read', {'path': 'safe.txt'}), {})
        self.invoke('Stop', last_assistant_message='Here is the answer.')
        self.assertTrue(self.marker.exists())
        self.prompt('Implement the change')
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.tool('apply_patch', {'command': CLEAN_PATCH}), {})

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
        for name in ('create-worktree', 'investigate', 'review-code', 'triage-errors', 'verify-unresolved-pr-comments'):
            with self.subTest(name=name):
                path = ROOT / 'skills' / name / 'SKILL.md'
                self.assertTrue(path.is_file())
                text = path.read_text()
                self.assertIn(f'name: {name}\n', text)
                self.assertNotIn('$ARGUMENTS', text)
                self.assertNotIn('!`', text)
        worktree_skill = (ROOT / 'skills/create-worktree/SKILL.md').read_text()
        self.assertIn('"', worktree_skill)
        self.assertIn('../../scripts/create-worktree.js', worktree_skill)

    def test_worktree_skill_example_quotes_installed_helper_path(self):
        install = self.root / 'plugin with spaces'
        install.symlink_to(ROOT, target_is_directory=True)
        skill = (install / 'skills/create-worktree/SKILL.md').read_text()
        command = next(line for line in skill.splitlines() if line.startswith('node '))
        helper = (install / 'skills/create-worktree' / '../../scripts/create-worktree.js').absolute()
        command = command.replace('/absolute/plugin root/scripts/create-worktree.js', str(helper))
        env = {**self.env, 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'}
        git = [
            'git', '-c', 'init.templateDir=', '-c', 'user.name=Self-check',
            '-c', 'user.email=self-check@example.invalid', '-c', 'commit.gpgsign=false',
        ]
        for args in (['init', '-q'], ['commit', '--allow-empty', '-qm', 'fixture']):
            subprocess.run(git + args, cwd=self.project, env=env, check=True, capture_output=True)
        config = self.project / '.claude/ioncache-ai-tools.local.json'
        config.parent.mkdir()
        config.write_text('{"enabledRules":["never_kill_without_asking"]}\n')
        result = subprocess.run(
            ['bash', '-c', command], cwd=self.project, env=env,
            text=True, capture_output=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        copied_config = self.root / 'feature worktree/.claude/ioncache-ai-tools.local.json'
        self.assertTrue(copied_config.is_symlink())
        self.assertEqual(copied_config.read_text(), config.read_text())

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
        for command in ('kill 123', 'git worktree add /tmp/new', 'printf x > package-lock.json', f'echo a{EM_DASH}b'):
            with self.subTest(command=command):
                output = self.tool('Bash', {'command': command})
                self.assertEqual(output.get('permissionDecision'), 'deny', output)
        self.assertEqual(self.tool('Bash', {'command': 'echo kill'}), {})

    def test_codex_config_overrides_apply_to_normalized_patches(self):
        path = self.home / '.codex/config.toml'
        path.parent.mkdir()
        global_config = '[ioncache-ai-tools]\ndisabled_rules = ["no-manual-lockfile-edit", "fix_emdash"]\n'
        path.write_text(global_config)
        patch = CLEAN_PATCH.replace('safe.txt', 'yarn.lock').replace('clean', EM_DASH)
        self.assertEqual(self.tool('apply_patch', {'command': patch}), {})
        path.write_text(
            global_config + f'\n[projects.{json.dumps(str(self.project))}.ioncache-ai-tools]\n'
            'enabled_rules = ["no-manual-lockfile-edit", "fix_emdash"]\n'
        )
        output = self.tool('apply_patch', {'command': patch})
        self.assertEqual(output.get('permissionDecision'), 'deny', output)
        self.assertIn('lockfile', output['permissionDecisionReason'])

    def test_stop_uses_supplied_response(self):
        self.assertEqual(self.invoke('Stop', last_assistant_message='clean response'), [{}])
        outputs = self.invoke('Stop', last_assistant_message=f'bad{EM_DASH}text')
        self.assertEqual(outputs[0]['decision'], 'block')
        self.assertEqual(self.invoke('Stop', last_assistant_message='corrected', stop_hook_active=True), [{}])

    def test_invalid_payloads_block_visibly(self):
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
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertIn('codex-adapter:', result.stderr)
                self.assertIn(message, result.stderr)

    def test_shared_hook_errors_block_instead_of_failing_open(self):
        data = {**self.payload, 'tool_name': 'Bash', 'tool_input': {'command': 'git status'}}
        for error in (RuntimeError('fixture failure'), subprocess.TimeoutExpired('fixture', 5)):
            with (
                self.subTest(error=type(error).__name__),
                mock.patch.object(codex_adapter, 'run_shared_hooks', side_effect=error),
                mock.patch.object(sys, 'argv', ['codex_adapter.py', 'PreToolUse']),
                mock.patch.object(sys, 'stdin', io.StringIO(json.dumps(data))),
                mock.patch.object(sys, 'stderr', new_callable=io.StringIO) as stderr,
                self.assertRaises(SystemExit) as stopped,
            ):
                codex_adapter.main()
            self.assertEqual(stopped.exception.code, 2)
            self.assertIn('codex-adapter:', stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
