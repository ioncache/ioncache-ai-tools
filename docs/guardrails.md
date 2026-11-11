# Guardrails

Installation and basic usage: [../README.md](../README.md).
Opt-outs: [configuration.md](configuration.md).

## What is checked

| Guard | Behavior |
| --- | --- |
| Answer-only questions | Blocks recognized mutations for the whole question turn and checks replies for unsolicited work |
| Scope | Checks recognized mutations, delegation, follow-up agent messages, and response work products against authorization |
| Documentation first | Supplies documentation-backed research guidance, not factual verification |
| Engineering judgment | Directs non-trivial work to coherent solutions within the authorized scope |
| Process termination | Blocks recognized process-kill commands while enabled; chat approval does not override it |
| Lockfiles | Blocks direct file and shell edits; use the package manager |
| Worktrees | Routes creation through the setup-aware `create-worktree` skill |
| Punctuation | Fixes or rejects em-dashes |
| Graphify | Requires a graph query before code discovery when a project graph exists, with bounded failure fallback |
| Context handoff | Claude Code only: at the context threshold, denies other tools until a handoff is written, then halts; blocks compaction |

These checks cover common actions, not every shell construct or tool.
While a question is pending, GraphQL calls must use one inline query without
`operationName`, body files, duplicate queries, or unrecognized options.
Patches with ambiguous file-header whitespace are rejected.

## Questions, scope, and recovery

A question mixed with an instruction still blocks recognized mutations.
Explicitly requested drafts or code may appear in the answer, but that does
not authorize file edits. A subsequent direct, non-question instruction clears
the question gate.

Assistant proposals supply context for later approval; they do not authorize
themselves. Question-tool exchanges retain the user's answer, including
refusals and unavailable-user replies. Successful tool execution is not consent.
Missing or truncated context cannot establish authorization.

If work is blocked because context is missing, state the complete task, scope,
and authorization directly in chat. This recovery route works across hosts
without requiring a confirmation tool. Genuine restrictions still apply;
repeating a denied call does not grant permission.

Copilot can recover missing prompt and question-tool history from its native
transcript at root Stop when `approval-recovery` is enabled. Recovery validates
the session and exact Stop event, and retains the chronological dialogue as a
whole or not at all. It becomes available after Stop, not before the first
blocked edit, and does not retry edits or authorize a new task. Claude and
Codex do not import historical transcripts for approval recovery.

The context handoff Write to the session's handoff file is plugin-owned state.
The question gate and scope check allow that one Write; every other action
keeps its checks. See
[context-handoff.md](context-handoff.md).

Compaction and resume preserve the active request and question gate. A clear
discards the active request and recovered dialogue. Copilot fences failed
prompt updates so stale authorization cannot permit mutations or delegation;
submit a genuine request successfully to recover.

## Model usage and failures

Semantic checks launch the same host's CLI outside the consuming repository.
They use that isolated CLI's default model, with request, candidate, proposal,
and approval context supplied over stdin. They check authorization and
answer-only behavior, not factual claims, execution outcomes, or documentation.

**These calls consume additional host usage and can add latency.** Each has a
60-second deadline. Decisions are reused until the candidate, authorization,
or relevant settings change; operational failures are not cached as denials.

The CLI on `PATH` must support the isolation flags and authenticate
noninteractively. Claude requires `--safe-mode` support (2.1.169+); Codex
requires `--ignore-user-config` support (0.122.0+). These are flag minimums,
not compatibility guarantees for every hook event. Use a current supported CLI:

- https://github.com/anthropics/claude-code/releases/tag/v2.1.169
- https://github.com/openai/codex/releases/tag/rust-v0.122.0

Reviewer runs suppress this plugin's hooks. Claude disables customizations;
Copilot disables custom instructions; Codex ignores user configuration.
Claude and Copilot have no tools. Codex disables shell, web, and native
subagents in read-only mode but may expose utility tools. Unsupported options
produce upgrade guidance, never a retry with weaker isolation.

An unavailable or malformed reviewer denies recognized mutations. Read-only
investigation remains available to diagnose the failure. Final checks permit
at most two model calls and one correction per user turn. Further failure or
budget exhaustion produces a warning and an unverified result, not a successful
check or an endless correction loop.

## Context and privacy

Startup policy is delivered at initialization, context recovery, and supported
subagent startup, with a first-prompt fallback. Ordinary prompts do not repeat
the bootstrap. Question turns carry a compact answer-only contract.

Scope records live under `~/.cache/ioncache-ai-tools/claim-evidence/` in the
`scope-policy` namespace. They can contain user requests and assistant text.
Session end discards review decisions but retains request context for resume.
History and reviewer payloads are bounded; omissions are marked rather than
treated as consent.

The isolated host CLI can retain its own session history. Copilot does not
provide the ephemeral mode used for Claude and Codex here. Documentation-cache
storage and usage are separate: [documentation-cache.md](documentation-cache.md).

## Host coverage and limits

| Host | Response coverage |
| --- | --- |
| Claude Code | Records streamed `MessageDisplay` text and checks the final response |
| Copilot CLI | Retains root assistant prose through the exact current Stop event, including root task-completion summaries |
| Codex | Checks the final message only; its unstable transcript format is not parsed |

Missing batches, truncated text, or unavailable final text are incomplete
coverage, not a successful whole-turn check. Checks cannot retract streamed
prose or undo completed actions. Other plugins' synthetic prompts cannot
always be distinguished from genuine user messages.

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
initialize child state; anonymous child stops warn without consuming the
parent's review budget.

For Graphify, a successful query unlocks source inspection for that turn and
graph snapshot. A failed or unverified query permits source fallback. An
unavailable graph or executable causes one explanatory denial, then ordinary
discovery is permitted on retry. Help output, echoed commands, and queries
against another graph do not satisfy the gate.

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
