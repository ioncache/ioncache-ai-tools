#!/usr/bin/env python3
"""Exercise source coverage and exact-artifact checkpoints without real host state."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import claim_evidence
import copilot_adapter
from evidence_review import check_review, inventory, publication_commands
from evidence_source import check_native_read, read_page, source_snapshot, source_unit, unit_bounds
from evidence_store import EvidenceStore, record_page, reference_key


class ClaimEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='claim-evidence-check-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / 'home'
        self.home.mkdir()
        self.patch = mock.patch.dict(os.environ, {
            'HOME': str(self.home), 'CODEX_HOME': str(self.home / '.codex'),
            'COPILOT_HOME': str(self.home / '.copilot'),
        })
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.data = {
            'cwd': str(self.root), 'session_id': 'fixture', 'agent_id': 'root',
            'evidence_model_output': True,
        }
        self.source = self.root / 'source.py'
        self.source.write_text('def handler():\n    return 204\n')

    def hook(self, event, **fields):
        return claim_evidence.run_hook(event, {**self.data, **fields})

    def helper(self, args, response=None):
        command = f'{sys.executable} "{claim_evidence.HELPER}" {args}'
        fields = {'tool_name': 'Bash', 'tool_input': {'command': command}}
        output = self.hook('PreToolUse', **fields)
        if response is not None:
            return self.hook('PostToolUse', **fields, tool_response=response)
        return output

    def deliver(self, unit='file'):
        snapshot = source_snapshot(self.source)
        options = argparse.Namespace(path=str(self.source), unit=unit, page=1, sha256=None)
        first, _ = read_page(options)
        for number in range(1, first['pages'] + 1):
            options.page = number
            _, output = read_page(options)
            result = self.helper(
                f'read "{self.source}" --unit {unit} --page {number} --sha256 {snapshot["sha256"]}',
                {'stdout': output + '\n'},
            )
            self.assertNotIn('not delivered', str(result))
        return {'path': str(self.source), 'sha256': snapshot['sha256'], 'unit': unit, 'lines': [1, 2]}

    def request(self, text='The handler returns 204.'):
        return {'tool_name': 'Write', 'tool_input': {
            'file_path': str(self.root / 'README.md'), 'content': text,
        }}

    def prepare(self, request_path):
        options = claim_evidence.parser().parse_args(['prepare', str(request_path)])
        page, _ = claim_evidence.prepare_page(options, self.root)
        for number in range(1, page['pages'] + 1):
            options.page = number
            _, output = claim_evidence.prepare_page(options, self.root)
            self.helper(f'prepare "{request_path}" --page {number}', {'stdout': output})

    def review(self, prepared, evidence=None):
        return {
            'fingerprint': prepared['fingerprint'], 'reviewer': 'fixture reviewer',
            'classifications': [{
                'artifact': item['artifact'], 'start': 1, 'end': item['lines'],
                'kind': 'behavior' if evidence else 'non-behavior',
                'reason': 'Reviewed all outgoing content',
                'claims': [{
                    'text': item['text'], 'reason': 'The complete return path establishes this',
                    'evidence': [evidence],
                }] if evidence else [],
            } for item in prepared['artifacts'] if item['lines']],
        }

    def test_small_file_threshold_and_physical_lines(self):
        for count in (0, 1, 399, 400):
            self.source.write_bytes(b'\r\n' * count)
            with self.subTest(count=count), self.assertRaisesRegex(ValueError, '400'):
                check_native_read({'file_path': str(self.source), 'offset': 1}, self.root)
        self.source.write_bytes(b'\n' * 400 + b'x')
        self.assertEqual(len(source_snapshot(self.source)['lines']), 401)
        check_native_read({'file_path': str(self.source)}, self.root)

    def test_exact_large_python_units_include_decorators_and_failure_paths(self):
        self.source.write_text('\n' * 400 + '@decorator\nasync def handle():\n    try:\n        return 1\n    finally:\n        cleanup()\n')
        snapshot = source_snapshot(self.source)
        self.assertIn('401:406', unit_bounds(snapshot))
        check_native_read({'file_path': str(self.source), 'offset': 401, 'limit': 6}, self.root)
        for start, limit in ((402, 5), (401, 4), (403, 4)):
            with self.assertRaises(ValueError):
                check_native_read({'file_path': str(self.source), 'offset': start, 'limit': limit}, self.root)

    def test_unsupported_language_uses_whole_file(self):
        path = self.root / 'handler.js'
        path.write_text('\n' * 401 + 'function handler() {}\n')
        self.assertEqual(list(unit_bounds(source_snapshot(path))), ['file'])
        with self.assertRaises(ValueError):
            check_native_read({'file_path': str(path), 'offset': 402, 'limit': 1}, self.root)

    def test_reads_without_post_delivery_never_grant_coverage(self):
        self.helper(f'read "{self.source}"')
        snapshot = source_snapshot(self.source)
        with EvidenceStore(self.data) as store:
            self.assertIsNone(store.get('coverage', reference_key({**snapshot, 'unit': 'file'})))

    def test_complete_pages_required_and_truncation_rejected(self):
        self.source.write_text('#' + 'a' * 4500)
        options = argparse.Namespace(path=str(self.source), unit='file', page=1, sha256=None)
        page, output = read_page(options)
        result = self.helper(f'read "{self.source}"', {'stdout': output[:100]})
        self.assertIn('not delivered intact', str(result))
        with EvidenceStore(self.data) as store:
            self.assertIsNone(store.get('coverage', reference_key(page)))
        self.deliver()
        with EvidenceStore(self.data) as store:
            self.assertTrue(store.get('coverage', reference_key(page)))

    def test_source_change_between_pre_and_post_rejected(self):
        options = argparse.Namespace(path=str(self.source), unit='file', page=1, sha256=None)
        _, output = read_page(options)
        command = f'{sys.executable} "{claim_evidence.HELPER}" read "{self.source}"'
        fields = {'tool_name': 'Bash', 'tool_input': {'command': command}}
        self.hook('PreToolUse', **fields)
        self.source.write_text('changed\n')
        result = self.hook('PostToolUse', **fields, tool_response={'stdout': output})
        self.assertIn('changed during delivery', str(result))

    def test_checkpoint_rejects_unread_stale_and_wrong_agent_evidence(self):
        prepared = inventory(self.request(), self.root)
        snapshot = source_snapshot(self.source)
        ref = {'path': str(self.source), 'sha256': snapshot['sha256'], 'unit': 'file', 'lines': [1, 2]}
        with EvidenceStore(self.data) as store, self.assertRaisesRegex(ValueError, 'no complete'):
            check_review(self.review(prepared, ref), prepared, {'cwd': self.root, 'store': store})
        ref = self.deliver()
        with EvidenceStore({**self.data, 'agent_id': 'other'}) as store, self.assertRaisesRegex(ValueError, 'no complete'):
            check_review(self.review(prepared, ref), prepared, {'cwd': self.root, 'store': store})
        self.source.write_text('changed\n')
        with EvidenceStore(self.data) as store, self.assertRaisesRegex(ValueError, 'stale'):
            check_review(self.review(prepared, ref), prepared, {'cwd': self.root, 'store': store})

    def test_review_requires_every_line_and_exact_claim(self):
        prepared = inventory(self.request('First\nSecond'), self.root)
        review = self.review(prepared)
        review['classifications'][0]['end'] = 1
        with EvidenceStore(self.data) as store, self.assertRaisesRegex(ValueError, 'every outgoing line'):
            check_review(review, prepared, {'cwd': self.root, 'store': store})
        review = self.review(prepared, self.deliver())
        review['classifications'][0]['claims'][0]['text'] = 'Not present'
        with EvidenceStore(self.data) as store, self.assertRaisesRegex(ValueError, 'quote'):
            check_review(review, prepared, {'cwd': self.root, 'store': store})

    def test_checkpoint_approval_and_artifact_changes(self):
        ref = self.deliver()
        request = self.request()
        denied = self.hook('PreToolUse', **request)
        self.assertIn('checkpoint required', str(denied))
        prepared = inventory(request, self.root)
        with EvidenceStore(self.data) as store:
            request_path = store.request_path(prepared['fingerprint'])
        review_path = request_path.with_suffix('.review.json')
        review_path.write_text(json.dumps(self.review(prepared, ref)))
        self.assertIn('prepare every inventory page', str(self.helper(f'approve "{request_path}" --review "{review_path}"')))
        self.prepare(request_path)
        self.assertIsNone(self.helper(f'approve "{request_path}" --review "{review_path}"'))
        self.assertIn('checkpoint required', str(self.hook('PreToolUse', **request)))
        options = claim_evidence.parser().parse_args(['approve', str(request_path), '--review', str(review_path)])
        receipt = claim_evidence.approval_candidate(options, self.root)[2]
        self.helper(f'approve "{request_path}" --review "{review_path}"', {'stdout': receipt})
        self.assertIsNone(self.hook('PreToolUse', **request))
        self.assertIn('checkpoint required', str(self.hook('PreToolUse', **self.request('Different'))))
        self.source.write_text('changed\n')
        self.assertIn('stale', str(self.hook('PreToolUse', **request)))

    def test_review_file_can_be_written_without_recursive_checkpoint(self):
        self.hook('PreToolUse', **self.request())
        prepared = inventory(self.request(), self.root)
        with EvidenceStore(self.data) as store:
            path = store.request_path(prepared['fingerprint']).with_suffix('.review.json')
        request = {'tool_name': 'Write', 'tool_input': {'file_path': str(path), 'content': '{}'}}
        self.assertIsNone(self.hook('PreToolUse', **request))
        patch = f'*** Begin Patch\n*** Add File: {path}\n+{{}}\n*** End Patch'
        self.assertIsNone(self.hook('PreToolUse', tool_name='apply_patch', tool_input={'command': patch}))
        path.with_name('unregistered.review.json').write_text('{}')
        request['tool_input']['file_path'] = str(path.with_name('unregistered.review.json'))
        self.assertIsNotNone(self.hook('PreToolUse', **request))

    def test_compaction_and_resume_clear_coverage_and_approvals(self):
        for event in ('PreCompact', 'SessionStart', 'SessionEnd', 'SubagentStart'):
            ref = self.deliver()
            self.hook(event)
            with EvidenceStore(self.data) as store:
                self.assertIsNone(store.get('coverage', reference_key(ref)))

    def test_compaction_invalidates_other_working_directories_in_same_session(self):
        ref = self.deliver()
        elsewhere = self.root / 'another-project'
        elsewhere.mkdir()
        other_context = {**self.data, 'cwd': str(elsewhere)}
        with EvidenceStore(other_context) as store:
            self.assertIsNone(store.get('coverage', reference_key(ref)))
        claim_evidence.run_hook('PreCompact', other_context)
        with EvidenceStore(self.data) as store:
            self.assertIsNone(store.get('coverage', reference_key(ref)))

    def test_stop_requests_one_correction_without_infinite_loop(self):
        self.assertEqual(self.hook('Stop', last_assistant_message='Unchecked')['decision'], 'block')
        self.assertIn('not mechanically verified', self.hook('Stop', last_assistant_message='Corrected')['systemMessage'])
        self.assertIn('not mechanically verified', self.hook('Stop', last_assistant_message='Another correction')['systemMessage'])
        self.hook('UserPromptSubmit', prompt='Next task')
        self.assertEqual(self.hook('Stop', last_assistant_message='Unchecked')['decision'], 'block')

    def test_copilot_reports_unverified_stop_completion(self):
        warning = 'Claim evidence: final prose is not mechanically verified.'
        with (
            mock.patch.object(copilot_adapter, 'final_response', return_value='Unchecked'),
            mock.patch.object(copilot_adapter, 'run_shared_hooks', return_value=[{'systemMessage': warning}]),
            mock.patch.object(copilot_adapter.sys, 'stderr', new_callable=io.StringIO) as stderr,
        ):
            output = copilot_adapter.run_hook('agentStop', {'sessionId': 'fixture', 'cwd': str(self.root)})
        self.assertIsNone(output)
        self.assertIn(warning, stderr.getvalue())

    def test_config_disable_and_discovery_tools_remain_available(self):
        self.assertIsNone(self.hook('PreToolUse', tool_name='Grep', tool_input={'pattern': 'return'}))
        path = self.root / '.claude/ioncache-ai-tools.local.json'
        path.parent.mkdir()
        path.write_text('{"disabledRules":["claim-evidence"]}')
        self.assertIsNone(self.hook('PreToolUse', **self.request()))

    def test_reader_cli_and_whole_file_fallback_for_invalid_python(self):
        self.source.write_text('\n' * 401 + 'def invalid(\n')
        result = subprocess.run(
            [sys.executable, str(claim_evidence.HELPER), 'read', str(self.source)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('CLAIM_EVIDENCE_SOURCE ', result.stdout)

    def test_claude_credits_serialized_batch_not_structured_post_output(self):
        options = argparse.Namespace(path=str(self.source), unit='file', page=1, sha256=None)
        page, output = read_page(options)
        fields = {
            'tool_name': 'Bash',
            'tool_input': {'command': f'{sys.executable} "{claim_evidence.HELPER}" read "{self.source}"'},
            'tool_use_id': 'read-1',
        }
        self.hook('PreToolUse', **fields)
        self.hook('PostToolUse', **fields, evidence_model_output=False, tool_response={'stdout': output})
        with EvidenceStore(self.data) as store:
            self.assertIsNone(store.get('coverage', reference_key(page)))
        self.hook('PostToolBatch', tool_calls=[{**fields, 'tool_response': [{'type': 'text', 'text': output}]}])
        with EvidenceStore(self.data) as store:
            self.assertTrue(store.get('coverage', reference_key(page)))

    def test_search_and_native_read_never_substitute_for_reader_delivery(self):
        for name in ('Grep', 'Read'):
            fields = {'tool_name': name, 'tool_input': {'file_path': str(self.source)}}
            self.hook('PreToolUse', **fields)
            self.hook('PostToolUse', **fields, tool_response=self.source.read_text())
        ref = {**source_snapshot(self.source), 'unit': 'file'}
        with EvidenceStore(self.data) as store:
            self.assertIsNone(store.get('coverage', reference_key(ref)))

    def test_reader_handles_unicode_crlf_and_unterminated_lines_exactly(self):
        text = '\n' * 400 + '@decorate\r\ndef example():\r\n    return "' + chr(0x1F600) * 2500 + '"'
        self.source.write_bytes(text.encode())
        snapshot = source_snapshot(self.source)
        unit, bounds = source_unit(snapshot, '401:403')
        self.assertEqual(unit, text[400:])
        self.assertEqual(bounds, (401, 403))
        options = argparse.Namespace(path=str(self.source), unit='401:403', page=1, sha256=None)
        first, _ = read_page(options)
        chunks = []
        for page in range(1, first['pages'] + 1):
            options.page = page
            record, output = read_page(options)
            chunks.append(record['content'])
            self.assertEqual(json.loads(output.split(' ', 1)[1]), record)
        self.assertEqual(''.join(chunks), unit)
        options.sha256 = 'old'
        with self.assertRaisesRegex(ValueError, 'changed'):
            read_page(options)

    def test_concurrent_and_duplicate_pages_do_not_lose_coverage(self):
        self.source.write_text('#' + 'x' * 12000)
        snapshot = source_snapshot(self.source)
        base = {'path': str(self.source), 'sha256': snapshot['sha256'], 'unit': 'file', 'pages': 7}
        def observe(page):
            with EvidenceStore(self.data) as store:
                record_page(store, {**base, 'page': page})
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(observe, [1, 1, 2, 3, 4, 5, 6, 7]))
        with EvidenceStore(self.data) as store:
            self.assertTrue(store.get('coverage', reference_key(base)))

    def test_changed_target_invalidates_inventory_fingerprint(self):
        request = self.request()
        old = inventory(request, self.root)['fingerprint']
        (self.root / 'README.md').write_text('existing')
        self.assertNotEqual(inventory(request, self.root)['fingerprint'], old)

    def test_publication_inventory_checks_body_files_and_explicit_text(self):
        body = self.root / 'body.txt'
        body.write_text('The handler returns 204.')
        request = {'tool_name': 'Bash', 'tool_input': {
            'command': f'gh pr create --title "Handler behavior" --body-file "{body}"',
        }}
        prepared = inventory(request, self.root)
        self.assertIn(body.read_text(), [item['text'] for item in prepared['artifacts']])
        body.write_text('Changed claim')
        self.assertNotEqual(inventory(request, self.root)['fingerprint'], prepared['fingerprint'])
        for command in (
            'gh pr create --title "Title"', 'gh pr create --fill',
            'gh pr create --title Title --body-file -',
            'gh pr create --title Title --body "$BODY"',
            'cd project && gh pr create --title Title --body Text',
            'gh pr edit --editor',
        ):
            with self.subTest(command=command), self.assertRaises(ValueError):
                inventory({'tool_name': 'Bash', 'tool_input': {'command': command}}, self.root)
        self.assertEqual(publication_commands('git log --grep commit'), [])
        self.assertTrue(publication_commands('git -C project commit -m text'))
        self.assertTrue(publication_commands('gh -R owner/repo pr create --title Title --body Text'))

    def test_commit_inventory_tracks_staged_snapshot_not_worktree(self):
        subprocess.run(['git', '-c', 'init.templateDir=', 'init', str(self.root)], check=True, capture_output=True)
        subprocess.run(['git', 'add', 'source.py'], cwd=self.root, check=True, capture_output=True)
        request = {'tool_name': 'Bash', 'tool_input': {'command': 'git commit -m "Describe the handler"'}}
        prepared = inventory(request, self.root)
        self.assertEqual(prepared['artifacts'][-1]['destination'], 'staged diff')
        self.source.write_text('new source\n')
        self.assertEqual(inventory(request, self.root)['fingerprint'], prepared['fingerprint'])
        subprocess.run(['git', 'add', 'source.py'], cwd=self.root, check=True, capture_output=True)
        self.assertNotEqual(inventory(request, self.root)['fingerprint'], prepared['fingerprint'])
        for command in ('git commit -a -m Text', 'git commit -m Text source.py'):
            with self.assertRaises(ValueError):
                inventory({'tool_name': 'Bash', 'tool_input': {'command': command}}, self.root)

    def test_malformed_reviews_and_publication_timeout_do_not_fail_open(self):
        prepared = inventory(self.request(), self.root)
        malformed = self.review(prepared)
        malformed['classifications'] = ['not an object']
        with EvidenceStore(self.data) as store, self.assertRaisesRegex(ValueError, 'classification'):
            check_review(malformed, prepared, {'cwd': self.root, 'store': store})
        with mock.patch('evidence_review.subprocess.run', side_effect=subprocess.TimeoutExpired('git', 2)):
            output = self.hook('PreToolUse', tool_name='Bash', tool_input={'command': 'git commit -m Message'})
        self.assertIn('timed out', str(output))
        self.assertEqual(output['hookSpecificOutput']['permissionDecision'], 'deny')

    def test_lifecycle_cleanup_removes_only_its_session_requests(self):
        self.hook('PreToolUse', **self.request())
        with EvidenceStore(self.data) as store:
            path = store.request_path(inventory(self.request(), self.root)['fingerprint'])
            unrelated = store.requests / 'keep.txt'
            unrelated.write_text('keep')
        other = {**self.data, 'session_id': 'other'}
        claim_evidence.run_hook('PreToolUse', {**other, **self.request()})
        with EvidenceStore(other) as store:
            other_path = store.request_path(inventory(self.request(), self.root)['fingerprint'])
        self.hook('SessionEnd')
        self.assertFalse(path.exists())
        self.assertTrue(other_path.exists())
        self.assertTrue(unrelated.exists())

    def native(self, host, invocation):
        event, fields = invocation
        data = {'cwd': str(self.root), 'session_id': f'native-{host}', **fields}
        script = claim_evidence.HELPER
        arguments = ['hook', event]
        if host == 'codex':
            script = script.with_name('codex_adapter.py')
            arguments = [event]
        elif host == 'copilot':
            script = script.with_name('copilot_adapter.py')
            arguments = [event[0].lower() + event[1:]]
            data = {'cwd': str(self.root), 'sessionId': f'native-{host}', 'timestamp': 1, **fields}
            if 'tool_name' in fields:
                data['toolName'] = fields['tool_name']
                data['toolArgs'] = json.dumps(fields['tool_input'])
                if event == 'PostToolUse':
                    data['toolResult'] = {'resultType': 'success', 'textResultForLlm': fields['tool_response']}
        if host == 'claude' and event == 'PostToolUse':
            arguments = ['hook', 'PostToolBatch']
            data = {'cwd': str(self.root), 'session_id': f'native-{host}', 'tool_calls': [fields]}
        result = subprocess.run(
            [sys.executable, str(script), *arguments], input=json.dumps(data),
            text=True, capture_output=True, cwd=self.root, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def native_helper(self, host, arguments):
        command = shlex.join([sys.executable, str(claim_evidence.HELPER), *arguments])
        fields = {'tool_name': 'bash' if host == 'copilot' else 'Bash', 'tool_input': {'command': command}}
        self.assertEqual(self.native(host, ('PreToolUse', fields)), {})
        result = subprocess.run(shlex.split(command), cwd=self.root, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = self.native(host, ('PostToolUse', {**fields, 'tool_response': result.stdout}))
        self.assertNotIn('not delivered', str(output))
        return result.stdout

    def test_native_checkpoint_round_trip_on_all_hosts(self):
        for host in ('claude', 'codex', 'copilot'):
            with self.subTest(host=host):
                self.native_round_trip(host)

    def native_round_trip(self, host):
        text = 'The handler returns 204.'
        target = self.root / f'{host}.md'
        if host == 'copilot':
            request = {'tool_name': 'create', 'tool_input': {'path': str(target), 'file_text': text}}
            normalized = {'tool_name': 'Write', 'tool_input': {'file_path': str(target), 'content': text}}
            native_read = {'tool_name': 'view', 'tool_input': {'path': str(self.source), 'view_range': [1, 1]}}
        elif host == 'codex':
            patch = f'*** Begin Patch\n*** Add File: {target}\n+{text}\n*** End Patch'
            request = normalized = {'tool_name': 'apply_patch', 'tool_input': {'command': patch}}
            native_read = {'tool_name': 'Read', 'tool_input': {'file_path': str(self.source), 'offset': 1, 'limit': 1}}
        else:
            request = normalized = {'tool_name': 'Write', 'tool_input': {'file_path': str(target), 'content': text}}
            native_read = {'tool_name': 'Read', 'tool_input': {'file_path': str(self.source), 'offset': 1, 'limit': 1}}
        self.assertIn('400 lines', str(self.native(host, ('PreToolUse', native_read))))
        self.assertIn('checkpoint required', str(self.native(host, ('PreToolUse', request))))
        source_output = self.native_helper(host, ['read', str(self.source)])
        source_record = json.loads(source_output.split(' ', 1)[1])
        reference = {
            'path': str(self.source), 'sha256': source_record['sha256'], 'unit': 'file', 'lines': [1, 2],
        }
        session = f'copilot-native-{host}' if host == 'copilot' else f'native-{host}'
        prepared = inventory(normalized, self.root)
        with EvidenceStore({'cwd': str(self.root), 'session_id': session}) as store:
            request_path = store.request_path(prepared['fingerprint'])
        page = json.loads(self.native_helper(host, ['prepare', str(request_path)]).split(' ', 1)[1])
        for number in range(2, page['pages'] + 1):
            self.native_helper(host, ['prepare', str(request_path), '--page', str(number)])
        review_path = request_path.with_suffix('.review.json')
        review_path.write_text(json.dumps(self.review(prepared, reference)))
        self.native_helper(host, ['approve', str(request_path), '--review', str(review_path)])
        self.assertEqual(self.native(host, ('PreToolUse', request)), {})
        self.native(host, ('PreCompact', {}))
        self.assertIn('checkpoint required', str(self.native(host, ('PreToolUse', request))))


if __name__ == '__main__':
    unittest.main()
