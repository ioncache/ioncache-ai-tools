# Category-isolated review design

Status: source implementation and offline validation are complete after the
focused design corrections passed review. Native model/host acceptance and
matched review-quality trials remain unverified.
Code baseline: `aaa0197fcd5cd568cf65f47924817ca962ba16a2`.

The earlier design's five reviewed corrections did not establish readiness.
Further review exposed a reproducible ledger failure and unresolved contracts.
This revision replaces generation tracking with simpler assignment records,
separates review configuration from skill activation, and specifies the required
ledger behavior change. Offline implementation checks are not proof of native
instruction isolation or review-quality improvement.

## 1. Purpose and boundaries

The unit of review is a category, not a directory. Each enabled general category gets
a fresh worker and one category-specific instruction set across the requested
scope. No worker reviews security, documentation, and complexity together.
Separate headings or reports do not create separate reasoning contexts.

Change reviews cover introduced or worsened behavior in the pinned change.
Repository and explicit path/file reviews also include unchanged files within
their requested scope. Every worker receives the whole candidate-file inventory,
checks its own applicability, and reads necessary callers and implementations.
An explicit language prerequisite is resolved from source evidence before
dispatch; JSDoc is JavaScript-only. Remaining file-level applicability is a
worker outcome, not a predicted-value shortcut. Missing a dedicated language
guide does not remove general review responsibilities.

No inline, small-change, predicted-value, or desired-agent-count exception.
Observed concurrency limits queue assignments rather than combine categories.
Source evidence and discoveries may overlap across independent categories;
their instructions and discovery conversations must not be pooled.

The caller/coordinator prepares instructions, schedules, and collects. It does
not perform category reviews or adjudicate findings. A separate adjudicator
assesses original evidence; its own discoveries require fresh validation.
Missing evidence prevents a complete review, not other authorized work.
Do not introduce a permission fence or persistent worker-authorization state.

The original reference used instruction-file-first passes across all applicable
files, followed by correctness. Preserve that category-first intent. Modern
project and shipped sources for the same category form one effective instruction
set; they are not competing reviewers with conflicting defaults.

References:

- https://blog.cloudflare.com/ai-code-review/
  Adopt its specialist sessions and consolidation, not reduced-risk shortcuts.
- https://claude.com/resources/articles/building-agents-when-to-fold-subagents-into-your-main-agent-loop
  Keep useful generic composition and avoid unnecessary handoffs; independent
  verification remains an intentional fresh-context use case.

The reported API/frontend roster is an acceptance counterexample, not proof of
which cached or local skill produced it. No consuming project is to be modified.

## 2. Categories, sources, and configuration

Add a small `skills/review-code/categories.json` catalog with stable category
IDs, their canonical instruction paths, declared applicability, and feature IDs.
Canonical domain standards live under `skills/review-code/categories/`.
Existing writing skills reuse their corresponding domain standards without
loading the review workflow, read-only protocol, or reporting machinery.

| Category | Required concern |
| --- | --- |
| `security` | Stack-neutral trust boundaries, authorization, untrusted input, injection, secrets, unsafe disclosure, and relevant cryptographic/transport contracts. Framework examples are conditional, not the applicability test for the category. |
| `code-complexity` | Responsibility, parameters, nesting, and structural complexity, with concrete maintenance consequences rather than metric-only fix demands. |
| `comments` | Necessary implementation rationale and accurate native API documentation, with distinct rules for their different purposes. |
| `jsdoc` | JavaScript-only documented parameter/return/error contracts and JSDoc conventions; not TypeScript. |
| `unit-tests` | Framework-adaptive assertion quality, isolation, mocking and cleanup; Vitest conventions apply only to actual Vitest suites. |
| `documentation` | Consequential accuracy of usage/operational documentation and existing writing conventions. |
| `design-coherence` | Objective fit, responsibility ownership, justified abstractions, and coherent compatibility decisions. |
| `correctness` | Functional results, error paths, state, cleanup, modes, and operation completeness. |
| `integration` | Actual producer/consumer contracts, moved/shared code, and asynchronous handoffs end to end. |
| `privacy` | Personal-data collection, use, logging, disclosure, retention, and deletion against documented purposes and obligations; no invented legal requirements. |
| `performance` | Credible latency, throughput, memory, I/O, repeated-work, and scaling regressions under supported workloads. |
| `test-coverage` | Meaningful assertions for changed behavior across the project's actual languages and frameworks, including Python self-checks and E2E tests. |

