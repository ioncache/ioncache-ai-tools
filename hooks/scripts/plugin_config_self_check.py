#!/usr/bin/env python3
"""Offline configuration reconciliation and activation regressions."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
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
import uuid

import plugin_config as config
import guidance
from classify_question import marker_path
from hook_adapter_common import run_shared_hooks

ROOT = Path(__file__).resolve().parents[2]


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.project = self.root / 'project'
        self.project.mkdir()
        patcher = mock.patch.dict(os.environ, {
            'HOME': str(self.root / 'home'), 'CODEX_HOME': str(self.root / 'codex'),
            'COPILOT_HOME': str(self.root / 'copilot'), 'XDG_CACHE_HOME': str(self.root / 'cache'),
            'IONCACHE_DOCS_DISTILLER': '', 'PYTHONDONTWRITEBYTECODE': '1',
        })
        patcher.start()
        self.addCleanup(patcher.stop)
        self.data = {'cwd': str(self.project), 'session_id': f'config-check-{uuid.uuid4()}'}
        self.addCleanup(lambda: marker_path(self.data).unlink(missing_ok=True))

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))


    def test_install_update_adds_preserves_and_removes_settings(self):
        path = self.root / 'config.json'
        old = {'features': {'retained': True, 'disabled': True, 'removed': True}}
        self.assertEqual(config.sync_file(path, old['features']), old)
        self.write(path, {'features': {'retained': False, 'disabled': False, 'removed': False}})
        new = {'retained': True, 'disabled': True, 'added': True}
        expected = {'features': {'retained': False, 'disabled': False, 'added': True}}
        self.assertEqual(config.sync_file(path, new), expected)
        self.assertEqual(json.loads(path.read_text()), expected)
        stamp = path.stat().st_mtime_ns
        config.sync_file(path, new)
        self.assertEqual(path.stat().st_mtime_ns, stamp)

    def test_legacy_settings_migrate_and_retired_claim_settings_disappear(self):
        for host, (path, project_path) in config.paths(self.project).items():
            with self.subTest(host=host):
                self.write(path, {'disabledRules': ['no_broad_process_kill', 'claim-evidence', 'graphify'],
                                  'enabledRules': ['verify-state-before-claiming']})
                self.write(project_path, {'enabledRules': ['no_broad_process_kill', 'claim-evidence', 'graphify']})
                config.synchronize(str(self.project), host)
                stored = json.loads(path.read_text())
                self.assertEqual(set(stored['features']), set(config.defaults()))
                self.assertFalse(stored['features']['no_broad_process_kill'])
                self.assertEqual(json.loads(project_path.read_text()), {
                    'features': {'no_broad_process_kill': True},
                })
                self.assertNotIn('disabledRules', stored)
                self.assertNotIn('claim-evidence', path.read_text())
                self.assertNotIn('graphify', path.read_text())
                self.assertNotIn('verify-state-before-claiming', path.read_text())

    def test_codex_migrates_once_without_rewriting_host_settings(self):
        global_path, _ = config.paths(self.project)['codex']
        toml = global_path.with_name('config.toml')
        toml.parent.mkdir(parents=True)
        original = (
            'model = "configured-model"\n[ioncache-ai-tools]\n'
            'disabled_rules = ["no_broad_process_kill", "claim-evidence"]\n'
            f'[projects.{json.dumps(str(self.project))}.ioncache-ai-tools]\n'
            'enabled_rules = ["no_broad_process_kill"]\n'
        )
        toml.write_text(original)
        self.assertNotIn('no_broad_process_kill', config.synchronize(str(self.project), 'codex'))
        self.assertEqual(toml.read_text(), original)
        stored = json.loads(global_path.read_text())
        self.assertFalse(stored['features']['no_broad_process_kill'])
        self.assertNotIn('claim-evidence', global_path.read_text())
        stored['features']['no_broad_process_kill'] = True
        self.write(global_path, stored)
        self.assertNotIn('no_broad_process_kill', config.synchronize(str(self.root), 'codex'))

    def test_project_overrides_inherit_defaults_and_cross_host_disables(self):
        paths = config.paths(self.project)
        self.write(paths['copilot'][0], {'features': {'fix_emdash': False}})
        self.write(paths['copilot'][1], {'features': {'fix_emdash': True, 'removed': False}})
        self.assertNotIn('fix_emdash', config.synchronize(str(self.project), 'copilot'))
        self.assertEqual(json.loads(paths['copilot'][1].read_text()), {'features': {'fix_emdash': True}})
        self.write(paths['claude'][1], {'features': {'fix_emdash': False}})
        self.assertIn('fix_emdash', config.synchronize(str(self.project), 'copilot'))
        self.assertEqual(set(json.loads(paths['copilot'][0].read_text())['features']), set(config.defaults()))

    def test_invalid_configuration_is_not_replaced_or_silently_enabled(self):
        path = self.root / 'invalid.json'
        for text in ('{bad', '[]', '{"features":{"fix_emdash":"false"}}'):
            path.write_text(text)
            with self.subTest(text=text), self.assertRaises(ValueError):
                config.sync_file(path, config.defaults())
            self.assertEqual(path.read_text(), text)

    def test_sync_preserves_symlinks_and_serializes_concurrent_writers(self):
        target = self.root / 'main.json'
        self.write(target, {'features': {'fix_emdash': False, 'removed': True}})
        link = self.root / 'worktree.json'
        link.symlink_to(target)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: config.sync_file(link, config.defaults()), range(8)))
        self.assertTrue(link.is_symlink())
        self.assertTrue(all(result == results[0] for result in results))
        self.assertFalse(json.loads(target.read_text())['features']['fix_emdash'])

    def test_failed_replace_preserves_the_original_file(self):
        path = self.root / 'settings.json'
        original = '{"features":{"fix_emdash":false}}'
        path.write_text(original)
        with mock.patch.object(config.os, 'replace', side_effect=OSError('unavailable')):
            with self.assertRaises(OSError):
                config.sync_file(path, config.defaults())
        self.assertEqual(path.read_text(), original)
        self.assertEqual(list(self.root.glob('.settings.json-*')), [])

    def test_runtime_keeps_readable_preferences_when_persistence_fails(self):
        path = config.paths(self.project)['claude'][0]
        original_open = Path.open

        def fail_lock(target, *args, **kwargs):
            if target.name.endswith('.lock'):
                raise PermissionError('lock unavailable')
            return original_open(target, *args, **kwargs)

        failures = (
            ('mkdir', mock.patch.object(Path, 'mkdir', side_effect=PermissionError('read-only directory'))),
            ('lock-open', mock.patch.object(Path, 'open', autospec=True, side_effect=fail_lock)),
            ('flock', mock.patch.object(config.fcntl, 'flock', side_effect=OSError('locking unavailable'))),
            ('replace', mock.patch.object(config.os, 'replace', side_effect=PermissionError('read-only directory'))),
        )
        for boundary, failure in failures:
            self.write(path, {'features': {'fix_emdash': False}})
            original = path.read_text()
            with self.subTest(boundary=boundary), failure, mock.patch.object(sys, 'stderr', io.StringIO()) as stderr:
                self.assertEqual(config.synchronize(str(self.project), 'claude'), {'fix_emdash'})
                self.assertIn('could not persist', stderr.getvalue())
                self.assertNotIn('features paused', stderr.getvalue())
            self.assertEqual(path.read_text(), original)

    def test_unreadable_preferences_still_pause_features(self):
        path = config.paths(self.project)['claude'][0]
        self.write(path, {'features': {'fix_emdash': False}})
        read_text = Path.read_text

        def unreadable(target, *args, **kwargs):
            if target == path:
                raise PermissionError('cannot read preferences')
            return read_text(target, *args, **kwargs)

        with mock.patch.object(Path, 'read_text', autospec=True, side_effect=unreadable), \
                mock.patch.object(sys, 'stderr', io.StringIO()) as stderr:
            self.assertEqual(config.synchronize(str(self.project), 'claude'), set(config.defaults()))
        self.assertIn('features paused', stderr.getvalue())

    def test_explicit_sync_exits_nonzero_for_read_and_write_failures(self):
        path = config.paths(self.project)['claude'][0]
        for failure in ('parse', 'persist'):
            self.write(path, {'features': {'fix_emdash': False}})
            if failure == 'parse':
                path.write_text('{bad')
            original = path.read_text()
            persistence = (mock.patch.object(config.os, 'replace', side_effect=PermissionError('read-only'))
                           if failure == 'persist' else nullcontext())
            with self.subTest(failure=failure), persistence, \
                    mock.patch.object(sys, 'argv', ['plugin_config.py', 'claude', '--project', str(self.project)]), \
                    mock.patch.object(sys, 'stdout', io.StringIO()) as stdout, \
                    mock.patch.object(sys, 'stderr', io.StringIO()) as stderr:
                with self.assertRaises(SystemExit) as stopped:
                    config.main()
                self.assertNotEqual(stopped.exception.code, 0)
                self.assertEqual(stdout.getvalue(), '')
                self.assertIn('failed', stderr.getvalue())
            self.assertEqual(path.read_text(), original)
        result = subprocess.run(
            [sys.executable, '-B', config.__file__, 'claude', '--project', str(self.project)],
            text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(path))
        self.assertFalse(json.loads(path.read_text())['features']['fix_emdash'])

    def test_unchanged_settings_do_not_acquire_a_writer_lock(self):
        path = self.root / 'settings.json'
        catalog = config.defaults()
        stored = config.sync_file(path, catalog)
        with mock.patch.object(config.fcntl, 'flock') as lock:
            self.assertEqual(config.sync_file(path, catalog), stored)
        lock.assert_not_called()

    def test_contended_configuration_lock_is_bounded_and_preserves_preferences(self):
        path = self.root / 'settings.json'
        self.write(path, {'features': {'fix_emdash': False}})
        original = path.read_text()
        lock_path = path.with_name('.' + path.name + '.lock')
        with lock_path.open('a') as lock, mock.patch.object(config, 'LOCK_WAIT_SECONDS', 0.02):
            config.fcntl.flock(lock, config.fcntl.LOCK_EX)
            with self.assertRaisesRegex(TimeoutError, 'configuration lock'):
                config.sync_file(path, config.defaults())
            with mock.patch.object(sys, 'stderr', io.StringIO()) as stderr:
                stored = config.sync_file(path, config.defaults(), strict=False)
            self.assertFalse(stored['features']['fix_emdash'])
            self.assertIn('could not persist', stderr.getvalue())
            self.assertEqual(path.read_text(), original)
        self.assertFalse(config.sync_file(path, config.defaults())['features']['fix_emdash'])

    def test_sync_rereads_preferences_after_acquiring_the_writer_lock(self):
        path = self.root / 'settings.json'
        self.write(path, {'features': {'fix_emdash': True}})
        flock = config.fcntl.flock

        def concurrent_edit(descriptor, operation):
            flock(descriptor, operation)
            path.write_text('{"features":{"fix_emdash":false}}')

        with mock.patch.object(config.fcntl, 'flock', side_effect=concurrent_edit):
            stored = config.sync_file(path, config.defaults())
        self.assertFalse(stored['features']['fix_emdash'])
        self.assertEqual(json.loads(path.read_text()), stored)

    def test_feature_lookup_reads_the_catalog_once(self):
        with mock.patch.object(config, 'defaults', wraps=config.defaults) as catalog:
            self.assertTrue(config.enabled('no_broad_process_kill', self.data))
        self.assertEqual(catalog.call_count, 1)

    def test_deterministic_guard_resolves_settings_once(self):
        guidance.run_hook('UserPromptSubmit', {**self.data, 'prompt': 'Implement the fix'})
        with mock.patch.object(config, 'sync_file', wraps=config.sync_file) as reads:
            self.assertIsNone(guidance.run_hook('PreToolUse', {
                **self.data, 'tool_name': 'Write', 'tool_input': {'file_path': 'target.py', 'content': 'fix'},
            }))
        self.assertEqual(reads.call_count, 1)

    def test_question_guard_observes_configuration_changes_between_calls(self):
        path = config.paths(self.project)['claude'][0]
        prompt = {**self.data, 'prompt': 'Why did that change?'}
        self.assertIn('Question guidance:', str(guidance.run_hook('UserPromptSubmit', prompt)))
        data = {**self.data, 'tool_name': 'Write', 'tool_input': {'file_path': 'target.py', 'content': 'fix'}}
        self.assertIsNone(guidance.run_hook('PreToolUse', data))
        self.write(path, {'features': {'answer-questions': False}})
        self.assertNotIn('Question guidance:', str(guidance.run_hook('UserPromptSubmit', prompt)))
        self.write(path, {'features': {'answer-questions': True}})
        self.assertIn('Question guidance:', str(guidance.run_hook('UserPromptSubmit', prompt)))
        self.assertIsNone(guidance.run_hook('PreToolUse', data))

    def test_all_features_off_prevents_policy_and_tool_denials(self):
        global_path = config.paths(self.project)['claude'][0]
        self.write(global_path, {'features': {name: False for name in config.defaults()}})
        output = run_shared_hooks('UserPromptSubmit', {**self.data, 'prompt': 'Why?'})
        self.assertIn('Disabled plugin skills:', str(output))
        self.assertNotIn('answer-only', str(output))
        self.assertEqual(run_shared_hooks('PreToolUse', {
            **self.data, 'tool_name': 'Bash', 'tool_input': {'command': 'pkill worker'},
        }), [])
        self.assertEqual(run_shared_hooks('Stop', {
            **self.data, 'last_assistant_message': chr(0x2014),
        }), [])


    def test_response_punctuation_does_not_gate_completion_or_disable_file_checks(self):
        dash = chr(0x2014)
        self.assertEqual(run_shared_hooks('Stop', {
            **self.data, 'last_assistant_message': f'Already visible{dash}text',
        }), [])
        output = run_shared_hooks('PreToolUse', {
            **self.data, 'tool_name': 'Write', 'tool_input': {'file_path': 'x', 'content': dash},
        })
        self.assertIn('updatedInput', str(output))
        path = config.paths(self.project)['claude'][0]
        self.write(path, {'features': {'fix_emdash': False}})
        self.assertEqual(run_shared_hooks('PreToolUse', {
            **self.data, 'tool_name': 'Write', 'tool_input': {'file_path': 'x', 'content': dash},
        }), [])

    def test_skill_catalog_and_independent_opt_out(self):
        skills = {path.parent.name for path in (ROOT / 'skills').glob('*/SKILL.md')}
        self.assertEqual({name.removeprefix('skill:') for name in config.defaults()
                          if name.startswith('skill:')}, skills)
        path = config.paths(self.project)['claude'][0]
        self.write(path, {'features': {'skill:review-code': False}})
        output = guidance.run_hook('UserPromptSubmit', {**self.data, 'prompt': 'Review the code'})
        self.assertIn('Disabled plugin skills: review-code', str(output))
        for name in ('review-code', 'ioncache-ai-tools:review-code'):
            denied = guidance.run_hook('PreToolUse', {
                **self.data, 'tool_name': 'Skill', 'tool_input': {'skill': name},
            })
            self.assertEqual(denied['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertIsNone(guidance.run_hook('PreToolUse', {
            **self.data, 'tool_name': 'skill', 'tool_input': {'skill': 'security'},
        }))
        self.assertIsNone(guidance.run_hook('PreToolUse', {
            **self.data, 'tool_name': 'skill', 'tool_input': {'skill': 'another-plugin:review-code'},
        }))

    def test_retired_question_entrypoint_cannot_reactivate_stale_markers(self):
        legacy = self.root / 'legacy-registration'
        self.write(legacy / 'hooks/hooks.json', {'hooks': {'PreToolUse': [{
            'hooks': [{'command': shlex.join([
                sys.executable, str(ROOT / 'hooks/scripts/block_pending_question.py'),
            ])}],
        }]}})
        for actor in (None, 'worker'):
            data = {**self.data, 'agent_id': actor, 'tool_name': 'Write',
                    'tool_input': {'file_path': 'target.py', 'content': 'requested'}}
            marker = marker_path(data)
            marker.touch()
            self.addCleanup(lambda path=marker: path.unlink(missing_ok=True))
            with self.subTest(actor=actor):
                with mock.patch('hook_adapter_common.PLUGIN_ROOT', legacy):
                    self.assertEqual(run_shared_hooks('PreToolUse', data), [])
                self.assertEqual(run_shared_hooks('PreToolUse', data), [])
                denial = run_shared_hooks('PreToolUse', {
                    **data, 'tool_name': 'Bash', 'tool_input': {'command': 'pkill worker'},
                })
                self.assertEqual(denial[0]['hookSpecificOutput']['permissionDecision'], 'deny')

    def test_corrupt_config_allows_repair_then_restores_opt_out(self):
        path = config.paths(self.project)['claude'][0]
        path.parent.mkdir(parents=True)
        path.write_text('{bad')
        with mock.patch.object(sys, 'stderr'):
            self.assertEqual(config.synchronize(str(self.project), 'claude'), set(config.defaults()))
        self.assertEqual(path.read_text(), '{bad')
        self.write(path, {'features': {'fix_emdash': False}})
        self.assertEqual(config.synchronize(str(self.project), 'claude'), {'fix_emdash'})

    def test_question_and_scope_opt_out_do_not_disable_process_guard(self):
        guidance.run_hook('UserPromptSubmit', {**self.data, 'prompt': 'Why?'})
        path = config.paths(self.project)['claude'][0]
        self.write(path, {'features': {
            'answer-questions': False, 'scope-exactly-what-asked': False,
        }})
        self.assertIsNone(guidance.run_hook('PreToolUse', {
            **self.data, 'tool_name': 'Write', 'tool_input': {'file_path': 'x', 'content': 'requested'},
        }))
        result = run_shared_hooks('PreToolUse', {
            **self.data, 'tool_name': 'Bash', 'tool_input': {'command': 'pkill worker'},
        })
        self.assertEqual(result[0]['hookSpecificOutput']['permissionDecision'], 'deny')

    def test_model_review_modules_are_not_imported_by_active_entrypoints(self):
        script = (
            'import importlib.abc,json,sys\n'
            'class NoClaims(importlib.abc.MetaPathFinder):\n'
            ' def find_spec(self,name,*args):\n'
            '  if name in {"scope_guard","task_authorization","block_pending_question","turn_guard","turn_review","scope_review","copilot_history","claim_evidence","evidence_review","evidence_source","block_emdash_turn"}:\n'
            '   raise AssertionError("Retired module loaded: "+name)\n'
            'sys.meta_path.insert(0,NoClaims())\n'
            'import copilot_adapter,codex_adapter,guidance,docs_cache\n'
            'from hook_adapter_common import run_shared_hooks\n'
            'data=json.loads(sys.argv[1])\n'
            'guidance.run_hook("SessionStart",data)\n'
            'guidance.run_hook("UserPromptSubmit",{**data,"prompt":"Implement the change"})\n'
            'guidance.run_hook("PreToolUse",{**data,"tool_name":"Write","tool_input":{"file_path":"x","content":"claim"}})\n'
            'guidance.run_hook("PostToolUse",{**data,"tool_name":"Read","tool_input":{},"tool_response":"output"})\n'
            'run_shared_hooks("Stop",{**data,"last_assistant_message":"The tests passed."})\n'
            'url="https://example.com/api"\n'
            'docs_cache.store_fact(docs_cache.cache_key(url,None),url,"fact","copilot",length=20000)\n'
            'docs_cache.copilot_pre({**data,"sessionId":data["session_id"],"toolName":"web_fetch","toolArgs":{"url":url,"max_length":20000}})\n'
        )
        result = subprocess.run([sys.executable, '-B', '-c', script, json.dumps(self.data)], cwd=ROOT / 'hooks/scripts',
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_each_tool_rule_has_an_effective_independent_opt_out(self):
        cases = (
            ('no_broad_process_kill', 'Bash', {'command': 'pkill worker'}),
            ('block_raw_worktree_add', 'Bash', {'command': 'git worktree add ../feature -b feature'}),
            ('no-manual-lockfile-edit', 'Write', {'file_path': 'yarn.lock', 'content': 'edited'}),
            ('no_manual_lockfile_edit_bash', 'Bash', {'command': 'echo edited > yarn.lock'}),
            ('fix_emdash', 'Write', {'file_path': 'note.md', 'content': chr(0x2014)}),
        )
        path = config.paths(self.project)['claude'][0]
        for name, tool, args in cases:
            with self.subTest(feature=name):
                self.write(path, {'features': {}})
                data = {**self.data, 'tool_name': tool, 'tool_input': args}
                self.assertTrue(run_shared_hooks('PreToolUse', data))
                self.write(path, {'features': {name: False}})
                self.assertEqual(run_shared_hooks('PreToolUse', data), [])

    def test_cache_opt_out_skips_hits_workers_and_notices_on_every_host(self):
        import docs_cache
        url = 'https://example.com/api'
        docs_cache.store_fact(docs_cache.cache_key(url, None), url, 'fact', 'copilot', length=20000)
        docs_cache.set_status('worker unavailable')
        self.write(config.paths(self.project)['claude'][0], {'features': {'docs-cache': False}})
        data = {**self.data, 'tool_name': 'WebFetch', 'tool_input': {'url': url, 'prompt': 'Explain'},
                'tool_response': {'code': 200, 'result': 'source text'}}
        with mock.patch.object(docs_cache, 'start_distiller') as worker:
            for host in ('claude', 'codex'):
                for event in ('PreToolUse', 'PostToolUse', 'Stop'):
                    self.assertIsNone(docs_cache.native_hook(host, event, data))
            copilot = {**self.data, 'sessionId': self.data['session_id'], 'toolName': 'web_fetch',
                       'toolArgs': {'url': url, 'max_length': 20000},
                       'toolResult': {'resultType': 'success', 'textResultForLlm': 'source text'}}
            for handler in (docs_cache.copilot_pre, docs_cache.copilot_post, docs_cache.copilot_stop):
                self.assertIsNone(handler(copilot))
            worker.assert_not_called()
        self.assertTrue(docs_cache.fresh_facts(docs_cache.cache_key(url, None)))

    def test_documentation_reminder_has_an_independent_opt_out(self):
        self.write(config.paths(self.project)['claude'][0], {
            'features': {'documentation-first': False},
        })
        output = guidance.run_hook('UserPromptSubmit', {**self.data, 'prompt': 'Explain the code'})
        self.assertNotIn('documentation-backed', str(output))
        self.assertIn('Scope includes', str(output))
        self.assertIsNone(guidance.run_hook('PreToolUse', {
            **self.data, 'tool_name': 'Grep', 'tool_input': {'pattern': 'entry'},
        }))

    def test_retired_settings_are_pruned_without_changing_other_preferences(self):
        for host, (path, project_path) in config.paths(self.project).items():
            with self.subTest(host=host):
                self.write(path, {
                    'features': {'graphify': True, 'approval-recovery': True, 'answer-questions': False,
                                 'task-authorization': True, 'skill:task-authorization': True,
                                 'never_kill_without_asking': True, 'display-emdash': True},
                    'projects': {str(self.project): {'features': {'graphify': False, 'fix_emdash': False}}},
                })
                self.write(project_path, {'features': {'graphify': True, 'docs-cache': False}})
                config.synchronize(str(self.project), host)
                stored = json.loads(path.read_text())
                self.assertNotIn('graphify', path.read_text())
                self.assertNotIn('approval-recovery', stored['features'])
                for retired in ('task-authorization', 'skill:task-authorization', 'never_kill_without_asking',
                                'display-emdash'):
                    self.assertNotIn(retired, stored['features'])
                self.assertFalse(stored['features']['answer-questions'])
                self.assertTrue(stored['features']['fix_emdash'])
                self.assertEqual(stored['projects'][str(self.project)], {'features': {'fix_emdash': False}})
                self.assertEqual(json.loads(project_path.read_text()), {'features': {'docs-cache': False}})


if __name__ == '__main__':
    unittest.main()
