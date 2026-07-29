---
name: documentation-writing
description: Use when writing or updating documentation, READMEs, commit messages, or code comments, for sentence style, punctuation, and emphasis rules.
---

# Documentation Writing

Rules for writing and updating documentation.

## Core Principles

1. Write for a technical human reader, not an AI scanner
2. Use standard keyboard punctuation only
3. Be direct and precise, avoid filler

## Never Use Em Dashes

Never use em dashes anywhere: prose, headings, commit messages, code comments,
or any other output. Almost no one writes with em dashes on a computer because
there is no dedicated key for them. They read as unnatural and are explicitly
prohibited.

Use standard alternatives instead:

- Replace "X, Y" or "X: Y" for what would have been "X, Y", depending on the
  relationship
- Replace "Step 1: Do thing" for what would have been "Step 1, Do thing"
- Replace "Feature (completed in #N)" for what would have been
  "Feature, completed in #N"
- Replace table cells using "-" for N/A, not an em dash

## Sentence Style

Keep sentences short and direct. One idea per sentence.

Use active voice. Write "the sanitizer matches field names" not "field names
are matched by the sanitizer."

Avoid AI-style filler phrases. Never write "it is worth noting that", "this
ensures that", "please note that", "it should be noted", or similar padding.
State the point directly.

## Emphasis

Reserve bold for genuinely critical terms or warnings. Do not bold phrases for
visual decoration or to create fake structure. When everything is emphasized,
nothing is.

## Checklist

- [ ] No em dashes anywhere in the output
- [ ] Punctuation uses only standard keyboard characters (comma, semicolon,
      colon, hyphen)
- [ ] Headings use colons, not dashes, to introduce a subtitle or step label
- [ ] Sentences are short and use active voice
- [ ] No AI filler phrases
- [ ] Bold used sparingly, only for genuinely critical content