Each shipped category has an independent, default-enabled `review-<category>` key in
`config/defaults.json`. These are separate from `skill:<name>` activation keys.
`skill:review-code` still disables the overall workflow; the surrounding loop's
skill switch and `review-auto-model-selection` remain independent.

Disabling `skill:documentation-writing`, `skill:security`, or
`skill:engineering-judgment` must not silently remove review coverage that
correctness provides today. No category invokes a disabled writing skill.
Its separately enabled review feature uses the canonical domain instructions.
Document these distinct controls and test migration with pre-existing disabled
skill values. Review coverage changes only through explicit review-category
settings, approved scope/exclusions, or an explicitly changed requirement.

Use the current settings resolver, project cwd, cross-host disable semantics,
and read-only option normalization. Do not infer category switches from
similarly named skill keys or create a second configuration precedence engine.

### Project standards

Inventory project sources and their `applyTo`, scope, references, and exceptions.
Map each independently named standard to its review category, retaining sources
and provenance. Same-category project rules join that category's packet;
a genuinely additional purpose gets a separate category and worker.
Neither source count nor directory count determines worker count.

Additional project categories belong to the request's effective registry, not
the shipped configuration catalog. The caller records a stable `project:<slug>`
ID, title, complete bounded instructions, source identity, applicability, and
exceptions. IDs must be unique and remain unchanged across a phase and its
resume. Same-purpose sources join one descriptor; different purposes never do.
The effective registry combines shipped entries with these descriptors.
Prepare constructs packets from that registry and Check validates against the
same frozen registry, rather than rejecting every ID absent from shipped JSON.

Every project descriptor is required by default. An exclusion is accepted only
when the user explicitly supplied it, with its category ID and the original
instruction's provenance retained in the request. Do not invent or suggest
exclusions, ask a category-selection question, or treat predicted inapplicability
as exclusion authority. Explicit language prerequisites instead use frozen
source evidence, separately from exclusions and settings. Verified absence
omits that language-specific worker; unknown language facts leave unresolved
coverage while other categories continue. General categories are never removed
merely because a stack-specific guide is missing.
User-configured shipped review switches retain their existing independent role.
Do not create dynamic `review-project:*` settings that ordinary catalog writers
would discard. This design adds no persistent project-category settings format.

Freeze project descriptors and user-supplied exclusions in the phase plan and
its existing ledger reason fields. Standalone requests retain them only in
their private request/handback. Settings resolution controls shipped IDs;
it neither prunes nor grants authority to request-local project descriptors.

Precedence is the host's instruction hierarchy, explicit owner requirements,
applicable project conventions/exceptions, then shipped defaults. Within project
sources, follow their declared scope and precedence, not an invented ordering.
For example, a project's API-test location overrides shipped colocation advice
for those tests. Do not dispatch a second worker to enforce the opposite default.

Preparing this inventory and recording precedence is not a code-review pass.
The category worker interprets its same-purpose rules and determines path
applicability. Unresolved equal-authority contradictions require investigation
of the referenced requirements and an explicit coverage limitation if unresolved;
no actor silently chooses the easier rule.

Mixed documents supply complete category-specific sections, not their entire
multi-purpose checklist. A source-to-category mapping is recorded once per
phase and reused on resume. Re-discovery producing different prose is not new
authority. Reviewed instruction edits cannot silently weaken approved rules.

### Mixed-version configuration limitation

An older installed writer removes keys absent from its catalog. A later new
writer then restores their default values, losing a new explicit opt-out.
This was reproduced using the current `plugin_config.reconcile` function.
Adding keys to the new source cannot fix an already running older writer.

This change does not claim mixed-version preference preservation. Deployment
must update all active copies sharing these settings before initializing the
new review switches; preserve and verify explicitly chosen settings through
that rollout. Document this prerequisite in configuration/development guidance.
Do not add an opaque backup or competing settings store to hide the limitation.
Mixed-version support, if required, needs a separately approved migration design.

## 3. Skill cleanliness and instruction delivery

Generic skills should compose where useful. Category-specific skills must not
pull in other categories, directly or through a generic composer.

| Static source role | Current skills |
| --- | --- |
| Category-specific | `security`, `code-complexity`, `comments`, `jsdoc`, `unit-tests` |
| Composable generic guidance | `engineering-judgment`, `documentation-writing` |
| Workflow/interaction | `answer-questions`, `create-worktree`, `investigate`, `post-pr-review-comments`, `prompt-output`, `review-code`, `review-dependabot-pr`, `review-triage-loop`, `review-validate-fix-loop`, `triage-errors`, `verify-unresolved-pr-comments`, `write-pr-descriptions` |

