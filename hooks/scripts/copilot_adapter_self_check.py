#!/usr/bin/env python3
"""Run all checks, or pass CopilotAdapterTests.test_name for one test."""
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

import copilot_adapter
import copilot_history
import docs_cache
import hook_adapter_common
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

    def test_autonomous_work_continues_across_questions_and_stale_state(self):
        self.write_config(self.home / '.claude/ioncache-ai-tools.local.json', {'features': {}})
        self.prompt('Implement the requested report with two independent workers')
        self.marker.write_text('stale question')
        actors = ({}, {'sessionId': 'worker-a', 'agentId': 'worker-a',
                       'parentAgentId': self.payload['sessionId']},
                  {'sessionId': 'worker-b', 'agentId': 'worker-b',
                   'parentAgentId': self.payload['sessionId']})
        self.assertEqual(self.tool('task', {'prompt': 'Write the requested report'}), {})
        for index, actor in enumerate(actors):
            self.invoke('userPromptTransformed', **actor,
                        prompt='What have you found?', transformedPrompt='What have you found?')
            self.invoke('preCompact', **actor)
            self.invoke('sessionStart', **actor, source='resume')
            for worker in actors:
                self.assertEqual(self.invoke('preToolUse', **worker, toolName='create',
                                            toolArgs={'path': f'report-{index}.txt', 'file_text': 'continued'})[0], {})
            command = f'printf "continued" > report-{index}.txt'
            self.assertEqual(self.invoke('preToolUse', **actor, toolName='bash',
                                         toolArgs={'command': command})[0], {})
            subprocess.run(command, shell=True, check=True, cwd=self.project, env=self.env, timeout=5)
            self.assertEqual((self.project / f'report-{index}.txt').read_text(), 'continued')
        self.assertFalse((self.home / '.cache/ioncache-ai-tools/claim-evidence').exists())

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
        self.assertEqual(self.tool('bash', {'command': 'pkill fixture-worker'})['permissionDecision'], 'deny')
        worker = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], env=self.env)
        try:
            command = f'kill {worker.pid}'
            self.assertEqual(self.tool('bash', {'command': command}), {})
            subprocess.run(['kill', str(worker.pid)], check=True, timeout=5)
            worker.wait(timeout=5)
        finally:
            if worker.poll() is None:
                worker.terminate()
                worker.wait(timeout=5)
        self.assertEqual(self.tool('bash', {'command': 'pkill fixture-worker'})['permissionDecision'], 'deny')

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
        self.prompt('What changed in this checkout?')
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
        self.prompt('Why did that change?')
        self.assertEqual(self.tool('bash', command), {})
        self.assertEqual(self.tool('view', {'path': 'source.py'}), {})
        self.prompt('Commit the requested fix')
        self.assertEqual(self.tool('bash', command), {})
        self.assertEqual(self.tool('bash', {'command': 'pkill worker'})['permissionDecision'], 'deny')
        self.assertFalse(capture.exists())


    def test_adapter_deadline_includes_configuration_before_shared_hooks(self):
        self.prompt('Implement the requested file')
        question = {**self.payload, 'prompt': 'Why?', 'transformedPrompt': 'Why?'}
        with (
            mock.patch.object(copilot_adapter, 'ADAPTER_TIMEOUT_SECONDS', 0.02),
            mock.patch.object(copilot_adapter, 'synchronize', side_effect=lambda *_: time.sleep(1)),
            mock.patch.object(sys, 'stdout', io.StringIO()) as notices,
            mock.patch.object(sys, 'stderr', io.StringIO()),
        ):
            started = time.monotonic()
            self.assertIsNone(copilot_adapter.run_hook('userPromptTransformed', question))
            self.assertLess(time.monotonic() - started, 0.5)
        self.assertIn('invocation deadline', notices.getvalue())
        self.assertEqual(self.tool('create', {'path': 'x', 'file_text': 'y'}), {})


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

    def test_stop_does_not_retry_visible_text_or_gate_tools(self):
        self.prompt('Why is this different?')
        path = self.write_events(self.transcript_events(f'Bad{EM_DASH}punctuation.'))
        output = self.invoke('agentStop', transcriptPath=str(path))[0]
        self.assertEqual(output, {})
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.tool('create', {'path': 'x', 'file_text': 'y'}), {})
        self.write_events(self.transcript_events('Corrected punctuation.'))
        self.assertEqual(self.invoke('agentStop', transcriptPath=str(path), stop_hook_active=True)[0], {})

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
                        'MODE=review pkill worker', "if true; then sed -i 's/a/b/' package-lock.json; fi",
                        'echo ready # status\npkill worker', "echo ready; pkill worker\nprintf 'unfinished"):
            with self.subTest(command=command):
                self.assertEqual(self.tool('bash', {'command': command})['permissionDecision'], 'deny')
        self.assertEqual(self.tool('bash', {'command': 'echo kill'}), {})
        self.assertEqual(self.tool('bash', {'command': "echo ';' pkill worker"}), {})
        self.assertEqual(self.tool('bash', {'command': "echo '>' package-lock.json"}), {})
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
        self.assertEqual([call.kwargs['timeout'] for call in run.call_args_list], [5, 2, 1])


if __name__ == '__main__':
    unittest.main()
