---
name: claim-evidence
description: Checks behavioral claims against complete, current source evidence. Use before writing code comments, documentation, commit or pull request text, or answers describing code behavior, and when a claim-evidence checkpoint blocks a tool.
---

# Claim evidence

Complete delivery is a prerequisite, not proof of comprehension or truth.
Snippets, diffs, summaries, previous prose, and tests do not establish coverage.

## Read policy

- Files of 400 lines or fewer require whole-file read requests, without ranges.
- Larger Python files support complete functions, methods, classes, and
  top-level statements. Use parser-produced boundaries, not guessed limits.
- Other languages, unsupported syntax, and uncertain boundaries require the
  whole file. Do not substitute brace counting.
- A branch or loop is not evidence for a claim about its enclosing function.
- Read coordinating callers and relevant dependencies for cross-unit claims.
- Read registration statements for claims about callback registration.

## Evidence reader

Resolve `../../hooks/scripts/claim_evidence.py` relative to this skill directory.
Use its quoted absolute path in standalone commands: no pipes, redirects, or chaining.

```text
python3 "/absolute/plugin root/hooks/scripts/claim_evidence.py" units source.py
python3 "/absolute/plugin root/hooks/scripts/claim_evidence.py" read source.py
python3 "/absolute/plugin root/hooks/scripts/claim_evidence.py" read source.py --unit 410:480
```

`units` reports the hash and exact unit IDs; `file` selects the entire file.
The reader emits at most 2,000 source characters per page. Follow its `pages`
count with `--page N --sha256 HASH`, retaining the same unit and snapshot.
Read every page before relying on the unit. If the source changes, restart.
Only an active post-tool hook grants delivered coverage. Running the reader
outside the host or saving its output to a file grants nothing.
Native reads are not credited; use this reader first to avoid duplicate reads.

## Checkpoint workflow

1. Submit the intended edit or publication call. A missing checkpoint denies
   execution and saves its exact normalized request to a private JSON file.
2. Run `prepare REQUEST.json` through the helper. Read all its `pages` with
   `--page N --sha256 HASH`. Its hash is the review fingerprint. The inventory
   includes outgoing text, message files, and staged commit changes.
3. Read complete evidence for each behavioral claim. Trace success, failure,
   early-return, and ordering paths. Verify relevant dependency behavior.
4. Review every outgoing line. Prefer a separate reviewer. Do not classify a
   behavioral assertion as non-behavior merely to pass the gate.
5. Save `REQUEST.review.json` beside the captured request. This private review
   file is exempt from the edit checkpoint so review does not recurse.
6. Run `approve REQUEST.json --review REQUEST.review.json` through the helper,
   wait for the post-tool checkpoint receipt, then retry the call unchanged.

Review format:

```json
{
  "fingerprint": "from prepare",
  "reviewer": "reviewer identity",
  "classifications": [
    {
      "artifact": 0,
      "start": 1,
      "end": 1,
      "kind": "behavior",
      "reason": "Checked the complete unit and its exits",
      "claims": [{
        "text": "Exact outgoing claim",
        "reason": "The cited control flow establishes the claim",
        "evidence": [{
          "path": "/absolute/source.py",
          "sha256": "from reader",
          "unit": "file",
          "lines": [10, 20]
        }]
      }]
    }
  ]
}
```

Use `kind: "non-behavior"` with a specific rationale and no claims for code
or prose that makes no behavioral assertion. Classifications cover every
artifact line exactly once, including blank lines. Split mixed blocks.
Evidence must remain current when the original call is retried.
For new behavior, make the code-only edit and reread before adding prose.

## Limits

Review verdicts are attestations, not semantic proofs. Verify external APIs
against current authoritative evidence and decisions against their records.
Omit or narrow claims whose coverage cannot be established.
The plugin does not buffer chat. Stop requests one correction, then permits
completion to avoid loops; it cannot retract already displayed text.
See [guard limitations](../../README.md#claim-evidence-guard).