Keep this classification as static catalog/test metadata. It is not a runtime
agent-role database or an authorization mechanism. Audit all shipped skills,
their explicit load directions, and referenced resources. Test the registered
category sources for cross-category links and composer back edges; manually
review prose dependencies that a reference check cannot classify.
No general-purpose dependency-graph framework is needed.

Generic engineering judgment may call complexity or security when appropriate.
Complexity must not call back into the generic composer and thereby acquire
security instructions. Remove the existing reverse load in
`skills/code-complexity/SKILL.md`; do not just move it to another wrapper section.
Preserve writing-specific execution steps, such as running edited tests, in
writing wrappers rather than a review worker's authority.

Update category-skill activation descriptions too. Reading an API function for
complexity must not automatically activate security because the file is an API.
For bounded review assignments, applicability follows the assigned category,
not incidental source content. Generic work can still select relevant skills;
a supplied review packet needs no additional writing-wrapper load.

### Mandatory correction to existing guidance

The engineering-judgment reminder currently reaches `SubagentStart` through
`guidance.py`; the same policy also reaches session/prompt events. Changing it
is required, not "if necessary".

Make the existing reminder and generic skill activation wording say that
planning, implementation, and unassigned design work may use generic composition,
while an already assigned review/validation worker follows its supplied bounded
instructions and must not load a generic review checklist or another category.
This is stateless instruction wording for all event paths, not a role detector.
Keep the current hook, opt-outs, and failure behavior; add no new hook or state.

Test the actual emitted context through the shared handler and affected adapters,
including interleaved parent/child payloads. Merely removing a link from the
review packet does not remove this independent injection path.

Visible loading of a second category checklist or a generic reviewer preset
invalidates that assignment's isolation coverage. Relaunch with corrected
plugin guidance and a neutral available profile within existing authority;
otherwise return incomplete coverage and continue other authorized work.
Do not require the user to disable the plugin to recover.

Hidden host instructions are a separately disclosed observability limitation,
not proof of contamination and not proof of pristine context. Native constraints
remain binding. Claim only the instruction delivery actually observed; never
mark a known conflicting load as a harmless unknown.

## 4. Exact criterion and assessment ownership

Move each current correctness obligation deliberately, preserving its substance:

| Existing obligation in `CRITERIA.md` | Discovery owner |
| --- | --- |
| Objective fit, duplication, abstractions, responsibility ownership | `design-coherence` |
| Actual argument/return/error/side-effect contracts at callers | `integration`; `jsdoc` independently checks what is documented |
| Swallowed errors, stale state/races, cleanup, mode/flag interactions | `correctness` |
| Enumeration/pagination, partial results, batch completion, retry results | `correctness` |
| Module boundaries, moved/shared consumers, events and readiness prerequisites | `integration` |
| Trust boundaries and hostile inputs | `security`, with explicit stack-neutral criteria |
| Resource use and scaling under realistic load | `performance` |
| Usage documentation, examples, stated operational/business behavior | `documentation` |
| Project-specific standards and exceptions | Their named category, not a second correctness sweep |

Each owner can read all evidence needed for its purpose. This is not a ban on
correctness reading callers, or on two categories finding the same issue.
The integration worker discovers its own producer/consumer edges across the
whole scope; no obsolete directory-owner map or invented upstream edge producer
is required. Its report records traced and missing boundaries.

The existing security skill already has general principles; saying it contains
no applicable Python guidance is too strong. Nonetheless, the new security
standard must explicitly cover non-web/Python command, file, authorization, and
secret-handling boundaries instead of treating Fastify examples as universal.

### Separate discovery from assessment

- `PROTOCOL.md`: scope, read-only authority, source evidence, identities,
  limitations, and result format. No documentation or test discovery checklist.
- Category files: only that category's discovery criteria and applicability.
- `assessment/COMMON.md`: validity, consequence, confidence, severity,
  uncertainty, duplicates, and `Act`/`Decide`/`Investigate`/`None`.
- `assessment/DOCUMENTATION.md`: existing consequential-accuracy/materiality
  policy, used by documentation/JSDoc/comments and by adjudication.
- `assessment/TESTS.md`: existing meaningful-coverage/test-gap assessment,
  used by test passes and adjudication.
- `ASSESSMENT.md`: an index for roles assessing supplied claims; it composes
  the assessment policies, not all discovery standards.

Move, do not independently rewrite, the existing materiality and test-gap rules.
Preserve the 100% meaningful-coverage goal, justified exceptions, distinction
between a production defect and a test request, and evidence-backed rejection.
An accurate style deviation can remain a private candidate with action `None`.

