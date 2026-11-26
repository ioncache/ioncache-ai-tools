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

    def test_opt_out_changes_are_read_on_the_next_invocation(self):
        self.assertEqual(json.loads(self.invoke()), {'enabled': True})
        path = config.paths(self.project)['copilot'][1]
        path.parent.mkdir(parents=True)
        path.write_text('{"features":{"response-validation":false}}')
        self.assertEqual(json.loads(self.invoke()), {'enabled': False})
        path.write_text('{"features":{"response-validation":true}}')
        self.assertEqual(json.loads(self.invoke()), {'enabled': True})
        self.assertEqual(json.loads(self.invoke('no_broad_process_kill')), {'enabled': True})

    def test_bad_settings_fail_without_rewriting_them(self):
        path = config.paths(self.project)['claude'][1]
        path.parent.mkdir(parents=True)
        path.write_text('{broken')
        with mock.patch.object(sys, 'stderr', io.StringIO()), self.assertRaises(SystemExit) as error:
            self.invoke()
        self.assertEqual(error.exception.code, 1)
        self.assertEqual(path.read_text(), '{broken')

    def test_existing_sync_output_is_preserved_and_unknown_features_fail(self):
        self.assertEqual(self.invoke(None), str(config.paths(self.project)['claude'][0]))
        with mock.patch.object(sys, 'stderr', io.StringIO()), self.assertRaises(SystemExit) as error:
            self.invoke('not-a-shipped-feature')
        self.assertEqual(error.exception.code, 1)


if __name__ == '__main__':
    unittest.main()
