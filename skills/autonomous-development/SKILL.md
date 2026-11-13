---
name: autonomous-development
description: Prepares an idea or existing artifacts for bounded implementation and review-ready PRs. Use when explicitly asked to prepare, execute, or resume an autonomous development plan.
---

# Autonomous development

Loading this skill does not authorize execution, spending, commits, or publication.
Humans approve the plan and retain PR approval and merge control. Questions do
not cancel an existing assignment. Use native permissions, not a turn-based gate.

## Prepare

1. Read the repository instructions and supplied idea, issue, design, or plan.
   Investigate and expand existing artifacts rather than treating them as complete.
   Resolve contradictory requirements before handover.
2. Configure planning, design documentation, and execution independently. Ask
   where each belongs when it is not already explicit. Do not bundle GitHub,
   Notion, and Claude into a preset.
3. Use the selected services' available tools and current documentation to create
   or update the intended artifacts. Reuse existing records; do not create duplicates.
   GitHub issues and Notion pages are optional destinations, not prerequisites.
4. Establish task and PR boundaries, dependencies, exact acceptance commands,
   allowed paths, compatibility, flags, intermediate states, rollout, rollback,
   and cleanup. Several tasks may form one PR.
5. Read [CONTRACT.md](CONTRACT.md). Produce a human-readable plan and a manifest
   with private snapshots of requirements, design, and plan content. Present the
   normalized interpretation and content identity for approval.
6. Resolve permissions and finite limits explicitly. Approval of document content
   is not native host permission. Do not infer publication or model budgets.

Run the helper by resolving `../../scripts/development_run.py` relative to this
installed skill directory:

```sh
python3 "/absolute/plugin/scripts/development_run.py" validate "/private/bundle/manifest.json"
```

## Execute

After explicit approval of the returned identity, initialize private state
outside the repository. Keep the approved input bundle and evidence private.

```sh
python3 "/absolute/plugin/scripts/development_run.py" init "/private/bundle/manifest.json" \
  --approved "<approved-identity>" --root "/project" --store "/private/development-run"
```

The packaged execution adapter is a Claude Workflow named
`ioncache-ai-tools:autonomous-development-run`. In Claude, ask the main agent
to run it with structured `store`, `pluginRoot`, and a unique `invocation` string.
Do not launch it from a subagent or silently substitute an external CLI.
The invocation string distinguishes a new launch from native replay.

Preflight must establish actual artifact access, native permissions, fresh
workers, independent review, result delivery, and cancellation. The adapter
dispatches reviewers, adjudicators, validators, and fixers flat. No leaf
launches another agent. [WORKERS.md](WORKERS.md) defines these assignments.

The controller and adapter have offline checks, not completed live-host
qualification. Obtain separate approval and resource limits for live trials.
Copilot and Codex can prepare manifests and inspect state; they do not yet have
packaged execution adapters. Do not imply cloud hosting or shared controls have
been provisioned.

## Resume and report

```sh
python3 "/absolute/plugin/scripts/development_run.py" status "/private/development-run"
```

Read persisted state before resuming. Keep attempts, findings, completed commits,
and PRs. Collect outstanding results before issuing another assignment. If a
worker is gone, inspect local and remote effects and record native shutdown
evidence with `retire`, then `resume`. Never reset the run to regain allowances.
See [CONTRACT.md](CONTRACT.md) for exact commands.

Report per-PR progress, readiness, exceptions, consumed allowances, incomplete
work, and evidence references. A runtime success is not acceptance. Mark a PR
ready only for its verified revision. Never approve or merge it, force-push,
push the default branch, deploy, or change production flags.
