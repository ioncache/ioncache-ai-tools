---
name: post-pr-review-comments
description: Turns verified review findings into brief, natural GitHub PR comments with enough context to act. Use when a human is driving a PR review and wants comments written up, added to a pending draft review, or edited, including authorised wording edits to submitted review comments; never submits the review.
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

Keep comments to a few short sentences, usually 1-3, in one compact paragraph.
Use short bullets rather than a comma-separated list when listing several items.
Bullets replace prose; they are not a way to squeeze a report into one comment.

Use everyday words, contractions, and direct phrasing. Fragments, lowercase
openings, and omitted final periods are fine when they read naturally. Do not
polish a normal review comment into formal prose, or force casual quirks into
every comment. First person is optional.

Offer an observation, question, or suggestion, never an authoritative verdict
that the engineer is wrong. The register is tentative and collaborative, even
for verified findings. Leave room for the author to disagree, explain, or supply
context you may have missed without burying the point.

Vary phrasing and sentence structure naturally from comment to comment, as a
person writing each one would. Do not prescribe a list of stock phrases or turn
the examples into reusable openings. Variation is not mechanically swapping
synonyms in the same template.

Explain the problem and what needs to change. Include the trigger or connecting
step the author needs, but do not give each part its own sentence or paragraph.
Do not repeat what the anchored code already makes clear. A useful link can
replace a long explanation of an external contract.

For example:

> a missing email seems to fail the whole batch, including valid invitations. worth rejecting that row before queueing?

For a helper-reuse comment the human has chosen:

> any reason not to use `loadSettings` here? it already handles these defaults, so we wouldn't need a second copy

These illustrate the voice, not mandatory openings or claims to reuse.
Avoid review-bot jargon, formal conclusions, defensive filler, hypothetical
objections, and drafting history. Never write "just want to call out."
Use identifiers only when they help locate or explain the issue, not to dump
the call stack. Follow repository spelling without altering identifiers.
Keep triage/severity markers outside comment bodies.

## Process

1. Establish the PR, base, context-only sibling PRs, and carry-over claims.
   If asked to perform an automated review, use `review-code` and finish it
   before posting. If the human supplies findings, verify those without
   starting an unsolicited review. Keep PR-specific details out of this skill.
2. Verify candidates against code and sources; reviewer conclusions are leads,
   not evidence. Keep unresolved concerns in separate notes with the missing
   evidence, not among ready comments.
3. Draft in a session-scratchpad Markdown file. Run the readiness check and
   correct your own draft before presenting the file with its full path.
   Never post an unpresented draft or re-render the comment list in the terminal.
4. Apply requested edits; the request authorises them, including systemic
   feedback across the file. Report which comments changed. Answer questions
   without editing; a question alone is not approval.
5. Before revising a rejected comment, explain whether its finding survives
   without the rejected claim; otherwise propose dropping it.
   Do not ask again for edits or removals already authorised.
6. Posting requires an explicit request to post, not merely to draft or edit.
   If posting is already authorised, presentation does not require another
   approval. Follow the GitHub procedures, including approval to create a
   pending review when none exists. Never submit the review.

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
misleading. Describe the needed behaviour rather than prescribing an
implementation, unless the fix is trivial or the human requested it.
There is no required opening, closing, or sentence-by-sentence structure.
Tentative wording is a tone choice, not a substitute for verification.
If the causal link is unverified, keep the concern in working notes until
checked. Evidence supports the observation; it does not require an
authoritative tone.

## Anchoring

Check the current diff. Anchor added/context lines inside a hunk, not removed-only
lines, using `path:start-end` headings. Anchor the whole relevant prose construct
unless one line is the subject. For cross-file findings, use where the change
introduces the behaviour, not merely any available hunk.
Never cite line references into other files.

Without a valid anchor, retain `path (non-inline, unposted)` and ask how to proceed;
do not invent an anchor or drop the finding. Keep independent fixes separate.
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

Before presentation and posting, reread the saved comments as the author seeing
only the anchored hunk and comment, not private review notes:

1. Is the point verified, correctly anchored, and clear enough to act on?
   For a bug, can the author understand how this change causes the problem?
   For a human-selected preference, is it honestly phrased as one?
2. Is it a few short sentences an engineer would actually type, inviting
   discussion rather than declaring the author wrong? Remove repeated context,
   investigation detail, and unnecessary quotations. Shorten by cutting, not by
   splitting the same text into more sentences or paragraphs. Read the comments
   together for repeated openings or a stamped-out sentence pattern.

After wording edits, reread the saved result for lost context or changed claims.
Unverified claims or unexplained relevance block posting, however polished.
For already-presented drafts, make the requested edits without another approval
round. Explain remaining gaps and ask only about changes not already authorised.

## File format

```
# PR #NNN review comments

Ordered by file in diff order, then line.

---

## 1. path/to/file.js:120-134

short comment, usually 1-3 sentences in one paragraph

---
```
