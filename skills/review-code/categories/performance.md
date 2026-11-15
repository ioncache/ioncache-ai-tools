# Performance

Evaluate latency, throughput, memory, I/O and repeated work against supported
input volume, concurrency and workload, not speculative scale.
Trace loops, queries, copying, serialization, retries and caches to the actual
consumer. Check whether costs multiply across items, phases or processes.

Use bounded measurements or source-supported growth and realistic inputs.
Explain why the cost matters under an established operating condition.
Do not invent host/model limits or propose removing required independent work
solely to reduce a count. Distinguish unavoidable contract cost from avoidable
duplication, unbounded growth or resource retention.
