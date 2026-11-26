"""List or update shipped plugin settings across Claude, Copilot, and Codex."""
import argparse
import json
from pathlib import Path
import sys

import plugin_config as config

HOOK_SETTINGS = frozenset({
    'answer-questions', 'autonomous-development-explicit-only', 'block_raw_worktree_add',
    'docs-cache', 'fix_emdash', 'no_broad_process_kill', 'no-manual-lockfile-edit',
    'no_manual_lockfile_edit_bash',
})
INSTRUCTION_SETTINGS = frozenset({
    'documentation-first', 'engineering-judgment', 'scope-exactly-what-asked',
    'writer-quality-guidance',
})


def setting_groups(names):
    groups = {title: {} for title in ('Hooks', 'Instructions', 'Autonomous development', 'Reviews', 'Skills')}
    for name in names:
        if name in HOOK_SETTINGS:
            title = 'Hooks'
            public = 'hook:' + name.replace('autonomous-development-', 'autonomous-development:', 1)
        elif name in INSTRUCTION_SETTINGS:
            title, public = 'Instructions', 'instruction:' + name
        elif name == 'autonomous-development':
            title, public = 'Autonomous development', 'autonomous-development:execution'
        elif name.startswith('autonomous-development-'):
            title, public = 'Autonomous development', 'autonomous-development:' + name.removeprefix(
                'autonomous-development-')
        elif name.startswith('review-'):
            title, public = 'Reviews', 'review:' + name.removeprefix('review-')
        elif name.startswith('skill:'):
            title, public = 'Skills', name
        else:
            raise ValueError(f'setting has no display group: {name}')
        groups[title][public] = name
    return {title: settings for title, settings in groups.items() if settings}


def arguments(argv, catalog):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--global', dest='global_scope', action='store_true',
                        help='read or update global values, preserving project overrides')
    parser.add_argument('--project', type=Path, default=Path.cwd(),
                        help='project directory (default: current working directory)')
    for title, settings in setting_groups(catalog).items():
        group = parser.add_argument_group(title)
        for public, name in sorted(settings.items()):
            group.add_argument('--' + public, dest=name, choices=('enabled', 'disabled'),
                               default=argparse.SUPPRESS, help=f'set {public}')
    return parser.parse_args(argv)


def states(project, catalog, global_scope, *, updates=None):
    expected = updates or {}
    unchecked = set(expected)
    global_disabled = set()

    def observe(path, original, document, is_global):
        if path in expected:
            stored = config.settings(json.loads(original), catalog) if original is not None else {}
            verify_updates(path, stored, expected[path])
            unchecked.discard(path)
        if is_global:
            global_disabled.update(name for name, enabled in document['features'].items() if not enabled)

    effective = config.synchronize(str(project), catalog=catalog, strict=True, persist=False,
                                   read_observer=observe)
    for path in sorted(unchecked):
        verify_updates(path, {}, expected[path])
    return (global_disabled if global_scope else effective), effective


def update(project, catalog, changes, *, global_scope):
    host_paths = config.paths(project)
    targets = {host: (global_path if global_scope else project_path).resolve()
               for host, (global_path, project_path) in host_paths.items()}
    if not global_scope:
        global_paths = {global_path.resolve() for global_path, _ in host_paths.values()}
        for path in targets.values():
            if path in global_paths:
                raise ValueError(f'project settings target is a global settings file: {path}; '
                                 'choose a distinct --project directory, or use --global '
                                 'for an intentional global update')
    for host, path in targets.items():
        global_path = host_paths[host][0]
        legacy = (config.legacy_codex(global_path.with_name('config.toml'))
                  if global_scope and host == 'codex' and not global_path.exists() else None)
        config.sync_file(path, catalog, complete=global_scope, legacy=legacy, updates=changes)
        print(f'Saved: {path}')
    return targets


def verify_updates(path, stored, changes):
    if any(stored.get(name) is not value for name, value in changes.items()):
        raise ValueError(f'settings changed concurrently in {path}; '
                         'inspect the listing before retrying')


def display(project, names, selected, effective, *, global_scope):
    print(f'Project: {project}')
    print(f'Scope: {"global" if global_scope else "project"} (Claude, Copilot, Codex)')
    groups = setting_groups(names)
    width = max(len('Setting'), *(len(public) for settings in groups.values() for public in settings))
    heading = f'{"Setting":<{width}}  {"Global" if global_scope else "State":<8}'
    if global_scope:
        heading += '  Effective project'
    for title, settings in groups.items():
        print('\n' + title)
        print('-' * len(heading))
        print(heading.rstrip())
        for public, name in sorted(settings.items()):
            state = 'disabled' if name in selected else 'enabled'
            line = f'{public:<{width}}  {state:<8}'
            if global_scope:
                line += '  ' + ('disabled' if name in effective else 'enabled')
            print(line.rstrip())
    if global_scope and any((name in selected) != (name in effective) for name in names):
        print('\nProject overrides differ from global values; they were preserved.')


def main(argv=None):
    try:
        catalog = config.defaults()
        args = arguments(argv, catalog)
        project = args.project.resolve()
        if not project.is_dir():
            raise ValueError(f'project directory does not exist: {project}')
        changes = {name: value == 'enabled' for name, value in vars(args).items() if name in catalog}
        selected, effective = states(project, catalog, args.global_scope)
        if changes:
            targets = update(project, catalog, changes, global_scope=args.global_scope)
            selected, effective = states(project, catalog, args.global_scope,
                                         updates={path: changes for path in targets.values()})
        display(project, changes or catalog, selected, effective, global_scope=args.global_scope)
    except (OSError, ValueError, TypeError) as error:
        print(f'plugin-settings: {error}', file=sys.stderr)
        print('No success confirmed. Writes, if started, may be partial across hosts. '
              'Run without setting flags to inspect; correct the reported problem and retry.',
              file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
