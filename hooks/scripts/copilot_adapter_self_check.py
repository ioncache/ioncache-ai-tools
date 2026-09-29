#!/usr/bin/env python3
"""Run all checks, or pass CopilotAdapterTests.test_name for one test."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import uuid

import copilot_adapter
import hook_adapter_common

ROOT = Path(__file__).resolve().parents[2]
EM_DASH = chr(0x2014)


class CopilotAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='copilot-adapter-check-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'project with spaces'
        self.project.mkdir()
        self.home = self.root / 'home'
        self.home.mkdir()
        self.env = {
            **os.environ,
            'HOME': str(self.home),
            'COPILOT_HOME': str(self.home / '.copilot'),
            'CODEX_HOME': str(self.home / '.codex'),
            'PYTHONDONTWRITEBYTECODE': '1',
        }
        self.payload = {
            'sessionId': f'self-check-{uuid.uuid4()}',
            'cwd': str(self.project),
            'timestamp': 123456,
        }
        self.marker = Path(f'/tmp/.ioncache-pending-question-copilot-{self.payload["sessionId"]}')
        self.addCleanup(lambda: self.marker.unlink(missing_ok=True))

    def invoke(self, event, **fields):
        result = subprocess.run(
            [sys.executable, str(ROOT / 'hooks/scripts/copilot_adapter.py'), event],
            input=json.dumps({**self.payload, **fields}), text=True,
            capture_output=True, env=self.env, cwd=self.root, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else {}, result.stderr

    def prompt(self, prompt):
        return self.invoke('userPromptTransformed', prompt=prompt, transformedPrompt='expanded prompt')[0]

    def tool(self, name, args):
        return self.invoke('preToolUse', toolName=name, toolArgs=args)[0]

    def write_config(self, path, config):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config))

    def transcript_events(self, text):
        return [
            {'type': 'user.message', 'data': {'content': 'a prompt'}},
            {'type': 'assistant.turn_start', 'data': {'turnId': 'current'}},
            {'type': 'assistant.message', 'data': {'content': text}},
            {'type': 'hook.start', 'data': {'hookType': 'agentStop', 'input': self.payload}},
        ]

    def write_events(self, events):
        path = self.root / 'events.jsonl'
        path.write_text(''.join(json.dumps(event) + '\n' for event in events))
        return path

    def test_manifest_reuses_shared_components(self):
        manifest = json.loads((ROOT / '.github/plugin/plugin.json').read_text())
        for path in ('.claude-plugin/plugin.json', '.codex-plugin/plugin.json'):
            other = json.loads((ROOT / path).read_text())
            self.assertEqual(manifest['name'], other['name'])
            self.assertEqual(manifest['version'], other['version'])
        self.assertEqual((ROOT / manifest['commands']).resolve(), ROOT / 'commands')
        self.assertEqual((ROOT / manifest['skills']).resolve(), ROOT / 'skills')
        hooks = json.loads((ROOT / manifest['hooks']).read_text())
        self.assertEqual(hooks['version'], 1)
        self.assertEqual(set(hooks['hooks']), {
            'userPromptTransformed', 'preToolUse', 'agentStop', 'sessionEnd',
        })
        for event, entries in hooks['hooks'].items():
            self.assertEqual(len(entries), 1)
            self.assertIn('${COPILOT_PLUGIN_ROOT}/hooks/scripts/copilot_adapter.py', entries[0]['bash'])
            self.assertTrue(entries[0]['bash'].endswith(event))

    def test_prompt_preserves_transformation_and_injects_shared_reminders(self):
        output = self.prompt('Implement the feature')
        text = output['modifiedTransformedPrompt']
        self.assertTrue(text.startswith('expanded prompt\n\n'))
        self.assertIn('Never state or rely on specifics', text)
        self.assertIn('ioncache-ai-tools', text)
        for name in ('scope-exactly-what-asked', 'verify-state-before-claiming'):
            rule = json.loads((ROOT / f'hooks/rules/{name}.json').read_text())
            self.assertIn(rule['message'], text)

    def test_graphify_uses_consumer_cwd(self):
        graph = self.project / 'graphify-out/graph.json'
        graph.parent.mkdir()
        graph.write_text('{}')
        self.assertIn('graphify query', self.prompt('Investigate the flow')['modifiedTransformedPrompt'])

    def test_question_blocks_mutations_until_non_question_prompt(self):
        text = self.prompt('why is this behavior different')['modifiedTransformedPrompt']
        self.assertIn('answer-questions', text)
        self.assertTrue(self.marker.exists())
        for name, args in [
            ('create', {'path': 'x', 'file_text': 'y'}),
            ('edit', {'path': 'x', 'old_str': 'a', 'new_str': 'b'}),
            ('apply_patch', '*** Begin Patch\n*** Add File: x\n+y\n*** End Patch'),
            ('bash', {'command': 'git commit -m change'}),
        ]:
            with self.subTest(name=name):
                self.assertEqual(self.tool(name, args)['permissionDecision'], 'deny')
        self.assertEqual(self.tool('view', {'path': 'x'}), {})
        self.assertEqual(self.tool('bash', {'command': 'git status --short'}), {})
        self.prompt('Implement the change')
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.tool('create', {'path': 'x', 'file_text': 'y'}), {})

    def test_native_shell_rules(self):
        for command in ('kill 123', 'git worktree add /tmp/new', 'printf x > package-lock.json'):
            with self.subTest(command=command):
                self.assertEqual(self.tool('bash', {'command': command})['permissionDecision'], 'deny')
        self.assertEqual(self.tool('bash', {'command': 'echo kill'}), {})
        self.assertEqual(self.tool('bash', json.dumps({'command': 'git status'})), {})

    def test_edits_and_writes_rewrite_only_new_text_without_granting_permission(self):
        cases = [
            ('create', {'path': 'x', 'file_text': f'a{EM_DASH}b'}, 'file_text'),
            ('edit', {'path': 'x', 'old_str': f'old{EM_DASH}text', 'new_str': f'a{EM_DASH}b'}, 'new_str'),
            ('str_replace_editor', {'command': 'insert', 'path': 'x', 'insert_line': 2, 'new_str': f'a{EM_DASH}b'}, 'new_str'),
        ]
        for name, args, field in cases:
            with self.subTest(name=name):
                output = self.tool(name, args)
                self.assertEqual(output, {'modifiedArgs': {**args, field: 'a, b'}})
        args = {'path': 'x', 'old_str': f'old{EM_DASH}text', 'new_str': 'clean'}
        self.assertEqual(self.tool('edit', args), {})

    def test_lockfile_denial_wins_over_rewrite(self):
        for name, args in [
            ('create', {'path': 'package-lock.json', 'file_text': EM_DASH}),
            ('edit', {'path': 'pnpm-lock.yaml', 'old_str': 'x', 'new_str': EM_DASH}),
        ]:
            output = self.tool(name, args)
            self.assertEqual(output['permissionDecision'], 'deny')
            self.assertNotIn('modifiedArgs', output)

    def test_patch_checks_all_files_and_move_destinations(self):
        for header in ('Add File', 'Update File', 'Delete File', 'Move to'):
            patch = f'*** Begin Patch\n*** Update File: safe.txt\n+x\n*** {header}: yarn.lock\n+y\n*** End Patch'
            with self.subTest(header=header):
                self.assertEqual(self.tool('apply_patch', patch)['permissionDecision'], 'deny')
        patch = '*** Begin Patch\n*** Add File: safe.txt\n+content\n*** End Patch'
        self.assertEqual(self.tool('apply_patch', patch), {})
        self.assertEqual(self.tool('apply_patch', {'input': patch}), {})

    def test_patch_preserves_context_and_denies_only_added_emdashes(self):
        patch = f'*** Begin Patch\n*** Update File: x\n@@\n context{EM_DASH}text\n-old{EM_DASH}text\n+clean\n*** End Patch'
        self.assertEqual(self.tool('apply_patch', patch), {})
        output = self.tool('apply_patch', patch.replace('+clean', f'+new{EM_DASH}text'))
        self.assertEqual(output['permissionDecision'], 'deny')
        self.assertNotIn('modifiedArgs', output)

    def test_copilot_config_overrides_and_cross_host_union(self):
        global_path = self.home / '.copilot/ioncache-ai-tools.local.json'
        local_path = self.project / '.github/copilot/ioncache-ai-tools.local.json'
        rule = 'never_kill_without_asking'
        self.write_config(global_path, {'disabledRules': [rule]})
        self.assertEqual(self.tool('bash', {'command': 'kill 123'}), {})
        self.write_config(local_path, {'enabledRules': [rule]})
        self.assertEqual(self.tool('bash', {'command': 'kill 123'})['permissionDecision'], 'deny')
        self.write_config(self.project / '.claude/ioncache-ai-tools.local.json', {'disabledRules': [rule]})
        self.assertEqual(self.tool('bash', {'command': 'kill 123'}), {})
        self.write_config(local_path, {'disabledRules': ['fix_emdash']})
        self.assertEqual(self.tool('create', {'path': 'x', 'file_text': EM_DASH}), {})

    def test_malformed_copilot_config_logs_and_keeps_rules_running(self):
        config = self.home / '.copilot/ioncache-ai-tools.local.json'
        config.parent.mkdir()
        config.write_text('{bad')
        output, stderr = self.invoke('preToolUse', toolName='bash', toolArgs={'command': 'kill 123'})
        self.assertEqual(output['permissionDecision'], 'deny')
        self.assertIn('failed to read', stderr)

    def test_stop_checks_only_current_root_response(self):
        events = self.transcript_events('clean')
        events.insert(0, {'type': 'assistant.message', 'data': {'content': EM_DASH}})
        events.insert(-1, {'type': 'assistant.message', 'agentId': 'child', 'data': {'content': EM_DASH}})
        events.insert(-1, {'type': 'assistant.message', 'data': {'parentToolCallId': 'child', 'content': EM_DASH}})
        path = self.write_events(events)
        self.assertEqual(self.invoke('agentStop', transcriptPath=str(path))[0], {})
        path = self.write_events(self.transcript_events(f'bad{EM_DASH}text'))
        self.assertEqual(self.invoke('agentStop', transcriptPath=str(path))[0]['decision'], 'block')

    def test_stop_waits_for_async_transcript_flush(self):
        path = self.write_events([])
        def flush():
            time.sleep(0.15)
            self.write_events(self.transcript_events('flushed response'))
        writer = threading.Thread(target=flush)
        writer.start()
        try:
            self.assertEqual(self.invoke('agentStop', transcriptPath=str(path))[0], {})
        finally:
            writer.join()

    def test_stop_accepts_corrected_response_after_a_block(self):
        old_events = self.transcript_events(EM_DASH)
        old_events[-1]['data']['input'] = {**self.payload, 'timestamp': 123455}
        corrected = [
            {'type': 'assistant.turn_start', 'data': {'turnId': 'correction'}},
            {'type': 'assistant.message', 'data': {'content': 'corrected text'}},
            {'type': 'hook.start', 'data': {'hookType': 'agentStop', 'input': self.payload}},
        ]
        path = self.write_events(old_events + corrected)
        self.assertEqual(self.invoke('agentStop', transcriptPath=str(path), stop_hook_active=True)[0], {})

    def test_stop_does_not_accept_previous_invocation(self):
        events = self.transcript_events('stale response')
        events[-1]['data']['input'] = {**self.payload, 'timestamp': 123455}
        path = self.write_events(events)
        with mock.patch.object(copilot_adapter, 'TRANSCRIPT_WAIT_SECONDS', 0.05):
            with self.assertRaises(TimeoutError):
                copilot_adapter.final_response({**self.payload, 'transcriptPath': str(path)})

    def test_session_end_cleans_its_own_marker(self):
        self.prompt('why is this different')
        self.assertTrue(self.marker.exists())
        self.assertEqual(self.invoke('sessionEnd')[0], {})
        self.assertFalse(self.marker.exists())

    def test_invalid_input_fails_visibly(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / 'hooks/scripts/copilot_adapter.py'), 'preToolUse'],
            input=json.dumps({**self.payload, 'toolName': 'apply_patch', 'toolArgs': 'malformed'}),
            text=True, capture_output=True, env=self.env, timeout=10,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('no recognized file headers', result.stderr)

    def test_shared_hook_failure_is_not_silently_ignored(self):
        failure = subprocess.CompletedProcess(['python3', 'hook.py'], 1, '', 'fixture failure\n')
        with mock.patch.object(hook_adapter_common.subprocess, 'run', return_value=failure):
            with mock.patch('sys.stderr') as stderr:
                with self.assertRaises(RuntimeError):
                    hook_adapter_common.run_shared_hooks('PreToolUse', {
                        'cwd': str(self.project), 'tool_name': 'Read', 'tool_input': {},
                    })
                stderr.write.assert_any_call('fixture failure\n')


if __name__ == '__main__':
    unittest.main()
