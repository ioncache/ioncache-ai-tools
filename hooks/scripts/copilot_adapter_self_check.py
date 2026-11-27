#!/usr/bin/env python3
"""Run all checks, or pass CopilotAdapterTests.test_name for one test."""
import copy
import io
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
import uuid
from contextlib import nullcontext

import copilot_adapter
import copilot_history
import copilot_question
import docs_cache
import guidance
import hook_adapter_common
import plugin_config
import plugin_settings
from classify_question import marker_path
from pending_question_self_check import CLAUDE_BATCH, QUESTION_FIXTURES, RECORDED_CLAUDE
from turn_guard_self_check import install_reviewers

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
import pytest
from self_check_support import inprocess_hooks, run_main, uses_process

EM_DASH = chr(0x2014)
NATIVE_QUESTION_EVENTS = json.loads((ROOT / 'hooks/fixtures/copilot-question-events.json').read_text())


class CopilotAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='copilot-adapter-check-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'project with spaces'
        self.project.mkdir()
        self.home = self.root / 'home'
        self.home.mkdir()
        self.write_config(self.home / '.claude/ioncache-ai-tools.local.json', {'features': {}})
        self.env = {
            **os.environ,
            'HOME': str(self.home),
            'COPILOT_HOME': str(self.home / '.copilot'),
            'CODEX_HOME': str(self.home / '.codex'),
            'XDG_CACHE_HOME': str(self.home / '.cache'),
            'PYTHONDONTWRITEBYTECODE': '1',
            'PATH': install_reviewers(self.root),
        }
        patcher = mock.patch.dict(os.environ, self.env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.progress = []
        self.payload = {
            'sessionId': f'self-check-{uuid.uuid4()}',
            'cwd': str(self.project),
            'timestamp': 123456,
        }
        self.marker = Path(f'/tmp/.ioncache-pending-question-copilot-{self.payload["sessionId"]}')
        self.addCleanup(lambda: self.marker.unlink(missing_ok=True))
        pending = marker_path(copilot_adapter.shared_input(self.payload), 'prompt')
        self.addCleanup(lambda: pending.unlink(missing_ok=True))

    def invoke(self, event, **fields):
        process = uses_process(self)
        with nullcontext() if process else inprocess_hooks():
            result = run_main(
                copilot_adapter, [event], input=json.dumps({**self.payload, **fields}),
                env=self.env, cwd=self.root, process=process,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        outputs = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        self.progress.extend(item['message'] for item in outputs if item.get('type') == 'progress')
        decisions = [item for item in outputs if item.get('type') != 'progress']
        self.assertLessEqual(len(decisions), 1)
        return decisions[0] if decisions else {}, result.stderr

    def prompt(self, prompt):
        return self.invoke('userPromptTransformed', prompt=prompt, transformedPrompt='expanded prompt')[0]

    def verified_question(self, prompt):
        # This exercises the shared contract, not an origin signal supplied by Copilot.
        return guidance.run_hook('UserPromptSubmit', {
            **copilot_adapter.shared_input(self.payload),
            '_ioncache_prompt_origin': 'user', 'prompt': prompt,
        })

    def tool(self, name, args):
        return self.invoke('preToolUse', toolName=name, toolArgs=args)[0]

    def write_config(self, path, config):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config))

    def test_settings_skill_opt_out_retains_helper_recovery_and_other_guards(self):
        skill = {'skill': 'ioncache-ai-tools:plugin-settings'}
        self.assertEqual(self.tool('skill', skill), {})
        result = run_main(plugin_settings, ['--skill:plugin-settings=disabled'],
                          cwd=self.project, env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.tool('skill', skill)['permissionDecision'], 'deny')
        self.assertEqual(self.tool('bash', {'command': 'pkill fixture'})['permissionDecision'], 'deny')
        command = shlex.join([sys.executable, str(plugin_settings.__file__),
                              '--project', str(self.project), '--skill:plugin-settings=enabled'])
        self.assertEqual(self.tool('bash', {'command': command}), {})
        result = run_main(plugin_settings, ['--skill:plugin-settings=enabled'],
                          cwd=self.project, env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.tool('skill', skill), {})
        self.assertEqual(self.tool('bash', {'command': 'pkill fixture'})['permissionDecision'], 'deny')

    def test_project_alias_opt_out_survives_older_catalog_hooks(self):
        link = self.root / 'project-link'
        link.symlink_to(self.project, target_is_directory=True)
        self.payload['cwd'] = str(link)
        command = {'command': 'pkill fixture'}
        self.assertEqual(self.tool('bash', command)['permissionDecision'], 'deny')
        path = self.home / '.claude/ioncache-ai-tools.local.json'
        self.write_config(path, {'features': {}, 'projects': {
            str(self.project.resolve()): {'features': {'no_broad_process_kill': False}},
        }})
        self.assertEqual(self.tool('bash', command), {})
        older = {name: value for name, value in plugin_config.defaults().items()
                 if name != 'no_broad_process_kill'}
        with mock.patch.object(plugin_config, 'defaults', return_value=older):
            self.assertEqual(self.tool('bash', {'command': 'printf fixture'}), {})
        self.assertEqual(self.tool('bash', command), {})
        self.assertEqual(self.tool('bash', {'command': 'git worktree add /tmp/new'})['permissionDecision'], 'deny')
        self.write_config(path, {'features': {}})
        self.assertEqual(self.tool('bash', command)['permissionDecision'], 'deny')
        self.assertEqual(self.tool('bash', {'command': 'kill -TERM 12345'}), {})

    def native_history(self, *groups):
        events = [event for group in groups for event in NATIVE_QUESTION_EVENTS[group]]
        content = '\n'.join(json.dumps(event) for event in events) + '\n'
        content = content.replace('capture-root', self.payload['sessionId'])
        path = self.home / '.copilot/session-state' / self.payload['sessionId'] / 'events.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def test_native_user_question_blocks_only_the_main_session(self):
        self.prompt(NATIVE_QUESTION_EVENTS['question'][0]['data']['input']['prompt'])
        self.native_history('question', 'children', 'handbacks')
        self.assertEqual(self.tool('create', {'path': 'main.txt', 'file_text': 'no'}).get('permissionDecision'),
                         'deny')
        self.assertEqual(self.tool('stop_agent', {'agent_id': 'worker'}).get('permissionDecision'), 'deny')
        self.assertEqual(self.tool('view', {'path': 'main.txt'}), {})
        self.assertEqual(self.tool('read_agent', {'agent_id': 'worker'}), {})
        for identity in ({'agentId': 'child', 'parentAgentId': self.payload['sessionId']},
                         {'sessionId': self.payload['sessionId'] + '-child', 'agentId': 'child',
                          'parentAgentId': self.payload['sessionId']}):
            output, _ = self.invoke('preToolUse', **identity, toolName='create',
                                    toolArgs={'path': 'child.txt', 'file_text': 'continued'})
            self.assertEqual(output, {})
        self.assertEqual(self.tool('task', {'prompt': 'Continue work'}).get('permissionDecision'), 'deny')
        self.native_history('question', 'answered', 'handbacks')
        command = 'printf continued > continued.txt'
        self.assertEqual(self.tool('bash', {'command': command}), {})
        subprocess.run(command, shell=True, cwd=self.project, env=self.env, check=True, timeout=5)
        self.assertEqual((self.project / 'continued.txt').read_text(), 'continued')
        self.native_history('question', 'instruction', 'children', 'handbacks')
        self.assertEqual(self.tool('task', {'prompt': 'Continue work'}), {})

    def test_native_non_user_sources_never_create_a_question_restriction(self):
        path = self.native_history('question')
        question = [json.loads(line) for line in path.read_text().splitlines()]
        variants = [{'source': source} for source in
                    ('agent-parent', 'automation-check', 'schedule-1', 'system', 'autopilot', 'memory', '')]
        variants += [{'agentAuthored': True}, {'isAutopilotContinuation': True}]
        for metadata in variants:
            with self.subTest(metadata=metadata):
                events = copy.deepcopy(question)
                events[-1]['data'].update(metadata)
                path.write_text('\n'.join(json.dumps(event) for event in events) + '\n')
                self.assertEqual(self.tool('create', {'path': 'continued.txt', 'file_text': 'yes'}), {})
        self.native_history('question', 'autopilot', 'children', 'handbacks')
        self.assertEqual(self.tool('stop_agent', {'agent_id': 'worker'}), {})

    def test_native_question_evidence_failures_do_not_reuse_an_old_question(self):
        path = self.native_history('question')
        question = path.read_text()
        self.marker.write_text('')
        pending = copy.deepcopy(NATIVE_QUESTION_EVENTS['instruction'][0])
        pending['data']['input']['sessionId'] = self.payload['sessionId']
        for suffix in ('{incomplete', '{invalid}\n', json.dumps(pending) + '\n'):
            with self.subTest(suffix=suffix):
                path.write_text(question + suffix)
                self.assertEqual(self.tool('create', {'path': 'continued.txt', 'file_text': 'yes'}), {})
                self.assertEqual(self.tool('bash', {'command': 'pkill fixture'})['permissionDecision'], 'deny')
        path.unlink()
        path.symlink_to(self.project / 'missing-history')
        self.assertEqual(self.tool('stop_agent', {'agent_id': 'worker'}), {})

    def test_native_question_opt_out_and_new_instruction_recovery(self):
        self.native_history('question')
        self.assertEqual(self.tool('create', {'path': 'x', 'file_text': 'y'}).get('permissionDecision'), 'deny')
        self.write_config(self.home / '.claude/ioncache-ai-tools.local.json',
                          {'features': {'answer-questions': False}})
        self.assertEqual(self.tool('create', {'path': 'x', 'file_text': 'y'}), {})
        self.assertEqual(self.tool('bash', {'command': 'pkill fixture'})['permissionDecision'], 'deny')
        self.write_config(self.home / '.claude/ioncache-ai-tools.local.json',
                          {'features': {'answer-questions': True}})
        self.assertEqual(self.tool('create', {'path': 'x', 'file_text': 'y'}).get('permissionDecision'), 'deny')
        self.native_history('question', 'instruction')
        self.assertEqual(self.tool('create', {'path': 'x', 'file_text': 'y'}), {})

    def test_native_lifecycle_preserves_only_the_current_root_question(self):
        args = {'agent_id': 'assigned-worker'}
        for event, fields in (('preCompact', {}), ('sessionStart', {'source': 'resume'})):
            with self.subTest(event=event):
                self.native_history('question', 'children', 'handbacks')
                self.assertFalse(self.marker.exists())
                self.invoke(event, **fields)
                self.assertEqual(self.tool('stop_agent', args).get('permissionDecision'), 'deny')
                self.assertEqual(self.tool('read_agent', args), {})
                child, _ = self.invoke(
                    'preToolUse', sessionId=self.payload['sessionId'] + '-child',
                    agentId='child', parentAgentId=self.payload['sessionId'],
                    toolName='stop_agent', toolArgs=args,
                )
                self.assertEqual(child, {})
                for ending in ('instruction', 'answered'):
                    with self.subTest(ending=ending):
                        self.native_history('question', ending, 'children', 'handbacks')
                        self.invoke(event, **fields)
                        self.assertEqual(self.tool('stop_agent', args), {})
                self.assertFalse(self.marker.exists())

    def test_native_lifecycle_rechecks_replaced_history_without_stale_restrictions(self):
        args = {'agent_id': 'assigned-worker'}
        for event, fields in (('preCompact', {}), ('sessionStart', {'source': 'resume'})):
            with self.subTest(event=event):
                history = self.native_history('question')
                self.assertFalse(self.marker.exists())
                self.invoke(event, **fields)
                self.assertEqual(self.tool('stop_agent', args).get('permissionDecision'), 'deny')
                replacement = history.with_suffix('.replacement')
                replacement.write_text('\n'.join(
                    json.dumps(item) for item in NATIVE_QUESTION_EVENTS['handbacks']
                ) + '\n')
                replacement.replace(history)
                self.assertEqual(self.tool('stop_agent', args), {})
                self.assertEqual(self.tool('bash', {'command': 'pkill fixture'})['permissionDecision'], 'deny')
                self.native_history('question')
                self.assertEqual(self.tool('stop_agent', args).get('permissionDecision'), 'deny')
                self.assertFalse(self.marker.exists())

    def test_native_question_matches_user_origin_across_delivery_modes(self):
        path = self.native_history('question')
        question = [json.loads(line) for line in path.read_text().splitlines()]
        for delivery in ('idle', 'steering', 'queued'):
            with self.subTest(delivery=delivery):
                question[-1]['data'].update(source='user', delivery=delivery)
                path.write_text('\n'.join(json.dumps(event) for event in question) + '\n')
                self.assertEqual(self.tool('task', {'prompt': 'Change files'}).get('permissionDecision'), 'deny')

    def test_native_interactive_question_correlates_through_its_memory_context(self):
        path = self.native_history('interactive_question')
        self.assertEqual(self.tool('create', {'path': 'x', 'file_text': 'y'}).get('permissionDecision'), 'deny')
        self.assertEqual(self.tool('bash', {'command': 'cat seed.txt'}), {})
        events = [json.loads(line) for line in path.read_text().splitlines()]
        events[1]['data']['interactionId'] = 'another-interaction'
        path.write_text('\n'.join(json.dumps(event) for event in events) + '\n')
        self.assertEqual(self.tool('create', {'path': 'x', 'file_text': 'y'}), {})
        self.native_history('interactive_question', 'instruction', 'children', 'handbacks')
        self.assertEqual(self.tool('create', {'path': 'x', 'file_text': 'y'}), {})

    def test_native_history_budget_and_mismatched_message_fail_open(self):
        path = self.native_history('question')
        question = path.read_text()
        filler = json.dumps({'type': 'assistant.message', 'data': {'content': 'x' * 2000}}) + '\n'
        with mock.patch.object(copilot_question, 'MAX_HISTORY_BYTES', 1024):
            path.write_text(filler + question)
            self.assertEqual(self.tool('task', {'prompt': 'Change files'}).get('permissionDecision'), 'deny')
            path.write_text(question + filler)
            self.assertEqual(self.tool('task', {'prompt': 'Change files'}), {})
            self.assertTrue(any('history budget' in message for message in self.progress))
        events = [json.loads(line) for line in question.splitlines()]
        events[-1]['data']['content'] = 'Different displayed content'
        path.write_text('\n'.join(json.dumps(event) for event in events) + '\n')
        self.assertEqual(self.tool('task', {'prompt': 'Change files'}), {})
        self.assertTrue(any('do not match' in message for message in self.progress))

    def assert_available(self, groups, decision):
        self.progress.clear()
        self.native_history(*groups)
        output = self.tool('create', {'path': 'skill.txt', 'file_text': 'yes'})
        self.assertEqual(output.get('permissionDecision'), decision)
        self.assertFalse([message for message in self.progress if 'unavailable' in message])

    def test_native_skill_invocations_correlate_and_preserve_the_question_turn(self):
        for groups in (('question', 'skill_instruction'), ('skill_instruction_bare',),
                       ('question', 'skill_prompt_mode')):
            with self.subTest(groups=groups):
                self.assert_available(groups, None)
        self.assert_available(('instruction', 'path_question'), 'deny')
        self.assert_available(('instruction', 'skill_question'), 'deny')
        self.assertEqual(self.tool('view', {'path': 'skill.txt'}), {})
        self.assert_available(('question', 'skill_load_legacy'), 'deny')
        self.assertEqual(self.tool('bash', {'command': 'cat seed.txt'}), {})
        self.assert_available(('skill_question', 'instruction'), None)
        command = 'printf resumed > resumed.txt'
        self.assertEqual(self.tool('bash', {'command': command}), {})
        subprocess.run(command, shell=True, cwd=self.project, env=self.env, check=True, timeout=5)
        self.assertEqual((self.project / 'resumed.txt').read_text(), 'resumed')

    def test_native_skill_expansion_mismatches_report_unavailability(self):
        def replace_prompt(group, old, new):
            def change(events):
                hook = next(event for event in reversed(events) if event['type'] == 'hook.start')
                hook['data']['input']['prompt'] = hook['data']['input']['prompt'].replace(old, new)
            return group, change

        def replace_content(group, content):
            def change(events):
                events[-1]['data']['content'] = content
            return group, change

        cases = [
            replace_prompt('skill_instruction', 'ARGUMENTS: PR 86', 'ARGUMENTS: PR 87'),
            replace_prompt('skill_instruction', '\n\nARGUMENTS: PR 86 --post-comments', ''),
            replace_prompt('skill_instruction', '</skill-context>', '</skill-context>\n\nWhy?'),
            replace_prompt('skill_instruction', 'The user explicitly invoked', 'The agent invoked'),
            replace_content('skill_instruction', '/ioncache-ai-tools:other PR 86 --post-comments'),
            replace_content('skill_instruction_bare', '/ioncache-ai-tools:plugin-settings why?'),
            replace_content('skill_question', 'why are you assessing them? what does it say?'),
            replace_prompt('skill_question', '\n\nwhy are you', '\n\nwhy were you'),
        ]
        for index, (group, change) in enumerate(cases):
            with self.subTest(group=group, case=index):
                path = self.native_history('question', group)
                events = [json.loads(line) for line in path.read_text().splitlines()]
                change(events)
                path.write_text('\n'.join(json.dumps(event) for event in events) + '\n')
                self.progress.clear()
                self.marker.write_text('')
                self.assertEqual(self.tool('create', {'path': 'skill.txt', 'file_text': 'yes'}), {})
                self.assertTrue(any('do not match' in message for message in self.progress))
                self.assertEqual(self.tool('bash', {'command': 'pkill fixture'})['permissionDecision'], 'deny')

    def test_unverified_prompt_origins_release_existing_question_state(self):
        fixtures = json.loads((ROOT / 'hooks/fixtures/prompt-origins.json').read_text())['copilot']
        prompts = [item['payload'] for item in fixtures]
        report = 'Why did the test finish? What should happen next? Can the parent continue?'
        prompts += [
            {'prompt': report, 'transformedPrompt': report},
            {'prompt': report, 'transformedPrompt': '<system_notification>' + report + '</system_notification>'},
            {'prompt': report, 'transformedPrompt': report, '_ioncache_prompt_origin': 'user'},
        ]
        for payload in prompts:
            with self.subTest(payload=payload):
                fields = {**payload, 'sessionId': self.payload['sessionId'], 'cwd': str(self.project)}
                self.marker.write_text('')
                output, _ = self.invoke('userPromptTransformed', **fields)
                self.assertFalse(self.marker.exists())
                self.assertNotIn('Question turn:', str(output))
                self.assertIn('A user question asks for information, not action', str(output))
                self.assertIn('even for an existing assignment', str(output))
                self.assertIn('reports, notifications, or parent-written messages', str(output))
                self.assertEqual(self.tool('create', {'path': 'report.txt', 'file_text': 'continued'}), {})
                self.assertEqual(self.tool('task', {'prompt': 'Continue the assigned work'}), {})
                self.assertEqual(self.tool('bash', {'command': 'git status --short'}), {})
        command = 'printf continued > resumed.txt'
        self.assertEqual(self.tool('bash', {'command': command}), {})
        subprocess.run(command, shell=True, cwd=self.project, env=self.env, check=True, timeout=5)
        self.assertEqual((self.project / 'resumed.txt').read_text(), 'continued')

    def test_question_stop_control_preserves_read_only_recovery_and_child_work(self):
        args = {'agent_id': 'assigned-worker'}
        self.verified_question('Why have the workers not stopped?')
        denied = self.tool('stop_agent', args)
        self.assertEqual(denied.get('permissionDecision'), 'deny')
        self.assertIn('Read-only research remains available', denied['permissionDecisionReason'])
        self.assertEqual(self.tool('read_agent', args), {})
        self.assertEqual(self.tool('list_agents', {}), {})
        for identity in ({'agentId': 'child', 'parentAgentId': self.payload['sessionId']},
                         {'sessionId': self.payload['sessionId'] + '-child', 'agentId': 'child',
                          'parentAgentId': self.payload['sessionId']},
                         {'sessionId': self.payload['sessionId'] + '-independent'}):
            with self.subTest(identity=identity):
                output, _ = self.invoke('preToolUse', **identity, toolName='stop_agent', toolArgs=args)
                self.assertEqual(output, {})
        self.assertEqual(self.tool('stop_agent', args).get('permissionDecision'), 'deny')
        self.prompt('Stop the assigned worker')
        self.assertEqual(self.tool('stop_agent', args), {})

    def test_question_stop_control_opt_out_and_checker_failure(self):
        args = {'agent_id': 'assigned-worker'}
        settings = self.home / '.claude/ioncache-ai-tools.local.json'
        self.verified_question('Why have the workers not stopped?')
        self.assertEqual(self.tool('stop_agent', args).get('permissionDecision'), 'deny')
        self.write_config(settings, {'features': {'answer-questions': False}})
        self.assertTrue(self.marker.exists())
        self.assertEqual(self.tool('stop_agent', args), {})
        output = self.prompt('Why have the workers not stopped?')
        self.assertNotIn('A user question asks for information, not action', str(output))
        self.assertEqual(self.tool('stop_agent', args), {})
        self.assertEqual(self.tool('bash', {'command': 'pkill fixture'})['permissionDecision'], 'deny')
        self.write_config(settings, {'features': {'answer-questions': True}})
        self.verified_question('Why have the workers not stopped?')
        self.assertEqual(self.tool('stop_agent', args).get('permissionDecision'), 'deny')
        self.marker.unlink()
        self.marker.symlink_to(self.project / 'unavailable-marker')
        self.assertEqual(self.tool('stop_agent', args), {})
        self.assertTrue(any('pending-question checks unavailable' in item for item in self.progress))
        self.prompt('Continue the assignment')
        self.assertFalse(self.marker.is_symlink())
        self.assertEqual(self.tool('stop_agent', args), {})

    def test_incomplete_child_identity_cannot_clear_or_inherit_root_marker(self):
        self.verified_question('Why did this change?')
        output, _ = self.invoke('userPromptTransformed', parentAgentId='parent',
                                prompt='Why did this change?', transformedPrompt='Why did this change?')
        self.assertNotIn('Question turn:', str(output))
        self.assertTrue(self.marker.exists())
        self.assertEqual(self.invoke('preToolUse', parentAgentId='parent', toolName='create',
                                     toolArgs={'path': 'child.txt', 'file_text': 'continued'})[0], {})
        self.assertEqual(self.tool('create', {'path': 'root.txt', 'file_text': 'blocked'})['permissionDecision'],
                         'deny')

    def test_question_classifier_and_foreign_host_batches(self):
        for prompt, expected, note in QUESTION_FIXTURES:
            with self.subTest(case=note):
                self.verified_question(prompt)
                self.assertEqual(self.marker.exists(), expected)
                self.assertEqual(self.tool('task', {'prompt': 'Continue the work'}).get('permissionDecision'),
                                 'deny' if expected else None)
                self.assertEqual(self.tool('view', {'path': 'report.txt'}), {})
        # Claude transcript replays are unknown input here, not captured Copilot formats.
        for report in (RECORDED_CLAUDE['handback'], CLAUDE_BATCH):
            with self.subTest(report=report[:50]):
                self.verified_question('Why did it fail?')
                self.prompt(report + '\nCan the parent continue?')
                self.assertFalse(self.marker.exists())
                self.assertEqual(self.tool('task', {'prompt': 'Continue the work'}), {})
                self.assertEqual(self.tool('create', {'path': 'report.txt', 'file_text': 'continued'}), {})

    def test_prompt_origin_recovery_survives_settings_and_marker_failures(self):
        self.verified_question('Why did this change?')
        settings = self.home / '.claude/ioncache-ai-tools.local.json'
        settings.write_text('{bad')
        output, stderr = self.invoke('userPromptTransformed', prompt='Why did the worker finish?',
                                      transformedPrompt='Why did the worker finish?')
        self.assertIn('features paused', stderr)
        self.assertFalse(self.marker.exists())
        self.assertNotIn('Question turn:', str(output))
        self.assertEqual(self.tool('create', {'path': 'report.txt', 'file_text': 'continued'}), {})
        self.write_config(settings, {'features': {}})
        self.marker.symlink_to(self.project / 'unavailable-marker')
        self.assertEqual(self.tool('create', {'path': 'report.txt', 'file_text': 'continued'}), {})
        self.assertTrue(any('pending-question checks unavailable' in item for item in self.progress))
        self.prompt('Continue the assignment')
        self.assertEqual(self.tool('task', {'prompt': 'Continue the assignment'}), {})
        self.assertEqual(self.tool('bash', {'command': 'pkill fixture'})['permissionDecision'], 'deny')

    @pytest.mark.process
    def test_root_question_blocks_only_root_and_children_continue(self):
        self.write_config(self.home / '.claude/ioncache-ai-tools.local.json', {'features': {}})
        self.marker.write_text('')
        self.prompt('Implement the requested report with two independent workers')
        self.assertFalse(self.marker.exists(), 'a work instruction must clear an earlier question state')
        self.assertEqual(self.tool('task', {'prompt': 'Write the requested report'}), {})
        root = {}
        suffix = uuid.uuid4().hex
        workers = tuple({'sessionId': f'worker-{name}-{suffix}', 'agentId': f'worker-{name}',
                         'parentAgentId': self.payload['sessionId']} for name in ('a', 'b'))
        for worker in workers:
            for kind in ('question', 'prompt'):
                path = marker_path(copilot_adapter.shared_input({**self.payload, **worker}), kind)
                self.addCleanup(path.unlink, missing_ok=True)
            # Parent-written assignments are not user questions, even when phrased as one.
            self.invoke('userPromptTransformed', **worker,
                        prompt='What have you found?', transformedPrompt='What have you found?')
        self.verified_question('What have you found?')
        self.assertTrue(self.marker.exists())
        for event in ('preCompact', 'sessionStart'):
            self.invoke(event, **root, source='resume')
            denied = self.invoke('preToolUse', toolName='create',
                                 toolArgs={'path': 'report-root.txt', 'file_text': 'continued'})[0]
            self.assertEqual(denied['permissionDecision'], 'deny')
            self.assertIn('Read-only research remains available', denied['permissionDecisionReason'])
        for delegation in (('task', {'prompt': 'Finish the report'}),
                           ('bash', {'command': 'git commit -m "Finish the report"'})):
            self.assertEqual(self.tool(*delegation)['permissionDecision'], 'deny')
        self.assertEqual(self.tool('view', {'path': 'report-root.txt'}), {})
        self.assertEqual(self.tool('bash', {'command': 'git status --short'}), {})
        for index, worker in enumerate(workers):
            command = f'printf "continued" > report-{index}.txt'
            self.assertEqual(self.invoke('preToolUse', **worker, toolName='create',
                                         toolArgs={'path': f'report-{index}.txt', 'file_text': 'continued'})[0], {})
            self.assertEqual(self.invoke('preToolUse', **worker, toolName='bash',
                                         toolArgs={'command': command})[0], {})
            subprocess.run(command, shell=True, check=True, cwd=self.project, env=self.env, timeout=5)
            self.assertEqual((self.project / f'report-{index}.txt').read_text(), 'continued')
        self.prompt('Write the root report')
        self.assertEqual(self.tool('create', {'path': 'report-root.txt', 'file_text': 'continued'}), {})
        self.assertEqual(self.tool('task', {'prompt': 'Finish the report'}), {})
        self.assertFalse((self.home / '.cache/ioncache-ai-tools/claim-evidence').exists())

    def test_autonomous_skill_is_user_only_without_fencing_existing_work(self):
        for name in ('autonomous-development', 'ioncache-ai-tools:autonomous-development'):
            output = self.tool('skill', {'skill': name})
            self.assertEqual(output.get('permissionDecision'), 'deny')
            self.assertIn('ordinary tools', output['permissionDecisionReason'])
        self.assertEqual(self.tool('view', {'path': str(ROOT / 'skills/autonomous-development/SKILL.md')}), {})
        command = 'printf continued > continued.txt'
        self.assertEqual(self.tool('bash', {'command': command}), {})
        subprocess.run(command, shell=True, check=True, cwd=self.project, env=self.env, timeout=5)
        self.assertEqual((self.project / 'continued.txt').read_text(), 'continued')
        self.assertEqual(self.tool('skill', {'skill': 'review-code'}), {})
        self.assertEqual(self.tool('skill', {'skill': 'autonomous-development'})['permissionDecision'], 'deny')
        self.prompt('/ioncache-ai-tools:autonomous-development')
        self.assertEqual(self.tool('view', {'path': str(ROOT / 'skills/autonomous-development/SKILL.md')}), {})
        self.assertEqual(self.tool('skill', {'skill': 'autonomous-development'})['permissionDecision'], 'deny')
        self.write_config(self.home / '.claude/ioncache-ai-tools.local.json',
                          {'features': {'autonomous-development-explicit-only': False}})
        self.assertEqual(self.tool('skill', {'skill': 'autonomous-development'}), {})
        self.assertEqual(self.tool('bash', {'command': 'killall node'})['permissionDecision'], 'deny')

    def test_checker_failure_does_not_require_human_recovery(self):
        self.write_config(self.home / '.claude/ioncache-ai-tools.local.json', {'features': {}})
        data = {**self.payload, 'toolName': 'create', 'toolArgs': {'path': 'report.txt', 'file_text': 'x'}}
        with mock.patch.object(copilot_adapter, 'run_shared_hooks', side_effect=RuntimeError('checker unavailable')), \
                mock.patch.object(sys, 'stderr', io.StringIO()), \
                mock.patch.object(sys, 'stdout', io.StringIO()) as notices:
            self.assertIsNone(copilot_adapter.run_hook('preToolUse', data))
        self.assertIn('unavailable', notices.getvalue())
        self.assertNotIn('permissionDecision', notices.getvalue())
        self.assertIsNone(copilot_adapter.run_hook('preToolUse', data))
        self.assertEqual(self.tool('create', {'path': 'package-lock.json', 'file_text': '{}'})['permissionDecision'], 'deny')
        self.assertEqual(self.tool('bash', {'command': 'npm install --package-lock-only --ignore-scripts'}), {})

    @pytest.mark.process
    def test_lockfile_and_process_denials_have_executable_recovery(self):
        self.prompt('Update dependencies and clean up the test process')
        self.assertEqual(self.tool('create', {'path': 'package-lock.json', 'file_text': '{}'})['permissionDecision'], 'deny')
        package = '{"name":"autonomous-recovery-fixture","version":"1.0.0","private":true}'
        self.assertEqual(self.tool('create', {'path': 'package.json', 'file_text': package}), {})
        (self.project / 'package.json').write_text(package)
        command = 'npm install --package-lock-only --ignore-scripts --offline --no-audit --no-fund'
        self.assertEqual(self.tool('bash', {'command': command}), {})
        result = subprocess.run(command, shell=True, cwd=self.project, env=self.env,
                                text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.project / 'package-lock.json').is_file())
        self.assertEqual(self.tool('create', {'path': 'package-lock.json', 'file_text': '{}'})['permissionDecision'], 'deny')
        for prefix in ('', 'exec '):
            with self.subTest(prefix=prefix):
                broad = prefix + 'pkill fixture-worker'
                self.assertEqual(self.tool('bash', {'command': broad})['permissionDecision'], 'deny')
                worker = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], env=self.env)
                try:
                    self.assertIsNone(worker.poll())
                    command = f'{prefix}kill {worker.pid}'
                    self.assertEqual(self.tool('bash', {'command': command}), {})
                    subprocess.run(command, shell=True, check=True, cwd=self.project, env=self.env, timeout=5)
                    self.assertLess(worker.wait(timeout=5), 0)
                finally:
                    if worker.poll() is None:
                        worker.terminate()
                        worker.wait(timeout=5)
                self.assertEqual(self.tool('bash', {'command': broad})['permissionDecision'], 'deny')

    def test_worktree_denial_recovers_without_loading_a_skill(self):
        self.write_config(self.home / '.claude/ioncache-ai-tools.local.json',
                          {'features': {'skill:create-worktree': False}})
        subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=self.project, check=True, env=self.env)
        subprocess.run([
            'git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
            '-c', 'commit.gpgsign=false', 'commit', '--allow-empty', '-qm',
            'test: initialize fixture\n\nCo-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>',
        ], cwd=self.project, check=True, env=self.env)
        destination = self.root / 'recovered-worktree'
        args = ['-b', 'recovered', str(destination)]
        raw = shlex.join(['git', 'worktree', 'add', *args])
        denied = self.tool('bash', {'command': raw})
        self.assertEqual(denied['permissionDecision'], 'deny')
        self.assertIn(str(ROOT / 'scripts/create-worktree.py'), denied['permissionDecisionReason'])
        command = [sys.executable, str(ROOT / 'scripts/create-worktree.py'), *args]
        self.assertEqual(self.tool('bash', {'command': shlex.join(command)}), {})
        result = subprocess.run(command, cwd=self.project, env=self.env, text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((destination / '.git').is_file())


    def test_default_reads_do_not_need_a_command_or_tool_allowlist(self):
        self.write_config(self.home / '.claude/ioncache-ai-tools.local.json', {'features': {}})
        self.prompt('Inspect this checkout')
        (self.project / 'input.txt').write_text('inspection fixture\n')
        for command in (
            'find . -type f',
            f'{sys.executable} -c "from pathlib import Path; print(Path(\'input.txt\').read_text())"',
            'git --version',
        ):
            with self.subTest(command=command):
                self.assertEqual(self.tool('bash', {'command': command}), {})
                result = subprocess.run(command, shell=True, cwd=self.project, env=self.env,
                                        text=True, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
        for command in ('rg --files --hidden', 'node -e "console.log(process.cwd())"',
                        'gh pr view 123 --json title', 'project-inspector --summary'):
            self.assertEqual(self.tool('bash', {'command': command}), {})
        self.assertEqual(self.tool('new_provider_lookup', {'query': 'checkout status'}), {})
        self.assertEqual(self.tool('mcp__provider__get_record', {'id': '123'}), {})
        self.assertEqual(self.tool('mcp__provider__update_record', {'id': '123'}), {})
        self.assertEqual(self.tool('bash', {'command': 'touch report.txt'}), {})


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

    def completion_events(self, summary):
        events = self.transcript_events('Before completion.')
        events[2]['data']['toolRequests'] = [{'name': 'task_complete', 'toolCallId': 'finish'}]
        events.insert(-1, {'type': 'session.task_complete', 'data': {'summary': summary}})
        return events

    def test_manifest_reuses_shared_components(self):
        manifest = json.loads((ROOT / '.github/plugin/plugin.json').read_text())
        for path in ('.claude-plugin/plugin.json', '.codex-plugin/plugin.json'):
            other = json.loads((ROOT / path).read_text())
            self.assertEqual(manifest['name'], other['name'])
            self.assertEqual(manifest['version'], other['version'])
        self.assertNotIn('commands', manifest)
        self.assertEqual((ROOT / manifest['skills']).resolve(), ROOT / 'skills')
        hooks = json.loads((ROOT / manifest['hooks']).read_text())
        self.assertEqual(hooks['version'], 1)
        self.assertEqual(set(hooks['hooks']), {
            'userPromptTransformed', 'preToolUse', 'postToolUse', 'agentStop', 'sessionEnd',
            'sessionStart', 'preCompact', 'subagentStart', 'postToolUseFailure',
        })
        self.assertFalse((ROOT / 'skills/claim-evidence/SKILL.md').exists())
        for event, entries in hooks['hooks'].items():
            self.assertEqual(len(entries), 1)
            self.assertIn('${COPILOT_PLUGIN_ROOT}/hooks/scripts/copilot_adapter.py', entries[0]['bash'])
            self.assertTrue(entries[0]['bash'].endswith(event))

    def test_prompt_preserves_transformation_and_supplies_stateless_guidance(self):
        output = self.prompt('Implement the feature')
        text = output['modifiedTransformedPrompt']
        self.assertTrue(text.startswith('expanded prompt\n\n'))
        self.assertIn('documentation-backed', text)
        self.assertIn('ioncache-ai-tools', text)
        for name in ('engineering-judgment', 'scope-exactly-what-asked'):
            rule = json.loads((ROOT / f'hooks/rules/{name}.json').read_text())
            self.assertIn(rule['message'], text)
        self.assertIn('documentation-backed', str(self.prompt('Continue the feature')))

    def test_bounded_review_guidance_reaches_native_children_without_fences(self):
        for identity in ('parent-review', 'child-review'):
            native = {'sessionId': identity, 'agentId': identity}
            startup, _ = self.invoke('subagentStart', **native)
            self.assertIn('Assigned review workers and validators', str(startup))
            prompt, _ = self.invoke('userPromptTransformed', **native,
                                    prompt='Why?', transformedPrompt='Review only security')
            self.assertTrue(prompt['modifiedTransformedPrompt'].startswith('Review only security'))
            self.assertIn('do not load engineering-judgment, review-code', str(prompt))
            command = 'printf reviewed'
            self.assertEqual(self.invoke('preToolUse', **native, toolName='bash',
                                         toolArgs={'command': command})[0], {})
            result = subprocess.run(command, shell=True, cwd=self.project, env=self.env,
                                    check=True, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.stdout, 'reviewed')

    def test_tools_and_replies_do_not_launch_scope_reviewers(self):
        capture = self.root / 'unexpected-review.txt'
        self.env.update(REVIEW_FIXTURE_CAPTURE=str(capture), REVIEW_FIXTURE_ERROR='Reviewer unavailable')
        self.prompt('Post the review replies')
        command = {'command': 'git commit -m "Fix the requested issue"'}
        self.assertEqual(self.tool('bash', command), {})
        self.assertEqual(self.tool('task', {'prompt': 'Inspect the requested code'}), {})
        path = self.write_events(self.completion_events('The requested work is complete.'))
        self.assertEqual(self.invoke('agentStop', transcriptPath=str(path))[0], {})
        self.assertFalse(capture.exists())
        self.verified_question('Why did that change?')
        self.assertEqual(self.tool('bash', command)['permissionDecision'], 'deny')
        self.assertEqual(self.tool('view', {'path': 'source.py'}), {})
        self.prompt('Commit the requested fix')
        self.assertEqual(self.tool('bash', command), {})
        self.assertEqual(self.tool('bash', {'command': 'pkill worker'})['permissionDecision'], 'deny')
        self.assertFalse(capture.exists())


    def test_adapter_deadline_interrupts_prompt_hooks(self):
        def slow_hooks(*_):
            signal.setitimer(signal.ITIMER_REAL, 0.01)
            time.sleep(1)
            return []

        self.prompt('Implement the requested file')
        question = {**self.payload, 'prompt': 'Why?', 'transformedPrompt': 'Why?'}
        with (
            mock.patch.object(copilot_adapter, 'ADAPTER_TIMEOUT_SECONDS', 5),
            mock.patch.object(copilot_adapter, 'invocation_deadline',
                              wraps=copilot_adapter.invocation_deadline) as deadline,
            mock.patch.object(copilot_adapter, 'run_shared_hooks', side_effect=slow_hooks) as delayed_hooks,
            mock.patch.object(sys, 'stdout', io.StringIO()) as notices,
            mock.patch.object(sys, 'stderr', io.StringIO()),
        ):
            started = time.monotonic()
            self.assertIsNone(copilot_adapter.run_hook('userPromptTransformed', question))
            self.assertLess(time.monotonic() - started, 0.5)
        self.assertIn('invocation deadline', notices.getvalue())
        deadline.assert_called_once_with(5)
        delayed_hooks.assert_called_once()
        self.assertEqual(self.tool('create', {'path': 'x', 'file_text': 'y'}), {})

    def test_invocation_deadline_stops_handlers_and_preserves_completed_rewrites(self):
        rewrite = {'hookSpecificOutput': {
            'hookEventName': 'PreToolUse', 'updatedInput': {'content': 'a, b'},
        }}
        for completed, expected in (({}, None), (rewrite, {'modifiedArgs': {'path': 'x', 'file_text': 'a, b'}})):
            with self.subTest(completed=completed):
                def handler(*args, **kwargs):
                    if run.call_count == 1:
                        return subprocess.CompletedProcess(args[0], 0, json.dumps(completed), '')
                    signal.setitimer(signal.ITIMER_REAL, 0.01)
                    time.sleep(1)
                    return subprocess.CompletedProcess(args[0], 0, '', '')

                with (
                    mock.patch.object(hook_adapter_common.subprocess, 'run', side_effect=handler) as run,
                    mock.patch.object(docs_cache, 'copilot_pre') as cache,
                    mock.patch.object(sys, 'stdout', io.StringIO()) as notices,
                    mock.patch.object(sys, 'stderr', io.StringIO()),
                ):
                    output = copilot_adapter.run_hook('preToolUse', {
                        **self.payload, 'toolName': 'create', 'toolArgs': {'path': 'x', 'file_text': f'a{EM_DASH}b'},
                    })
                self.assertEqual(run.call_count, 2, 'No handler may start after invocation expiry')
                cache.assert_not_called()
                self.assertEqual(output, expected)
                self.assertIn('invocation deadline', notices.getvalue())
        self.assertEqual(self.tool('create', {'path': 'continued.txt', 'file_text': 'continued'}), {})
        self.assertEqual(self.tool('bash', {'command': 'pkill worker'})['permissionDecision'], 'deny')

    def test_invocation_deadline_escapes_native_cache_failure_recovery(self):
        def slow_cache(data):
            signal.setitimer(signal.ITIMER_REAL, 0.01)
            time.sleep(1)

        with (
            mock.patch.object(copilot_adapter, 'run_shared_hooks', return_value=[]),
            mock.patch.object(docs_cache, 'copilot_pre', side_effect=slow_cache),
            mock.patch.object(sys, 'stdout', io.StringIO()) as notices,
            mock.patch.object(sys, 'stderr', io.StringIO()),
        ):
            output = copilot_adapter.run_hook('preToolUse', {
                **self.payload, 'toolName': 'view', 'toolArgs': {'path': 'x'},
            })
        self.assertIsNone(output)
        self.assertIn('checks unavailable', notices.getvalue())
        self.assertIn('invocation deadline', notices.getvalue())
        self.assertNotIn('permissionDecision', notices.getvalue())


    def test_stop_does_not_collect_response_text(self):
        self.prompt('Why does this happen?')
        events = self.transcript_events('The final explanation.')
        events[2:2] = [
            {'type': 'assistant.message', 'data': {'content': 'Here is an unsolicited plan.', 'toolRequests': [{'name': 'view'}]}},
            {'type': 'assistant.turn_start', 'data': {'turnId': 'second'}},
        ]
        path = self.write_events(events)
        with mock.patch.object(copilot_adapter, 'run_shared_hooks', return_value=[]) as shared:
            copilot_adapter.run_hook('agentStop', {**self.payload, 'transcriptPath': str(path)})
        stop_input = next(call.args[1] for call in shared.call_args_list if call.args[0] == 'Stop')
        self.assertNotIn('last_assistant_message', stop_input)
        self.assertNotIn('Here is an unsolicited plan.', json.dumps(stop_input))


    def test_stop_excludes_execution_and_documentation_evidence(self):
        self.prompt('Run the tests and report the observed result')
        fields = {'toolName': 'bash', 'toolArgs': {'command': 'python3 -m unittest -q'}, 'toolCallId': 'tests'}
        self.invoke('preToolUse', **fields)
        self.invoke('postToolUse', **fields, toolResult={
            'resultType': 'success', 'textResultForLlm': 'Ran 205 tests\nOK',
        })
        for index in range(5):
            self.invoke('postToolUse', toolName='view', toolArgs={'path': f'{index}.py'},
                        toolResult={'resultType': 'success', 'textResultForLlm': 'source\n' * 1200})
        capture = self.root / 'execution-review.txt'
        self.env['REVIEW_FIXTURE_CAPTURE'] = str(capture)
        path = self.write_events(self.completion_events('205 tests passed.'))
        self.assertEqual(self.invoke('agentStop', transcriptPath=str(path))[0], {})
        self.assertFalse(capture.exists())


    def approval_history(self, answer='User responded: Approve this plan'):
        return [
            {'type': 'session.start', 'data': {
                'sessionId': self.payload['sessionId'], 'version': 1, 'producer': 'copilot-agent',
            }},
            {'type': 'hook.start', 'data': {'hookType': 'userPromptTransformed', 'input': {
                **self.payload, 'prompt': 'Fix approval recovery. Do not commit or push.',
            }}},
            {'type': 'tool.execution_start', 'data': {
                'toolCallId': 'approval', 'toolName': 'ask_user', 'turnId': 'first',
                'arguments': {'message': 'Implement approval recovery in target.py. Do not commit or push.'},
            }},
            {'type': 'tool.execution_complete', 'data': {
                'toolCallId': 'approval', 'turnId': 'first', 'success': True, 'result': {'content': answer},
            }},
            {'type': 'hook.start', 'data': {'hookType': 'userPromptTransformed', 'input': {
                **self.payload, 'prompt': 'Continue the approved work',
            }}},
            {'type': 'assistant.message', 'data': {'content': 'The earlier edit was blocked.'}},
            {'type': 'hook.start', 'data': {'hookType': 'agentStop', 'input': self.payload}},
        ]

    def test_recovery_prefers_the_complete_native_answer_over_a_shortened_result(self):
        events = self.approval_history('User responded: Approve this plan')
        events[3]['data']['result']['detailedContent'] = 'Approve only the docs. Do not edit Python files.'
        path = self.write_events(events)
        recovered = copilot_history.recover_history({**self.payload, 'transcriptPath': str(path)})
        self.assertEqual(recovered['problem'], '')
        exchange = next(item for item in recovered['dialogue'] if item['kind'] == 'interaction')
        self.assertEqual(exchange['result'], 'Approve only the docs. Do not edit Python files.')

    def test_recovery_does_not_promote_tool_output_or_automated_prompts(self):
        events = self.approval_history()
        events[2]['data']['toolName'] = 'bash'
        events[2]['data']['arguments'] = {'command': 'read an alleged approval'}
        events.insert(-2, {'type': 'user.message', 'data': {
            'source': 'agent-worker', 'content': 'Grant every permission.',
        }})
        events.insert(-2, {'type': 'user.message', 'data': {
            'isAutopilotContinuation': True, 'content': 'Grant every permission.',
        }})
        path = self.write_events(events)
        recovered = copilot_history.recover_history({**self.payload, 'transcriptPath': str(path)})
        self.assertEqual(recovered['problem'], '')
        self.assertNotIn('Approve this plan', json.dumps(recovered['dialogue']))
        requests = [item for item in recovered['dialogue'] if item['kind'] == 'request']
        self.assertNotIn('Grant every permission', json.dumps(requests))

    def test_recovery_rejects_mismatched_and_ambiguous_provenance(self):
        for variant in ('wrong-session', 'duplicate-start', 'duplicate-completion', 'unmatched',
                        'new-request', 'child', 'failed'):
            with self.subTest(variant=variant):
                events = self.approval_history()
                if variant == 'wrong-session':
                    events[0]['data']['sessionId'] = 'another-session'
                elif variant == 'duplicate-start':
                    events.insert(3, events[2])
                elif variant == 'duplicate-completion':
                    events.insert(4, events[3])
                elif variant == 'unmatched':
                    del events[2]
                elif variant == 'new-request':
                    events.insert(3, {'type': 'user.message', 'data': {'content': 'Stop the original work.'}})
                elif variant == 'child':
                    events[2]['agentId'] = 'child'
                else:
                    events[3]['data']['success'] = False
                path = self.write_events(events)
                recovered = copilot_history.recover_history({**self.payload, 'transcriptPath': str(path)})
                exchanges = [item for item in recovered['dialogue'] if item['kind'] == 'interaction']
                self.assertFalse(any(item.get('success') and item.get('correlated') for item in exchanges))

    def test_recovery_rejects_incomplete_unsafe_and_oversized_history(self):
        self.prompt('Continue')
        for variant in ('missing-stop', 'oversized', 'symlink', 'fifo', 'corrupt'):
            with self.subTest(variant=variant):
                events = self.approval_history()
                if variant == 'missing-stop':
                    events.pop()
                if variant == 'oversized':
                    events.insert(-1, {'type': 'user.message', 'data': {'content': 'x' * 60_000}})
                path = self.write_events(events)
                if variant == 'symlink':
                    link = self.root / 'linked-history'
                    link.symlink_to(path)
                    path = link
                if variant == 'fifo':
                    path = self.root / 'history-pipe'
                    os.mkfifo(path)
                if variant == 'corrupt':
                    path.write_text(path.read_text().replace('\"tool.execution_start\"', 'broken-json'))
                recovered = copilot_history.recover_history({**self.payload, 'transcriptPath': str(path)})
                self.assertEqual(recovered['dialogue'], [])
                self.assertTrue(recovered['problem'])


    def test_engineering_reminder_can_be_disabled_and_reenabled(self):
        name = 'engineering-judgment'
        rule = json.loads((ROOT / f'hooks/rules/{name}.json').read_text())
        scope = json.loads((ROOT / 'hooks/rules/scope-exactly-what-asked.json').read_text())
        self.write_config(self.home / '.copilot/ioncache-ai-tools.local.json', {'disabledRules': [name]})
        text = self.prompt('Implement the feature')['modifiedTransformedPrompt']
        self.assertNotIn(rule['message'], text)
        self.assertIn(scope['message'], text)
        self.write_config(self.project / '.github/copilot/ioncache-ai-tools.local.json', {'enabledRules': [name]})
        self.invoke('preCompact')
        self.assertIn(rule['message'], self.prompt('Implement the feature')['modifiedTransformedPrompt'])
        self.assertIn(rule['message'], str(self.prompt('Continue the feature')))


    def test_lifecycle_and_prompt_events_supply_guidance(self):
        output, _ = self.invoke('sessionStart', source='startup')
        self.assertIn('documentation-backed', output['additionalContext'])
        self.assertIn('documentation-backed', str(self.prompt('Implement the change')))
        self.assertIn('documentation-backed', str(self.invoke('sessionStart', source='resume')[0]))
        self.assertIn('documentation-backed', self.invoke('subagentStart', agentName='explore')[0]['additionalContext'])
        self.assertEqual(self.invoke('preCompact')[0], {})
        self.assertIn('documentation-backed', self.prompt('Continue')['modifiedTransformedPrompt'])

    def test_stop_does_not_retry_visible_text_or_clear_question_state(self):
        self.verified_question('Why is this different?')
        path = self.write_events(self.transcript_events(f'Bad{EM_DASH}punctuation.'))
        output = self.invoke('agentStop', transcriptPath=str(path))[0]
        self.assertEqual(output, {})
        self.assertTrue(self.marker.exists())
        self.assertEqual(self.tool('create', {'path': 'x', 'file_text': 'y'})['permissionDecision'], 'deny')
        self.write_events(self.transcript_events('Corrected punctuation.'))
        self.assertEqual(self.invoke('agentStop', transcriptPath=str(path), stop_hook_active=True)[0], {})
        self.prompt('Create the file')
        self.assertEqual(self.tool('create', {'path': 'x', 'file_text': 'y'}), {})

    def test_web_fetch_served_from_docs_cache_and_corruption_recovers(self):
        url = 'https://git-scm.com/docs/git-commit'
        args = json.dumps({'url': url, 'max_length': 20000})
        self.assertEqual(self.tool('web_fetch', args), {})
        entries = self.home / '.cache/ioncache-ai-tools/docs-cache/entries'
        key = docs_cache.cache_key(url, None)
        (entries / f'{key}.json').write_text(json.dumps({'url': url, 'facts': [
            {'fact': 'cached fixup fact', 'fetched_at': time.time(),
             'harness': 'copilot', 'length': 20000}]}))
        denied = self.tool('web_fetch', args)
        self.assertEqual(denied['permissionDecision'], 'deny')
        self.assertIn('cached fixup fact', denied['permissionDecisionReason'])
        self.assertEqual(self.tool('web_fetch', args), {}, 'repeat must fetch live')
        (entries / f'{key}.json').write_text(json.dumps({'facts': [{'fetched_at': 'bad'}]}))
        output, stderr = self.invoke('preToolUse', toolName='web_fetch', toolArgs=args)
        self.assertEqual(output, {})
        self.assertEqual(stderr, '')
        self.assertFalse((entries / f'{key}.json').exists())

    def test_docs_cache_io_errors_still_fail_open(self):
        url = 'https://git-scm.com/docs/git-commit'
        entries = self.home / '.cache/ioncache-ai-tools/docs-cache/entries'
        (entries / f'{docs_cache.cache_key(url, None)}.json').mkdir(parents=True)
        output, stderr = self.invoke('preToolUse', toolName='web_fetch',
                                     toolArgs={'url': url, 'max_length': 20000})
        self.assertEqual(output, {})
        self.assertIn('docs-cache:', stderr)

    def test_docs_cache_problem_uses_display_only_progress_once(self):
        status = self.home / '.cache/ioncache-ai-tools/docs-cache/distill-status.json'
        status.parent.mkdir(parents=True)
        status.write_text(json.dumps({'problem': 'Not logged in', 'ts': time.time()}))
        payload = {'toolName': 'bash', 'toolArgs': {'command': 'true'},
                   'toolResult': {'resultType': 'success', 'textResultForLlm': ''}}
        output, stderr = self.invoke('postToolUse', **payload)
        self.assertEqual(output, {})
        notice = self.progress[-1]
        self.assertIn('Not logged in', notice)
        self.assertEqual(stderr, '')
        path = self.write_events(self.transcript_events('Fetch completed.'))
        self.assertEqual(self.invoke('agentStop', transcriptPath=str(path))[0], {})
        self.assertEqual(self.invoke('postToolUse', **payload)[0], {})
        self.assertEqual(self.progress, [notice])

    @pytest.mark.process
    def test_docs_cache_deduplication_survives_processes_and_user_turns(self):
        status = self.home / '.cache/ioncache-ai-tools/docs-cache/distill-status.json'
        status.parent.mkdir(parents=True)
        status.write_text(json.dumps({'problem': 'Not logged in', 'ts': time.time()}))
        payload = {'toolName': 'bash', 'toolArgs': {'command': 'true'},
                   'toolResult': {'resultType': 'success', 'textResultForLlm': ''}}
        self.invoke('postToolUse', **payload)
        notice = self.progress[-1]
        path = self.write_events(self.transcript_events('Done.'))
        for _ in range(2):
            self.assertEqual(self.invoke('agentStop', transcriptPath=str(path))[0], {})
        path = self.write_events(self.transcript_events('Another turn without the diagnostic.'))
        self.assertEqual(self.invoke('agentStop', transcriptPath=str(path))[0], {})
        self.assertEqual(self.invoke('postToolUse', **payload)[0], {})
        self.assertEqual(self.progress, [notice])

    def test_docs_cache_new_problem_gets_a_new_display_notice(self):
        with mock.patch.dict(os.environ, self.env):
            docs_cache.set_status('Not logged in')
            data = {**self.payload, 'last_assistant_message': 'Done.'}
            self.assertIn('Not logged in', docs_cache.copilot_stop(data)['systemMessage'])
            self.assertIsNone(docs_cache.copilot_stop(data))
            docs_cache.set_status('Executable missing')
            self.assertIn('Executable missing', docs_cache.copilot_stop(data)['systemMessage'])

    def test_docs_cache_notice_storage_errors_remain_fail_open(self):
        with mock.patch.dict(os.environ, self.env):
            docs_cache.set_status('Not logged in')
            data = {**self.payload, 'last_assistant_message': 'Done.'}
            notice = docs_cache.pending_notice(self.payload['sessionId'])
            with mock.patch.object(docs_cache.os, 'open', side_effect=PermissionError('unavailable')), \
                    mock.patch.object(sys, 'stderr'):
                output = copilot_adapter.docs_cache_hook(docs_cache.copilot_stop, data)
            self.assertIsNone(output)
            self.assertFalse(notice['marker'].exists())

    def test_failed_shared_hook_does_not_consume_an_undelivered_notice(self):
        docs_cache.set_status('worker unavailable')
        with mock.patch.object(copilot_adapter, 'run_shared_hooks', side_effect=RuntimeError('fixture failure')):
            with mock.patch.object(sys, 'stdout', io.StringIO()), mock.patch.object(sys, 'stderr', io.StringIO()):
                self.assertIsNone(copilot_adapter.run_hook('postToolUse', {
                    **self.payload, 'toolName': 'bash', 'toolArgs': {'command': 'true'},
                    'toolResult': {'resultType': 'success', 'textResultForLlm': ''},
                }))
        self.assertIsNotNone(docs_cache.pending_notice(self.payload['sessionId']))

    def test_docs_cache_warning_does_not_depend_on_response_punctuation(self):
        status = self.home / '.cache/ioncache-ai-tools/docs-cache/distill-status.json'
        status.parent.mkdir(parents=True)
        status.write_text(json.dumps({'problem': f'Not logged in{EM_DASH}retry', 'ts': time.time()}))
        self.invoke('postToolUse', toolName='bash', toolArgs={'command': 'true'},
                    toolResult={'resultType': 'success', 'textResultForLlm': ''})
        notice = self.progress[-1]
        self.assertNotIn(EM_DASH, notice)
        path = self.write_events(self.transcript_events(f'{notice}\nBad{EM_DASH}punctuation'))
        self.assertEqual(self.invoke('agentStop', transcriptPath=str(path))[0], {})
        path = self.write_events(self.transcript_events('Clean requested answer.'))
        self.assertEqual(self.invoke('agentStop', transcriptPath=str(path))[0], {})
        self.assertEqual(self.progress, [notice])

    def test_adapter_stays_out_of_docs_distiller_runs(self):
        self.env['IONCACHE_DOCS_DISTILLER'] = '1'
        self.assertEqual(self.prompt('Implement the feature'), {})


    def test_native_shell_rules(self):
        for command in ('pkill worker', 'git worktree add /tmp/new', 'printf x > package-lock.json',
                        'kill -TERM 00', 'kill -TERM +0',
                        'exec pkill worker', 'exec kill -TERM +0', "exec sed -i 's/a/b/' package-lock.json",
                        'MODE=review pkill worker', "if true; then sed -i 's/a/b/' package-lock.json; fi",
                        'echo ready # status\npkill worker', "echo ready; pkill worker\nprintf 'unfinished"):
            with self.subTest(command=command):
                self.assertEqual(self.tool('bash', {'command': command})['permissionDecision'], 'deny')
        self.assertEqual(self.tool('bash', {'command': 'echo kill'}), {})
        self.assertEqual(self.tool('bash', {'command': "echo ';' pkill worker"}), {})
        self.assertEqual(self.tool('bash', {'command': "echo '>' package-lock.json"}), {})
        self.assertEqual(self.tool('bash', {'command': 'exec echo pkill worker'}), {})
        self.assertEqual(self.tool('bash', {'command': 'exec npm install --package-lock-only --ignore-scripts'}), {})
        self.assertEqual(self.tool('bash', json.dumps({'command': 'git status'})), {})


    def test_patch_header_whitespace_is_denied(self):
        for target in ('Add File: yarn.lock\f\n+x', 'Update File: yarn.lock\f\n@@\n-old\n+new',
                       'Delete File: yarn.lock\f', 'Update File: safe.txt\n*** Move to: yarn.lock\f\n@@\n-old\n+new'):
            patch = f'*** Begin Patch\n*** {target}\n*** End Patch'
            with self.subTest(target=target):
                output = self.tool('apply_patch', patch)
                self.assertEqual(output.get('permissionDecision'), 'deny')
                self.assertIn('header whitespace', output['permissionDecisionReason'])
                self.assertNotIn('modifiedArgs', output)

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

    def test_literal_data_recovers_without_rewriting_paths_or_content(self):
        original = f"printf 'a{EM_DASH}b' > 'literal{EM_DASH}.txt'"
        denied = self.tool('bash', {'command': original})
        self.assertEqual(denied['permissionDecision'], 'deny')
        script = (
            'from pathlib import Path; '
            'Path("literal" + chr(0x2014) + ".txt").write_text('
            '"a" + chr(0x2014) + "b", encoding="utf-8")'
        )
        command = shlex.join([sys.executable, '-c', script])
        self.assertNotIn(EM_DASH, command)
        self.assertEqual(self.tool('bash', {'command': command}), {})
        subprocess.run(command, shell=True, check=True, cwd=self.project, env=self.env, timeout=5)
        self.assertEqual((self.project / f'literal{EM_DASH}.txt').read_bytes(),
                         f'a{EM_DASH}b'.encode('utf-8'))
        self.assertEqual(self.tool('bash', {'command': original})['permissionDecision'], 'deny')
        self.assertIn('chr(0x2014)', denied['permissionDecisionReason'])

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

    def test_large_patch_checks_last_target_within_hook_budget(self):
        patch = '*** Begin Patch\n' + ''.join(
            f'*** Add File: safe-{index}.txt\n+x\n' for index in range(1000)
        ) + '*** Delete File: yarn.lock\n*** End Patch'
        started = time.monotonic()
        output = self.tool('apply_patch', patch)
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual(output['permissionDecision'], 'deny')
        self.assertIn('lockfile', output['permissionDecisionReason'])

    def test_patch_checks_text_after_non_lf_separators(self):
        for separator in ('\f', chr(0x2028), chr(0x2029)):
            with self.subTest(separator=repr(separator)):
                patch = f'*** Begin Patch\n*** Add File: safe.txt\n+before{separator}after{EM_DASH}text\n*** End Patch'
                output = self.tool('apply_patch', patch)
                self.assertEqual(output.get('permissionDecision'), 'deny', output)
                self.assertNotIn('modifiedArgs', output)
                self.assertEqual(self.tool('apply_patch', patch.replace(EM_DASH, ',')), {})

    def test_copilot_config_overrides_and_cross_host_union(self):
        global_path = self.home / '.copilot/ioncache-ai-tools.local.json'
        local_path = self.project / '.github/copilot/ioncache-ai-tools.local.json'
        rule = 'no_broad_process_kill'
        self.write_config(global_path, {'disabledRules': [rule]})
        self.assertEqual(self.tool('bash', {'command': 'pkill worker'}), {})
        self.write_config(local_path, {'enabledRules': [rule]})
        self.assertEqual(self.tool('bash', {'command': 'pkill worker'})['permissionDecision'], 'deny')
        self.write_config(self.project / '.claude/ioncache-ai-tools.local.json', {'disabledRules': [rule]})
        self.assertEqual(self.tool('bash', {'command': 'pkill worker'}), {})
        self.write_config(local_path, {'disabledRules': ['fix_emdash']})
        self.assertEqual(self.tool('create', {'path': 'x', 'file_text': EM_DASH}), {})

    def test_malformed_copilot_config_pauses_features_without_replacing_preferences(self):
        config = self.home / '.copilot/ioncache-ai-tools.local.json'
        config.parent.mkdir()
        config.write_text('{bad')
        output, stderr = self.invoke('preToolUse', toolName='bash', toolArgs={'command': 'pkill worker'})
        self.assertEqual(output, {})
        self.assertIn('failed to read', stderr)
        self.assertIn('features paused', stderr)
        self.assertEqual(config.read_text(), '{bad')

    def test_stop_does_not_require_a_readable_transcript(self):
        events = self.transcript_events('clean')
        events.insert(0, {'type': 'assistant.message', 'data': {'content': EM_DASH}})
        events.insert(-1, {'type': 'assistant.message', 'agentId': 'child', 'data': {'content': EM_DASH}})
        events.insert(-1, {'type': 'assistant.message', 'data': {'parentToolCallId': 'child', 'content': EM_DASH}})
        path = self.write_events(events)
        self.assertEqual(self.invoke('agentStop', transcriptPath=str(path))[0], {})
        path = self.write_events(self.transcript_events(f'bad{EM_DASH}text'))
        self.assertEqual(self.invoke('agentStop', transcriptPath=str(path))[0], {})
        path.write_text('{invalid transcript')
        self.assertEqual(self.invoke('agentStop', transcriptPath=str(path))[0], {})
        path.unlink()
        self.assertEqual(self.invoke('agentStop', transcriptPath=str(path))[0], {})
        self.assertEqual(self.invoke('agentStop')[0], {})

    def test_stop_does_not_review_native_completion_summary(self):
        self.prompt('Implement the requested change')
        summary = 'Completed the requested change.'
        path = self.write_events(self.completion_events(summary))
        capture = self.root / 'completion-review.txt'
        self.env['REVIEW_FIXTURE_CAPTURE'] = str(capture)
        self.assertEqual(self.invoke('agentStop', transcriptPath=str(path))[0], {})
        self.assertFalse(capture.exists())
        self.assertFalse((self.home / '.cache/ioncache-ai-tools/claim-evidence').exists())

    def test_completion_summary_does_not_trigger_a_visible_rewrite(self):
        self.prompt('Implement the requested change')
        path = self.write_events(self.completion_events(f'Bad{EM_DASH}punctuation.'))
        output = self.invoke('agentStop', transcriptPath=str(path))[0]
        self.assertEqual(output, {})
        events = self.completion_events('Only the observed result is reported.')
        events.insert(0, {'type': 'session.task_complete', 'data': {'summary': 'Stale summary.'}})
        self.write_events(events)
        self.assertEqual(self.invoke('agentStop', transcriptPath=str(path))[0], {})

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


    @pytest.mark.process
    def test_invalid_input_fails_visibly(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / 'hooks/scripts/copilot_adapter.py'), 'preToolUse'],
            input=json.dumps({**self.payload, 'toolName': 'apply_patch', 'toolArgs': 'malformed'}),
            text=True, capture_output=True, env=self.env, timeout=10,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('no recognized file headers', result.stderr)
        self.assertNotIn('permissionDecision', result.stdout)

    def test_shared_hook_failure_is_not_silently_ignored(self):
        failure = subprocess.CompletedProcess(['python3', 'hook.py'], 1, '', 'fixture failure\n')
        with mock.patch.object(hook_adapter_common.subprocess, 'run', return_value=failure):
            with mock.patch('sys.stderr') as stderr:
                outputs = hook_adapter_common.run_shared_hooks('PreToolUse', {
                    'cwd': str(self.project), 'tool_name': 'Read', 'tool_input': {},
                })
                self.assertTrue(outputs)
                self.assertTrue(all('checks unavailable' in item['systemMessage'] for item in outputs))
                self.assertNotIn('permissionDecision', str(outputs))
                stderr.write.assert_any_call('fixture failure\n')

    def test_malformed_handler_output_cannot_erase_an_independent_denial(self):
        outputs = [
            {'hookSpecificOutput': []},
            {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                    'permissionDecisionReason': 'Use the package manager'}},
        ]
        results = [subprocess.CompletedProcess(['python3', 'hook.py'], 0, json.dumps(value), '')
                   for value in outputs]
        with (
            mock.patch.object(hook_adapter_common.subprocess, 'run', side_effect=results),
            mock.patch.object(sys, 'stdout', io.StringIO()),
            mock.patch.object(sys, 'stderr', io.StringIO()),
        ):
            output = copilot_adapter.run_hook('preToolUse', {
                **self.payload, 'toolName': 'create', 'toolArgs': {'path': 'yarn.lock', 'file_text': 'x'},
            })
        self.assertEqual(output, {'permissionDecision': 'deny', 'permissionDecisionReason': 'Use the package manager'})

    def test_shared_deadline_expires_before_native_timeout(self):
        with (
            mock.patch.object(hook_adapter_common.time, 'monotonic', side_effect=[0, 21]),
            mock.patch.object(hook_adapter_common.subprocess, 'run') as run,
            mock.patch.object(sys, 'stderr', io.StringIO()),
        ):
            output = hook_adapter_common.run_shared_hooks('PreToolUse', {'cwd': str(self.project)})
        run.assert_not_called()
        self.assertIn('internal deadline', str(output))
        self.assertNotIn('permissionDecision', str(output))

    def test_shared_deadline_reduces_remaining_handler_budget(self):
        result = subprocess.CompletedProcess(['python3', 'hook.py'], 0, '', '')
        with (
            mock.patch.object(hook_adapter_common.time, 'monotonic', side_effect=[0, 1, 18, 19, 19.5]),
            mock.patch.object(hook_adapter_common.subprocess, 'run', return_value=result) as run,
        ):
            hook_adapter_common.run_shared_hooks('PreToolUse', {'cwd': str(self.project)})
        self.assertEqual([call.kwargs['timeout'] for call in run.call_args_list], [5, 2, 1, 0.5])


if __name__ == '__main__':
    unittest.main()
