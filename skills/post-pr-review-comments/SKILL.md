---
name: post-pr-review-comments
description: Turns review findings into GitHub PR review comments in a pending draft review. Use when a human is driving a PR review and wants comments written up, edited, and added to GitHub; never submits the review.
---

# PR Review Comment Process

Write up findings for a human-led PR review; use `review-code` to produce them.
Establish the PR, base branch, context-only sibling PRs, and carry-over findings
or claims to recheck. Keep PR-specific details out of this skill.

## Process

1. Run the automated review if not already complete. Post nothing until it finishes.
2. Draft comments in a Markdown file in the session scratchpad; give its full path.
3. Make targeted edits to that file. Never re-render the list in the terminal
   or reword comments the human has not asked to change.
4. Answer questions in plain text without editing. Wait for explicit approval
   to update; a question is not approval.
5. Before editing a rejected comment, explain whether the finding survives
   without the rejected claim. If not, propose dropping it.
6. Apply systemic feedback across the file: check every comment for the same
   fault and report which others changed.

## What counts as a finding

Report user, operational, or business misbehaviour, or documentation/runbooks
that cannot be followed. Exclude duplication, helper reuse, style, wording-only
issues, log-message noise, and speculative typo guards.

Require code or documentation evidence for the scenario. Inspect callers;
flag missing guards only for inputs they can actually produce. Another helper's
defensive code is not evidence.
Outside-diff findings require a PR-changed input that makes the failure reachable.
Explain that dependency; exclude untouched pre-existing problems.

Flag missing tests only for business logic the PR enables, with no other
coverage and no stated branch-specific test policy. Check that policy first.

## Anchoring

Check the current PR diff before assigning anchors. Use added or context lines
inside its hunks, never removed-only lines. Put `path:start-end` in each
comment's working-file heading.

For prose, anchor the whole relevant construct; use one line only when that
line is the subject. Suggestion blocks use the smallest changed range.
For cross-file findings, anchor where the diff introduces the behaviour and
describe the downstream effect. Never cite line references into other files.

## Wording

Use a few short sentences, one point per sentence, each on its own line with
a blank line between. Expand only for more than one genuinely distinct failure
path or a necessary documentation quote. Shorten sentences, not just line breaks.
Introduce referents before using them; name items rather than unexplained counts.

Use conversational first person. Qualifiers such as "I think" are optional;
do not repeat stock phrases across a review. Never write "just want to call out."
Avoid colourful idioms, review-bot jargon, defensive filler, hypothetical
objections, and explanations of earlier drafting mistakes. Each sentence should
state the problem, impact, or recommendation. Keep triage/severity markers and
legends in the working file only.

Describe who or what is affected, the triggering state, the wrong behaviour,
and its impact. End with recommended behaviour, not an exact implementation
unless trivial. State upstream fix direction in its own sentence.
Use code identifiers only when naming a route, flow, or field by role helps locate it.
Follow repository spelling, preserving identifiers and third-party quotations.

## Citing third-party documentation

Verify claims in current documentation, not memory or a reviewer's summary.
First identify the dependency/API version actually used, including client
overrides. Cross-check names and shapes against installed types or versioned
schemas; prefer evidence for the pinned version over mismatched guides.

Read and link the human-facing page, not alternate Markdown or search-filtered
views. Use supported version-specific URLs, never invented parameters.
If unavailable, identify the documented version and verify applicability.
Verify rendered anchor IDs rather than guessing slugs. For an unanchored nested
field, link its containing section and explain how to reach it.

Blockquote the relevant sentence below the link. If documentation is
unreachable, label the claim unverified. Deprecations/removals exclusive to
newer dependency versions are not findings for the pinned version.

## GitHub suggestion blocks

Use a `suggestion` block only for a literal, same-file replacement of the
anchored lines requiring no design decision. If the fix needs another file,
code outside the diff, or a judgement call, use prose and say where it belongs.

Use the smallest range containing the change; omit unchanged enclosing code.
Keep independently fixable issues in separate comments with separate minimal
anchors. Repeated findings may refer briefly to an earlier comment.

Before posting, reread the current file and refresh the PR-head diff.
Verify the entire range is inside a hunk and the verbatim replacement produces
valid syntax.

## Posting to GitHub

Use a small scratchpad script invoking `gh`, in an available runtime, with a
`--dry-run`; avoid one-off shell mutations. Before deleting, list targets and
exclude human-written comments, even when they share the assistant's review.

Recheck the review's state before modifying it; the human may submit at any time.
A draft is a `PENDING` `PullRequestReview`. While pending, use GraphQL:

- Add: `addPullRequestReviewThread` with `pullRequestReviewId`, `body`, `path`,
  `line` (range end), and `side: RIGHT`; for ranges also pass `startLine` and
  `startSide: RIGHT`.
- Reply: `addPullRequestReviewThreadReply` with `pullRequestReviewId`,
  `pullRequestReviewThreadId`, and `body`, keeping replies in your pending review.
- Edit: `updatePullRequestReviewComment` on the existing comment's ID.
  Delete and re-add only when its anchor must move and the review is pending.

Never use REST's create-review-comment endpoint: it publishes and notifies.
Never call `submitPullRequestReview` or `deletePullRequestReview`; submission
and discarding belong to the human.

After each addition, verify the returned thread/comment and comment count;
success alone is not proof. Finish by confirming the review is still `PENDING`
and nothing intended to stay private has published.

### Once a review has been submitted

For any non-`PENDING` state:

- Do not add threads or rely on a particular mutation error or return value
  to detect submission.
- Make authorised wording edits in place with `updatePullRequestReviewComment`;
  published edits are visible, not private drafts.
- Do not create another pending review without the human's explicit request.
- Never delete and recreate a published comment to move its anchor. Keep it
  in place, remove suggestions that depend on a different anchor, and describe
  the fix in prose.

## Judging another reviewer's comments

When asked to assess another reviewer's comments, read each comment's `diff_hunk`
and surrounding code, not just its body.
Post a plain verdict as its own sentence using the pending-reply rules above.
Give the human a one-line reason per verdict outside GitHub, flagging conflicts
with written repository instructions so they can overrule it.

## Ordering

By file in diff order, then line ascending, or by severity, never mixed.
When a comment is removed, leave the remaining numbers as they are.

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
