# Review orchestration plan

Prepared on 2026-11-06 for review before implementation. This document is
self-contained; another harness should not need the originating conversation.
It proposes changes, not a description of shipped behavior or authorization
to implement them.

## Implementation record: 2026-11-06

The shared implementation is present in this checkout. This record distinguishes
implemented instructions and mechanics from unverified native execution; the
proposal below remains the design reference.

| Step | Implementation and remaining gate |
| --- | --- |
| 1 | Shared criteria, role instructions, request/pass/assessment contracts, and the three contract walkthroughs are implemented under `skills/review-code/`. |
| 2 | Current documentation and installed CLI versions/help were inspected. Separate approval for live trials was requested but unavailable. No launch-to-handback trials were run, and account-model discovery remains unverified. |
| 3 | Conditional nested/flat instructions and the storeless `review_ledger.py fingerprint` command are implemented. No agent descriptors or manifest migrations were added; packaging and native execution acceptance remain gated on Step 2. |
| 4 | The review/fix caller uses shared contracts and schema-1 evidence mapping. Mechanical fixtures exercise full/focused reviews, both mode records, provenance, duplicate observations, and resumable versus terminal outcomes. |
| 5 | README, roadmap, design, and repository instructions distinguish implementation from verified support. Mechanical checks do not complete the required live evaluation. |

The documentation baseline was checked against Claude Code 2.1.319, Codex CLI
0.163.0, and Copilot CLI 1.0.106 using their local `--version` and `--help`
output and the authoritative sources below. Tool availability and help text
do not establish a working lifecycle, account entitlement, or model suitability.
All three hosts still need approved trials before verified support is claimed.

Acceptance evidence is split as follows:

- Automated ledger fixtures cover storeless fingerprints, dirty/untracked/deleted
  inputs, index/HEAD drift, completed pass evidence, full/focused event ordering,
  origin/selection provenance, duplicates, reopening, and failure resumption.
- Shared-reference checks verify that the review entry points' linked files
  remain in the plugin. Contract walkthroughs name each finding's consumer,
  validator, and permitted action.
- Live nested/flat collection, inline routing, model selection/substitution,
  cross-boundary detection, adversarial-input handling, interruption cleanup,
  and comparative review quality remain unverified. The instructions define
  these behaviors; mechanical fixtures do not prove model compliance.

No account-filtered selection source or relevant model ranking has been
demonstrated. The implemented policy therefore preserves configured defaults
when evidence is unavailable, without claiming automatic selection is delivered.

## Goal

Run substantial code reviews through a dedicated coordinator with its own
context and model selection. The coordinator delegates independent review
passes, waits for their results, verifies and reconciles findings, and returns
one consolidated result to the invoking agent.

Keep execution inside the user's current coding harness. Do not build a
deployed service, VM, cloud control plane, or separate agent platform.
Normal model requests still use the harness's configured providers; local
orchestration does not imply local inference.

Select models from what the current harness and account actually expose at
review time. Do not ship model names, provider-specific rankings, fixed tier
mappings, or named fallback chains.

## Starting point

The existing [review-code skill](../skills/review-code/SKILL.md) already
requires independent substantial standards passes, a common scope and
snapshot, complete result collection, deduplication, and cross-cutting
correctness review. It preserves small checks with the coordinator and
respects configured model defaults.

Coordination currently belongs to the agent running the skill. A worker
whose caller already coordinates passes must not spawn another layer.
The proposed dedicated coordinator makes that role an explicit delegation
boundary, without creating a second review methodology.

