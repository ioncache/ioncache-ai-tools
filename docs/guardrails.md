# Guardrails

Installation and basic usage: [../README.md](../README.md).
Opt-outs: [configuration.md](configuration.md).

## Guidance and permission

The plugin guides continuous autonomous workers. Scope handling is
instruction, not task approvals, read allowlists, or root/child permission
registries. Compaction, resume, and background handbacks do not create
authorization requirements.

The assistant must still honor the user's scope and explicit pause or
cancellation instructions. Hooks do not determine semantic intent or review
answer content. Native host permissions remain authoritative.

## Question turns

A user question asks for information so the user can decide what to do. The
answer-only tool guard requires positive evidence that a root prompt came
from the user, as well as question-shaped text. With both, the shared guard
applies this contract:

- The agent receives the answer contract: reasoning, a supported cause for
  WHY, and no apologies, deflections, recommendations, or offers of more work.
- The agent's recognized state-changing tool calls are denied during the
  question turn, even to continue an existing assignment.
- Read-only research stays available. After a denial, the agent answers from
  what it can research and ends the turn.

| Denied during a question turn | Examples |
| --- | --- |
| File edits | `Edit`, `Write`, `MultiEdit`, `NotebookEdit`, `apply_patch` |
| Recognized shell mutations | `git commit`/`push`/`reset`/`rebase`/`merge`, `gh pr create`/`merge`, `rm`, `mv`, `cp`, `mkdir`, `touch`, `tee`, file redirects, `npm install`, `node -e`, `python -c`, GraphQL mutations |
| MCP operations | Operation names starting with the word `create`, `update`, `delete`, `edit`, `write`, `remove`, `merge`, or `push`, in snake, kebab, dotted, or camel case (`create_issue`, `createIssue`) |
| Work control | Launching, messaging, or stopping workers (`Agent`, `Task`, `Workflow`, `SendMessage`, `TaskStop`, `stop_agent`, `spawn_agent`, `send_input`) and task or todo creation (`TaskCreate`, `TaskUpdate`, `TodoWrite`) |

Question state belongs to one identity. A question to the root never blocks a
running subagent. Prompts a subagent receives from its parent are not user
questions, so a question-shaped assignment does not restrict that subagent.
Host-started and unknown-origin prompt events clear the state instead of
creating it, so an orchestrator can act on returned work after answering.
They receive non-restrictive guidance, not the answer-only contract.
Clearing precedes configuration and guidance work. A failed evaluation cannot
create a marker afterward. Native checks re-read current evidence after
compaction or resume; unavailable evidence never restores a stale restriction.

Copilot verifies native question turns at tool time, not from the prompt-hook
payload alone. It correlates the current root `userPromptTransformed` with
the subsequent native `user.message`, including delivery and provenance.
An intervening memory-context message is skipped only when it belongs to
that same interaction. A user-invoked skill expands the prompt but not the
emitted message. A leading `/plugin:skill [arguments]` invocation matches only
when the expansion names that command and repeats its arguments. An inline
mention matches when the user's text follows the expansion unchanged. Older
skill-sourced messages that deliver model-loaded skill text are skipped.
Prompt mode (`-p`) delivers a typed command unexpanded, and the model then
loads the skill, so a prompt starting with `/name` or `/plugin:name` followed
by whitespace is an instruction. A prompt starting with a single-segment path
followed by a space, such as `/tmp why is it full?`, is also treated as an
instruction; a path containing another `/` remains a question.
Agent-authored, automation and autopilot messages do not start a question
restriction. Child events and tool-result handbacks cannot create a root
question. A new instruction or a completed root answer ends the restriction.
Missing, ambiguous, malformed or unreadable evidence leaves tools available.

Claude correlates the tool hook's `prompt_id` with a root transcript message
whose explicit `origin.kind` is `human`. The session and prompt must match,
and sidechain, metadata, host-message framing and completed answers cannot
create a question restriction. Native typed prompts and SDK messages declared
as human input carry this origin. An SDK prompt without declared origin does not.
Metadata records with the current `promptId` are skipped only for Skill tool
content, which names its `sourceToolUseID`, and image-read size notes. Other
metadata, such as peer messages or Stop hook feedback, still releases the
restriction. A typed slash command records command framing in the human
message and is an instruction.

Codex requires the current `turn_id` to have explicit `turn_trigger: "user"`
attribution without a parent turn or initiating agent, followed by its original
`user.text` message. This is the trigger assigned by the interactive TUI.
Completed, interrupted, delegated and automated turns do not qualify.
User-role items made entirely of `environments.environment_context` or
`skills.selected_skill_instructions` are host context, not user input.
Any other additional user-role input in the same turn makes the original
attribution ambiguous and releases the restriction; it does not inherit the
original question. Text starting with a `$plugin:skill` mention, or its linked
form, is an instruction when that skill was injected in the turn.
`codex exec` has an `exec` trigger, not verified human origin.

An explicit leading skill invocation is an instruction to run that skill on
every host, even when its arguments are question-shaped. A skill mentioned
inside a question leaves the turn a question. Skill or image content loaded
during the turn does not end the question turn.

All hosts use bounded local history at tool time, without another persisted
permission state. Unknown origin, older formats and transcripts that have not
caught up receive guidance without a tool fence. Native Claude and Codex calls
never fall back to an old question marker when their history is unavailable.

The missing tool fence does not relax the assistant's user-question rule.
Root guidance still requires answering a genuine user question without
continuing an existing assignment in that turn. Asking why workers have not
stopped does not authorize stopping them. This behavioral instruction does
not classify an unknown-origin prompt as user-written: question-shaped reports,
notifications, and parent-written assignments remain non-blocking.

A user-text clause ending in `?` makes the prompt a question. Without `?`,
the entire prompt must be one short clause: at most 12 words and 120
characters, with no trailing period, newline, colon or semicolon. It must
start with an interrogative word. Commas are allowed only for identical
repeated emphasis, such as "why the fuck, why the fuck!!!!!".

Starting words inside longer prose do not count. "When CI passes, merge the
PR." and the conditional feature request "when it's turned on, the review
skill should automatically post comments" are not questions. These limits
deliberately miss long, multi-clause and period-ended unpunctuated questions
rather than fence ordinary reports. This remains a text heuristic, not a
semantic determination of intent.

Coverage limits:

- The shell check recognizes common commands, not every state change. For
  example, `git add`, `git stash`, `sed -i`, `curl -X POST`, scripts run by
  path, and unlisted interpreters are not recognized.
- Unlisted host tools, such as scheduling tools, are not recognized.
- The guard does not check the reply. WHY answers and the other reply rules
  are instructions only.
- A question typed directly to a subagent identity is treated like a
  parent-written prompt and receives guidance only.
- A separate root session is not proof of user origin. Parent-written
  assignments without a child identity remain unknown and do not create a
  marker.

### Prompt-origin evidence and gaps

The initial references and live command-hook captures were checked on macOS
on 2026-11-17. Copilot's reference and live-session hook inputs were checked
again on 2026-11-24. Sanitized payloads are in
[../hooks/fixtures/prompt-origins.json](../hooks/fixtures/prompt-origins.json).
Recorded Claude model-facing batches, kept separate from hook captures, are in
[../hooks/fixtures/claude-batched-prompts.json](../hooks/fixtures/claude-batched-prompts.json).
Copilot native message provenance and worker routing are recorded separately in
[../hooks/fixtures/copilot-question-events.json](../hooks/fixtures/copilot-question-events.json).
The 2026-11-25 Claude and Codex captures are in
[../hooks/fixtures/claude-question-events.json](../hooks/fixtures/claude-question-events.json)
and [../hooks/fixtures/codex-question-events.json](../hooks/fixtures/codex-question-events.json).

