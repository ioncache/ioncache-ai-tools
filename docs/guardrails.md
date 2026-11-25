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
create a marker afterward. Compaction and resume keep existing state until
the next prompt.

Copilot verifies native question turns at tool time, not from the prompt-hook
payload alone. It correlates the current root `userPromptTransformed` with
the subsequent native `user.message`, including delivery and provenance.
An intervening memory-context message is skipped only when it belongs to
that same interaction.
Agent-authored, automation and autopilot messages do not start a question
restriction. Child events and tool-result handbacks cannot create a root
question. A new instruction or a completed root answer ends the restriction.
Missing, ambiguous, malformed or unreadable evidence leaves tools available.

Claude and Codex still have no verified positive native user-origin signal.
A genuine question with unknown origin receives guidance without a tool
fence. The shared guard supports positively identified user questions, but
normalized-input tests are not proof of those hosts' native detection.

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

| Host | Observed input and documented limits | Remaining gap |
| --- | --- | --- |
| Claude Code 2.1.326 | Captured a root question, instruction, background subagent report and shell-task notification. User prompts and notifications both had `prompt_id`. Recorded model-facing entry 419 combines a notification inside a leading system reminder with an agent hand-back. Entries 248 and 268 contain summary reminders. The batch reproduces the old prefix miss and declarative-starter false positive without any question marks. | No verified positive user-origin signal. The recorded batch is not hook stdin, so its exact prompt-hook representation remains unverified. Independent peer messages, scheduled tasks and Code Mode output were not captured. |
| Copilot CLI 1.0.113-1 | Captured a root question at `userPromptTransformed`, with `prompt` and `transformedPrompt` but no origin field. Documentation excludes system notifications from this event; that does not establish the provenance of every submitted or parent-written message. | Worker capture was denied by tool permissions. Instruction, hand-back, task-notification and peer-message captures remain unavailable. Batching and reminder formats are unverified. |
| Copilot CLI 1.0.115-8 (2026-11-24) | Human questions and autopilot reminders have the same prompt-hook fields, but subsequent `user.message` records distinguish autopilot provenance. Synchronous and background assignments carry child identities and an agent source. Question-shaped handbacks arrive as tool results; completion arrives as a system notification, not a root prompt hook. | Prompt-hook fields alone do not establish origin. Peer-message, scheduled-prompt and batched-prompt routing remain unverified. |
| Copilot CLI 1.0.116-1 (2026-11-24) | A fresh CLI invocation with this plugin denied a question-turn file redirect through the native pre-tool hook. Its emitted root message matches the earlier user-delivery evidence. Native pre-tool history records summarize a `toolCalls` batch; command hooks still receive individual tool inputs. | Resuming that disposable session with `--plugin-dir` emitted no hook events, so that invocation does not establish resumed enforcement. Custom callers that omit provenance cannot be distinguished from ordinary user delivery. |
| Copilot CLI 1.0.116-2 (2026-11-24) | One interactive process allowed read-only research and denied a write during a user question. The next instruction launched a child with a question-shaped assignment; the child wrote its fixture and returned a question, after which the parent wrote its own fixture. Native hooks ran for both identities throughout. The prompt sequence included memory context with the same interaction identity. | Live interleaving of a new root question while a child is actively writing remains covered by isolated adapter tests, not this interactive run. Peer messages, scheduled prompts and other batching formats remain unverified. |
| Codex 0.163.0 | Captured a root question and instruction. A worker returned a question-heavy report, but that return and the shell completion produced no additional prompt-hook invocation in this run. The documented prompt fields are `turn_id` and `prompt`, not origin. Stop-hook continuation reasons can act as new user prompts. | No verified positive user-origin signal. Child prompt, asynchronous notification, peer-message and Stop-continuation payloads were not captured. Batching and reminder formats are unverified. |

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
- https://docs.github.com/en/copilot/reference/hooks-reference#userprompttransformed
- https://learn.chatgpt.com/docs/hooks#userpromptsubmit
- https://learn.chatgpt.com/docs/hooks#stop

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

Assistant display and final-response text are not rewritten or blocked on any
host. Stop hooks deliver cache notices, not punctuation correction loops.
The `fix_emdash` file protections remain independent of assistant output.

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
