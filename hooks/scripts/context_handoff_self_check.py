#!/usr/bin/env python3
"""Offline regressions for the Claude Code context handoff hooks and status line."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import uuid

import context_handoff
import plugin_config as config
from classify_question import marker_path
from hook_adapter_common import run_shared_hooks
from turn_guard_self_check import install_reviewers

SCRIPTS = Path(__file__).resolve().parent
HOOK = SCRIPTS / 'context_handoff.py'


class ContextHandoffTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.project = self.root / 'project'
        self.project.mkdir()
        self.plugin_data = self.root / 'plugin-data'
        patcher = mock.patch.dict(os.environ, {
            'HOME': str(self.root / 'home'), 'CODEX_HOME': str(self.root / 'codex'),
            'COPILOT_HOME': str(self.root / 'copilot'), 'XDG_CACHE_HOME': str(self.root / 'cache'),
            'CLAUDE_PLUGIN_DATA': str(self.plugin_data), context_handoff.THRESHOLD_ENV: '75',
            'IONCACHE_DOCS_DISTILLER': '', 'PYTHONDONTWRITEBYTECODE': '1',
            'PATH': install_reviewers(self.root),
            # Any scope review that runs denies, so only exempt calls pass.
            'REVIEW_FIXTURE_RESULT': '{"ok": false, "reason": "Not authorized by the user."}',
        })
        patcher.start()
        self.addCleanup(patcher.stop)
        self.data = self.session()
        self.handoff = self.plugin_data / 'handoffs' / f'{self.data["session_id"]}.md'

    def session(self):
        data = {'cwd': str(self.project), 'session_id': f'handoff-check-{uuid.uuid4()}'}
        self.addCleanup(lambda: marker_path(data).unlink(missing_ok=True))
        self.addCleanup(lambda: marker_path(data, 'prompt').unlink(missing_ok=True))
        return data

    def hook(self, event, data=None, **fields):
        result = subprocess.run(
            [sys.executable, '-B', str(HOOK), event], input=json.dumps({**(data or self.data), **fields}),
            capture_output=True, text=True, cwd=self.project,
        )
        output = json.loads(result.stdout) if result.stdout.strip() else None
        return result.returncode, output, result.stderr

    def output(self, event, data=None, **fields):
        code, output, stderr = self.hook(event, data, **fields)
        self.assertEqual(code, 0, stderr)
        return output

    def shared(self, event, **fields):
        return run_shared_hooks(event, {**self.data, **fields})

    def statusline(self, percent, session=None):
        self.output('SessionStart', source='startup')
        payload = {
            'session_id': session or self.data['session_id'], 'cwd': str(self.project),
            'model': {'display_name': 'Opus'},
            'context_window': {'used_percentage': percent, 'context_window_size': 200000},
        }
        result = subprocess.run(
            [sys.executable, '-B', str(self.plugin_data / 'statusline.py')],
            input=json.dumps(payload), capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()

    def disable(self, *features):
        path = config.paths(self.project)['claude'][0]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'features': {name: False for name in features}}))

    def assert_denied(self, outputs, text):
        decisions = [output.get('hookSpecificOutput', {}) for output in outputs]
        self.assertTrue(any(item.get('permissionDecision') == 'deny' and text in item['permissionDecisionReason']
                            for item in decisions), outputs)

    def test_statusline_copy_records_usage_beside_itself_and_keeps_last_known_value(self):
        self.assertEqual(self.statusline(42), '[Opus] ctx 42%')
        source = (SCRIPTS / 'context_statusline.py').read_text()
        self.assertEqual((self.plugin_data / 'statusline.py').read_text(), source)
        usage = self.plugin_data / 'context' / f'{self.data["session_id"]}.json'
        self.assertEqual(json.loads(usage.read_text())['used_percentage'], 42)
        self.assertEqual(self.statusline(None), '[Opus] ctx --')
        self.assertEqual(json.loads(usage.read_text())['used_percentage'], 42)
        self.assertIn('status line error', self.statusline(50, session='../escape'))
        self.assertFalse((self.plugin_data / 'escape.json').exists())
        (self.plugin_data / 'statusline.py').write_text('stale copy from an older plugin version')
        self.output('SessionStart', source='resume')
        self.assertEqual((self.plugin_data / 'statusline.py').read_text(), source)

    def test_below_threshold_leaves_work_alone(self):
        self.statusline(74)
        self.assertIsNone(self.output('UserPromptSubmit', prompt='Implement the change'))
        self.assertIsNone(self.output('PreToolUse', tool_name='Bash', tool_input={'command': 'ls'}))
        self.assertIsNone(self.output('PostToolUse', tool_name='Bash', tool_input={'command': 'ls'},
                                      tool_response={'exit_code': 0}))
        self.assertIsNone(self.output('Stop', stop_hook_active=False))

    def test_threshold_forces_handoff_then_halts_and_resumes_once(self):
        self.statusline(80)
        prompt = self.shared('UserPromptSubmit', prompt='Implement the change')
        self.assertIn(f'with the Write tool to {self.handoff}', str(prompt))
        self.assertIn('Load the ioncache-ai-tools:context-handoff skill', str(prompt))
        self.assert_denied(self.shared('PreToolUse', tool_name='Bash', tool_input={'command': 'ls'}),
                           'Context handoff required: context usage is 80%')
        self.assert_denied([self.output('PreToolUse', tool_name='Write',
                                        tool_input={'file_path': str(self.project / 'x.py'), 'content': 'x'})],
                           str(self.handoff))
        self.assertEqual(self.shared('PreToolUse', tool_name='Skill',
                                     tool_input={'skill': 'ioncache-ai-tools:context-handoff'}), [])
        write = {'tool_name': 'Write', 'tool_input': {'file_path': str(self.handoff), 'content': '# Goal\nShip it.'}}
        # The scope reviewer fixture denies every reviewed call, so passing proves the exemption.
        self.assertEqual(self.shared('PreToolUse', **write), [])

        self.handoff.parent.mkdir(parents=True, exist_ok=True)
        self.handoff.write_text('# Goal\nShip it.')
        halted = self.output('PostToolUse', **write, tool_response={'filePath': str(self.handoff)})
        self.assertEqual(halted, {
            'continue': False,
            'stopReason': f'Handoff saved to {self.handoff}. Type /clear, then send any message '
                          'to continue in a fresh session.',
        })
        self.assertIsNone(self.output('PreToolUse', tool_name='Bash', tool_input={'command': 'ls'}))
        self.assertIsNone(self.output('Stop', stop_hook_active=False))

        resumed = self.output('SessionStart', self.session(), source='clear')
        text = resumed['hookSpecificOutput']['additionalContext']
        self.assertIn('Act on it when the user sends their first message', text)
        self.assertIn(str(self.handoff), text)
        self.assertIn('<handoff>\n# Goal\nShip it.\n</handoff>', text)
        self.assertIsNone(self.output('SessionStart', self.session(), source='startup'))
        self.assertEqual(self.handoff.read_text(), '# Goal\nShip it.')

    def test_resume_and_compact_starts_do_not_consume_a_pending_handoff(self):
        self.handoff.parent.mkdir(parents=True)
        self.handoff.write_text('handoff')
        self.output('PostToolUse', tool_name='Write', tool_input={'file_path': str(self.handoff), 'content': 'x'},
                    tool_response={})
        for source in ('resume', 'compact'):
            self.assertIsNone(self.output('SessionStart', self.session(), source=source))
        other = {**self.session(), 'cwd': str(self.root)}
        self.assertIsNone(self.output('SessionStart', other, source='startup'))
        self.assertIn('handoff', str(self.output('SessionStart', self.session(), source='startup')))

    def test_missing_handoff_file_reports_and_keeps_the_pending_record(self):
        self.handoff.parent.mkdir(parents=True)
        self.handoff.write_text('handoff')
        self.output('PostToolUse', tool_name='Write', tool_input={'file_path': str(self.handoff), 'content': 'x'},
                    tool_response={})
        self.handoff.unlink()
        output = self.output('SessionStart', self.session(), source='clear')
        self.assertIn('context handoff failed: FileNotFoundError', output['systemMessage'])
        self.assertEqual(len(list((self.plugin_data / 'pending').glob('*.json'))), 1)

    def test_question_turn_allows_only_the_handoff_write(self):
        self.statusline(90)
        self.shared('UserPromptSubmit', prompt='Why did the build fail?')
        write = {'tool_name': 'Write', 'tool_input': {'file_path': str(self.handoff), 'content': 'handoff'}}
        self.assertEqual(self.shared('PreToolUse', **write), [])
        self.assert_denied(self.shared('PreToolUse', tool_name='Write',
                                       tool_input={'file_path': 'notes.md', 'content': 'x'}),
                           'classified as a question')

    def test_post_tool_and_stop_redirect_to_the_handoff_with_bounded_stops(self):
        self.statusline(75)
        post = self.output('PostToolUse', tool_name='Read', tool_input={'file_path': 'a'}, tool_response='text')
        self.assertEqual(post['decision'], 'block')
        self.assertIn(str(self.handoff), post['reason'])
        self.assertIsNone(self.output('PostToolUse', tool_name='Skill',
                                      tool_input={'skill': 'context-handoff'}, tool_response={}))
        stop = self.output('Stop', stop_hook_active=False)
        self.assertEqual(stop['decision'], 'block')
        self.assertIn(str(self.handoff), stop['reason'])
        repeat = self.output('Stop', stop_hook_active=True)
        self.assertNotIn('decision', repeat)
        self.assertIn('Send any message to have Claude write it', repeat['systemMessage'])
        self.assertIn('context handoff required', str(self.output('UserPromptSubmit', prompt='ok')).lower())

    def test_precompact_is_blocked_only_for_claude_main_sessions_with_the_feature_enabled(self):
        code, output, stderr = self.hook('PreCompact', trigger='manual')
        self.assertEqual((code, output), (2, None))
        self.assertIn('Compaction is disabled by ioncache-ai-tools', stderr)
        self.assertIn('/ioncache-ai-tools:context-handoff', stderr)
        for fields in ({'_ioncache_harness': 'codex'}, {'agent_id': 'child'}):
            self.assertEqual(self.hook('PreCompact', **fields)[0], 0)
        self.disable('context-handoff')
        self.assertEqual(self.hook('PreCompact', trigger='auto')[0], 0)

    def test_subagents_and_other_hosts_are_not_enforced(self):
        self.statusline(95)
        for fields in ({'agent_id': 'child', 'agent_type': 'Explore'}, {'_ioncache_harness': 'copilot'}):
            with self.subTest(fields=fields):
                self.assertIsNone(self.output('PreToolUse', tool_name='Bash', tool_input={'command': 'ls'}, **fields))
                self.assertIsNone(self.output('Stop', stop_hook_active=False, **fields))

    def test_feature_opt_out_disables_enforcement_and_the_scope_exemption(self):
        self.statusline(95)
        self.disable('context-handoff')
        self.assertIsNone(self.output('UserPromptSubmit', prompt='Implement the change'))
        self.assertIsNone(self.output('PreToolUse', tool_name='Bash', tool_input={'command': 'ls'}))
        self.shared('UserPromptSubmit', prompt='Implement the change')
        self.assert_denied(self.shared('PreToolUse', tool_name='Write',
                                       tool_input={'file_path': str(self.handoff), 'content': 'x'}),
                           'Not authorized by the user.')

    def test_disabled_skill_states_the_handoff_requirements_inline(self):
        self.statusline(80)
        self.disable('skill:context-handoff')
        output = self.output('UserPromptSubmit', prompt='Implement the change')
        text = output['hookSpecificOutput']['additionalContext']
        self.assertNotIn('Load the', text)
        self.assertIn('every user instruction quoted verbatim', text)
        self.assertIn(str(self.handoff), text)

    def test_missing_status_line_is_reported_once_after_the_first_response(self):
        self.output('SessionStart', source='startup')
        self.assertIsNone(self.output('UserPromptSubmit', prompt='Implement the change'))
        self.assertIsNone(self.output('PostToolUse', tool_name='Read', tool_input={}, tool_response='x'))
        self.assertIsNone(self.output('Stop', stop_hook_active=False))
        notice = self.output('UserPromptSubmit', prompt='Continue')['systemMessage']
        self.assertIn(f'/statusline Use the command: python3 "{self.plugin_data / "statusline.py"}"', notice)
        self.assertIsNone(self.output('PostToolUse', tool_name='Read', tool_input={}, tool_response='x'))
        self.assertIsNone(self.output('UserPromptSubmit', prompt='Continue'))

    def test_configuration_failures_are_reported_without_blocking_tools(self):
        self.statusline(80)
        for name, value, expected in (
                ('CLAUDE_PLUGIN_DATA', None, 'CLAUDE_PLUGIN_DATA is not set'),
                (context_handoff.THRESHOLD_ENV, None, f'{context_handoff.THRESHOLD_ENV} is not set'),
                (context_handoff.THRESHOLD_ENV, '100', 'must be between 1 and 99')):
            env = {**os.environ}
            env.pop(name)
            if value is not None:
                env[name] = value
            with self.subTest(name=name, value=value), mock.patch.dict(os.environ, env, clear=True):
                output = self.output('PreToolUse', tool_name='Bash', tool_input={'command': 'ls'})
                self.assertEqual(set(output), {'systemMessage'})
                self.assertIn(expected, output['systemMessage'])


if __name__ == '__main__':
    unittest.main()
