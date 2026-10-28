# Dependency review workflow

## 1. Inventory the bump

Resolve the repository and PR. Pin three snapshot roles: the PR comparison
base, the target branch's current tip, and the head commit. Use comparison
base to head for the inventory, old/new package evidence, and paired checks.
For GitHub PRs, the comparison base is the merge base, as documented in
[GitHub's comparison rules](https://docs.github.com/en/pull-requests/reference/branches#three-dot-and-two-dot-git-diff-comparisons).
Do not substitute the target tip: it may have changed independently and
already contain a bumped version. If the target tip differs, check it
separately in step 7. If the comparison base cannot be established, report
the review blocked rather than inventing old versions.

Identify every ecosystem and changed manifest or lockfile. Include npm,
Python packages managed with pip, uv, or Poetry, Go, Cargo, Maven, GitHub
Actions, Docker base images, and any other ecosystem present. Use the actual
files and resolved dependency graphs, not just the PR title or direct manifest
constraints. Inventory indirect changes even when their direct parent is pinned.

For each changed resolution, record:

- Package identity, ecosystem, source, old/new resolved versions, and manifest
  and lockfile locations. Keep multiple installed versions or platform variants
  distinct. Match resolutions through their dependency paths, workspace, and
  platform, not the package name alone. Include added/removed packages and
  changed artifact digests or sources even when the version label stays the same.
  Use `absent` for a missing side and identify additions, removals, and
  artifact-only changes explicitly; do not invent an old/new version pair.
- Jump size: major, minor, or patch where the version scheme supports it.
  Flag pre-1.0 versions explicitly; minor bumps may break compatibility.
  Label non-semantic versions, commit pins, and image digests without inventing
  a semantic jump classification.
- Direct or indirect status in each snapshot, including workspace and
  runtime/development/optional scope. For an indirect package, name every
  direct root that pulls it in and preserve the resolved dependency paths.
- Lockfile format changes and resolver/tool compatibility. Record changed
  language/runtime floors, package engine constraints, Python requirements,
  platform constraints, and toolchain requirements.

Account for the complete resolved graph, not only changed lines in a lockfile.
If resolution requires unavailable tooling or an unlocked dependency has no
reproducible old version, record that uncertainty rather than guessing.

### Checkpoint the inventory

Keep a run index and one result file per package in private persistent storage.
Use safe identifiers for filenames, not unsanitized registry names or URLs.
Record repository/PR identity, each snapshot role and SHA, manifest/lockfile
fingerprints, environment assumptions, and the complete ordered package list.

Each package analysis record contains its snapshot SHAs and input fingerprints,
identity and version pair or absent side, dependency parents, status (`pending`,
`in_progress`, `complete`, or `blocked`), completed steps, usage sites/searches,
release and documentation URLs, artifact identities, source citations, impact
decisions, environment drift, required check identifiers, and unverified gaps.

Save after each substantive step and immediately after steps 2 through 6
finish for that package. `complete` means those analysis steps are finished
without unresolved analysis gaps, not that shared validation passed or that
the PR is safe. Analysis gaps keep the package blocked while others proceed.
Keep shared check plans/results in the run index, owned by the coordinator.
Pending shared checks must not force completed package research to restart.

Write each checkpoint to a temporary file in the same directory, validate
its content, then atomically replace the destination. Publish package results
before updating the run index. On resume, reconcile intact package records
with the index so an interrupted index update does not discard finished work.
Do not trust incomplete or malformed records as completed analysis.

On resume, read the saved run instead of repeating finished research. Recheck
the PR snapshots, evidence files, artifact identities, and environment inputs.
Reuse results only when their inputs still match. If a changed snapshot or
dependency graph invalidates conclusions, mark affected packages and shared
checks unfinished; invalidate all when the affected set cannot be established.
Resume unfinished steps without repeating validated completed ones. Retry
blocked steps when the missing evidence or access becomes available; otherwise
continue with pending work and retain the blocks in the report. Resume shared
checks separately, then reconcile their results with package verdicts.

## 2. Map the project's usage

Search both snapshots and record every relevant usage site with `file:line`,
qualified by base or head when the lines differ. Follow aliases, wrappers,
re-exports, dynamic loading, configuration, and generated entry points where
they affect the dependency path.

For direct packages, find imports, API calls, config keys, CLI invocations,
plugin registrations, build steps, CI steps, and container steps. Record actual
arguments, accepted input shapes, option values, defaults relied on, return
values consumed, exception handling, and side effects the project expects.

For indirect packages, trace from project entry points through every relevant
direct dependency into the changed package. Read the parent's code even if its
version is unchanged. Record the intermediate calls and any adaptation or
error handling. An unchanged direct dependency does not isolate the project
from a major indirect bump.

If needed to establish a call path, obtain parent or package source now using
the non-executing inspection rules in step 4. Record the actual parent version
in each snapshot rather than assuming it matches a current local installation.

For formatters, linters, type checkers, test runners, and build tools, record
where they run: local scripts, CI, pre-commit, and container builds. Include
configuration and plugin integrations. Compare old/new output on the current
code during isolated checks, including files untouched by the PR.

When no usage is found, show the exact searches, roots, exclusions, and results.
Check implicit plugin loading, initialization, packaging, installation, and
transitive paths before claiming no reachable usage. A negative name search
alone is not proof of non-use. State the searched scope and leave unresolved
dynamic or external entry points unverified.

## 3. Read the full changelog

For version changes, fetch upstream changelogs, release notes, or tag compare
views covering every intervening release from old exclusive to new inclusive,
including prereleases when applicable. For a downgrade, inspect the reversed
interval and behavior being removed. Enumerate releases and record every URL.
Check pagination and truncation. Do not substitute the PR body's excerpts or
notes for just the endpoint versions.

Read all entries, not only matches for breaking-change keywords. Extract every
entry touching a used symbol, option, default, file format, runtime requirement,
or behavior mapped in step 2. Record why each is relevant. Inspect compare
history when release notes omit versions; missing history remains a disclosed
gap, not evidence that nothing changed.

For an added or removed package, there is no two-version release interval.
Read the present version's release notes and the parent's relevant history.
For same-version artifact/source changes, record that no version interval
exists and inspect the actual artifact differences in step 4. Do not invent
release history or treat an absent counterpart as an unavailable download.

Read authoritative security advisories and record the CVEs or advisory IDs
the bump fixes, affected versions, and relevance to project usage. A security
fix does not prove compatibility. Check the source even when notes describe
the change as a bug fix or omit it entirely.

## 4. Diff the package source

Obtain both exact versions, where present, from their registry or read installs
whose version, origin, and artifact identity can be verified. For each version,
record the artifact URL or local provenance, version, checksum/digest when
available, and platform variant. Verify identity against the snapshot's
lockfile or immutable manifest pins where available; a calculated checksum
alone does not establish that the artifact matches the project resolution.
Read current official documentation before choosing download commands or
registry APIs; save those documentation URLs.

For additions, inspect the head artifact; for removals, inspect the comparison
base artifact. Trace the parent/project path on both sides to explain how
the dependency becomes reachable or ceases to be used. Link replacement
packages rather than pretending they are two versions of the same package.
For same-version source or digest changes, inspect both distinct artifacts.

Keep each inspection copy in its own empty directory outside the project.
Download artifacts as data. Before extraction, check paths and link targets
for traversal or escape from that directory. Do not trust archive filenames.
Never import, execute, install, or build these copies, run their scripts,
start their containers, or evaluate their configuration. Reject retrieval
methods that execute package code to obtain metadata. Reused installs are
read-only evidence too, not permission to load the package.

Inspect the code actually shipped for the project's runtime and platform,
including generated or bundled entry points. Map it to source if necessary.
A source tag is not proof of what a registry artifact contains. If native
code, missing sources, or unverifiable source-to-artifact mapping prevents
comparison, report the affected path as unverified.

Diff the exact symbols and configuration paths mapped in step 2. Follow their
internal calls far enough to establish behavior for project inputs. Include
changed helpers, dependency calls, module initialization, registration, and
defaults that affect those paths even when the public wrapper is unchanged.
Compare errors raised, return shapes, ordering, side effects, and relevant
runtime or performance behavior. Cite version-qualified source `file:line`
or immutable upstream links for both sides. Do not stop at an unchanged
signature, a short diff excerpt, or a release-note claim.

For GitHub Actions, compare the action definition's inputs, outputs, defaults,
and runtime, then follow its entry point and the code behind every workflow
input used. Include composite steps and referenced actions or images.

For container base images, resolve exact image identities and target
architectures. Read image metadata and filesystem/package inventories without
starting the images. Compare the OS, language runtime, and system libraries
the project's build and runtime paths use. Trace relevant upstream source
changes where an inventory alone cannot establish compatibility.

## 5. Judge the impact on this project

For every relevant change from steps 3 and 4, record the affected project
`file:line`, the exact input or call, and a concrete before/after. Explain the
old result X and new result Y with both source paths and project assumptions.
Separate conclusions established by static source tracing from observed check
results. Never claim to have reproduced behavior by merely reading it.

For additions, removals, and replacements, the before/after is the project
call path and its outcome, not a fictional implementation on the absent side.
Do not declare a removed package harmless without checking the replacement
path and any installation or initialization behavior the project relied on.

Use one of these verdicts for verified changes:

- **no impact**: show why the changed behavior preserves this project's
  contract or cannot be reached with its actual inputs/configuration.
- **breaks**: give the reachable failure scenario and resulting project failure.
- **needs a project change**: identify the specific required configuration,
  usage, runtime, or tooling adjustment and what fails or changes without it.

If evidence cannot decide, mark the case unverified rather than choosing a
verdict. Preserve verified findings alongside gaps. At package level, summarize
the actionable verdicts without hiding unresolved paths behind "no impact".
Packages with no mapped runtime usage still need installation, tooling,
environment, and packaging compatibility accounted for.

Fictional example: `src/preview.py:42` falls back when an image decoder returns
no image for a truncated header. The old decoder returns no image; the new
decoder raises an exception that the caller does not catch. Cite both decoder
implementations and the project fallback. The finding is that malformed image
input now aborts preview generation, not that the image library "could break".

Save individual package analyses without waiting for other packages. After
collecting them, the coordinator reconciles grouped changes across package
boundaries and records any remaining gaps. Check the combined graph and shared
call paths; individually compatible packages can change each other's inputs.
Do not attribute a failure to one package without evidence.

## 6. Check environment drift

Compare the resolved requirements against Dockerfiles, CI setup steps, language
version files, toolchain-manager configuration, local scripts, and pre-commit
configuration. Record pins that the PR leaves behind.

Check specifically for:

- A new runtime floor or lockfile format unsupported by a pinned environment.
- CI installing an unpinned latest tool while a container pins an older one.
  A green CI run does not establish that the container can install or build.
- Build or packaging tools declared as runtime dependencies. Trace production
  installation and packaging rules to establish whether they ship in artefacts.
- Formatter or linter changes that rewrite or flag existing files the PR does
  not touch. Record the affected files and expected later-PR churn.

Give each drift finding the conflicting `file:line` pins and a concrete
failure or output change. Keep pre-existing drift distinct from newly
introduced or worsened drift. Do not silently align versions to make checks pass.

## 7. Run the project's checks on both base and head

Discover the project's documented validation commands, scripts, and CI jobs.
Verify all command syntax and flags against current official documentation
for the pinned tool versions before use. Record the documentation URLs.

The coordinator runs shared checks once per required snapshot/environment
combination and saves results under the check identifiers used by packages.
Workers must not run overlapping installs or checks in shared environments.

Use separate disposable comparison-base and head environments, with each
snapshot's own lockfiles and the project's pinned tools where possible.
If the target-branch tip differs from the comparison base, also run the
applicable checks on that pinned tip and label those results separately.
They establish current base-branch health, not the PR's old package behavior.
Do not reuse the user's dependency installation or modify reviewed snapshots.
Isolate caches and generated outputs that could contaminate the comparison.

Inspection artifacts from step 4 remain inert. Project validation is the only
execution phase: it uses separate installations and can execute dependencies
through installs, tests, tools, or builds. Inspect those commands first and
use the available sandbox and permission controls, without production secrets,
privileged host access, or deployment side effects. If that execution cannot
be isolated or authorized, skip it with the reason; never treat it as passed.

Run frozen or locked installation, tests, lint, format check, type check, and
container builds wherever applicable. Use non-fixing modes. Do not regenerate
locks, reformat source, update snapshots, or weaken checks. Confirm the
installed resolutions and artifact identities match each inventory. Missing
pins or unavailable tools are limitations, not permission to use the latest
version silently.

Run the same checks on comparison base and head under comparable environments.
If the PR intentionally changes a tool/runtime pin, use each declared pin and
record the difference. An extra comparison with a common supported toolchain can
clarify attribution but must not replace the required pinned-environment check.
For tooling changes, compare diagnostics and proposed formatting on identical
project inputs so source changes do not masquerade as tool behavior changes.

Record exact commands, working directories, tool/runtime versions, exit status,
relevant output, and log locations for both snapshots. Separate existing base
failures, new head failures, and inconclusive environmental failures. A base
failure does not excuse a different head failure. List every skipped or
inapplicable check with its reason. Passing checks supplement source evidence;
they never replace steps 2 through 5.

## 8. Report

Recheck snapshot identities before finalizing. If inputs changed, apply the
checkpoint invalidation rules before claiming anything about the current PR,
or limit the report to the reviewed SHAs and mark the current PR unverified.
Reconcile every inventory entry with a completed result or an explicit
unverified gap; include failed workers and interrupted packages. Report the
private run directory for resume,
package-analysis counts by status, shared-check outcomes, covered environments,
and overall completeness. A completed analysis record cannot override a
failed or skipped required check.

Return a per-package table, preserving distinct resolutions:

| Package | Old to new | Jump | Direct/indirect and direct parents | Usage sites | Relevant changes | Verdict | Evidence links |
| --- | --- | --- | --- | --- | --- | --- | --- |

Use version-qualified project/source citations and upstream URLs. Summarize
verified verdicts and visibly flag any remaining gaps in the row; do not
force an unverified package into a clean verdict.

Then return findings ranked most severe first. Use High for correctness or
security failures, Medium for reliability/contracts/tooling, and Low for
cosmetic churn. Each finding needs project `file:line`, a one-sentence problem
statement, a concrete failure scenario with before/after, source evidence,
and the minimal recommended project action. Do not apply it.

Always include an **Unverified** section listing what was not checked, why,
the affected packages/paths/environments, and the evidence needed to finish.
Use "None" only when there are no gaps. Speculative "could break" statements
belong here, never in findings.

Finally include the check comparison:

| Check | Exact base command and environment | Base result | Exact head command and environment | Head result | Attribution or skip reason |
| --- | --- | --- | --- | --- | --- |

Label each base role and immutable SHA explicitly. When the target tip differs,
include its check results separately rather than replacing comparison-base
results. Include logs and environment differences, not just pass/fail totals.
End with the compatibility conclusion for the checked scope and any work still
unverified. Do not approve the PR or turn the report into posted comments.
