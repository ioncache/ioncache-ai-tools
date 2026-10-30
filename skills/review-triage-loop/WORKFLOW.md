# Review and triage workflow

## Establish an unchanged target

Resolve absolute target paths and the intended scope. A document or repository
review can include existing problems. For a branch/PR review, pin its comparison
base and reviewed head, include relevant local edits, and distinguish introduced
problems from pre-existing ones. Do not silently substitute a remote diff for
local files. If the required scope or base is unavailable, stop as blocked.

Record target fingerprints before review and check them again after review,
after validation, and on resume. Include the file inventory, additions,
deletions, and relevant untracked inputs, not only a commit identifier.
Keep supporting sources distinct from the target. Record exclusions and
limitations rather than implying full coverage. Check mutable supporting
inputs before reusing judgments and after validation. If they change, use the
ledger's evidence-invalidation procedure before counting a quiet round.

Keep the target unchanged across rounds. If it changes, preserve the current
work and stop as blocked with the drift evidence. Do not restore files,
silently adopt a new version, or combine quiet rounds from different targets.
The user must explicitly choose a new review or provide the original version.

## Give each reviewer the minimal assignment

The coordinator owns agent launches. Start rounds sequentially so each fresh
agent receives all findings recorded before it starts. Persist the round
number and exact assignment before launching; a started round consumes capacity
even if interrupted or unsuccessful.

Round one receives only this task text, substituting the resolved target:

> Do a full review of <target>. Report every issue you find. Do not edit any file.

For a change review, the target phrase identifies the pinned comparison and
local scope. It must not add hints about likely defects or preferred outcomes.
Use available read-only worker controls without appending review methodology
to the task text.

Every later round receives the same text, followed by:

> These issues have already been found. Do not report them again; report only issues not on this list. Report a previously recorded issue only when new evidence changes its assessment, and identify that evidence.

Append every canonical issue recorded so far, including actionable, uncertain,
rejected, unreachable, and low-value findings. Give its ID, current assessment,
affected behavior/location, trigger, and enough evidence and reasoning to
recognize it or challenge a mistaken dismissal. Link duplicate observations to
the canonical ID instead of repeating equivalent entries.

Give reviewers nothing else: no focus areas, checklist, desired issue count,
remaining budget, coordinator analysis, or reference to the ledger. Necessary
evidence within an issue's assessment is not a license to add review guidance.
Do not silently truncate the inventory to fit a context limit. If the full
inventory cannot be supplied, stop as blocked and disclose that limitation.

Save the exact response before triaging. A failed, truncated, or visibly
partial response is incomplete, not evidence that no issues exist. Stop with
the gap rather than repeatedly relaunching within the same round.

## Validate and triage every candidate

The coordinator evaluates the evidence rather than accepting the reviewer's
labels. Re-read the relevant target and sources. Agreement between models is
not validation. Record the following separately for every underlying issue,
including those that will not appear in the report:

| Dimension | Required judgment |
| --- | --- |
| Validity | Supported, refuted, or unverified against an actual requirement or intended behavior. |
| Kind | Substantive defect/design gap, edge case, or editorial preference; labels can overlap. |
| Reachability | Demonstrated, plausible, prevented, or unknown, with the triggering conditions and evidence. |
| Risk | High, Medium, Low, or Unknown, with consequence, likelihood, and recoverability. |
| Confidence | High, Medium, or Low confidence in the evidence, separate from potential harm. |
| Priority | P0: immediate action; P1: before the affected step or release; P2: planned later work; P3: only alongside related edits; none: no warranted action. Explain the dependency or urgency. |
| Disposition | Act, decide, investigate, opportunistic, or no action, with the value and cost/risk of the next action. |

Use a reasoned "not applicable" where a refuted claim has no actual risk or
priority. Do not invent numerical probabilities or lower potential impact
because evidence is uncertain. A plausible serious failure may justify
investigation before a fix is known.

### Evidence and materiality

Validate behavior against actual callers, constraints, and intended requirements.
For design documents, distinguish a deliberate future change from an accidental
contradiction. An omitted implementation detail is not automatically a design
defect: explain the consequential ambiguity, unmet requirement, or failure it
would cause. A preference for another architecture is not a finding by itself.

Verify third-party claims using current authoritative sources applicable to
the project's intended versions and configuration. Record URLs, retrieval
dates, versions, and the relevant evidence. Latest documentation does not
automatically describe the version in use. Pin project source comparisons,
including any code read from the default branch, rather than treating a moving
branch name as a permanent reference. Keep unavailable evidence unverified.

"Will never happen" requires an enforced invariant that prevents the trigger.
Small scale, typical traffic, UI restrictions without enforcement evidence,
and expected operator behavior are assumptions, not proof of impossibility.
Low probability may justify accepting risk, but not calling the claim false.
Document the assumption and the consequence if it stops holding.

