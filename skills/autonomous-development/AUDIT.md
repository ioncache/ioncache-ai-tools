# PR process audit

This contract applies to use of the autonomous-development skill, not to
development of the plugin itself. Publication requires the approved manifest's
`publish_audit: true`, the enabled `autonomous-development-audit` feature, and
native permission. Missing permission in an older manifest means no publication.

## Storage and lifetime

Publish only `AUDIT.md` and `audit.json` on the run-owned branch
`ioncache-audit/<run-id>/<pr-id>` in the same GitHub repository. The first commit
has no implementation ancestors; later versions fast-forward that audit branch.
The implementation worktree, index, HEAD and review fingerprint remain unchanged.
This adapter supports github.com HTTPS and SSH repository URLs, not another
hosting provider, GitHub Enterprise Server, or cross-repository PRs.

Each publication adds a PR comment linking both files by immutable commit ID.
The initial comment follows draft creation. A final comment follows full-PR
review, the accepted commit and any approved UI evidence, before readiness.
Retain both comments and previous commits. Do not delete the audit branch as
part of ordinary worktree cleanup. Repository retention and access policies still
apply; this is not a separate archival or tamper-proof service.

Keep the private run store as well: new runs retain complete ledgers and objects
under its `reviews/` directory, independently of all worktrees. After cleanup,
produce a local historical export with a reviewed narrative:

```sh
python3 "/absolute/plugin/scripts/development_audit.py" archive "/private/run" \
  --pr "<plan-pr-id>" --public "/private/public-narrative.json"
```

This reads saved snapshots and history, writes identity-addressed files under
`<private-run-store>/archives/`, and performs no publication or live-worktree
acceptance. It cannot substitute for a reserved audit assignment. Legacy migrated
ledgers stay at their external migration destination; retain that storage too.

## What is exported

The helper mechanically projects:

- Approved content identities, the exact code commit and review fingerprint.
- Assignment IDs, roles, attempts, outcomes and report/worker identity hashes.
- Available review ledgers' iteration counts, findings, observations, decisions,
  fix results, check outcomes, event ordering, timestamps and evidence hashes.
- Execution limits, consumed assignments and explicit unavailable metrics.
- Requested native models/efforts and separately observed actual identities,
  their observation source and an evidence digest, tied to assignment/role.
  Control calls are run-level observations, not invented assignments.

It does not copy input documents, source blobs, raw report bodies, prompts,
private paths, diagnostic strings or arbitrary event reason/evidence fields.
Review progress checkpoints remain private and are not exported as evidence.
Model observations project only the fields above, not their raw private files.
Their export-time snapshot stays fixed during acknowledgment; later observations
do not revoke approval of unchanged published bytes.
Model IDs, including private deployment identifiers, still need publication
review. A selected alias does not prove which model ran; null actual values and
unavailable model records remain gaps, not inferred successes.
Unavailable or abandoned histories remain explicit gaps. No counts or findings
are reconstructed from missing evidence. Worker hashes permit comparison of
reported identities, not proof of independent contexts.

The assigned worker separately writes publication-safe narrative JSON:

```json
{
  "summary": "What was implemented and how the process ended.",
  "method": "Review coverage, criteria, configuration, model observations and limitations.",
  "verification": "What checks established and what remains unverified.",
  "findings": [
    {
      "review": "<review-run-id>",
      "id": "F001",
      "summary": "A description safe for this repository's audience.",
      "rationale": "Validation and decision history, including why it was fixed or rejected."
    }
  ],
  "regressions": [],
  "limitations": ["Any material evidence gaps."]
}
```

Account for every finding in every available ledger, including rejected and
ignored candidates. Preserve meaningful decision changes, not just the last
label. Describe effective review coverage, checks and selection choices from
actual records; do not infer success or observable model identity from defaults.
The helper validates finding references and completeness, not narrative truth.

An established regression relationship has `cause` and `effect` objects, each
with `review` and `id`, plus `basis` (`observed` or `inferred`) and public `evidence`.
Both findings must exist. Do not invent causal relationships from chronological
proximity. An empty list means no relationship was supplied, not that none occurred.

## Export, inspect, publish

Resolve `../../scripts/development_audit.py` relative to this skill directory.
Use it only for the current reserved `audit-initial` or `audit-final` assignment.
Write the narrative under `<store>/reports/<assignment-id>/public.json`.

```sh
python3 "/absolute/plugin/scripts/development_audit.py" export "/private/run" \
  --public "/private/run/reports/A0007/public.json"
```

The helper writes two files under that assignment's private `audit/` directory
and returns their combined identity. Read both complete files. Check publication
scope, secrets, personal data, private-source references, accuracy and missing
evidence. Revise the public narrative and export again if necessary.
This semantic review is required: allowlisted structure is not an automatic
secret detector, and free-form narrative can still disclose sensitive information.

Publish only after reviewing the exact bytes:

```sh
python3 "/absolute/plugin/scripts/development_audit.py" publish "/private/run" \
  --approved "<exported-bundle-identity>"
```

This is the assigned worker's approval of an export already authorized by the
human-approved run contract, not another mandatory human prompt. The identity
binds both files, not just the JSON. Changed evidence or edited output requires
a new export and inspection. Neither the exporter nor publisher edits `RUN.json`.
Return the complete publisher receipt as the development report's `data`.

The publisher uses a temporary private Git repository, an explicit non-force
push to the audit ref, and authenticated `gh api` calls. It checks the PR's
repository, owned branch, open state and exact code commit before publication.
Repository identities are case-insensitive; branch names remain case-sensitive.
It resolves the authenticated actor through GraphQL before pushing, supporting
both user and GitHub App installation tokens without relying on `GET /user`.
Before pushing, it verifies that the Git commit contains exactly the two
approved files with their approved bytes. Filters or commit hooks cannot silently
change the published bundle or add files.
It respects Git signing configuration. Branch rules or missing credentials
produce failure, not a fallback to another repository or publication destination.

## Recovery and limitations

If a response is lost, inspect the existing export, audit branch and PR comments.
Repeating the same publication reuses identical committed files and the matching
comment by the authenticated caller. Markers include the run, assignment and
export identities. Different assignments retain distinct publication records.
The helper scans all comment pages. It does not overwrite another person's
comment or a modified matching comment.

Resolve credentials, signing, filter/hook compatibility or permitted branch-rule
issues without bypassing required safeguards, then retry the same
known operation. Unknown live workers still require native shutdown/reconciliation
before retirement. A blocked development assignment resumes as a counted retry;
initial and final publication have separate attempt keys. Do not reset allowances
or change the destination to evade a denial. If evidence/code changed, use the
existing counted review reconciliation path before publishing a new final audit.
If the approved operation remains impossible within its limits, preserve the
initial PR and private evidence and report incomplete work.

The bundle records its publication assignment as reserved: it is captured before
the controller acknowledges publication. Its PR comment and retained receipt
record that external effect. It does not claim subsequent readiness or merging.
Native tool transcripts, complete control-event history, actual model usage,
cost and reliable worker durations are not automatically captured.
Original private evidence remains useful for a deeper authorized investigation.

Protocol references:
https://git-scm.com/docs/git-push
https://cli.github.com/manual/gh_api
https://docs.github.com/en/rest/issues/comments
https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation
