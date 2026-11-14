# Review options

Normal invocation starts with defaults, without a configuration question.
There is no `--non-interactive` flag. `--help` displays options, defaults, and
examples without inspecting a target or launching a review.

Use `/ioncache-ai-tools:review-code` in Claude Code or Copilot CLI, and
`$ioncache-ai-tools:review-code` in Codex. The same review options work with
`review-validate-fix-loop`; they affect reviewing and validation, not fixing.

| Option | Default and meaning |
| --- | --- |
| `[target ...]` | Active PR, otherwise branch and local changes under SKILL.md's baseline rules. Explicit scope takes precedence. |
| `--model-selection auto\|configured` | `auto`: attempt suitable role selection when the host permits it. `configured` leaves unspecified roles on host defaults. Neither setting replaces explicit role choices. |
| `--lead-model MODEL` | Coordinator and separately launched adjudicator. Omitted: selection policy. |
| `--reviewer-model MODEL` | Default for correctness, each standards pass, and the separate integration specialist. Omitted: selection policy. |
| `--validator-model MODEL` | Independent caller validation. Omitted: selection policy. |
| `--lead-effort LEVEL`, `--reviewer-effort LEVEL`, `--validator-effort LEVEL` | Omitted: host/model default. Explicit values must be supported by the native host and selected model. |
| `--fallback configured\|fail` | Omitted: `fail` for a role with an explicit model or effort, `configured` otherwise. `configured` authorizes one retry with that role's configured model and effort. |
| `--strategy auto\|sweep-first\|specialists` | `auto`: deterministically use `specialists`. `sweep-first` runs correctness first without changing the remaining required single-purpose assignments. |
| `--help` | Show help only. |

Model and effort values are opaque native identifiers, not a plugin-maintained
catalog. There is no `--main-model`: the lead is a review agent, not the existing
host conversation. Changing the conversation model uses the host's own controls.
Do not rewrite host settings, agent definitions, or plugin configuration for a run.

Examples use placeholders, not recommendations or verified available models:

```text
/ioncache-ai-tools:review-code
/ioncache-ai-tools:review-code --help
/ioncache-ai-tools:review-code this PR --model-selection configured
/ioncache-ai-tools:review-code this PR --lead-model LEAD_ID --reviewer-model REVIEW_ID
/ioncache-ai-tools:review-code src --reviewer-model REVIEW_ID --reviewer-effort LEVEL --fallback configured
$ioncache-ai-tools:review-code --help
```

Claude Code's `argument-hint` advertises arguments in autocomplete; it does not
implement parsing or a settings form. Other hosts may ignore it. Do not promise
a portable option picker. Help is the portable discovery path.

## Normalize once, forward without reinterpretation

Before new target discovery, resolve [../../scripts/review_options.py](../../scripts/review_options.py)
relative to the installed skill and run it from the consuming project:

```sh
python3 -B "/absolute/plugin/scripts/review_options.py" review-code --help
python3 -B "/absolute/plugin/scripts/review_options.py" review-code "this PR" --model-selection auto
```

Pass the actual invocation arguments as separate, safely quoted arguments,
not shell code. Never `eval` invocation text. For a loop use
`review-validate-fix-loop` as the helper's skill argument. The helper owns flag
definitions, defaults, validation, and normalized output; do not maintain a
second parser in prompts. It rejects unknown, abbreviated, duplicate, empty,
and conflicting arguments. On an argument error, show the diagnostic and help;
correct the invocation when intent is unambiguous, otherwise leave the review
unstarted. Errors do not fence other authorized work.

For `--help`, show the helper output and relevant examples above, then stop.
Do not prepare context, inspect Git, create a ledger, or research or launch models. For ordinary
invocation, preserve the JSON output as `review_options` in the request. Forward
its `roles`, requested and effective selection policy, fallback, strategy, and
`specified` and `option_sources` fields intact. Do not turn a configured default
into an explicit user model selection.
Use `effective_strategy` for scheduling while retaining `strategy` as requested.
The helper resolves `auto` to `specialists`; the orchestrator does not decide
whether a review is small enough to run inline or combine purposes.

