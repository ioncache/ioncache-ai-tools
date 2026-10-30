---
name: post-pr-review-comments
description: Turns review findings into GitHub PR review comments in a pending draft review. Use when a human is driving a PR review and wants comments written up, edited, and added to GitHub; never submits the review.
---

# PR Review Comment Process

How Claude turns review findings into posted GitHub PR comments, when a human
is driving the review conversationally. This is the write-up-and-post phase,
not the finding-production phase; see the `review-code` skill for how findings
themselves get produced.

Kick off a review by pasting a PR-specific prompt that names the PR, the base
branch, any sibling PRs to treat as context only, and anything carried over
from a previous PR's review that bears on this one (an unresolved defect, a
doc claim to re-verify). This document is the stable process both that prompt
and Claude should follow; keep PR-specific content out of it.

## Process

1. Run the automated review, wait for it to finish, post nothing yet.
2. Write findings as comments into a markdown file on disk in the session
   scratchpad. Tell the user the full path.
3. Every change to a comment after that is a targeted edit to that file. Never
   re-render the whole list in the terminal. Never reword a comment the user
   hasn't asked to change.
4. A question from the user gets a plain-text answer and nothing else. No
   file edit until they say "update" or "proceed", a question is not
   approval.
5. When the user says a comment is wrong, say whether the finding still
   stands without the part they rejected before touching anything. If it
   doesn't, propose dropping it.
6. When the user corrects one comment for a systemic reason (wording,
   anchoring, sourcing), check every other comment in the file for the same
   fault before reporting done, and say which ones also changed. Don't make
   the user find the same problem twice.

## What counts as a finding

Only ways the system misbehaves for a member, an operator, or the business,
or a runbook/doc that can't be followed as written. Not findings: duplication,
"reuse the existing helper," style, comment wording alone, log-message noise,
speculative guards against operator typos. If a scenario needs something the
code and docs never establish, it's invented, drop it.

