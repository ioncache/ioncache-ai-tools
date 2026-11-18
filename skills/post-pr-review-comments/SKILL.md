---
name: post-pr-review-comments
description: Turns verified review findings into brief, natural GitHub PR comments with enough context to act. Use when a human is driving a PR review and wants comments written up, added to a review, replied to in existing published threads, or edited, including authorised wording edits to submitted review comments; never submits the review.
---

# PR Review Comment Process

Write like an engineer talking to another engineer in a review thread.
Give the author enough to understand the issue and act, not the investigation
that led to it. Keep the full reasoning and supporting evidence in working notes.

Keep local-only work local. Never submit or discard a review.
Before planning or performing GitHub comment/review operations, or assessing
another reviewer's comments, read [references/github-review.md](references/github-review.md).
That reference is mandatory for those tasks, not for local drafting alone.

## Voice and length

Write short notes, not an essay: informative, with a possible direction.
The default unit is a sentence fragment on its own line, with a blank line
between fragments. Fragments are lowercase, with no final full stop; preserve
the exact case of identifiers and quoted text.

Questions are always complete sentences, capitalised and ending with a question
mark. When two pieces only make sense together, keep them in one paragraph as
proper sentences with capitals and punctuation. This includes a question and
its follow-up reason, or an "It works today..." / "But..." pair.

Put three or more parallel items, such as affected callers or error messages,
in a short bullet list introduced by a fragment ending in a colon.
Give the author enough to understand and act, but cut clauses that add no fact.
Splitting into fragments must not pad length; dense packing must not disguise it.
These layout rules apply to PR comments, not implementation comments or general
documentation.

Use everyday words, contractions, and direct phrasing. Do not polish a normal
review comment into formal prose or force casual quirks into every comment.
First person is optional.

Offer an observation, question, or suggestion, never an authoritative verdict
that the engineer is wrong. The register is tentative and collaborative, even
for verified findings. Leave room for the author to disagree, explain, or supply
context you may have missed without burying the point.

Vary phrasing and sentence structure naturally from comment to comment, as a
person writing each one would. Do not prescribe a list of stock phrases or turn
the examples into reusable openings. Variation is not mechanically swapping
synonyms in the same template.

Explain the problem and what needs to change. Include the trigger or connecting
step the author needs. Do not repeat what the anchored code already makes clear.
A useful link can replace a long explanation of an external contract.

For a metadata-ownership comment the human has chosen:

```text
metadata keys spelled out here, and again where they're read: `locale` and `duration_months` in `buildRenewalSchedule`, `duration_months` in `buildOrderFields`

if they drift apart nothing errors: no `duration_months` and `buildRenewalSchedule` skips the order, no `locale` and translated purchases get default-language prices

each file's tests hard-code their own copy of the keys, so a one-sided rename stays green

Could `services/billing/checkout-metadata.js` own both writing and reading this metadata? That would also remove this block's reliance on `options.recurring_data`, which only exists because the `if (plan.recurring)` branch above created it.
```

For a helper-reuse comment the human has chosen:

```text
the same defaults copied into three callers:

- `startWorker`
- `reloadWorker`
- `previewSettings`

Would `loadSettings` fit here? It already supplies these defaults.
```

These illustrate the voice, not mandatory openings or claims to reuse.
Avoid review-bot jargon, formal conclusions, defensive filler, hypothetical
objections, and drafting history. Never write "just want to call out."
Use identifiers only when they help locate or explain the issue, not to dump
the call stack. Follow repository spelling without altering identifiers.
Keep triage/severity markers outside comment bodies.

## Terminology

Use the exact name from the code, README, or vendor documentation: the route
(`GET /orders/checkout`, not "completion"), function (`buildSchedule`, not
"the handler"), flag by its key, test by its title, and error by its message text.
Name a field's owner when it could mean another system's field: "the identity
provider user's `data.product_id`", not just `data.product_id`.

Replace bare references that make the reader guess. Use "the
`if (plan.recurring)` branch above", not "the branch above". When two flags
matter, name both keys rather than saying "the flag". Replace vague states such
as "unconfigured" with the missing setting or exact condition.
Distinguish our webhook route from the webhook endpoint registered with the
vendor, and the vendor's test account from the deployed development app.

