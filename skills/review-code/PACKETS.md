# Preparing and checking category packets

The caller resolves `../../scripts/review_assignments.py` relative to this
installed skill. It reads JSON and writes JSON to stdout, never launches models
or creates a state store. Keep request, plan and result files in caller-owned
private storage outside the reviewed tree.

```sh
python3 -B "/absolute/plugin/scripts/review_assignments.py" prepare "/private/request.json"
python3 -B "/absolute/plugin/scripts/review_assignments.py" prepare "/private/revised-request.json" \
  --previous "/private/plan.json"
python3 -B "/absolute/plugin/scripts/review_assignments.py" packet "/private/plan.json" security \
  --assignment "security-replacement-1" --result-file "/private/security-replacement-1.json"
python3 -B "/absolute/plugin/scripts/review_assignments.py" check "/private/plan.json" "/private/handoff.json"
```

Persist each returned object before using it. Do not use `packet` to create
extra allowances: it derives an immutable assignment, not permission to launch.
Exit 2 means malformed/unavailable inputs; repair them or return incomplete.
Check exits 1 for structurally incomplete coverage, 0 for structural success.
Neither result changes host permissions or establishes a completed review.

## Request and frozen plan

Prepare requires `objective`, `kind` (`full` or `focused`), `target`, `base`
(nonempty `not applicable` when appropriate), `snapshot` (the pinned identity),
`root` (absolute consuming worktree), `files` (complete candidate-file list),
`constraints` (explicit read/tool/check limits), `scratch_directory` (absolute),
and the normalized `review_options` from OPTIONS.md.

Optional fields are:

- `project_categories`: additional descriptors with `id: project:<slug>`,
  `title`, `source`, `source_identity`, complete `content`, `applicability`,
  and `exceptions` (an explicit list). An objectively language-specific purpose
  may declare a lowercase `language` prerequisite; general purposes omit it.
- `project_sources`: same-purpose requirement records containing `category`,
  `source`, `source_identity`, complete scoped `content`, `applicability`,
  and `exceptions`. Keep original-source identity separate from excerpt identity.
- `exclusions`: only user instructions, with `category`, `authority: user`,
  original `instruction`, and its `source` provenance. Empty by default.
  Never ask for a category selection or generate exclusions from applicability.
- `language_inventory`: candidate paths mapped to `{languages, evidence}`.
  `languages` is a list of lowercase language names; use `javascript` for
  JavaScript/JSX and `typescript` for TypeScript/TSX. Include each actual embedded
  source language. `evidence` identifies the inspected source or language-tool
  result and what it establishes. Use an empty list only for verified non-source
  content, not an unfamiliar language. Omit unclassified files.
- `replacement_rounds`: a finite nonnegative caller-supplied bound; default 1.
- `category_context`: category IDs mapped to `{history, settled_decisions}` lists.
  Supply only that category's relevant prior dispositions and settled requirements,
  never sibling discovery outcomes or the implementation conversation.
- `correction`: required for a focused request, with `before` and `after` snapshot
  IDs and `delta` containing the complete records from the ledger's correction
  diff. `after` must equal the request snapshot. Full requests omit this field.

The helper combines the shipped catalog with project descriptors, applies
independent `configuration.review_features`, and freezes the effective registry,
request, technical-applicability decisions, replacement bound and one packet per
required category.
Writing-skill opt-outs cannot remove review coverage.
General categories remain required regardless of the language inventory.
For an explicit language prerequisite, one evidenced matching source establishes
`applicable`. Only classification of the entire candidate inventory without a
match establishes `not_applicable`. Otherwise the decision is `unknown`.
Neither `unknown` nor `not_applicable` launches a language-specific worker;
`unknown` remains unresolved coverage while other categories proceed.

Inspect actual source languages, including embedded scripts, rather than assuming
all files share the repository's main language or treating a file extension as
complete evidence for mixed-language content. JSDoc requires JavaScript, not
TypeScript. A missing language/framework guide is not evidence of language absence.
The caller records source facts, not a predicted usefulness judgment.

The current phase-plan schema is 2; the catalog and ledger event schemas are
unchanged. Schema-1 plans lack this applicability contract and cannot be silently
reinterpreted. Preserve their original evidence and consumed work, then use the
existing counted reconciliation/new-phase path if authorized and within limits.
An unavailable new phase leaves coverage incomplete, not a fence on other work.
Fingerprints use SHA-256 over canonical sorted JSON, including full frozen
instruction strings, not a claim that source provenance has been independently
authenticated. Keep source contents, not just hashes and paths.

Each packet carries `assignment`, `review_type`, target/base/snapshot/root,
objective/kind/constraints, `candidate_files`, `scope_files`, `result_file`,
`instruction_set`, `technical_applicability`, its category-only `context`, the focused `correction` when
applicable, and `identity`. Its instruction set includes source contents,
applicability, scoped project precedence and its own identity.
Send those contents as the instructions. Do not tell the worker to load the
writing wrapper, full catalog, composer or a preset general reviewer.
The full plan retains the original language evidence; a dispatched packet
records the matching and unclassified paths at its preparation time. Matching
language somewhere does not apply that language's rules to every candidate.

Initial `scope_files` equals the whole candidate inventory. For a measured
capacity shard, derive a packet with repeated `--file` arguments; it retains
the full inventory and identical category instructions. Never use shards merely
to satisfy a concurrency limit. Queue independent categories instead.
The specialist still owns complete relevant traces across its shard boundary.

## Native attempt records and active map

The caller records every invocation chronologically, including failed launches:

