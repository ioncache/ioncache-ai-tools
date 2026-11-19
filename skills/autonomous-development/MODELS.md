# Native role models

Resolve choices from the current host's supported models and authoritative
capability evidence before launching, following review-code
`ORCHESTRATION.md#runtime-model-selection`. Reuse one bounded capability lookup;
do not probe models by spawning agents. The plugin ships no model ranking or
version-pinned fallback chain. A public catalog does not prove account access.

## Role requirements

Choose the cheapest suitable model and supported low effort for
`development-control`: it executes a helper and relays JSON without semantic
judgment. For `implement`, `adjudicator` and `fixer`, choose the most capable
supported model for the actual task, with supported high reasoning effort.
Review options affect adjudication, not the fixing model.

Choose `reviewer` and `validator` for evidence tracing and independent assessment,
not merely low price. Choose `review-owner` for reliable ledger transitions and
complete evidence handoff. Security, integration and documentation can all need
deep reasoning. Use high effort where the current model supports it and the
work justifies it; do not automatically assign every category a cheap model.

`preflight` and `prepare` need reliable capability, repository and dependency
checks. `commit`, `draft` and `ready` need precise state/receipt reconciliation.
The audit roles need privacy-aware publication review; `evidence` needs the
project's browser and verification tools. Choose the least expensive model
demonstrated to satisfy each role, and a supported effort adequate to those
decisions. Explain these choices and their cost trade-offs at handover.

Use native configured defaults only when explicitly selected, automatic selection
is disabled/restricted, or bounded evidence cannot establish a suitable choice.
Disclose that limitation; never hide an all-configured choice in manifest prose.
Existing approved constraints still apply, including an explicit configured-only
constraint. Do not silently change an active run's approved choices.

## Overrides and launch map

The optional `configuration.execution.models` is a sparse map keyed by the role
names above (including `audit-initial` and `audit-final`). Each entry has exactly:

```json
{"model": "NATIVE_MODEL_ID", "effort": "high", "fallback": "fail"}
```

`model: null` and `effort: null` explicitly request the corresponding configured
native default. Model IDs are host-specific strings. Verify native support;
do not translate a model name into another provider's name.
The native workflow accepts `low`, `medium`, `high`, `xhigh` and `max` effort
strings, but each selected model may support only a subset.

The optional `configuration.execution.review_options` uses the existing
`review_options.py` field names, for example:

```json
{"reviewer_model": "REVIEW_MODEL_ID", "reviewer_effort": "high", "fallback": "fail"}
```

These are normalized by the shared parser. Lead maps to `review-owner` and
`adjudicator`; reviewer and validator map to their matching roles. Preserve
normalized choices and provenance when the owner prepares/resumes review packets.
Explicit review model/effort values override the manifest's role entry, which
overrides the launch-time researched default. An explicit review model with no
effort uses that model's native effort default, not an unrelated model's tuning.
`model_selection: configured` keeps unspecified review roles configured.

Supply a complete `models` object in the workflow's structured arguments,
with an entry of the shape above for every role:
`development-control`, `preflight`, `prepare`, `implement`, `review-owner`,
`reviewer`, `adjudicator`, `validator`, `fixer`, `commit`, `draft`,
`audit-initial`, `audit-final`, `evidence`, `ready`.
Resolve it from the approved overrides, normalized review options and current
host evidence. Include the effective control choice before the first call,
since the script cannot read files before launching a bookkeeping worker.
Missing choices are rejected before any worker starts, rather than silently
putting every role on the main session's model.

The controller passes this complete map to every `next --models '<JSON>'`
reservation. It freezes launch choices and selection policy with that assignment,
separately from the approved manifest. Dispatch and durable fallback consult that
saved selection; a later invocation cannot silently replace a failed attempt's
`fallback: fail`. Older assignments lacking a saved choice do not imply permission
for configured fallback. Retry the original selection within remaining limits or
use an explicitly chosen, supported selection for a fresh counted attempt.

`autonomous-development-model-selection: false` keeps unspecified roles on
configured defaults. `review-auto-model-selection: false` does the same for
review roles only. Explicit approved choices remain explicit. Read these
settings before building launch arguments; the controller also supplies their
current values for subsequent calls. Never rewrite host configuration.

On rejection, honor `fallback`: `fail` leaves the role incomplete;
`configured` permits one counted configured retry after the failed call's
effects and native shutdown are reconciled. The script does not blindly retry
a mutating call or infer that a thrown native error means no work happened.
Keep review category replacement limits and top-level attempt limits intact.
Do not relaunch a worker merely because its actual model is unobservable.

After collecting a blocked report or retiring the failed worker, schedule the
allowed fallback before resuming:

```sh
python3 "/absolute/plugin/scripts/development_run.py" model-fallback "/private/run" \
  --revision 8 --key "first:implement:change" --role implement \
  --reason "Native model selection rejected; effects reconciled" \
  --shutdown-evidence "Native worker and its processes exited"
```

Use the actual assignment key and current revision, then `resume` and launch a
fresh counted attempt. The controller permits one configured fallback per
assignment key/role, only under its declared policy, and consumes it on the next
reservation. A new invocation does not restore that allowance. The fallback
omits both model and effort overrides without rewriting the approved manifest.
Review fallbacks use a counted review retry and retain the original ledger and
completed category evidence. A pre-reservation control failure leaves ordinary
status and bookkeeping available to the launcher; do not invent a completed
assignment or a native model observation for a worker that never started.

## Observed identities

Each worker receives a separately quoted `model-report` helper command with its
invocation, call, role, assignment and selected native options. Run it before
work and before returning. Add `--actual-model` and `--actual-effort` only from
the worker's own native context or transcript, naming `--source native-context`
or `native-transcript`. Otherwise omit actual values and retain `unavailable`.
Never copy a requested alias, parent model or another worker's observation into
an actual identity field.

The helper writes under the private store's `models/`, without changing the run
revision or acceptance. Include its `model_report` path in the development
report; review leaves retain the path in their shared `selection` object.
Bookkeeping workers write the observation but still return exact controller JSON.
Private report failures are visible limitations, not permission fences.
Old reports stay valid and their absent identities stay unknown.

The audit includes selected and observed identities with their source, not raw
model report files. These are supplied observations, not authenticated telemetry.
Each audit export freezes its model observations. Later worker-return and control
observations remain private evidence for future exports without invalidating the
already reviewed bundle or its publication receipt. Code, input, history and
exported-byte checks still apply.
Host policy may substitute another model, and an effort cap can change the
effective effort. Record only what is actually exposed. Publication review
must consider whether provider-specific model/deployment names are private.

Native references:
https://code.claude.com/docs/en/workflows
https://code.claude.com/docs/en/model-config
https://code.claude.com/docs/en/sub-agents

The `agent(prompt, opts)` names `model` and `effort` were also checked against
Claude Code 2.1.325's bundled `/workflow-authoring` reference. This verifies the
API, not model entitlement or successful live execution of this adapter.
