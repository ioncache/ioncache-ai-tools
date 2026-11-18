# GitHub review procedures

Read this before planning or performing GitHub comment/review operations or
assessing another reviewer's comments. It does not authorise posting.

## Posting to GitHub

Use a small scratchpad script invoking `gh`, in an available runtime, with a
`--dry-run`; avoid one-off shell mutations. Before deleting, list targets and
exclude human-written comments, even when they share the assistant's review.

Never call `submitPullRequestReview` or `deletePullRequestReview`; submission
and discarding belong to the human.

Choose the method from the request:

- "Add comments to a review": prefer a pending review for new inline threads.
  This is a recommendation, not a condition for all posting. Honour a request
  to publish new comments directly instead.
- "Reply" or "respond" to existing published review comments: post directly to
  those threads. The request authorises the replies; do not ask for a separate
  posting approval or require a pending review.
- "Draft a reply", "suggest a response", or "keep it pending": preserve the
  requested draft visibility instead of publishing. A question alone does not
  authorise posting.

### Recommended pending-review workflow

When using this workflow, find the authenticated user's `PENDING`
`PullRequestReview` for this PR and use its ID. If none exists and creating one
is not already authorised, ask the human for approval. Keep comments intended
as drafts local until that draft review exists.
Recheck its state before modifying it; the human may submit at any time.
While pending, use GraphQL:

- Add: `addPullRequestReviewThread` with `pullRequestReviewId`, `body`, `path`,
  `line` (range end), and `side: RIGHT`; for ranges also pass `startLine` and
  `startSide: RIGHT`.
- Draft reply: `addPullRequestReviewThreadReply` with `pullRequestReviewId`,
  `pullRequestReviewThreadId`, and `body`. Use this for unpublished threads or
  when the human wants the reply kept in a pending review, not as a prerequisite
  for replying to an existing published comment.
- Edit: `updatePullRequestReviewComment` on the existing comment's ID.
  Delete and re-add only when its anchor must move and the review is pending.

Do not use the direct-publication endpoints below for comments intended to
remain drafts.

After each pending-review addition, verify the returned thread/comment and
comment count; success alone is not proof. Finish pending-review changes by
confirming the review is still `PENDING` and nothing intended to stay private
has published.

### Directly publishing new inline comments

When the human wants new inline comments published directly, use REST
`POST /repos/{owner}/{repo}/pulls/{pull_number}/comments` with `body`,
`commit_id`, `path`, `line`, and `side`; include `start_line` and `start_side`
for a range. Use the current PR head and a valid diff anchor. This publishes
and notifies rather than staging a comment in a pending review.

Read back the created comment and verify its body and anchor. Direct comment
publication does not authorise submitting or discarding a pending review.

GitHub's direct-comment endpoint:
https://docs.github.com/en/rest/pulls/comments#create-a-review-comment-for-a-pull-request

### Replies to existing published review comments

Follow an instruction to reply or respond by posting to the existing published
thread, unless the human asks for a draft. Do not create a pending review just
to reply, or make replying conditional on finding one. Replies publish directly
and can notify participants; this does not authorise submitting any pending review.

Read the existing thread and confirm the target comment belongs to the intended
PR and is published. Use REST
`POST /repos/{owner}/{repo}/pulls/{pull_number}/comments/{comment_id}/replies`
with `body`. Supply the top-level review comment's numeric REST ID, not its
GraphQL node ID or a reply's ID. If responding to a reply, use its
`in_reply_to_id` to locate the top-level comment; GitHub does not support replies
to replies through this endpoint.

Read back the created reply and verify its body and `in_reply_to_id` against the
intended thread. Do not require the resulting comment to belong to a pending
review.

GitHub's reply endpoint and top-level-comment requirement:
https://docs.github.com/en/rest/pulls/comments#create-a-reply-for-a-review-comment

## Once a review has been submitted

For any non-`PENDING` state:

- Do not add new inline threads to that submitted review or rely on a particular
  mutation error or return value to detect submission. Authorised replies to
  existing published comments use the direct-reply procedure above.
- Make authorised wording edits in place with `updatePullRequestReviewComment`;
  published edits are visible, not private drafts.
- Do not create another pending review without the human's explicit request.
- Never delete and recreate a published comment to move its anchor. Keep it
  in place, remove suggestions that depend on a different anchor, and describe
  the fix in prose.

## Judging another reviewer's comments

When asked to assess another reviewer's comments, read each comment's diff hunk
(`diff_hunk` in REST, `diffHunk` in GraphQL) and surrounding code, not just its body.
When posting is authorised, post a plain verdict as its own sentence using the
existing-thread reply rules above. Assessment alone does not authorise posting.
Give the human a one-line reason per verdict outside GitHub, flagging conflicts
with written repository instructions so they can overrule it.
