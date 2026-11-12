# Contributor instructions

These instructions apply to work on this repository. They are not plugin runtime
policy and must not be injected into consuming projects.

Read [.github/copilot-instructions.md](.github/copilot-instructions.md) for
architecture, validation commands, and contributor conventions.

## Primary invariant: autonomous continuation

This plugin supplies guidance to continuous autonomous workers. Guidance must
not become a permission state machine that stops a worker.

**Every plugin-owned denial must leave an agent-executable recovery path.**

A narrow action guard may deny an unchanged violation, but the worker must be
able to take an allowed alternative and continue. Asking a human, restarting
the session, or disabling the plugin is not sufficient recovery for an
unattended worker. Scope and question instructions are guidance, not gates.

## Design and review requirements

- Make each denial actionable. Identify an autonomous recovery step that remains
  reachable under the combined hooks and rules. Do not retain a blocking feature
  that cannot satisfy this requirement.
- Keep error explanations, necessary read-only investigation, and genuine user
  input reachable. Never require a blocked action to obtain the evidence or
  authorization needed to unblock that same action.
- Distinguish policy violations from checker failures. A failed guidance check
  reports its unavailability without inventing a policy verdict or granting
  native host permissions. Recovery must not depend on the failed checker.
- Reevaluate changed requests, candidates, and evidence instead of preserving
  stale denials. Retain enough proposal, approval, and denial context for
  recovery, without treating missing or truncated context as consent.
- Bound automated retries and correction loops. Use an allowed alternative or
  continue other authorized work, not endless identical rejections.
  Never grant permission, weaken a restriction, or mark a failed check as
  successful merely because a retry budget ran out.
- Do not make disabling the plugin or manually rewriting its private state the
  only recovery path.

## Verification

Treat an unrecoverable state as a merge-blocking defect.

For changes affecting enforcement, extend the existing self-checks to demonstrate
the whole sequence: a violating action is denied, agent-executable recovery
succeeds without human intervention, and authorized work can resume. Verify that actions
which still violate the policy remain blocked.

Cover relevant failure and lifecycle cases, such as checker unavailability,
cached denials, approval or evidence eviction, compaction, resume, and subagent
handoffs. Exercise interactions through affected host adapters, not just isolated
denial functions. Follow the existing isolated-reviewer test conventions.

Passing one regression is not proof that every recovery path works. Report
remaining verification gaps rather than claiming a guarantee.
