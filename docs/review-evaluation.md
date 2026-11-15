# Evaluating review changes

Mechanical option and ledger checks do not measure finding quality or prove
native model routing. Use
[../scripts/fixtures/review_quality.json](../scripts/fixtures/review_quality.json)
for a bounded, synthetic comparison without private application source.

All Q01-Q10 cases have been exposed. They are regression/calibration material,
not held out. The additional per-category positive and negative controls are
also exposed calibration material.
`stack_applicability_controls` adds native Python/Node tests, mixed-language
JSDoc, Python identifier handling and Go API documentation pairs. These are
prospective exposed controls, separate from the frozen comparison below.
The offline mutation check validates that the Python/Node assertion controls
distinguish broken production behavior; it does not score model responses.
Its expected claims are acceptance hypotheses, not proof. Have an independent
reader validate them against the supplied source and reference contracts before
scoring. Do not expose `expected`, `reject`, or split labels to reviewers.
Do not tune instructions against held-out results and then call the same cases
held out in a later comparison.

Validate expected controls independently before a live trial. Do not expose
category labels or expected claims/actions while creating a discovery input.
Standard-only positives may expect a private `None` observation; preserving
one is not an actionable false positive. In particular, Q05's historical
comment can produce a comment-standard candidate that adjudication maps to
`None`, without a human cleanup row.

Use native fresh contexts, not an external model runner. Give old and new
instructions the same input identities, role/model settings, tool permissions,
and finite review budget. Pin model choices only when authorized and supported.
Record requested and observable actual models separately; unknown identity or
different routing limits the comparison. Keep implementation context, expected
answers, and prior review outcomes out of both review contexts.

Match outputs to the underlying trigger, incorrect behavior, and consequence.
Measure actionable precision, consequential misses by severity, false positives
on negative controls, and justified uncertainty separately. Raw finding counts
and a shorter report alone do not show improvement. Do not penalize a reviewer
for preserving a genuinely unresolved consequential premise as `Investigate`.

Store raw reports, input/instruction identities, model observations, and scoring
decisions in private session artifacts. A single small comparison is a smoke
evaluation, not a general quality guarantee.

## Category-isolation acceptance

Offline checks inspect packet contents/dependencies, emitted adapter guidance,
configuration, full file union, bounded replacements and real ledger transitions.
They use fake records, never model launches. A fixture returning `complete`
does not demonstrate model compliance or semantic trace completeness.

Native trials separately inspect visible tool inputs, identities, guideline
loads and original reports, using fresh source-loaded Claude Code, Codex and
Copilot CLI sessions. Unsupported or unavailable paths remain unverified.
Record observed native data separately from caller-authored metadata.
Known generic/cross-category instruction loading invalidates that assignment;
hidden context is an observability limitation, not evidence of pristine context.

Include technical applicability and native-stack controls, not just applicable
positive/negative cases:

- JavaScript-free Python and TypeScript targets launch no JSDoc worker while
  retaining general documentation, contracts and unit-test quality.
- Mixed targets, including embedded scripts, apply JSDoc rules only to actual
  JavaScript. Unknown language facts defer that worker without completing the
  review or stopping other categories; later evidence resolves the same phase.
- Unit-test review finds meaningful assertion, mocking and isolation defects in
  Python unittest and Node's built-in tests. Valid native naming and lifecycle
  conventions must not trigger Vitest-only requirements.
- Native database APIs remain valid under generic security guidance; unsafe
  validation or swallowed operational failures still warrant findings.
- Accurate native API documentation remains valid even when it explains what
  the operation does; materially misleading caller contracts still warrant findings.

The earlier Vitest-only non-applicability expectation was incorrect for the
intended product. Adjudication still checks purpose compliance, but reviewing
non-Vitest unit tests is not itself a scope violation. Preserve the original
trial records; do not rewrite them into passes under the corrected contract.

Run two predeclared repetitions of each required composite and tiny-file case,
and a bounded full/focused/interrupted-resumed/final-full sequence on each
supported host. Exercise all 12 categories on applicable inputs, plus
JavaScript-free cases that omit JSDoc by evidence. Include same-purpose scoped project
overrides, an additional project category, user-only exclusion provenance,
writing-skill opt-outs and independent category settings.
Concurrency restrictions must queue the roster rather than pool purposes.
Exercise the alternate supported topology twice on one host, or record it
unverified. Do not invent limits, exceed authorized spending or use an external
model runner to compensate for unavailable native delegation.

On one supporting host, twice, include these discriminating sequences:

