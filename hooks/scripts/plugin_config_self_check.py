#!/usr/bin/env python3
"""Offline configuration reconciliation and activation regressions."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import io
from itertools import product
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
import uuid

import pytest
import yaml

import plugin_config as config
import plugin_settings
import block_pending_question
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
        self.data = {'cwd': str(self.project), 'session_id': f'config-check-{uuid.uuid4()}',
                     '_ioncache_prompt_origin': 'user'}
        self.addCleanup(lambda: marker_path(self.data).unlink(missing_ok=True))

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def settings_command(self, *args, raw=False):
        with mock.patch.object(sys, 'stdout', io.StringIO()) as stdout, \
                mock.patch.object(sys, 'stderr', io.StringIO()) as stderr:
            try:
                code = plugin_settings.main(list(args) if raw else ['--project', str(self.project), *args])
            except SystemExit as error:
                code = error.code
        return code, stdout.getvalue(), stderr.getvalue()

    def tree_state(self):
        result = {}
        for path in self.root.rglob('*'):
            if path.is_symlink():
                result[path] = ('link', path.readlink())
            elif path.is_file():
                result[path] = ('file', path.read_bytes())
            else:
                result[path] = ('directory',)
        return result

    def test_settings_listing_is_complete_effective_and_read_only(self):
        paths = config.paths(self.project)
        self.write(paths['claude'][0], {'features': {'answer-questions': False}})
        self.write(paths['claude'][1], {'features': {'answer-questions': True}})
        self.write(paths['copilot'][1], {'features': {'skill:review-code': False}})
        legacy = paths['codex'][0].with_name('config.toml')
        legacy.parent.mkdir(parents=True)
        legacy.write_text('[ioncache-ai-tools]\ndisabled_rules = ["docs-cache"]\n')
        before = self.tree_state()

        code, output, error = self.settings_command()

        self.assertEqual(code, 0, error)
        rows = [line.split() for line in output.splitlines()
                if len(line.split()) == 2 and line.split()[1] in ('enabled', 'disabled')]
        self.assertEqual(len(rows), len(config.defaults()))
        values = dict(rows)
        self.assertEqual(values['hook:answer-questions'], 'enabled')
        self.assertEqual(values['skill:review-code'], 'disabled')
        self.assertEqual(values['hook:docs-cache'], 'disabled')
        self.assertEqual(values['hook:no_broad_process_kill'], 'enabled')
        self.assertEqual(values['instruction:documentation-first'], 'enabled')
        self.assertEqual(values['autonomous-development:execution'], 'enabled')
        self.assertEqual(values['autonomous-development:audit'], 'enabled')
        self.assertEqual(values['review:comments'], 'enabled')
        headings = ('Hooks', 'Instructions', 'Autonomous development', 'Reviews', 'Skills')
        positions = [output.index('\n' + heading + '\n') for heading in headings]
        self.assertEqual(positions, sorted(positions))
        for heading in headings:
            self.assertRegex(output, '\n' + heading + r'\n-{3,}\nSetting')
        hooks = output[positions[0]:positions[1]]
        self.assertIn('hook:autonomous-development:explicit-only', hooks)
        self.assertNotIn('instruction:', hooks)
        self.assertNotIn('skill:', hooks)
        self.assertEqual(self.tree_state(), before)

        code, output, error = self.settings_command('--global')

        self.assertEqual(code, 0, error)
        self.assertIn('Effective project', output)
        rows = [line.split() for line in output.splitlines()
                if len(line.split()) == 3 and line.split()[1] in ('enabled', 'disabled')]
        self.assertEqual(len(rows), len(config.defaults()))
        self.assertIn(['hook:answer-questions', 'disabled', 'enabled'], rows)
        self.assertIn(['skill:review-code', 'enabled', 'disabled'], rows)
        self.assertIn(['hook:docs-cache', 'disabled', 'disabled'], rows)
        self.assertNotIn('Saved:', output)
        self.assertEqual(self.tree_state(), before)

    def test_settings_grouped_flags_update_existing_storage_keys(self):
        flags = {
            'hook:answer-questions': 'answer-questions',
            'hook:autonomous-development:explicit-only': 'autonomous-development-explicit-only',
            'hook:context-handoff': 'context-handoff',
            'hook:response-validation': 'response-validation',
            'instruction:documentation-first': 'documentation-first',
            'autonomous-development:execution': 'autonomous-development',
            'autonomous-development:audit': 'autonomous-development-audit',
            'review:comments': 'review-comments',
            'review:report-json-recovery': 'review-report-json-recovery',
            'skill:comments': 'skill:comments',
            'skill:context-handoff': 'skill:context-handoff',
        }

        code, output, error = self.settings_command(*(f'--{name}=disabled' for name in flags))

        self.assertEqual(code, 0, error)
        for public in flags:
            self.assertRegex(output, public + r'\s+disabled')
        for _, path in config.paths(self.project).values():
            self.assertEqual(json.loads(path.read_text())['features'],
                             {stored: False for stored in flags.values()})
        self.assertEqual(config.synchronize(str(self.project), persist=False), set(flags.values()))

    def test_response_validation_defaults_and_opt_in_in_the_settings_view(self):
        before = self.tree_state()
        for scope in ((), ('--global',)):
            with self.subTest(scope=scope):
                code, output, error = self.settings_command('--json', *scope)
                self.assertEqual(code, 0, error)
                rows = {row['name']: row for group in json.loads(output)['groups'] for row in group['settings']}
                self.assertEqual(rows['hook:response-validation'], {
                    'name': 'hook:response-validation', 'enabled': False, 'effective': False,
                })
                self.assertEqual(self.tree_state(), before)

        code, output, error = self.settings_command('--json', '--global', '--hook:response-validation=enabled')
        self.assertEqual(code, 0, error)
        rows = {row['name']: row for group in json.loads(output)['groups'] for row in group['settings']}
        self.assertEqual(rows['hook:response-validation'], {
            'name': 'hook:response-validation', 'enabled': True, 'effective': True,
        })
        self.assertNotIn('response-validation', config.synchronize(str(self.project), persist=False))

    def test_settings_json_view_is_read_only_and_shares_effective_states(self):
        paths = config.paths(self.project)
        self.write(paths['claude'][0], {'features': {'answer-questions': False}})
        self.write(paths['claude'][1], {'features': {'answer-questions': True}})
        before = self.tree_state()

        code, output, error = self.settings_command('--json', '--global')

        self.assertEqual(code, 0, error)
        result = json.loads(output)
        self.assertEqual(result['scope'], 'global')
        self.assertEqual(result['saved'], [])
        rows = {row['name']: row for group in result['groups'] for row in group['settings']}
        self.assertEqual(len(rows), len(config.defaults()))
        self.assertEqual(rows['hook:answer-questions'],
                         {'name': 'hook:answer-questions', 'enabled': False, 'effective': True})
        self.assertEqual(self.tree_state(), before)

        code, output, error = self.settings_command('--json', '--ui', '--hook:docs-cache=disabled')

        self.assertEqual(code, 0, error)
        result = json.loads(output)
        self.assertEqual(set(result['saved']), {str(pair[1]) for pair in paths.values()})
        rows = {row['name']: row for group in result['groups'] for row in group['settings']}
        self.assertEqual(len(rows), len(config.defaults()))
        self.assertFalse(rows['hook:docs-cache']['enabled'])
        self.assertTrue(rows['hook:answer-questions']['enabled'])
        for _, path in paths.values():
            self.assertFalse(json.loads(path.read_text())['features']['docs-cache'])

    def test_settings_ui_opt_out_preserves_cli_recovery_and_other_features(self):
        code, output, error = self.settings_command('--json', '--ui',
                                                   '--hook:plugin-settings-ui=disabled')
        self.assertEqual(code, 0, error)
        self.assertFalse(json.loads(output)['uiEnabled'])
        before = self.tree_state()
        code, output, error = self.settings_command('--json', '--ui', '--hook:docs-cache=disabled')
        self.assertNotEqual(code, 0)
        self.assertEqual(output, '')
        self.assertIn('--hook:plugin-settings-ui=enabled', error)
        self.assertEqual(self.tree_state(), before)
        self.assertEqual(config.synchronize(str(self.project), persist=False),
                         {'plugin-settings-ui', 'response-validation'})

        self.assertEqual(self.settings_command('--hook:plugin-settings-ui=enabled')[0], 0)
        code, output, error = self.settings_command('--json', '--ui', '--hook:docs-cache=disabled')
        self.assertEqual(code, 0, error)
        self.assertTrue(json.loads(output)['uiEnabled'])
        self.assertEqual(config.synchronize(str(self.project), persist=False), {'docs-cache', 'response-validation'})

    def test_settings_native_command_parses_arguments_without_shell_execution(self):
        project = self.root / 'project with spaces; literal'
        project.mkdir()
        arguments = f'--project {shlex.quote(str(project))} --hook:answer-questions=disabled'
        code, output, error = self.settings_command('--command', arguments, raw=True)
        self.assertEqual(code, 0, error)
        self.assertIn(str(project), output)
        for _, path in config.paths(project).values():
            self.assertFalse(json.loads(path.read_text())['features']['answer-questions'])
        before = self.tree_state()

        for arguments in ('"unterminated', '--list; touch unexpected', '--command recursive'):
            code, _, _ = self.settings_command('--command', arguments, raw=True)
            self.assertNotEqual(code, 0)
            self.assertEqual(self.tree_state(), before)

    @pytest.mark.process
    def test_native_claude_settings_command_uses_namespaced_skill_and_persists_changes(self):
        cli = ROOT / 'node_modules/.bin/claude'
        self.assertTrue(cli.exists(), 'Install contributor tooling with npm ci')
        home = self.root / 'native-home'
        self.write(home / '.claude/.claude.json', {})
        env = {key: value for key, value in os.environ.items()
               if not any(word in key for word in ('TOKEN', 'API_KEY', 'AUTH', 'CLAUDE', 'ANTHROPIC'))}
        env.update({
            'HOME': str(home), 'CLAUDE_CONFIG_DIR': str(home / '.claude'),
            'COPILOT_HOME': str(home / '.copilot'), 'CODEX_HOME': str(home / '.codex'),
            'XDG_CACHE_HOME': str(home / '.cache'), 'PWD': str(self.project),
            'ANTHROPIC_API_KEY': 'offline-test-key', 'ANTHROPIC_BASE_URL': 'http://127.0.0.1:1',
            'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1', 'DISABLE_AUTOUPDATER': '1',
            'NO_PROXY': '127.0.0.1',
        })
        command = [
            str(cli), '--plugin-dir', str(ROOT), '--setting-sources', '',
            '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}', '--no-chrome',
        ]
        for arguments in ('', '--list', '--hook:docs-cache=disabled',
                          '--hook:plugin-settings-ui=disabled', ''):
            result = subprocess.run(
                [*command, '-p', '/ioncache-ai-tools:plugin-settings ' + arguments],
                cwd=self.project, env=env, text=True, capture_output=True, timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            setting = ('hook:plugin-settings-ui' if arguments == '--hook:plugin-settings-ui=disabled'
                       else 'hook:docs-cache')
            self.assertIn(setting, result.stdout)
            self.assertNotIn('Native settings command unavailable', result.stdout)
        for _, path in config.paths(self.project).values():
            self.assertFalse(json.loads(path.read_text())['features']['docs-cache'])

    def test_settings_help_groups_public_flags_without_reading_preferences(self):
        path = config.paths(self.project)['claude'][0]
        path.parent.mkdir(parents=True)
        path.write_text('{bad')

        code, output, error = self.settings_command('--help')

        self.assertEqual(code, 0, error)
        for heading in ('Hooks', 'Instructions', 'Autonomous development', 'Reviews', 'Skills'):
            self.assertIn('\n' + heading + ':\n', output)
        self.assertIn('--hook:answer-questions', output)
        self.assertIn('--autonomous-development:execution', output)
        self.assertNotIn('--answer-questions', output)
        self.assertEqual(path.read_text(), '{bad')
        self.assertEqual(list(self.root.rglob('*.lock')), [])

    def test_settings_unknown_catalog_entry_is_not_silently_omitted(self):
        catalog = {**config.defaults(), 'new-uncategorized-feature': True}
        with mock.patch.object(config, 'defaults', return_value=catalog):
            code, output, error = self.settings_command()
        self.assertNotEqual(code, 0)
        self.assertEqual(output, '')
        self.assertIn('setting has no display group: new-uncategorized-feature', error)
        self.assertEqual(list(self.root.rglob(config.FILENAME)), [])

    def test_settings_project_updates_all_hosts_without_changing_globals(self):
        paths = config.paths(self.project)
        for global_path, _ in paths.values():
            self.write(global_path, {
                'features': {'answer-questions': False},
                'projects': {str(self.project): {'features': {'answer-questions': False}}},
            })
        self.write(paths['copilot'][1], {'features': {'docs-cache': False}})
        originals = {path: path.read_bytes() for path, _ in paths.values()}

        code, output, error = self.settings_command('--hook:answer-questions=enabled', '--skill:review-code=disabled')

        self.assertEqual(code, 0, error)
        self.assertIn('Scope: project', output)
        for global_path, project_path in paths.values():
            self.assertEqual(global_path.read_bytes(), originals[global_path])
            features = json.loads(project_path.read_text())['features']
            expected = {'answer-questions': True, 'skill:review-code': False}
            if project_path == paths['copilot'][1]:
                expected['docs-cache'] = False
            self.assertEqual(features, expected)
        self.assertEqual(config.synchronize(str(self.project), persist=False),
                         {'docs-cache', 'skill:review-code', 'response-validation'})
        self.assertEqual(self.settings_command('--hook:answer-questions=disabled')[0], 0)
        self.assertIn('answer-questions', config.synchronize(str(self.project), persist=False))

    def test_settings_home_project_collision_preserves_globals_and_recovers(self):
        paths = config.paths(self.project)
        for global_path, _ in paths.values():
            self.write(global_path, {'features': {'answer-questions': True}})
        originals = {path: path.read_bytes() for path, _ in paths.values()}
        before = self.tree_state()
        home_args = ('--project', str(Path.home()))

        code, output, error = self.settings_command(*home_args, '--hook:answer-questions=disabled')

        self.assertNotEqual(code, 0)
        self.assertNotIn('Saved:', output)
        self.assertIn('--project', error)
        self.assertIn('--global', error)
        self.assertEqual(self.tree_state(), before)
        code, _, error = self.settings_command(*home_args)
        self.assertEqual(code, 0, error)
        self.assertEqual(self.tree_state(), before)

        code, _, error = self.settings_command('--hook:answer-questions=disabled')

        self.assertEqual(code, 0, error)
        for global_path, project_path in paths.values():
            self.assertEqual(global_path.read_bytes(), originals[global_path])
            self.assertFalse(json.loads(project_path.read_text())['features']['answer-questions'])
        before = self.tree_state()
        code, _, error = self.settings_command(*home_args, '--hook:answer-questions=disabled')
        self.assertNotEqual(code, 0)
        self.assertIn('--project', error)
        self.assertEqual(self.tree_state(), before)

    def test_settings_later_host_global_link_is_rejected_before_writes(self):
        paths = config.paths(self.project)
        for global_path, _ in paths.values():
            self.write(global_path, {'features': {'answer-questions': True}})
        link = paths['codex'][1]
        link.parent.mkdir()
        link.symlink_to(paths['claude'][0])
        before = self.tree_state()

        code, output, error = self.settings_command('--hook:answer-questions=disabled')

        self.assertNotEqual(code, 0)
        self.assertNotIn('Saved:', output)
        self.assertIn(str(paths['claude'][0]), error)
        self.assertIn('--project', error)
        self.assertIn('--global', error)
        self.assertEqual(self.tree_state(), before)
        code, _, error = self.settings_command()
        self.assertEqual(code, 0, error)
        self.assertEqual(self.tree_state(), before)

        code, _, error = self.settings_command('--global', '--hook:answer-questions=disabled')

        self.assertEqual(code, 0, error)
        self.assertTrue(link.is_symlink())
        for global_path, _ in paths.values():
            self.assertFalse(json.loads(global_path.read_text())['features']['answer-questions'])
        before = self.tree_state()
        code, _, error = self.settings_command('--hook:answer-questions=enabled')
        self.assertNotEqual(code, 0)
        self.assertIn('--global', error)
        self.assertEqual(self.tree_state(), before)

    def test_settings_global_updates_preserve_and_display_project_overrides(self):
        paths = config.paths(self.project)
        self.write(paths['claude'][0], {
            'features': {'answer-questions': False},
            'projects': {str(self.project): {'features': {'answer-questions': False}}},
        })
        self.write(paths['copilot'][1], {'features': {'docs-cache': False}})
        project_original = paths['copilot'][1].read_bytes()

        code, output, error = self.settings_command('--global', '--hook:answer-questions=enabled',
                                                    '--hook:docs-cache=enabled')

        self.assertEqual(code, 0, error)
        self.assertIn('Effective project', output)
        self.assertRegex(output, r'hook:answer-questions\s+enabled\s+disabled')
        self.assertRegex(output, r'hook:docs-cache\s+enabled\s+disabled')
        self.assertIn('Project overrides differ', output)
        for global_path, _ in paths.values():
            features = json.loads(global_path.read_text())['features']
            self.assertEqual(set(features), set(config.defaults()))
            self.assertTrue(features['answer-questions'])
            self.assertTrue(features['docs-cache'])
        self.assertEqual(json.loads(paths['claude'][0].read_text())['projects'],
                         {str(self.project): {'features': {'answer-questions': False}}})
        self.assertEqual(paths['copilot'][1].read_bytes(), project_original)
        self.assertEqual(config.synchronize(str(self.root), persist=False), {'response-validation'})

    def test_settings_global_update_preserves_legacy_codex_preferences(self):
        path = config.paths(self.project)['codex'][0]
        legacy = path.with_name('config.toml')
        legacy.parent.mkdir(parents=True)
        text = '[ioncache-ai-tools]\ndisabled_rules = ["docs-cache"]\n'
        legacy.write_text(text)

        code, _, error = self.settings_command('--global', '--hook:answer-questions=disabled')

        self.assertEqual(code, 0, error)
        self.assertEqual(legacy.read_text(), text)
        features = json.loads(path.read_text())['features']
        self.assertFalse(features['docs-cache'])
        self.assertFalse(features['answer-questions'])

    def test_settings_reject_bad_flags_without_writing_and_accept_a_corrected_request(self):
        for flag in ('--unknown=disabled', '--hook:answer-questions=false', '--hook:answer=enabled',
                     '--answer-questions=enabled', '--instruction:answer-questions=enabled', 'disable docs-cache'):
            with self.subTest(flag=flag):
                code, output, error = self.settings_command('--hook:docs-cache=disabled', flag)
                self.assertNotEqual(code, 0)
                self.assertEqual(output, '')
                self.assertIn('error:', error)
                self.assertEqual(list(self.root.rglob(config.FILENAME)), [])
        code, _, error = self.settings_command('--hook:docs-cache=disabled', '--hook:docs-cache=enabled')
        self.assertEqual(code, 0, error)
        self.assertNotIn('docs-cache', config.synchronize(str(self.project), persist=False))

    def test_settings_reject_invalid_project_paths_without_side_effects(self):
        for global_path, _ in config.paths(self.project).values():
            self.write(global_path, {'features': {'answer-questions': True}})
        regular_file = self.root / 'not-a-directory'
        regular_file.write_text('unchanged')
        for project in (self.root / 'missing', regular_file):
            with self.subTest(project=project):
                before = self.tree_state()
                code, output, error = self.settings_command(
                    '--project', str(project), '--hook:answer-questions=disabled')

                self.assertNotEqual(code, 0)
                self.assertNotIn('Saved:', output)
                self.assertIn('project directory', error)
                self.assertEqual(self.tree_state(), before)

                code, _, error = self.settings_command('--hook:answer-questions=disabled')

                self.assertEqual(code, 0, error)
                for global_path, project_path in config.paths(self.project).values():
                    self.assertTrue(json.loads(global_path.read_text())['features']['answer-questions'])
                    self.assertFalse(json.loads(project_path.read_text())['features']['answer-questions'])

    def test_sync_file_rejects_invalid_updates_before_filesystem_changes(self):
        catalog = config.defaults()
        existing = self.root / 'existing.json'
        self.write(existing, {'features': {'answer-questions': True, 'docs-cache': False}})
        missing = self.root / 'missing' / 'settings.json'
        invalid = ({'unknown': True}, {'answer-questions': 'disabled'}, {'answer-questions': 0})
        before = self.tree_state()
        for path, updates in product((existing, missing), invalid):
            with self.subTest(path=path, updates=updates):
                with self.assertRaisesRegex(ValueError, 'shipped feature IDs and boolean values'):
                    config.sync_file(path, catalog, updates=updates)
                self.assertEqual(self.tree_state(), before)

        config.sync_file(existing, catalog, updates={'answer-questions': False})

        features = json.loads(existing.read_text())['features']
        self.assertFalse(features['answer-questions'])
        self.assertFalse(features['docs-cache'])

    def test_settings_validate_every_host_before_writes(self):
        path = config.paths(self.project)['codex'][1]
        path.parent.mkdir(parents=True)
        path.write_text('{bad')
        before = {file: file.read_bytes() for file in self.root.rglob('*') if file.is_file()}

        code, output, error = self.settings_command('--hook:answer-questions=disabled')

        self.assertNotEqual(code, 0)
        self.assertEqual(output, '')
        self.assertIn('No success confirmed', error)
        self.assertEqual({file: file.read_bytes() for file in self.root.rglob('*') if file.is_file()}, before)

    def test_settings_partial_failure_is_reported_and_retry_completes(self):
        paths = config.paths(self.project)
        replace = config.os.replace

        def fail_copilot(source, target):
            if target == paths['copilot'][1]:
                raise PermissionError('copilot settings unavailable')
            return replace(source, target)

        with mock.patch.object(config.os, 'replace', side_effect=fail_copilot):
            code, output, error = self.settings_command('--hook:answer-questions=disabled')
        self.assertNotEqual(code, 0)
        self.assertIn(str(paths['claude'][1]), output)
        self.assertIn('partial', error)
        self.assertIn('copilot settings unavailable', error)
        self.assertFalse(paths['copilot'][1].exists())
        self.assertFalse(paths['codex'][1].exists())
        self.assertEqual(self.settings_command()[0], 0)

        code, _, error = self.settings_command('--hook:answer-questions=disabled')

        self.assertEqual(code, 0, error)
        for _, path in paths.values():
            self.assertFalse(json.loads(path.read_text())['features']['answer-questions'])

    def test_settings_post_write_divergence_is_reported_and_retry_completes(self):
        paths = config.paths(self.project)
        update = plugin_settings.update
        for global_scope, enabled, host in product((False, True), (False, True), paths):
            with self.subTest(global_scope=global_scope, enabled=enabled, host=host):
                targets = {name: pair[0 if global_scope else 1] for name, pair in paths.items()}
                scope = ('--global',) if global_scope else ()
                flag = '--hook:answer-questions=' + ('enabled' if enabled else 'disabled')

                def competing_update(*args, **kwargs):
                    result = update(*args, **kwargs)
                    document = json.loads(targets[host].read_text())
                    document['features']['answer-questions'] = not enabled
                    self.write(targets[host], document)
                    return result

                with mock.patch.object(plugin_settings, 'update', side_effect=competing_update):
                    code, output, error = self.settings_command(*scope, flag)

                self.assertNotEqual(code, 0)
                self.assertNotIn('Scope:', output)
                self.assertIn('concurrently', error)
                self.assertIn('No success confirmed', error)
                for name, path in targets.items():
                    self.assertEqual(json.loads(path.read_text())['features']['answer-questions'],
                                     not enabled if name == host else enabled)
                code, _, error = self.settings_command(*scope)
                self.assertEqual(code, 0, error)

                code, output, error = self.settings_command(*scope, flag)

                self.assertEqual(code, 0, error)
                self.assertIn('Scope:', output)
                for path in targets.values():
                    self.assertEqual(json.loads(path.read_text())['features']['answer-questions'], enabled)

    def test_settings_final_read_failure_preserves_writes_and_retry_completes(self):
        paths = config.paths(self.project)
        update = plugin_settings.update
        read_text = Path.read_text
        for global_scope in (False, True):
            with self.subTest(global_scope=global_scope):
                scope = ('--global',) if global_scope else ()
                targets = [pair[0 if global_scope else 1] for pair in paths.values()]
                written = False

                def completed_update(*args, **kwargs):
                    nonlocal written
                    result = update(*args, **kwargs)
                    written = True
                    return result

                def fail_final_read(path, *args, **kwargs):
                    if written and path == targets[-1]:
                        raise OSError('post-write settings read unavailable')
                    return read_text(path, *args, **kwargs)

                with mock.patch.object(plugin_settings, 'update', side_effect=completed_update), \
                        mock.patch.object(Path, 'read_text', fail_final_read):
                    code, output, error = self.settings_command(*scope, '--hook:answer-questions=disabled')

                self.assertNotEqual(code, 0)
                self.assertNotIn('Scope:', output)
                self.assertIn('post-write settings read unavailable', error)
                self.assertIn('No success confirmed', error)
                for path in targets:
                    self.assertFalse(json.loads(path.read_text())['features']['answer-questions'])
                code, _, error = self.settings_command(*scope)
                self.assertEqual(code, 0, error)

                code, output, error = self.settings_command(*scope, '--hook:answer-questions=disabled')

                self.assertEqual(code, 0, error)
                self.assertIn('Scope:', output)
                for path in targets:
                    self.assertFalse(json.loads(path.read_text())['features']['answer-questions'])

    def test_settings_verification_rejects_a_mismatch_restored_after_readback(self):
        paths = config.paths(self.project)
        update = plugin_settings.update
        read_text = Path.read_text
        for global_scope, enabled in product((False, True), (False, True)):
            with self.subTest(global_scope=global_scope, enabled=enabled):
                scope = ('--global',) if global_scope else ()
                state = 'enabled' if enabled else 'disabled'
                flag = '--hook:answer-questions=' + state
                target = paths['codex'][0 if global_scope else 1]
                written = False
                restored = False

                def competing_update(*args, **kwargs):
                    nonlocal written
                    result = update(*args, **kwargs)
                    document = json.loads(read_text(target))
                    document['features']['answer-questions'] = not enabled
                    self.write(target, document)
                    written = True
                    return result

                def restore_after_read(path, *args, **kwargs):
                    nonlocal restored
                    text = read_text(path, *args, **kwargs)
                    if written and path == target and not restored:
                        document = json.loads(text)
                        document['features']['answer-questions'] = enabled
                        self.write(target, document)
                        restored = True
                    return text

                with mock.patch.object(plugin_settings, 'update', side_effect=competing_update), \
                        mock.patch.object(Path, 'read_text', restore_after_read):
                    code, output, error = self.settings_command(*scope, flag)

                self.assertTrue(restored)
                self.assertNotEqual(code, 0)
                self.assertNotIn('Scope:', output)
                self.assertIn('concurrently', error)
                self.assertIn('No success confirmed', error)
                for pair in paths.values():
                    path = pair[0 if global_scope else 1]
                    self.assertEqual(json.loads(path.read_text())['features']['answer-questions'], enabled)
                code, output, error = self.settings_command(*scope)
                self.assertEqual(code, 0, error)
                self.assertRegex(output, r'hook:answer-questions\s+' + state)
                code, output, error = self.settings_command(*scope, flag)
                self.assertEqual(code, 0, error)
                self.assertRegex(output, r'hook:answer-questions\s+' + state)

    def test_settings_readback_requires_each_requested_stored_value(self):
        update = plugin_settings.update
        for global_scope, removal in product((False, True), ('file', 'feature')):
            with self.subTest(global_scope=global_scope, removal=removal):
                scope = ('--global',) if global_scope else ()
                target = config.paths(self.project)['codex'][0 if global_scope else 1]

                def remove_update(*args, **kwargs):
                    result = update(*args, **kwargs)
                    if removal == 'file':
                        target.unlink()
                    else:
                        document = json.loads(target.read_text())
                        del document['features']['answer-questions']
                        self.write(target, document)
                    return result

                with mock.patch.object(plugin_settings, 'update', side_effect=remove_update):
                    code, output, error = self.settings_command(*scope, '--hook:answer-questions=enabled')

                self.assertNotEqual(code, 0)
                self.assertNotIn('Scope:', output)
                self.assertIn(str(target), error)
                code, _, error = self.settings_command(*scope, '--hook:answer-questions=enabled')
                self.assertEqual(code, 0, error)
                self.assertTrue(json.loads(target.read_text())['features']['answer-questions'])

    def test_settings_update_rereads_symlink_target_under_lock(self):
        target = self.root / 'shared.json'
        self.write(target, {'features': {'answer-questions': True}})
        path = config.paths(self.project)['claude'][1]
        path.parent.mkdir()
        path.symlink_to(target)
        acquire = config.acquire_lock

        def concurrent_edit(lock):
            acquire(lock)
            if Path(lock.name).parent == target.parent:
                self.write(target, {'features': {'answer-questions': True, 'docs-cache': False}})

        with mock.patch.object(config, 'acquire_lock', side_effect=concurrent_edit):
            code, _, error = self.settings_command('--hook:answer-questions=disabled')

        self.assertEqual(code, 0, error)
        self.assertTrue(path.is_symlink())
        self.assertEqual(json.loads(target.read_text())['features'],
                         {'answer-questions': False, 'docs-cache': False})
        with mock.patch.object(config, 'acquire_lock', side_effect=AssertionError('unnecessary lock')):
            self.assertEqual(self.settings_command('--hook:answer-questions=disabled')[0], 0)

    def test_settings_skill_metadata_advertises_command_flags(self):
        source = (ROOT / 'skills/plugin-settings/SKILL.md').read_text()
        self.assertTrue(source.startswith('---\n'))
        header, separator, _ = source.partition('\n---\n')
        self.assertTrue(separator, 'Skill frontmatter must have a closing delimiter')
        metadata = yaml.safe_load(header)
        for path in ('.claude-plugin/plugin.json', '.codex-plugin/plugin.json',
                     '.github/plugin/plugin.json'):
            manifest = json.loads((ROOT / path).read_text())
            self.assertEqual(f'{manifest["name"]}:{metadata["name"]}',
                             'ioncache-ai-tools:plugin-settings')
        hint = metadata['argument-hint']
        self.assertIsInstance(hint, str)
        flags = set(re.findall(r'--[a-z]+(?:-[a-z]+)*', hint))
        self.assertTrue({'--list', '--help', '--global', '--project'} <= flags, hint)
        self.assertRegex(hint, r'--project(?:\s+|=)[^\]\s]+')
        self.assertRegex(hint, r'--[^=\s]+=(?:enabled\|disabled|disabled\|enabled)')

    @pytest.mark.process
    def test_installed_settings_helper_runs_from_an_unrelated_project(self):
        install = self.root / 'plugin with spaces'
        install.symlink_to(ROOT, target_is_directory=True)
        skill = install / 'skills/plugin-settings'
        helper = skill / '../../hooks/scripts/plugin_settings.py'
        self.assertIn('../../hooks/scripts/plugin_settings.py', (skill / 'SKILL.md').read_text())
        for args in ([], ['--hook:answer-questions=disabled']):
            result = subprocess.run([sys.executable, '-B', str(helper), *args], cwd=self.project,
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f'Project: {self.project}', result.stdout)
            if not args:
                self.assertEqual(list(self.root.rglob(config.FILENAME)), [])
        for _, path in config.paths(self.project).values():
            self.assertFalse(json.loads(path.read_text())['features']['answer-questions'])


    def test_guidance_deadline_reports_unavailability_and_next_call_recovers(self):
        def slow_settings(*args, **kwargs):
            signal.setitimer(signal.ITIMER_REAL, 0.01)
            time.sleep(1)

        write = {**self.data, 'tool_name': 'Write', 'tool_input': {'file_path': 'x', 'content': 'continued'}}
        guidance.run_hook('UserPromptSubmit', {**self.data, 'prompt': 'Why did it fail?'})
        self.assertEqual(block_pending_question.run_hook(write)['hookSpecificOutput']['permissionDecision'], 'deny')
        # A non-question instruction clears the marker even when guidance and settings both fail.
        with (
            mock.patch.object(guidance, 'feature_settings', side_effect=slow_settings),
            mock.patch.object(config, 'synchronize', side_effect=OSError('settings unavailable')),
            mock.patch.object(sys, 'stderr', io.StringIO()),
        ):
            output = guidance.run_hook('UserPromptSubmit', {**self.data, 'prompt': 'Implement the fix'})
        self.assertIn('invocation deadline', output['systemMessage'])
        self.assertNotIn('hookSpecificOutput', output)
        self.assertFalse(marker_path(self.data).exists())
        self.assertIsNone(block_pending_question.run_hook(write))
        self.assertIsNone(guidance.run_hook('PreToolUse', write))
        self.assertIn('additionalContext', guidance.run_hook('UserPromptSubmit', {
            **self.data, 'prompt': 'Implement the fix',
        })['hookSpecificOutput'])

    def test_bounded_review_guidance_is_stateless(self):
        for event in ('SessionStart', 'SubagentStart', 'UserPromptSubmit'):
            for identity in ('root', 'reviewer'):
                data = {**self.data, 'session_id': identity, 'agent_id': identity,
                        'prompt': 'Review only the assigned category'}
                output = guidance.run_hook(event, data)
                message = output['hookSpecificOutput']['additionalContext']
                self.assertIn('Assigned review workers and validators', message)
                self.assertIn('do not load engineering-judgment, review-code', message)
                self.assertNotIn('permissionDecision', str(output))
                self.assertIsNone(guidance.run_hook('PreToolUse', {
                    **data, 'tool_name': 'Read', 'tool_input': {'file_path': 'source.py'},
                }))
        self.write(config.paths(self.project)['claude'][0], {
            'features': {'engineering-judgment': False},
        })
        output = guidance.run_hook('SubagentStart', self.data)
        self.assertNotIn('Assigned review workers and validators', str(output))
        self.assertIn('documentation-backed', str(output))

    def test_failed_guidance_cannot_recreate_a_verified_question_marker(self):
        data = {**self.data, 'prompt': 'Why did this change?'}
        guidance.run_hook('UserPromptSubmit', data)
        self.assertTrue(marker_path(data).exists())
        with mock.patch.object(guidance, 'evaluate', side_effect=OSError('guidance unavailable')), \
                mock.patch.object(sys, 'stderr', io.StringIO()):
            output = guidance.run_hook('UserPromptSubmit', data)
        self.assertIn('guidance checks unavailable', output['systemMessage'])
        self.assertNotIn('Question turn:', str(output))
        self.assertFalse(marker_path(data).exists())
        self.assertIsNone(block_pending_question.run_hook({
            **self.data, 'tool_name': 'Write', 'tool_input': {'file_path': 'report.txt', 'content': 'continued'},
        }))

    def test_install_update_adds_preserves_and_removes_settings(self):
        path = self.root / 'config.json'
        old = {'features': {'retained': True, 'disabled': True, 'graphify': True}}
        self.assertEqual(config.sync_file(path, old['features']), old)
        self.write(path, {'features': {'retained': False, 'disabled': False, 'graphify': False}})
        new = {'retained': True, 'disabled': True, 'added': True}
        expected = {'features': {'retained': False, 'disabled': False, 'added': True}}
        self.assertEqual(config.sync_file(path, new), expected)
        self.assertEqual(json.loads(path.read_text()), expected)
        stamp = path.stat().st_mtime_ns
        config.sync_file(path, new)
        self.assertEqual(path.stat().st_mtime_ns, stamp)

    def test_older_catalog_writes_preserve_newer_opt_outs_in_every_scope(self):
        name = 'review-report-json-recovery'
        newer = config.defaults()
        older = {key: value for key, value in newer.items() if key != name}
        documents = (
            (True, {'features': {name: False}}),
            (False, {'features': {name: False}}),
            (True, {'features': {}, 'projects': {str(self.project): {'features': {name: False}}}}),
        )
        path = self.root / 'mixed-versions.json'
        for complete, document in documents:
            with self.subTest(complete=complete, document=document):
                self.write(path, document)
                config.sync_file(path, older, complete=complete, updates={'fix_emdash': False})
                stored = json.loads(path.read_text())
                scope = stored['projects'][str(self.project)] if 'projects' in document else stored
                self.assertIs(scope['features'].get(name), False)
                config.sync_file(path, newer, complete=complete)
                stored = json.loads(path.read_text())
                scope = stored['projects'][str(self.project)] if 'projects' in document else stored
                self.assertFalse(scope['features'][name])
                self.assertFalse(stored['features']['fix_emdash'])
                stamp = path.stat().st_mtime_ns
                config.sync_file(path, older, complete=complete)
                self.assertEqual(path.stat().st_mtime_ns, stamp)

    def test_unknown_settings_are_preserved_but_never_effective(self):
        name = 'skill:future-feature'
        global_path, project_path = config.paths(self.project)['claude']
        tool = {**self.data, 'tool_name': 'Skill', 'tool_input': {'skill': 'ioncache-ai-tools:future-feature'}}
        newer = {**config.defaults(), name: True}
        for scope, enabled in product(('global', 'embedded', 'project'), (False, True)):
            with self.subTest(scope=scope, enabled=enabled):
                self.write(global_path, {'features': {}})
                project_path.unlink(missing_ok=True)
                document = {'features': {name: enabled, 'fix_emdash': False}}
                if scope == 'embedded':
                    document = {'features': {}, 'projects': {str(self.project): document}}
                path = project_path if scope == 'project' else global_path
                self.write(path, document)

                snapshot = config.feature_settings(self.data)
                self.assertEqual(snapshot.disabled, {'fix_emdash', 'response-validation'})
                self.assertNotIn(name, snapshot.catalog)
                self.assertFalse(config.enabled(name, self.data))
                self.assertIsNone(guidance.run_hook('PreToolUse', tool))
                stored = json.loads(path.read_text())
                values = stored['projects'][str(self.project)] if scope == 'embedded' else stored
                self.assertIs(values['features'].get(name), enabled)

                with mock.patch.object(config, 'defaults', return_value=newer):
                    self.assertEqual(config.enabled(name, self.data), enabled)
                    output = guidance.run_hook('PreToolUse', tool)
                if enabled:
                    self.assertIsNone(output)
                else:
                    self.assertEqual(output['hookSpecificOutput']['permissionDecision'], 'deny')

    def test_embedded_project_overrides_match_aliases_in_hooks_and_commands(self):
        link = self.root / 'project-link'
        link.symlink_to(self.project, target_is_directory=True)
        spellings = (self.project, link, self.project / '..' / 'project')
        path = config.paths(self.project)['claude'][0]
        for stored, current in product(spellings, repeat=2):
            with self.subTest(stored=stored, current=current):
                self.write(path, {'features': {}, 'projects': {
                    str(stored): {'features': {'fix_emdash': False}},
                }})
                self.assertFalse(config.enabled('fix_emdash', {**self.data, 'cwd': str(current)}))
                with mock.patch.object(sys, 'argv', [
                    'plugin_config.py', 'claude', '--project', str(current), '--feature', 'fix_emdash',
                ]), mock.patch.object(sys, 'stdout', io.StringIO()) as stdout:
                    config.main()
                self.assertEqual(json.loads(stdout.getvalue()), {'enabled': False})
                code, output, error = self.settings_command('--project', str(current), '--json', raw=True)
                self.assertEqual(code, 0, error)
                rows = {row['name']: row for group in json.loads(output)['groups'] for row in group['settings']}
                self.assertFalse(rows['hook:fix_emdash']['effective'])

    def test_conflicting_project_aliases_keep_opt_outs_and_project_file_precedence(self):
        link = self.root / 'project-link'
        link.symlink_to(self.project, target_is_directory=True)
        path, local = config.paths(self.project)['claude']
        entries = [(str(self.project), {'features': {'fix_emdash': True}}),
                   (str(link), {'features': {'fix_emdash': False}})]
        for ordered in (entries, list(reversed(entries))):
            with self.subTest(ordered=ordered):
                self.write(path, {'features': {}, 'projects': dict(ordered)})
                self.assertIn('fix_emdash', config.synchronize(str(self.project), persist=False, strict=True))
                self.assertIn('fix_emdash', config.synchronize(str(link), persist=False, strict=True))
                self.write(local, {'features': {'fix_emdash': True}})
                self.assertNotIn('fix_emdash', config.synchronize(str(link), persist=False, strict=True))
                local.unlink()

    def test_unrelated_project_alias_failure_preserves_effective_settings(self):
        unrelated = self.root / 'unrelated-loop'
        unrelated.symlink_to(unrelated.name)
        path, local = config.paths(self.project)['claude']
        self.write(path, {'features': {'fix_emdash': False}, 'projects': {
            str(unrelated): {'features': {'no_broad_process_kill': False}},
            str(self.project): {'features': {'fix_emdash': True, 'docs-cache': False}},
        }})
        self.write(local, {'features': {'fix_emdash': False}})
        resolve = Path.resolve

        def fail_unrelated(target, *args, **kwargs):
            if target == unrelated:
                raise failure
            return resolve(target, *args, **kwargs)

        for failure in (RuntimeError('Symlink loop'), PermissionError('Alias inaccessible')):
            with self.subTest(failure=type(failure).__name__), \
                    mock.patch.object(Path, 'resolve', autospec=True, side_effect=fail_unrelated), \
                    mock.patch.object(sys, 'stderr', io.StringIO()) as stderr:
                before = self.tree_state()
                expected = {'fix_emdash', 'docs-cache', 'response-validation'}
                self.assertEqual(config.synchronize(str(self.project), strict=True, persist=False), expected)
                code, output, error = self.settings_command('--json')
                self.assertEqual(code, 0, error)
                rows = {row['name']: row for group in json.loads(output)['groups'] for row in group['settings']}
                self.assertTrue(rows['hook:no_broad_process_kill']['effective'])
                self.assertFalse(rows['hook:fix_emdash']['effective'])
                self.assertEqual(self.tree_state(), before)
                self.assertEqual(config.feature_settings(self.data).disabled, expected)
                self.assertIn(str(unrelated), stderr.getvalue())
                self.assertIn(str(failure), stderr.getvalue())
                self.assertNotIn('features paused', stderr.getvalue())

    def test_current_project_resolution_failure_is_not_ignored(self):
        resolve = Path.resolve

        def fail_current(target, *args, **kwargs):
            if target == self.project:
                raise RuntimeError('Current project unavailable')
            return resolve(target, *args, **kwargs)

        with mock.patch.object(Path, 'resolve', autospec=True, side_effect=fail_current), \
                mock.patch.object(sys, 'stderr', io.StringIO()) as stderr:
            self.assertEqual(config.synchronize(str(self.project), persist=False), set(config.defaults()))
            self.assertIn('features paused', stderr.getvalue())
            with self.assertRaisesRegex(RuntimeError, 'Current project unavailable'):
                config.synchronize(str(self.project), strict=True, persist=False)

    def test_legacy_settings_migrate_and_retired_claim_settings_disappear(self):
        future = {'future-camel-disabled': False, 'future-camel-enabled': True,
                  'future-snake-disabled': False, 'future-snake-enabled': True}
        newer = {**config.defaults(), **dict.fromkeys(future, True)}
        for host, (path, project_path) in config.paths(self.project).items():
            with self.subTest(host=host):
                self.write(path, {
                    'disabledRules': ['no_broad_process_kill', 'claim-evidence', 'graphify', 'future-camel-disabled'],
                    'enabledRules': ['verify-state-before-claiming', 'future-camel-enabled'],
                    'disabled_rules': ['future-snake-disabled'], 'enabled_rules': ['future-snake-enabled'],
                })
                self.write(project_path, {
                    'enabledRules': ['no_broad_process_kill', 'claim-evidence', 'graphify', 'future-camel-enabled'],
                    'disabledRules': ['future-camel-disabled'],
                    'disabled_rules': ['future-snake-disabled'], 'enabled_rules': ['future-snake-enabled'],
                })
                config.synchronize(str(self.project), host)
                stored = json.loads(path.read_text())
                self.assertEqual(set(stored['features']), set(config.defaults()) | set(future))
                self.assertEqual({name: stored['features'][name] for name in future}, future)
                self.assertFalse(stored['features']['no_broad_process_kill'])
                self.assertEqual(json.loads(project_path.read_text()), {
                    'features': {'no_broad_process_kill': True, **future},
                })
                self.assertNotIn('disabledRules', stored)
                self.assertNotIn('claim-evidence', path.read_text())
                self.assertNotIn('graphify', path.read_text())
                self.assertNotIn('verify-state-before-claiming', path.read_text())
                disabled = config.synchronize(str(self.project), host, catalog=newer)
                for name, enabled in future.items():
                    self.assertEqual(name in disabled, not enabled)

    def test_codex_migrates_once_without_rewriting_host_settings(self):
        global_path, _ = config.paths(self.project)['codex']
        toml = global_path.with_name('config.toml')
        toml.parent.mkdir(parents=True)
        original = (
            'model = "configured-model"\n[ioncache-ai-tools]\n'
            'disabled_rules = ["no_broad_process_kill", "claim-evidence", "future-global-disabled"]\n'
            'enabled_rules = ["future-global-enabled"]\n'
            f'[projects.{json.dumps(str(self.project))}.ioncache-ai-tools]\n'
            'enabled_rules = ["no_broad_process_kill", "future-project-enabled"]\n'
            'disabled_rules = ["future-project-disabled"]\n'
        )
        toml.write_text(original)
        self.assertNotIn('no_broad_process_kill', config.synchronize(str(self.project), 'codex'))
        self.assertEqual(toml.read_bytes(), original.encode())
        stored = json.loads(global_path.read_text())
        self.assertFalse(stored['features']['no_broad_process_kill'])
        self.assertIs(stored['features'].get('future-global-disabled'), False)
        self.assertIs(stored['features'].get('future-global-enabled'), True)
        embedded = stored['projects'][str(self.project)]['features']
        self.assertIs(embedded.get('future-project-disabled'), False)
        self.assertIs(embedded.get('future-project-enabled'), True)
        self.assertNotIn('claim-evidence', global_path.read_text())
        future = {'future-global-disabled': False, 'future-global-enabled': True,
                  'future-project-disabled': False, 'future-project-enabled': True}
        newer = {**config.defaults(), **dict.fromkeys(future, True)}
        disabled = config.synchronize(str(self.project), 'codex', catalog=newer)
        for name, enabled in future.items():
            self.assertEqual(name in disabled, not enabled)
        self.assertEqual(toml.read_bytes(), original.encode())
        stored['features']['no_broad_process_kill'] = True
        self.write(global_path, stored)
        self.assertNotIn('no_broad_process_kill', config.synchronize(str(self.root), 'codex'))

    def test_project_overrides_inherit_defaults_and_cross_host_disables(self):
        paths = config.paths(self.project)
        self.write(paths['copilot'][0], {'features': {'fix_emdash': False}})
        self.write(paths['copilot'][1], {'features': {'fix_emdash': True, 'graphify': False}})
        self.assertNotIn('fix_emdash', config.synchronize(str(self.project), 'copilot'))
        self.assertEqual(json.loads(paths['copilot'][1].read_text()), {'features': {'fix_emdash': True}})
        self.write(paths['claude'][1], {'features': {'fix_emdash': False}})
        self.assertIn('fix_emdash', config.synchronize(str(self.project), 'copilot'))
        self.assertEqual(set(json.loads(paths['copilot'][0].read_text())['features']), set(config.defaults()))

    def test_invalid_configuration_is_not_replaced_or_silently_enabled(self):
        path = self.root / 'invalid.json'
        for text in ('{bad', '[]', '{"features":{"fix_emdash":"false"}}',
                     '{"features":{"future-feature":"false"}}'):
            path.write_text(text)
            with self.subTest(text=text), self.assertRaises(ValueError):
                config.sync_file(path, config.defaults())
            self.assertEqual(path.read_text(), text)

    @pytest.mark.process
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
                self.assertEqual(config.synchronize(str(self.project), 'claude'), {'fix_emdash', 'response-validation'})
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

    @pytest.mark.process
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
        data = {**self.data, 'tool_name': 'Write', 'tool_input': {'file_path': 'target.py', 'content': 'fix'}}
        self.assertIn('Question turn:', str(guidance.run_hook('UserPromptSubmit', prompt)))
        self.assertEqual(block_pending_question.run_hook(data)['hookSpecificOutput']['permissionDecision'], 'deny')
        self.write(path, {'features': {'answer-questions': False}})
        self.assertIsNone(block_pending_question.run_hook(data), 'opting out must release a pending question')
        self.assertNotIn('Question turn:', str(guidance.run_hook('UserPromptSubmit', prompt)))
        self.assertFalse(marker_path(self.data).exists())
        self.write(path, {'features': {'answer-questions': True}})
        self.assertIn('Question turn:', str(guidance.run_hook('UserPromptSubmit', prompt)))
        self.assertEqual(block_pending_question.run_hook(data)['hookSpecificOutput']['permissionDecision'], 'deny')
        guidance.run_hook('UserPromptSubmit', {**self.data, 'prompt': 'Apply the fix'})
        self.assertIsNone(block_pending_question.run_hook(data))

    def test_all_features_off_prevents_policy_and_tool_denials(self):
        global_path = config.paths(self.project)['claude'][0]
        self.write(global_path, {'features': {name: False for name in config.defaults()}})
        output = run_shared_hooks('UserPromptSubmit', {**self.data, 'prompt': 'Why?'})
        self.assertIn('Disabled plugin skills:', str(output))
        self.assertNotIn('Question turn:', str(output))
        self.assertFalse(marker_path(self.data).exists())
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
        for skill in ('review-code', 'autonomous-development', 'plugin-settings'):
            self.write(path, {'features': {'skill:' + skill: False}})
            output = guidance.run_hook('UserPromptSubmit', {**self.data, 'prompt': 'Review the code'})
            self.assertIn('Disabled plugin skills: ' + skill, str(output))
            for name in (skill, 'ioncache-ai-tools:' + skill):
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

    def test_review_model_opt_out_preserves_skill_and_other_guards(self):
        path = config.paths(self.project)['claude'][0]
        self.write(path, {'features': {'review-auto-model-selection': False}})
        for event in ('SessionStart', 'SubagentStart', 'UserPromptSubmit'):
            output = guidance.run_hook(event, {**self.data, 'prompt': 'Review this branch'})
            self.assertIn('Automatic review model selection is disabled', str(output))
            self.assertIn('explicit user model choices', str(output))
        self.assertIsNone(guidance.run_hook('PreToolUse', {
            **self.data, 'tool_name': 'Skill', 'tool_input': {'skill': 'review-code'},
        }))
        self.assertIn('deny', str(run_shared_hooks('PreToolUse', {
            **self.data, 'tool_name': 'Bash', 'tool_input': {'command': 'pkill worker'},
        })))
        self.assertEqual(run_shared_hooks('PreToolUse', {
            **self.data, 'tool_name': 'Bash', 'tool_input': {'command': 'git status --short'},
        }), [])
        self.write(path, {'features': {'review-auto-model-selection': True}})
        self.assertNotIn('Automatic review model selection is disabled', str(
            guidance.run_hook('UserPromptSubmit', {**self.data, 'prompt': 'Review this branch'})
        ))

    def test_read_only_resolution_preserves_legacy_files_and_matches_sync(self):
        paths = config.paths(self.project)
        legacy = paths['codex'][0].with_name('config.toml')
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text('[ioncache-ai-tools]\ndisabled_rules = ["review-auto-model-selection"]\n')
        self.write(paths['claude'][0], {'features': {'fix_emdash': False}})
        self.write(paths['claude'][1], {'features': {'fix_emdash': True}})
        before = {path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        with mock.patch.object(config, 'write_atomic', side_effect=AssertionError('unexpected write')):
            disabled = config.synchronize(str(self.project), 'copilot', strict=True, persist=False)
        self.assertEqual(disabled, {'review-auto-model-selection', 'response-validation'})
        self.assertEqual({path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()}, before)
        self.assertEqual(config.synchronize(str(self.project), 'copilot', strict=True), disabled)

    def test_unknown_origin_keeps_user_question_guidance_without_marking_the_turn(self):
        for event in ('SessionStart', 'UserPromptSubmit'):
            with self.subTest(event=event):
                data = {**self.data, '_ioncache_prompt_origin': 'unknown',
                        'prompt': 'Why have the workers not stopped?'}
                output = str(guidance.run_hook(event, data))
                self.assertIn('A user question asks for information, not action', output)
                self.assertIn('even for an existing assignment', output)
                self.assertIn('A question about stopping workers is not permission to stop them', output)
                self.assertIn('reports, notifications, or parent-written messages', output)
                self.assertNotIn('Question turn:', output)
                self.assertFalse(marker_path(data).exists())
                self.assertEqual(run_shared_hooks('PreToolUse', {
                    **data, 'tool_name': 'stop_agent', 'tool_input': {'agent_id': 'worker'},
                }), [])

    def planning_lookup(self, plugin=ROOT, project=None):
        """Runs the documented incremental-planning lookup exactly as Prepare does."""
        skill = (ROOT / 'skills/autonomous-development/SKILL.md').read_text()
        blocks = [block for block in skill.split('```sh\n')[1:]
                  if 'autonomous-development-incremental-planning' in block.split('```', 1)[0]]
        self.assertEqual(len(blocks), 1)
        command = blocks[0].split('```', 1)[0]
        command = command.replace('/absolute/plugin', str(plugin))
        command = command.replace('/absolute/project', str(project or self.project))
        return subprocess.run(['/bin/sh', '-c', command], cwd=self.root, text=True, capture_output=True)

    def test_incremental_planning_lookup_matches_embedded_project_through_a_symlink(self):
        name = 'autonomous-development-incremental-planning'
        link = self.root / 'project-link'
        link.symlink_to(self.project, target_is_directory=True)
        global_path = config.paths(self.project)['claude'][0]
        # Embedded overrides are keyed by the resolved root, so the lookup must normalize its argument.
        self.write(global_path, {'features': {}, 'projects': {str(self.project): {'features': {name: False}}}})
        result = self.planning_lookup(project=link)
        self.assertEqual((result.returncode, result.stdout), (0, 'false\n'), result.stderr)
        self.write(global_path, {'features': {}, 'projects': {str(self.project): {'features': {name: True}}}})
        self.assertEqual(self.planning_lookup(project=link).stdout, 'true\n')

    def test_incremental_planning_lookup_quotes_spaced_paths_and_ignores_cwd_modules(self):
        name = 'autonomous-development-incremental-planning'
        plugin = self.root / 'plugin with spaces'
        plugin.symlink_to(ROOT, target_is_directory=True)
        project = self.root / 'project with spaces'
        project.mkdir()
        # An unquoted project argument would read the unconfigured sibling `project` and print true.
        self.write(config.paths(project)['claude'][1], {'features': {name: False}})
        result = self.planning_lookup(plugin, project)
        self.assertEqual((result.returncode, result.stdout), (0, 'false\n'), result.stderr)
        config.paths(project)['claude'][1].unlink()
        result = self.planning_lookup(plugin, project)
        self.assertEqual((result.returncode, result.stdout), (0, 'true\n'), result.stderr)
        # A consuming project's stdlib-named module in the working directory never runs.
        (self.root / 'tomllib.py').write_text('raise SystemExit("planted module executed")\n')
        result = self.planning_lookup(plugin, project)
        self.assertEqual((result.returncode, result.stdout), (0, 'true\n'), result.stderr)

    def test_incremental_planning_lookup_is_false_when_the_catalog_lacks_the_setting(self):
        name = 'autonomous-development-incremental-planning'
        plugin = self.root / 'older-plugin'
        (plugin / 'hooks/scripts').mkdir(parents=True)
        # plugin_config locates its catalog from its own resolved path, so a symlink would read the real one.
        (plugin / 'hooks/scripts/plugin_config.py').write_bytes(Path(config.__file__).read_bytes())
        catalog = {key: True for key in config.defaults() if key != name}
        self.write(plugin / 'config/defaults.json', {'features': catalog})
        result = self.planning_lookup(plugin)
        self.assertEqual((result.returncode, result.stdout), (0, 'false\n'), result.stderr)

    def test_incremental_planning_lookup_is_effective_read_only_and_independent(self):
        name = 'autonomous-development-incremental-planning'
        paths = config.paths(self.project)
        self.assertIs(config.defaults()[name], True)
        result = self.planning_lookup()
        self.assertEqual((result.returncode, result.stdout), (0, 'true\n'), result.stderr)
        self.assertFalse(any(path.is_file() for path in self.root.rglob('*')))

        # Unrelated autonomous-development and skill controls do not disable the guide.
        self.write(paths['claude'][0], {'features': {'autonomous-development-audit': False,
                                                      'autonomous-development-model-selection': False,
                                                      'skill:engineering-judgment': False}})
        self.assertEqual(self.planning_lookup().stdout, 'true\n')

        # A sparse project opt-out applies, and the global file keeps its retained values.
        self.write(paths['copilot'][1], {'features': {name: False}})
        before = {path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        self.assertEqual(self.planning_lookup().stdout, 'false\n')
        self.assertEqual({path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()}, before)

        # The opt-out leaves the skill, execution and other safeguards enabled.
        disabled = config.synchronize(str(self.project), 'claude', strict=True, persist=False)
        for feature in ('autonomous-development', 'skill:autonomous-development',
                        'autonomous-development-explicit-only', 'autonomous-development-progress'):
            self.assertNotIn(feature, disabled)
        self.assertIn('deny', str(run_shared_hooks('PreToolUse', {
            **self.data, 'tool_name': 'Bash', 'tool_input': {'command': 'pkill worker'},
        })))
        self.assertIsNone(guidance.run_hook('PreToolUse', {
            **self.data, 'tool_name': 'Skill', 'tool_input': {'skill': 'review-code'},
        }))

        # A global disable on one host applies even where another host's project re-enables it.
        paths['copilot'][1].unlink()
        self.write(paths['codex'][0], {'features': {name: False}})
        self.write(paths['claude'][1], {'features': {name: True}})
        self.assertEqual(self.planning_lookup().stdout, 'false\n')
        # Within one host, a project setting overrides its global value.
        self.write(paths['codex'][1], {'features': {name: True}})
        self.assertEqual(self.planning_lookup().stdout, 'true\n')

        # Legacy Codex TOML is honored without migrating or rewriting it.
        for path in (paths['codex'][0], paths['codex'][1], paths['claude'][1]):
            path.unlink()
        legacy = paths['codex'][0].with_name('config.toml')
        legacy.write_text(f'[ioncache-ai-tools]\ndisabled_rules = ["{name}"]\n')
        before = {path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        self.assertEqual(self.planning_lookup().stdout, 'false\n')
        self.assertEqual({path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()}, before)
        legacy.unlink()

        # Unreadable settings report unavailability, never an enabled result, and stay untouched.
        paths['claude'][0].write_text('{bad')
        result = self.planning_lookup()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertEqual(paths['claude'][0].read_text(), '{bad')
        # Repairing the settings restores the effective value without other recovery.
        self.write(paths['claude'][0], {'features': {}})
        self.assertEqual(self.planning_lookup().stdout, 'true\n')

    def test_question_marker_applies_only_to_the_questioned_identity(self):
        root = {**self.data, 'tool_name': 'Write', 'tool_input': {'file_path': 'target.py', 'content': 'requested'}}
        child = {**root, 'agent_id': 'worker'}
        self.addCleanup(lambda: marker_path(child).unlink(missing_ok=True))
        # A child prompt is parent-written, so it records no question state.
        output = str(guidance.run_hook('UserPromptSubmit', {**self.data, 'agent_id': 'worker', 'prompt': 'Why?'}))
        self.assertFalse(marker_path(child).exists())
        self.assertIn(guidance.CHILD_QUESTION_GUIDANCE, output)
        self.assertIn(guidance.CHILD_BOOTSTRAP, output)
        self.assertNotIn('Question turn:', output)
        self.assertNotIn(guidance.BOOTSTRAP['answer-questions'], output)
        output = str(guidance.run_hook('SubagentStart', {**self.data, 'agent_id': 'worker'}))
        self.assertIn(guidance.CHILD_BOOTSTRAP, output)
        self.assertNotIn(guidance.BOOTSTRAP['answer-questions'], output)
        self.assertIn(guidance.BOOTSTRAP['answer-questions'],
                      str(guidance.run_hook('SessionStart', self.data)))
        guidance.run_hook('UserPromptSubmit', {**self.data, 'prompt': 'Why did the worker change that?'})
        self.assertTrue(marker_path(root).exists())
        self.assertEqual(run_shared_hooks('PreToolUse', root)[0]['hookSpecificOutput']['permissionDecision'], 'deny')
        for tool, args in (('Agent', {'prompt': 'Apply the change'}), ('SendMessage', {'to': 'worker'}),
                           ('Workflow', {'script': 'x'}), ('TaskCreate', {'subject': 'Apply it'}),
                           ('TaskStop', {'task_id': 'worker'})):
            with self.subTest(tool=tool):
                output = run_shared_hooks('PreToolUse', {**self.data, 'tool_name': tool, 'tool_input': args})
                self.assertEqual(output[0]['hookSpecificOutput']['permissionDecision'], 'deny')
        for tool, args in (('Read', {'file_path': 'target.py'}), ('Bash', {'command': 'git log -1'})):
            self.assertEqual(run_shared_hooks('PreToolUse', {**self.data, 'tool_name': tool, 'tool_input': args}), [])
        self.assertEqual(run_shared_hooks('PreToolUse', child), [])
        self.assertEqual(run_shared_hooks('PreToolUse', {**child, 'tool_name': 'Agent', 'tool_input': {}}), [])
        denial = run_shared_hooks('PreToolUse', {
            **child, 'tool_name': 'Bash', 'tool_input': {'command': 'pkill worker'},
        })
        self.assertEqual(denial[0]['hookSpecificOutput']['permissionDecision'], 'deny')

    def test_host_started_turns_do_not_create_or_keep_question_state(self):
        notices = (
            '<task-notification>\n<summary>Where did the worker stop?</summary>\n</task-notification>',
            # Observed Claude Code framing for subagent hand-backs and other sessions' messages.
            'Another Claude session sent a message:\n<agent-message from="a85e39ab5b874ee52">\n'
            '[Subagent hand-back] The report follows:\n  Is claim 7 true? Which version added it?\n'
            '</agent-message>',
        )
        write = {**self.data, 'tool_name': 'Write', 'tool_input': {'file_path': 'x', 'content': 'next step'}}
        delegate = {**self.data, 'tool_name': 'Agent', 'tool_input': {'prompt': 'Run the next worker'}}
        for notice in notices:
            with self.subTest(notice=notice.split('\n')[0]):
                output = guidance.run_hook('UserPromptSubmit', {
                    **self.data, '_ioncache_prompt_origin': 'unknown', 'prompt': notice,
                })
                self.assertNotIn('Question turn:', str(output))
                self.assertFalse(marker_path(self.data).exists())
                self.assertEqual(run_shared_hooks('PreToolUse', write), [])
                self.assertEqual(run_shared_hooks('PreToolUse', delegate), [])
                guidance.run_hook('UserPromptSubmit', {**self.data, 'prompt': 'Why did it fail?'})
                denied = run_shared_hooks('PreToolUse', delegate)
                self.assertEqual(denied[0]['hookSpecificOutput']['permissionDecision'], 'deny')
                # The host-started turn ends the question turn, so orchestration can resume.
                guidance.run_hook('UserPromptSubmit', {
                    **self.data, '_ioncache_prompt_origin': 'unknown', 'prompt': notice,
                })
                self.assertFalse(marker_path(self.data).exists())
                self.assertEqual(run_shared_hooks('PreToolUse', delegate), [])

    def test_question_state_failures_report_unavailability_without_denial(self):
        data = {**self.data, 'tool_name': 'Write', 'tool_input': {'file_path': 'x', 'content': 'y'}}
        with mock.patch.object(guidance, 'set_marker', side_effect=OSError('marker unavailable')), \
                mock.patch.object(sys, 'stderr', io.StringIO()):
            output = guidance.run_hook('UserPromptSubmit', {**self.data, 'prompt': 'Why?'})
        self.assertIn('question-state checks unavailable', output['systemMessage'])
        self.assertIn('Question turn:', output['hookSpecificOutput']['additionalContext'])
        self.assertIsNone(block_pending_question.run_hook(data))
        marker = marker_path(self.data)
        marker.symlink_to(self.project / 'foreign-marker')
        with mock.patch.object(sys, 'stderr', io.StringIO()):
            output = block_pending_question.run_hook(data)
        self.assertIn('pending-question checks unavailable', output['systemMessage'])
        self.assertNotIn('permissionDecision', str(output))
        marker.unlink()
        marker.write_text('')
        with mock.patch('classify_question.os.getuid', return_value=os.getuid() + 1), \
                mock.patch.object(sys, 'stderr', io.StringIO()):
            output = block_pending_question.run_hook(data)
        self.assertIn('pending-question checks unavailable', output['systemMessage'])
        self.assertNotIn('permissionDecision', str(output))
        marker.unlink()
        with mock.patch.object(block_pending_question, 'has_marker', side_effect=OSError('unreadable')), \
                mock.patch.object(sys, 'stderr', io.StringIO()):
            self.assertNotIn('permissionDecision', str(block_pending_question.run_hook(data)))

    def test_corrupt_config_allows_repair_then_restores_opt_out(self):
        path = config.paths(self.project)['claude'][0]
        path.parent.mkdir(parents=True)
        path.write_text('{bad')
        with mock.patch.object(sys, 'stderr'):
            self.assertEqual(config.synchronize(str(self.project), 'claude'), set(config.defaults()))
        self.assertEqual(path.read_text(), '{bad')
        self.write(path, {'features': {'fix_emdash': False}})
        self.assertEqual(config.synchronize(str(self.project), 'claude'), {'fix_emdash', 'response-validation'})

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
            '  if name in {"scope_guard","task_authorization","turn_guard","turn_review","scope_review","copilot_history","claim_evidence","evidence_review","evidence_source","block_emdash_turn"}:\n'
            '   raise AssertionError("Retired module loaded: "+name)\n'
            'sys.meta_path.insert(0,NoClaims())\n'
            'import block_pending_question,copilot_adapter,codex_adapter,guidance,docs_cache\n'
            'from hook_adapter_common import run_shared_hooks\n'
            'data=json.loads(sys.argv[1])\n'
            'guidance.run_hook("SessionStart",data)\n'
            'guidance.run_hook("UserPromptSubmit",{**data,"prompt":"Implement the change"})\n'
            'guidance.run_hook("PreToolUse",{**data,"tool_name":"Write","tool_input":{"file_path":"x","content":"claim"}})\n'
            'block_pending_question.run_hook({**data,"tool_name":"Write","tool_input":{"file_path":"x","content":"claim"}})\n'
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
