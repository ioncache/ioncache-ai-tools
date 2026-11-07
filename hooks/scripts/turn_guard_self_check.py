#!/usr/bin/env python3
"""Offline regressions for turn state, evidence, and reviewer protocol."""
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
import uuid

from classify_question import QUESTION_CONTRACT, marker_path
import block_emdash_turn
import docs_cache
import turn_guard as guard
import turn_review


def install_reviewers(root):
    directory = root / 'reviewers'
    directory.mkdir()
    fixture = directory / 'fixture'
    fixture.write_text(
        f'#!{sys.executable}\nimport os,sys\nfrom pathlib import Path\n'
        'if os.environ.get("REVIEW_FIXTURE_CAPTURE"):\n'
        '    Path(os.environ["REVIEW_FIXTURE_CAPTURE"]).write_text(sys.stdin.read())\n'
        'if os.environ.get("REVIEW_FIXTURE_ERROR"):\n'
        '    print(os.environ["REVIEW_FIXTURE_ERROR"],file=sys.stderr)\n'
        '    sys.exit(2)\n'
        'print(os.environ.get("REVIEW_FIXTURE_RESULT", \'{"ok": true, "reason": ""}\'))\n'
    )
    fixture.chmod(0o700)
    for name in ('claude', 'codex', 'copilot'):
        (directory / name).symlink_to(fixture)
    return str(directory) + os.pathsep + os.environ.get('PATH', '')


def process_exists(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def process_stopped(pid):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        result = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)],
                                capture_output=True, text=True, timeout=2, check=False)
        status = result.stdout.strip()
        if result.returncode == 1 and not status and not result.stderr.strip():
            return True
        if result.returncode == 0 and status.startswith('Z'):
            return True
        time.sleep(0.02)
    return False


class TurnGuardTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='turn-guard-check-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.project = self.root / 'project'
        self.project.mkdir()
        self.env = {
            'HOME': str(self.root / 'home'), 'CODEX_HOME': str(self.root / 'codex'),
            'COPILOT_HOME': str(self.root / 'copilot'), 'XDG_CACHE_HOME': str(self.root / 'cache'),
            'PATH': install_reviewers(self.root), 'IONCACHE_DOCS_DISTILLER': '',
        }
        patcher = mock.patch.dict(os.environ, self.env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.data = {'session_id': f'self-check-{uuid.uuid4()}', 'cwd': str(self.project)}
        self.addCleanup(lambda: marker_path(self.data).unlink(missing_ok=True))

    def hook(self, event, **fields):
        if event in ('Stop', 'SubagentStop'):
            fields.setdefault('_response_coverage', 'turn')
        data = {**self.data, **fields}
        if data.get('agent_id'):
            path = marker_path(data)
            self.addCleanup(lambda: path.unlink(missing_ok=True))
        return guard.run_hook(event, data)

    def state(self):
        with guard.store_for(self.data) as store:
            return store.get(guard.CATEGORY, 'state')

    def prompt(self, text='Implement the requested fix'):
        return self.hook('UserPromptSubmit', prompt=text)

    def tool(self, event='PreToolUse', **fields):
        return self.hook(event, tool_name='Write',
                         tool_input={'file_path': 'target.py', 'content': 'requested change'}, **fields)

    def graph(self):
        graph = self.project / 'graphify-out/graph.json'
        graph.parent.mkdir()
        graph.write_text('{}')
        return graph

    def test_bootstrap_once_and_zero_ordinary_prompt_growth(self):
        first = self.hook('SessionStart', source='startup')
        self.assertLessEqual(len(first['hookSpecificOutput']['additionalContext']), 800)
        for _ in range(20):
            self.assertIsNone(self.prompt())
        self.assertIsNone(self.hook('SessionStart', source='resume'))
        self.assertEqual(self.state()['prompt'], 'Implement the requested fix')

    def test_child_write_invalidates_parent_live_state(self):
        self.prompt()
        self.hook('PostToolUse', tool_name='Bash', tool_input={'command': 'git status'}, tool_response='clean')
        self.hook('SubagentStart', agent_id='child')
        self.hook('PostToolUse', agent_id='child', tool_name='Write',
                  tool_input={'file_path': 'target.py', 'content': 'changed'}, tool_response='written')
        self.assertEqual(self.state()['observations'], [])
        self.assertGreater(self.state()['mutation'], 0)

    def test_read_changed_before_post_hook_is_not_current_evidence(self):
        path = self.project / 'source.py'
        path.write_text('old')
        self.prompt()
        fields = {'tool_name': 'Read', 'tool_input': {'file_path': str(path)}, 'tool_use_id': 'read-1'}
        self.hook('PreToolUse', **fields)
        path.write_text('new content')
        self.hook('PostToolUse', **fields, tool_response='old')
        item = guard.review_request(self.data, self.state(), {})['observations'][0]
        self.assertFalse(item['unchanged'])

    def test_reads_need_unambiguous_pre_tool_provenance(self):
        path = self.project / 'source.py'
        path.write_text('source')
        self.prompt()
        fields = {'tool_name': 'Read', 'tool_input': {'file_path': str(path)}}
        self.hook('PreToolUse', **fields)
        self.hook('PostToolUse', **fields, tool_response='source')
        self.assertTrue(guard.current_observations(self.state())[-1]['unchanged'])
        self.hook('PreToolUse', **fields)
        self.hook('PreToolUse', **fields)
        for _ in range(2):
            self.hook('PostToolUse', **fields, tool_response='source')
            self.assertFalse(guard.current_observations(self.state())[-1]['unchanged'])

    def test_child_write_invalidates_an_inflight_parent_read(self):
        self.prompt()
        fields = {'tool_name': 'Bash', 'tool_input': {'command': 'git status'}, 'tool_use_id': 'status'}
        self.hook('PreToolUse', **fields)
        self.hook('SubagentStart', agent_id='child')
        self.hook('PostToolUse', agent_id='child', tool_name='Write',
                  tool_input={'file_path': 'target.py', 'content': 'changed'}, tool_response='written')
        self.hook('PostToolUse', **fields, tool_response='clean before child write')
        self.assertFalse(self.state()['observations'][0]['fresh'])

    def test_new_native_prompt_cannot_reuse_old_authorization(self):
        self.hook('UserPromptSubmit', prompt='Implement the change', prompt_id='first')
        with mock.patch.object(turn_review, 'review') as reviewer:
            output = self.tool(prompt_id='second')
        self.assertIn('prompt has not been recorded', str(output))
        reviewer.assert_not_called()

    def test_explicit_child_resume_rebinds_new_assignment(self):
        self.prompt()
        self.hook('SubagentStart', agent_id='child')
        self.prompt('Continue implementing with the same agent')
        self.hook('SubagentStart', agent_id='child')
        with mock.patch.object(turn_review, 'review', return_value={'ok': True, 'reason': ''}):
            self.assertIsNone(self.hook('PreToolUse', agent_id='child', tool_name='Write',
                                       tool_input={'file_path': 'target.py', 'content': 'requested'}))

    def test_followup_delegation_is_reviewed(self):
        self.prompt('Why does this happen?')
        with mock.patch.object(turn_review, 'review', return_value={'ok': False, 'reason': 'Unrequested draft.'}) as reviewer:
            output = self.hook('PreToolUse', tool_name='write_agent',
                               tool_input={'agent_id': 'child', 'message': 'Draft a replacement design'})
        self.assertIn('Unrequested draft', str(output))
        reviewer.assert_called_once()

    def test_approval_preserves_the_assistant_proposal(self):
        self.prompt('Propose one change and wait for approval')
        proposal = 'Change only reader.py; leave writer.py unchanged.'
        with mock.patch.object(turn_review, 'review', return_value={'ok': True, 'reason': ''}):
            self.hook('Stop', last_assistant_message=proposal)
        self.prompt('Yes, proceed with that proposal')
        self.assertIn(proposal, json.dumps(guard.review_request(self.data, self.state(), {})))

    def test_tool_approval_preserves_the_full_proposal_after_evidence_churn(self):
        self.prompt('Propose the fix, get approval, then implement it')
        proposal = 'Plan details. ' * 400 + 'Edit turn_guard_self_check.py. Do not commit or push.'
        fields = {'tool_name': 'ask_user', 'tool_use_id': 'approval',
                  'tool_input': {'message': proposal, 'requestedSchema': {'properties': {}}}}
        answer = {'resultType': 'success', 'textResultForLlm': 'User responded: Approve this plan'}
        self.hook('PreToolUse', **fields)
        self.hook('PostToolUse', **fields, tool_response=answer)
        self.tool('PostToolUse', tool_response='written')
        self.hook('PreCompact')
        self.prompt('Continue the approved work')
        with mock.patch.object(turn_review, 'review', return_value={'ok': True, 'reason': ''}) as reviewer:
            self.tool()
        request = reviewer.call_args.args[1]
        interaction = request.get('user_interactions', [{}])[-1]
        self.assertEqual(interaction.get('input'), fields['tool_input'])
        self.assertEqual(json.loads(interaction['result']), answer)
        self.assertTrue(interaction['correlated'])
        self.assertFalse(interaction['truncated'])
        self.assertEqual(request['observations'], [])

    def test_denial_is_response_evidence_without_a_post_tool_event(self):
        self.prompt()
        reason = 'The approved proposal was not available.'
        with mock.patch.object(turn_review, 'review', return_value={'ok': False, 'reason': reason}):
            output = self.tool()
        self.assertEqual(output['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertEqual(self.state()['observations'], [])
        self.prompt('Why was the edit blocked?')
        with mock.patch.object(turn_review, 'review', return_value={'ok': True, 'reason': ''}) as reviewer:
            self.hook('Stop', last_assistant_message='The hook rejected the edit because it lacked the proposal.')
        decisions = reviewer.call_args.args[1].get('hook_decisions', [])
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]['tool'], 'Write')
        self.assertEqual(decisions[0]['reason'], output['hookSpecificOutput']['permissionDecisionReason'])
        self.assertEqual(decisions[0]['input']['file_path'], 'target.py')

    def test_user_exchanges_keep_refusals_failures_and_missing_provenance(self):
        self.prompt()
        fields = {'tool_name': 'ask_user', 'tool_input': {'message': 'Approve the change'}, 'tool_use_id': 'answer'}
        for event, result, success in (
            ('PostToolUse', {'resultType': 'success', 'textResultForLlm': 'No, do not edit.'}, True),
            ('PostToolUse', {'resultType': 'success', 'textResultForLlm': 'The user is unavailable.'}, True),
            ('PostToolUseFailure', {'error': 'cancelled'}, False),
        ):
            with self.subTest(result=result):
                self.hook('PreToolUse', **fields)
                self.hook(event, **fields, tool_response=result)
                item = guard.review_request(self.data, self.state(), {})['user_interactions'][-1]
                self.assertEqual(json.loads(item['result']), result)
                self.assertIs(item['success'], success)
                self.assertTrue(item['correlated'])
        self.hook('PostToolUse', **fields, tool_response='Yes')
        self.assertFalse(self.state()['user_interactions'][-1]['correlated'])
        self.hook('PreToolUse', **fields)
        self.hook('PostToolUse', **{**fields, 'tool_input': {'message': 'A different proposal'}}, tool_response='Yes')
        self.assertFalse(self.state()['user_interactions'][-1]['correlated'])

    def test_user_exchange_survives_mutation_but_not_a_changed_request_in_flight(self):
        self.prompt()
        fields = {'tool_name': 'ask_user', 'tool_input': {'message': 'Approve the proposal'}, 'tool_use_id': 'answer'}
        self.hook('PreToolUse', **fields)
        self.tool('PostToolUse', tool_response='written')
        self.hook('PostToolUse', **fields, tool_response='Yes')
        self.assertTrue(self.state()['user_interactions'][-1]['correlated'])
        self.assertFalse(self.state()['observations'][-1]['fresh'])
        self.hook('PreToolUse', **fields)
        self.prompt('Stop editing and explain the result')
        self.hook('PostToolUse', **fields, tool_response='Yes')
        self.assertFalse(self.state()['user_interactions'][-1]['correlated'])
        request = guard.review_request(self.data, self.state(), {})
        self.assertEqual(request['latest_request'], 'Stop editing and explain the result')

    def test_user_interaction_retention_is_bounded_and_clear_resets_it(self):
        self.prompt()
        for index in range(8):
            fields = {'tool_name': 'ask_user', 'tool_use_id': str(index),
                      'tool_input': {'message': 'Plan. ' * 1000}}
            self.hook('PreToolUse', **fields)
            self.hook('PostToolUse', **fields, tool_response='Yes')
        self.assertLessEqual(len(json.dumps(self.state()['user_interactions'])), guard.MAX_EVIDENCE_CHARS)
        self.assertTrue(self.state()['interaction_context_incomplete'])
        fields['tool_input']['message'] = 'x' * guard.MAX_EVIDENCE_CHARS
        self.hook('PreToolUse', **fields)
        self.hook('PostToolUse', **fields, tool_response='Yes')
        self.assertTrue(self.state()['user_interactions'][-1]['truncated'])
        self.hook('SessionEnd')
        self.hook('SessionStart', source='resume')
        self.assertTrue(self.state()['user_interactions'])
        self.hook('SessionStart', source='clear')
        self.assertNotIn('user_interactions', self.state())

    def test_budget_fitting_keeps_approval_context_before_disposable_evidence(self):
        self.prompt()
        fields = {'tool_name': 'ask_user', 'tool_input': {'message': 'Plan. ' * 2000}}
        self.hook('PreToolUse', **fields)
        self.hook('PostToolUse', **fields, tool_response='Yes, proceed')
        for name in ('Read', 'WebFetch'):
            self.hook('PostToolUse', tool_name=name, tool_input={}, tool_response='e' * 6500)
        candidate = {'kind': 'tool', 'tool': 'Write', 'input': {'content': 'c' * 65_000}}
        request = guard.review_request(self.data, self.state(), candidate)
        self.assertLessEqual(turn_review.input_size(request), turn_review.MAX_INPUT_BYTES)
        self.assertEqual(request['candidate'], candidate)
        self.assertEqual([item['input'] for item in request['user_interactions']], [fields['tool_input']])
        self.assertFalse(request['interaction_context_incomplete'])
        self.assertTrue(request['omitted_context'])

    def test_only_user_input_tools_supply_dialogue_context(self):
        self.prompt()
        for name in ('AskUserQuestion', 'ask_user', 'request_user_input', 'Read', 'mcp__other__ask_user'):
            fields = {'tool_name': name, 'tool_input': {'message': 'A proposal'}, 'tool_use_id': name}
            self.hook('PreToolUse', **fields)
            self.hook('PostToolUse', **fields, tool_response='Yes, proceed')
        self.assertEqual([item['tool'] for item in self.state()['user_interactions']],
                         ['AskUserQuestion', 'ask_user', 'request_user_input'])

    def test_denial_receipts_do_not_become_tool_authority_or_live_evidence(self):
        self.prompt()
        rejected = {'ok': False, 'reason': 'Unrequested change.'}
        with mock.patch.object(turn_review, 'review', return_value=rejected) as reviewer:
            for _ in range(20):
                self.tool()
        self.assertEqual(reviewer.call_count, 1)
        self.assertEqual(reviewer.call_args.args[1]['hook_decisions'], [])
        self.assertEqual(len(self.state()['hook_decisions']), 16)
        self.assertEqual(self.state()['observations'], [])
        self.tool('PostToolUse', tool_response='a different authorized write')
        self.assertTrue(self.state()['hook_decisions'])
        with mock.patch.object(turn_review, 'review', return_value={'ok': True, 'reason': ''}):
            self.assertIsNone(self.tool())

    def test_denial_recording_failure_preserves_the_original_denial(self):
        output = guard.denial('Missing authorization.')
        with mock.patch.object(guard, 'store_for', side_effect=PermissionError('unavailable')), \
                mock.patch.object(sys, 'stderr'):
            self.assertEqual(guard.record_denial(self.data, output), output)

    def test_approval_preserves_proposals_before_the_final_message(self):
        self.prompt('Propose one change and wait')
        proposal = 'Change reader.py only; leave writer.py untouched.'
        self.hook('MessageDisplay', message_id='proposal', index=0, final=True, delta=proposal)
        self.hook('MessageDisplay', message_id='final', index=0, final=True, delta='Waiting for approval.')
        with mock.patch.object(turn_review, 'review', return_value={'ok': True, 'reason': ''}):
            self.hook('Stop', last_assistant_message='Waiting for approval.')
        self.prompt('Yes, proceed')
        self.assertIn(proposal, json.dumps(guard.review_request(self.data, self.state(), {})))

    def test_approval_keeps_complete_final_proposal_when_earlier_prose_overflows(self):
        self.prompt('Propose one change and wait')
        proposal = 'Change reader.py only; leave writer.py untouched.'
        self.hook('MessageDisplay', message_id='earlier', index=0, final=True,
                  delta='Earlier research. ' * guard.MAX_RESULT_CHARS)
        with mock.patch.object(turn_review, 'review', return_value={'ok': True, 'reason': ''}):
            self.hook('Stop', last_assistant_message=proposal, _response_coverage='partial')
        self.prompt('Yes, proceed')
        history = guard.review_request(self.data, self.state(), {})['assistant_context'][-1]
        self.assertEqual(history['response'], proposal)
        self.assertFalse(history['truncated'])
        self.assertTrue(history['earlier_messages_truncated'])
        self.assertLessEqual(len(history['response']) + sum(len(item['text']) for item in history['earlier_messages']),
                             guard.MAX_RESULT_CHARS)

    def test_oversized_final_proposal_remains_explicitly_truncated(self):
        self.prompt('Propose one change and wait')
        self.hook('MessageDisplay', message_id='earlier', index=0, final=True, delta='An older proposal.')
        with mock.patch.object(turn_review, 'review', return_value={'ok': True, 'reason': ''}):
            self.hook('Stop', last_assistant_message='x' * (guard.MAX_RESULT_CHARS + 1))
        self.prompt('Yes, proceed')
        history = guard.review_request(self.data, self.state(), {})['assistant_context'][-1]
        self.assertTrue(history['truncated'])
        self.assertEqual(len(history['response']), guard.MAX_RESULT_CHARS)
        self.assertTrue(history['earlier_messages'][0]['truncated'])
        self.assertEqual(history['earlier_messages'][0]['text'], '')

    def test_incomplete_earlier_display_does_not_mark_the_final_proposal_truncated(self):
        self.prompt('Propose one change and wait')
        self.hook('MessageDisplay', message_id='earlier', index=0, final=False, delta='Partial notes')
        proposal = 'Change reader.py only.'
        with mock.patch.object(turn_review, 'review', return_value={'ok': True, 'reason': ''}):
            self.hook('Stop', last_assistant_message=proposal, _response_coverage='final-message')
        self.prompt('Yes, proceed')
        history = guard.review_request(self.data, self.state(), {})['assistant_context'][-1]
        self.assertEqual(history['response'], proposal)
        self.assertFalse(history['truncated'])
        self.assertTrue(history['earlier_messages_truncated'])

    def test_recent_proposal_survives_history_and_display_limits(self):
        for count, size in ((1, 9000), (1, guard.MAX_RESPONSE_CHARS + 1), (70, 20)):
            with self.subTest(count=count, size=size):
                self.prompt('Propose one change and wait')
                research = 'Earlier research. ' + 'x' * size
                for index in range(count):
                    self.hook('MessageDisplay', message_id=f'research-{index}', index=0, final=True, delta=research)
                proposal = 'Change reader.py only; leave writer.py untouched.'
                self.hook('MessageDisplay', message_id='proposal', index=0, final=False, delta=proposal[:20])
                self.hook('MessageDisplay', message_id='proposal', index=1, final=True, delta=proposal[20:])
                self.hook('MessageDisplay', message_id='final', index=0, final=True, delta='Waiting for approval.')
                with mock.patch.object(turn_review, 'review', return_value={'ok': True, 'reason': ''}) as reviewer:
                    self.hook('Stop', last_assistant_message='Waiting for approval.')
                self.assertTrue(reviewer.call_args.args[1]['candidate']['earlier_messages'].startswith('Earlier research.'))
                self.prompt('Yes, proceed')
                history = guard.review_request(self.data, self.state(), {})['assistant_context'][-1]
                self.assertIn(proposal, json.dumps(history))
                retained = next(item for item in history['earlier_messages'] if item['text'] == proposal)
                self.assertFalse(retained['truncated'])
                self.assertTrue(history['earlier_messages_omitted'])
                self.assertLessEqual(len(history['response']) + sum(len(item['text']) for item in history['earlier_messages']),
                                     guard.MAX_RESULT_CHARS)

    def test_partial_recent_proposal_stays_incomplete(self):
        for index, text in ((1, 'Missing the proposal prefix.'), (0, 'New proposal. ' * guard.MAX_RESULT_CHARS)):
            with self.subTest(index=index):
                self.prompt('Propose one change and wait')
                self.hook('MessageDisplay', message_id='older', index=0, final=True, delta='An older proposal.')
                self.hook('MessageDisplay', message_id='proposal', index=index, final=True, delta=text)
                with mock.patch.object(turn_review, 'review', return_value={'ok': True, 'reason': ''}):
                    self.hook('Stop', last_assistant_message='Waiting for approval.')
                self.prompt('Yes, proceed')
                history = guard.review_request(self.data, self.state(), {})['assistant_context'][-1]
                self.assertTrue(history['earlier_messages'][-1]['truncated'])

    def test_recent_proposals_do_not_leak_into_new_turns_or_children(self):
        self.prompt('Propose a change')
        self.hook('MessageDisplay', message_id='proposal', index=0, final=True, delta='An old proposal.')
        self.hook('SubagentStart', agent_id='child')
        with guard.store_for({**self.data, 'agent_id': 'child'}) as store:
            self.assertEqual(store.get(guard.CATEGORY, 'state')['recent_messages'], [])
        self.prompt('Explain a separate topic')
        self.assertEqual(self.state()['recent_messages'], [])

    def test_native_failure_preserves_diagnostics(self):
        self.prompt()
        self.hook('PostToolUseFailure', tool_name='Bash', tool_input={'command': 'pytest'},
                  error='ModuleNotFoundError: example', is_interrupt=False)
        item = self.state()['observations'][0]
        self.assertFalse(item['success'])
        self.assertIn('ModuleNotFoundError', item['result'])

    def test_compaction_recovers_on_a_tool_result_without_a_new_prompt(self):
        self.prompt('Why does this happen?')
        identity = self.state()['id']
        self.hook('PreCompact')
        output = self.hook('PostToolUse', tool_name='Read', tool_input={'file_path': 'source.py'}, tool_response='source')
        self.assertIn(QUESTION_CONTRACT, str(output))
        self.assertTrue(self.state()['bootstrapped'])
        self.assertEqual(self.state()['id'], identity)
        self.assertIsNone(self.hook('PostToolUse', tool_name='Read', tool_input={'file_path': 'source.py'}, tool_response='source'))

    def test_transient_reviewer_failure_can_recover(self):
        self.prompt()
        with mock.patch.object(turn_review, 'review', side_effect=RuntimeError('temporary')), mock.patch('sys.stderr'):
            self.assertIsNotNone(self.tool())
        with mock.patch.object(turn_review, 'review', return_value={'ok': True, 'reason': ''}) as recovered:
            self.assertIsNone(self.tool())
        recovered.assert_called_once()

    def test_large_documentation_input_does_not_poison_later_reviews(self):
        self.prompt()
        self.hook('PostToolUse', tool_name='WebFetch',
                  tool_input={'url': 'https://example.com', 'prompt': 'x' * 100_000}, tool_response='Reference.')
        self.assertLessEqual(len(json.dumps(self.state()['docs'])), guard.MAX_EVIDENCE_CHARS)
        self.prompt('Create the requested file')
        self.assertIsNone(self.tool())

    def test_combined_context_fits_without_truncating_the_request_or_candidate(self):
        self.prompt('Implement ' + 'x' * 12_000)
        for index in range(4):
            self.hook('PostToolUse', tool_name='WebFetch', tool_input={'url': f'https://example.com/{index}'},
                      tool_response='d' * 7_000)
            self.hook('PostToolUse', tool_name='Read', tool_input={'file_path': f'{index}.py'},
                      tool_response='s' * 7_000)
        candidate = {'kind': 'tool', 'tool': 'Write', 'input': {'content': 'c' * 20_000}}
        request = guard.review_request(self.data, self.state(), candidate)
        self.assertEqual(request['latest_request'], self.state()['prompt'])
        self.assertEqual(request['candidate'], candidate)
        self.assertLessEqual(len((turn_review.POLICY + '\n\n' + json.dumps(request)).encode()),
                             turn_review.MAX_INPUT_BYTES)
        self.assertTrue(request['omitted_context'])

    def test_private_reviewer_payload_is_only_sent_on_stdin(self):
        for harness in ('claude', 'codex', 'copilot'):
            argv, stdin = turn_review.command(harness, 'PRIVATE_FIXTURE')
            self.assertNotIn('PRIVATE_FIXTURE', ' '.join(argv))
            self.assertIn('PRIVATE_FIXTURE', stdin)

    def test_display_messages_are_checked_without_altering_display(self):
        self.prompt('Why does this happen?')
        self.assertIsNone(self.hook('MessageDisplay', message_id='first', index=0, final=False, delta='Unrequested '))
        self.assertIsNone(self.hook('MessageDisplay', message_id='first', index=1, final=True, delta='plan.'))
        self.hook('MessageDisplay', message_id='last', index=0, final=True, delta='The actual answer.')
        with mock.patch.object(turn_review, 'review', return_value={'ok': True, 'reason': ''}) as reviewer:
            self.hook('Stop', last_assistant_message='The actual answer.')
        self.assertIn('Unrequested plan.', json.dumps(reviewer.call_args.args[1]['candidate']))

    def test_final_only_review_does_not_claim_whole_turn_success(self):
        self.prompt()
        with mock.patch.object(turn_review, 'review', return_value={'ok': True, 'reason': ''}):
            output = self.hook('Stop', _response_coverage='final-message', last_assistant_message='Done.')
        self.assertIn('earlier assistant', output['systemMessage'])
        self.assertFalse(self.state()['last_review']['ok'])
        self.assertTrue(self.state()['last_review']['candidate_ok'])

    def test_missing_display_batch_is_explicitly_partial(self):
        self.prompt()
        self.hook('MessageDisplay', message_id='answer', index=1, final=True, delta='Done.')
        with mock.patch.object(turn_review, 'review', return_value={'ok': True, 'reason': ''}):
            output = self.hook('Stop', _response_coverage='final-message', last_assistant_message='Done.')
        self.assertIn('incomplete', output['systemMessage'])

    def test_sigterm_reaps_the_reviewer(self):
        code = (
            'import subprocess,sys,turn_review\n'
            'original=subprocess.Popen\n'
            'def launch(*args,**kwargs):\n'
            '    child=original(*args,**kwargs)\n'
            '    print(child.pid,flush=True)\n'
            '    return child\n'
            'subprocess.Popen=launch\n'
            'turn_review.run_command([sys.executable,"-c","import time; time.sleep(30)"],None)\n'
        )
        child_pid = None
        worker = subprocess.Popen([sys.executable, '-c', code], cwd=Path(guard.__file__).parent,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertTrue(select.select([worker.stdout], [], [], 5)[0])
            child_pid = int(worker.stdout.readline())
            worker.terminate()
            worker.communicate(timeout=5)
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline and process_exists(child_pid):
                time.sleep(0.02)
            self.assertFalse(process_exists(child_pid), 'reviewer survived hook cancellation')
        finally:
            if worker.poll() is None:
                worker.kill()
            worker.communicate()
            if child_pid and process_exists(child_pid):
                os.kill(child_pid, signal.SIGKILL)

    def test_timeout_cleans_children_after_reviewer_leader_exits(self):
        code = (
            'import subprocess,sys\n'
            'child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"])\n'
            'print(child.pid,flush=True)\n'
        )
        child_pid = None
        process = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            self.assertTrue(select.select([process.stdout], [], [], 5)[0])
            child_pid = int(process.stdout.readline())
            self.assertTrue(process_stopped(process.pid), 'fixture leader has not exited')
            started = time.monotonic()
            with (
                mock.patch.object(turn_review.subprocess, 'Popen', return_value=process),
                mock.patch.object(turn_review, 'REVIEW_TIMEOUT', 0.1),
                self.assertRaises(subprocess.TimeoutExpired),
            ):
                turn_review.run_command([sys.executable, '-c', code], None)
            self.assertLess(time.monotonic() - started, 2)
            self.assertTrue(process_stopped(child_pid), 'reviewer grandchild survived timeout cleanup')
        finally:
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if child_pid and process_exists(child_pid):
                try:
                    os.kill(child_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.communicate(timeout=5)

    def test_emdash_block_survives_unavailable_turn_state(self):
        cache = Path(self.env['HOME']) / '.cache'
        cache.mkdir(parents=True)
        (cache / 'ioncache-ai-tools').write_text('not a directory')
        result = subprocess.run(
            [sys.executable, block_emdash_turn.__file__],
            input=json.dumps({**self.data, 'last_assistant_message': f'Bad{chr(0x2014)}punctuation'}),
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['decision'], 'block')
        self.assertIn('continuation', result.stderr)

    def test_emdash_correction_preserves_the_question_turn(self):
        self.prompt('Why does this happen?')
        identity = self.state()['id']
        result = subprocess.run(
            [sys.executable, block_emdash_turn.__file__],
            input=json.dumps({**self.data, 'last_assistant_message': f'Bad{chr(0x2014)}punctuation'}),
            capture_output=True, text=True, check=True,
        )
        self.assertIsNone(self.prompt(json.loads(result.stdout)['reason']))
        self.assertEqual(self.state()['id'], identity)
        self.assertTrue(self.state()['question'])

    def test_hyphenated_mcp_mutation_cannot_bypass_question_or_scope_checks(self):
        fields = {'tool_name': 'mcp__issues__create-issue', 'tool_input': {'title': 'Unrequested'}}
        self.prompt('Why does this happen?')
        with mock.patch.object(turn_review, 'review') as reviewer:
            self.assertIn('answer-only', str(self.hook('PreToolUse', **fields)))
        reviewer.assert_not_called()
        self.prompt('Explain the current issue')
        with mock.patch.object(turn_review, 'review', return_value={'ok': False, 'reason': 'Unrequested issue.'}) as reviewer:
            self.assertIn('Unrequested issue', str(self.hook('PreToolUse', **fields)))
        reviewer.assert_called_once()

    def test_read_only_mcp_suffix_does_not_block_or_invalidate_observations(self):
        self.prompt('What is the latest update?')
        self.hook('PostToolUse', tool_name='Read', tool_input={'file_path': 'source.py'}, tool_response='source')
        fields = {'tool_name': 'mcp__srv__get-latest-update', 'tool_input': {}}
        with mock.patch.object(turn_review, 'review') as reviewer:
            self.assertIsNone(self.hook('PreToolUse', **fields))
            self.hook('PostToolUse', **fields, tool_response='Latest update')
        reviewer.assert_not_called()
        self.assertEqual(self.state()['mutation'], 0)
        self.assertEqual([item['tool'] for item in self.state()['observations']], ['Read', fields['tool_name']])

    def test_question_contract_is_complete_without_skill_invocation(self):
        self.hook('SessionStart')
        text = self.prompt('Why does this happen?')['hookSpecificOutput']['additionalContext']
        self.assertEqual(text, QUESTION_CONTRACT)
        self.assertNotIn('skill', text)
        self.assertNotIn('before', text)
        with mock.patch.object(turn_review, 'review') as reviewer:
            self.assertEqual(self.tool()['hookSpecificOutput']['permissionDecision'], 'deny')
        reviewer.assert_not_called()
        self.assertIsNone(self.hook('PreToolUse', tool_name='WebFetch', tool_input={'url': 'https://example.com'}))

    def test_bootstrap_fallback_for_hosts_without_session_start(self):
        self.assertIn(guard.BOOTSTRAP, str(self.prompt()))
        self.assertIsNone(self.prompt('Continue the implementation'))

    def test_compaction_preserves_question_and_evidence_state(self):
        self.prompt('Why does this happen?')
        identity = self.state()['id']
        self.hook('PreCompact')
        self.assertTrue(marker_path(self.data).exists())
        text = self.hook('SessionStart', source='compact')['hookSpecificOutput']['additionalContext']
        self.assertIn(QUESTION_CONTRACT, text)
        self.assertEqual(self.state()['id'], identity)
        self.assertTrue(self.state()['question'])

    def test_correction_is_not_a_new_user_authorization(self):
        self.prompt('Why does this happen?')
        identity = self.state()['id']
        rejected = {'ok': False, 'reason': 'The draft was not requested.'}
        with mock.patch.object(turn_review, 'review', return_value=rejected):
            output = self.hook('Stop', last_assistant_message='Because X. Here is a replacement design.')
            self.assertEqual(output['decision'], 'block')
            self.assertIsNone(self.prompt(output['reason']))
            self.assertEqual(self.state()['id'], identity)
            self.assertEqual(self.state()['stop_attempts'], 1)
            output = self.hook('Stop', last_assistant_message='Still an unsolicited design.')
            self.assertIn(guard.UNVERIFIED, output['systemMessage'])
            self.assertNotIn('decision', output)
        self.assertTrue(marker_path(self.data).exists())

    def test_requested_artifact_and_question_are_supplied_to_reviewer(self):
        self.prompt('What would a draft of this message look like?')
        with mock.patch.object(turn_review, 'review', return_value={'ok': True, 'reason': ''}) as reviewer:
            self.assertIsNone(self.hook('Stop', last_assistant_message='The explicitly requested draft.'))
        request = reviewer.call_args.args[1]
        self.assertTrue(request['question_only'])
        self.assertEqual(request['latest_request'], self.state()['prompt'])
        self.assertEqual(request['candidate']['text'], 'The explicitly requested draft.')

    def test_denials_are_cached_until_candidate_or_evidence_changes(self):
        self.prompt()
        with mock.patch.object(turn_review, 'review', return_value={'ok': False, 'reason': 'Unrequested change.'}) as reviewer:
            for _ in range(3):
                self.assertEqual(self.tool()['hookSpecificOutput']['permissionDecision'], 'deny')
            self.assertEqual(reviewer.call_count, 1)
            self.hook('PostToolUse', tool_name='Read', tool_input={'file_path': 'target.py'}, tool_response='new evidence')
            self.tool()
            self.assertEqual(reviewer.call_count, 2)

    def test_repeated_successful_stop_does_not_repeat_model_call(self):
        self.prompt()
        with mock.patch.object(turn_review, 'review', return_value={'ok': True, 'reason': ''}) as reviewer:
            self.hook('Stop', last_assistant_message='Requested result.')
            self.hook('Stop', last_assistant_message='Requested result.')
        self.assertEqual(reviewer.call_count, 1)

    def test_other_hook_continuations_cannot_restart_review_budget(self):
        self.prompt()
        with mock.patch.object(turn_review, 'review', return_value={'ok': False, 'reason': 'Unrequested draft.'}) as reviewer:
            for index in range(5):
                self.hook('Stop', last_assistant_message=f'Different unsolicited draft {index}.')
        self.assertEqual(reviewer.call_count, 2)
        self.assertFalse(self.state()['last_review']['ok'])

    def test_exhausted_budget_does_not_request_an_unreviewable_correction(self):
        self.prompt()
        with mock.patch.object(turn_review, 'review', return_value={'ok': True, 'reason': ''}) as reviewer:
            self.assertIsNone(self.hook('Stop', last_assistant_message='First answer.'))
            self.assertIsNone(self.hook('Stop', last_assistant_message='Second answer.'))
            output = self.hook('Stop', last_assistant_message='Changed by another hook.')
        self.assertIn('budget', output['systemMessage'])
        self.assertNotIn('decision', output)
        self.assertEqual(self.state()['stop_attempts'], 0)
        self.assertEqual(reviewer.call_count, 2)

    def test_unavailable_state_warns_at_stop_but_denies_mutations(self):
        cache = Path(self.env['HOME']) / '.cache'
        cache.mkdir(parents=True)
        (cache / 'ioncache-ai-tools').write_text('not a directory')
        data = {**self.data, 'agent_id': 'fixture-child', 'tool_name': 'Write',
                'tool_input': {'file_path': 'target.py', 'content': 'new'}}
        for event in ('Stop', 'SubagentStop', 'PreToolUse'):
            result = subprocess.run(
                [sys.executable, guard.__file__, event], input=json.dumps(data),
                capture_output=True, text=True, check=False,
            )
            if event == 'PreToolUse':
                self.assertEqual(result.returncode, 2)
            else:
                self.assertEqual(result.returncode, 0)
                self.assertIn(guard.UNVERIFIED, json.loads(result.stdout)['systemMessage'])

    def test_symlink_loop_runtime_error_exits_with_blocking_status(self):
        self.prompt('Explain the code flow')
        loop = self.project / 'loop'
        loop.symlink_to(loop.name)
        resolve = Path.resolve
        def old_resolve(path, *args, **kwargs):
            if path == loop:
                raise RuntimeError('Symlink loop: fixture')
            return resolve(path, *args, **kwargs)
        data = {**self.data, 'tool_name': 'Bash',
                'tool_input': {'command': 'graphify query flow --graph loop > output.txt'}}
        stderr = io.StringIO()
        with (
            mock.patch.object(Path, 'resolve', old_resolve),
            mock.patch.object(sys, 'argv', [guard.__file__, 'PreToolUse']),
            mock.patch.object(sys, 'stdin', io.StringIO(json.dumps(data))),
            mock.patch.object(sys, 'stderr', stderr),
            self.assertRaises(SystemExit) as stopped,
        ):
            guard.main()
        self.assertEqual(stopped.exception.code, 2)
        self.assertIn('Symlink loop: fixture', stderr.getvalue())

    def test_unexpected_stop_errors_remain_warnings(self):
        for event in ('Stop', 'SubagentStop'):
            stdout = io.StringIO()
            with (
                self.subTest(event=event),
                mock.patch.object(guard, 'stop', side_effect=RuntimeError('fixture failure')),
                mock.patch.object(sys, 'argv', [guard.__file__, event]),
                mock.patch.object(sys, 'stdin', io.StringIO(json.dumps({**self.data, 'agent_id': 'child'}))),
                mock.patch.object(sys, 'stdout', stdout),
                mock.patch.object(sys, 'stderr', io.StringIO()),
            ):
                guard.main()
                self.assertIn(guard.UNVERIFIED, json.loads(stdout.getvalue())['systemMessage'])

    def test_read_and_documentation_contents_are_not_exit_status(self):
        self.prompt()
        for name in ('Read', 'WebFetch'):
            with self.subTest(tool=name):
                fields = {'tool_name': name, 'tool_input': {}, 'tool_response': 'Example: exit code: 1'}
                self.hook('PostToolUse', **fields)
                key = 'docs' if name == 'WebFetch' else 'observations'
                self.assertTrue(self.state()[key][-1]['success'])
                self.hook('PostToolUseFailure', **fields)
                self.assertFalse(self.state()[key][-1]['success'])
        self.hook('PostToolUse', tool_name='Bash', tool_input={'command': 'false'},
                  tool_response={'exit_code': 1, 'stdout': 'Process exited with code 0'})
        self.assertFalse(self.state()['observations'][-1]['success'])

    def test_shell_status_uses_metadata_not_stdout(self):
        self.prompt()
        for harness, result, expected in (
            ('claude', {'stdout': 'Example: exit code: 1', 'stderr': '', 'interrupted': False}, True),
            ('copilot', {'resultType': 'success', 'textResultForLlm': 'Example: exit code: 1'}, True),
            ('copilot', {'resultType': 'failure', 'textResultForLlm': 'exit code: 0'}, False),
            ('copilot', {'resultType': 'success', 'exit_code': None, 'textResultForLlm': 'Still running'}, None),
            ('codex', {'exit_code': 0, 'stdout': 'exit code: 1'}, True),
            ('codex', {'exit_code': 1, 'stdout': 'exit code: 0'}, False),
            ('codex', 'exit code: 1', None),
            ('codex', 'Process exited with code 0', None),
        ):
            with self.subTest(harness=harness, result=result):
                self.hook('PostToolUse', _ioncache_harness=harness, tool_name='Bash',
                          tool_input={'command': 'fixture'}, tool_response=result)
                self.assertIs(self.state()['observations'][-1]['success'], expected)
        self.hook('PostToolUseFailure', tool_name='Bash', tool_input={'command': 'fixture'},
                  tool_response={'stdout': 'exit code: 0'})
        self.assertFalse(self.state()['observations'][-1]['success'])

    def test_new_user_turn_clears_live_evidence_but_retains_applicable_docs(self):
        self.prompt()
        self.hook('PostToolUse', tool_name='Bash', tool_input={'command': 'git status'}, tool_response='clean')
        self.hook('PostToolUse', tool_name='WebFetch', tool_input={'url': 'https://example.com/v2'},
                  tool_response={'code': 200, 'result': 'Version 2 reference.'})
        self.prompt('Continue the fix')
        self.assertEqual(self.state()['observations'], [])
        self.assertEqual(len(self.state()['docs']), 1)
        self.assertEqual(self.state()['requests'][-2:], ['Implement the requested fix', 'Continue the fix'])

    def test_mutation_invalidates_live_evidence_and_reviews(self):
        self.prompt()
        self.hook('PostToolUse', tool_name='Bash', tool_input={'command': 'git status'}, tool_response='clean')
        self.tool()
        self.tool('PostToolUse', tool_response={'success': True})
        state = self.state()
        self.assertEqual(state['mutation'], 1)
        self.assertEqual(state['reviews'], {})
        self.assertEqual([item['tool'] for item in state['observations']], ['Write'])

    def test_external_file_change_invalidates_observation(self):
        path = self.project / 'source.py'
        path.write_text('before')
        self.prompt()
        self.hook('PostToolUse', tool_name='Read', tool_input={'file_path': 'source.py'}, tool_response='before')
        path.write_text('after, changed elsewhere')
        request = guard.review_request(self.data, self.state(), {})
        self.assertFalse(request['observations'][0]['unchanged'])

    def test_failed_empty_and_truncated_results_are_not_proof_of_coverage(self):
        self.prompt()
        self.hook('PostToolUse', tool_name='WebFetch', tool_input={'url': 'https://example.com'},
                  tool_response={'code': 404, 'result': ''})
        self.assertFalse(self.state()['docs'][0]['success'])
        self.hook('PostToolUse', tool_name='Read', tool_input={'file_path': 'large.py'},
                  tool_response='x' * 20000)
        item = self.state()['observations'][0]
        self.assertTrue(item['truncated'])
        self.assertLessEqual(len(item['result']), guard.MAX_RESULT_CHARS)

    def test_cache_delivery_records_source_and_original_fetch_age(self):
        self.prompt()
        fetched = time.time() - 86400
        url = 'https://example.com/api/v2'
        docs_cache.store_fact(docs_cache.cache_key(url, None), url, 'Only this detail.', 'claude',
                              now=fetched, source={'reference_only': True})
        output = docs_cache.claude_pre({**self.data, 'tool_name': 'WebFetch',
                                       'tool_input': {'url': url, 'prompt': 'Specific detail'}})
        self.assertIn('Only this detail.', str(output))
        item = self.state()['docs'][0]
        self.assertTrue(item['cached_summary'])
        self.assertEqual(item['observed_at'], fetched)
        self.assertEqual(item['input']['url'], url)

    def test_expired_docs_are_not_supplied_to_reviewer(self):
        self.prompt()
        guard.record_cache({**self.data, 'tool_name': 'WebFetch', 'tool_input': {'url': 'https://example.com'}},
                           [{'fetched_at': time.time() - docs_cache.TTL_SECONDS - 1}], 'Old detail')
        self.assertEqual(guard.review_request(self.data, self.state(), {})['documentation'], [])

    def test_graph_discovery_requires_a_real_completed_query(self):
        self.graph()
        self.prompt('Explain the code flow')
        with mock.patch.object(guard.shutil, 'which', return_value='/bin/graphify'):
            denied = self.hook('PreToolUse', tool_name='Grep', tool_input={'pattern': 'entry'})
            self.assertIn('graphify query', str(denied))
            self.hook('PostToolUse', tool_name='Bash',
                      tool_input={'command': 'echo graphify query flow'}, tool_response='fake query')
            self.assertIsNotNone(self.hook('PreToolUse', tool_name='Grep', tool_input={}))
            query = {'tool_name': 'Bash', 'tool_input': {'command': 'graphify query "entry flow"'}}
            self.hook('PreToolUse', **query)
            self.hook('PostToolUse', **query, tool_response={'exit_code': 0, 'stdout': 'entry.py'})
            self.assertIsNone(self.hook('PreToolUse', tool_name='Grep', tool_input={}))

    def test_graph_help_other_graph_and_changed_graph_do_not_unlock_discovery(self):
        graph = self.graph()
        self.prompt()
        for command in ('graphify query --help', 'graphify query --help --graph graphify-out/graph.json',
                        'graphify query flow --graph other.json', 'echo graphify query flow'):
            self.assertFalse(guard.graph_query({**self.data, 'tool_name': 'Bash', 'tool_input': {'command': command}}))
        query = {'tool_name': 'Bash', 'tool_input': {'command': 'graphify query flow'}}
        self.hook('PreToolUse', **query)
        graph.write_text('{"changed":true}')
        self.hook('PostToolUse', **query, tool_response={'exit_code': 0})
        with mock.patch.object(guard.shutil, 'which', return_value='/bin/graphify'):
            self.assertIsNotNone(self.hook('PreToolUse', tool_name='Grep', tool_input={}))

    def test_missing_and_failed_graph_queries_have_bounded_fallback(self):
        self.graph()
        self.prompt()
        with mock.patch.object(guard.shutil, 'which', return_value=None):
            self.assertIn('unavailable', str(self.hook('PreToolUse', tool_name='Grep', tool_input={})))
            self.assertIsNone(self.hook('PreToolUse', tool_name='Grep', tool_input={}))
        self.prompt()
        query = {'tool_name': 'Bash', 'tool_input': {'command': 'graphify query absent'}}
        self.hook('PreToolUse', **query)
        self.hook('PostToolUseFailure', **query, tool_response={'error': 'no match', 'exit_code': 4})
        self.assertIsNone(self.hook('PreToolUse', tool_name='Grep', tool_input={}))

    def test_unreadable_graph_does_not_permanently_block_source_discovery(self):
        graph = self.graph()
        self.prompt()
        stat = Path.stat
        def guarded_stat(path, *args, **kwargs):
            if path == graph:
                raise PermissionError('unreadable graph directory')
            return stat(path, *args, **kwargs)
        with mock.patch.object(Path, 'stat', guarded_stat):
            self.assertIn('unavailable', str(self.hook('PreToolUse', tool_name='Grep', tool_input={})))
            self.assertIsNone(self.hook('PreToolUse', tool_name='Grep', tool_input={}))

    def test_shell_wrappers_without_an_executable_are_not_discovery(self):
        self.prompt()
        self.assertIsNone(self.hook('PreToolUse', tool_name='Bash', tool_input={'command': 'env -i'}))

    def test_rule_disable_settings_apply_to_bootstrap_and_reviews(self):
        config = self.project / '.claude/ioncache-ai-tools.local.json'
        config.parent.mkdir()
        config.write_text(json.dumps({'disabledRules': ['scope-exactly-what-asked', 'verify-state-before-claiming']}))
        scope_rule = Path(guard.__file__).parents[1] / 'rules/scope-exactly-what-asked.json'
        self.assertNotIn(json.loads(scope_rule.read_text())['message'], str(self.prompt()))
        request = guard.review_request(self.data, self.state(), {})
        self.assertFalse(request['scope'])
        self.assertFalse(request['live_state'])

    def test_state_survives_cwd_change_without_reusing_another_graph(self):
        self.prompt('Why does this happen?')
        other = self.root / 'other'
        other.mkdir()
        output = guard.pre_tool({**self.data, 'cwd': str(other), 'tool_name': 'Write',
                                 'tool_input': {'file_path': 'target.py', 'content': 'new'}})
        self.assertEqual(output['hookSpecificOutput']['permissionDecision'], 'deny')

    def test_child_bootstrap_does_not_reset_parent_request(self):
        self.prompt('Why does this happen?')
        identity = self.state()['id']
        self.hook('SubagentStart', agent_id='child')
        with guard.store_for({**self.data, 'agent_id': 'child'}) as store:
            child = store.get(guard.CATEGORY, 'state')
        self.assertTrue(child['question'])
        self.assertEqual(self.state()['id'], identity)
        self.hook('SubagentStart')
        self.assertEqual(self.state()['id'], identity)

    def test_parallel_observations_do_not_overwrite_each_other(self):
        self.prompt()
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(lambda index: self.hook(
                'PostToolUse', tool_name='Read', tool_input={'file_path': f'{index}.txt'}, tool_response=str(index)
            ), range(8)))
        self.assertEqual(len(self.state()['observations']), 8)

    def test_child_cannot_reuse_permission_after_parent_request_changes(self):
        self.prompt()
        self.hook('SubagentStart', agent_id='child')
        self.prompt('Stop editing and summarize the findings')
        with mock.patch.object(turn_review, 'review') as reviewer:
            output = self.hook('PreToolUse', agent_id='child', tool_name='Write',
                               tool_input={'file_path': 'target.py', 'content': 'extra'})
        self.assertIn('parent user request changed', str(output))
        reviewer.assert_not_called()

    def test_child_without_start_event_is_initialized_from_parent_request(self):
        self.prompt('Why does this happen?')
        output = self.hook('PreToolUse', agent_id='unannounced-child', tool_name='Write',
                           tool_input={'file_path': 'target.py', 'content': 'extra'})
        self.assertIn('answer-only', str(output))
        self.hook('PostToolUse', agent_id='unannounced-child', tool_name='Read',
                  tool_input={'file_path': 'source.py'}, tool_response='value')
        with guard.store_for({**self.data, 'agent_id': 'unannounced-child'}) as store:
            child = store.get(guard.CATEGORY, 'state')
        self.assertEqual(len(child['observations']), 1)
        self.assertEqual(self.state()['observations'], [])
        self.assertEqual(child['parent_turn'], self.state()['id'])

    def test_anonymous_child_stop_does_not_consume_parent_review_budget(self):
        self.prompt()
        previous = self.state()
        with mock.patch.object(turn_review, 'review') as reviewer:
            output = self.hook('SubagentStop', last_assistant_message='Child result.')
        self.assertIn('subagent identity', output['systemMessage'])
        self.assertEqual(self.state(), previous)
        reviewer.assert_not_called()

    def test_delegation_is_reviewed_without_forbidding_read_only_research(self):
        self.prompt('Why does this fail?')
        with mock.patch.object(turn_review, 'review', return_value={'ok': True, 'reason': ''}) as reviewer:
            self.assertIsNone(self.hook('PreToolUse', tool_name='Agent',
                                       tool_input={'prompt': 'Read source to explain the failure.'}))
        self.assertTrue(reviewer.call_args.args[1]['question_only'])

    def test_shell_source_reads_and_json_reads_cannot_skip_graph_discovery(self):
        self.graph()
        (self.project / 'manifest.json').write_text('{}')
        self.prompt()
        with mock.patch.object(guard.shutil, 'which', return_value='/bin/graphify'):
            self.assertIsNotNone(self.hook('PreToolUse', tool_name='Bash',
                                          tool_input={'command': 'cat manifest.json'}))
            self.assertIsNotNone(self.hook('PreToolUse', tool_name='Read',
                                          tool_input={'file_path': 'manifest.json'}))
        self.assertIsNone(self.hook('PreToolUse', tool_name='Read',
                                   tool_input={'file_path': str(self.root / 'external-docs.txt')}))

    def test_session_end_cleans_child_markers_without_dropping_resume_context(self):
        self.prompt('Why?')
        child = {**self.data, 'agent_id': 'child'}
        self.addCleanup(lambda: marker_path(child).unlink(missing_ok=True))
        self.hook('SubagentStart', agent_id='child')
        self.hook('UserPromptSubmit', agent_id='child', prompt='Read the source')
        self.assertTrue(marker_path(child).exists())
        self.hook('SessionEnd')
        self.assertFalse(marker_path(child).exists())
        self.assertEqual(self.state()['prompt'], 'Why?')

    def test_oversized_request_history_is_explicitly_incomplete(self):
        self.prompt('Implement ' + 'x' * guard.MAX_REQUEST_CHARS)
        self.prompt('Continue')
        request = guard.review_request(self.data, self.state(), {})
        self.assertTrue(request['request_context_incomplete'])
        self.assertEqual(request['latest_request'], 'Continue')

    def test_state_changes_during_review_do_not_approve_a_mutation(self):
        self.prompt()
        def changed(harness, request):
            self.hook('PostToolUse', tool_name='Read', tool_input={'file_path': 'new.txt'}, tool_response='new')
            return {'ok': True, 'reason': ''}
        with mock.patch.object(turn_review, 'review', side_effect=changed):
            self.assertIn('changed during review', str(self.tool()))

    def test_lookup_permissions_survive_unavailable_state_store(self):
        with mock.patch.object(guard, 'store_for', side_effect=PermissionError('unavailable')):
            self.assertIsNone(self.hook('PreToolUse', tool_name='WebFetch', tool_input={}))

    def test_reviewer_failure_denies_mutations_and_bounds_stop_feedback(self):
        self.prompt()
        with mock.patch.object(turn_review, 'review', side_effect=subprocess.TimeoutExpired('fixture', 60)), \
                mock.patch.object(sys, 'stderr'):
            self.assertIn('checker is unavailable', str(self.tool()))
            self.assertEqual(self.hook('Stop', last_assistant_message='Done.')['decision'], 'block')
            self.assertIn('systemMessage', self.hook('Stop', last_assistant_message='Done.'))

    def test_reviewer_protocol_and_default_host_model(self):
        for harness in ('claude', 'codex', 'copilot'):
            with self.subTest(harness=harness):
                self.assertEqual(turn_review.review(harness, {'candidate': 'fixture'}), {'ok': True, 'reason': ''})
                command, _ = turn_review.command(harness, 'fixture')
                self.assertNotIn('--model', command)
                self.assertNotIn('-m', command)
        for value in ('not JSON', '[]', '{"ok":"true","reason":""}', '{"ok":false,"reason":""}',
                      '{"ok":true,"reason":"Cannot verify this."}'):
            with self.subTest(value=value), mock.patch.dict(os.environ, {'REVIEW_FIXTURE_RESULT': value}):
                with self.assertRaises(ValueError):
                    turn_review.review('claude', {})

    def test_unsupported_reviewer_options_report_upgrade_without_exposing_stderr(self):
        self.prompt()
        cases = (
            ('claude', "error: unknown option '--safe-mode'", '2.1.169'),
            ('codex', "error: unexpected argument '--ignore-user-config' found", '0.122.0'),
            ('copilot', 'error: unknown flag: --available-tools', 'Copilot CLI'),
        )
        for harness, error, requirement in cases:
            with (
                self.subTest(harness=harness),
                mock.patch.dict(os.environ, {'REVIEW_FIXTURE_ERROR': error + '\nPRIVATE_FIXTURE_DETAIL'}),
                mock.patch.object(sys, 'stderr', io.StringIO()) as stderr,
            ):
                output = self.tool(_ioncache_harness=harness)['hookSpecificOutput']
                self.assertEqual(output['permissionDecision'], 'deny')
                self.assertIn('Upgrade', output['permissionDecisionReason'])
                self.assertIn(requirement, output['permissionDecisionReason'])
                self.assertNotIn('PRIVATE_FIXTURE_DETAIL', str(output) + stderr.getvalue())
        self.assertEqual(self.state()['reviews'], {})
        self.assertIsNone(self.tool())

    def test_other_reviewer_failures_are_not_reported_as_an_unsupported_cli(self):
        self.prompt()
        for error in ('Authentication failed', 'Invalid argument: prompt cannot be empty'):
            with (
                self.subTest(error=error),
                mock.patch.dict(os.environ, {'REVIEW_FIXTURE_ERROR': error + '\nPRIVATE_FIXTURE_DETAIL'}),
                mock.patch.object(sys, 'stderr', io.StringIO()) as stderr,
            ):
                output = self.tool()
            self.assertIn('semantic checker is unavailable', str(output))
            self.assertNotIn('Upgrade', str(output))
            self.assertNotIn('PRIVATE_FIXTURE_DETAIL', str(output) + stderr.getvalue())

    def test_reviewer_budget_fails_before_launch(self):
        with mock.patch.object(turn_review, 'run_command') as run:
            with self.assertRaisesRegex(ValueError, 'byte budget'):
                turn_review.review('claude', {'candidate': 'x' * turn_review.MAX_INPUT_BYTES})
        run.assert_not_called()

    def test_internal_review_runs_do_not_recurse(self):
        with mock.patch.dict(os.environ, {docs_cache.DISTILLER_ENV: '1'}):
            self.assertIsNone(self.prompt())
            self.assertIsNone(self.tool())

    def test_session_end_preserves_request_for_resume_but_discards_live_evidence(self):
        self.prompt('Why?')
        self.hook('PostToolUse', tool_name='Read', tool_input={'file_path': 'source.py'}, tool_response='value')
        self.hook('SessionEnd')
        self.assertEqual(self.state()['prompt'], 'Why?')
        self.assertEqual(self.state()['observations'], [])
        self.assertFalse(marker_path(self.data).exists())
        self.hook('SessionStart', source='resume')
        self.assertTrue(marker_path(self.data).exists())
        self.hook('SessionStart', source='clear')
        self.assertNotIn('prompt', self.state())
        self.assertFalse(marker_path(self.data).exists())


if __name__ == '__main__':
    unittest.main()
