# Integration contracts

Trace actual producer and consumer together across the requested scope.
Parameter, return, error and side-effect contracts must match actual callers.
Check moved/shared code and all affected consumers rather than signatures or
directories in isolation.

Inspect event/webhook ordering, background work, polling, queues and readiness.
A readiness signal must establish the prerequisites its consumer needs, not
merely occur last among the events inspected.

Trace record and configuration producers through their readers, including
normalization, persistence, delivery and resumed consumption. Preserve evidence
and authority at handoffs. Do not assume metadata causes behavior without an
actual consumer implementing it.

Record the boundaries traced and any missing endpoint or prerequisite evidence.
Source/file union alone does not prove end-to-end semantic coverage.
