# Functional correctness

Check supported behavior and reachable failure paths, recording applicability:

- Functional results, boundary values, mode, flag and configuration interactions.
- Swallowed errors and silenced signals: catches, fallbacks, filters and noise
  lists that hide failure from a caller or observer.
- Races against cached or asynchronous state, stale reads and interrupted work.
- Cleanup and teardown that stop at the first failure or leave partial state.
- Changed batching, enumeration, cleanup and retries: pagination, maximum sizes,
  rate limits, partial results and completion semantics at realistic volume.
  A successful response need not mean the operation completed.

Read actual callers and relevant implementations. Consult authoritative
documentation where a third-party default or contract determines behavior,
including unchanged calls whose inputs the change enlarges.
Support every finding with a reachable trigger and consequence.
