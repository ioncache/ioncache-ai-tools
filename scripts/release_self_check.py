#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

HELPER = Path(__file__).with_name('release.js')
MANIFESTS = (
    '.claude-plugin/plugin.json',
    '.codex-plugin/plugin.json',
    '.github/plugin/plugin.json',
)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='release-check-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.env = {
            **os.environ, 'HOME': str(self.root), 'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_CONFIG_GLOBAL': os.devnull, 'PYTHONDONTWRITEBYTECODE': '1',
        }
        for key in list(self.env):
            if key.startswith(('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE')):
                self.env.pop(key)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Release fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.write_versions('0.9.0')
        self.commit('feat: initial fixture')
        self.write_versions('1.0.0')
        self.notes = (
            '# Changelog\n\nRelease notes.\n\n## 1.0.0 (2026-01-01)\n\n'
            '### New\n\n- Existing release.\n\n### Updated\n\n- None.\n\n### Fixed\n\n- None.\n'
        )
        (self.root / 'CHANGELOG.md').write_text(self.notes)
        self.commit('chore: release 1.0.0')

    def git(self, *args):
        return subprocess.run(
            ['git', *args], cwd=self.root, env=self.env, check=True,
            capture_output=True, text=True,
        ).stdout.strip()

    def commit(self, subject):
        self.git('add', '.')
        self.git('commit', '-qm', subject)
        return self.git('rev-parse', 'HEAD')

    def write_versions(self, version):
        for name in MANIFESTS:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({'name': 'fixture', 'version': version}, indent=2) + '\n')

    def change(self, subject):
        (self.root / 'feature.txt').write_text(subject)
        return self.commit(subject)

    def cli(self, *args):
        return subprocess.run(
            ['node', str(HELPER), *args], cwd=self.root,
            env=self.env, capture_output=True, text=True,
        )

    def release_files(self):
        return {
            name: (self.root / name).read_bytes()
            for name in (*MANIFESTS, 'CHANGELOG.md')
        }

    def test_release_uses_version_transition_not_later_manifest_edits(self):
        feature = self.change('feat(cli)!: add command')
        path = self.root / MANIFESTS[0]
        manifest = json.loads(path.read_text())
        manifest['description'] = 'Metadata changed without a release.'
        path.write_text(json.dumps(manifest))
        metadata = self.commit('docs: clarify plugin description')
        fix = self.change('fix(parser): handle empty input')
        legacy = self.change('Improve legacy documentation')
        head = self.git('rev-parse', 'HEAD')

        result = self.cli('1.1.0')
        self.assertEqual(result.returncode, 0, result.stderr)
        text = (self.root / 'CHANGELOG.md').read_text()
        current = text.split('## 1.0.0')[0]
        new = current.split('### New\n')[1].split('### Updated\n')[0]
        updated = current.split('### Updated\n')[1].split('### Fixed\n')[0]
        fixed = current.split('### Fixed\n')[1]
        self.assertIn(f'**cli:** add command ([{feature[:7]}]', new)
        self.assertIn(f'clarify plugin description ([{metadata[:7]}]', updated)
        self.assertIn(f'Improve legacy documentation ([{legacy[:7]}]', updated)
        self.assertIn(f'**parser:** handle empty input ([{fix[:7]}]', fixed)
        self.assertIn('### BREAKING CHANGES\n', current)
        self.assertIn(f'https://github.com/ioncache/ioncache-ai-tools/commit/{feature}', new)
        self.assertNotIn('initial fixture', current)
        self.assertNotIn('release 1.0.0', current)
        self.assertTrue(text.endswith(self.notes.split('## 1.0.0')[1]))
        for name in MANIFESTS:
            self.assertEqual(json.loads((self.root / name).read_text())['version'], '1.1.0')
        self.assertEqual(json.loads(path.read_text())['description'], manifest['description'])
        self.assertEqual(self.git('rev-parse', 'HEAD'), head)
        self.assertEqual(self.git('tag'), '')
        self.assertEqual(self.git('diff', '--cached', '--name-only'), '')
        self.assertEqual(self.cli('--check').returncode, 0)

    def test_next_release_does_not_repeat_previously_released_commits(self):
        self.change('feat: first feature')
        self.assertEqual(self.cli('1.1.0').returncode, 0)
        self.commit('chore: release 1.1.0')
        prior = (self.root / 'CHANGELOG.md').read_text()
        self.change('fix: second release fix')

        result = self.cli('1.1.1')
        self.assertEqual(result.returncode, 0, result.stderr)
        text = (self.root / 'CHANGELOG.md').read_text()
        current = text.split('## 1.1.0')[0]
        self.assertNotIn('first feature', current)
        self.assertNotIn('release 1.1.0', current)
        self.assertRegex(current, r'### New\n\n[*-] None\.')
        self.assertRegex(current, r'### Updated\n\n[*-] None\.')
        self.assertIn('second release fix', current)
        self.assertTrue(text.endswith(prior.split('## 1.1.0')[1]))

    def test_check_rejects_missing_notes_or_sections_without_writing(self):
        self.assertEqual(self.cli('--check').returncode, 0)
        self.write_versions('1.1.0')
        before = self.release_files()
        result = self.cli('--check')
        self.assertEqual(result.returncode, 2)
        self.assertIn('release entry for 1.1.0', result.stderr)
        self.assertEqual(self.release_files(), before)
        (self.root / 'CHANGELOG.md').write_text(
            self.notes.replace('## 1.0.0', '## 1.1.0').replace('### Fixed\n\n- None.\n', ''),
        )
        self.assertIn('New, Updated and Fixed', self.cli('--check').stderr)

    def test_invalid_or_non_increasing_version_leaves_release_files_untouched(self):
        before = self.release_files()
        for version in ('1.0.0', '0.9.9', '1.1', '01.1.0', '1.1.0-rc.1', '1.1.0+build', 'v1.1.0'):
            with self.subTest(version=version):
                result = self.cli(version)
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertEqual(self.release_files(), before)

    def test_uncommitted_changes_cannot_silently_disappear_from_notes(self):
        before = self.release_files()
        (self.root / 'pending.txt').write_text('not yet in the Git log')
        result = self.cli('1.1.0')
        self.assertEqual(result.returncode, 2)
        self.assertIn('clean worktree', result.stderr)
        self.assertEqual(self.release_files(), before)
        self.assertEqual((self.root / 'pending.txt').read_text(), 'not yet in the Git log')

    def test_mismatched_manifests_fail_before_writing(self):
        path = self.root / MANIFESTS[1]
        manifest = json.loads(path.read_text())
        manifest['version'] = '1.0.1'
        path.write_text(json.dumps(manifest))
        before = self.release_files()
        result = self.cli('1.1.0')
        self.assertEqual(result.returncode, 2)
        self.assertIn('same version', result.stderr)
        self.assertEqual(self.release_files(), before)
        self.assertEqual(self.cli('--check').returncode, 2)

    def test_preset_keeps_hidden_types_custom_types_and_breaking_change_footers(self):
        for kind in ('docs', 'chore', 'refactor', 'test', 'build', 'ci', 'perf', 'style', 'custom'):
            self.change(f'{kind}: {kind} change')
        self.change('fix(api): revise response\n\nBREAKING CHANGE: clients must use the new response')
        self.git('tag', 'v9.0.0')

        result = self.cli('1.1.0')
        self.assertEqual(result.returncode, 0, result.stderr)
        current = (self.root / 'CHANGELOG.md').read_text().split('## 1.0.0')[0]
        updated = current.split('### Updated\n')[1].split('### Fixed\n')[0]
        for kind in ('docs', 'chore', 'refactor', 'test', 'build', 'ci', 'perf', 'style', 'custom'):
            self.assertIn(f'{kind} change', updated)
        self.assertIn('### BREAKING CHANGES\n\n* **api:** clients must use the new response', current)
        self.assertIn('## 1.1.0 (', current)
        self.assertNotIn('## 9.0.0', current)
        self.assertEqual(self.cli('--check').returncode, 0)

    def test_empty_release_still_has_all_categories(self):
        result = self.cli('1.1.0')
        self.assertEqual(result.returncode, 0, result.stderr)
        current = (self.root / 'CHANGELOG.md').read_text().split('## 1.0.0')[0]
        for category in ('New', 'Updated', 'Fixed'):
            self.assertRegex(current, rf'### {category}\n\n[*-] None\.')
        self.assertEqual(self.cli('--check').returncode, 0)

    def test_reverts_remain_visible_and_merge_messages_do_not_duplicate_changes(self):
        feature = self.change('feat: temporary feature')
        self.git('revert', '--no-edit', feature)
        self.git('checkout', '-qb', 'side')
        self.change('fix: merged fix')
        self.git('checkout', '-q', '-')
        self.git('merge', '--no-ff', '-qm', 'feat: duplicate merge summary', 'side')

        result = self.cli('1.1.0')
        self.assertEqual(result.returncode, 0, result.stderr)
        current = (self.root / 'CHANGELOG.md').read_text().split('## 1.0.0')[0]
        self.assertIn('temporary feature', current.split('### New\n')[1].split('### Updated\n')[0])
        self.assertIn('Revert', current.split('### Updated\n')[1].split('### Fixed\n')[0])
        self.assertIn('merged fix', current.split('### Fixed\n')[1])
        self.assertNotIn('duplicate merge summary', current)

    def test_shallow_checkout_can_check_notes_but_cannot_generate_an_incomplete_release(self):
        self.change('feat: a change after the release boundary')
        clone = tempfile.TemporaryDirectory(prefix='release-shallow-check-')
        self.addCleanup(clone.cleanup)
        destination = Path(clone.name) / 'checkout'
        self.git('clone', '-q', '--depth', '1', self.root.as_uri(), str(destination))
        self.root = destination
        before = self.release_files()

        self.assertEqual(self.cli('--check').returncode, 0)
        result = self.cli('1.1.0')
        self.assertEqual(result.returncode, 2)
        self.assertIn('full Git history', result.stderr)
        self.assertEqual(self.release_files(), before)


if __name__ == '__main__':
    unittest.main()
