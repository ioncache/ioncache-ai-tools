# Development and plugin maintenance

Installation: [../README.md#install](../README.md#install).
Contributor requirements: [../AGENTS.md](../AGENTS.md) and
[../.github/copilot-instructions.md](../.github/copilot-instructions.md).

## Local development

Use Python 3.15, Node.js 22.12.0+, npm, Git, and macOS or Linux for contributor
checks. The installed plugin runtime supports Python 3.11+.
From the repository root:

```sh
npm ci
```

This installs contributor tooling and activates Husky's `commit-msg` hook.
Repeat it in each checkout or worktree. This repository's worktree setup runs
it automatically. Plugin users do not need these npm dependencies.

Validation commands are maintained in
[../.github/copilot-instructions.md#validation-commands](../.github/copilot-instructions.md#validation-commands).

### Native settings pane tests

`npm ci` includes the pinned Claude Code CLI used by `npm run test:settings-ui`.
These native mod tests need no sign-in, network, or model calls. They mount the
pane on terminal, Desktop, and VS Code surfaces, press controls, and stub the
process boundary. The Python configuration self-checks exercise real settings
reads, writes, scope precedence, and recovery. One process-tier test starts
the native command alongside the skill and verifies persisted changes, with
isolated preferences and model traffic directed to a closed local endpoint.

The Claude mod in `hooks/plugin-settings.mjs` is an ES module because the host
requires that format; its native tests use `.test.ts`. Neither needs a build
step. Other Node helpers remain CommonJS. After changing layout, also inspect
the pane in an interactive Claude session; the native test kit validates trees
and callbacks, not terminal painting.

### Python tests

Install the pinned contributor-only dependencies in each worktree:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
```

CI pins Python 3.15 to match the local test runtime. The plugin runtime remains
standard-library-only. Pytest collects the existing
`unittest.TestCase` suites and the two wrapped custom-main checks.

```sh
.venv/bin/python -m pytest -n auto
.venv/bin/python -m pytest -n auto scripts/development_run_self_check.py
.venv/bin/python -m pytest hooks/scripts/copilot_adapter_self_check.py::CopilotAdapterTests::test_native_shell_rules
.venv/bin/python -m pytest -n auto -m process
```

`-n auto` uses separate worker processes, not threads. The tests patch global
environment and signal state, so thread-based parallelism is unsafe. Each test
gets isolated files, HOME, XDG, host settings and Git configuration. The default
duration report lists the slowest 20 setup, call or teardown phases. Use
`--junitxml=results.xml` for per-test timing data. Aim for a full local run near
one minute on a 12-core Mac; investigate regressions instead of adding workers
blindly. CI uses the same parallel command and retains the Node and release
checks.

Ordinary state, validation and recovery tests invoke the actual Python `main()`
functions in-process, including argument parsing and protocol streams.
`tests/self_check_support.py` restores environment, working directory, standard
input, arguments and alarm state between calls. Hook tests run the shared
manifest's real handlers in-process; unknown handlers still use their real
subprocess path. Persisted workflow scenarios run the actual JavaScript workflow,
but bridge Python helper commands back into the isolated Python fixture. The
bridge executes the generated report-submission argv rather than replacing it
with a successful canned result.

The explicit `process` tier covers native adapters and recovery, CLI failures,
locking, crash publication and restart, pinned executors and launch scripts,
the native Node workflow, monitor processes and the release helper. A process
marker normally switches shared CLI helpers to subprocesses too.
`@pytest.mark.process(helpers=False)` identifies tests with their own explicit
process launch, while allowing ordinary setup to stay in-process.
Git commands and the Node workflow also remain real in other tests; the marker
selects boundary contracts, not every test which happens to start a process.

Build new scenarios with shared immutable starting fixtures and private copies.
The two largest suites copy a committed Git seed into each test's directory.
Do not copy persisted run state with absolute roots, worktree paths or content
digests unchanged. Non-process development scenarios pin a small representative
executor; executor-resource and native-launch tests pin the complete source.
Opt into further fixture assumptions explicitly:

- `state_logic` preserves HEAD, index and file membership while re-reading live
  file content. Teardown verifies those assumptions against a real snapshot.
  Do not use it for ownership, staging, commit or file-addition/removal tests.
- `stable_storage` reuses external-directory eligibility during a scenario,
  then verifies every cached result at teardown. Do not use it when moving a
  store, changing symlinks or creating repositories changes that eligibility.

Neither marker permits temporarily violating its assumptions and restoring them
before teardown. Keep boundary cases unmarked and retain the fixture guard
tests. Enforcement coverage must still demonstrate denial, executable recovery
and resumed work through the relevant adapters, including failure and lifecycle
cases. When changing a fixture or bridge, deliberately break the behavior it
claims to cover and confirm the relevant test fails.

#### Performance reference

The modernization baseline collected 691 tests and passed in 150.15 seconds
with `-n auto` on a 12-core Mac. Before incorporating subsequent upstream
coverage, the revised suite collected 699 tests, including
48 explicitly marked process tests, and passed in 65.55 seconds on that Mac
and 23.93 seconds in a 10-worker Linux container. Both used Python 3.15.2.
Mac measurements ranged from 63 to 66 seconds: close to the one-minute goal,
but not yet below 60 seconds. Linux container results are not GitHub Actions
runner timings.

The before column below comes from the original handoff: the development file
ran serially alone; the other files ran serially with six files concurrent.
The after column measures each file alone with `pytest -n auto`, including
worker startup. These are wall times, not summed worker durations, and the
different concurrency means the ratios are not isolated implementation speedups.
Running the whole suite once shares startup and is faster than adding the after
column.

| Suite | Before (seconds) | After (seconds) |
| --- | ---: | ---: |
| `scripts/development_run_self_check.py` | 661 | 47.76 |
| `scripts/review_ledger_self_check.py` | 168 | 12.34 |
| `hooks/scripts/copilot_adapter_self_check.py` | 54 | 4.73 |
| `hooks/scripts/codex_adapter_self_check.py` | 47 | 4.20 |
| `hooks/scripts/pending_question_self_check.py` | 9 | 1.19 |
| `hooks/scripts/plugin_config_self_check.py` | 6 | 2.54 |
| `scripts/release_self_check.py` | 4 | 1.55 |
| `hooks/scripts/turn_guard_self_check.py` | 4 | 2.24 |
| `hooks/scripts/claim_evidence_self_check.py` | 3 | 2.46 |
| `scripts/review_options_self_check.py` | 3 | 1.60 |
| `scripts/review_assignments_self_check.py` | 2 | 1.44 |
| `scripts/review_comments_self_check.py` | 1 | 1.33 |
| `hooks/scripts/docs_cache_self_check.py` | <1 | 0.93 |
| `hooks/scripts/rule_engine_self_check.py` | <1 | 2.15 |
| `tests/test_self_check_support.py` | New | 1.01 |

Eight temporary mutations in disposable source copies were detected: accepting
implementation HEAD/index drift, accepting stale ledger revisions, corrupting
Copilot denial output, ignoring Codex denial precedence, allowing question-turn
writes, ignoring rule-engine denials, corrupting generated workflow `submit`
arguments, and reusing stale file content in the snapshot fixture. The submit
mutation failed both a bridged scenario and a native-process scenario.
These checks support retained coverage in the changed areas, not a proof that
every possible regression is detectable.

### Loading source changes

For a session using a live checkout, run one of these from its root:

```sh
claude --plugin-dir .
copilot --plugin-dir .
```

Claude relative-path plugins from local-directory marketplaces also load in
place. Reload with `/reload-plugins` or start a new session after changes.
Remote installs are cached.

Direct Copilot repository installs use a cached copy. For a persistent local
source, register a local marketplace and install from it:

```sh
copilot plugin marketplace add /absolute/path/to/checkout
copilot plugin install ioncache-ai-tools@ioncache-ai-tools
```

Start a new session after source changes. `copilot plugin install .` is not a
supported local-directory installation command.

Codex installs use cached copies too. Update the source referenced by the
marketplace, reinstall with
`codex plugin add ioncache-ai-tools --marketplace ioncache-ai-tools`, and start
a fresh thread. This repository's shipped Codex marketplace points to remote
`main`; local testing requires a marketplace entry pointing at the checkout.

Refresh installed copies when testing background reviewers or documentation
distillers, even if the main session uses a live checkout. Feature settings
live outside the plugin cache and need no reinstall.

Category-isolation acceptance needs fresh host sessions using this source,
including child workers. A source self-check does not replace native instruction
delivery evidence. Do not treat an old cached session as testing the new guidance.
Refresh catalog writers together: older copies can erase new `review-*` settings.
See [review-evaluation.md](review-evaluation.md) for the separate offline/native
acceptance paths and [configuration.md](configuration.md) for rollout limitations.

Host documentation:

- https://code.claude.com/docs/en/plugins/loading
- https://developers.openai.com/plugins/build/plugins
- https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference

## Updating and removing installed plugins

Use Claude Code's `/plugin` interface to update or remove the plugin.
For Copilot, use `copilot plugin update ioncache-ai-tools` or
`copilot plugin uninstall ioncache-ai-tools`.

Refresh the Codex marketplace and reinstall:

```sh
codex plugin marketplace upgrade ioncache-ai-tools
codex plugin add ioncache-ai-tools --marketplace ioncache-ai-tools
```

To remove the Codex plugin and its marketplace:

```sh
codex plugin remove ioncache-ai-tools --marketplace ioncache-ai-tools
codex plugin marketplace remove ioncache-ai-tools
```

Start a fresh session or thread after updating. Settings reconcile on the next
hook invocation; explicit synchronization is described in
[configuration.md](configuration.md).

## Commit conventions

Commit messages and PR titles follow Conventional Commits, for example
`fix: preserve hook permissions` or `feat(review): add draft comments`.
Generated merge, revert, and version messages are not exempt. Write reverts as
`revert: describe the reverted change`.

The `Commit conventions` workflow checks PR titles, PR commits, and commits
pushed to `main`. Local hooks can be bypassed. Require that status check on
`main` to block merges on failures. Squash-only merging, PR titles as squash
messages, and linear history are separate GitHub repository settings; the
tooling does not configure them. A bad edited squash message is reported by
the push check after it reaches `main`.

## Version changes and changelog

Every version change must update [../CHANGELOG.md](../CHANGELOG.md) with New,
Updated, and Fixed sections. In a clean feature worktree, commit the intended
changes first, then run:

```sh
npm run release -- VERSION
```

Replace `VERSION` with an increasing `MAJOR.MINOR.PATCH` version.
The helper requires contributor dependencies and full Git history. It uses
https://conventional-changelog.js.org/ with the Conventional Commits preset.
It updates all three plugin manifests and prepends notes from commits since
the commit that introduced the current manifest version. Metadata-only
manifest edits do not reset that boundary; no release tags are required.

`feat` and `feature` commits become New items, `fix` commits become Fixed
items, and other commits become Updated items. Breaking changes get a separate
section. Merge commits are excluded; reverted commits and their reverts remain
visible. Items link to commits, and empty sections say `None.`.

Review the generated notes, then commit the manifests and changelog together.
The helper does not commit, tag, push, or include uncommitted changes.
Check manifest and changelog consistency with:

```sh
npm run release:check
```