- Fail an initial category attempt and its allowed replacement. Retain both
  records, keep unaffected work, interrupt/resume without refunding allowances,
  and leave that category incomplete after exhaustion. A permitted unrelated
  action must still succeed.
- Force measured same-category sharding over a producer/consumer boundary.
  A positive has a reachable contract mismatch that requires both endpoints;
  its negative preserves the same endpoints and workload but satisfies the
  contract. Record the actual end-to-end trace, not only the file union.
- Make one necessary file/trace indivisible under actual allowed capacity.
  Its outcome must be incomplete, without inventing partial success, a larger
  context, another review purpose or permission to exceed the bound.

Persist the frozen phase plan before launches and after legitimate open-phase
revisions using existing reason fields. Verify recovery with the private prompt
files absent. Settle applied outcomes before reconciliation, then reconfirm a
previously verified fix after fresh full coverage without another artificial edit.

## Quality verdict

Freeze the cases, instruction identities, host/topology, model settings,
permissions, budgets and scoring rules before two matched old/new trials.
Allow at most one predeclared extra trial for disagreement, not repeat-until-pass.
New labels and a full roster do not demonstrate substantive category coverage.

Score absolute expected behavior per category as well as relative non-regression.
Every required positive needs its supported candidate/action or independently
justified consequential uncertainty; negatives must not gain actionable false
positives. A missing private standard-only observation fails that category's
absolute observation control without becoming a demanded code cleanup.
Equal misses by old and new are an absolute acceptance failure, even when the
relative score ties. Unknown or unobservable outcomes are inconclusive, not passes.
Report any baseline tie without claiming a quality improvement.

### Recorded category-isolation comparison

Two matched baseline/candidate pairs ran through native Claude Code. Each full
review received 33 independent sample projects, with Q06 evaluated separately as
a rejected-candidate adjudication. An independent reader validated all 34 controls
before execution; an independent scorer then scored all 136 case-trials.

The baseline was `aaa0197fcd5cd568cf65f47924817ca962ba16a2`.
The frozen corpus SHA-256 was
`bdd53092b6f451fd0666b7d0528b12725405daa26bc6b1867a2522802d1e4f6f`.
The frozen candidate runtime digest was
`5e92c85f96e31348cbafddbcaad8a08db03e4356fa734cc39a9a7baa2ef9dff5`.
Inputs, runtime copies, original reports, permissions and configured-default
selection remained unchanged during the comparison. The host reported
`claude-sonnet-5-5`; this is a host observation, not independent backend identity
verification. No model or effort override was supplied.

| Measure | Baseline | Candidate |
| --- | --- | --- |
| Expected core final actions | 68/68 | 68/68 |
| Required actionable misses | 0 | 0 |
| Actionable negative-control false positives | 0 | 0 |
| Final severity above the frozen oracle | 10 | 14 |
| Final consequential unsupported extras | 1 | 2 |

The candidate also met all 48 named category discovery/scope controls, including
all 40 required private observations. Core action non-regression held, but this
was not a quality improvement or an unqualified pass. Severity inflated relative
to baseline, and some final answers retained unsupported timing estimates or an
additional rate-limit condition. The disagreements remain recorded. No extra
matched pair was run, and the exposed cases were not relabeled as held out.

### Recorded native lifecycle evidence

All three hosts ran from isolated source-loaded plugin copies, without changing
real installed caches or global settings. Two tiny reviews per host demonstrated
12 separate category launches followed by separate adjudication under the
then-unconditional roster. This does not validate the current language-aware
dispatch contract. Copilot needed
a new caller-owned final handoff to recover one earlier incomplete final record;
completed discovery was not repeated.

| Lifecycle trial | Observed result |
| --- | --- |
| Claude Code, repetitions 1 and 2 | Both reached `completed_with_exceptions`, using three full reviews and two fix cycles. Each had 68 fresh Agent calls without resume/model overrides. Both corrected the behavioral defects; neither changed the original tests or project instruction files. |
| Copilot, repetition 1 | Native assisted approval refused persistence of unadjudicated evidence, including the interrupted stop. The ledger remained `running` at revision 1; this was not a successful interruption. |
| Copilot, repetition 2 | Recovered the initial six attempts and added privacy, but security remained incomplete after its replacement reported host-injected cross-category instructions. Native approval also refused the final handoff and stop writes. No fixes occurred; the ledger remained `running` at revision 8. |
| Codex, repetitions 1 and 2 | Recovered, revised coverage, fixed the behavioral defects, completed focused review, settled outcomes and reconciled the roster change. Both hit the account usage limit during final full review, leaving that coverage incomplete. |
| Copilot missing-reference probes, repetitions 1 and 2 | Each initial attempt and its fresh replacement actually failed the required read. After ledger-only resume, both attempts and the exhausted allowance remained, no third worker launched, and a new unrelated continuation file was written. Both correctly remained incomplete. |

