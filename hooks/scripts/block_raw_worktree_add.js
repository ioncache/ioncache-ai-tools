#!/usr/bin/env node
// PreToolUse hook: denies raw `git worktree add` in Bash commands.
//
// Raw `git worktree add` skips whatever per-project setup a repo defines
// (see ../../scripts/create-worktree.js and .worktree-setup.json) -
// untracked local config, generated caches, env files. The /create-worktree
// command wraps `git worktree add` and applies that setup, so it's the only
// permitted path. This hook only matches the assistant's own tool calls;
// the `git worktree add` that /create-worktree runs internally never passes
// through PreToolUse.

const fs = require('fs')

const RAW_WORKTREE_ADD = /\bgit\s+(-C\s+\S+\s+)?worktree\s+add\b/

function main() {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'))
  if (input.tool_name !== 'Bash') return

  const command = (input.tool_input || {}).command || ''
  if (!RAW_WORKTREE_ADD.test(command)) return

  console.log(
    JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'PreToolUse',
        permissionDecision: 'deny',
        permissionDecisionReason:
          'Raw `git worktree add` is not allowed: it skips any per-project ' +
          'worktree setup. Use the `/create-worktree <same args>` command ' +
          "instead - it wraps `git worktree add` and applies the repo's " +
          '.worktree-setup.json, if one is defined.'
      }
    })
  )
}

main()
