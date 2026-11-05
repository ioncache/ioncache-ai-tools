---
name: write-pr-descriptions
description: Writes and edits pull request titles and descriptions for human reviewers. Use when asked to draft, update, shorten, or check a PR title, body, description, or summary.
---

# Write PR Titles and Descriptions

Explain the problem and why the change solves it. Write for human reviewers.

## Preparation and structure

1. Establish the requested scope. Read the relevant diff and issue or background;
   verify claims and ask for missing reasoning rather than inventing it.
2. Find the repository's applicable PR template and title conventions. Do not
   assume a template path or sections. Ask if the applicable template is ambiguous.
3. Keep the template's sections in order. Remove author-guidance comments and
   `(optional)` from headings; use `N/A` for sections that do not apply.
4. Preserve existing checklist text, including references to tests and docs;
   mark items only when supported by evidence.
5. Without a template, use Overview and Details, with no mandatory subheadings.
   In all cases, allow brief prose and bullets anywhere; no Overview sentence limit.
6. Follow repository title conventions. Concisely name the problem being fixed
   or intended change. Edit an existing title only when requested.

## Body content

Cover the issue, how it happens, its effect, the fix, and relevant non-code background.
These are content requirements, not mandatory headings. Details is an explanation,
not a diff specification or file inventory.

Pair every how-it-works statement with its reason in the same sentence or bullet:
why the approach is needed or why the behavior matters. Preserve reasoning and
benefit when shortening. Avoid repetition, but retain necessary explanations
even when the checklist mentions their topic.

Define unfamiliar domain terms and internal shorthand, or avoid them. Supply
context rather than assuming whole-codebase knowledge. Question-based groups and
`condition: outcome` bullets are optional, used only when they help human readers.

Include status codes, error codes, or payloads when needed to specify behavior,
not as an exhaustive API catalog; explain their purpose too. Within a PR body,
reserve fenced code for payloads or responses a reviewer must match to a schema.

Attribute behavior to the code, not the PR. When describing the PR's action,
write "This PR updates the code so that...", never "This PR records..." or
"This PR does X".

## Style and exclusions

- Keep prose and bullets brief. Use bullet lists, never comma-separated lists.
- Use natural capitalization and useful punctuation; short forms are fine.
- Keep each body paragraph and bullet on one unbroken line; do not hand-wrap.
- Use complete URLs for issues, PRs, and docs, including template references.
- Leave out file names, hook names, implementation shape, cosmetic detail,
  unsolicited reassurance, and review-process narration.
- Do not report tests, documentation updates, linting, or formatting in authored
  summary content. Preserve the template checklist exception above.
- Omit lockfile changes unless the lockfile is the entire change.
- Never add "Review fixes" or "Post-review changes" sections or generated-by footers.

## Editing an existing PR

Change only what was requested. Preserve unrelated wording and formatting, even
when template cleanup would otherwise apply. Flag other stale content without
editing it; never regenerate the body wholesale.

1. Fetch the current title and body before drafting.
2. Immediately before posting, re-fetch the body and check its edit history for
   changes since drafting, including edits since the agent's last post.
   Re-fetch the title if changing it.
3. Stop and ask if intervening edits conflict with the request or current content
   or history cannot be checked.
4. Apply the edit to the latest version. After posting, read back to verify the
   result and preservation of unrelated content.

## Before posting

- [ ] Title follows repository conventions; an existing title changes only on request
- [ ] Template sections and checklist are preserved, or the fallback is used
- [ ] Problem, cause, effect, fix, background, and benefit are clear; each behavior has a reason
- [ ] Short prose and bullets; terms defined, full URLs, no manual wrapping
- [ ] No excluded content, except preserved checklist text and lockfile-only changes
- [ ] Existing body and edit history refreshed; only requested edits applied, author edits preserved

## Worked example without a template

Title: `Resume interrupted imports without duplicating entries`

```markdown
# Overview
When an import stops partway through, restarting it repeats completed entries because progress is not retained. Users must then remove duplicates before relying on the imported data.

## Details
This PR updates the import code so that:

- each import retains its progress so restarting it can skip entries that were already saved
- restarting uses the original uploaded file so saved progress cannot accidentally be applied to a different file
- an interrupted import stays available to resume so users can finish without uploading the file again
```
