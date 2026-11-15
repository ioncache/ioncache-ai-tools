# Design coherence

Every file, abstraction, function and test should serve the requested objective.
Evaluate duplication, unrelated behavior and unjustified abstraction against
concrete consequences, not a preference for another implementation.

Keep responsibilities and shared rules coherent across affected components.
Do not prefer a smaller patch that moves a rule to the wrong owner or leaves
consumers inconsistent. Similar code alone does not justify shared runtime code.
An abstraction should protect a concrete responsibility or invariant, not an
imagined future use.

Establish the objective, documented requirements, owners and invariants.
Separate requirements from assumptions. Account for supported deployment,
compatibility and migration needs when judging responsibility boundaries.
Prefer the simplest coherent solution within the owner's actual scope.
Missing context that changes the decision remains explicit uncertainty.