Quote a document's actual wording. Do not put a paraphrase in quotation marks
or add qualifiers such as "only". Name functions or files for cross-file context;
never cite line references into other files.

## Process

1. Establish the PR, base, context-only sibling PRs, and carry-over claims.
   If asked to perform an automated review, use `review-code` and finish it
   before posting. If the human supplies findings, verify those without
   starting an unsolicited review. Keep PR-specific details out of this skill.
2. Verify candidates against code and sources; reviewer conclusions are leads,
   not evidence. Keep unresolved concerns in separate notes with the missing
   evidence, not among ready comments.
3. Draft in a session-scratchpad Markdown file. Run the readiness check and
   address the independent readers' findings before presenting the file with
   its full path.
   Never post an unpresented draft or re-render the comment list in the terminal.
4. Apply requested edits; the request authorises them, including systemic
   feedback across the file. Report which comments changed. Answer questions
   without editing; a question alone is not approval.
5. Before revising a rejected comment, explain whether its finding survives
   without the rejected claim; otherwise propose dropping it.
   Do not ask again for edits or removals already authorised.
6. Follow the requested action. "Add comments to a review" normally means using
   a pending review; this is the recommended method, not a prerequisite for
   new inline comments. Honour requests to publish new comments directly.
   "Reply" or "respond" to an existing published PR comment authorises posting
   the response directly, without a pending review or another posting approval.
   Requests to draft, edit, or suggest a response do not authorise posting.
   Honour explicit instructions to keep a reply local or pending. Presentation
   does not require another approval when posting is already authorised.
   Follow the GitHub procedures. Never submit the review.

## What counts as a finding

When selecting findings yourself, include user, operational, or business
misbehaviour, security/privacy failures, and unusable documentation/runbooks.
Exclude duplication, helper reuse, style, wording-only issues, log-message
noise, and speculative typo guards.

When the human has chosen an item, help write it even if it is about reuse,
style, or another preference. Verify its factual claims without inventing a
bug or overstating its impact to make it qualify. If the premise is wrong,
explain that rather than posting it as fact.

For internal contracts, inspect callers for producible inputs; for external
boundaries, check the input contract and existing validation. Values rejected
upstream need no further guard. Another helper's defensive code is not evidence.
Outside-diff findings need a PR-changed input making the failure reachable;
explain that dependency in the comment. Exclude untouched pre-existing problems.

Flag missing tests only for newly enabled business logic with no other coverage
and no stated branch-specific test policy. Check that policy first.

## Verify fully, explain briefly

Trace intervening callers, transformations, validation, and error handling.
A shared helper or indirect call alone proves nothing; do not assume inputs
arrive unchanged or errors escape their callers. This is verification work,
not a checklist of things to include in the comment.

Keep the connection to the anchored change clear. Include a non-obvious trigger
or intermediate step when leaving it out would make the finding confusing or
misleading, for example: "`findOne` finds no record and throws
`No record for session ...` after the schedule is built".

Before saying "everywhere" or listing affected places, check every candidate
and name the full set actually affected. A caller that reads the value but gets
the same result either way is not affected. Use a short list for three or more.
If an existing test looks as though it covers the case, name it by title and
explain why it does not.

Describe the needed behaviour rather than prescribing an implementation, unless
the fix is trivial or the human requested it. For a proposed fix, state the
exact condition and check that it preserves neighbouring paths served by the
same code. For a test request, name assertions that would fail under the
described regression, not merely assertions that pass today.

State the evidence's scope when it matters, for example, "every two-line session
inspected in the vendor's test account returned the items in this order".
Say what could not be checked, such as production; do not generalise test-account
observations into a production guarantee.

There is no stock opening or closing; order the facts to make the point clear.
Tentative wording is a tone choice, not a substitute for verification.
If the causal link is unverified, keep the concern in working notes until
checked. Evidence supports the observation; it does not require an
authoritative tone.

## Anchoring

For new inline threads, check the current diff. Anchor added/context lines inside
a hunk, not removed-only lines, using `path:start-end` headings.
Anchor the whole relevant prose construct
unless one line is the subject. For cross-file findings, use where the change
introduces the behaviour, not merely any available hunk.
Never cite line references into other files.

