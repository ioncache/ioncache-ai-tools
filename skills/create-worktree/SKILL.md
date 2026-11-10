---
name: create-worktree
description: Creates a git worktree and applies the repo's .worktree-setup.json. Use when asked to create a worktree, including local config, generated caches, and post-create commands.
---

Resolve `../../scripts/create-worktree.py` relative to this skill's directory,
not the current working directory. Run the launcher from the user's repository,
passing the requested `git worktree add` arguments as separate, shell-quoted
arguments. Quote the resolved script path too, installation paths can contain
spaces. Do not assume a host-specific plugin-root environment variable exists.

The Python launcher requires Node.js 22.12.0 or later and checks its version
before invoking the JavaScript helper. If Node.js is missing, too old, or its
version cannot be verified, report the diagnostic and stop without creating a
worktree or setup files. Do not install or upgrade Node.js without separate
authorization or bypass the launcher with a direct Node or raw Git command.

For example, after resolving the actual installed path:

```bash
python3 "/absolute/plugin root/scripts/create-worktree.py" -b feature "../feature worktree"
```

Report the command's output. If it failed, show the diagnostic and stop,
don't retry with different arguments on your own.
