"""Exercise the response mod's configuration protocol without a native model."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import plugin_config as config


class ResponseValidationSettingsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / 'project'
        self.project.mkdir()
        patcher = mock.patch.dict(os.environ, {
            'HOME': str(self.root / 'home'), 'CODEX_HOME': str(self.root / 'codex'),
            'COPILOT_HOME': str(self.root / 'copilot'),
        })
        patcher.start()
        self.addCleanup(patcher.stop)

    def invoke(self, feature='response-validation'):
        args = ['plugin_config.py', 'claude', '--project', str(self.project)]
        if feature is not None:
            args.extend(['--feature', feature])
        with mock.patch.object(sys, 'argv', args), mock.patch.object(sys, 'stdout', io.StringIO()) as stdout:
            config.main()
        return stdout.getvalue().strip()

    def test_default_off_and_cross_host_opt_in_changes_are_read_on_the_next_invocation(self):
        self.assertEqual(json.loads(self.invoke()), {'enabled': False})
        for _, path in config.paths(self.project).values():
            path.parent.mkdir(parents=True)
            path.write_text('{"features":{"response-validation":true}}')
        self.assertEqual(json.loads(self.invoke()), {'enabled': True})
        path = config.paths(self.project)['copilot'][1]
        path.write_text('{"features":{"response-validation":false}}')
        self.assertEqual(json.loads(self.invoke()), {'enabled': False})
        path.write_text('{"features":{"response-validation":true}}')
        self.assertEqual(json.loads(self.invoke()), {'enabled': True})
        self.assertEqual(json.loads(self.invoke('no_broad_process_kill')), {'enabled': True})

    def test_synchronization_adds_the_off_default_without_resetting_saved_opt_ins(self):
        self.invoke(None)
        path = config.paths(self.project)['claude'][0]
        self.assertFalse(json.loads(path.read_text())['features']['response-validation'])
        self.assertEqual(json.loads(self.invoke()), {'enabled': False})
        for host, (global_path, _) in config.paths(self.project).items():
            global_path.parent.mkdir(parents=True, exist_ok=True)
            global_path.write_text('{"features":{"response-validation":true}}')
            config.synchronize(str(self.project), host)
            self.assertTrue(json.loads(global_path.read_text())['features']['response-validation'])
        self.assertEqual(json.loads(self.invoke()), {'enabled': True})

    def test_bad_settings_fail_feature_queries_without_rewriting_them(self):
        for host, paths in config.paths(self.project).items():
            for path in paths:
                with self.subTest(host=host, path=path):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('{broken')
                    with (
                        mock.patch.object(sys, 'stderr', io.StringIO()) as stderr,
                        mock.patch.object(config, 'write_atomic') as writer,
                    ):
                        with self.assertRaises(SystemExit) as error:
                            self.invoke()
                        self.assertEqual(error.exception.code, 1)
                        self.assertIn('synchronization failed', stderr.getvalue())
                        writer.assert_not_called()
                    self.assertEqual(path.read_text(), '{broken')
                    with mock.patch.object(sys, 'stderr', io.StringIO()), self.assertRaises(SystemExit) as error:
                        self.invoke(None)
                    self.assertEqual(error.exception.code, 1)
                    self.assertEqual(path.read_text(), '{broken')
                    path.unlink()

    def test_unreadable_settings_fail_queries_and_repair_restores_an_explicit_opt_out(self):
        paths = config.paths(self.project)
        for host in ('claude', 'copilot'):
            path = paths[host][0]
            path.parent.mkdir(parents=True)
            path.write_text('{"features":{"response-validation":false}}')
        unreadable = paths['copilot'][0]
        read_settings = config.read_settings

        def read(path, *args, **kwargs):
            if path == unreadable:
                raise PermissionError('unreadable settings')
            return read_settings(path, *args, **kwargs)

        with (
            mock.patch.object(config, 'read_settings', side_effect=read),
            mock.patch.object(sys, 'stderr', io.StringIO()) as stderr,
        ):
            with self.assertRaises(SystemExit) as error:
                self.invoke()
            self.assertEqual(error.exception.code, 1)
            self.assertIn('unreadable settings', stderr.getvalue())
            with self.assertRaises(SystemExit) as error:
                self.invoke(None)
            self.assertEqual(error.exception.code, 1)
        self.assertEqual(json.loads(self.invoke()), {'enabled': False})

    def test_feature_query_keeps_opt_out_when_reconciliation_cannot_write(self):
        path = config.paths(self.project)['claude'][0]
        path.parent.mkdir(parents=True)
        path.write_text('{"features":{"response-validation":false}}')
        original, _, reconciled = config.read_settings(path, config.defaults(), True, None)
        self.assertNotEqual(original, reconciled)
        with (
            mock.patch.object(config, 'write_atomic', side_effect=PermissionError('read-only')) as writer,
            mock.patch.object(sys, 'stderr', io.StringIO()),
        ):
            self.assertEqual(json.loads(self.invoke()), {'enabled': False})
            writer.assert_not_called()
            with self.assertRaises(SystemExit) as error:
                self.invoke(None)
            self.assertEqual(error.exception.code, 1)
        self.assertEqual(path.read_text(), original)

    def test_existing_sync_output_is_preserved_and_unknown_features_fail(self):
        self.assertEqual(self.invoke(None), str(config.paths(self.project)['claude'][0]))
        with mock.patch.object(sys, 'stderr', io.StringIO()), self.assertRaises(SystemExit) as error:
            self.invoke('not-a-shipped-feature')
        self.assertEqual(error.exception.code, 1)


if __name__ == '__main__':
    unittest.main()
