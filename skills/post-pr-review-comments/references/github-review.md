# GitHub review procedures

Read this before planning or performing GitHub comment/review operations or
assessing another reviewer's comments. It does not authorise posting.

## Posting to GitHub

Use a small scratchpad script invoking `gh`, in an available runtime, with a
`--dry-run`; avoid one-off shell mutations. Before deleting, list targets and
exclude human-written comments, even when they share the assistant's review.

Before adding threads or replies, find the authenticated user's `PENDING`
`PullRequestReview` for this PR and use its ID. If none exists, ask the human
for approval to create one. Keep new comments local until that draft exists.
Recheck its state before modifying it; the human may submit at any time.
While pending, use GraphQL:

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

## Once a review has been submitted

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

When asked to assess another reviewer's comments, read each comment's diff hunk
(`diff_hunk` in REST, `diffHunk` in GraphQL) and surrounding code, not just its body.
Post a plain verdict as its own sentence using the pending-reply rules above.
Give the human a one-line reason per verdict outside GitHub, flagging conflicts
with written repository instructions so they can overrule it.
