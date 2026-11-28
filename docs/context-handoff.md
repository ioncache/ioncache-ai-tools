# Context handoff

Claude Code 2.1.332+ can use a task-focused handoff at native compaction
boundaries. The handoff keeps the goal, workspace, unfinished task, decisions,
user constraints, open questions and next step. It asks the continuation to
check current disk state rather than trust earlier reports.

## Use

Native automatic compaction receives the handoff instructions. To compact
earlier, use Claude's built-in command:

```text
/compact
```

Optional text after the command tells the summarizer what else to keep. The
command uses Claude's compaction machinery in the same session. It does not
launch a replacement worker or require `/clear`, another message, or a restart.

For a portable handoff document, invoke `/ioncache-ai-tools:context-handoff`
in Claude or Copilot, or `$ioncache-ai-tools:context-handoff` in Codex. That skill
writes a document, not a context swap, and does not stop existing workers.

The skill accepts an optional destination file in the request, not fixed flags.
Without a destination, it returns the handoff in one fenced Markdown block.

Claude controls the automatic-compaction threshold. No status-line setup or
plugin threshold is needed. The plugin does not poll usage, interrupt a turn,
or compact other workers. If the manual command is unavailable while work is
running, let that work continue; native automatic compaction remains available.

## Continuation and recovery

Claude retains ownership of its transcript, compaction summary and kept
messages, including opaque message handles and tool exchanges. The plugin
changes only the summarizer's instructions, not message identities, permissions,
worker ownership or question-turn state. Child compactions are unchanged.

The handoff stays in the native session transcript and resumes with that
session. There is no working-directory-wide pending file for another session
to accidentally consume. The plugin does not launch another model separately;
native compaction still consumes model usage.

Summaries are model-generated, not a guarantee that every instruction or detail
survives. Missing prior context cannot be recovered by this feature. Compaction
failure is not converted into success and does not cause a retry loop or tool
denial. Other plugins and Claude's own permissions remain in force.

## Settings and other hosts

Disable automatic handoff instructions through the shared settings interface:

```text
/ioncache-ai-tools:ioncache-ai-tools-settings --hook:context-handoff=disabled
```

`skill:context-handoff` independently controls the portable-document skill.
Disabling only the skill does not disable automatic handoff instructions.
Boolean settings are reread for each operation.

Copilot and Codex do not run this native mod. The skill writes a portable
handoff document when requested, but it does not replace those hosts' contexts.

## Host contract

The implementation uses `session.compact` from Claude Code's native mod API.
Offline native tests exercise the dispatch, failure and continuation contracts
with compaction stubbed; they do not establish live summarizer quality.

Claude Code 2.1.332 does not support `session.state` or `session.load`
events, and rejects compaction from a `command.run` hook. The plugin therefore
uses the existing native boundary instead of creating its own threshold,
queued command, or pending-session state.

Reference: https://code.claude.com/docs/en/mods
