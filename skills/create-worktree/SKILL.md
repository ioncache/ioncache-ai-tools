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
version cannot be verified, leave the worktree and setup files untouched.
Use a compatible installed Node.js via `PATH`, or the project's authorized
runtime setup procedure, then retry the launcher. Do not bypass its checks with
a direct Node or raw Git command. If the prerequisite remains unavailable,
report that operation as pending and continue other authorized work.

For example, after resolving the actual installed path:

```bash
python3 "/absolute/plugin root/scripts/create-worktree.py" -b feature "../feature worktree"
```

Report the command's output. On failure, address the reported cause before
retrying; do not repeat an unchanged failing command or silently change the
requested branch and destination.
