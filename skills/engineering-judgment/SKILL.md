---
name: engineering-judgment
description: Guides engineering decisions toward coherent behavior across the affected application or services, rather than the shortest patch. Use when implementing non-trivial features or fixes, refactoring, choosing abstractions or dependencies, or reviewing design and contract changes.
---

# Engineering judgment

Prefer the simplest coherent solution, not the fewest changed lines or files.
Understand broadly enough to make the change sound. Change only what the
requested outcome needs, within the user's authorization.

Keep the effort proportional. A local correction with no contract impact does
not need an architecture review. This skill does not authorize edits during
questions, planning, or read-only reviews.

## Understand the affected system

1. Establish the requested outcome, explicit scope limits, and documented
   requirements. Separate those from assumptions and possible future needs.
2. Read the relevant code and project decisions. Trace affected producers,
   consumers, shared rules, and stored data. Follow contracts across packages
   or services when the change reaches them, not every service by default.
3. Identify who owns each affected responsibility and what must remain true.
   Consider deployment topology, failure behavior, and compatibility when
   relevant. A fix that works in one process may fail across replicas.
4. Use actual consumers, supported behavior, and documented load as evidence.
   Do not invent another service's contract or requirements. If missing context
   changes the choice materially, ask or report the limitation.

## Choose the solution

Evaluate choices in this order:

1. Satisfy the requested behavior, correctness, security, and compatibility
   obligations. Do not trade these away to reduce the patch.
2. Keep responsibilities and contracts coherent across the affected system.
   Avoid duplicating a business rule or moving work into the wrong layer just
   because it requires fewer edits.
3. Among sound choices, prefer the least unnecessary complexity and maintenance
   burden. Line and file counts are not measures of correctness or cohesion.

Reuse project components, standard or platform features, and installed
dependencies when their semantics and lifecycle fit. Do not force reuse or
hand-roll a replacement merely to avoid a justified dependency.

Preserve established boundaries unless they cause the problem. A necessary
interface change or focused refactor is not an unrequested feature. An
abstraction should protect a concrete responsibility or invariant, not an
imagined future use. Similar code in independent services does not by itself
justify shared runtime code or tighter deployment coupling.

## Keep the scope honest

Include supporting callers, tests, configuration, and documentation needed
for the requested outcome. For contract or data changes, account for affected
consumers and rollout or migration needs.

Honor explicit file, service, behavior, and action limits. If the sound solution
exceeds them, explain the dependency and ask for approval. Do not silently widen
the work or ship a local workaround that leaves the known problem elsewhere.
Leave unrelated cleanup and speculative redesign out.

## Complete and check the change

Check the affected behavior end to end at the relevant boundaries, including
failure cases and compatibility. Use focused tests that distinguish the sound
solution from the tempting local patch. Keep validation proportional.

When delegating, pass the relevant contracts, ownership constraints, authorized
scope, and this decision order explicitly. Do not assume workers inherit the
skill or have loaded it. Reconcile their results across affected boundaries.

Keep explanations concise without hiding material tradeoffs or gaps. Explain
why broader supporting changes are necessary when that is not obvious. Do not
produce an architecture report or fixed checklist in every response.

## Examples

| Situation | Appropriate judgment |
| --- | --- |
| A local label is wrong | Correct the label and relevant expectation; do not redesign the UI. |
| Two callers apply the same pricing rule inconsistently | Fix the responsible domain rule and affected callers, not another caller-specific exception. |
| An event field must change while old consumers remain deployed | Address consumer compatibility and rollout, not just the producer's output. |
| A cache must coordinate across replicas | Check the actual deployment and consistency needs; process-local state may not solve the task. |
| A helper might support more backends someday | Keep the current implementation unless a concrete boundary or requirement justifies abstraction. |
| Only one service is authorized for edits, but its contract change needs another | Explain the dependency and request scope approval instead of breaking the consumer or editing it silently. |
