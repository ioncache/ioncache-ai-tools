# Context handoff

Installation and basic usage: [../README.md](../README.md).
Opt-outs: [configuration.md](configuration.md).

Claude Code only. When a session's context usage reaches the threshold, Claude
stops its work, writes a self-contained handoff prompt, and the session halts.
After `/clear`, the next session starts with that handoff. Compaction is
blocked while the feature is enabled.

## Setup

Claude Code hooks do not receive context usage; only the status line command
does. Configure the plugin's status line once:

```text
/statusline Use the command: python3 ~/.claude/plugins/data/ioncache-ai-tools-ioncache-ai-tools/statusline.py
```

- The path is the plugin's data directory for the `ioncache-ai-tools`
  marketplace install. The directory name is the plugin ID
  (`ioncache-ai-tools@ioncache-ai-tools`) with every character other than a
  letter, digit, `_`, or `-` replaced by `-`.
- A session-start hook keeps that copy current, so the setting survives plugin
  updates. Start one session with the plugin enabled before configuring it.
- This replaces any existing status line. It shows the model and context usage,
  such as `[Opus] ctx 42%`.
- If no usage is recorded after Claude's first response, the plugin shows the
  exact `/statusline` command once per session.

The threshold is the `Context handoff threshold (%)` plugin option, 75 by
default and between 1 and 99. Change it in `/config`.

## Flow

1. The status line records the session's context usage in the data directory
   after each assistant message.
2. At or above the threshold, Claude is told to stop and load the
   `context-handoff` skill. Until the handoff exists, every tool call except
   the Skill tool and a Write to the session's handoff file is denied, and one
   attempt to end the turn is turned back with the same instruction.
3. Saving the handoff file stops Claude and shows its path. Type `/clear`, then
   send any message.
4. The new session receives the handoff as context, once, and acts on it when
   your message arrives. Later sessions do not receive it again.

To hand off before the threshold, or after compaction was blocked, run
`/ioncache-ai-tools:context-handoff`.

## Handoff contents

The [skill](../skills/context-handoff/SKILL.md) requires the goal, workspace
path and branch, current task, decisions and their reasons, every user
instruction quoted verbatim, open questions, and the exact next step. It is
written from the conversation alone; tools other than the Write are denied once
the threshold is reached.

The handoff does not report what is on disk or which tests pass. It gives the
commands the new session runs first (`git status`, `git diff`, `git log`, and
the build, test, and lint commands in use), so that state comes from the disk.

## Files

Everything lives under the plugin data directory,
`~/.claude/plugins/data/ioncache-ai-tools-ioncache-ai-tools/`:

| Path | Contents |
| --- | --- |
| `statusline.py` | The status line command |
| `context/<session>.json` | Latest recorded usage for a session |
| `handoffs/<session>.md` | The handoff a session wrote |
| `pending/<hash>.json` | A handoff waiting for the next session in the same working directory |
| `consumed/<session>.json` | The pending record a new session received |
| `sessions/<session>.json` | Whether a session has responded and been told the status line is missing |

Handoffs can contain anything from the conversation. Claude Code deletes this
directory when the plugin is uninstalled from its last scope.

## Interaction with other guards

The handoff Write is plugin-owned session state, not user work. The answer-only
question gate and the scope check allow it. Every other action keeps its
normal checks, including in the resumed session: the handoff is assistant-written
and does not authorize work by itself. If a scope check blocks work after the
handoff, restate the task and authorization in chat.

## Limits

- Pending handoffs are keyed by the hook's working directory. A session started
  in a different directory does not receive it.
- A new session started in the same directory before `/clear` receives the
  pending handoff instead.
- Writing the handoff outside the project can trigger Claude Code's normal
  permission prompt.
- Subagents are not checked; only the main session's context is measured.
- Until the status line is configured, no handoff is forced, and compaction is
  still blocked. Configure the status line, run the skill manually, or disable
  `context-handoff`.

## Host references

- https://code.claude.com/docs/en/hooks
- https://code.claude.com/docs/en/plugins-reference#user-configuration
- https://code.claude.com/docs/en/plugins-reference#environment-variables
