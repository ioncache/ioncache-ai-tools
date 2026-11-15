# Documentation materiality

Report inaccurate descriptions, types, examples, or operational instructions
when they cause a concrete mistaken action, consequential misunderstanding,
or maintenance risk. Name that consequence. No runtime incident is required,
but inaccuracy alone is insufficient. Stale rationale that changes nothing
a reader should do belongs in `None`, not a wording-cleanup backlog.
Resolve mismatches against the intended contract; do not assume the code
is right and rewrite documentation to match a bug.

Accurate documentation that differs only in style or shape is not an actionable
finding. For example, an accurate inline JSDoc object type instead of a named
typedef violates a presentation convention, not the documented contract.
Being new code or violating a documented style rule does not change that.
