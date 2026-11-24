# PR process audit

This contract applies to use of the autonomous-development skill, not to
development of the plugin itself. Publication requires the approved manifest's
`publish_audit: true`, the enabled `autonomous-development-audit` feature, and
native permission. Missing permission in an older manifest means no publication.

## Storage and lifetime

Publish the reviewed `AUDIT.md` and `audit.json` to the wiki of the repository
being modified. The wiki is a separate Git repository at
`https://github.com/<owner>/<repo>.wiki.git` (or its SSH equivalent).
Push only its existing default branch. Never create an audit branch in the
implementation repository. Its worktree, index, HEAD and review fingerprint
remain unchanged, and deleting an implementation branch does not delete the wiki.
This adapter supports github.com HTTPS and SSH repository URLs, not another
hosting provider, GitHub Enterprise Server, or cross-repository PRs.

Each publication creates separately named report and JSON files:
`Audit-PR-<number>-run-<run-id>-<assignment-id>-<bundle-identity>.md` and `.json`.
The initial publication follows draft creation. The final publication follows
full-PR review, the accepted commit and any approved UI evidence, before readiness.
The helper never overwrites different bytes at an existing publication path.
Retain both versions and the wiki history. Repository access, deletion and
retention policies still apply; the wiki is not tamper-proof archival storage.

Update the `Automated-Pull-Request-Audits` wiki page automatically. Create that
page if it is absent from an initialized wiki. Its table has `Date`,
`Pull request`, and `Audit records` columns, with one row per PR. Prepend the
newest publication and replace that PR's previous row, leaving other rows and
surrounding content intact. Use the UTC publication date, PR number/title/link,
and links to the report and JSON. Repeating the same publication leaves its
existing row in place rather than duplicating or reordering it.

Keep the index discoverable from the existing `Home.md` or `Home.markdown`.
If both exist, preserve and update both rather than relying on GitHub's
same-title selection. If Home has no index link, append
one between `ioncache-audit-index:start` and `ioncache-audit-index:end` HTML
comments. Create `Home.md` only if neither exists. Preserve all other Home content
and existing handwritten inline, reference-style or wiki index links instead of
duplicating them. An edited or malformed managed block requires preserving its
human notes outside the block before repair and retry. Home bytes are verified
along with the audit and index.

Update an `Audit` section in the PR body with `Report`, `Data (audit.json)`, and
`Automated Pull Request Audits` links, as in the wiki index. Preserve the rest of
the description, including an existing checklist and human notes. The helper
owns only the link block between `ioncache-audit:start` and `ioncache-audit:end`
HTML comments. Initial and final publication update that block; they do not post
conversation comments or require manual uploads.
The approved narrative can reference follow-up issues from
[FOLLOW_UPS.md](FOLLOW_UPS.md), making the audit the discovery index without a
per-run parent issue. Keep those references disclosure-reviewed. The `draft`
and `ready` workers, not the audit publisher, own the PR's Known issues not fixed
here section; never overwrite it when replacing the audit link block.

An initialized, writable wiki is a deployment prerequisite. GitHub documents
creating its initial page before cloning; enabling the repository's wiki setting
alone does not establish this capability. Preflight checks wiki initialization,
reachability and write access with read-only evidence before implementation.
PR-body editing needs a PR, so `audit-initial` establishes it. The helper does not initialize GitHub
wikis, change repository settings, or silently choose another destination when
the wiki is unavailable.

Keep the private run store as well: new runs retain complete ledgers and objects
under its `reviews/` directory, independently of all worktrees. After cleanup,
produce a local historical export with a reviewed narrative:

```sh
python3 "/absolute/plugin/scripts/development_audit.py" archive "/private/run" \
  --pr "<plan-pr-id>" --public "/private/public-narrative.json"
```