Without a valid anchor for a new thread, retain `path (non-inline, unposted)` and
ask how to proceed; do not invent an anchor or drop the finding.
Replies use the existing thread's anchor; they do not need a new current-diff hunk.
Keep independent fixes separate.
Repeated findings may refer back but must explain their own connection and impact.
Order by file in diff order then line, or by severity, never mixed.
Do not renumber remaining comments after removal.

## Citing third-party documentation

Verify current sources, not memory or reviewer summaries. Identify the version
actually used, including client overrides; check names/shapes against installed
types or versioned schemas. Prefer pinned-version evidence; newer-only removals
or deprecations are not findings for the pinned version.

Read and link human-facing pages, not alternate Markdown or filtered views.
Use supported version-specific URLs, never invented parameters; if unavailable,
identify the documented version and verify applicability. Verify rendered anchor
IDs. For unanchored fields, link the containing section and name the field.
Include a link when it helps the author verify or act on the point, not as a
mandatory appendix. Do not paste documentation into every comment. Quote only
when the exact wording matters, keep it short, and preserve it verbatim.
Unreachable evidence stays unverified, not ready to post.

## GitHub suggestion blocks

Use `suggestion` only for a literal same-file replacement requiring no design
decision. Use the smallest changed range without unchanged enclosing code.
For cross-file, outside-diff, or judgement-dependent fixes, use prose and name
where the fix belongs. Before posting, reread the current source and refresh the
PR-head diff; verify the whole range is inside a hunk and replacement syntax is valid.

## Readiness check

Before presentation and posting, use separate fresh-context subagents for
correctness and comprehensibility. The author's reread does not count as either
check. Give each worker only its single-purpose instructions below; workers
must ignore ambient review guidance, not load other skills or generic review
workflows, and not delegate another review layer.

1. **Correctness:** verify every factual claim against evidence, not the
   author's conclusions. Read whole relevant files and trace callers,
   transformations, validation, and error handling. Check the current anchor,
   the full affected set, proposed fixes against neighbouring paths, and
   whether requested assertions would fail under the regression.
   Cite current applicable vendor documentation for external claims; use
   authorised read-only live data when a claim depends on deployed state.
   A claim that documentation is silent requires reading the relevant
   documentation, including separate guides that address the behaviour.
   A failed search or one silent page is not evidence of absence.
   Report each claim's evidence or gap and a per-comment verdict: verified,
   incorrect, or unverified. Keep human-selected preferences labelled honestly.
2. **Comprehensibility:** use a different fresh-context reader given only each
   comment, its anchored lines, and access to the PR, never the review notes or
   correctness report. For each comment, report inexact or ambiguous terms
   with the correct names, missing facts, hard-to-parse sentences, and a verdict:
   clear or needs revision. Check the fragment layout, complete questions,
   tied paragraphs, and lists. Check that the causal step and relevance are
   understandable without private context, and that the wording invites
   discussion rather than declaring the author wrong.

Fix the findings and rerun the independent checks on revised comments until
every comment retained for posting is verified and clear. Recheck changed
claims as well as wording; do not carry a verdict across edits it did not cover.
Read the comments together for repeated openings or a stamped-out pattern,
and cut repeated context, investigation detail, and unnecessary quotations.

Bound correction rounds to three per comment unless the human sets another
finite limit. If a reader or required evidence is unavailable, or a comment
still fails at the limit, keep it unposted, report the gap, and continue other
authorised work. A retry limit never makes a failed check pass.
If a comment is wrong, explain why and propose deletion; the human decides.
Do not silently remove it or ask again for a removal already authorised.

Unverified claims or unexplained relevance leave a comment unready, however
polished.
For already-presented drafts, make the requested edits without another approval
round. Explain remaining gaps and ask only about changes not already authorised.

## File format

```
# PR #NNN review comments

Ordered by file in diff order, then line.

---

## 1. path/to/file.js:120-134

the locale default copied from `loadSettings`

a one-sided change would leave `startWorker` using a different default

Could `startWorker` use `loadSettings`? It already supplies the locale default.

---
```
