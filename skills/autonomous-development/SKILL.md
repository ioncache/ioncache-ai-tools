---
name: autonomous-development
description: User-invoked only. Prepares an idea or existing artifacts for bounded implementation and review-ready PRs. Never automatically load this skill based on a matching task.
disable-model-invocation: true
user-invocable: true
---

# Autonomous development

Activate only through the human's direct skill invocation, not an assistant's
skill-tool call or inferred task match. Do not automatically load this skill
for planning, implementation, review, or maintenance of its own source.
Existing authorized work continues normally without invoking this skill.

Loading this skill does not authorize execution, spending, commits, or publication.
Humans approve the plan and retain PR approval and merge control. A user question
makes the questioned controller answer-only for that turn; it does not cancel
the assignment or stop workers. Hand-backs are not user questions.

## Prepare

1. Read the repository instructions and supplied idea, issue, design, or plan.
   Investigate and expand existing artifacts rather than treating them as complete.
   Resolve contradictory requirements before handover.
   An existing issue may supply both requirements and design. Keep implementation
   notes in the plan instead of inventing a competing design source.
2. Configure planning, design documentation, and execution independently. Ask
   where each belongs when it is not already explicit. Do not bundle GitHub,
   Notion, and Claude into a preset.
3. Use the selected services' available tools and current documentation to create
   or update the intended artifacts. Reuse existing records; do not create duplicates.
   GitHub issues and Notion pages are optional destinations, not prerequisites.
4. Establish task and PR boundaries, dependencies, exact acceptance commands,
   behavioral scope, compatibility, flags, intermediate states, rollout, rollback,
   and cleanup. Several tasks may form one PR.
5. Read [CONTRACT.md](CONTRACT.md). Produce a human-readable plan and a manifest
   with private snapshots of requirements, design, and plan content. Present the
   normalized interpretation and content identity for approval. For the packaged
   Claude adapter, set `configuration.execution.provider` to exactly
   `claude-workflows`. This identifier is not the workflow's display name.
   Run provider-specific validation before presenting the identity.
6. Resolve permissions and finite limits explicitly. Approval of document content
   is not native host permission. Do not infer publication or model budgets.
   Resolve native model and effort choices before launch under
   [MODELS.md](MODELS.md), including suitable implementation, adjudication and
   fixing choices. Bookkeeping runs in Python, not a model.
   Present the role table, evidence, cost trade-offs and configured-only
   limitations explicitly, not buried in constraints. Put explicit overrides in
   `configuration.execution.models` or `configuration.execution.review_options`.
   Size review allowances using the rule in CONTRACT.md, including independent
   category, adjudication, validation, owner and correction calls.
   Include `permissions.publish_audit` explicitly in new manifests, proposing
   `true` for GitHub PRs. Explain the repository wiki, newest-first audit index,
   public narrative review and PR-body links before approval. Confirm that the
   wiki is initialized and writable. A declined permission or
   the independent audit opt-out leaves publication disabled, not implied.
   Budget two additional assignments per PR plus any publication retries.
   See [AUDIT.md](AUDIT.md) for the export and publication contract.

Run the helper by resolving `../../scripts/development_run.py` relative to this
installed skill directory:

```sh
python3 "/absolute/plugin/scripts/development_run.py" validate "/private/bundle/manifest.json" \
  --provider claude-workflows
```

## Execute

Generic validation without `--provider` also accepts other execution providers,
with a warning when no packaged adapter exists. It does not authorize Claude
to execute that manifest.

After explicit approval of the returned identity, initialize private state
outside the launch repository and every planned worktree. Respect the project's
worktree-location convention, including sibling directories. Keep the approved
input bundle and raw evidence private.

```sh
python3 "/absolute/plugin/scripts/development_run.py" init "/private/bundle/manifest.json" \
  --approved "<approved-identity>" --root "/project" --store "/private/development-run" \
  --provider claude-workflows
```

The launching agent owns a script-driven dispatch loop. Resolve
`../../scripts/development_handoff.py` relative to this skill. Save the resolved
role map from MODELS.md as private JSON, then run:

```sh
python3 "/absolute/plugin/scripts/development_handoff.py" prepare "/private/development-run" \
  --models-file "/private/role-models.json"
```

Python pins the executor's resources and version inside the private run store,
reserves work, and writes a complete native workflow script with frozen jobs.
Use the returned pinned `helper` path for every later handoff command. Never
switch the executing scripts to the implementation worktree or edit resources
used by a running review.

For `action: launch`, run `claim STORE --batch B000001` with the returned batch ID.
After that command succeeds, launch the returned `script` through Claude's native
Workflow tool as `scriptPath`, without `args`. Do not invoke the packaged template
directly, paste state into workflow arguments, or ask a model to reproduce JSON.
Each generated workflow runs just one bounded batch: independent readers or one
exclusive fixer. It cannot reserve work, accept results, or declare the run complete.

