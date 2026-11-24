# Known issues not fixed here

Truth, correction scope, and publication are separate decisions. A real defect
does not disappear because this change did not introduce it or will not fix it.
This policy changes reporting, not fix eligibility, acceptance, or permissions.

## Reporting set

Use the latest evidenced assessment for each underlying issue. Include it when:

- `validation` is `valid` or `uncertain`;
- it has not reached a verified `fixed` disposition;
- `material` is not `false`; and
- it is not a duplicate of another canonical issue.

`material: true` means an evidenced defect or a credible consequential
uncertainty, including meaningful documentation errors and test gaps.
`material: false` requires a reason showing that the observation is style-only
or lacks a concrete consequence. Low severity, expensive correction, accepted
risk, pre-existing behavior, an out-of-scope location, and `report_action: None`
are not reasons to set it false. Keep invalid, duplicate, and genuinely
immaterial observations counted rather than naming them in this section.

The reporting set does not depend on `ignored` versus `out_of_scope`,
`introduced`, the main report's severity floor, or an action recommendation.
Missing legacy materiality is a disclosed assessment gap, not grounds to hide
a valid or uncertain finding. Pending candidates remain an assessment-gap
count, not confirmed defects. Retain an earlier established issue as uncertain
when invalidation requires renewed assessment; do not silently erase it.

## Human report

Include an explicit **Known issues not fixed here** section in review-code,
review/fix, and review-triage reports. For each issue give its stable key or ID,
title, location, concise evidence and consequence, confidence/basis, and why it
was not fixed. Identify pre-existing versus introduced behavior and label
uncertainty. Include the worthwhile follow-up or missing check, if known.
An entry already explained in the main report can reference that finding's ID,
but must still name the issue and explain its deferral here.

Update this section from current assessments on completion or interruption.
A later verified resolution or invalidation removes the issue from the current
list, not from history. A finding absent from a later pass is not thereby fixed.
Use stable underlying-behavior keys across categories, cycles, and task reviews.
Reconcile different keys for the same cause explicitly rather than guessing
from a shared file or similar title.

`scripts/review_reporting.py` projects a private handback (`candidates` and
`assessments`) or review-ledger status JSON:

```sh
python3 "/installed plugin/scripts/review_reporting.py" "/private/handback.json" --format markdown
```

The helper emits a private draft, not publication approval. It does not verify
the semantic assessments or launch models. It also accepts `--format json`.
For the Markdown-only triage ledger, apply this same set directly; do not use
the remediation ledger merely to generate a report.

The independent `review-known-issues` setting controls this named section.
Read its effective value through the helper or normalized review options.
When disabled, disclose that omission and retain the complete inventory.
It does not alter validation, fix eligibility, review coverage, or independently
authorized follow-up publication.

## Publication boundary

Standalone review skills do not create tickets or update a PR body. Their
caller may do so only under separate authorization. Autonomous development
uses [../autonomous-development/FOLLOW_UPS.md](../autonomous-development/FOLLOW_UPS.md).

Never automatically copy raw private evidence into a public PR or issue.
Sensitive findings require safe disclosure; withhold pre-existing exploitable
details and personal data from public output. Keep the full evidence in private
storage, and use a safe notice or approved private destination. A publication
failure or missing permission leaves the finding in the private human report.