This reads saved snapshots and history, writes identity-addressed files under
`<private-run-store>/archives/`, and performs no publication or live-worktree
acceptance. It uses the saved accepted snapshot when present, otherwise the
latest saved PR snapshot. The bundle identifies the historical run outcome and
whether an accepted code commit exists. Use `publish-archive` below to publish
an inspected archive without reserving an assignment. An archive cannot satisfy
the workflow's final-audit or readiness requirements.
Legacy migrated ledgers stay at their external migration destination; retain that storage too.
If an existing run needed external-storage recovery, retain its assigned review
storage too. While the original store remains invalid, new archives use
`$XDG_STATE_HOME/ioncache-ai-tools/development-recovery/<run-id>/archives/`
(under `~/.local/state` when XDG state is unset), without moving the private store.

Discovery is limited to review storage pinned in this run's saved assignments
and individual recorded ledger references. Legacy references can locate their
migrated ledger by the same review ID; they do not include neighboring ledgers.
Historical reads retain path, symlink, ownership and snapshot-integrity checks.
They can read existing evidence if its storage later becomes part of a repository;
that does not permit further ledger writes there. New review and archive-output
locations must still pass the external-storage check. A failed Git probe reports
checker unavailability, not proof that a location is outside repositories.
Reusing a worktree path does not add the new occupant's reviews to an old archive.
Missing recorded reviews remain explicit gaps rather than being replaced with
other history found at that path.

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

The independent freshness witness and releases of its recorded storage locations
take precedence over an older readable ledger. A witnessed failed closure remains
failed even if the ledger write was interrupted. Stale history stays unavailable;
its counters and findings are not presented as current or reconstructed from the
witness.

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
Use `export` and `publish` only for the current reserved `audit-initial` or
`audit-final` assignment. The separate archive commands do not require one.
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

The publisher uses a temporary private wiki checkout, a non-force push to its
advertised default branch, and authenticated `gh api` calls. It checks the PR's
repository, owned branch, open state and exact code commit before publication.
Repository identities are case-insensitive; branch names remain case-sensitive.
HTTPS Git operations use `gh auth git-credential` in the temporary checkout;
SSH URLs retain Git's SSH authentication. Verify the chosen credential's actual
wiki access rather than inferring it from access to the implementation repository.
Before pushing, the helper verifies the two approved files, generated index and
Home bytes, and rejects any unrelated changed files. Other wiki files remain
untouched. Filters or commit hooks cannot silently change the published bundle
or navigation.
It respects Git signing configuration. Missing access or signing failures
produce failure, not a fallback destination or a false successful receipt.

## Publish outside an active audit assignment

Run `archive` first, then read both complete exported files and perform the same
publication-safety review as for a live export. Publish those exact bytes:

```sh
python3 "/absolute/plugin/scripts/development_audit.py" publish-archive "/private/run" \
  --pr "<plan-pr-id>" --approved "<archived-bundle-identity>"
```

This works for running, blocked, interrupted, failed and completed runs, including
after implementation-worktree cleanup. It requires the original approved inputs
and manifest, `publish_audit`, `push` and `create_pr` permissions, the enabled
audit feature and workflow, and native permission. It does not infer new human
authorization or waive an opt-out. Use an intact current helper when an older
pinned executor lacks this command; do not replace the run's executor pin.

The saved accepted file snapshot must match a successful commit handoff.
Review acceptance alone does not establish that its fixes were committed.
For supported rebases, the retained snapshot-to-tree evidence must match the
Git commit object in the main repository; retain those objects after worktree
cleanup. Missing evidence leaves local export available. Complete the accepted
commit handoff or restore the retained objects before publishing.
The PR must be open in the approved repository on its owned branch, and its head
must equal that exact commit.
Even a patch-identical rebase with a different commit is refused. Reconcile
the review within existing allowances, or use `rebase-review` for a supported
unchanged target rebase, then regenerate and inspect the archive. If that
recovery is unavailable, retain the local archive and report publication
incomplete. Never relabel old evidence, reset limits, or force-push to make it fit.
Historical publication records prior evidence, including failed or unavailable
reviews; it does not revalidate the code or imply current acceptance.

