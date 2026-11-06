#!/usr/bin/env python3
"""Run all checks, or pass DocsCacheTests.test_name for one test."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import docs_cache

URL = 'https://git-scm.com/docs/git-commit'


def fetch(url=URL, session='s1', **extra):
    return {'sessionId': session, 'toolName': 'web_fetch',
            'toolArgs': json.dumps({'url': url, 'max_length': 20000, **extra})}


class DocsCacheTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='docs-cache-check-')
        self.addCleanup(temp.cleanup)
        patcher = mock.patch.dict(os.environ, {'XDG_CACHE_HOME': temp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.key = docs_cache.cache_key(URL, None)

    def test_normalize_ignores_cosmetic_differences(self):
        same = {docs_cache.normalize_url(u) for u in (
            URL, 'https://www.git-scm.com/docs/git-commit/', 'https://GIT-SCM.com/docs/git-commit.html',
            'https://git-scm.com/docs/git-commit#_options')}
        self.assertEqual(same, {'git-scm.com/docs/git-commit'})

    def test_volatile_pages(self):
        self.assertTrue(docs_cache.is_volatile('https://fusionauth.io/docs/release-notes/'))
        self.assertTrue(docs_cache.is_volatile('https://github.com/o/r/releases/tag/v1'))
        self.assertTrue(docs_cache.is_volatile('https://raw.githubusercontent.com/o/r/main/README.md'))
        self.assertFalse(docs_cache.is_volatile('https://raw.githubusercontent.com/o/r/' + 'a' * 40 + '/README.md'))
        self.assertFalse(docs_cache.is_volatile(URL))

    def test_miss_hit_then_bypass_then_hit(self):
        self.assertIsNone(docs_cache.copilot_pre(fetch()))
        docs_cache.store_fact(self.key, URL, '--fixup=<commit> makes a fixup! commit.', 'copilot', length=20000)
        denied = docs_cache.copilot_pre(fetch())
        self.assertEqual(denied['permissionDecision'], 'deny')
        self.assertIn('--fixup=<commit>', denied['permissionDecisionReason'])
        self.assertIsNone(docs_cache.copilot_pre(fetch()), 'repeat must fetch live')
        self.assertEqual(docs_cache.copilot_pre(fetch())['permissionDecision'], 'deny')
        self.assertEqual(docs_cache.copilot_pre(fetch(session='s2'))['permissionDecision'], 'deny')

    def test_chunk_is_part_of_key(self):
        docs_cache.store_fact(self.key, URL, 'fact', 'copilot')
        self.assertIsNone(docs_cache.copilot_pre(fetch(start_index=5000)))

    def test_longer_cached_chunk_covers_shorter_request(self):
        docs_cache.store_fact(self.key, URL, 'fact', 'copilot', length=20000)
        self.assertEqual(docs_cache.copilot_pre(fetch(max_length=16000))['permissionDecision'], 'deny')
        self.assertIsNone(docs_cache.copilot_pre(fetch(session='s2', max_length=30000)))
        self.assertIsNone(docs_cache.copilot_pre(fetch(session='s3', max_length=None)))

    def test_unknown_lengths_never_claim_whole_page_coverage(self):
        docs_cache.store_fact(self.key, URL, 'unknown chunk', 'copilot')
        self.assertIsNone(docs_cache.copilot_pre(fetch()))
        docs_cache.store_fact(self.key, URL, 'known chunk', 'copilot', length=20000)
        data = fetch()
        data['toolArgs'] = {'url': URL}
        self.assertIsNone(docs_cache.copilot_pre(data))
        with mock.patch.object(subprocess, 'Popen') as popen:
            docs_cache.copilot_post({**data, 'toolResult': {
                'resultType': 'success', 'textResultForLlm': 'unknown chunk'}})
            popen.assert_not_called()

    def test_bypass_requires_the_same_arguments(self):
        docs_cache.store_fact(self.key, URL, 'fact', 'copilot', length=20000)
        self.assertEqual(docs_cache.copilot_pre(fetch())['permissionDecision'], 'deny')
        self.assertEqual(docs_cache.copilot_pre(fetch(max_length=16000))['permissionDecision'], 'deny')
        self.assertIsNone(docs_cache.copilot_pre(fetch()))
        self.assertIsNone(docs_cache.copilot_pre(fetch(max_length=16000)))

    def test_volatile_pages_ignore_existing_entries(self):
        url = 'https://example.com/latest'
        docs_cache.store_fact(docs_cache.cache_key(url, None), url, 'stale', 'copilot', length=20000)
        self.assertIsNone(docs_cache.copilot_pre(fetch(url)))

    def test_raw_requests_bypass_the_cache(self):
        docs_cache.store_fact(self.key, URL, 'fact', 'copilot')
        self.assertIsNone(docs_cache.copilot_pre(fetch(raw=True)))
        with mock.patch.object(subprocess, 'Popen') as popen:
            docs_cache.copilot_post({**fetch(raw=True), 'toolResult': {'resultType': 'success', 'textResultForLlm': '<html>'}})
            popen.assert_not_called()

    def test_other_tools_ignored(self):
        self.assertIsNone(docs_cache.copilot_pre({'toolName': 'bash', 'toolArgs': {'command': 'ls'}}))

    def test_expiry_and_per_key_cap(self):
        old = time.time() - docs_cache.TTL_SECONDS - 1
        docs_cache.store_fact(self.key, URL, 'old', 'copilot', now=old)
        self.assertEqual(docs_cache.fresh_facts(self.key), [])
        for n in range(5):
            docs_cache.store_fact(self.key, URL, f'f{n}', 'copilot')
        self.assertEqual([f['fact'] for f in docs_cache.fresh_facts(self.key)], ['f4', 'f3', 'f2'])

    def test_size_cap_evicts_oldest(self):
        with mock.patch.object(docs_cache, 'MAX_CACHE_BYTES', 400):
            for n in range(5):
                key = docs_cache.cache_key(f'{URL}{n}', None)
                docs_cache.store_fact(key, f'{URL}{n}', 'x' * 100, 'copilot')
                os.utime(docs_cache.cache_dir() / 'entries' / f'{key}.json', (n, time.time() - 100 + n))
            docs_cache.evict()
        remaining = list((docs_cache.cache_dir() / 'entries').glob('*.json'))
        self.assertLess(len(remaining), 5)
        self.assertTrue(docs_cache.fresh_facts(docs_cache.cache_key(f'{URL}4', None)))

    def test_corrupt_entry_is_a_miss(self):
        (docs_cache.cache_dir() / 'entries' / f'{self.key}.json').write_text('{not json')
        self.assertIsNone(docs_cache.copilot_pre(fetch()))

    def test_files_are_private(self):
        docs_cache.store_fact(self.key, URL, 'fact', 'copilot')
        root = docs_cache.cache_dir()
        self.assertEqual(root.stat().st_mode & 0o777, 0o700)
        self.assertEqual((root / 'entries' / f'{self.key}.json').stat().st_mode & 0o777, 0o600)

    def test_post_skips_failures_and_volatile_pages(self):
        with mock.patch.object(subprocess, 'Popen') as popen:
            docs_cache.copilot_post({**fetch(), 'toolResult': {'resultType': 'failure', 'textResultForLlm': 'x'}})
            docs_cache.copilot_post({**fetch('https://x.io/changelog'),
                                     'toolResult': {'resultType': 'success', 'textResultForLlm': 'x'}})
            popen.assert_not_called()
            docs_cache.copilot_post({**fetch(), 'toolResult': {'resultType': 'success', 'textResultForLlm': 'page'}})
            popen.assert_called_once()

    def test_distill_stores_fact_and_skips_none(self):
        job = {'url': URL, 'start': None, 'length': None, 'text': 'page', 'question': None, 'harness': 'copilot'}
        done = subprocess.CompletedProcess([], 0, stdout='NONE\n', stderr='')
        with mock.patch.object(docs_cache.shutil, 'which', return_value='claude'), \
                mock.patch.object(subprocess, 'run', return_value=done):
            docs_cache.distill(job)
        self.assertEqual(docs_cache.fresh_facts(self.key), [])
        done.stdout = 'git commit --fixup=<commit> creates a fixup! commit.\n'
        with mock.patch.object(docs_cache.shutil, 'which', return_value='claude'), \
                mock.patch.object(subprocess, 'run', return_value=done):
            docs_cache.distill(job)
        self.assertEqual(docs_cache.fresh_facts(self.key)[0]['fact'], done.stdout.strip())

    def run_distill(self, returncode=0, stdout='fact', stderr='', which='claude'):
        job = {'url': URL, 'start': None, 'length': None, 'text': 'page', 'question': None, 'harness': 'copilot'}
        done = subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)
        with mock.patch.object(docs_cache.shutil, 'which', return_value=which), \
                mock.patch.object(subprocess, 'run', return_value=done):
            docs_cache.distill(job)

    def test_distiller_enforces_word_limit_without_truncating_facts(self):
        fact = ' '.join(['word'] * 150)
        self.run_distill(stdout=fact)
        self.run_distill(stdout=f'{fact} extra')
        self.assertEqual([entry['fact'] for entry in docs_cache.fresh_facts(self.key)], [fact])
        self.assertIn('150-word limit', self.notice())
        log = (docs_cache.cache_dir() / 'events.jsonl').read_text().splitlines()
        self.assertEqual(json.loads(log[-1])['event'], 'distill-failed')

    def test_overlong_existing_facts_are_not_served(self):
        docs_cache.store_fact(self.key, URL, 'word ' * 151, 'copilot', length=20000)
        self.assertIsNone(docs_cache.copilot_pre(fetch()))

    def notice(self, session='s1'):
        output = docs_cache.copilot_post({'sessionId': session, 'toolName': 'bash', 'toolArgs': {}})
        return output and output['userNotice']

    def test_distiller_problems_reach_the_user_once_per_session(self):
        self.assertIsNone(self.notice())
        self.run_distill(returncode=1, stdout='', stderr='Not logged in. Run claude auth login.')
        notice = self.notice()
        self.assertIn('Not logged in', notice)
        self.assertEqual(self.notice(), notice, 'post-tool context does not prove delivery')
        data = {'sessionId': 's1', 'last_assistant_message': 'Done.'}
        blocked = docs_cache.copilot_stop(data)
        self.assertEqual(blocked['decision'], 'block')
        self.assertIn(notice, blocked['reason'])
        self.assertIsNone(docs_cache.copilot_stop({
            **data, 'last_assistant_message': 'Done.\n' + notice.replace(' ', '\n'),
        }))
        self.assertIsNone(self.notice(), 'same problem is reported once per session')
        self.assertIn('Not logged in', self.notice(session='s2'))
        self.run_distill(which=None)
        self.assertIn('not found on PATH', self.notice())

    def test_notice_does_not_conflict_with_punctuation_guard(self):
        self.run_distill(returncode=1, stderr=f'Not logged in{chr(0x2014)}sign in again.')
        notice = self.notice()
        self.assertNotIn(chr(0x2014), notice)
        self.assertIn('Not logged in-sign in again.', notice)
        self.assertIsNone(docs_cache.copilot_stop({
            'sessionId': 's1', 'last_assistant_message': notice,
        }))

    def test_expiry_warning_on_success_is_reported_then_cleared(self):
        self.run_distill(stderr='Warning: this sign-in ends between 2026-11-09 and 2026-11-12.')
        self.assertTrue(docs_cache.fresh_facts(self.key), 'a warning must not block storing')
        self.assertIn('sign-in ends', self.notice())
        self.run_distill()
        self.assertIsNone(self.notice(session='s2'))

    def test_distiller_timeout_is_reported(self):
        job = {'url': URL, 'start': None, 'length': None, 'text': 'page', 'question': None, 'harness': 'copilot'}
        with mock.patch.object(docs_cache.shutil, 'which', return_value='claude'), \
                mock.patch.object(subprocess, 'run', side_effect=subprocess.TimeoutExpired('claude', 90)):
            docs_cache.distill(job)
        self.assertIn('timed out', self.notice())

    def test_multibyte_prompt_is_bounded_without_overstating_coverage(self):
        job = {'url': URL, 'start': None, 'length': 100000,
               'text': chr(0x1F600) * 100000, 'question': None, 'harness': 'copilot'}
        done = subprocess.CompletedProcess([], 0, stdout='fact', stderr='')
        with mock.patch.object(docs_cache.shutil, 'which', return_value='copilot'), \
                mock.patch.object(subprocess, 'run', return_value=done) as run:
            docs_cache.distill(job)
        argv = run.call_args.args[0]
        prompt = argv[argv.index('-p') + 1]
        self.assertLessEqual(len(prompt.encode('utf-8')), 100000)
        text = prompt.split('Page text:\n', 1)[1]
        fact = docs_cache.fresh_facts(self.key)[0]
        self.assertEqual(fact['length'], len(text))
        self.assertIsNone(docs_cache.copilot_pre(fetch(max_length=100000)))
        result = subprocess.run([sys.executable, '-c', 'pass', prompt], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_worker_launch_failure_is_reported_immediately(self):
        data = {**fetch(), 'toolResult': {'resultType': 'success', 'textResultForLlm': 'page'}}
        with mock.patch.object(subprocess, 'Popen', side_effect=OSError('cannot start worker')):
            output = docs_cache.copilot_post(data)
        self.assertIn('cannot start worker', output['userNotice'])

    def test_unexpected_worker_error_is_saved_for_user_notice(self):
        job = {'url': URL, 'start': None, 'length': 20000,
               'text': 'page', 'question': None, 'harness': 'copilot'}
        with mock.patch.object(sys, 'argv', ['docs_cache.py', 'distill']), \
                mock.patch.object(sys, 'stdin', io.StringIO(json.dumps(job))), \
                mock.patch.object(sys, 'stderr', io.StringIO()), \
                mock.patch.object(docs_cache.shutil, 'which', return_value='copilot'), \
                mock.patch.object(subprocess, 'run', side_effect=OSError('cannot execute distiller')):
            docs_cache.main()
        self.assertIn('cannot execute distiller', self.notice())

    def test_distiller_uses_the_harness_cli_and_small_model(self):
        argv, stdin = docs_cache.distiller_command('claude', 'MSG')
        self.assertEqual((argv[0], argv[argv.index('--model') + 1], stdin), ('claude', 'haiku', 'MSG'))
        argv, stdin = docs_cache.distiller_command('copilot', 'MSG')
        self.assertEqual((argv[0], argv[argv.index('--model') + 1], stdin), ('copilot', 'gpt-6-luna', None))
        self.assertIn('MSG', argv[argv.index('-p') + 1])
        argv, stdin = docs_cache.distiller_command('codex', 'MSG')
        self.assertEqual((argv[:2], argv[argv.index('-m') + 1], stdin), (['codex', 'exec'], 'gpt-6-luna', None))
        self.assertIn('MSG', argv[-1])
        with self.assertRaises(ValueError):
            docs_cache.distiller_command('other', 'MSG')

    def test_distiller_run_is_marked_and_ignores_answer_text_in_stderr(self):
        job = {'url': URL, 'start': None, 'length': None, 'text': 'page', 'question': None, 'harness': 'codex'}
        done = subprocess.CompletedProcess([], 0, stdout='fact', stderr='codex\nthe warning flag does X\ntokens used')
        with mock.patch.object(docs_cache.shutil, 'which', return_value='/bin/codex'), \
                mock.patch.object(subprocess, 'run', return_value=done) as run:
            docs_cache.distill(job)
        self.assertEqual(run.call_args.kwargs['env'][docs_cache.DISTILLER_ENV], '1')
        self.assertEqual(run.call_args.args[0][0], '/bin/codex')
        self.assertIsNone(self.notice(), 'only lines starting with warning are warnings')

    def test_main_fails_open(self):
        out = io.StringIO()
        with mock.patch.object(sys, 'argv', ['docs_cache.py', 'distill']), \
                mock.patch.object(sys, 'stdin', io.StringIO('not json')), \
                mock.patch.object(sys, 'stdout', out), mock.patch.object(sys, 'stderr', io.StringIO()):
            docs_cache.main()
        self.assertEqual(out.getvalue(), '')

    def test_script_exits_zero_on_bad_input(self):
        script = Path(docs_cache.__file__)
        result = subprocess.run([sys.executable, str(script), 'distill'], input='{}{',
                                capture_output=True, text=True, env=os.environ)
        self.assertEqual((result.returncode, result.stdout), (0, ''))


if __name__ == '__main__':
    unittest.main(argv=sys.argv[:1] + sys.argv[1:], verbosity=1)
