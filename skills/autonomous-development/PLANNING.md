# Incremental delivery planning

Prepare uses this guide before finalizing the human-readable plan and manifest,
when the effective `autonomous-development-incremental-planning` setting is
enabled. [SKILL.md](SKILL.md) defines that lookup and the baseline used when it
is disabled or unavailable.

Every plan explicitly decides:

1. Whether the work belongs in one PR or several small, coherent PRs.
2. Whether to use a feature flag, after investigating the repository's mechanism.
3. Whether any PR increment warrants its own issue or sub-issue.

Smaller increments should improve understanding, feedback and review for
humans and agents. Splitting is a reasoned choice, not a PR-count target. One
coherent PR remains a valid result.

These are planning questions to investigate and answer, not mandatory prompts
to the human. Ask only when missing information materially changes the choice
and cannot be established from available evidence. Keep the effort
proportional: a small change can answer every question in a few sentences. Do
not demand a large table for a typo fix or create issues to fill a template.

This guide does not grant host permissions, authorize merging or deployment,
or activate production flags. Planning a flag never authorizes changing one.

## Flow

1. Investigate repository conventions and relevant current behavior.
2. Identify plausible delivery boundaries and compare them with one cohesive PR.
3. Assess feature flags for the overall change and for any slice with distinct
   rollout needs.
4. Revisit the boundaries using compatibility, dependency, release and rollback
   findings.
5. Decide the issue structure separately from the PR structure.
6. Record the chosen plan, boundary contracts, prerequisite evidence, rejected
   alternatives, assumptions and unresolved decisions. Resolve conditional
   candidates before including them in the executable manifest.

## Repository investigation

Look for documented conventions and representative implementations, not
assumed best practices.

| Area | Why it affects the design |
| --- | --- |
| Feature flags and configuration | Evaluation APIs, defaults, environments, lifecycle, failure behavior, targeting and tests determine whether a flag can safely separate merging from activation. |
| Branch and review policy | Trunk-based work, accepted stacking practices, branch protection, required approvals and review ownership affect landing overhead. Repository preference does not create executor capabilities. |
| Release and deployment model | Independently released packages or services, lockstep releases, mobile or external clients and mixed-version deployments constrain safe intermediate states. |
| Compatibility and migrations | API, event, database, configuration, file-format and public-package contracts may need additive changes or an expand, migrate and contract sequence. |
| Tests and delivery cost | Integration tests, preview environments, CI duration and release costs affect whether more PRs actually reduce risk. |
| Architecture and ownership | Stable interfaces and real ownership boundaries can support slices; directory boundaries alone do not. |
| Issue conventions | Parent issues, sub-issues, templates, labels, design locations and access restrictions determine how to organize durable context. |
| Observability and operations | Metrics, rollout checks, kill switches, rollback procedures and cleanup ownership determine whether an increment can stay safely deployed. |

Record relevant evidence and search limitations. Not finding a flag system in
one file is not evidence that none exists. Verify provider-specific semantics
against current documentation; a dependency's presence alone does not establish
runtime flag support.

## PR boundaries

Weigh these signals together rather than scoring them mechanically:

| Signal | Guidance |
| --- | --- |
| Independent user or operational value | A useful subset is a strong split candidate, even if the larger feature never ships. |
| Improvement to an existing feature | A standalone reliability, accessibility, performance or usability improvement is a strong candidate. |
| Backward-compatible preparation | An additive interface or behavior-preserving prerequisite can justify a PR without immediate user value. Explain what it enables and why maintaining it temporarily is worthwhile. |
| Focused feedback or uncertainty reduction | A slice that validates an integration or assumption can prevent investment in the wrong approach. A research spike need not produce a mergeable production PR. |
| Independent verification or rollback | A boundary with its own meaningful checks and recovery path can reduce blast radius. |
| Distinct release or ownership boundary | Separate packages, services or review owners can favor splitting when their contracts support it. |
| Strict dependencies | Landing order, repeated base updates, review delay and blocked successors are costs against splitting, never an automatic veto. |
| Tight coupling or atomic correctness | Keep changes together when a split creates unsupported states, breaks consumers or obscures invariants. |
| Temporary complexity | Duplicate paths, adapters, flags and migrations carry real maintenance and test costs. Do not add them only to manufacture smaller PRs. |
| Review and delivery overhead | More PRs mean more CI, review, audit, coordination and potentially model cost. Prefer a few coherent increments over fragmented micro-PRs. |

Do not use fixed line, file, token or PR-count thresholds as the decision rule.
Prefer vertical, usable slices, but allow a justified compatibility-preserving
preparatory change. Keep each slice's tests, configuration, documentation and
dependent callers with it.

