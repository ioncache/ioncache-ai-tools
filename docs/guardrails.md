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
- The agent's recognized state-changing tool calls are denied until its next
  non-question prompt, even to continue an existing assignment.
- Read-only research stays available. After a denial, the agent answers from
  what it can research and ends the turn.

| Denied during a question turn | Examples |
| --- | --- |
| File edits | `Edit`, `Write`, `MultiEdit`, `NotebookEdit`, `apply_patch` |
| Recognized shell mutations | `git commit`/`push`/`reset`/`rebase`/`merge`, `gh pr create`/`merge`, `rm`, `mv`, `cp`, `mkdir`, `touch`, `tee`, file redirects, `npm install`, `node -e`, `python -c`, GraphQL mutations |
| MCP operations | Operation names starting with the word `create`, `update`, `delete`, `edit`, `write`, `remove`, `merge`, or `push`, in snake, kebab, dotted, or camel case (`create_issue`, `createIssue`) |
| Work control | Launching, messaging, or stopping workers (`Agent`, `Task`, `Workflow`, `SendMessage`, `TaskStop`, `spawn_agent`, `send_input`) and task or todo creation (`TaskCreate`, `TaskUpdate`, `TodoWrite`) |

Question state belongs to one identity. A question to the root never blocks a
running subagent. Prompts a subagent receives from its parent are not user
questions, so a question-shaped assignment does not restrict that subagent.
Host-started and unknown-origin prompt events clear the state instead of
creating it, so an orchestrator can act on returned work after answering.
They receive non-restrictive guidance, not the answer-only contract.
Clearing precedes configuration and guidance work. A failed evaluation cannot
create a marker afterward. Compaction and resume keep existing state until
the next prompt.

**Native question enforcement is currently unavailable on all three hosts.**
The captured payloads do not establish user origin. A genuine question with
unknown origin therefore receives guidance without a tool fence. This favors
unattended continuation over accidentally stopping a worker on a report.
The shared guard still supports positively identified user questions, but
its normalized-input tests are not proof of native detection.

The classifier checks each sentence or line. One that ends in `?` or opens
with an interrogative word (`what`, `why`, `how`, `when`, `where`, `who`,
`which`, `is`, `are`, `does`, `did`, `can`, `could`, `should`, `would`,
`will`, `has`, `have`, `was`, or `were`) makes the prompt a question. This
includes statements and pasted lines such as "When CI passes, merge the PR."
or "Have the worker retry the build." To give an instruction, rephrase it so
no sentence or line opens that way or ends in `?`.

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

The official references below and live command-hook captures were checked on
macOS on 2026-11-17. Sanitized stdin payloads are in
[../hooks/fixtures/prompt-origins.json](../hooks/fixtures/prompt-origins.json).

| Host | Observed input and documented limits | Remaining gap |
| --- | --- | --- |
| Claude Code 2.1.326 | Captured a root question, instruction, background subagent report and shell-task notification. User prompts and notifications both had `prompt_id`. The documented prompt hook also runs on scheduled tasks, other sessions' messages and Code Mode output. | No verified positive user-origin signal. Peer messages, scheduled tasks and Code Mode output were not captured. The originally reported hand-back framing mismatch was not reproduced. |
| Copilot CLI 1.0.113-1 | Captured a root question at `userPromptTransformed`, with `prompt` and `transformedPrompt` but no origin field. Documentation excludes system notifications from this event; that does not establish the provenance of every submitted or parent-written message. | Worker capture was denied by tool permissions. Instruction, hand-back, task-notification and peer-message captures remain unavailable. |
| Codex 0.163.0 | Captured a root question and instruction. A worker returned a question-heavy report, but that return and the shell completion produced no additional prompt-hook invocation in this run. The documented prompt fields are `turn_id` and `prompt`, not origin. Stop-hook continuation reasons can act as new user prompts. | No verified positive user-origin signal. Child prompt, asynchronous notification, peer-message and Stop-continuation payloads were not captured. |

Claude's hook documentation explicitly warns that transcripts are asynchronous
and may not yet contain the current turn. The captures confirmed this at prompt
time. Codex documents its transcript format as unstable. Neither a stale
transcript nor an event called `UserPromptSubmit` establishes a human author.
Known wrapper text can identify particular host messages, but the absence of
a wrapper cannot prove that a bare report is a user question. The shared
handler therefore uses no harness-specific prefix allowlist.

References for these specific contracts:

- https://code.claude.com/docs/en/hooks#userpromptsubmit
- https://code.claude.com/docs/en/hooks#common-input-fields
- https://docs.github.com/en/copilot/reference/hooks-reference#userprompttransformed
- https://learn.chatgpt.com/docs/hooks#userpromptsubmit
- https://learn.chatgpt.com/docs/hooks#stop

The captures used an opt-in probe loaded from the feature worktree and a
one-invocation Codex hook override. No persistent user hook registration points
at a temporary script. Offline recovery tests cover unknown reports, children,
settings and marker failures; they do not fill the live-host gaps above.

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