If there are conversational role choices or saved options, the caller first
writes a private context JSON file outside the reviewed tree. Resolve conflicts
between explicit current user instructions before creating it. Its `choices`
map uses option names with underscores and a value/source pair:

```json
{
  "choices": {
    "reviewer_model": {
      "value": "MODEL_ID",
      "source": "Explicit user role choice in the current request"
    }
  }
}
```

Pass it as a helper control before the skill name, not as a user-facing skill
flag. The same invocation arguments still follow the skill name:

```sh
python3 -B "/absolute/plugin/scripts/review_options.py" \
  --context "/absolute/private/review-context.json" review-code "this PR"
```

For resume, include `saved` containing the prior normalized `review_options`
recovered from the checked ledger, or explicit `null` when an older run has no
recorded choices. Do not copy a selection record's automatically chosen model
into requested options. The helper merges saved choices, resolved conversational
choices, then explicit invocation flags, in that order. It validates them with
the same flag definitions and recomputes all role fallbacks and effective
selection against fresh configuration. Do not merge these fields in prose.
Explicit conversational models and efforts default to `fail`, just like flags.
Flags take precedence over general role preferences, not unresolved contradictory
current instructions.

The helper reads effective plugin settings without synchronizing or writing
them. Run it from the same project `cwd` the host supplies to hooks, not an
inferred Git root. A package launched as the project inside a monorepo can have
its own overrides. `review-auto-model-selection: false` changes unspecified roles to
configured defaults while retaining explicit choices. A disabled skill remains
disabled independently. `configuration.review_features` contains the current
independent `review-<category>` controls used by packet preparation. Writing
`skill:*` controls do not disable those categories. There is no category-selection
prompt or automatic exclusion option.
Configuration failure reports unavailability; continue
authorized work without applying this skill, rather than inventing permission.
If the helper is unavailable, report that limitation. Help can be read here;
do not silently ignore supplied flags or claim they were validated.

The helper's output establishes option and configuration state only. It does
not establish model access, suitability, or host permission. Apply
[ORCHESTRATION.md#runtime-model-selection](ORCHESTRATION.md#runtime-model-selection)
before native launches. Automatic selection is best effort, not a reason to ask
for a setup decision or block when configured defaults can satisfy the role.

An explicit role model or effort requires execution of that role rather than
silently treating it as an unused hint. Execute the complete single-purpose
assignment roster regardless of change size or strategy. A requested
validator may check the final handback even when there are no candidates.
Do not change the parent model to emulate an inline override. If the host
cannot honor an explicit choice, follow its role's fallback and report the
limitation; do not quietly run inline instead.

## Review/fix forwarding and resume

The loop also accepts `--max-loops N` and `--max-fix-cycles N`, both positive
integers defaulting to 3, or `--resume LEDGER`. Resume reuses the saved target
and limits and rejects new target or limit arguments.

Retain normalized options in the initial review request and in existing ledger
reason/evidence fields, not new event fields. Forward the same review choices
to full reviews, focused review-fixes, and independent caller validation.
Model options do not authorize changing the fixing agent or increasing limits.

On resume, recover saved review options from the ledger and pass them in the
helper context above. The helper overlays only explicit choices and invocation
fields, not default-valued omissions. Preserve its recomputed request in the
next event's reason/evidence. Resume output leaves limits unset; use the ledger's
original limits, never new parser defaults.
For older runs without recorded options, use current defaults and disclose
that prior choices could not be recovered; do not invent them.
Re-read plugin settings and host authority and discard stale availability
observations. Saved choices are request evidence, not permission to override
current host restrictions. This changes neither scope nor consumed allowances.
The helper recomputes `effective_strategy` on resume, including for older saved
requests. Do not resume a bundled worker or an inline-review plan: rebuild
those assignments with fresh single-purpose contexts under the same run limits.
