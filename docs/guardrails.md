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

A user question asks for information so the user can decide what to do. When
a root agent's prompt is classified as a question, that turn is answer-only:

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
Host-started turns clear the state instead of creating it, so an orchestrator
can act on returned work after answering. In Claude these are background-task
notifications (`<task-notification>`), subagent hand-backs, and messages from
other sessions (`Another Claude session sent a message:`). Claude's hook input
has no origin field, so these prefixes are inferred from observed transcripts,
not a documented contract. Compaction and resume keep the state until the next
prompt.

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
- A host that represents a delegated worker as a separate root session, with
  no subagent identity, would apply the guard to that worker's
  question-shaped assignment. Sending the worker a non-question instruction
  clears it.

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