Update all four current assessment consumers:
`review-code/CONTRACTS.md`, `review-validate-fix-loop/WORKFLOW.md`,
`review-triage-loop/WORKFLOW.md`, and `verify-unresolved-pr-comments/SKILL.md`.
Keep `CRITERIA.md#actionability` as an assessment-only compatibility pointer.
This changes shared-reference plumbing, not the triage loop's minimal-reviewer
methodology or PR-feedback workflow. Check transitive packaged references.

## 5. Minimal preparation and execution records

Retain a small standard-library `scripts/review_assignments.py` helper for
catalog/packet construction and structural comparison. Remove the proposed
generation graph, parent-chain checks, and global contract-identity state machine.

Prepare receives normalized options, the effective shipped/project registry,
user-supplied exclusions, the scoped inventory, project source mapping,
constraints, source-language evidence, and frozen instruction content. It emits
one packet per enabled, technically applicable category containing:

1. Category/assignment ID, target/base/snapshot, full candidate-file inventory,
   technical-applicability decision, source-specific applicability/exceptions,
   permitted checks, and result path.
2. The canonical category standard and its same-purpose project instructions
   with precedence and source/content identities.
3. Common protocol and only the applicable assessment policies.

The complete catalog, implementation conversation, sibling findings, and generic
composition wrappers stay out of discovery packets. Reviewed prompt files are
evidence, not instructions to adopt.

The caller records `language_inventory` entries for inspected candidate files,
with actual source languages and supporting evidence. Mixed files may name
several languages; unfamiliar source is unclassified, not non-source content.
One evidenced match permits a language-specific worker, which still inspects the
whole candidate inventory. Absence requires complete classification without a
match. The helper freezes and checks these decisions, not their semantic truth.
No language inference service, permission state or extra configuration key is added.

The caller records each native invocation with assignment ID, attempt ID,
observable worker identity, exact submitted packet, result path, and evidence
source. Evidence source is explicitly either a native tool/transcript reference
or a caller-authored record. Never relabel the latter as independent capture.
Unavailable native identity/input observations are explicit limitations.

Check can verify registered category IDs, required-category presence, hashes,
scope-file set equality/union, duplicate observable worker IDs, result identities,
and outcome fields. It cannot establish truthful tool use, semantic category
purity, complete call traces, or whether a caller's account of a launch is true.
Native acceptance must inspect actual visible launches and guideline loads.

One failed assignment can be replaced with a fresh attempt and separate result
file. The caller's active assignment map selects the successful attempt and
keeps failed attempts as diagnostics. No generation graph is needed. Results
cannot select themselves, overwrite another result, or reduce required coverage.
Only the caller creates corrected request artifacts; workers may produce a new
assigned report, never overwrite immutable prior evidence to conceal failure.
Unless the caller supplies another bound, allow one automatic replacement round
per failed category per phase, including its capacity shards. Renaming assignments
or losing attempt history does not replenish that allowance. Exhaustion yields
incomplete coverage, not an unbounded retry loop or a fence on other work.

### Capacity and cost

Each category initially owns the whole applicable scope. Pre-launch sizing may
use measured input size, actual advertised context limits, and caller read limits.
That is capacity evidence; a worker does not have to fail first. If no reliable
bound is known, disclose the uncertainty rather than inventing one.

When necessary, shard within one category, retaining its identical instructions,
fresh contexts, complete file-union coverage, and end-to-end relevant traces.
The specialist owns semantic trace completeness; set arithmetic cannot prove it.
An indivisible file/trace beyond allowed capacity remains incomplete.
Concurrency alone is handled by queuing, not sharding or bundling.

With all 12 categories enabled and JavaScript evidenced, a phase needs at least
13 workers in flat mode (12 specialists plus adjudicator), or 14 in nested mode
(also a coordinator), before extra project categories, validators, retries or
capacity shards. Verified JavaScript-free scope uses one fewer worker per phase.
Full/focused/full confirmation applies each phase's own language evidence rather
than assuming a fixed total.
This is a stated consequence of isolation, not a target count or hidden budget.

Keep `auto -> specialists`, ordering-only `sweep-first`, existing role-model and
effort controls, and fallback. Never change the parent/fixing model or settings.

## 6. Persistence, resumption, and fixed findings

Preparation does not consume review passes. Persist the prepared plan before
launching workers, using existing ledger schema-1 string fields. Phase plans use
schema 2 for language applicability; the ledger event schema does not change:

