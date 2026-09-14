---
name: create-worktree
description: Create a git worktree and apply the repo's .worktree-setup.json (untracked local config, generated caches, post-create commands), writing the file with generic defaults on first use
allowed-tools: Bash(node:*)
---

Run: !`node ${CLAUDE_PLUGIN_ROOT}/scripts/create-worktree.js $ARGUMENTS`

Report the command's output. If it failed, show the git error and stop,
don't retry with different arguments on your own.
