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

Keep one current report and matching JSON file per PR. The page title is
`Audit: PR #<number>, <PR title in sentence case>`. For example:
`Audit:-PR-#69,-incremental-delivery-planning-for-autonomous-development.md`
and `.json`. The filename supplies the wiki title; do not repeat it as an H1
inside the report. Links encode `#` as `%23`, while keeping `:` and `,` literal.
Spaces become filename hyphens; literal title hyphens use U+2010 to retain their
display. The helper preserves leading acronyms, removes unsafe filename
characters and bounds the title's UTF-8 length. This title style intentionally
uses `:`, despite GitHub's warning about Windows-incompatible filename characters.

The initial publication follows draft creation. The final publication follows
full-PR review, the accepted commit and any approved UI evidence, before readiness.
The final audit replaces the initial page and data in place. A later title change
renames that pair on the next reviewed export; recognized older per-run audit
pairs for that PR are removed from the current tree. Do not keep superseded page
copies. Wiki Git history and retained receipts preserve prior versions.
Partial pairs, symlinks, unrecognized content and foreign-PR data are not replaced:
restore the pair from wiki history or preserve conflicting content under another
page name, then retry. Title-based pairs require schema-2 PR ownership metadata;
schema-1 pairs are recognized only under legacy per-run names.
Unrelated wiki pages remain untouched. Repository access,
deletion and retention policies still apply; the wiki is not tamper-proof storage.

Update the `Automated-Pull-Request-Audits` wiki page automatically. Create that
page if it is absent from an initialized wiki. Its table has `Date`,
`Pull request`, and `Audit records` columns, with one row per PR. Prepend the
newest publication and replace that PR's previous row, leaving other rows and
surrounding content intact. Use the UTC publication date, PR number/title/link,
and links to the report and JSON. Repeating the same publication leaves its
matching row in place rather than duplicating or reordering it. A missing or
altered managed row is rebuilt on retry without changing other PR rows.

Keep the index discoverable from the existing `Home.md` or `Home.markdown`.
If both exist, preserve and update both rather than relying on GitHub's
same-title selection. If Home has no index link, append
one between `ioncache-audit-index:start` and `ioncache-audit-index:end` HTML
comments. Create `Home.md` only if neither exists. Preserve all other Home content
and existing handwritten inline, reference-style or wiki index links instead of
duplicating them. An edited or malformed managed block requires preserving its
human notes outside the block before repair and retry. Marker examples inside
code are literal content, not managed blocks. Home bytes are verified
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
  Pass names and known category identifiers come from recorded review structure;
  missing category evidence stays unavailable, not inferred from all reviewers.
  Read `review_type` from JSON evidence or `review_type=<category>` tokens.
  A recognized pass name is the fallback when its evidence has no known category.
- Execution limits, consumed assignments and explicit unavailable metrics.
- Requested native models/efforts and separately observed actual identities,
  their observation source and an evidence digest, tied to assignment/role.
  Control calls are run-level observations, not invented assignments.