| Path | Durable record and ordering |
| --- | --- |
| Full loop review | Prepare first; include normalized options, complete phase plan and frozen category instructions in `start_review.reason`; record the event before any reviewer launch. |
| Focused loop review | After edits/checks, record `fix_done` to save the after snapshot. Read the actual correction delta, prepare the focused plan, and persist it through an internal `stop`/`resume` checkpoint before launching workers. |
| Orderly interruption or same-phase plan revision | Record the complete current plan, attempt map, available evidence, change reason and consumed allowances in the existing `stop.reason`; `resume` retains the phase and counts. |
| Completed coverage | Preserve complete pass records in `review_done` or `fixes_reviewed`, and assessments in decision evidence. |
| Standalone review | Private request/results for this invocation, not a ledger. Do not add or advertise a standalone cross-session resume feature. |

Frozen instructions and requirement mappings must be recoverable from the
ledger, not only paths/hashes into disposable scratch. Native acceptance exposed
that `diff` cannot read the after snapshot before `fix_done` saves it. An earlier
fixture accidentally supplied a before-to-before empty diff. The corrected
sequence uses the existing stop/resume checkpoint, preserves the counted cycle,
and verifies the actual changed content without private prompt files.

An abrupt interruption may lose unrecorded attempts. Recover only evidence
whose identity and native completion can be established. If it cannot be
recovered, do not invent successful coverage or refund spending. Use counted
reconciliation/re-review within remaining allowances, or return incomplete.
This is deliberately simpler than adding an open-phase checkpoint event/store.

### Changes on resume

Resume checks current authority, explicit options, category enablement, and
the saved phase plan. Disabling a category cancels its outstanding obligations,
records the explicit exclusion, and does not invalidate unrelated completed
coverage. A writing-skill toggle has no effect on review categories.

An installed plugin's byte change or a differently phrased inventory is not
itself new review authority. Reuse the frozen phase instructions; apply updated
standards at the next full phase, or earlier when the owner explicitly requires
them. Hashes verify artifact identity, not semantic compatibility.

Newly classified files may extend language evidence in an open phase, preserving
existing classifications, packets and consumed attempts. Wrong or deleted
existing classifications require counted reconciliation, not a quiet rewrite.
Old schema-1 plans retain their evidence and counts but cannot be reinterpreted
as satisfying the new applicability contract; use the existing new-phase path.

Adding required coverage during an open review phase permits a revised recorded
plan within that counted phase: persist it through the existing stop/resume pair
before launching added assignments. Recover the latest recorded complete plan,
not only the first recorded plan for that phase. Do not replay completion
events or refund consumed allowances.

If coverage is already closed, or prior coverage is known to violate isolation,
use counted reconciliation and a new full review, after settling any applied
outcomes as follows. While `fixing`, use existing fix recovery first. In
`validating_fixes`, independently validate each still-applied correction before
reconciliation discards its current-cycle verification route. Use valid focused
evidence or fresh outcome-validation evidence under the same snapshot, authority,
and passing-check requirements. Record those decisions in the existing fields;
they do not amend or certify invalid category coverage.

This ordering preserves a legitimate prior fixed decision for reconfirmation.
When a language contradiction or legacy plan prevents `reviewing_fixes` from
closing, do not fabricate focused completion to obtain that decision. Retain
the applied cycle and reconcile within remaining outer capacity. A fresh full
review can provide first verification only for the latest applied cycle in an
invalidated loop, with no completed focused review, unchanged after snapshot,
passing fix/current checks, and no newer superseding decision. Record fresh
independent outcome evidence. Original partial coverage and counts stay intact.

Neither route allows "applied" alone to become "fixed". If the snapshot, required
checks, authority, or outcome evidence cannot support verification, leave the
review incomplete rather than manufacture a fixed history or another edit.
That outcome does not fence other authorized work.

At exhausted capacity, return incomplete; do not use reconciliation to evade
an exhausted correction budget or grandfather invalid coverage. Terminal
non-resumable runs remain historical, not automatically reopened.

### Required ledger correction

Current `reconcile` sets every finding to pending/open, including verified fixed
findings. `decision(... fixed)` then rejects them in `validating`. A real CLI
probe reproduced this twice without file drift; ordinary confirmation completes.
The previous design was wrong to describe this as a documentation-only recovery.

Extend `review_loop_state.decision` narrowly, preserving all current event-field
and value validation. A read-only full-review reconfirmation may set `fixed`
in `validating` only when:

- The finding's last prior decision was a verified `valid`/`fixed` resolution.
- Its current validation is pending after invalidation.
- A fresh full review has completed and its required checks passed.
- Fresh independent assessment and evidence establish that the same resolution
  still holds. A known recurrence instead becomes valid/open for a real fix.