Findings on code outside the diff are allowed only when this PR changes an
input that code depends on, so the failure wouldn't exist without this PR.
Say so plainly in the comment ("not introduced here, but this is what makes
it reachable"). Pre-existing problems the PR doesn't touch are out of scope.

Don't flag a missing guard for a shape the code never actually produces, check what calls the function before assuming a defensive check is missing.
"Another helper does it defensively" is not a reason on its own.

A missing test is a finding only when the untested rule is the business logic
the PR turns on and nothing else covers it, and only if the branch doesn't
carry its own stated test policy (some prototype branches deliberately skip
new suites; check for that before flagging).

## Anchoring

Every comment attaches to lines inside a diff hunk of this PR, added or
context lines, never lines that only exist in the old version. Check the
actual hunks before assigning a range; don't infer from memory of an earlier
read, the PR may have moved since.

For prose comments without a suggestion block, anchor to the whole construct
the finding is about (a function, a block, a JSX element), not one arbitrary
line, so the reader has the surrounding context. Write the anchor as
`path:start-end` in the comment's own heading in the working file. A single
line is correct only when the finding really is about that one line.
Comments with suggestion blocks use the smallest changed range, as described
under GitHub suggestion blocks.

For a cross-file finding, anchor on the diff line that introduces the
behaviour and say only that the effect shows up elsewhere. Never chain
`file:line` references across files inside one comment.

## Wording

Every comment: single sentences, one per line, blank line between, one point
per sentence. Three or four short sentences is normal, go longer only when
the finding has two genuinely distinct failure paths or needs a documentation
quote.

Brevity means shorter sentences, not the same sentences spread across more
lines, splitting a block across five lines is the same wall of text with
gaps in it.

Every sentence has to be self-contained: introduce a noun phrase before
referring back to it. No "six things" without listing them, no "the costly
one" without naming the set, no "in that window" without having described the
window. A bare count is worse than naming the items or leaving them out,
because it promises the reader something and then withholds it.

Conversational first person, "it looks like," "I think," "maybe X should
Y?" are examples of the tone, not required qualifiers or a checklist to work
through one of each. Never repeat one verbatim across a review. Never write
"just want to call out."

Cut defensive filler. Never add a sentence that pre-empts an objection nobody
raised or patches a mistake from an earlier draft. Every sentence should
state the problem, its impact, or the recommendation.

No colourful idiom, "the case that bites," "rears its head," "the smoking
gun." No developer writes that way and it reads as generated text; state the
case plainly instead. No review-bot language either ("load-bearing,"
"exposes a bad path").

No triage markers or legends in a posted comment ("follow-up ok," a severity
tag). GitHub has no legend for the reader to consult. Keep triage
classification in the working file only.

Describe the scenario in business terms, which member, in what state, what
the system does, and why that's wrong, then what should hold instead. End
every comment with a recommendation about the required behaviour. Don't
prescribe the exact code change unless it's trivial. When a fix belongs
upstream (a backfill must guarantee X, or exclude the member instead), say
that as its own sentence.

No code identifiers unless naming a route, flow, or field by role helps the
reader find it. No line numbers into other files.

Follow the repository's spelling convention. Identifiers and quoted
third-party text keep their own spelling.

## Citing third-party documentation

Never state how a vendor library or service behaves from memory or from a
review agent's summary. Read the current documentation first.

Find the dependency or API version the codebase actually uses, including any
explicit client-level version override, before reading documentation.
Cross-check field names and shapes against the installed package's types or
version-specific schema. Prefer evidence for the pinned version when general
guides disagree, since guides sometimes use a newer version's names.

Read and link the human web page a person would open, never a `.md` variant
or a `?query=`-filtered view; those don't turn up in a web search and aren't
what the team reads.

Use the vendor's supported version-specific URL for the pinned dependency
version. Do not invent a version parameter. If no version-specific URL is
available, state which version the documentation covers and verify that the
claim applies to the pinned version.

Verify the anchor against the rendered page before citing it, fetch the page
and grep for `id="..."`. Do not guess a heading slug from the markdown
source. When a nested field has no direct anchor, link to its containing
section and explain which field to expand.

Quote the relevant sentence in a blockquote under the link. If the
documentation can't be reached, say the claim is unverified rather than
stating it. Never flag a deprecation or removal that only exists in a version
newer than the one pinned here, that's a dependency-upgrade sweep, not a PR
finding.

## GitHub suggestion blocks

Add a ` ```suggestion ` block only when the fix is a literal, same-file,
drop-in replacement for the exact anchored lines, no design decision, no
change in a different file. If the real fix needs a different file, code
outside this PR's diff, or a judgement call, leave the comment as prose and
say where the fix belongs.

Anchor a suggestion to the smallest range that actually changes, not the
smallest range that looks syntactically whole, GitHub only replaces what's
inside the anchor, it doesn't need the surrounding brackets reproduced. A
single-line anchor with a single-line replacement is normal.

Never bundle two independently-fixable issues into one anchor with one
suggestion touching both. Split them into separate comments on separate
minimal anchors. If the second is essentially the same finding, its body can
be as short as "same as the previous one, this one isn't read either."

Before posting: read the actual current file at that range, confirm the
suggestion block applied verbatim produces valid syntax, and confirm the
range lies entirely inside a diff hunk on the current PR head (PRs move, re-pull the diff, don't reuse an earlier fetch).

## Posting to GitHub

A draft review is a `PENDING` `PullRequestReview` node. While it's pending:

- Add a comment with the GraphQL `addPullRequestReviewThread` mutation,
  passing `pullRequestReviewId`, `path`, `line`, and, for a range, `startLine` with `side: RIGHT` / `startSide: RIGHT` on both ends.
- Never use the REST create-review-comment endpoint. It posts immediately
  and notifies the PR's author; a pending review doesn't.
- Never call `submitPullRequestReview` or `deletePullRequestReview` yourself.
  The human submits, and only the human decides to discard a draft.
- To change something already added, use `updatePullRequestReviewComment` on
  its id, don't delete and re-add unless the anchor itself has to move and
  the review is still pending.
- Reply to a comment from another reviewer (Copilot, a teammate) into your
  own pending review with `addPullRequestReviewThreadReply`, passing
  `pullRequestReviewId`, `pullRequestReviewThreadId`, and `body`, this keeps
  the reply unpublished until the human submits.
- Write this as a small Node script in the scratchpad driving `gh` through
  `child_process`, not one-off shell mutations per comment, with a
  `--dry-run`. Before any delete, list what's about to go and exclude
  comments the human wrote themselves; a human's own comments and Claude's
  sit in the same pending review.
- After every addition, verify the returned thread or comment and re-check
  the comment count to confirm it landed. A successful response alone is not
  proof that the comment was added.
- Verify at the end: the review still reads `PENDING`, and nothing meant to
  stay private has published.

### Once a review has been submitted

The human may submit a review outside the conversation, in the browser, at
any point, check the review's `state` before assuming it's still a draft.
Once it's `submitted` (any non-`PENDING` state), the rules change:

- Do not add threads to that review. Do not rely on a particular error or
  return value to detect that the review has already been submitted.
- For an authorised wording change, use `updatePullRequestReviewComment`
  to edit the existing comment in place. Edits to published comments are
  visible, not private draft changes.
- Do not create a second, separate pending review to hold new comments as a
  workaround unless the human explicitly asks for that. It's a genuinely
  different, more disruptive action than editing an existing conversation,
  and it should be their call, not a default fallback.
- If a finding's fix needs the comment to move to a different anchor, and the
  review is already published, don't delete the old comment and add a new
  one to simulate a move. Just leave the comment where it is. Drop any
  suggestion block that depended on the narrower anchor and state the fix in
  prose instead, a comment nobody can act on is better than one that
  briefly disappears from a review someone may already be reading.

## Judging another reviewer's comments

When asked to weigh in on Copilot's (or anyone else's) review comments: fetch
each comment's `diff_hunk` and read the surrounding code, never judge from
the comment body text alone. Reply with a plain verdict, "I think this is
valid" or "I don't think we need to do this", as its own sentence, posted as
a reply per the rules above. Then tell the user, outside GitHub, the one-line
reason for each verdict, and flag any case where the verdict goes against a
written repo instruction file so they can overrule it.

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