If draft creation succeeded but its report did not record the URL, add
`--pull-request "https://github.com/OWNER/REPO/pull/NUMBER"`. This identifies an
existing PR; it does not create one. The same repository, branch, open-state
and commit checks still apply. It cannot replace a different recorded PR URL.
The URL is retained in the receipt, not written into workflow state.

The command uses the same guarded wiki push, index and Home updates, PR link
block and confirmed PR reread as normal publication. After confirmation, it
atomically saves `receipt.json` beside the archive's two files, including the
manifest approval identity and `publish_audit` authorization basis. A receipt
write failure remains incomplete; retrying the same archive confirms the remote
effects and records the receipt without duplicating the publication.
`RUN.json`, outcomes, history, assignments and allowances remain byte-for-byte
unchanged. When archive storage uses the external recovery location, its receipt
and temporary wiki checkout stay there too, never in a repository.

Changed history, outcome, acceptance or review evidence requires a fresh archive
and inspection. Later model observations alone do not revoke approval of a
frozen archive. If an old archive is incompatible or unavailable, regenerate it
from the retained evidence rather than editing its files. A historical receipt
does not complete a pending audit assignment or mark a PR ready.

## Recovery and limitations

If a response is lost, inspect the existing export, wiki files and PR body.
Repeating the same publication reuses matching files and links without creating
another row, commit or PR update. Page names include the run, assignment and
export identities. Different assignments retain distinct publication records.
Concurrent wiki pushes are retried at most three times by fetching the new head
and rebuilding the table edit; never force-push or discard another writer's rows.
If contention continues, retry the same export within the assignment's limits.
Archive publication has the same three-attempt contention bound per invocation
but does not spend or refund development assignments.

If the table or managed PR link block was edited into an unsupported shape,
preserve the human content and repair only the structure before retrying.
Move human notes outside the managed link block; do not discard them. Consolidate
duplicate rows for this PR without deleting their audit records.
The publisher rereads the PR after pushing the wiki and verifies its body after
updating it. GitHub's body update is not an atomic compare-and-swap: avoid
concurrent PR-description writers, since an edit between the final read and
PATCH can still race. A missing confirmation remains incomplete, not success.

Resolve credentials, signing, filter/hook compatibility or permitted wiki-access
issues without bypassing required safeguards, then retry the same
known operation. Unknown live workers still require native shutdown/reconciliation
before retirement. A blocked development assignment resumes as a counted retry;
initial and final publication have separate attempt keys. Do not reset allowances
or change the destination to evade a denial. If evidence/code changed, use the
existing counted review reconciliation path before publishing a new final audit.
If the approved operation remains impossible within its limits, preserve the
initial PR and private evidence and report incomplete work.

Older audit-branch receipts remain historical evidence; do not delete their
publications or rewrite saved history. They cannot satisfy wiki publication for
a pending readiness step. Use counted reconciliation to publish a current wiki
audit without resetting approvals or consumed assignments.

The bundle records its publication assignment as reserved: it is captured before
the controller acknowledges publication. Its wiki files, PR links and retained receipt
record that external effect. It does not claim subsequent readiness or merging.
Archives instead record their captured historical run outcome, not a new
workflow transition. Native tool transcripts, complete control-event history, actual model usage,
cost and reliable worker durations are not automatically captured.
Original private evidence remains useful for a deeper authorized investigation.

Protocol references:
https://git-scm.com/docs/git-push
https://cli.github.com/manual/gh_api
https://docs.github.com/en/communities/documenting-your-project-with-wikis/adding-or-editing-wiki-pages
https://docs.github.com/en/communities/documenting-your-project-with-wikis/editing-wiki-content
https://docs.github.com/en/rest/pulls/pulls#update-a-pull-request
