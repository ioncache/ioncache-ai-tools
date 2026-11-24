# Writing quality

This contract is for implementers and fixers, not reviewers, adjudicators or
validators. Apply the supplied standards to your own authorized edits. This is
not another review pass, permission to discover extra work, or authority to
adjudicate findings. A fixer corrects only validated, in-scope `Act` findings;
an implementer follows the approved task. Preserve explicit limits and unrelated
edits. File hints are starting points, not fences on necessary dependencies.

Before editing, read and reconcile the surrounding context: complete affected
functions and contracts, callers, tests, related documentation and duplicate
statements. Do not work only from cited line slices. Trace enough context to
keep the correction coherent without performing unrelated cleanup.

The supplied standards contain the same category source contents used by review
packets, without discovery protocols or assessment assignments. Apply each
standard only to the kinds of changes it describes. General standards adapt to
the actual language and framework. Vitest conventions apply only to Vitest
suites. JSDoc applies only to JavaScript, including evidenced embedded JavaScript,
never to TypeScript or other languages.

Before writing, resolve actual language and project evidence with the supplied
helper command. Replace its context path with your own private JSON file outside
the repository. Use `files` and `language_inventory` in the review packet format:
each inspected path maps to `{"languages": ["python"], "evidence": "what was read"}`.
Record all actual embedded languages; leave unknown files unclassified rather
than guessing. For implementation, also inventory applicable project instructions
as same-purpose `project_sources` or `project_categories` using PACKETS.md's
record format, preserving scope and exceptions. Fixers already receive the
saved phase's project standards and must not replace them.
Refresh this context when necessary dependencies introduce another language or
kind of change. Deferred language standards are not a waiver; resolve them
before writing that language. Missing evidence is a reported guidance gap, not
permission to impose another stack's conventions or stop unrelated work.

Before reporting, self-check your actual diff against the applicable supplied
standards, the approved scope and the surrounding contracts. Correct issues
introduced by your own edits within that scope and the existing allowance.
Run the smallest relevant checks. Do not weaken assertions, change acceptance
criteria or claim a check passed without running it. Self-checking does not
replace independent review, adjudication or verification.

In the existing report's evidence, record the standards and source identities
you applied, the context reconciled, the diff self-check and commands/results.
Disclose unresolved guidance or verification gaps. Do not add an approval gate,
invent additional retries or claim that a self-check proves convergence.
