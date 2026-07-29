---
name: verify-unresolved-pr-comments
description: Analyze unresolved review comments and PR-level feedback on the active PR and return a triage chart with severity, fix recommendation, suggestion validity, and required action. Read-only, do not edit files, resolve threads, post replies, or run tests.
---

Follow these steps exactly and in order. Do not substitute your own approach,
output format, or API calls. Do not produce any output until all data-gathering
steps are complete.

## Operating mode

This prompt is read-only triage. Do not modify files, apply patches, stage
changes, commit changes, run formatters, run lint, run tests, resolve review
threads, or post PR comments. On success, the only output should be the triage
table and the one-line summary requested below. On failure to retrieve review
thread data, do not produce a table.

When a review comment is valid, recommend the minimal fix in the table only. Do
not implement the fix. When a review comment is invalid or should not be fixed,
write the exact response the developer can post manually. Do not post it.

## Fetch the PR and collect review feedback

The goal of this step is to retrieve all review feedback on the active pull
request, including:

- Inline review threads with their resolution status (`isResolved`)
- Review-level bodies, such as requested-changes or commented reviews
- PR-level conversation comments (issue comments on the PR)

Resolution status is required for inline review threads, without it you cannot
distinguish resolved from unresolved threads. PR-level comments and review
bodies do not have thread resolution status, so evaluate them separately as
described below.

Inspect the available integration surfaces for GitHub PR access, such as tools
or toolsets, MCP servers and resources, skills or slash commands, plugins, and
custom agents or subagents. Use an internal capability only when it returns
review-thread resolution state and PR-level comments, otherwise it cannot be
the source of truth for the full PR feedback set. If no such capability is
available, or it cannot expose thread resolution status, fall back to the CLI
approach below.

### CLI fallback

**Constraints for this option:**

- Do NOT use `/pulls/.../comments` to fetch review threads, it does not expose
  `isResolved`. Use the GraphQL API for review thread data.
- Do not guess the PR number or repository owner/name, retrieve them as shown
  below.

Get the active PR number from the current branch and the repository owner/name:

```bash
gh pr view --json number,headRefName,reviewDecision
gh repo view --json nameWithOwner
```

Pass `OWNER`, `REPO`, and `NUMBER` as variables via `-F`. Leave cursor variables
unset on the first request. On follow-up requests, pass the relevant `endCursor`
value back with `-F threadsCursor=END_CURSOR` or `-F reviewsCursor=END_CURSOR`
or `-F prCommentsCursor=END_CURSOR`:

```bash
gh api graphql \
  -F owner=OWNER \
  -F repo=REPO \
  -F number=NUMBER \
  -f query='
query($owner: String!, $repo: String!, $number: Int!, $threadsCursor: String, $reviewsCursor: String, $prCommentsCursor: String) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      reviewDecision
      reviewThreads(first: 100, after: $threadsCursor) {
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
          id
          isResolved
          comments(first: 100) {
            pageInfo {
              hasNextPage
              endCursor
            }
            nodes {
              author { login }
              path
              line
              body
            }
          }
        }
      }
      reviews(first: 100, after: $reviewsCursor) {
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
          author { login }
          state
          body
          submittedAt
        }
      }
      comments(first: 100, after: $prCommentsCursor) {
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
          author { login }
          body
          createdAt
        }
      }
    }
  }
}'
```

Nested comment pagination requires a follow-up query per review thread. If a
thread's `comments.pageInfo.hasNextPage` is true, pass that thread's `id` and
the comments `endCursor` into this query until all comments for that thread are
retrieved:

```bash
gh api graphql \
  -F threadId=THREAD_ID \
  -F commentsCursor=END_CURSOR \
  -f query='
query($threadId: ID!, $commentsCursor: String) {
  node(id: $threadId) {
    ... on PullRequestReviewThread {
      comments(first: 100, after: $commentsCursor) {
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
          author { login }
          path
          line
          body
        }
      }
    }
  }
}'
```

If any connection returns `pageInfo.hasNextPage: true`, keep paginating until
all review threads, thread comments, review bodies, and PR-level conversation
comments have been retrieved.

If review threads with `isResolved` status cannot be retrieved, stop and return
this plain failure message instead of the triage table:

`Failed to verify unresolved PR comments because review thread data with isResolved status is not available in this session. Rerun this command with read-only gh CLI access for the GraphQL fallback.`

## Filter and evaluate

Filter inline review threads to `isResolved: false` only. Discard all resolved
threads, do not read or evaluate them.

Include feedback from all authors (bots, human reviewers, etc.) among the
unresolved threads. Also evaluate review-level bodies and PR-level conversation
comments when they contain actionable feedback and have not been superseded by
later comments or current code changes. Include requested-changes reviews, or
the tool's equivalent blocking review feedback, when the pull request is still
blocked by them. Note the author on each row so it's clear who raised each
issue. For feedback not tied to a specific file or line, use `-` in the File
column.

For each unresolved comment, evaluate it against the current PR diff, changed
files, or patch content provided by the available tool or API:

- Read the relevant section of the diff carefully, do not rely on the comment
  description alone.
- Do not recommend defense-in-depth for scenarios that can't happen through
  normal code paths (for example: null-guarding values guaranteed by the
  database schema, or adding fallbacks for data the framework already
  validates).

Produce a markdown table with these columns:

| # | Author | File | Issue Summary | Severity | Fix? | Suggestion Valid? | Required Action / PR Response |
| --- | ------ | ---- | ------------- | -------- | ---- | ----------------- | ----------------------------- |

Rules for each column:

- **Severity**: High / Medium / Low based on impact (High = correctness bug or
  security; Medium = reliability, reproducibility, or operational risk; Low =
  cosmetic or edge-case tooling)
- **Fix?**: Fix or No fix. If the suggestion is valid and targets new code
  introduced in this PR, the answer is always Fix. "No fix" is only for
  comments that are invalid, target pre-existing code unchanged by the PR, or
  recommend defense-in-depth for impossible scenarios. This column is a
  recommendation only, do not make file edits.
- **Suggestion Valid?**: Yes / Partially / No, with a one-line reason if
  Partially or No.
- **Required Action / PR Response**: If fixing, state the minimal change for
  the developer to make later. If not fixing, write the exact response the
  developer can post in the PR thread. Do not post responses or mark threads
  resolved.

After a successful table, provide a one-line summary: how many to fix, how many
to respond-no-change, and any deferred items.
