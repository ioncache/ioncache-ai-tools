#!/usr/bin/env python3
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


MIN_NODE_VERSION = (22, 12, 0)


def require_supported_node(node):
    result = subprocess.run(
        [node, '--version'], check=True, capture_output=True, text=True, timeout=5,
    )
    version = result.stdout.strip()
    match = re.fullmatch(r'v([0-9]+)\.([0-9]+)\.([0-9]+)', version)
    if match is None:
        raise ValueError(f'could not determine a stable Node.js version from {node}: {version!r}')
    if tuple(int(part) for part in match.groups()) < MIN_NODE_VERSION:
        raise ValueError(f'found unsupported Node.js {version} at {node}')


def main():
    node = shutil.which('node')
    try:
        if node is None:
            raise ValueError('node was not found on PATH')
        require_supported_node(node)
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        minimum = '.'.join(str(part) for part in MIN_NODE_VERSION)
        print(
            f'create-worktree: Node.js {minimum} or later is required. {error}. '
            'Install or upgrade Node.js, or correct PATH, then retry. '
            'No worktree was created.',
            file=sys.stderr,
        )
        return 1

    try:
        helper = Path(__file__).resolve().with_suffix('.js')
        os.execv(node, [node, str(helper), *sys.argv[1:]])
    except OSError as error:
        print(
            f'create-worktree: could not launch Node.js: {error}. '
            'Check executable access and invocation arguments, then retry. '
            'No worktree was created.',
            file=sys.stderr,
        )
        return 1


if __name__ == '__main__':
    sys.exit(main())