The guarded interrupted-focused route above additionally supports first
verification after fresh full coverage; it does not accept application alone.
Never-applied, failed, superseded or drifted outcomes remain rejected.
Keep normal current-cycle fix validation unchanged. Reconfirmation consumes
the already counted full review, not another file edit or artificial fix cycle.
The ledger validates recorded prerequisites, not the truth of that assessment.

An in-memory transition prototype using real CLI-produced histories completed
this route with two outer reviews and one real fix cycle. Negative controls
rejected never-fixed, applied-only, and failed-current-check cases. This is
design evidence only; implement real CLI regression tests before the code fix.
Also test a real recurrence, invalid event values, exhausted limits, and fixing.
Include interruption after `fixes_reviewed` but before fixed decisions: settle
applied outcomes, reconcile added coverage, reconfirm, and complete without an
extra edit. The negative case must stay incomplete when required outcome
evidence is unavailable, rather than misclassifying the finding.
Also exercise language/schema retirement before `fixes_reviewed`: fresh full
verification closes the applied outcome at the unchanged snapshot without
another edit. Failed fixes/checks, intervening drift, later reopening and outer
exhaustion must still reject completion.

Event shapes stay schema 1, but older helpers will not understand the new legal
transition. Do not claim backward runtime compatibility from an unchanged schema
number. Resume these histories with the updated helper, preserving all counts.

## 7. Acceptance with distinct evidence levels

### Offline, deterministic tests

No models run in self-checks. Tests below establish structure or bookkeeping:

| Case | Discriminating assertion |
| --- | --- |
| Catalog, scopes, and tiny input | Expected general and evidenced language-specific IDs, with the whole candidate inventory in every dispatched packet. |
| Technical applicability and recovery | Python/TS-only scopes omit JSDoc without losing generic coverage; mixed/embedded JavaScript dispatches it. Unknown facts remain incomplete, then resolve by extending the same phase without replay or refunded attempts. Changed frozen facts and old plan schemas require a counted new phase. |
| Old skill opt-outs versus new review switches | Old disabled writing skills leave coverage enabled; each explicit review switch removes only its category. |
| Same-category project rules | One packet/worker obligation with recorded project precedence, not conflicting duplicate defaults. |
| Additional project categories | A request-local descriptor survives Prepare/Check and ledger-plan round trips without a shipped feature key. Explicit language prerequisites use source evidence; general purposes remain required unless explicitly excluded. No selection prompt or generated exclusion. |
| Packet and source hygiene | No bundled standards, generic composer references, or unrelated assessment modules in constructed packets; all source references resolve. |
| Startup/prompt/child guidance | Actual handler/adapter output no longer directs bounded workers to load generic review guidance; skill activation descriptions constrain bounded roles; opt-outs and question recovery remain independent. |
| Structural records and replacement | Wrong IDs, changed packets, reused known worker IDs, missing reports and file-union gaps are rejected; valid replacement preserves prior evidence. |
| Exhausted replacements | Initial failure followed by failure of the one allowed replacement leaves incomplete coverage and immutable diagnostics. Attempt counts remain consumed through resume, renamed assignments, and capacity shards. No further replacement is accepted; other authorized work remains reachable. |
| Persistence and interruption | Actual CLI plan recovery from full/focused event fields with scratch unavailable; counts and authority are not reconstructed from guesses. |
| Fixed-finding reconciliation | Actual CLI reproducers complete without another edit: settle completed focused outcomes before reconciliation, or first verify interrupted applied outcomes after fresh full coverage at the unchanged snapshot. Negative controls remain rejected. |
| Ordering/options | Same category coverage for both strategies; preserve help, role choices, fallback and resume provenance. |
| Old/new config writers | Explicitly reproduce the unsupported mixed-version key loss and verify the documented single-catalog rollout. Do not mark key loss as fixed. |

These tests do not prove a model read every file, applied a policy correctly, or
obeyed a packet. Mocked launch records remain mocks.

### Native lifecycle matrix

Before execution, pin the actual source roots, supported topology per host,
fixture inputs, permissions, and allowed model settings. The required host set
is Claude Code, Codex, and Copilot CLI; unavailable hosts are unverified, not
implicitly passed. No undocumented mode flag or alternate runner is assumed.

For each available host, run two repetitions of:

1. Standalone composite multi-directory review.
2. Standalone tiny-change review.
3. One bounded full/focused/interrupted-resumed/final-full review-fix sequence,
   using only authorized disposable fixture edits.

