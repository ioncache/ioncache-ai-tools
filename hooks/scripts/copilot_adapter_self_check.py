#!/usr/bin/env python3
"""Run all checks, or pass CopilotAdapterTests.test_name for one test."""
import io
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
import docs_cache
import hook_adapter_common
import turn_guard
from classify_question import marker_path
from turn_guard_self_check import install_reviewers

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
        result = subprocess.run(
            [sys.executable, str(ROOT / 'hooks/scripts/copilot_adapter.py'), event],
            input=json.dumps({**self.payload, **fields}), text=True,
            capture_output=True, env=self.env, cwd=self.root, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        outputs = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        self.progress.extend(item['message'] for item in outputs if item.get('type') == 'progress')
        decisions = [item for item in outputs if item.get('type') != 'progress']
        self.assertLessEqual(len(decisions), 1)
        return decisions[0] if decisions else {}, result.stderr

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
        self.assertNotIn('commands', manifest)
        self.assertEqual((ROOT / manifest['skills']).resolve(), ROOT / 'skills')
        hooks = json.loads((ROOT / manifest['hooks']).read_text())
        self.assertEqual(hooks['version'], 1)
        self.assertEqual(set(hooks['hooks']), {
            'userPromptTransformed', 'preToolUse', 'postToolUse', 'agentStop', 'sessionEnd',
            'sessionStart', 'preCompact', 'subagentStart', 'subagentStop', 'postToolUseFailure',
        })
        self.assertFalse((ROOT / 'skills/claim-evidence/SKILL.md').exists())
        for event, entries in hooks['hooks'].items():
            self.assertEqual(len(entries), 1)
            self.assertIn('${COPILOT_PLUGIN_ROOT}/hooks/scripts/copilot_adapter.py', entries[0]['bash'])
            self.assertTrue(entries[0]['bash'].endswith(event))

    def test_prompt_preserves_transformation_and_bootstraps_only_once(self):
        output = self.prompt('Implement the feature')
        text = output['modifiedTransformedPrompt']
        self.assertTrue(text.startswith('expanded prompt\n\n'))
        self.assertIn('documentation-backed', text)
        self.assertIn('ioncache-ai-tools', text)
        for name in ('engineering-judgment', 'scope-exactly-what-asked', 'verify-state-before-claiming'):
            rule = json.loads((ROOT / f'hooks/rules/{name}.json').read_text())
            self.assertIn(rule['message'], text)
        self.assertEqual(self.prompt('Continue the feature'), {})

    def test_failed_prompt_update_cannot_reuse_old_authorization(self):
        self.prompt('Implement the requested file')
        question = {**self.payload, 'prompt': 'Why is this different?', 'transformedPrompt': 'Why is this different?'}
        with mock.patch.object(copilot_adapter, 'run_shared_hooks', side_effect=RuntimeError('database unavailable')):
            with self.assertRaises(RuntimeError):
                copilot_adapter.transform_prompt(question)
        for name, args in (('create', {'path': 'x', 'file_text': 'y'}),
                           ('write_agent', {'agent_id': 'old', 'message': 'Implement the old change'})):
            self.assertEqual(self.tool(name, args).get('permissionDecision'), 'deny')
        self.prompt('Implement the newly requested file')
        self.assertEqual(self.tool('create', {'path': 'x', 'file_text': 'y'}), {})

    def test_stop_supplies_visible_prose_before_tools(self):
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
        self.assertIn('Here is an unsolicited plan.', json.dumps(stop_input))

    def test_failed_prompt_fence_survives_old_feedback_and_resume(self):
        self.prompt('Implement the change')
        turn_guard.remember_continuation(copilot_adapter.shared_input(self.payload), 'old feedback')
        with mock.patch.object(copilot_adapter, 'run_shared_hooks', side_effect=RuntimeError('unavailable')):
            with self.assertRaises(RuntimeError):
                copilot_adapter.transform_prompt({**self.payload, 'prompt': 'Why?', 'transformedPrompt': 'Why?'})
        stderr = io.StringIO()
        with mock.patch.object(sys, 'stderr', stderr), self.assertRaisesRegex(RuntimeError, 'turn_guard.py exited with 2'):
            copilot_adapter.transform_prompt({**self.payload, 'prompt': 'old feedback', 'transformedPrompt': 'old feedback'})
        self.assertIn('turn-guard: the current user request has not been recorded', stderr.getvalue())
        self.invoke('sessionEnd')
        self.invoke('sessionStart', source='resume')
        self.assertEqual(self.tool('create', {'path': 'x', 'file_text': 'y'})['permissionDecision'], 'deny')

    def test_dangling_prompt_fence_cannot_reopen_authorization(self):
        self.prompt('Implement the change')
        path = marker_path(copilot_adapter.shared_input(self.payload), 'prompt')
        path.symlink_to(self.root / 'missing')
        self.assertEqual(self.tool('create', {'path': 'x', 'file_text': 'y'}).get('permissionDecision'), 'deny')

    def test_mid_turn_compaction_recovers_on_native_post_tool_output(self):
        self.prompt('Why does this happen?')
        self.invoke('preCompact')
        fields = {'toolName': 'view', 'toolArgs': {'path': 'source.py'},
                  'toolResult': {'resultType': 'success', 'textResultForLlm': 'source'}}
        output, _ = self.invoke('postToolUse', **fields)
        self.assertIn('Question turn:', output['additionalContext'])
        self.assertEqual(self.invoke('postToolUse', **fields)[0], {})

    def test_successful_view_does_not_parse_file_contents_as_exit_status(self):
        self.prompt('Explain this file')
        path = self.project / 'failure-example.txt'
        path.write_text('The example fails with exit code: 1.')
        fields = {'toolName': 'view', 'toolArgs': {'path': str(path)}}
        self.invoke('preToolUse', **fields)
        self.invoke('postToolUse', **fields, toolResult={
            'resultType': 'success', 'textResultForLlm': path.read_text(),
        })
        with turn_guard.store_for(copilot_adapter.shared_input(self.payload)) as store:
            state = store.get(turn_guard.CATEGORY, 'state')
        observation = turn_guard.current_observations(state)[-1]
        self.assertTrue(observation['success'])
        self.assertTrue(observation['unchanged'])

    def test_bash_exit_code_text_does_not_override_native_status(self):
        self.prompt('Inspect the command output')
        fields = {'toolName': 'bash', 'toolArgs': {'command': 'printf "exit code: 1"'}}
        for event, result_type, expected in (
            ('postToolUse', 'success', True), ('postToolUseFailure', 'failure', False),
        ):
            with self.subTest(event=event):
                self.invoke('preToolUse', **fields)
                self.invoke(event, **fields, toolResult={'resultType': result_type, 'textResultForLlm': 'exit code: 1'})
                with turn_guard.store_for(copilot_adapter.shared_input(self.payload)) as store:
                    state = store.get(turn_guard.CATEGORY, 'state')
                self.assertIs(state['observations'][-1]['success'], expected)

    def test_recent_proposal_survives_transcript_capture_limits(self):
        self.prompt('Propose one change and wait')
        proposal = 'Change reader.py only; leave writer.py untouched.'
        events = self.transcript_events('Waiting for approval.')
        events[2:2] = [
            {'type': 'assistant.message', 'data': {'content': 'Earlier research. ' + 'x' * turn_guard.MAX_RESPONSE_CHARS}},
            {'type': 'assistant.message', 'data': {'content': proposal}},
        ]
        path = self.write_events(events)
        response = copilot_adapter.response_context({**self.payload, 'transcriptPath': str(path)})
        self.assertTrue(response['_assistant_messages'][0].startswith('Earlier research.'))
        self.assertEqual(response['_response_coverage'], 'partial')
        with mock.patch.object(turn_guard.turn_review, 'review', return_value={'ok': True, 'reason': ''}):
            turn_guard.run_hook('Stop', {**copilot_adapter.shared_input(self.payload), **response})
        self.prompt('Yes, proceed')
        with turn_guard.store_for(copilot_adapter.shared_input(self.payload)) as store:
            history = store.get(turn_guard.CATEGORY, 'state')['history'][-1]
        self.assertIn(proposal, json.dumps(history))
        retained = next(item for item in history['earlier_messages'] if item['text'] == proposal)
        self.assertFalse(retained['truncated'])
        self.assertTrue(history['earlier_messages_omitted'])

    def test_native_approval_keeps_the_tool_proposal_and_user_answer(self):
        self.prompt('Propose the fix, get approval, then implement it')
        proposal = 'Plan details. ' * 400 + 'Update the guard self-check. No commits or pushes.'
        args = {'message': proposal, 'requestedSchema': {'properties': {}}}
        fields = {'toolName': 'ask_user', 'toolArgs': json.dumps(args), 'toolCallId': 'approval'}
        answer = {'resultType': 'success', 'textResultForLlm': 'User responded: Approve this plan'}
        self.invoke('preToolUse', **fields)
        self.invoke('postToolUse', **fields, toolResult=answer)
        capture = self.root / 'review-input.txt'
        self.env['REVIEW_FIXTURE_CAPTURE'] = str(capture)
        self.assertEqual(self.tool('create', {'path': 'turn_guard_self_check.py', 'file_text': 'requested change'}), {})
        request = json.loads(capture.read_text().splitlines()[-1])
        interaction = request.get('user_interactions', [{}])[-1]
        self.assertEqual(interaction.get('input'), args)
        self.assertEqual(json.loads(interaction['result']), answer)
        self.assertFalse(interaction['truncated'])
        self.assertTrue(interaction['correlated'])

    def test_stop_continuation_retains_earlier_visible_prose(self):
        self.prompt('Why does this happen?')
        turn_guard.remember_continuation(copilot_adapter.shared_input(self.payload), 'owned feedback')
        events = self.transcript_events('Unsolicited plan.')
        events[-1]['data']['input'] = {**self.payload, 'timestamp': 123455}
        events.extend([
            {'type': 'user.message', 'data': {'content': 'owned feedback'}},
            {'type': 'assistant.turn_start', 'data': {}},
            {'type': 'assistant.message', 'data': {'content': 'The answer.'}},
            {'type': 'hook.start', 'data': {'hookType': 'agentStop', 'input': self.payload}},
        ])
        path = self.write_events(events)
        result = copilot_adapter.response_context({**self.payload, 'transcriptPath': str(path)})
        self.assertIn('Unsolicited plan.', result['_assistant_messages'])

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
        self.assertEqual(self.prompt('Continue the feature'), {})

    def test_graphify_uses_consumer_cwd(self):
        graph = self.project / 'graphify-out/graph.json'
        graph.parent.mkdir()
        graph.write_text('{}')
        self.assertIn('graphify query', self.prompt('Investigate the flow')['modifiedTransformedPrompt'])

    def test_lifecycle_context_is_not_discarded_or_repeated_per_prompt(self):
        output, _ = self.invoke('sessionStart', source='startup')
        self.assertIn('documentation-backed', output['additionalContext'])
        self.assertEqual(self.prompt('Implement the change'), {})
        self.assertEqual(self.invoke('sessionStart', source='resume')[0], {})
        self.assertIn('documentation-backed', self.invoke('subagentStart', agentName='explore')[0]['additionalContext'])
        self.assertEqual(self.invoke('preCompact')[0], {})
        self.assertIn('documentation-backed', self.prompt('Continue')['modifiedTransformedPrompt'])

    def test_stop_correction_preserves_question_mode(self):
        self.prompt('Why is this different?')
        self.env['REVIEW_FIXTURE_RESULT'] = '{"ok":false,"reason":"Unrequested draft."}'
        path = self.write_events(self.transcript_events('Unrequested draft.'))
        output = self.invoke('agentStop', transcriptPath=str(path))[0]
        self.assertEqual(output['decision'], 'block')
        self.assertEqual(self.prompt(output['reason']), {})
        self.assertTrue(self.marker.exists())
        self.assertEqual(self.tool('create', {'path': 'x', 'file_text': 'y'})['permissionDecision'], 'deny')
        self.assertEqual(self.invoke('agentStop', transcriptPath=str(path), stop_hook_active=True)[0], {})
        self.assertIn('did not verify', self.progress[-1])

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
            with self.assertRaises(RuntimeError):
                copilot_adapter.run_hook('postToolUse', {
                    **self.payload, 'toolName': 'bash', 'toolArgs': {'command': 'true'},
                    'toolResult': {'resultType': 'success', 'textResultForLlm': ''},
                })
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
        self.assertEqual(self.invoke('agentStop', transcriptPath=str(path))[0]['decision'], 'block')
        path = self.write_events(self.transcript_events('Clean requested answer.'))
        self.assertEqual(self.invoke('agentStop', transcriptPath=str(path))[0], {})
        self.assertEqual(self.progress, [notice])

    def test_adapter_stays_out_of_docs_distiller_runs(self):
        self.env['IONCACHE_DOCS_DISTILLER'] = '1'
        self.assertEqual(self.prompt('Implement the feature'), {})

    def test_question_blocks_mutations_until_non_question_prompt(self):
        text = self.prompt('why is this behavior different')['modifiedTransformedPrompt']
        self.assertIn('Question turn: answer and reasoning only', text)
        self.assertTrue(self.marker.exists())
        for name, args in [
            ('create', {'path': 'x', 'file_text': 'y'}),
            ('edit', {'path': 'x', 'old_str': 'a', 'new_str': 'b'}),
            ('apply_patch', '*** Begin Patch\n*** Add File: x\n+y\n*** End Patch'),
            ('bash', {'command': 'git commit -m change'}),
            ('bash', {'command': "gh api graphql -f 'query=query Read { q } mutation Change { m }' -f operationName=Change"}),
        ]:
            with self.subTest(name=name):
                self.assertEqual(self.tool(name, args)['permissionDecision'], 'deny')
        self.assertEqual(self.tool('view', {'path': 'x'}), {})
        self.assertEqual(self.tool('bash', {'command': 'git status --short'}), {})
        self.assertEqual(self.tool('bash', {'command': "echo '>' output.txt"}), {})
        self.prompt('Implement the change')
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.tool('create', {'path': 'x', 'file_text': 'y'}), {})

    def test_native_shell_rules(self):
        for command in ('kill 123', 'git worktree add /tmp/new', 'printf x > package-lock.json',
                        'echo ready # status\nkill 123', "echo ready; kill 123\nprintf 'unfinished"):
            with self.subTest(command=command):
                self.assertEqual(self.tool('bash', {'command': command})['permissionDecision'], 'deny')
        self.assertEqual(self.tool('bash', {'command': 'echo kill'}), {})
        self.assertEqual(self.tool('bash', {'command': "echo ';' kill 123"}), {})
        self.assertEqual(self.tool('bash', {'command': "echo '>' package-lock.json"}), {})
        self.assertEqual(self.tool('bash', json.dumps({'command': 'git status'})), {})

    def test_graphql_template_cannot_hide_mutation(self):
        self.prompt('why is this different')
        command = "gh api graphql -f 'query=mutation { m }' --template '-fquery=query { q }'"
        self.assertEqual(self.tool('bash', {'command': command}).get('permissionDecision'), 'deny')
        self.assertEqual(self.tool('bash', {'command': command.replace('mutation { m }', 'query { q }')}), {})

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

    def test_shared_deadline_expires_before_native_timeout(self):
        with (
            mock.patch.object(hook_adapter_common.time, 'monotonic', side_effect=[0, 81]),
            mock.patch.object(hook_adapter_common.subprocess, 'run') as run,
            self.assertRaisesRegex(TimeoutError, 'internal deadline'),
        ):
            hook_adapter_common.run_shared_hooks('PreToolUse', {'cwd': str(self.project)})
        run.assert_not_called()

    def test_shared_deadline_reduces_remaining_handler_budget(self):
        result = subprocess.CompletedProcess(['python3', 'hook.py'], 0, '', '')
        with (
            mock.patch.object(hook_adapter_common.time, 'monotonic', side_effect=[0, 1, 78, 79, 79.5]),
            mock.patch.object(hook_adapter_common.subprocess, 'run', return_value=result) as run,
        ):
            hook_adapter_common.run_shared_hooks('PreToolUse', {'cwd': str(self.project)})
        self.assertEqual([call.kwargs['timeout'] for call in run.call_args_list], [5, 2, 1, 0.5])


if __name__ == '__main__':
    unittest.main()
