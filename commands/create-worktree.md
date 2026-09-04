---
name: create-worktree
description: Create a git worktree, applying the repo's .worktree-setup.json (untracked local config, env files, generated caches) if it defines one
allowed-tools: Bash(node:*)
---

Run: !`node ${CLAUDE_PLUGIN_ROOT}/scripts/create-worktree.js $ARGUMENTS`

Report the command's output. If it failed, show the git error and stop,
don't retry with different arguments on your own.