Use its observed supported topology. Exercise the alternate flat/nested topology
on one supporting host, twice, or report that path unverified. Record the exact
host/mode/phase matrix. Include controlled single-slot queuing and changed-plan
recovery; label simulated constraints and do not call them observed host limits.
Do not exceed explicitly authorized spending to complete this matrix.

Include a bounded failed-replacement scenario in both repetitions on one
supporting host: fail the initial attempt and its allowed replacement, inspect
the actual launch count, and demonstrate that unrelated authorized work can
continue. Do not infer this behavior from synthetic attempt records alone.

On one supporting host, force same-category capacity sharding in both
repetitions. Put a producer and consumer in separate shards, with one supported
cross-boundary defect and a negative control whose prerequisite is guaranteed.
Require the expected result from original worker evidence, not only complete
file union. Include an indivisible over-capacity trace that remains incomplete.
Use explicitly simulated capacity where necessary and label it as such.
If either native scenario cannot run within available capabilities or spending,
record it as unverified rather than substituting a passing offline assertion.

Inspect original native launch inputs, visible skill loads, distinct worker
identities, original reports, and scope evidence, not just caller summaries.
Known cross-category loading, missing categories, incorrect project precedence,
or bundled context is a failed trial. Incomparable or unobservable required
evidence is an explicit gap, not a successful mechanical check.

### Category and quality controls

Q01-Q10 are now exposed regression/calibration material, including Q10. Do not
call them held out after using their answers to design these changes. Change
their split documentation accordingly. A new held-out set, if used, must be
independently authored and withheld; no generalization claim is required here.

The protected regression set is all existing Q01-Q10 plus one applicable case
and one negative control for each category below. Independently validate source,
expected private candidate behavior, and final action before native trials.
Strip oracle fields and labels from reviewer inputs.

| Category control | Applicable case / negative control |
| --- | --- |
| Security | Python authorization or untrusted-path failure / enforced boundary |
| Complexity | Structure with a concrete maintenance hazard / cohesive code exceeding a numeric preference |
| Comments | Misleading current operational rationale / inconsequential historical note |
| JSDoc | Documented type misleading a real caller / accurate nonpreferred type formatting |
| Unit-test quality | Assertions or mocks hiding a supported failure in the actual framework / meaningful native assertions without imported Vitest conventions |
| Documentation | Consequential wrong operational command / harmless historical wording |
| Design coherence | Duplicated ownership producing incompatible rules / justified abstraction |
| Correctness | Incomplete enumeration or swallowed failure / complete supported behavior |
| Integration | Readiness before a consumer prerequisite / prerequisite actually guaranteed |
| Privacy | Processing contrary to an explicit purpose/retention contract / compliant processing without invented legal obligations |
| Performance | Evidenced repeated-work growth at supported volume / bounded inconsequential work |
| General test coverage | Unasserted supported behavior in Python/E2E/Vitest / meaningful existing protection |

An applicable style observation may correctly remain a private candidate with
action `None`. In particular, a comments worker may notice Q05; it is a false
positive only if promoted into a reportable cleanup/fix. Record discovery and
adjudication separately so Q10 cannot be missed behind an otherwise good filter.

Run two matched old/new trials per protected case with fixed authorized
settings. At most one extra matched trial is allowed for disagreement, declared
before its result. No prompt changes or favorable-result retrying mid-comparison.
A reproducible new consequential miss, actionable false positive, or loss of
justified uncertainty blocks an unqualified fixed claim. Correct it or obtain
an explicit owner disposition; inconclusive results stay unresolved.
Passing this bounded set is regression evidence, not exhaustive review proof.

Score absolute category behavior separately from relative non-regression.
Every required new-category control must meet its predeclared discovery and
adjudication expectations. Repeated equal failure by old and new is not a pass:
record failed or unverified absolute acceptance until corrected or explicitly
dispositioned by the owner. A non-regression result cannot stand in for expected
behavior. Preserve legitimate private `None` observations and the bounded
repetition rules; do not change an oracle after seeing a result.

## 8. Implementation scope and review disposition

| Area | Required work |
| --- | --- |
| `skills/review-code/` | Catalog, bounded category resources, packet/protocol instructions, separated assessment, and revised contracts. |
| Existing category/generic skills | Reuse domain standards, preserve generic composition and writing behavior, remove cross-category load paths. |
| Existing engineering guidance rule and activation descriptions | Mandatory bounded-role wording across current event paths, with adapter checks. |
| `config/defaults.json`, options and configuration docs/checks | Independent review keys, old-skill migration, explicit rollout limitation, unchanged precedence. |
| `scripts/review_assignments.py` and focused self-check | Small construction/structural checker; no generation graph or claims of native capture. |
| `scripts/review_loop_state.py`, ledger checks and protocol docs | Guarded fixed reconfirmation, pre-launch phase-plan persistence, and real CLI regressions. |
| Four assessment consumers named above | Reference migration only where their methodology is otherwise unchanged. |
| CI, review fixtures, evaluation and user/developer docs | New checks, exposed-fixture labeling, acceptance matrix, truthful cost and compatibility statements. |

