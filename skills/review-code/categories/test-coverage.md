# Meaningful test coverage

Use the project's actual languages, test runners and verification seams.
Inspect assertions for supported new or changed behavior, including branches,
failures and side effects that can occur before an error. Execution coverage
does not prove that assertions detect wrong behavior.

Identify the regression a missing assertion must catch. If a proposed test
describes production misbehavior, first establish reachability and report the
underlying defect when supported, with the test as regression protection.

For plans, check whether specified controls distinguish the intended behavior
from the failure: include relevant recovery sequences, lifecycle combinations
and negative controls. Offline records cannot establish native/model behavior.
Separate absolute expected behavior from relative non-regression; equal failure
is not demonstrated success.

Do not impose another framework's conventions. Respect allowed checks and
distinguish inspected tests from executed tests and observed coverage.
