---
name: create-worktree
description: Creates a git worktree and applies the repo's .worktree-setup.json. Use when asked to create a worktree, including local config, generated caches, and post-create commands.
---

Resolve `../../scripts/create-worktree.js` relative to this skill's directory,
not the current working directory. Run the helper from the user's repository,
passing the requested `git worktree add` arguments as separate, shell-quoted
arguments. Quote the resolved script path too, installation paths can contain
spaces. Do not assume a host-specific plugin-root environment variable exists.

For example, after resolving the actual installed path:

```bash
node "/absolute/plugin root/scripts/create-worktree.js" -b feature "../feature worktree"
```

Report the command's output. If it failed, show the git error and stop,
don't retry with different arguments on your own.