No new runtime hook, external model runner, permission store, competing
configuration store, ledger event schema, model ranking, automatic publishing,
release bump, or consuming-project modification belongs in this change.

External review disposition:

| Finding | Resolution in this revision |
| --- | --- |
| R1: injected generic guidance | Mandatory correction and explicit contaminated-versus-unobservable outcomes. |
| R2: skill switches weaken review coverage | Independent review keys; preserve existing substantive coverage by default. |
| R3: same-subject project/shipped conflict | One category packet with explicit precedence and specialist applicability. |
| R4: fixed findings cannot close after reconcile | Reproduced; requires the specified code transition and real regression tests, not prose alone. |
| R5: migration and assessment leakage | Explicit ownership/consumer map and bounded policy files. The claim of zero stack-neutral security guidance was overstated. |
| R6: unavailable persistence | Prepare before existing durable events; no generation state or standalone resume promise. |
| R7: sacrificial capacity failure | Measured pre-launch capacity evidence is permitted. |
| R8: unverifiable, overbuilt record machinery | Remove generation graph; distinguish structural checks, caller records, native observations, and semantic judgments. |
| R9: ineffective acceptance/held-out leakage | Separate evidence levels, fixed matrix/repetitions, all-category controls, stage-specific scoring, and regression-only exposed cases. |
| DES1: project-category registry/control | Request-local descriptors with stable IDs feed Prepare and Check; only explicit user exclusions remove obligations. No dynamic shipped-setting keys or selection prompt. |
| TEST1: replacement exhaustion coverage | Offline consumed-allowance checks plus a bounded native initial-and-replacement failure scenario with continued authorized work. |
| TEST2: semantic sharding coverage | Forced cross-shard positive/negative controls and an indivisible-trace incomplete case, distinct from queuing and file union. |
| EVAL1: equal old/new failure | Absolute expected category behavior is a separate acceptance requirement; equal misses cannot pass through relative non-regression. |
| Minor observations | Clarify static roles versus authorization state, immutable artifact ownership, unchanged-file scopes, and 13/14-per-phase cost. Mixed-version key loss remains an explicit unsupported deployment case. |

Earlier reviewer reports and the superseded draft remain private evidence.
One subsequent independent phase-contract review found the closed-focused-phase
ordering gap described above (PHASE-1). Its real-state-machine probes established
that settling applied outcomes before reconciliation retains the legal route.
This revision adds that ordering and its acceptance case. The reviewer inherited
generic guidance; this was design evidence, not a native isolation trial.

## 9. Implementation and acceptance status

The category catalog, isolated instruction packets, independent controls,
workflow integration and fixed-finding recovery are implemented. Offline checks
cover their structure and transitions. Native execution additionally exposed and
corrected malformed-result recovery, missing final-adjudicator records, and the
focused-plan ordering defect described in section 6.

Native composite execution prompted a separate check of finding validity and
assignment compliance. Its Vitest-only unit-test contract was later corrected:
non-Vitest unit-test review is not itself a scope violation. Adjudication checks
actual applicability and purpose
against frozen worker packets. A true defect found through an out-of-purpose
review does not complete that category. The caller preserves its report,
deactivates the rejected coverage and uses the existing replacement allowance.
This adds no ledger fields or permission state.

The subsequent applicability audit corrected five issues: evidence-backed
language-specific dispatch, JavaScript-only JSDoc, framework-adaptive unit tests,
conditional security APIs, and native API documentation distinct from why-only
implementation comments. Current contracts and prospective expectations reflect
those corrections. Original native reports and frozen scores remain unchanged;
they do not establish native compliance with the revised standards.

Acceptance is not an unqualified pass. The bounded quality comparison preserved
all expected core actions but regressed severity and subsidiary claim support.
Claude completed two larger lifecycles with exceptions. Copilot encountered
native approval and instruction-contamination failures; Codex exhausted account
usage during final coverage. A targeted native loop verified the corrected
focused checkpoint. Capacity and full alternate-topology evidence remain
unverified.

See [review-evaluation.md](review-evaluation.md) for the frozen comparison,
observed outcomes and limitations. Neither passing design reviews nor successful
bookkeeping closes those remaining semantic and native acceptance gaps.