Schema-2 JSON adds publication metadata, requested model selections and structured
public finding details. Every finding has `title`, `summary`, `reason`,
`locations`, `category`, `pass`, `tracking_issues` and public decision reasons.
The short reason is the first sentence of the final public decision reason.
The helper does not automatically copy input documents, source blobs, raw report
bodies, prompts, private paths, diagnostic strings, finding keys or arbitrary
event reason/evidence fields. Keys, locations and decision prose must be supplied
in the separately reviewed public narrative. Categories and pass membership are
mechanical; their identifiers still require publication review.
Review progress checkpoints remain private and are not exported as evidence.
Model observations project only the fields above, not their raw private files.
Requested models and efforts combine saved dispatch job options with advisory
selections, deduplicated per role. Partial observations do not hide other saved
requests. Dispatch options include explicit overrides and configured fallbacks.
Raw manifest and launch defaults are not evidence of an effective request.
When neither record exists, the requested selection remains unknown.
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
  "method": "Review coverage and any context not captured mechanically.",
  "issues": ["https://github.com/owner/repo/issues/61"],
  "planning": {
    "model": null,
    "effort": null,
    "human_approved": true
  },
  "verification": [
    {"check": "Targeted tests", "result": "Passed", "runner": "implementer"},
    {"check": "Post-run check", "result": "Passed", "runner": "run by hand after the run stopped"}
  ],
  "not_verified": "Name what was not verified; do not infer live-host coverage.",
  "findings": [
    {
      "review": "<review-run-id>",
      "id": "F001",
      "key": "documentation-pr-links",
      "summary": "A description safe for this repository's audience.",
      "rationale": "A public explanation of the disposition.",
      "locations": ["docs/usage.md:20-25"],
      "decisions": [
        {"sequence": 6, "reason": "The links were broken. Public details of the initial assessment."},
        {"sequence": 12, "reason": "The links now resolve. Public details of the final assessment."}
      ],
      "tracking_issues": []
    }
  ],
  "regressions": [],
  "limitations": ["Any material evidence gaps."]
}
```

Account for every finding in every available ledger, including rejected and
ignored candidates. Supply every decision's actual ledger sequence in order;
the example numbers are placeholders. Preserve meaningful decision changes, not
just the last label. Use a publication-safe version of the finding key; the
helper removes category prefixes and humanizes words such as PR and JSON.
Locations must be repository-relative, optionally with line numbers. Tracking
and top-level issue references must be GitHub issue URLs. Supply tracking links
for out-of-scope work when available; do not invent an issue or infer a link from
private input references.

Narrative strings are plain text; the renderer escapes Markdown and HTML
structure. `issues`, `planning` and `not_verified` are optional. Record the
launching session's planning model and human approval only from evidence. The
`prepare` worker is worktree/branch setup, never planning or design.
Missing model records remain unknown. Review, implementation and delivery
models are grouped by stage without inferring observed identities from requests.
Legacy narratives with a verification string and summary/rationale-only findings
remain readable, with explicit missing-runner and missing-detail notices. They
never acquire private locations or decision prose automatically.

Describe effective review coverage, checks and selection choices from
actual records; do not infer success or observable model identity from defaults.
The helper validates finding references and completeness, not narrative truth.

## Human report layout

The helper renders the link/date/stage line, outcome counts, finding key, review
pass table, model-by-stage table, verification table and known gaps. It groups
findings as Fixed; Real problems not fixed in this PR; Accurate observations,
no change needed; and Rejected. Rejected entries are collapsed. Within each
group, sort by impact, category, then display number. Display numbers are unique
across available ledgers; their ledger mapping appears only under Identifiers.

Use the recorded status, not an inferred resolution:

| Validation / disposition | Public wording |
| --- | --- |
| valid / open | Confirmed, to be fixed |
| valid / fixed | Confirmed, fixed |
| valid / out_of_scope | Confirmed, outside this PR |
| valid / ignored | Confirmed, no change needed |
| invalid / ignored | Rejected, not a defect |

Applied but unverified fixes and failed fixes remain unfixed. Pending or uncertain
claims get an additional Unresolved section rather than being called confirmed
or rejected. Missing histories contribute no invented findings or clean results.
The report shows the first and final public decision sentences for fixed
findings, or the final reason otherwise, up to four locations (not for rejected
findings), and the complete public decision history under a disclosure.
Horizontal rules separate consecutive findings, not section introductions.

The assignment table comes near the end. Identifiers is last: run and ledger
IDs, reviewed commit, observed PR head and any mismatch, plus the structured
evidence bundle's SHA-256. The exact two-file approval identity stays in the
receipt: embedding that digest into its own Markdown input would be circular.
No mechanically generated hashes appear above Identifiers.

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
and returns their combined identity. Export reads the open PR to freeze its
title, head and UTC date before rendering. A title with no usable filename text
must be corrected before export writes either file. Publication and acknowledgment
reuse that metadata; a title or head change requires a fresh export and review.
The publication date is the UTC date at push initiation, not remote acceptance.
If it changes before the first push, regenerate and review the export.
Retries of an already published identical bundle retain its original date and
remain idempotent on later days.
Historical exports do not fetch a live PR head and explicitly leave it unobserved.
Read both complete files. Check publication
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
Home bytes and removal of superseded audit pairs, and rejects unrelated changed
files. Existing page bytes come from the fetched commit, not the checkout that
smudge filters can transform. Filters or commit hooks cannot silently change the
published bundle or navigation, or retain a superseded page.
After pushing, the helper verifies the approved pair, this PR's managed index
row and the absence of scheduled superseded paths at the fetched wiki head.
Missing, changed or non-regular publication files, a missing or changed PR row,
or restored superseded paths prevent receipt creation. Other index rows,
their order and surrounding text may change; the whole index need not match.
The receipt identifies that confirmed commit.
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
manifest approval identity and `publish_audit` authorization basis.

A normal retry with a valid receipt acknowledges that historical publication.
It verifies the approved archive bytes, receipt, PR target and authorization,
then returns the saved receipt without contacting the remote or rewriting it.
Later run history does not invalidate that acknowledgement. It does not confirm
current PR acceptance, current navigation or continued remote availability.
Permissions, feature opt-outs and approved-input checks still apply.

Without a receipt, publication still requires fresh matching run evidence and
the exact current PR head. Before remote writes, the helper saves
`publication-attempt.json` with the original managed PR block and wiki-row
digests. Retries can finish effects that still match those originals or this
archive. Unrelated PR text and other PRs' rows do not prevent recovery.
If either audit pointer has changed to another record, report the publication
as partial or superseded and preserve the newer navigation. A receipt write
failure remains incomplete; matching effects can be confirmed and receipted
without another wiki commit or PR update. For older publications without an
attempt record, existing archive pages require matching index and PR links
before automatic recovery.

To intentionally make the same approved archive current again, use
`publish-archive STORE --pr ID --approved IDENTITY --republish`. This starts
a new attempt against the current navigation and replaces the receipt only
after successful confirmation. It is not an automatic retry fallback.
Fresh-evidence, ownership, permission and exact-head checks still apply;
if run evidence changed, export and inspect a new archive instead.

`RUN.json`, outcomes, history, assignments and allowances remain byte-for-byte
unchanged. When archive storage uses the external recovery location, its receipt
and temporary wiki checkout stay there too, never in a repository.

New remote publication after changed history, outcome, acceptance or review
evidence requires a fresh archive and inspection. Later model observations alone do not revoke approval of a
frozen archive. If an old archive is incompatible or unavailable, regenerate it
from the retained evidence rather than editing its files. A historical receipt
does not complete a pending audit assignment or mark a PR ready.

## Recovery and limitations

If a response is lost, inspect the existing export, wiki files and PR body.
Live publication retries reuse matching files and links without creating
another row, commit or PR update. Archive retries follow the acknowledgement
and supersession rules above. Changed audit bytes update the same PR's page
and move its index row to the top even when its URL is unchanged. Different
assignments retain separate private bundles and receipts, not public page copies.
Concurrent wiki pushes are retried at most three times by fetching the new head
and rebuilding the table edit; never force-push or discard another writer's rows.
If contention continues, retry the same export within the assignment's limits.
Archive publication has the same three-attempt contention bound per invocation
but does not spend or refund development assignments.

If the table or managed PR link block was edited into an unsupported shape,
preserve the human content and repair only the structure before retrying.
Move human notes outside the managed link block; do not discard them. Consolidate
duplicate rows for this PR while preserving human content and wiki history.
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
