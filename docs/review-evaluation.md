# Evaluating review changes

Mechanical option and ledger checks do not measure finding quality or prove
native model routing. Use
[../scripts/fixtures/review_quality.json](../scripts/fixtures/review_quality.json)
for a bounded, synthetic comparison without private application source.

The corpus contains calibration cases, negative controls, and held-out variants.
Its expected claims are acceptance hypotheses, not proof. Have an independent
reader validate them against the supplied source and reference contracts before
scoring. Do not expose `expected`, `reject`, or split labels to reviewers.
Do not tune instructions against held-out results and then call the same cases
held out in a later comparison.

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

Native host acceptance additionally needs a launch-to-handback trial of help,
default selection, explicit role overrides, effort support, native rejection
and permitted fallback, actual-model reporting, and review/fix forwarding.
Never deliberately exceed account permissions to induce failures. Offline
fixtures can cover failure mechanics; label simulated outcomes as simulated.
Do not claim autocomplete, an options picker, or native routing was verified
from frontmatter or parser tests.