| Host | Observed input and documented limits | Remaining gap |
| --- | --- | --- |
| Claude Code 2.1.326 | Captured a root question, instruction, background subagent report and shell-task notification. User prompts and notifications both had `prompt_id`. Recorded model-facing entry 419 combines a notification inside a leading system reminder with an agent hand-back. Entries 248 and 268 contain summary reminders. The batch reproduces the old prefix miss and declarative-starter false positive without any question marks. | No verified positive user-origin signal. The recorded batch is not hook stdin, so its exact prompt-hook representation remains unverified. Independent peer messages, scheduled tasks and Code Mode output were not captured. |
| Claude Code 2.1.332 (2026-11-25) | Interactive typed and declared-human SDK prompts carried `origin.kind: "human"` with matching prompt/session IDs before tool use. The plugin allowed a read and denied a file redirect with its answer-only reason. In one SDK process, the next instruction wrote its fixture, a child with a question-shaped assignment wrote its fixture and returned a question, and the parent then wrote its own fixture. Child tool hooks carried the parent's session/prompt IDs plus their own `agent_id`. Unmarked SDK input had no origin and `turnOrigin: "sdk"`. | Older formats and delayed transcripts remain guidance-only. Live interleaving of a fresh root question while a child writes is covered offline, not by this native sequence. Peer and scheduled deliveries remain uncaptured. |
| Copilot CLI 1.0.113-1 | Captured a root question at `userPromptTransformed`, with `prompt` and `transformedPrompt` but no origin field. Documentation excludes system notifications from this event; that does not establish the provenance of every submitted or parent-written message. | Worker capture was denied by tool permissions. Instruction, hand-back, task-notification and peer-message captures remain unavailable. Batching and reminder formats are unverified. |
| Copilot CLI 1.0.115-8 (2026-11-24) | Human questions and autopilot reminders have the same prompt-hook fields, but subsequent `user.message` records distinguish autopilot provenance. Synchronous and background assignments carry child identities and an agent source. Question-shaped handbacks arrive as tool results; completion arrives as a system notification, not a root prompt hook. | Prompt-hook fields alone do not establish origin. Peer-message, scheduled-prompt and batched-prompt routing remain unverified. |
| Copilot CLI 1.0.116-1 (2026-11-24) | A fresh CLI invocation with this plugin denied a question-turn file redirect through the native pre-tool hook. Its emitted root message matches the earlier user-delivery evidence. Native pre-tool history records summarize a `toolCalls` batch; command hooks still receive individual tool inputs. | Resuming that disposable session with `--plugin-dir` emitted no hook events, so that invocation does not establish resumed enforcement. Custom callers that omit provenance cannot be distinguished from ordinary user delivery. |
| Copilot CLI 1.0.116-2 (2026-11-24) | One interactive process allowed read-only research and denied a write during a user question. The next instruction launched a child with a question-shaped assignment; the child wrote its fixture and returned a question, after which the parent wrote its own fixture. Native hooks ran for both identities throughout. The prompt sequence included memory context with the same interaction identity. | Live interleaving of a new root question while a child is actively writing remains covered by isolated adapter tests, not this interactive run. Peer messages, scheduled prompts and other batching formats remain unverified. |
| Copilot CLI 1.0.63-1.0.117-2 (2026-11-26) | A replay of every local root `user.message` found 124 skill expansions that did not equal the emitted message, all reported as unavailable before this change. They had the preamble `The user explicitly invoked the "/command" skill.`: 120 leading invocations and 4 inline mentions, all now matched. Model skill loads in 1.0.89 and later emit no `user.message`; 1.0.63 emitted a `skill-<name>` source. In live 1.0.117-2 interactive runs, the previous code allowed a write after an inline skill mention in a question and showed the unavailability notice twice; this change denied it with no notice. Leading, bare, and prompt-mode invocations ran the skill's write, and the next instruction resumed work. | Steering before 1.0.115-7 and some queued messages had no prompt hook. A 1.0.116-1 resumed prompt and a 1.0.117-1 message after `task_complete` also had none. These still report unavailability without a restriction. Multiple inline skill mentions in one prompt were not observed. |
| Claude Code 2.1.306-2.1.332 (2026-11-26) | A replay of local transcripts found 588 root tool calls in question turns that the restriction released early. Skill tool content and image-read notes used the current `promptId`. Peer messages could also use the current `promptId`. A live 2.1.332 SDK sequence with declared human origin showed the previous code allowing a write after a question loaded a skill and denying a typed plugin slash command's write. This change denied the question's write, allowed the slash command, denied writes after an image read and a plain question, and resumed on the next instruction. | Compaction summaries in the middle of a turn were not examined. |
| Codex 0.163.0 TUI skill capture (2026-11-26) | A question containing a `$skill` mention recorded host environment context, the user text, then a user-role `skills.selected_skill_instructions` item. Before this change, that item released the restriction and the redirect was written. Plugin skills are named `plugin:skill`. Replaying pre-tool payloads against three live rollouts denied that write with this change and allowed it with the previous code. Live, the previous guidance led the model to skip a leading `$skill` invocation's write; with this change it ran. | Text with an attached image is wrapped in host framing items and is not fenced. Steering in the middle of a turn still releases the restriction. In the live sequences, the model declined question-turn writes itself, so the denial was verified by replay rather than a live hook decision. |
| Codex 0.163.0 (2026-11-25) | The interactive CLI supplied matching `task_started.turn_attribution` and original `user.text` metadata. It allowed a read, denied a file redirect with the plugin's answer-only reason, then allowed the next user instruction to write its fixture in the same process. An app-server capture had the same user attribution. A separate exec capture used `exec`, which does not establish human origin. | The transcript format is not a stable hook API. Unknown triggers, steering, missing attribution and exec prompts remain guidance-only. Native child/peer routing is covered by offline adapter fixtures, not this live sequence. |

