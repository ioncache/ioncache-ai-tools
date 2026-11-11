---
name: context-handoff
description: Writes a self-contained handoff prompt so a fresh Claude Code session can continue the current work after /clear. Use when the context-handoff hook says the context threshold is reached, or when the user asks to hand off instead of compacting.
---

# Context Handoff

Stop the current task. Do not run commands, read files, or make further changes
first. Write the handoff from what this conversation already establishes.

## Where to write it

Use the Write tool, never a shell command, with the exact path the
context-handoff hook gave. Without one, write to:

```text
${CLAUDE_PLUGIN_DATA}/handoffs/${CLAUDE_SESSION_ID}.md
```

Saving that file halts the session. The user then types `/clear` and sends any
message, and the new session receives the handoff.

## Reader

The reader is a fresh session with no access to this conversation, its tool
output, or its memory of decisions. Everything it needs to continue must be in
the handoff itself. Write it as instructions to that session, not as a story of
this one.

## Required sections

1. **Goal**: what the user wants done, and what done looks like
2. **Workspace**: the absolute worktree or repository path and the branch this
   session worked in
3. **Current task**: the task in progress when this session stopped, and the
   step it was on
4. **Check the state first**: the commands the new session runs in the
   workspace before acting, to find the state on disk itself: `git status` and
   `git diff` for uncommitted changes, `git log` against the base branch for
   committed work, and the exact build, test, and lint commands this session
   used
5. **Decisions**: each decision made and the reason for it, including options
   rejected and why
6. **User instructions**: every instruction, correction, preference, and
   constraint the user gave during this session, quoted verbatim, each with
   enough context to apply it
7. **Open questions**: anything unresolved, and who has to answer it
8. **Next step**: the exact next action, specific enough to start without
   further investigation

Write `None.` under a section with nothing to report rather than omitting it.

## Rules

- Do not narrate the session's history. Record the goal, task, decisions, and
  instructions only.
- Do not report what is on disk or what passed. File lists, diff contents, and
  test or lint results come from the new session running the commands, not
  from this handoff.
- Do not present guesses as facts. Label anything unconfirmed as unverified, and
  say what would confirm it.
- Quote user instructions exactly, including their wording, scope limits, and
  prohibitions. Do not summarize or merge them.
- Use absolute paths and exact names, commands, and identifiers.
- After the Write succeeds, stop. Do not continue the task in this session.