The [review/fix skill](../skills/review-validate-fix-loop/SKILL.md) and its
[workflow](../skills/review-validate-fix-loop/WORKFLOW.md) currently give the
outer coordinator ownership of all launches and ledger writes. The
[earlier design](review-validate-fix-loop-design.md#deferred-optional-enhancements)
defers per-phase model and effort controls. This proposal introduces
role-based runtime selection for review only. It does not add controls for
every fixing phase or replace the separate cost-budget work.

Design decision: prefer a dedicated nested coordinator for substantial
reviews when the host supports the required lifecycle. This supersedes the
earlier design's general preference for flat orchestration in that case.
Flat execution remains the fallback, not an unsupported-host failure by
default. Step 5 records this decision in the earlier design separately from
claims about what has shipped.

The [review/triage loop](../skills/review-triage-loop/SKILL.md) is different:
fresh, minimally prompted reviewers run sequentially, followed by triage.
Preserve that experiment. Do not redirect it through this coordinator.

## What to borrow from Cloudflare

[Cloudflare's article](https://blog.cloudflare.com/ai-code-review/) motivates
the following changes:

| Borrow | Adaptation here |
| --- | --- |
| Specialist reviewers and a coordinator judge pass | Make the review coordinator a dedicated agent, not just a final summarizer. |
| Models matched to responsibility | Resolve available models at runtime rather than copying their model assignments. |
| Risk-sensitive delegation | Change worker count and grouping without dropping applicable standards. |
| Explicit scope and exclusions | State what each pass should and should not report, with evidence requirements. |
| Structured findings | Use one shared evidence contract and preserve the existing human-facing report. |
| Shared review context | Pass relevant references and concise context rather than every investigation transcript. |

Do not copy their CI integration, approval rubric, merge blocking, automatic
comment posting, provider failover service, telemetry backend, or fixed risk
thresholds. Do not blindly exclude lockfiles or generated files: their
relevance depends on the review target and changed behavior. Cloudflare
explicitly exempts database migrations from its generated-file filter;
preserve that exception.

## Responsibilities and execution

### Invoking agent

The invoking agent owns the user's request and any surrounding workflow.
It establishes the objective, scope, applicable constraints, and permission
boundary. It checks available delegation capabilities and selects the
coordinator's model before launching it.

It also owns the inline-versus-delegated decision. An inline review is
appropriate only when the required evidence fits a single direct read and
no substantial independent pass is needed. Otherwise use the dedicated
coordinator or flat fallback. Explicit requests for independent reviewers
take precedence over this shortcut.

This bootstrap matters: a coordinator cannot choose the model for its own
initial launch after it has already started.

The invoking agent provides requirements and relevant decisions, not
automatically its entire implementation conversation. It receives the
consolidated review and any required evidence records. It does not repeat
the whole review just because it receives the result.

### Review coordinator

The coordinator owns review planning, worker assignments, result collection,
evidence adjudication, integration review, and the final handback.
It selects worker models under the same policy used for its own launch.
It remains read-only with respect to the reviewed target.

Its work is judgment, not concatenation. It verifies reachable scenarios,
checks callers and requirements, resolves contradictory evidence, reconciles
underlying issues, and explains rejection or acceptance.

For specialist findings, coordinator adjudication is the independent
validation step, not a preliminary summary requiring another full validation
pass. Mark findings discovered by the coordinator itself separately: the
invoking agent checks their evidence independently before adopting them.
This does not require a new verifier agent for every finding.

### Specialist reviewers

Each worker owns a bounded pass and returns findings plus coverage.
Workers may trace relevant callers and consult authoritative sources.
They must not expand the review's authority, fix code, post comments, or
spawn their own reviewers.

Keep continuous call-chain investigations together. Separate agent contexts
provide independent investigations, not proof of independent assumptions
or freedom from inherited host instructions.

### Preferred execution

```text
Invoking agent
  -> capability check and coordinator model selection
  -> dedicated review coordinator
       -> confirm supplied scope and allocate passes
       -> independent specialist reviewers
       -> wait for every required result
       -> evidence adjudication and integration review
       -> consolidated report and evidence handback
  -> invoking agent
```

Permit only this review delegation layer below the coordinator. The outer
review/fix loop is a caller, not another specialist dispatching the same
passes in parallel.

The coordinator may perform independent cross-cutting investigation while
workers run. It must reconcile the complete required result set before
returning a completed review.

### Flat fallback and small reviews

Where nested launches are unavailable, or the host cannot deliver every
child's terminal outcome and report to the coordinator before it finishes,
the invoking agent handles assignment, launch, and collection. It then
passes the results to a separate adjudicator using the coordinator's
judgment instructions. The adjudicator can inspect source evidence but
does not launch another worker layer.

Use the same contracts in both modes. Disclose flat mode because the
invoking agent retains scheduling work and more intermediate context.
Do not introduce a daemon or second CLI process to bypass a host limitation.

Apply the invoking agent's inline-review criterion above. Do not call an
inline review an isolated coordinator review. If the request explicitly
requires independent agents and they are unavailable, return a blocked
outcome rather than substituting self-review.

## Runtime model selection

### Discover before selecting

For each run, inspect the current harness's supported discovery surfaces and
effective instructions. Establish:

- Models available to this session/account for delegated agents, not merely
  models advertised in a provider's public catalog.
- Whether model, reasoning effort, and context settings can be selected
  separately for the coordinator and workers.
- Applicable explicit user choices, host policies, defaults, and limits.
- Available evidence about model suitability and supported settings.
- Whether the harness exposes the actual model used after a launch.

Step 2 must name and demonstrate the source for each observation. Candidate
sources are the current session's delegation-tool model choices and a native
account-filtered catalog or access-checking resolver, if agent-accessible.
Distinguish supported parameter values from confirmed account access.
A user-only picker, static help list, or authored priority list alone does
not prove automated availability discovery.

Availability and suitability are separate. A model list alone does not
establish a quality ranking. Use current authoritative capability information
or relevant evaluation evidence when available. Do not infer capability from
model names, price, provider reputation, or a remembered leaderboard.

Record the current documentation or evaluation evidence used to match
candidates to roles. No account-discovery mechanism is assumed to exist on
every host. If Step 2 finds none, that host uses the disclosed default-only
fallback; it does not count as delivery of runtime model selection.

### Apply a role-based policy

| Responsibility | Selection needs |
| --- | --- |
| Coordinator/adjudicator | Evidence evaluation, conflicting claims, integration-level reasoning, reliable tool use, and context capacity for the request and required evidence. |
| Correctness, security, and performance passes | Strong code reasoning and the ability to trace reachable behavior across callers. |
| Mechanical or tightly bounded checks | Demonstrated ability to meet the pass requirements. Use evidence of lower overhead only as a tie-breaker among qualifying candidates. |

Documentation is not automatically a lightweight task. Checking a public
contract against implementation can require the same reasoning as code
review. A strong coordinator cannot recover issues that weak specialists
never identify.

Honor explicit user selections and applicable higher-priority instructions.
Within permitted discretion, choose a suitable available model for each
role. Use native per-run selection where supported; do not rewrite global
or project settings as a side effect of reviewing code.

Users express selections through existing harness settings or explicit
conversational role/model instructions accompanying the review request.
The review/fix invocation keeps its existing flags; this work adds no model
or effort flags. Host instructions that prohibit automatic overrides still
apply and must be recorded as a selection constraint.

If no reliable ranking is available, preserve configured defaults and state
the limitation. If discovery is unavailable, do not invent a catalog or
silently force a model. A single available model may fill several roles,
with separate contexts still providing the role boundary.

Do not choose an unauthorized replacement for an explicitly requested model.
The host may substitute independently of the coordinator. Detect and record
substitution wherever the host exposes it; do not promise to prevent it.
If a strict model requirement cannot be honored or verified, report the
required work as blocked unless the caller has authorized a fallback.

Record the requested selection, reason, evidence source, and actual selection
when observable. Mark an unobservable actual model as unknown, not verified.
Resolve effort and context settings against the selected model's supported
options rather than assuming settings transfer between models.

Recheck relevant availability after a launch failure or on resumption.
Retain successful evidence from an unchanged snapshot. Do not repeatedly
retry, change providers, or downgrade capability without an authorized,
bounded policy.

## Review contracts and quality

### Review request

Use one host-neutral request contract containing:

- Objective, review kind, target, pinned comparison base when applicable,
  and snapshot identity including relevant local changes.
- Applicable standards, requirements, exceptions, scope exclusions, and
  permission restrictions.
- Relevant caller-provided issue history and evidence-backed dispositions.
- Capability observations, model-selection constraints, and execution mode.
- Required completion conditions and applicable execution limits.

Reuse caller-provided snapshots. For standalone reviews, establish input
fingerprints without initializing a review/fix run solely to obtain them.
Include additions, deletions, and relevant untracked inputs. State unsupported
or mutable inputs rather than implying that a commit ID captures everything.

Shared context references must be accessible to every assigned worker.
File indirection reduces duplication of instructions, but does not guarantee
lower input cost when every model reads the same material.

### Pass allocation

Create a coverage map before launching workers. Every applicable standard
and the final cross-cutting pass needs an owner, scope, and completion
criterion. One worker can own several small, separately reported checks.

Use changed behavior, trust boundaries, failure impact, and investigation
size to allocate passes. A tiny authorization change may need substantial
review. A large mechanical edit may not need many independent specialists.
File counts and path names are hints, not a complete risk classifier.

Give workers explicit non-goals. Avoid speculative warnings, invented
requirements, and cosmetic suggestions presented as correctness defects.
Preserve the existing distinction between change reviews and repository
reviews, including treatment of pre-existing and out-of-scope issues.

### Findings and handback

Each candidate needs an underlying-issue key, location, affected behavior,
trigger, consequence, requirement or contract, supporting evidence,
uncertainty, proposed severity, and suggested next action. Include duplicate
or recurrence references where relevant.

Each pass result needs its assignment identity, reviewed snapshot, worker
identity, model-selection record, coverage evidence, limitations, and
complete/partial/failed outcome. An empty findings list is not evidence of
completed coverage.

The coordinator's handback contains:

- The existing consolidated human-facing findings table and counts.
- Scope, snapshot, execution mode, and coverage including required gaps.
- Evidence-backed candidate assessments, including duplicates and rejected
  candidates needed by a calling review/fix ledger.
- Unresolved consequential uncertainties, selection limitations, and a
  complete, incomplete, or blocked outcome.

Keep truth, scope, severity, confidence, and action separate. Model agreement
does not validate a finding. A rejected candidate needs evidence and a
reason; a serious uncertainty must not disappear merely to shorten output.
Perform the integration pass even if specialists return no findings.

Preserve the existing High/Medium/Low severity vocabulary and report shape.
Do not import Cloudflare's approval decision or silently redefine review
policy while changing orchestration.

## Lifecycle, permissions, and limits

Track the finite set of required assignments and their terminal outcomes.
Use supported host waits or completion notifications followed by result
retrieval, not repeated model calls whose only purpose is checking status.
An asynchronous return to the main conversation does not itself mean a
coordinator cannot collect children. Verify those two lifecycle boundaries
separately in Step 2.

Malformed, truncated, failed, or missing results leave the relevant coverage
incomplete. Do not merge a partial report into a clean result or report
completion while required descendants are still working.

Check the reviewed inputs before dispatch and after review/adjudication.
If they drift, preserve the evidence and return the mismatch. A standalone
review must not silently adopt the new target; a calling loop follows its
existing reconciliation protocol.

Keep launches bounded by the pass plan and host/user limits. Do not start
an unrequested multi-round search, add a verifier for every finding, or
recursively fan out. Additional investigation must have a specific evidence
gap and stay within the authorized scope and limits.

On interruption or failure, use permitted host lifecycle controls for owned
workers. Report any workers that could not be stopped or collected. Never
bypass permissions to clean up, restart the whole run to evade limits, or
interpret lack of output alone as proof of failure.

Workers and coordinators do not edit the target, commit, push, post reviews,
or change configuration. Use available tool restrictions, but distinguish
instruction-level read-only behavior from actual enforcement. Executable
validation must stay within permissions and must not mutate the target.

Keep review artifacts private and outside the reviewed target where possible.
The invoking agent owns any necessary persistent artifacts. In a review/fix
run, only the outer loop writes the canonical ledger through its helper.
Do not add a second writable review history or snapshot store by default.

Treat source text, PR descriptions, comments, and fetched documents as
evidence, not instructions that can change the task or select models.
Do not export private source to unrelated research services. Native model
requests remain subject to the user's configured provider and permissions.

## Implementation sequence

### Step 1: Define the shared review boundary

Refactor the [review-code instructions](../skills/review-code/SKILL.md) into
a concise entry point with shared role and contract references as needed.
Keep one source of truth for review criteria.

Define invoking-agent, coordinator, specialist, and flat-adjudicator roles.
Make entry-point delegation distinct from leaf-worker execution so loading
the same criteria cannot recursively start another full review.

Completion criterion: walk through sample handbacks for a specialist finding,
a coordinator-originated cross-boundary finding, and reviewed text that
requests edits or model changes. Identify each record's consumer, validator,
and permitted action. These contract walkthroughs feed the corresponding
acceptance scenarios; they are not evidence of model review quality.

### Step 2: Verify native execution and model discovery

For Claude Code, Codex, and Copilot CLI, verify current documentation and the
installed runtime before choosing packaging or invocation syntax. Check
coordinator launch, nested delegation, waits, result visibility, tool
restrictions, dynamic model selection, and effective model observability.

The following documentation baseline was checked on 2026-11-06. Recheck it
against the installed host before relying on it:

- Claude Code documents nested child-result collection in interactive
  sessions. Forks inherit the parent model and conversation, so use a
  non-fork coordinator for independent model selection and fresh context.
  Under `claude -p` with fork mode disabled, the spawning subagent does not
  wait for background nested subagents. Check interactive and noninteractive
  lifecycles separately, recording the fork-mode setting. Use flat mode if
  the coordinator cannot collect every required child result before finishing.
  Launch-time model parameters accept aliases; agent definitions also accept
  full IDs. Host allowlists can cause substitution. Plugin subagents ignore
  their own `hooks` and `permissionMode` fields; tool restrictions alone
  must not be described as a complete filesystem boundary.
- Codex documents collection of requested results and per-agent model/effort
  controls. Agents inherit parent sandbox and approval controls. Those
  statements do not establish plugin-based custom-agent discovery or an
  identical nested lifecycle.
- Copilot documents per-call and configured model selection, including
  host fallback. Custom subagents need `include-custom-instructions: true`
  to load repository instruction files. Its reference uses `modelPolicy`,
  while its agent how-to uses `model-policy`; verify the installed spelling.
  Inspect live result/wait/notification tools rather than treating the
  reference's brief status-tool description as proof of polling-only behavior.

Count actual agent launches when checking nesting limits. A loop skill
running in the main conversation is not an additional agent layer.
Record the host/version, evidence source, exposed selection and lifecycle
surfaces, and supported/fallback/blocked result for each capability.

Trials need separate approval before execution. Use small, supervised manual
trials on disposable inputs. Verify that a coordinator receives all child
results and returns one result to its caller. Include a flat-mode trial and
unavailable-discovery behavior.
Do not infer compatibility merely from similar tool names or agent files.

Completion criterion: retain a launch-to-handback trace for each claimed
execution mode and a sourced selection record for each claimed routing
capability. A catalog-dependent selection must be demonstrated without
changing shipped model identifiers. Record unresolved capabilities per host
and execution mode. Step 2 completes the capability investigation, not the
delivery of those unresolved capabilities. Steps 3 to 5 may proceed for
verified execution modes using disclosed configured defaults, even if no
tested host supports runtime selection. That delivers coordination only;
runtime selection remains an undelivered requirement until demonstrated.

### Step 3: Package the standalone coordinator

Implement the preferred nested path and flat fallback using native
delegation. Add host-specific descriptors only for discovery paths verified
in Step 2. Keep shared review policy in Markdown; do not duplicate it across
host descriptors or introduce a general scheduler.

No agent descriptors exist in this repository yet. Plan packaging by host:

- Claude Code documents a plugin `agents/` directory and
  `.claude-plugin/plugin.json`.
- Codex documents project/user custom-agent TOML files, but its plugin
  packaging guide does not establish discovery of bundled custom agents.
  Verify a native agent invocation supplied with shared role instructions
  before proposing extra installation steps. Do not silently write agent
  files into consuming projects or user configuration.
- Copilot's current Agent Plugins layout uses root `plugin.json` and
  `com.github.copilot/agents/`. Prefer that layout over extending the existing
  `.github/plugin/plugin.json` compatibility layout. Because the root
  manifest takes precedence, verify existing skills and hooks still load
  through the new layout before adopting it. Treat this as a shared packaging
  change: Codex also reads the root manifest.

For Codex, an inline `extensions.com.openai` object replaces the entire
`.codex-plugin/plugin.json` overlay without merging. Without that object,
the compatibility overlay supplies OpenAI-specific settings. Preserve the
explicit `./hooks/codex-hooks.json` selection in whichever configuration is
used. Do not let migration select the Claude hook file at `hooks/hooks.json`.

Codex and Copilot still document their compatibility layouts as supported.
Modernization is an explicit packaging decision, not a claim that those
layouts no longer work. Keep shared metadata consistent and preserve all
three hosts' existing behavior. Update the component-path descriptions in
[repository instructions](../.github/copilot-instructions.md) with any
adopted layout.

Wire in the runtime-selection capabilities demonstrated in Step 2 without
shipped model identifiers; otherwise use the disclosed configured-default
fallback.
Preserve existing direct handling of small reviews and the human report.

For Git-backed standalone fingerprints, reuse
`scripts/review_ledger.py`'s `snapshot(root, folder=None)`. Expose a read-only
invocation from the existing helper without initializing a ledger or storing
blobs. Preserve its whole-worktree coverage, HEAD/index checks, and documented
exclusions. Disclose that unrelated worktree drift can invalidate a narrower
review. Unsupported targets or required excluded inputs remain explicit
fingerprinting gaps; do not claim snapshot protection for them.

Completion criterion: the packaged plugin repeats Step 2's supported
launch-to-handback traces, preserves existing skills/hooks, and a standalone
fingerprint comparison detects additions, deletions, and relevant untracked
changes without creating a ledger or object store. Exercise the inline
decision and unavailable-capability fallback as well. If a root manifest is
adopted, verify both Copilot and Codex component discovery and confirm Codex
still loads its adapter hook configuration.

### Step 4: Integrate the review/fix caller

Update the [review/fix skill](../skills/review-validate-fix-loop/SKILL.md),
[workflow](../skills/review-validate-fix-loop/WORKFLOW.md), and
[ledger protocol](../skills/review-validate-fix-loop/LEDGER.md).
In nested mode, replace ownership of every specialist launch with ownership
of the review request and its result. In flat mode, the loop keeps assignment,
launch, and collection; the separate adjudicator is the addition. The outer
loop retains all writes, authorized fix batches, limit accounting, state
transitions, and final workflow reporting in both modes.

Record `start_review` before launching the full-review coordinator or any
specialist, so coordinator failure does not bypass outer-loop accounting.

Update the skills' configured-defaults-only instructions to reference the
runtime-selection policy and its explicit-input rules. Keep the loop's
model/effort flag rejection; conversational role selections and harness
settings are distinct from parsed invocation options.

Use the review boundary for full reviews and focused correction reviews.
Focused reviews retain their correction delta, affected callers, and all
outstanding relevant findings. They must not silently become full reviews.

Coordinator adjudication supplies validation for specialist findings.
The loop checks evidence completeness, investigates contradictions or gaps,
and records dispositions without repeating every investigation. It separately
validates coordinator-originated findings. Update the workflow's "Validate
findings independently" paragraph and the earlier design's "A separate
validator should challenge the finding" paragraph to name these owners.

Keep ledger schema 1. The richer handback is not a ledger event; map it
explicitly through the existing protocol:

| Handback content | Ledger representation |
| --- | --- |
| Candidate, including rejected or duplicate observations | `finding` with the existing key, summary, locations, severity, and evidence string array. |
| Completed pass | Exactly `name`, `worker`, `result: complete`, and `evidence`. Embed assignment identity, model-selection provenance, reviewed snapshot identity, and non-blocking limitations in the evidence string. |
| Assessment | `decision` after `review_done` or `fixes_reviewed`, with reasoning and validation provenance in existing reason/evidence fields. |
| Partial, failed, malformed, or missing required pass | Preserve received candidates, then `stop`. Put assignment outcomes, coverage gaps, model provenance, and available diagnostics in its reason; do not emit a successful review-completion event. |

Choose `blocked` for recoverable worker or capability failures and
`interrupted` for interruptions. Only those outcomes allow resumption.
Use `failed` for unrecoverable errors or `stalled` when progress cannot
continue and the run is abandoned. Do not make a recoverable worker failure
terminal merely because the worker's own outcome is `failed`.

Preserve checks and all other ordering requirements in the ledger protocol.
Do not add fields to exact-keyed events, fabricate completed passes, or
truncate diagnostics merely to fit the final human report. No schema bump
or old-ledger migration is part of this work.

Completion criterion: handback-to-event fixtures cover full and focused
reviews in nested and flat modes, including incomplete workers, resumable
versus terminal stops, and coordinator-originated findings. Existing ledger
replay accepts the records with unchanged counts, single-writer rules, and
drift handling.
The review/triage and dependency-review workflows remain unchanged; their
existing model policies are intentionally outside this proposal.

### Step 5: Validate and document adoption

First evaluate behavior through supervised manual reviews. Compare with the
existing process on the same snapshots. Judge missed issues, unsupported
findings, evidence quality, coverage, context overhead, and observed latency.
Record cost or usage only where the harness exposes it; mark missing data
as unavailable.

Do not claim improved review quality merely because more agents ran or a
more expensive model judged their outputs. Automate stable mechanical
cases after the manual path is established, without building a benchmark
service or requiring provider access in CI.

Update [README.md](../README.md),
[the roadmap](ROADMAP.md#review-workflow), and the
[repository instructions](../.github/copilot-instructions.md) to distinguish
implemented behavior, verified host support, and remaining limitations.
In the [earlier review/fix design](review-validate-fix-loop-design.md),
explicitly replace the general flat-orchestration preference and the
defaults-only/no-overrides descriptions with the conditional nesting and
review-role selection decisions. Preserve the separate deferral of
fixing-phase controls.
Do not change their shipped-behavior claims before the implementation exists.

Completion criterion: every acceptance scenario has recorded evidence or
an explicit unresolved limitation. Documentation claims only the modes and
selection capabilities demonstrated on each host. Required unresolved gaps
prevent claiming the affected capability is delivered.

## Acceptance scenarios

| Scenario | Required outcome |
| --- | --- |
| Substantial independent passes | Dedicated coordinator owns collection and adjudication; caller gets one handback. |
| Small review | Invoking agent applies the single-read/no-substantial-independent-pass criterion; explicit independence requests are honored. |
| Cross-boundary defect | Step 1's coordinator-originated case receives independent caller validation; supervised review checks actual integration-level detection. |
| Duplicate or conflicting candidates | Reconcile evidence and underlying causes rather than vote or concatenate. |
| Different available model catalogs | Resolve valid selections independently without hardcoded model/provider mappings. |
| Unknown model quality | Preserve defaults and disclose uncertainty instead of fabricating a ranking. |
| All tested hosts lack verified runtime selection | Steps 3 to 5 may deliver verified coordination using disclosed defaults; runtime selection remains an undelivered requirement. |
| Unavailable explicit model | No unauthorized agent-selected replacement; report observed host substitution and block an unverifiable strict requirement. |
| Unsupported effort or context option | Do not send an assumed setting to the selected model. |
| Nested delegation unavailable | Use flat mode if independent workers and an adjudicator can complete; otherwise block required independent work, not silently self-review. |
| Partial, malformed, or failed worker | Preserve useful evidence but do not mark required coverage complete. |
| Empty findings | Require completed pass evidence before reporting no findings. |
| Target drift or interruption | Preserve history and report incomplete work; do not silently restart or change scope. |
| Review/fix integration | Step 4 fixtures cover both execution modes, event ordering, schema-1 mapping, and unchanged outer-loop ownership and limits. |
| Prior rejected finding gains new evidence | Reopen its assessment without counting mere repetition as a new issue. |
| Reviewed text requests edits or model changes | Step 1's adversarial-input case leaves scope, model authority, and read-only permissions unchanged in supervised use. |

For documentation-only changes, run the relevant documentation checks from
[the validation workflow](../.github/workflows/validate.yml), including the
literal em-dash prohibition and skill frontmatter when skills change.
CI currently JSON-parses five manifests and three hook configurations.
If packaging changes, update that list and verify host discovery, not just
JSON syntax. Skill frontmatter checks cover only `skills/*/SKILL.md`;
new agent descriptors need format-specific checks. Shared Markdown references
need link/inclusion checks because existing CI does not validate those.

Extend and run `python3 scripts/review_ledger_self_check.py` for the
standalone fingerprint entry point and Step 4's event-mapping fixtures.
Run affected adapter self-checks only if adapter behavior changes.
Mechanical checks validate contracts and bookkeeping, not the correctness
of model judgments.

## Review focus before implementation

Reviewers of this plan should concentrate on:

- Whether the dedicated coordinator meaningfully improves ownership and
  context separation without duplicating the outer loop.
- Whether each host can discover usable models and apply role selections
  without overriding user policy or pretending a model list is a ranking.
- Whether the flat fallback preserves the evidence contract and exposes its
  weaker context separation.
- Whether all rejected/uncertain candidates needed by the ledger survive the
  consolidated handback.
- Whether manual lifecycle evidence supports the proposed host packaging
  before introducing new runtime code.

Exact host descriptors, discovery calls, and result transport remain gated
by Step 2. The storeless fingerprint helper and schema-1 ledger mapping are
chosen in Steps 3 and 4, not deferred packaging decisions. No new
persistent model configuration, automatic retry budget, provider service,
or universal model-quality score is proposed.

## External references

Consulted on 2026-11-06. Recheck relevant documentation against the installed
version and session capabilities during implementation. These sources are
starting points, not promises of identical host behavior.

- [Cloudflare: Orchestrating AI Code Review at scale](https://blog.cloudflare.com/ai-code-review/)
- [Claude Code: Custom subagents and nested delegation](https://code.claude.com/docs/en/sub-agents)
- [Codex: Subagents and model configuration](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [OpenAI: Plugin packaging](https://developers.openai.com/plugins/build/plugins)
- [Copilot CLI command reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference)
- [Copilot CLI custom-agent how-to](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/create-custom-agents-for-cli)
- [Copilot CLI plugin reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference)