Claude's hook documentation explicitly warns that transcripts are asynchronous
and may not yet contain the current turn. The captures confirmed this at prompt
time. Codex documents its transcript format as unstable. Neither a stale
transcript nor an event called `UserPromptSubmit` establishes a human author.
Known wrapper text can identify particular host messages, but the absence of
a wrapper cannot prove that a bare report is a user question. Claude framing
is normalized at the shared guidance entry boundary, outside the question
classifier. Column-zero task-notification and agent-message wrappers, or the
peer-message introduction, anywhere in a batch identify a host turn, including
inside a system reminder. System-reminder blocks are excluded from question
text, including nested or repeated reminders. An incomplete reminder leaves
origin unknown. Neither this negative evidence nor stripping reminders
establishes user origin.

References for these specific contracts:

- https://code.claude.com/docs/en/hooks#userpromptsubmit
- https://code.claude.com/docs/en/hooks#common-input-fields
- https://code.claude.com/docs/en/agent-sdk/typescript#sdkmessageorigin
- https://docs.github.com/en/copilot/reference/hooks-reference#userprompttransformed
- https://learn.chatgpt.com/docs/hooks#userpromptsubmit
- https://learn.chatgpt.com/docs/hooks#stop
- https://github.com/openai/codex/blob/rust-v0.163.0/codex-rs/tui/src/app_server_session.rs
- https://github.com/openai/codex/blob/rust-v0.163.0/codex-rs/protocol/src/turn_input.rs

The captures used an opt-in probe loaded from the feature worktree and a
one-invocation Codex hook override. No persistent user hook registration points
at a temporary script. Offline recovery tests cover unknown reports, children,
settings and marker failures. They also replay the recorded Claude batch and
exercise same-turn worker-launch recovery without another human prompt.
Replaying that text through Copilot and Codex tests their unknown-input
fallback, not those hosts' native framing. These checks do not fill the
live-host gaps above.

## Action checks and autonomous recovery

| Check | Denied action | Available alternative |
| --- | --- | --- |
| Lockfiles | Direct edits through file tools or recognized shell commands | Edit the dependency manifest and run the package manager |
| Broad process termination | Name-based commands and recognized process-group signals | Use an exact positive PID or native stop control for an owned or explicitly assigned process |
| Worktrees | Raw `git worktree add` or `gwta` | Run the setup launcher at the path supplied in the denial; no skill load is required |
| File punctuation | Shell input or added patch text containing em-dashes | Correct the command or added text; preserve patch context and literal filenames/data |
| Skill opt-outs | Explicitly loading a disabled plugin skill | Continue the task with other available tools |