Every selected implementation increment maps to its own PR. Several manifest
tasks can still belong to that PR. A manifest task is not necessarily an issue
or a whole PR.

## Boundary contracts

For each boundary between increments, record what the producer provides and
what each consumer requires, the responsible increments and the authoritative
design reference:

- Interface names, input and output schemas, configuration keys or externally
  consumed paths, where these form an actual contract.
- Behavioral guarantees, defaults, error behavior and relevant compatibility or
  version expectations.
- Which consumers can use the interface immediately and which need a later
  migration or activation.
- Checks that establish the producer's contract and each consumer's assumptions.

Do not invent interfaces to justify a split or freeze incidental implementation
details. Contract paths are not edit allowlists. Put shared contracts in the
authoritative design snapshots referenced by the affected tasks; task
`compatibility`, `completion` and `checks` capture the obligations without
duplicating the design.

## Safe intermediate states and dependencies

For each candidate increment, ask what happens if it lands and the rest is
delayed indefinitely or abandoned. Every permitted landing sequence must leave a
supported, testable state. Document:

- Behavior immediately after merge and deployment, including flag-disabled behavior.
- Supported old and new producer and consumer combinations.
- Migration or data prerequisites, background jobs, operational effects and reversibility.
- Acceptance checks that do not assume unmerged code exists.
- Whether the increment can be reverted independently after later increments land.
- Cleanup obligations if the project stops here.

Distinguish implementation dependencies, PR merge dependencies, deployment or
data prerequisites, and activation dependencies. Do not turn a preferred order
into a strict dependency, or omit a real one to make a plan look parallel.

Use an explicit acyclic dependency graph for PRs and tasks. Under the packaged
executor, a cross-PR prerequisite means waiting for its human merge; dependent
PRs are not stacked or rebased. Reflect those waits in the recommendation and
the limits. Independent increments can still proceed, though eligibility does
not promise concurrent implementation. A PR dependency does not prove that a
migration ran or a flag was enabled, so record operational prerequisites in the
plan and checks.

A flag can make increments independently mergeable only if the default path
actually stays compatible. If no safe useful split exists, explain why one PR
is preferable.

## Prerequisite evidence

For each real prerequisite, name the required outcome, its evidence source, and
the revision or environment the evidence applies to:

- **Same-PR task prerequisite:** the task's completion and acceptance evidence,
  not a separate merge.
- **Cross-PR prerequisite:** the intended PR actually merged, with its required
  changes present in the dependent base. During execution, each PR's `prepare`
  assignment waits until its prerequisite PRs are merged, then records the base
  it prepared from ([WORKERS.md](WORKERS.md)). The controller checks the
  reported merges and that this base descends from the approved one, not that
  the prerequisite's changes reached it. When a prerequisite targets a
  different branch, add a check that confirms them in the dependent base.
- **Deployment, data, configuration or activation prerequisite:** evidence of
  the required state in the relevant environment. Merged code alone is not enough.

A closed issue, a draft or ready PR, or a ticked checklist does not by itself
establish the outcome. An issue closed as not planned does not satisfy its
dependents. For a cancelled, superseded or partially completed prerequisite,
record whether the dependency remains unmet, equivalent evidence satisfies it,
or a justified plan revision removes or replaces it. Never drop it silently.

Ordering stays in the existing task and PR `dependencies`. The evidence
requirements belong in the design or plan and in the applicable `checks`, task
`completion` or `compatibility`, or PR `rollout`. The controller validates its
existing structural and bookkeeping invariants; this guide adds no remote
issue-status gate and does not make the controller prove reported operational facts.

## Conditional candidates

Separate selected increments from candidates needed only if investigation
establishes a condition. For each conditional candidate, record the question
or predicate, the evidence needed, the bounded investigation, and what would
retain, replace or remove the candidate and its dependency edges. Lack of
evidence means unresolved, not unnecessary.

Resolve the condition before the candidate enters an approved executable
manifest. Keep unresolved candidates and rejected alternatives in the
human-readable design, not as optional tasks or conditional edges: schema 1 has
no runtime conditional tasks. Do not omit a required outcome to make the
executable plan look complete. If discovery itself needs implementation, scope
and approve that bounded increment separately; its result informs a later plan
rather than authorizing it.

If later evidence changes approved scope, record a proposed revision for the
existing plan and manifest approval process. Do not rewrite an active manifest,
mark unperformed work complete, skip required checks, or assume a replacement
plan can be spliced into an existing run. Preserve prior evidence and consumed
allowances. Continue unaffected authorized work where the controller permits;
do not introduce a blanket pause.

