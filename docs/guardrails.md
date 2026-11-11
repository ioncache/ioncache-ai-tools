# Guardrails

Installation and basic usage: [../README.md](../README.md).
Opt-outs: [configuration.md](configuration.md).

## What is checked

| Guard | Behavior |
| --- | --- |
| Answer-only questions | Blocks recognized mutations for the whole question turn and supplies answer-only guidance |
| Scope | Supplies scope guidance and rejects mutations or delegation with stale native request or child-assignment context |
| Documentation first | Supplies documentation-backed research guidance, not factual verification |
| Engineering judgment | Directs non-trivial work to coherent solutions within the authorized scope |
| Process termination | Blocks recognized process-kill commands while enabled; chat approval does not override it |
| Lockfiles | Blocks direct file and shell edits; use the package manager |
| Worktrees | Routes creation through the setup-aware `create-worktree` skill |
| Punctuation | Fixes or rejects em-dashes |

These checks cover common actions, not every shell construct or tool.
While a question is pending, GraphQL calls must use one inline query without
`operationName`, body files, duplicate queries, or unrecognized options.
Patches with ambiguous file-header whitespace are rejected.

## Questions, scope, and recovery

A question mixed with an instruction still blocks recognized mutations.
Explicitly requested drafts or code may appear in the answer, but that does
not authorize file edits. A subsequent direct, non-question instruction clears
the question gate.

Scope and answer content remain instructions for the assistant. Hooks do not
judge whether a proposed action fits a request, whether an ambiguous approval
authorizes it, or whether prose offers unsolicited work. Passing a deterministic
check does not grant host permission or authorize work outside the user's request.

Compaction and resume preserve the active request and question gate. A clear
discards the active request. Copilot fences failed prompt updates so stale
question state cannot permit mutations or delegation. Resubmit a complete
direct instruction to recover. An identified child whose parent request has
changed needs a fresh assignment before it can mutate or delegate.

Read-only investigation and genuine user-input tools remain available during
these denials. Repeating a blocked mutation does not clear a question or refresh
a child assignment.

## Model usage

Scope, question, and punctuation guards do not launch model reviews.
Documentation-cache distillation is separate and consumes additional model
usage when enabled. Disable `docs-cache` to prevent those calls. Explicitly
invoked review skills can also use model agents.

## Context and privacy

Startup policy is delivered at initialization, context recovery, and supported
subagent startup, with a first-prompt fallback. Ordinary prompts do not repeat
the bootstrap. Question turns carry a compact answer-only contract.

Scope records live under `~/.cache/ioncache-ai-tools/claim-evidence/` in the
`scope-policy` namespace. They retain the current request, question
classification, request identity, and bounded punctuation
correction messages. They do not collect proposal histories or user answers
for authorization reviews. Session end clears question markers; resume restores
them from retained turn state.

Documentation-cache storage and usage are separate:
[documentation-cache.md](documentation-cache.md).

## Host coverage and limits

| Host | Final punctuation input |
| --- | --- |
| Claude Code | The native `last_assistant_message` field |
| Copilot CLI | The latest root assistant text at the exact current Stop event, including root task-completion summaries |
| Codex | The native `last_assistant_message` field; its unstable transcript format is not parsed |

Missing Copilot final text is reported as an unavailable punctuation check,
not a clean response. Checks cannot retract streamed prose or undo completed
actions. Other plugins' synthetic prompts cannot always be distinguished from
genuine user messages.

Copilot mid-turn steering does not trigger either prompt hook. The question
gate can therefore retain its previous classification. Resend a complete
instruction when the agent is idle to refresh it.

Background subagent handbacks have the same provenance limitation. Claude
Code runs `UserPromptSubmit` for background handbacks, but its documented
input has no origin field:
https://code.claude.com/docs/en/hooks#userpromptsubmit.
Copilot's `userPromptTransformed` excludes system notifications:
https://docs.github.com/en/copilot/reference/hooks-reference.
Codex documents no origin discriminator in `UserPromptSubmit`:
https://learn.chatgpt.com/docs/hooks#userpromptsubmit.
Use supported foreground collection when separation is unverified. Message
text is not trusted provenance, so notification-shaped prompts are not exempt
from classification and the question gate is not weakened. Synthetic prompt
misclassification is not fixed on every host.

Codex hosted search bypasses local tool hooks. Copilot's built-in general-purpose
agent lacks subagent start/stop events. Identified child tool events can
initialize child state.

These are not security boundaries. Host failures can prevent hooks from
running, and an agent with settings access can disable guards. Keep host
permissions in place for security-critical restrictions.

## Host references

- https://code.claude.com/docs/en/hooks
- https://code.claude.com/docs/en/cli-reference
- https://learn.chatgpt.com/docs/hooks
- https://learn.chatgpt.com/docs/non-interactive-mode
- https://docs.github.com/en/copilot/reference/hooks-reference
- https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference
- https://github.com/github/copilot-sdk/blob/main/docs/features/streaming-events.md