Structured file edits containing em-dashes are rewritten without bypassing
normal host permissions. For literal paths or search patterns containing that
character, use structured file/search tools instead of changing the literal.
For literal data writes or shell paths, use an ASCII-only command that constructs
the character, for example Python `chr(0x2014)`. Write/Edit/MultiEdit content
rewrites do not preserve literal em-dashes.
Ambiguous patch-header whitespace is rejected; resubmit unpadded headers.

These checks recognize common actions, not every shell construct or tool.
The process rule does not verify ownership of positive PIDs. Do not terminate
another worker's processes merely because a command passes the check.
The setup launcher requires Node.js 22.12.0+; runtime/setup failures leave that
operation pending, not the entire worker. Correct the prerequisite through
an authorized setup path or continue other assigned work.

A violating action remains denied when retried unchanged. No retry count
turns it into an approved action. Recovery changes the action, uses supplied
information, or selects an allowed tool; it does not require another plugin
approval exchange.

Documentation-cache hits supply cached facts instead of fetching again.
Repeating the identical fetch once requests a live-fetch bypass. Busy or
unavailable cache checking leaves normal fetching available.
See [documentation-cache.md](documentation-cache.md).

## Checker failures

Engine and adapter failures report unavailable checking, not a successful
policy check or a policy violation. They do not grant native permissions or
create a persistent denial. Independent completed decisions remain effective.
Handler, adapter, and configuration-lock waits are bounded.

Malformed settings remain untouched. Plugin features pause while native
permissions continue to apply, allowing configuration repair or other work.
An unavailable check is not a reason to repeat the same failing tool loop.
Neither disabling the plugin nor restarting a session is the only recovery
from a plugin-owned action denial.

## Model usage and stored data

Scope, question, and punctuation checks do not launch model reviews. Guidance
is supplied at supported lifecycle and prompt events without retaining user
requests, task approvals, or assignments. The question guard stores one empty
marker file per questioned root identity under `/tmp`; the next non-question
prompt removes it. A marker that is not a regular file owned by the current
account is reported as an unavailable check, not enforced.
Copilot's native check instead reads up to 4 MiB from its own session's
`events.jsonl` under `$COPILOT_HOME/session-state`, or
`~/.copilot/session-state` when unset. It requires an owned regular file and
rejects symlinks. The plugin does not copy or persist that conversation
history, and it cannot verify a prompt outside the bounded history window.

Documentation-cache distillation is separate and consumes additional model
usage when enabled. Disable `docs-cache` to prevent those calls. Explicitly
invoked review skills can also use model agents.

## Host coverage and limits

The punctuation guard does not rewrite or block assistant display or
final-response text. Stop hooks deliver cache notices, not punctuation
correction loops. The `fix_emdash` file protections remain independent of
assistant output. Separately, opt-in Claude response validation checks and
rewrites supported responses before delivery:
[response-validation.md](response-validation.md).

Copilot general-purpose workers can refuse `/tmp` writes before invoking tools,
even with allow-all and without the plugin. This is tracked separately at
https://github.com/github/copilot-cli/issues/5441; repository-local continuation
does not establish that this host-level limitation is resolved.

Some native events and hosted tools bypass local hooks. Missing prompt or
child-start events therefore must not be prerequisites for continued work.
Existing sessions can retain old hook registrations after an installation
change; start a fresh session when switching plugin versions or source paths.

These checks are not security boundaries or a guarantee of agent obedience.
Host failures can prevent hooks from running, and settings access permits
disabling guards. Keep native permissions for security-critical restrictions.

## Host references

- https://code.claude.com/docs/en/hooks
- https://learn.chatgpt.com/docs/hooks
- https://docs.github.com/en/copilot/reference/hooks-reference