## Feature-flag decision

For every plan, answer both questions with reasoning and evidence:

- Does the repository have an applicable flag or configuration mechanism?
- Should this work use it? Record `use`, `do not use` or `unresolved`.

Reassess per increment where rollout needs differ. Use the established
mechanism when it fits. Runtime rollout flags, build-time switches,
configuration and authorization checks are not interchangeable. Do not add a
second flag platform to make splitting possible. When no suitable mechanism
exists, compare an unflagged compatible change, a single PR, and the cost of a
minimal repository-appropriate mechanism. New infrastructure is an explicit
design decision, not an assumed supporting change.

For flagged work, specify:

- Purpose, evaluation boundary, owner, environment defaults and supported states.
- Disabled behavior, including no unintended writes, network calls, scheduled
  work or dependency initialization.
- Enabled behavior, partial-deployment compatibility and behavior when
  evaluation is unavailable.
- Tests for disabled and enabled paths and relevant transitions or interacting flags.
- Activation prerequisites, observable success and failure criteria, rollout
  stages and rollback.
- Whether rollback only changes routing or also needs compensation for
  persistent side effects.
- Removal conditions and accountable cleanup for the flag and the old path.

Preserve the original path while staging new behavior, without copying the
whole implementation. Prefer one clear, narrow decision boundary; limit
interacting flags and document invalid combinations.

Flags do not make destructive schema changes reversible, replace access
control, or justify leaving a known security defect active. Default-off often
suits incomplete runtime behavior, but repository policy and the actual change
determine defaults.

## Issue structure

Splitting PRs does not automatically require splitting issues.

Keep a small, cohesive design in one parent issue when its increments are easy
to understand together. Create or reuse native sub-issues when an increment has
independent value, substantial scope, its own detailed design or acceptance
criteria, separate ownership or lifecycle, or enough detail to make the parent
hard to use. Default to one substantial PR increment per child when separate
tracking is justified. Several small PRs can stay as explicit parent sections or
belong to one milestone issue, with a clear mapping. Prefer a flat
parent-to-increment structure; add a phase issue only when grouping materially
improves comprehension.

The parent owns the objective, cross-cutting design, invariants, scope and
non-goals, dependency overview, increment index, shared decisions and
end-to-end completion criteria. Each child owns its bounded outcome, local
design, exclusions, dependencies, acceptance, compatibility, and flag, rollout,
rollback and cleanup details, plus unresolved questions. Link shared decisions
rather than copying them into conflicting sources. A child must be assignable
without relying on chat history.

Hierarchy describes containment; dependency links describe ordering. Neither a
list order nor a parent-child link replaces explicit plan and manifest dependencies.

When GitHub publication is authorized:

- Inspect and reuse existing issues before creating anything.
- Create the native parent-child relationship, not only a textual reference:
  https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/adding-sub-issues
- Record `blocked by` or `blocking` relationships where useful, consistent with
  the plan:
  https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/creating-issue-dependencies
- Link each PR to the issue or increment it actually completes. A closing
  keyword closes its issue when the PR merges into the default branch, so do not
  use one for the parent on a partial PR. Record each PR's linked issue and
  whether that PR may close it in the manifest `constraints`, which the workers
  that write PR descriptions read:
  https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue
- Verify created issues and relationships. On retry, reconcile existing results
  instead of creating duplicates.
- If relationship creation is unavailable, keep the authorized design durable,
  record the incomplete relationship and its cause, and continue unaffected
  work. Do not claim a hierarchy exists or move a child from another parent.
- Stay within the selected repository, destination and visibility. Never copy
  private reference material into a public issue.

Other planning providers keep the same decomposition reasoning without GitHub.
Selecting a destination does not grant unrestricted publication permission.

## Decision record

The design exposes these records. One concise paragraph can satisfy several of
them for a simple change. They are human-readable planning concepts, not
manifest fields.

| Record | Required meaning |
| --- | --- |
| Delivery recommendation | One PR or several; reasons for the selected boundaries and material rejected alternatives. |
| Increment map | Stable ID, goal or value, scope, proposed PR, issue or parent section and whether that PR may close it, true dependencies, and safe post-merge state. |
| Boundary contracts | Producers, consumers, shared authoritative contract, compatibility obligations and checks at each meaningful split. |
| Prerequisite evidence | Required outcome and evidence source per dependency, its revision or environment, and handling of cancelled or replaced prerequisites. |
| Conditional candidates | Predicate, investigation and evidence, retain, replace or remove decision, affected dependencies, and whether it was resolved before approval. |
| Flag decision | Evidence about the existing mechanism; `use`, `do not use` or `unresolved`; defaults and lifecycle where applicable. |
| Verification and operations | Per-increment checks, compatibility, deployment and activation prerequisites, rollback and cleanup. |
| Issue decision | Why children are useful or unnecessary; parent and child responsibilities and dependency relationships. |
| Uncertainty | Open question, affected increment, provisional assumption, consequence if wrong, and whether resolution is needed before implementation or activation. |

