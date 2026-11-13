"""Reconcile plugin-owned settings with the shipped feature catalog."""
import argparse
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import tomllib

DEFAULTS = Path(__file__).resolve().parents[2] / 'config/defaults.json'
FILENAME = 'ioncache-ai-tools.local.json'
HOSTS = ('claude', 'copilot', 'codex')
LOCK_WAIT_SECONDS = 0.25


@dataclass(frozen=True)
class FeatureSettings:
    catalog: frozenset[str]
    disabled: frozenset[str]


def defaults():
    values = json.loads(DEFAULTS.read_text(encoding='utf-8'))['features']
    if not isinstance(values, dict) or not values or any(value is not True for value in values.values()):
        raise ValueError('shipped feature defaults must all be true')
    return values


def paths(project):
    home = Path.home()
    return {
        'claude': (home / '.claude' / FILENAME, Path(project) / '.claude' / FILENAME),
        'copilot': (
            Path(os.environ.get('COPILOT_HOME') or home / '.copilot') / FILENAME,
            Path(project) / '.github/copilot' / FILENAME,
        ),
        'codex': (
            Path(os.environ.get('CODEX_HOME') or home / '.codex') / FILENAME,
            Path(project) / '.codex' / FILENAME,
        ),
    }


def settings(document, catalog):
    if not isinstance(document, dict):
        raise ValueError('plugin configuration must be an object')
    values = {}
    for key, enabled in (('disabledRules', False), ('enabledRules', True),
                         ('disabled_rules', False), ('enabled_rules', True)):
        names = document.get(key, [])
        if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
            raise ValueError(f'{key} must be a list of setting IDs')
        values.update({name: enabled for name in names if name in catalog})
    features = document.get('features', {})
    if not isinstance(features, dict):
        raise ValueError('features must be an object')
    for name, value in features.items():
        if name in catalog:
            if type(value) is not bool:
                raise ValueError(f'feature {name!r} must be true or false')
            values[name] = value
    return values


def reconcile(document, catalog, complete=True):
    values = {**(catalog if complete else {}), **settings(document, catalog)}
    result = {'features': values}
    projects = document.get('projects', {})
    if not isinstance(projects, dict):
        raise ValueError('projects must be an object')
    if projects:
        result['projects'] = {
            root: {'features': settings(overrides, catalog)} for root, overrides in projects.items()
        }
    return result


def legacy_codex(path):
    if not path.exists():
        return {}
    config = tomllib.loads(path.read_text(encoding='utf-8'))
    section = config.get('ioncache-ai-tools', {})
    projects = config.get('projects', {})
    if not isinstance(section, dict) or not isinstance(projects, dict):
        raise ValueError('Codex plugin settings and projects must be tables')
    overrides = {}
    for root, data in projects.items():
        if not isinstance(data, dict):
            raise ValueError('Codex project settings must be tables')
        if 'ioncache-ai-tools' in data:
            overrides[root] = data['ioncache-ai-tools']
    result = dict(section)
    if overrides:
        result['projects'] = overrides
    return result


def write_atomic(path, text):
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_settings(path, catalog, complete, legacy):
    try:
        original = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        original = None
    document = json.loads(original) if original is not None else (legacy or {})
    result = reconcile(document, catalog, complete)
    return original, result, json.dumps(result, indent=2) + '\n'


def acquire_lock(lock):
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while True:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('configuration lock is busy; retry synchronization') from None
            time.sleep(min(0.02, remaining))


def sync_file(path, catalog, complete=True, legacy=None, *, strict=True):
    # Worktree-local settings may intentionally symlink to the main worktree.
    path = path.resolve()
    original, result, text = read_settings(path, catalog, complete, legacy)
    if text == original:
        return result
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with (path.parent / ('.' + path.name + '.lock')).open('a', encoding='utf-8') as lock:
            acquire_lock(lock)
            original, result, text = read_settings(path, catalog, complete, legacy)
            if text != original:
                write_atomic(path, text)
    except OSError as error:
        if strict:
            raise
        # A persistence failure must not mask unreadable or concurrently changed preferences.
        _, result, _ = read_settings(path, catalog, complete, legacy)
        print(f'plugin-config: could not persist {path}: {error}', file=sys.stderr)
    return result


def synchronize(project, harness=None, *, strict=False, catalog=None, persist=True):
    catalog = defaults() if catalog is None else catalog
    disabled = set()
    for host, (global_path, project_path) in paths(project).items():
        legacy_path = global_path.with_name('config.toml')
        legacy = {}
        try:
            if host == 'codex' and not global_path.exists():
                legacy = legacy_codex(legacy_path)
            if host == harness or global_path.exists() or legacy:
                if persist:
                    global_config = sync_file(global_path, catalog, legacy=legacy, strict=strict)
                else:
                    global_config = read_settings(global_path.resolve(), catalog, True, legacy)[1]
            else:
                global_config = {'features': catalog}
            values = {
                **global_config['features'],
                **global_config.get('projects', {}).get(str(project), {}).get('features', {}),
            }
            if project_path.exists():
                if persist:
                    project_config = sync_file(project_path, catalog, complete=False, strict=strict)
                else:
                    project_config = read_settings(project_path.resolve(), catalog, False, None)[1]
                values.update(project_config['features'])
            disabled.update(name for name, enabled in values.items() if not enabled)
        except (OSError, ValueError, TypeError) as error:
            if strict:
                raise
            # Never replace unreadable or malformed preferences with defaults.
            print(f'plugin-config: failed to read/sync {host} settings: {error}', file=sys.stderr)
            print('plugin-config: plugin features paused until this configuration is repaired.', file=sys.stderr)
            return set(catalog)
    return disabled


def feature_settings(data, *, refresh=False):
    snapshot = data.get('_ioncache_features')
    if isinstance(snapshot, FeatureSettings) and not refresh:
        return snapshot
    catalog = defaults()
    disabled = synchronize(data.get('cwd') or os.getcwd(), data.get('_ioncache_harness', 'claude'), catalog=catalog)
    return FeatureSettings(frozenset(catalog), frozenset(disabled))


def enabled(name, data):
    snapshot = feature_settings(data)
    return name in snapshot.catalog and name not in snapshot.disabled


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('host', choices=HOSTS)
    parser.add_argument('--project', default=os.getcwd(), help='project root for optional overrides')
    args = parser.parse_args()
    try:
        synchronize(str(Path(args.project).resolve()), args.host, strict=True)
    except (OSError, ValueError, TypeError) as error:
        print(f'plugin-config: synchronization failed: {error}', file=sys.stderr)
        sys.exit(1)
    print(paths(args.project)[args.host][0])


if __name__ == '__main__':
    main()