Five interrupted positive runs recovered after private request/packet/plan copies
were withheld; their initial original reports and withheld bytes remained intact.
The resumed Claude and Codex fixtures passed the behavioral checks. Copilot's
unfixed fixtures still failed the intended checks. Native approval failures were
not bypassed or reclassified as plugin permission decisions.

Acceptance exposed a focused-plan ordering defect in the instructions:
`fix_done` must save the after snapshot before the ledger can produce its
correction delta. The earlier offline fixture accidentally checked an empty
before-to-before diff. The corrected regression checks the actual changed bytes.
The workflow now saves `fix_done`, prepares from the saved delta, and checkpoints
the complete focused plan through `stop`/`resume` before any focused launch.

A subsequent targeted native Claude loop followed that corrected sequence,
completed two full reviews and one fix cycle, and preserved its original reports.
It used seven fresh launches: an initial missing-packet failure, its bounded
replacement, then independent review/adjudication roles. The failed attempt
remained recorded. This was a correctness-only workflow probe with explicit
fixture exclusions, not a replacement for the all-category matrix. The frozen
quality runtime predates the focused-workflow and assignment-compliance
corrections. Its scores remain frozen evidence, not a new matched evaluation of
the final instruction set.

The larger Claude runs are not clean acceptance substitutes: both made an
additional JSDoc-only edit, and repetition 2 did not persist its complete focused
plan before launching. Repetition 1 exercised fixed-finding reconfirmation after
reconciliation without an artificial behavioral edit.

A standalone Copilot composite review used a Vitest-only unit-test packet.
Its worker recognized that neither test framework was Vitest, then applied
general test-gap assessment as discovery. Separate adjudication accepted the
coverage because the production defects were real, and the structural check
passed. The run was recorded as a category-isolation failure against that frozen
packet. The user subsequently clarified that unit-test review must adapt to
the actual framework: non-Vitest work alone cannot support that failure diagnosis.
Individual findings still require their own validity and purpose assessment.

Adjudication now explicitly checks the reported method and applicability against
the frozen packet, separately from finding validity. It returns out-of-purpose
coverage as incomplete. The caller deactivates the affected attempt without
rewriting its report and uses only the existing bounded replacement allowance.
Correct findings or another category's coverage cannot fill that obligation.

A second Copilot composite run stopped after upstream 503 overloads and the
native 600-second background wait timeout. One bounded same-session continuation
used the stricter adjudication instructions with the old Vitest-only contract.
It rejected the unit-test report and a partial JSDoc report, accepted nine other categories,
preserved every existing original report, and left missing documentation coverage
explicit. Native approval then denied replacement-packet/history operations and
the final structural check. No replacement allowance was consumed. An unrelated
continuation marker was still written. This exercised rejection against the old
packet, not correct framework adaptation, successful end-to-end replacement or
a complete composite review. The final
answer also retained an unconfirmed JSDoc action, so reporting quality was not an
unqualified pass.

The two Claude candidate runs supply the standalone composite observations.
Neither Copilot composite trial is a clean category-isolation pass. Codex
standalone composite coverage remains unverified because of its account limit.

The current language-aware dispatch, framework-adaptive standards and native
documentation corrections postdate these trials and their frozen quality corpus.
Their source/record checks do not constitute a new matched native evaluation.

### Remaining native limitations

The full native matrix is not passed. Actual measured-capacity sharding and an
indivisible over-capacity trace remain unverified. The two missing-reference
probes demonstrated a real coordinator-to-worker boundary with flat replacement
fallback, not a complete all-category alternate nested topology.

Codex exposed distinct native context IDs and `fork_turns: none`; private passive
hook capture also exposed per-agent packet/source read requests. Its spawn-message
bodies remained encrypted, including in hook payloads. Hidden context was not
proven pristine on any host. Native observations, caller labels, reported model
names and unseen backend identities are not interchangeable.

Explicit role-model and effort overrides were not authorized for these trials.
Their native routing and rejection/fallback paths remain unverified; configured
defaults and offline option checks do not establish those outcomes.

Native host acceptance additionally needs a launch-to-handback trial of help,
default selection, explicit role overrides, effort support, native rejection
and permitted fallback, actual-model reporting, and review/fix forwarding.
Never deliberately exceed account permissions to induce failures. Offline
fixtures can cover failure mechanics; label simulated outcomes as simulated.
Do not claim autocomplete, an options picker, or native routing was verified
from frontmatter or parser tests.