A compact record for a small change:

```markdown
Delivery: one PR. The fix and its regression test are one atomic correction;
a separate test-only PR would add review cost without independent value.
Flags: the repository uses environment-based runtime flags (see its flag
module); do not use one, because the fix restores documented behavior and
reverting the PR is the rollback.
Issues: track under the existing bug issue; no child issues.
Prerequisites, contracts, conditions: none.
Uncertainty: none that affects implementation.
```

The [CONTRACT.md](CONTRACT.md) section on planning records maps these records
into existing manifest fields.

## Examples

Generic planning outcomes for common situations:

| Situation | Defensible outcome |
| --- | --- |
| Small cohesive fix | One PR with explicit no-flag reasoning and no child issues, as in the compact record above. |
| Existing-feature improvement plus a larger new feature | Ship the standalone improvement first when it has value on its own, such as faster search results that help even if a new search mode never ships. State that value and keep the larger feature in later increments. |
| Additive preparation without immediate user value | A separate PR adding an optional response field is acceptable when old clients ignore it, its purpose for the next increment is concrete, and leaving it unused if the project stops is harmless. Without that compatibility evidence, keep it with its consumer. |
| Useful slices with strict dependencies | Split a storage layer, an API and a UI that each have useful checks even though each waits for the previous human merge. Show the merge graph and the waits, and size the limits for them. |
| Producer and consumer in separate increments | Record the shared interface, defaults and error behavior in the design, with producer contract checks and consumer compatibility checks. Implementation paths stay hints, and several tasks can share one issue. |
| Closed, cancelled or partial prerequisite | A prerequisite issue closed as completed is checked for its merged PR in the dependent base and, for a migration, evidence it ran in the target environment. One closed as not planned leaves the dependency unmet until equivalent evidence or a justified revision replaces it. |
| Investigation can eliminate an increment | A proposed compatibility adapter is a conditional candidate. If the existing supported API already serves the consumer, record that evidence, remove the adapter and its edge before approval, and keep the decision in the design. |
| New evidence changes an approved increment | Keep the active manifest and completed work. Record a scope-revision proposal for the existing approval process, continue unaffected authorized work, and do not invent skipped or conditional tasks or a blanket pause. |
| Existing suitable runtime flag | Use it for incomplete user-facing behavior: explain that the disabled path preserves current behavior without new writes or calls, how staged activation and rollback work, and when the flag and old path are removed. |
| No suitable flag system, or uncertain evidence | Record where you searched and what remains unknown. Compare an unflagged compatible change, one PR and a minimal mechanism, and do not add infrastructure or claim absence without investigation. |
| Destructive migration or mixed-version consumers | A flag is not sufficient. Use an expand, migrate and contract sequence with documented rollback limits, or keep the change atomic. |
| Large project with substantial increments | Create or reuse native child issues for increments with their own design and acceptance, each with a bounded brief, links to shared parent context and explicit dependency edges. |
| Several small PRs with little separate design | Keep one readable issue with an explicit section per PR instead of creating children mechanically. |
| Existing children, partial publication failure or private source | Reuse existing children, report any relationship that could not be created with its cause, keep private details out of public issues, and continue unaffected work. |
| Non-GitHub provider or unresolved decisions | Keep the selected provider and its native structure. Record open questions with provisional assumptions and continue authorized design instead of forcing GitHub or interactive questions. |
| Enhanced planning disabled | Prepare uses its baseline step without this guide. Skill activation, reviews, audits, compatibility obligations and native permissions are unchanged. See [SKILL.md](SKILL.md). |
| Already authorized execution | Recorded in `constraints` under [SKILL.md](SKILL.md) Prepare step 6, covering only the publication permissions, model choices and finite limits it names, without a separate trial approval, repeated hash or invented budget prompt. This applies whether or not this guide is enabled. |
| Actual capability failure, or offline checks without end-to-end evidence | Report the failed operation, its evidence and recovery, or state the precise coverage limit, under [SKILL.md](SKILL.md) Execute. Never fabricate capability evidence. |
