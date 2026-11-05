---
name: post-pr-review-comments
description: Turns verified review findings into actionable GitHub PR comments that explain their connection to the reviewed code. Use when a human is driving a PR review and wants comments written up, edited, and added to a pending draft review; never submits the review.
---

# PR Review Comment Process

Help the PR author act on verified problems introduced or exposed by the change.
Actionable information comes before style: never sacrifice a causal link,
condition, evidence, or consequence for brevity or preferred phrasing.

Keep local-only work local. Never submit or discard a review.
Before planning or performing GitHub comment/review operations, or assessing
another reviewer's comments, read [GitHub review procedures](references/github-review.md).
That reference is mandatory for those tasks, not for local drafting alone.

## Process

1. Establish the PR, base, context-only sibling PRs, and carry-over claims.
   Use `review-code` if the automated review is not complete; finish it before
   posting. Keep PR-specific details out of this skill.
2. Verify candidates against code and sources; reviewer conclusions are leads,
   not evidence. Keep unresolved concerns in separate notes with the missing
   evidence, not among ready comments.
3. Draft in a session-scratchpad Markdown file and give its full path.
   Run the readiness check and correct your own draft before first presenting it.
4. After presentation, make only authorised, targeted edits. Answer questions
   without editing; a question is not approval. Never re-render the comment list
   in the terminal.
5. Before revising a rejected comment, explain whether its finding survives
   without the rejected claim; otherwise propose dropping it.
   Apply authorised systemic feedback across the file and report which comments
   changed.

## What counts as a finding

Include user, operational, or business misbehaviour, security/privacy failures,
and unusable documentation/runbooks. Exclude duplication, helper reuse, style,
wording-only issues, log-message noise, and speculative typo guards.

For internal contracts, inspect callers for producible inputs; for external
boundaries, check the input contract and existing validation. Values rejected
upstream need no further guard. Another helper's defensive code is not evidence.
Outside-diff findings need a PR-changed input making the failure reachable;
explain that dependency in the comment. Exclude untouched pre-existing problems.

Flag missing tests only for newly enabled business logic with no other coverage
and no stated branch-specific test policy. Check that policy first.

## Explain the connection

Trace intervening callers, transformations, validation, and error handling.
A shared helper or indirect call alone proves nothing; do not assume inputs
arrive unchanged or errors escape their callers.

Start each comment with the anchored change and a reachable trigger. Explain
the meaningful steps connecting it to the failure, who or what is affected,
and the concrete impact. End with the required behaviour, not implementation
details unless trivial; put an upstream fix direction in its own sentence.
The author must not have to reconstruct the relationship from a helper description.
If the link is unverified, withhold the comment rather than hide the gap behind
"might" or "could".

Example structure, not a wording template or an assumed failure:

> This import now queues rows without checking for a missing email.
>
> The queue worker passes those rows to `normalizeRecipients`, where one missing
> email fails the entire batch, including valid invitations.
>
> Report invalid rows before queueing so they do not block valid invitations.

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

## Wording

Use one sentence per paragraph with blank lines; preserve quotations verbatim.
Prefer short, single-point sentences, splitting overloaded explanations without
losing reasoning. There is no fixed sentence/word limit.
Introduce referents; name items rather than unexplained counts. Use identifiers
and file names only to locate or explain the issue, describe their roles, and
avoid call-stack dumps. Follow repository spelling without altering identifiers.

Use a conversational voice; first person is optional, not a required opening or
closing. Avoid repetitive boilerplate, not ordinary repeated words; do not force
synonyms. Never write "just want to call out."
Omit colourful idioms, review-bot jargon, defensive filler, hypothetical objections,
and drafting-history explanations. Each sentence must serve the connection,
evidence, problem, impact, or recommendation.
Keep triage/severity markers and legends in working files only, outside comment bodies.

## Citing third-party documentation

Verify current sources, not memory or reviewer summaries. Identify the version
actually used, including client overrides; check names/shapes against installed
types or versioned schemas. Prefer pinned-version evidence; newer-only removals
or deprecations are not findings for the pinned version.

Read and link human-facing pages, not alternate Markdown or filtered views.
Use supported version-specific URLs, never invented parameters; if unavailable,
identify the documented version and verify applicability. Verify rendered anchor
IDs. For unanchored fields, link the containing section and give navigation.
Blockquote the relevant sentence below the link. Unreachable evidence stays
unverified, not ready to post.

## GitHub suggestion blocks

Use `suggestion` only for a literal same-file replacement requiring no design
decision. Use the smallest changed range without unchanged enclosing code.
For cross-file, outside-diff, or judgement-dependent fixes, use prose and name
where the fix belongs. Before posting, reread the current source and refresh the
PR-head diff; verify the whole range is inside a hunk and replacement syntax is valid.

## Readiness check

Before presentation and posting, reread the saved comments as the author seeing
only the anchored hunk and comment, not private review notes. Perform both passes:

1. Substance: eligible finding, current evidence for every claim, relevant anchor,
   reachable trigger, explicit causal chain, concrete impact, and required behaviour.
2. Wording: sentence-per-paragraph spacing, verbatim quotations, single-point
   sentences, introduced referents, useful identifiers, and natural voice.

After wording edits, reread the saved result for lost context or changed claims.
Unverified claims or unexplained relevance block posting, however polished.
For already-presented drafts, explain remaining gaps and obtain approval for
corrections/removals not already authorised; never silently rewrite them.

## File format

```
# PR #NNN review comments

Ordered by file in diff order, then line.

---

## 1. path/to/file.js:120-134

sentence

sentence

---
```
