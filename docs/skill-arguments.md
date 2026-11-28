# Skill arguments

Append arguments after the skill invocation. Host-specific invocation syntax is
in [../README.md#invoke-a-skill](../README.md#invoke-a-skill).

Some skills accept fixed flags; others take a task, files, or other context in
plain language. The plain-language inputs below are not named flags or a rigid
argument order. For those inputs, **Current request** means information you have
already supplied, not a built-in default task. Missing essential context must be
resolved before work starts.

Defaults here describe omitted arguments, not whether a feature is enabled.
Only skills whose tables list `--help` define that flag.

## review-code

Accepts a review target and the following flags. With no arguments, review the
active PR; without a PR, review branch and local changes against the default
branch's merge-base. An explicit target, snapshot, or comparison base takes
precedence.

| Argument | Default | What it does |
| --- | --- | --- |
| `[target ...]` | Active PR, otherwise branch and local changes | Select files, a directory, repository, branch, PR, or a more specific comparison in plain language. |
| `--model-selection MODE` | `auto` | `auto` attempts suitable model selection for unspecified roles when enabled and permitted by the CLI. `configured` uses the CLI's configured defaults instead. |
| `--lead-model MODEL` | Model-selection policy | Select the model for the review coordinator and separate adjudicator, not the main conversation. |
| `--reviewer-model MODEL` | Model-selection policy | Select the default model for specialist reviewers, including the integration review. |
| `--validator-model MODEL` | Model-selection policy | Select the model for independent validation of findings that require another check. |
| `--lead-effort LEVEL` | CLI/model default | Set reasoning effort for the coordinator and adjudicator. |
| `--reviewer-effort LEVEL` | CLI/model default | Set reasoning effort for specialist reviewers. |
| `--validator-effort LEVEL` | CLI/model default | Set reasoning effort for independent validators. |
| `--fallback MODE` | Per role: `fail` with an explicit model or effort, otherwise `configured` | `configured` permits one retry using that role's CLI defaults after a launch failure. `fail` does not permit that fallback. This flag does not select the initial model. |
| `--strategy STRATEGY` | `auto`, which resolves to `specialists` | `specialists` runs independent review categories concurrently where supported. `sweep-first` starts correctness first, then runs the remaining categories. Neither reduces review coverage. |
| `--checks MODE` | `targeted` | Use bounded claim-directed checks in isolated copies with existing dependencies. `source` disables tests/probes. Neither permits routine suites, automatic installs or unapproved external-system access. |
| `--run-details` | Off | Add per-agent durations, a timeline and recorded waits. Every review still shows the compact runtime summary; evidence is retained in both display modes. |
| `--post-comments` | Off | After review, publish eligible findings as one `COMMENT` review on the PR, subject to the posting setting and permissions. |
| `--post-sensitive POLICY` | `private` | With posting enabled, `none` withholds sensitive findings; `private` includes them on private/internal repositories but only PR-introduced ones on public repositories; `all` permits them under the posting policy on any repository. |
| `-h`, `--help` | Off | Show options, defaults, and examples without inspecting a target or starting a review. |
| Report-severity preference, in plain language | `Low` | Choose `High`, `Medium`, or `Low` as the minimum severity in the main findings table. This changes presentation, not review coverage or whether unresolved issues are retained. There is no severity flag. |

Model names and effort levels must be supported by your CLI and selected model.
Explicit choices are not silently replaced. Supply each flag at most once;
unknown or abbreviated flags are rejected. These options do not change your
CLI's saved model settings. There is no `--main-model`, `--non-interactive`, or
token-budget flag.
A `--post-sensitive` override requires `--post-comments` or an explicit request
to post; choosing a disclosure policy alone does not request publication.

```text
/ioncache-ai-tools:review-code branch --model-selection configured
/ioncache-ai-tools:review-code this PR --post-comments --post-sensitive none
/ioncache-ai-tools:review-code this PR --run-details
/ioncache-ai-tools:review-code --help
```

Workflow and model-selection details:
[workflows.md#review-options](workflows.md#review-options).

## review-dependabot-pr

Accepts plain-language input, not a fixed flag set.

| Input | Default | What it does |
| --- | --- | --- |
| Dependency-update PR | No automatic target; identify it in the request or existing context | Select the Dependabot, Renovate, or similar dependency-update PR to compare against actual project usage. Grouped updates are supported. |
| Saved run directory | None; start a new review | Ask to resume using a previous run's private directory. Saved snapshots and evidence are checked before unfinished work continues. This is not a `--resume` flag. |

```text
/ioncache-ai-tools:review-dependabot-pr review this Dependabot PR
/ioncache-ai-tools:review-dependabot-pr resume using /absolute/private/dependency-review
```

This skill reports findings without changing the PR or posting comments.
Its full review contract is in
[../skills/review-dependabot-pr/SKILL.md](../skills/review-dependabot-pr/SKILL.md).

## verify-unresolved-pr-comments

This skill defines no target argument or flags. It uses the active PR associated
with the current branch; switch to the intended branch before invoking it.

| Invocation | Default | What it does |
| --- | --- | --- |
| No arguments | Active PR for the current branch | Evaluate unresolved inline threads, review bodies, and PR conversation comments without editing, posting, resolving threads, or running tests. |

## post-pr-review-comments

Accepts the following context in plain language, not as named flags.

| Input | Default | What it does |
| --- | --- | --- |
| PR and review context | Current request; establish the PR and comparison base before drafting | Identify the PR and any related PRs needed to understand the findings. |
| Findings or existing comments | Current request | Supply findings to verify, or identify comments to revise or reply to. Supplying findings does not start an unsolicited full review. |
| Requested action | No implied permission to publish | Ask to draft, edit, add comments to a review, publish, or reply. Drafting or editing alone does not authorize posting. A request to reply to an existing published comment does, unless you request a local draft. |
| Correction-round limit | Three rounds per comment | State a different finite limit in plain language for the independent correctness and clarity checks. Reaching the limit does not make an unverified comment ready to post. |

Adding comments to a review normally uses a pending review. Explicit requests
for direct publication are honored, but the skill never submits the review.
Writing and posting details:
[../skills/post-pr-review-comments/SKILL.md](../skills/post-pr-review-comments/SKILL.md).

## write-pr-descriptions

Accepts plain-language input, not a fixed flag set.

| Input | Default | What it does |
| --- | --- | --- |
| PR, branch, or relevant diff | Current request; no fixed PR number | Identify the change whose title or description should be written or checked. |
| Requested writing task | Current request | Ask to draft, update, shorten, or check the title or description. An existing title changes only when requested; unrelated body content is preserved. |
| Background and constraints | Supplied context and repository conventions | Explain the problem, intended behavior, and any scope or wording requirements. Missing reasoning is clarified rather than invented. |

The repository's PR template supplies the structure when present; otherwise the
skill uses Overview and Details. Full writing contract:
[../skills/write-pr-descriptions/SKILL.md](../skills/write-pr-descriptions/SKILL.md).

## review-triage-loop

Accepts an explicit target for a new run, or a saved ledger for resume.

| Argument | Default | What it does |
| --- | --- | --- |
| `target` | Required for a new run; no automatic target | Select a file, directory, repository, or branch/PR comparison. Missing or ambiguous targets are resolved before starting. |
| `--max-rounds N` | `5` for a new run; saved cap on resume | Set a positive total round cap. On resume, an explicit value replaces the total cap, not the remaining allowance, and cannot be lower than the rounds already started. |
| `--resume LEDGER` | Not set; start a new run | Continue from an absolute path to a saved private `REVIEW_LEDGER.md`, preserving its target and history. Cannot be combined with a replacement target. |

The loop also stops after two consecutive complete rounds with no new reportable
information. A cap of one is valid but cannot establish that stopping condition.
There are no model, effort, cost, time-budget, or `--help` flags. Unlike the
review/fix loop, this skill does not accept the shared review-code flags.

Examples and storage:
[workflows.md#review-loops](workflows.md#review-loops).

## review-validate-fix-loop

The table shows defaults for a new run. Resume keeps the saved target, limits,
and unspecified review choices; explicit review flags can override saved choices.
If an older run has no saved review choices, the assistant reports that gap and
uses defaults plus your explicit choices.

| Argument | Default | What it does |
| --- | --- | --- |
| `[target ...]` | Active PR or branch scope, inspected in the current worktree | Select the files, repository, branch, or comparison to review and fix. Current local fixes remain part of the review. |
| `--max-loops N` | `3` | Set a positive maximum number of full review loops for a new run. |
| `--max-fix-cycles N` | `3` | Set a positive maximum number of fix cycles within each full review loop. |
| `--resume LEDGER` | Not set; start a new run | Continue from an absolute path to a saved private `REVIEW_LEDGER.json`. Cannot be combined with a target, `--max-loops`, or `--max-fix-cycles`. |
| `--model-selection MODE` | `auto` | `auto` attempts suitable model selection for unspecified roles when enabled and permitted by the CLI. `configured` uses the CLI's configured defaults instead. |
| `--lead-model MODEL` | Model-selection policy | Select the model for the review coordinator and separate adjudicator, not the main conversation. |
| `--reviewer-model MODEL` | Model-selection policy | Select the default model for specialist reviewers, including the integration review. |
| `--validator-model MODEL` | Model-selection policy | Select the model for independent validation of findings that require another check. |
| `--lead-effort LEVEL` | CLI/model default | Set reasoning effort for the coordinator and adjudicator. |
| `--reviewer-effort LEVEL` | CLI/model default | Set reasoning effort for specialist reviewers. |
| `--validator-effort LEVEL` | CLI/model default | Set reasoning effort for independent validators. |
| `--fallback MODE` | Per role: `fail` with an explicit model or effort, otherwise `configured` | `configured` permits one retry using that role's CLI defaults after a launch failure. `fail` does not permit that fallback. This flag does not select the initial model. |
| `--strategy STRATEGY` | `auto`, which resolves to `specialists` | `specialists` runs independent review categories concurrently where supported. `sweep-first` starts correctness first, then runs the remaining categories. Neither reduces review coverage. |
| `-h`, `--help` | Off | Show options, defaults, and examples without starting or resuming a run. |
| Report-severity preference, in plain language | `Low` | Choose `High`, `Medium`, or `Low` as the minimum severity in the main findings table. This does not change fix policy, review coverage, or completion requirements. There is no severity flag. |

The review model and effort flags do not select the fixing model. Model/effort
values must be supported by the CLI; each flag may appear only once. Posting
flags are rejected, and this skill never commits, pushes, or posts comments.
There are no parent-model, fixing-model, persistent-config, cost, or
`--non-interactive` flags.

Examples, stopping conditions, and storage:
[workflows.md#review-loops](workflows.md#review-loops).

## investigate

Accepts plain-language input, not a fixed flag set.

| Input | Default | What it does |
| --- | --- | --- |
| Topic, feature, or workflow | Required; the assistant asks if no topic was supplied | Identify what existing behavior to trace and explain. Relevant file paths can narrow the investigation. |

The investigation is read-only.

## triage-errors

Accepts plain-language input, not a fixed flag set.

| Input | Default | What it does |
| --- | --- | --- |
| Failing command and error context | The failing check already identified in the current request; no fixed test command | Identify the test, build, lint, or other command to run. The assistant collects its errors, groups root causes, fixes them, and reruns the command. |

## create-worktree

Accepts the arguments to `git worktree add`, without the `git worktree add`
prefix. The plugin forwards them to your installed Git, then applies the main
worktree's `.worktree-setup.json`. Git validates the combination of options.
Support for newer flags depends on your installed Git version.

| Argument | Default | What it does |
| --- | --- | --- |
| `PATH` | Required | Choose the new worktree directory, relative to the current directory or absolute. Quote paths containing spaces. |
| `[COMMIT-ISH]` | Git's branch-name inference; `HEAD` when creating an explicitly named branch | Check out an existing branch or commit, or use it as the start point for a new branch. Without an explicit branch option or commit, Git uses the final component of `PATH` as the branch name. `-` means the previous checkout. |
| `-b BRANCH` | No explicit branch name | Create a new branch at the selected start point. Refuse if the branch already exists. |
| `-B BRANCH` | Off | Create the branch, or reset an existing branch to the selected start point before using it. |
| `-d`, `--detach` | Off | Check out the selected commit without attaching the worktree to a branch. |
| `--orphan` | Off, except Git's empty-repository inference | Create an empty worktree and index on a new branch with no commits. |
| `--checkout`, `--no-checkout` | `--checkout` | Populate, or skip populating, tracked files. Plugin copies, symlinks, generated files, and setup commands still run afterward. |
| `-f`, `--force` | Off | Override Git checks such as a branch already being checked out or a missing path still registered to another worktree. A missing locked worktree path requires the flag twice. |
| `--lock` | Off | Lock the worktree at creation so Git does not automatically prune its registration. |
| `--reason TEXT` | No lock explanation | With `--lock`, record why the worktree is locked. Quote a multi-word reason. |
| `--track[=MODE]`, `--no-track` | Git configuration; normally track a remote-tracking start branch | Set or suppress upstream tracking for a new branch. `--track` or `--track=direct` tracks the start-point branch; `--track=inherit` copies its upstream configuration. |
| `--guess-remote`, `--no-guess-remote` | `worktree.guessRemote`, normally off | Without a commit argument, prefer a uniquely matching remote-tracking branch for the destination's branch name. |
| `--relative-paths`, `--no-relative-paths` | `worktree.useRelativePaths`, normally absolute paths | Choose relative or absolute links between Git's worktree metadata and the new directory. |
| `-q`, `--quiet` | Off | Suppress Git's worktree-add feedback, not the plugin's setup output. |
| `--` | Not needed for ordinary paths | End option parsing; the next argument is the destination, even if its name starts with `-`. |

`-B` and `--force` remove Git safeguards; use them only for changes you intend.
This skill has no setup-file override, dry-run, or standalone `--help` flag.
Options for other Git worktree subcommands, such as `prune --dry-run`, do not
apply. Contributor helper self-tests are not skill arguments.

```text
/ioncache-ai-tools:create-worktree -b feature-name .worktrees/feature-name
/ioncache-ai-tools:create-worktree --detach .worktrees/inspection HEAD
```

Runtime requirements and setup configuration:
[workflows.md#worktree-setup](workflows.md#worktree-setup).
Git option semantics: https://git-scm.com/docs/git-worktree and
https://git-scm.com/docs/git-branch.

## plugin-settings

With no arguments, open Claude's native settings pane when available; otherwise
show the grouped text listing. Arguments use the text interface.

| Argument | Default | What it does |
| --- | --- | --- |
| `--list` | Off | Show the settings listing instead of opening the native pane. Does not write settings unless setting-change flags are also supplied. |
| `-h`, `--help` | Off | List accepted flags, including every setting's exact public name, without changing settings. |
| `--global` | Project scope | Read or update global defaults across all three hosts while preserving project overrides. |
| `--project PATH` | Current working directory | Select an existing project directory. With `--global`, this still identifies the project whose effective overrides are shown. |
| `--json` | Off | Return the complete settings view as JSON, including groups, effective values, and any saved paths. Can accompany setting changes. |

Every setting flag below accepts `STATE` as `enabled` or `disabled`, not a JSON
boolean. Multiple setting flags are accepted; repeating one uses its last value.
With no setting flags, there are no writes. **Unchanged** means an omitted flag
preserves the existing value rather than resetting it to the shipped default.
On a fresh installation, all settings below are enabled except
`hook:response-validation`.

### Hook setting flags

| Argument | Default | What it does |
| --- | --- | --- |
| `--hook:answer-questions=STATE` | Unchanged | Control question guidance and the answer-only guard for verified user-question turns. |
| `--hook:autonomous-development:explicit-only=STATE` | Unchanged | Control the tool guard that requires direct user invocation of autonomous development. Native invocation metadata remains separate. |
| `--hook:block_raw_worktree_add=STATE` | Unchanged | Require worktree creation to use the configured setup helper. |
| `--hook:docs-cache=STATE` | Unchanged | Control documentation caching, background fact distillation, and cache notices. |
| `--hook:fix_emdash=STATE` | Unchanged | Control em-dash checks and rewrites for commands and file edits, not chat replies. |
| `--hook:no-manual-lockfile-edit=STATE` | Unchanged | Block direct dependency-lockfile edits through file tools. |
| `--hook:no_broad_process_kill=STATE` | Unchanged | Block broad process-termination commands while allowing specific process targets. |
| `--hook:no_manual_lockfile_edit_bash=STATE` | Unchanged | Block recognized shell commands that directly edit dependency lockfiles. |
| `--hook:plugin-settings-ui=STATE` | Unchanged | Control Claude's native settings pane independently of the settings skill and text interface. |
| `--hook:response-validation=STATE` | Unchanged; shipped disabled | Control Claude's response review and rewriting before delivery, which adds model usage. |

### Instruction setting flags

| Argument | Default | What it does |
| --- | --- | --- |
| `--instruction:documentation-first=STATE` | Unchanged | Supply guidance to verify third-party APIs and behavior against documentation. |
| `--instruction:engineering-judgment=STATE` | Unchanged | Supply engineering-decision guidance and reminders to use the applicable specialist guidance. |
| `--instruction:scope-exactly-what-asked=STATE` | Unchanged | Supply scope guidance without introducing approval gates. |
| `--instruction:writer-quality-guidance=STATE` | Unchanged | Add applicable standards and context/diff self-check guidance to autonomous implementers and fixers. |

### Autonomous-development setting flags

| Argument | Default | What it does |
| --- | --- | --- |
| `--autonomous-development:audit=STATE` | Unchanged | Control authorized publication of process audit evidence to the modified repository's wiki and PR. |
| `--autonomous-development:execution=STATE` | Unchanged | Control execution while retaining preparation, inspection, and interruption controls. |
| `--autonomous-development:follow-ups=STATE` | Unchanged | Control authorized creation or reuse of follow-up issues for unresolved findings. |
| `--autonomous-development:incremental-planning=STATE` | Unchanged | Add planning guidance for PR slices, feature flags, child issues, and compatibility boundaries. |
| `--autonomous-development:model-selection=STATE` | Unchanged | Control automatic selection for development roles; explicit choices remain valid when disabled. |
| `--autonomous-development:progress=STATE` | Unchanged | Control worker progress-checkpoint writes, not the read-only progress viewer or assignment state. |
| `--autonomous-development:rebase-review=STATE` | Unchanged | Permit verified recovery of an accepted review after a clean rebase without repeating unchanged review work. |
| `--autonomous-development:report-contract=STATE` | Unchanged | Add the generated per-role JSON report contract to worker prompts; disabling it does not relax report validation. |
| `--autonomous-development:report-correction=STATE` | Unchanged | Permit two report-correction attempts in the assigned worker after initial validation fails. |
| `--autonomous-development:report-recovery=STATE` | Unchanged | Permit one evidence-based recovery submission for an exhausted job without repeating its work or resetting limits. |

### Review setting flags

These switches are independent of similarly named writing skills.

| Argument | Default | What it does |
| --- | --- | --- |
| `--review:auto-model-selection=STATE` | Unchanged | Control automatic model selection for unspecified review roles. Explicit role choices remain available. |
| `--review:code-complexity=STATE` | Unchanged | Include the code-complexity review category. |
| `--review:comments=STATE` | Unchanged | Include the comment-quality review category. |
| `--review:correctness=STATE` | Unchanged | Include the correctness review category. |
| `--review:design-coherence=STATE` | Unchanged | Include the design-coherence review category. |
| `--review:documentation=STATE` | Unchanged | Include the documentation review category. |
| `--review:incremental-adjudication=STATE` | Unchanged | Assess individual reports before all discovery finishes; disabling uses aggregate adjudication. |
| `--review:integration=STATE` | Unchanged | Include the separate cross-component integration review. |
| `--review:jsdoc=STATE` | Unchanged | Include JSDoc review when the target contains JavaScript; this does not make it apply to other languages. |
| `--review:known-issues=STATE` | Unchanged | Display unresolved material findings in reports and PR drafts; disabling display does not discard the inventory. |
| `--review:performance=STATE` | Unchanged | Include the performance review category. |
| `--review:post-comments=STATE` | Unchanged | Permit review-code's requested comment-posting step. Enabling this alone does not request posting. |
| `--review:privacy=STATE` | Unchanged | Include the privacy review category. |
| `--review:security=STATE` | Unchanged | Include the security review category. |
| `--review:targeted-checks=STATE` | Unchanged | Permit bounded isolated checks; disabling selects source-only review. |
| `--review:test-coverage=STATE` | Unchanged | Include review of whether the relevant behavior is covered by tests. |
| `--review:timing=STATE` | Unchanged | Collect and report runtime measurements; disabling leaves an unavailable total and does not change review coverage. |
| `--review:unit-tests=STATE` | Unchanged | Include review of unit-test quality using the target project's framework. |

### Skill setting flags

These flags control skill use, not whether the CLI displays the skill in its menu.

| Argument | Default | What it does |
| --- | --- | --- |
| `--skill:answer-questions=STATE` | Unchanged | Control loading the question-policy reference skill, not the automatic answer-only hook. |
| `--skill:autonomous-development=STATE` | Unchanged | Control use of the user-invoked autonomous-development skill. |
| `--skill:code-complexity=STATE` | Unchanged | Control the code-complexity writing and explicit-review guidance skill. |
| `--skill:comments=STATE` | Unchanged | Control the comment-writing and explicit comment-review guidance skill. |
| `--skill:create-worktree=STATE` | Unchanged | Control use of the configured worktree-creation skill; the setup helper remains available. |
| `--skill:documentation-writing=STATE` | Unchanged | Control the documentation-writing guidance skill. |
| `--skill:engineering-judgment=STATE` | Unchanged | Control the engineering-judgment skill and its load reminder. |
| `--skill:investigate=STATE` | Unchanged | Control the read-only investigation skill. |
| `--skill:jsdoc=STATE` | Unchanged | Control the JavaScript JSDoc guidance skill. |
| `--skill:plugin-settings=STATE` | Unchanged | Control the settings skill; the standalone settings helper remains available. |
| `--skill:post-pr-review-comments=STATE` | Unchanged | Control the PR comment-writing and posting skill. |
| `--skill:prompt-output=STATE` | Unchanged | Control the prompt-output formatting skill. |
| `--skill:review-code=STATE` | Unchanged | Control the standalone read-only review workflow. |
| `--skill:review-dependabot-pr=STATE` | Unchanged | Control the dependency-update review skill. |
| `--skill:review-triage-loop=STATE` | Unchanged | Control the read-only multi-round review and triage skill. |
| `--skill:review-validate-fix-loop=STATE` | Unchanged | Control the bounded review-and-fix skill. |
| `--skill:security=STATE` | Unchanged | Control the security implementation and explicit-review guidance skill. |
| `--skill:triage-errors=STATE` | Unchanged | Control the grouped-error diagnosis and fixing skill. |
| `--skill:unit-tests=STATE` | Unchanged | Control the unit-test writing and explicit-review guidance skill. |
| `--skill:verify-unresolved-pr-comments=STATE` | Unchanged | Control the read-only PR-feedback triage skill. |
| `--skill:write-pr-descriptions=STATE` | Unchanged | Control the PR title and description writing skill. |

Use `--list` for current values or `--help` for every accepted setting flag.
Setting names, feature meanings, and configuration precedence are documented in
[configuration.md#settings-command](configuration.md#settings-command) and
[configuration.md#feature-ids](configuration.md#feature-ids).
The native pane's internal `--ui` and `--command` helper switches are not part
of the user-facing skill interface.

```text
/ioncache-ai-tools:plugin-settings --list
/ioncache-ai-tools:plugin-settings --global --review:performance=disabled
/ioncache-ai-tools:plugin-settings --project /absolute/project --hook:docs-cache=disabled
```

## autonomous-development

Accepts plain-language input and artifact references, not a fixed skill flag set.
Direct user invocation starts preparation; it does not by itself approve
execution, model spending, commits, or publication.

| Input | Default | What it does |
| --- | --- | --- |
| Idea or existing requirements, issue, design, or plan | Current request; no default project objective | Supply the work to investigate and turn into an approved implementation plan. |
| Planning, design, and execution preferences | Resolve during preparation | Choose where artifacts live and which supported execution path to use. These choices are independent. |
| Permissions, model choices, and finite limits | Must be explicitly resolved before execution | Set the permitted work, publication actions, model choices, and work limits. Existing approval is reused only for what it actually covers. |
| Approved manifest or private run directory | None; prepare a new run unless an existing one is identified | Identify approved inputs or saved state for execution, inspection, continuation, or interruption. State the intended action in the request; there is no skill-level `--resume` flag. |

Flags shown in implementation-helper commands, such as `--provider`,
`--approved`, or `--stale-after`, are not skill arguments. Manifest configuration
and run-control details:
[workflows.md#autonomous-development](workflows.md#autonomous-development).

## engineering-judgment

Accepts plain-language input; no fixed flags.

| Input | Default | What it does |
| --- | --- | --- |
| Task, design decision, or implementation context | Current request | Apply engineering guidance to the requested work, including its constraints and affected code. It does not authorize unrelated changes. |

## code-complexity

Accepts plain-language input; no fixed flags.

| Input | Default | What it does |
| --- | --- | --- |
| Functions, files, or coding task | Current request | Apply function-cohesion, parameter-count, nesting, and control-flow guidance to the supplied work. |

## comments

Accepts plain-language input; no fixed flags.

| Input | Default | What it does |
| --- | --- | --- |
| Code, comments, or comment-writing task | Current request | Apply guidance for useful implementation comments and preserving native API documentation. |

## documentation-writing

Accepts plain-language input; no fixed flags.

| Input | Default | What it does |
| --- | --- | --- |
| Document, text, or writing task | Current request | Apply documentation standards to the requested README, guide, commit message, or other writing. |

## prompt-output

Accepts plain-language input; no fixed flags.

| Input | Default | What it does |
| --- | --- | --- |
| Prompt-writing request or prompt content | Current request | Format the requested prompt as one copyable Markdown code block. The skill supplies the output format, not a default prompt topic. |

## unit-tests

Accepts plain-language input; no fixed flags.

| Input | Default | What it does |
| --- | --- | --- |
| Behavior, source files, tests, or test-writing task | Current request | Apply test-writing or test-review guidance using the target project's language and test framework. |

## jsdoc

Accepts plain-language input; no fixed flags.

| Input | Default | What it does |
| --- | --- | --- |
| JavaScript API, source files, or JSDoc task | Current request | Write or review JavaScript JSDoc contracts, tags, and types. This skill does not target TypeScript or other languages. |

## security

Accepts plain-language input; no fixed flags.

| Input | Default | What it does |
| --- | --- | --- |
| Implementation task, files, or security question | Current request | Apply security guidance to the requested scope, such as input handling, authentication, or API/database access. |