After native completion, run `collect STORE --batch B000001`. Python reads and
checks actual report files, then advances durable state. Repeat `prepare` only
after collection. A lost `prepare` or `collect` reply can be recovered by repeating
that command. A lost `claim` reply cannot authorize another launch: inspect native
activity and reports first. `action: collect` means the batch was already claimed;
`action: inspect` means inspect durable state, not silently resume a stopped run.
Use [RECOVERY.md](RECOVERY.md) for failures and incomplete results.

The generic skill does not require Claude for planning or bookkeeping. The
packaged native batch adapter currently targets Claude. Do not silently substitute
another provider or launch an external CLI. An explicitly selected headless Claude
session can use the native Workflow tool under its normal host permissions;
that is different from replacing native orchestration with ad hoc CLI workers.

Preflight must establish actual artifact access, native permissions, fresh
workers, independent review, result delivery, and cancellation. The adapter
dispatches independent read-only review leaves concurrently, with each fixer
running alone between reader batches. All dispatch remains flat. No leaf
launches another agent. Reviewers receive frozen single-purpose packets, with
category controls independent of writing skills. [WORKERS.md](WORKERS.md)
defines these assignments and the final category-coverage handoff.
Host-loaded repository instructions may be present, but review workers must
ignore them and use only their explicitly assigned ruleset. Disclose observed
ambient sources; their presence must not stop execution, make coverage partial,
or trigger replacements.

The controller and adapter have offline checks, not completed live-host
qualification. Disclose that limitation and distinguish a separately scoped
qualification experiment from executing already approved work. Do not invent
another "live-trial approval" gate for actions and limits the human already approved.
Ask only for a genuinely missing decision, permission or increased allowance.
Copilot and Codex can prepare manifests and inspect state; they do not yet have
packaged execution adapters. Do not imply cloud hosting or shared controls have
been provisioned.

## Watch from launch

At launch, give the human the absolute store path and this exact command with
the installed script path filled in. It works in another session or terminal
with filesystem access to that store; no original host session is required:

```sh
python3 "/absolute/plugin/scripts/development_run.py" watch "/private/development-run"
```

The launching agent must also run this monitor immediately after launch.
Verify its first output and check preflight early. Use the default 300-second
inactivity threshold unless observed worker behavior warrants another value.
Continue watching through execution, rather than ending
the turn and relying only on the workflow-completion notification. A native
process-monitor tool may run this same command and deliver its output; do not
replace it with repeated model calls or an independent monitoring protocol.

Report promptly when the monitor reports blocked, interrupted, waiting,
exhausted, complete, unavailable state, or no durable advancement. The default
inactivity threshold is 300 seconds and can be changed with `--stale-after`.
Give a visible update at least every five minutes during long work, even if the
worker is active without a new checkpoint. State the current phase, durable
advancement, outstanding worker activity, and any blocker. A monitor exit is not
a failed task assertion; a native return is not verified completion.
Inactivity is an observation, not proof of a dead worker. Inspect native status
and outstanding effects before deciding whether recovery is needed. If the
worker is still legitimately active, report that and restart the same monitor
with a suitable threshold; never automatically cancel, retire, or relaunch it.
Do not spin on repeated unchanged inactivity notices.

Watching does not keep Claude running after its session exits. Current Claude
documentation describes native replay within the original session, and does
not document a cross-session `/workflows` visibility setting:
https://code.claude.com/docs/en/workflows.
The durable monitor is the supported cross-session view, not native run control.

## Resume and report

```sh
python3 "/absolute/plugin/scripts/development_run.py" status "/private/development-run"
```

Read persisted state before resuming. Keep attempts, findings, completed commits,
and PRs. Collect outstanding results before issuing another assignment. If a
worker is gone, inspect local and remote effects and record native shutdown
evidence before using the matching recovery in [RECOVERY.md](RECOVERY.md).
Retain readable reviews with `resume-review`, rather than retiring them by default.
Never reset the run to regain allowances.

Cancellation stops scheduling and owned native work, not implementation files,
issues, commits or evidence. Rollback is a separate destructive action. Clarify an
ambiguous "undo" before modifying either the target work or durable history.

Report per-PR progress, readiness, exceptions, consumed allowances, incomplete
work, and evidence references. A runtime success is not acceptance. Mark a PR
ready only for its verified revision. Never approve or merge it, force-push,
push the default branch, deploy, or change production flags.
When audit publication is approved and enabled, publish initial evidence after
creating the draft PR and final evidence before readiness. Preserve both immutable
links. Report disabled publication explicitly; never upload the private run store.
