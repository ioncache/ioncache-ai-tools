#!/usr/bin/env python3
import os
from pathlib import Path
import shutil
import sys


def main():
    node = shutil.which('node')
    if node is None:
        print(
            'create-worktree: Node.js is required for this skill. Install Node.js '
            'or make node available on PATH, then retry. No worktree was created.',
            file=sys.stderr,
        )
        return 1

    helper = Path(__file__).resolve().with_suffix('.js')
    try:
        os.execv(node, [node, str(helper), *sys.argv[1:]])
    except OSError as error:
        print(
            f'create-worktree: could not start Node.js: {error}. '
            'Check your Node.js installation and PATH, then retry.',
            file=sys.stderr,
        )
        return 1


if __name__ == '__main__':
    sys.exit(main())
