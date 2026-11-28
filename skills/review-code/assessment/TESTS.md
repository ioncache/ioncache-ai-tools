# Test gaps

Missing coverage of new or changed code is actionable by default. Aim for
100% coverage with meaningful assertions covering supported behavior, including
branches and failure paths. Do not decide a test is unnecessary merely because
the implementation looks simple or the path seems less important.

Identify the uncovered behavior and what an assertion must detect if it
regresses, including the consequence. Use that explanation to design the test,
not to justify skipping meaningful coverage. If a proposed test describes
production misbehavior, first investigate whether the trigger is reachable
and report the underlying defect when supported, with the test as regression
protection. Do not downgrade a production bug into a test-gap finding.
Coverage measures execution, not whether assertions detect wrong behavior.
Exceptions need concrete evidence tied to the supported contract or the
extreme-edge-case rule; record their rationale. Missing coverage measurements
are unknown, not proof of a gap or proof of 100% coverage. Respect the caller's
check permissions and distinguish source inspection from executed coverage.
Neither small code nor an immediately visible error is a blanket exemption:
check whether side effects or damage can precede that error. Conversely, a
second assertion of already-protected behavior needs a distinct regression
it would catch, not just another route through the implementation.

Source reasoning can establish a test gap unless the supplied user/project
rules require mutation proof. Do not impose a universal mutation run.
When proof is required, use an authorized isolated copy and distinguish the
baseline from the changed behavior: a surviving meaningful mutation supports
a gap, while an assertion failure can demonstrate existing protection.
Missing dependencies, crashes and unavailable execution are not either result.
Run only the smallest discriminating checks, retain outputs and input identities,
and never automatically install packages or mutate the reviewed tree.
