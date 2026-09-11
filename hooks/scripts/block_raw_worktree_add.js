#!/usr/bin/env node
// PreToolUse hook: denies creating a worktree by any path other than
// /create-worktree.
//
// Raw `git worktree add` skips whatever per-project setup a repo defines
// (see ../../scripts/create-worktree.js and .worktree-setup.json) -
// untracked local config, generated caches, post-create commands. So does
// oh-my-zsh's stock `gwta` alias for it. The /create-worktree command is the
// only permitted path. This hook only matches the assistant's own tool calls;
// the git call that /create-worktree runs internally never passes through
// PreToolUse. A shell function or alias defined on one machine cannot be
// recognised here: a hook only sees the command text, so wrappers like that
// have to be removed from the shell, not denied by name.

const fs = require('fs')

const RAW_WORKTREE_ADD = /(^|[\s;&|(`])git\s+(-C\s+\S+\s+)?worktree\s+add($|[\s;&|)`])/
const OH_MY_ZSH_ALIAS = /(^|[\s;&|(`<>])gwta($|[\s;&|)`<>])/

function main() {
  let input
  try {
    input = JSON.parse(fs.readFileSync(0, 'utf8'))
  } catch (err) {
    return
  }
  if (input.tool_name !== 'Bash') return

  const command = (input.tool_input || {}).command || ''
  if (!RAW_WORKTREE_ADD.test(command) && !OH_MY_ZSH_ALIAS.test(command)) return

  console.log(
    JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'PreToolUse',
        permissionDecision: 'deny',
        permissionDecisionReason:
          'Creating a worktree with raw git or `gwta` is not allowed: it skips ' +
          'the per-project worktree setup. Use the `/create-worktree <same args>` ' +
          "command instead - it wraps the git call and applies the repo's " +
          '.worktree-setup.json, writing a default one first if the repo has none.'
      }
    })
  )
}

main()