```json
{
  "id": "security-attempt-1",
  "round": 0,
  "packet": {"...": "the complete exact submitted packet"},
  "worker": null,
  "observation": {"kind": "caller", "source": "original tool-call reference or caller record"},
  "result": null
}
```

`round: 0` is the initial attempt, shared by initial shards; `round: 1` is the
first replacement round for that category, shared by its replacements/shards.
Each physical invocation gets a new assignment, attempt ID and result path.
Use an observed native worker identity when exposed, otherwise JSON `null`.
Set observation kind to `native` only for a referenced native tool/transcript
observation; a caller-authored description remains `caller`.
Retain terminal failure diagnostics even when no worker/result was created.

Read the original report and attach it as `result`, retaining its file.
The embedded result must equal the original parsed report. Do not normalize
its fields, even in a copy, to obtain a successful check. A malformed result
remains a failed attempt and still spends its category's allowance; use a fresh
replacement within the remaining bound. The helper retains inactive malformed
results as diagnostics without preventing a valid replacement from completing.
It includes the PROTOCOL.md fields; `instruction_set` is the instruction identity
string and `packet_identity` is the submitted packet identity.
The report may use `worker: null` when the child cannot observe its own native
ID, even when the caller has observed that ID. Preserve both observations;
do not rewrite the original report to manufacture child-side visibility.
`coverage.files` records every owned candidate considered for applicability;
record actual full-file reads separately. An inapplicable pass still supplies
its reason after inspecting applicable context. Extra discovered source evidence
does not expand authority.

Check takes a caller-owned handoff object with exactly these fields:

- `history_complete`: whether every phase attempt is accounted for.
- `attempts`: all chronological records, including failed and superseded attempts.
- `active`: required category IDs mapped to lists of selected attempt IDs.
- `other_workers`: observed `{role, worker}` records for coordinator,
  adjudicator and validators, so known cross-role reuse can be detected.
  Use `worker: null` when the native identity is not exposed, including
  synchronous handbacks. A caller-chosen assignment/profile label is not a
  native identity. Preserve host-returned task handles in the observation;
  do not promote them to opaque worker IDs without host evidence.

The final handoff includes the separately completed adjudicator. A check before
adjudication may diagnose category records, but remains structurally incomplete
until that role is recorded. This does not require repeating completed categories.
After all required adjudication/validation returns, write a final caller-owned
handoff and run the check again. If an earlier handoff cannot be edited, create
a new final handoff file with the original reports unchanged. A denied write or
missing final check remains an incomplete handback, not a completed review.

Only the caller selects active attempts; reports cannot select themselves.
Preserve successful unaffected shards while replacing a failed shard, within
the same category-wide replacement round. Re-sharding can change the selected
file subsets but must preserve identical instructions, full file union and
the chronological attempt history. Owned file subsets in one category/round
must not overlap; necessary evidence reads may overlap and cross those subsets.
Retrying a failed replacement as smaller shards still consumes another round.
Renaming cannot reset a round or authorize
another identical attempt. Stop retrying after exhaustion; return incomplete
coverage and continue unrelated authorized work.

Check verifies record identities, required categories, file union, known context
reuse, results, technical-applicability decisions and replacement bounds.
`unresolved_applicability` lists enabled, non-excluded language-specific purposes
whose language presence is unknown. Resolve those source facts and revise the
plan before claiming completeness; no completed categories need replay.
Check cannot prove the truth of language classifications, semantic trace coverage,
truthful launch observations, model compliance or independent adjudication.
Its `structurally_complete` result is not the overall review verdict.
Known contamination invalidates coverage. Hidden-context uncertainty is a
reported visibility limitation, not proof of contamination or pristine context.

## Interruption and phase changes

For loop callers, persist the complete frozen plan before launching:
`start_review.reason` for a full phase. For a focused phase, `fix_done` first saves
the after snapshot; prepare from its actual saved correction delta, then persist
the plan through an internal `stop` (`interrupted`)/`resume` checkpoint before
launching focused workers.
The latest orderly interruption or plan revision belongs in `stop.reason`
with the complete plan, all attempt records, active map, evidence and consumed
allowances. Resume without refunding any counts.
Recover the latest full plan, not only the initial phase record.

For an open-phase addition, disable or newly classified source, use
`prepare --previous` with the complete
revised request. It retains existing frozen packets (including archived disabled
ones), adds only newly required packets, and records current `required` categories.
Keep the separate chronological attempt history unchanged. Record the complete revised plan before
dispatch. An existing category's corrected instruction content is not ordinary
capacity sharding: known invalid isolation requires the loop's reconciliation
path. A setting that disables a category removes only its outstanding obligation;
retain its prior attempts as diagnostics outside active coverage.
Do not rebuild existing packets merely because installed source bytes changed.
New language records may fill gaps in the same phase, preserving all existing
records and packets. They may resolve an unknown language prerequisite and add
its first packet without refunding another category's attempts. Existing
classifications cannot be deleted or rewritten: contrary evidence requires a
counted new phase. Recompute language evidence for each new full/focused scope
and snapshot; do not reuse a prior scope's absence conclusion as a shortcut.
If the retired plan was in `reviewing_fixes`, do not fabricate `fixes_reviewed`.
Retain the applied outcomes and checks, reconcile within the outer limit, and
use the fresh full review for first verification under
[../review-validate-fix-loop/LEDGER.md](../review-validate-fix-loop/LEDGER.md)'s
unchanged-snapshot and retained-outcome prerequisites. Completed focused
outcomes still follow the pre-reconciliation settlement path.

Unknown spending or missing history cannot become a fresh allowance.
Recover native evidence or use a counted reconciliation within remaining loop
limits; otherwise report incomplete. Standalone review has private invocation
artifacts only and does not advertise cross-session resume.