Judge value using consequence, relevance, timing, correction cost, and regression
risk. A one-line edit is not automatically worthwhile. A costly correction is
not automatically low priority. Rare but serious problems must not disappear
behind an "edge case" label.

Product-dependent findings remain decisions, not invented requirements or
automatic fixes. Identify the specific decision and what depends on it.
Do not pause each round for routine adjudication; report consequential
questions together. Missing evidence should identify the smallest useful
check that would settle it.

### Deduplication and reopening

Use stable IDs for underlying failures or unmet requirements. Rewordings and
multiple symptoms of one cause are observations, not extra issues. Distinct
failures stay distinct even if one correction can address them; group their
recommended actions in the report without erasing their evidence.

Compare candidates against the entire ledger, not just previously reported
items. Keep every observation, including duplicates and rejected claims, with
its round and decision. Repetition alone does not reopen a finding. New
evidence can invalidate a dismissal, change risk or priority, or withdraw an
earlier reportable claim. Record the old and new assessments and why.

## Filter the report, not the investigation

A finding is reportable when it warrants one of these:

- Act: a supported, relevant problem with a worthwhile correction.
- Decide: an unresolved choice that materially affects correctness, risk,
  implementation, or a significant design commitment.
- Investigate: a credible consequential uncertainty with a specific useful
  evidence-gathering action, not an arbitrary hypothetical possibility.

P3 opportunistic edits, cosmetic preferences, duplicates, refuted claims, and
evidence-backed low-value observations remain in the ledger only. Do not turn
them into a second reading assignment or an unsolicited cleanup backlog.
Never silently accept a material risk solely to shorten the report.
Out-of-scope material risks should be clearly separated from in-scope actions;
their discovery does not authorize expanding the reviewed target.

Keep uncertain findings visibly uncertain. Do not describe a proposed
investigation or product decision as a verified defect or an authorized fix.
For unchanged outstanding items, retain them in the final list without
reprinting every explanation after every round.

## Count rounds and stop honestly

Finish validation and persist all assessments before finalizing a round.
Distinguish a fully processed candidate left explicitly unverified from an
unprocessed candidate or failed source check. A required coverage or verification
gap makes the round incomplete; it cannot contribute to the quiet streak.
A completed triage can retain consequential product decisions or evidence
questions as reportable uncertainties without pretending they are resolved.

Count a canonical ID as newly reportable only the first time it enters Act,
Decide, or Investigate. A previously suppressed issue can become newly
reportable. Promoting an already reported uncertainty to an action, reopening
an earlier reported issue, or withdrawing a mistaken report is a material
update, not another unique issue.

A complete round is quiet only when it has neither newly reportable issues
nor material evidence-backed updates to earlier reportable assessments.
Duplicates, wording changes, and unchanged uncertainty do not reset the streak.
Material updates do reset it, without inflating the unique-finding count.
Do not manufacture updates to keep reviewing.

After each complete round, increment the quiet streak if quiet; otherwise
reset it to zero. Stop at two consecutive quiet rounds. Check this condition
before the cap: if the second quiet round is the last allowed round, the quiet
stop was achieved. Otherwise stop at the cap as "round limit reached".

Never exceed the saved total cap, refund an interrupted launch, or silently
create a replacement run to continue. A partial/failed round stops the run as
blocked with an incomplete round and resets the quiet streak. Resumption must
follow the ledger protocol. Preflight blockers found before recording round
start consume no capacity.

Quiet stopping means diminishing reportable discovery within this scope,
not that the target has no defects or that open findings have been resolved.
Limits and quiet streaks are not monetary or token budgets.

## Report between rounds and at termination

Start with the outcome, rounds started versus the cap, and quiet streak.
After each round, give one cumulative row per round:

| Round | Newly reportable | Material updates | Running unique total | Result |
| --- | --- | --- | --- | --- |

Use "incomplete" rather than a misleading zero for an unfinished round.
The running total counts distinct IDs ever reported; withdrawals do not
rewrite history. Explain any difference from the current actionable count.

List newly reportable findings as numbered items in priority order. Each
needs a stable ID, originating round, plain-language problem or uncertainty,
trigger and consequence, evidence, priority, risk, and the worthwhile next
action. Keep consequential decisions/investigations separate from supported
corrections. Call out material updates by ID, including withdrawn findings.
Do not repeat suppressed items unless explicitly requested.

At termination, return the same table and the full current prioritized list
of worthwhile actions and consequential uncertainties, with originating rounds.
Group shared corrections without double counting issues. Include coverage
limitations, required checks not performed, unresolved material assumptions,
the stop reason, and the absolute ledger path. Rejected and low-value entries
remain available in the ledger, not dumped into the default final report.
