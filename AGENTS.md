# Contributor instructions

These instructions apply to work on this repository. They are not plugin runtime
policy and must not be injected into consuming projects.

Read [.github/copilot-instructions.md](.github/copilot-instructions.md) for
architecture, validation commands, and contributor conventions.

## Primary invariant: enforcement without deadlock

The plugin exists because agents can ignore instructions, memory, and skills.
Hooks must enforce those requirements without breaking the harness.

**Block noncompliant actions, never leave the user with no usable way forward.**

A policy denial may persist while its underlying violation remains. The user
must still have a supported route to clarify or change the request, supply
required evidence or authorization, and resume legitimate work. An explanation
alone is not recovery if legitimate work can never resume.

## Design and review requirements

- Make each denial actionable. Identify the unmet requirement and a supported
  recovery step that remains reachable under the combined hooks and rules.
- Keep error explanations, necessary read-only investigation, and genuine user
  input reachable. Never require a blocked action to obtain the evidence or
  authorization needed to unblock that same action.
- Distinguish policy violations from missing context and checker failures.
  Recovery must not depend solely on the component that failed.
- Reevaluate changed requests, candidates, and evidence instead of preserving
  stale denials. Retain enough proposal, approval, and denial context for
  recovery, without treating missing or truncated context as consent.
- Bound automated retries and correction loops. Exhaustion must produce an
  explicit recovery or escalation path, not endless identical rejections.
  Never grant permission, weaken a restriction, or mark a failed check as
  successful merely because a retry budget ran out.
- Do not make disabling the plugin or manually rewriting its private state the
  only recovery path.

## Verification

Treat an unrecoverable state as a merge-blocking defect.

For changes affecting enforcement, extend the existing self-checks to demonstrate
the whole sequence: a violating action is denied, legitimate recovery through
supported inputs succeeds, and authorized work can resume. Verify that actions
which still violate the policy remain blocked.

Cover relevant failure and lifecycle cases, such as checker unavailability,
cached denials, approval or evidence eviction, compaction, resume, and subagent
handoffs. Exercise interactions through affected host adapters, not just isolated
denial functions. Follow the existing isolated-reviewer test conventions.

Passing one regression is not proof that every recovery path works. Report
remaining verification gaps rather than claiming a guarantee.
