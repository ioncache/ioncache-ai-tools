# Durable review records

The top-level caller owns record storage. Coordinators may register and collect
their assigned workers; leaves write only their assigned reports. This protocol
does not add a review purpose, launch agents, or change ledger allowances.

## Start or resume

Resolve `../../scripts/review_records.py` relative to this installed skill.
After discovering the target, initialize one record run from the host's project
directory, before allocating requests or reports. This directory controls
settings even when it is a package below the Git worktree root:

```sh
python3 -B "/absolute/plugin/scripts/review_records.py" init --target "pr:123"
```

Use `pr:<number>` for a PR, `branch:<exact-branch>` for a branch, and
`repository` for a whole-repository review. Use a stable description for other
explicit scopes. Do not use a harness name, session directory, or timestamp
as the target.

Supply observed provenance with `--harness` (`claude`, `copilot`, or `codex`),
`--harness-version`, `--harness-source` and `--harness-evidence`. Model and effort
observations use `--model`, `--effort`, `--source` and `--evidence`.
Sources are `native-context`, `native-transcript` or `unavailable`.
Known identities require native evidence; omit unobservable values to retain
`unknown`. These arguments record observations, not requested launch settings.
Do not infer the actual model from an override, selection decision, or parent.

The helper returns `directory`, `run_id` and `scratch_directory`. Keep options,
requests, plans and the final handoff inside `directory`. Set the packet
request's `scratch_directory` and `run_id` from this result. Use the shared
packet helper to allocate category result files; allocate other roles' reports
under the same scratch directory with distinct names.
When `enabled` is false, omit `run_id` and use the private scratch fallback below.
Before dispatch, check the host's worker write permissions for the chosen
directory. If it is unavailable to workers, allocate their reports in permitted
private external scratch and import them after collection. A denied worker
write uses this same recovery; retain its analysis instead of repeating it.

On continuation, retain the existing directory and run identity. Do not
initialize another record run for a replacement worker or phase revision.
Different full/focused phases may share the run's scratch directory because
the packet helper includes a unique phase identifier in report names.

Loop ledgers and development acceptance records keep their existing owners,
paths and schemas. Save the record-directory reference beside the phase plan
or in existing ledger reason/evidence fields, not a new ledger event.
For a controller-pinned or already dispatched phase, preserve its original
report paths and packet identities. Import those files as described below;
do not redirect a live worker or relabel old evidence.

## Register and collect every role

Before launch, call `record` without `--result-file` for the lead, coordinator
(when present), each reviewer, adjudicator and validator. Use the actual
assignment ID and the observed worker ID when available. For phase-owned
roles, also pass `--phase` with the plan's `phase_id`: assignment IDs repeat
across fresh phases. Keep both values on registration and collection.
`init` registers the run lead as assignment `lead`; reuse that unphased
assignment for later lead observations. After collection, repeat with the full
result file:

```sh
python3 -B "/absolute/plugin/scripts/review_records.py" record "/absolute/run-directory" \
  --role reviewer --assignment "security-initial" --worker "observed-worker-id" \
  --phase "0123456789abcdef0123456789abcdef" \
  --result-file "/absolute/run-directory/reports/security-phase-initial.json"
```

Both `init` and `record` accept the provenance arguments above. Record the
current role's observed harness/version and model/effort with their sources,
including after a host change on resume. Missing observations stay unknown;
later unknowns do not erase earlier observations. A replacement worker uses
its own assignment ID. Failed or cancelled workers still retain their role
record and any available report; absence of a report is not success.

For a controller-pinned report or retained legacy report outside the record
run, add `--external-report`. Its source must be a regular owner-owned file
outside every repository. The helper copies it into the central reports
directory without changing its original bytes, permissions, or location.
Use physical absolute paths, resolving parent-directory aliases such as
macOS `/tmp` to `/private/tmp`; symlinked source files remain refused.
Attribute imported history only from its retained provenance, not from the
current caller's model or harness.

Retain complete reports, including rejected candidates, duplicates and
assessments. `record` keeps immutable original bytes and indexes `findings`,
`candidates`, `assessments`, `rejected_candidates` and `duplicates`, including
nested collections. Each indexed entry names its run, role, assignment, phase
(when supplied), observation and JSON pointer into the original. Raw source and indices stay
private; they are not input for automatic PR publication.

Malformed or duplicate-key JSON retains its original with an indexing error.
A report naming another run is also retained without indexing its findings;
the archive's run identity names its storage, not a correction to the original.
Run the existing report-repair protocol, then record the repaired file as another version.
Index generation stops at a bounded byte budget; oversized indexes retain the
original with an indexing error. Oversized metadata and cumulative run manifests
are rejected before replacing readable records. Shorten the new observation
evidence and retry; an already archived original remains retained. If history
has filled the manifest, keep later reports in private external scratch and
disclose the archival limitation rather than deleting history or restarting
the review.
Never replace retained originals or claim that archiving proves review quality.

## Find records and handle unavailable storage

```sh
python3 -B "/absolute/plugin/scripts/review_records.py" list --target "pr:123"
python3 -B "/absolute/plugin/scripts/review_records.py" status "/absolute/run-directory"
```

All hosts use
`$XDG_STATE_HOME/ioncache-ai-tools/reviews/records/<repository-key>/<target-key>/<run-id>/`,
defaulting to `~/.local/state/ioncache-ai-tools/reviews/records/`.
Repository keys group common HTTP(S)/SSH/Git origin spellings by host and
repository path, omitting credentials and applying Git's `insteadOf` rewrites.
`list` also checks the current raw-origin key for older records, marking those
rows `legacy_repository_key: true`; that older grouping may have been ambiguous.
Run `list` from the reviewed project, or pass its path with `--root`.
Repositories without such an origin use
their shared Git directory; non-Git scopes use their resolved root.
The helper rejects storage inside any repository or Git metadata and refuses
symlinks within run paths. Run directories are `0700`; helper-written files are `0600`.

`review-records` is enabled by default. When disabled, `init` returns
`enabled: false` without a directory and `record` makes no new persistent
record. Use the existing private scratch handoff instead; review coverage,
isolation, ledgers and posting settings remain independent. Existing records
remain readable.
The settings project saved at initialization also governs resumed recording;
older records without that field use their saved worktree root.
An opt-out does not cancel dispatched writes to already assigned report paths
or delete retained files. Keep those paths stable; allocate later phases in
private non-durable scratch and skip archival while disabled.

A storage failure is an archival limitation, not a permission or review-quality
verdict. Keep available reports in private external scratch and disclose the
missing archive. Retry a busy writer after it finishes. Correct an invalid
state location or restore access, then import the retained reports without
repeating completed review work. Files over 16 MiB remain at their source;
report the size limitation rather than truncating them. Do not reset a review
ledger, spend another review round, or stop unrelated authorized work merely
to repair record storage.
