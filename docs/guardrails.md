# Guardrails

Installation and basic usage: [../README.md](../README.md).
Opt-outs: [configuration.md](configuration.md).

## Guidance and permission

The plugin guides continuous autonomous workers. Scope and question handling
are instructions, not task approvals, read allowlists, turn fences, or
root/child permission registries. A side question does not cancel an existing
assignment or block another agent. Compaction, resume, and background
handbacks do not create authorization requirements.

The assistant must still honor the user's scope and explicit pause or
cancellation instructions. Hooks do not determine semantic intent or review
answer content. Native host permissions remain authoritative.

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
requests, task approvals, assignments, or question markers.

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
