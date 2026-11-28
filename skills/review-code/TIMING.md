# Review runtime reporting

The caller owns timing collection and presentation. Do not launch a timing
agent or give reviewers another assignment. Record observations during the
review regardless of `run_details`; that option changes only the final display.
Timing is diagnostic evidence, never a completion or permission gate.

Every final review response includes the compact summary. Example values:

```text
Total elapsed: 9m 00s
Setup: 1m | Longest reviewer: 5m | Adjudication: 1m 30s | Final merge: 1m | Posting: 30s
```

The renderer separates the second line's items with middle dots. Do not add
the agent table, timeline or wait breakdown unless normalized `run_details`
is true. Missing measurements say `unavailable`; an explicitly skipped stage
says `not run`. Never substitute estimates or silently omit total elapsed time.

## What the compact numbers mean

- **Total elapsed:** wall-clock time from the accepted review invocation to
  the reporting cutoff, after optional posting and report preparation. Include
  setup, queueing, pauses and other gaps, not just agent execution.
- **Setup:** observed preparation intervals before dependent dispatch.
- **Longest reviewer:** the maximum individual discovery-agent duration,
  including the integration category and failed or replacement attempts.
  Do not sum concurrent agents or call this the discovery phase's wall time.
  If any reviewer duration is missing, the maximum is unavailable.
- **Adjudication:** remaining assessment and required validation after discovery
  finishes and before final merge starts. Earlier overlapping report assessments
  remain in the agent records and detailed timeline. In aggregate mode, record
  the whole independent adjudication here.
- **Final merge:** cross-report reconciliation and presentation intervals.
  In aggregate mode, mark this `skipped` because it is not a separate pass.
- **Posting:** the attempted publication interval, including any permitted
  recovery. Mark it `skipped` when posting was not requested or attempted.

Record separate stage intervals for repeated phases. The helper measures their
union, not their sum, so overlapping observations do not count twice. These
numbers need not add up to total elapsed: individual maxima, overlapping work,
queueing and gaps are different measurements.

## Capture once, reuse native evidence

After valid option normalization and before target discovery, retain the
invocation timestamp when exposed, or a current caller-clock observation.
Record the cutoff before rendering the final timing report. Do not create
timing artifacts for help or an unstarted invalid invocation.
If the first available observation is later than invocation, state that the
measured window excludes earlier setup in the compact report's limitations.
Do not describe that partial window as the full invocation duration.

Maintain the sidecar as part of the existing caller lifecycle:

| Boundary | Record |
| --- | --- |
| Accepted invocation | Allocate `timing_file` in private scratch, retain the sourced start and begin setup. |
| Dispatch and result delivery | Append each attempt, then fill observed endpoints and collection separately; leave hidden events null. |
| Last discovery completes | Begin the remaining adjudication interval; record any evidenced dependency waits. |
| Final merge dispatch and completion | Finish adjudication and record merge separately. Zero remaining adjudication is valid when its two boundaries coincide. |
| Optional posting | Record the attempted interval or an explicit skipped stage. |
| Final local report | Finish the reporting window, persist the sidecar, render it and append the output to the findings. |

Only the top-level caller writes the consolidated sidecar. A nested coordinator
retains its workers' observations in a separate private contribution file and
returns its path. The caller merges that evidence without concurrent writes.
Keep the sidecar path and existing observations across compaction or resume.

Prefer timestamped native launch/completion records and the caller's existing
assignment map. Observe each physical agent attempt separately, including
coordinators, discovery workers, report adjudicators, merge adjudicators,
validators and failed launches. Keep the actual native worker identity when
exposed, otherwise null. Assignment IDs are not native worker IDs.

For each attempt, distinguish:

- `queued`: the assignment was eligible for dispatch.
- `started`: observed execution start, or caller dispatch time with that source
  distinction retained. A dispatch interval can include native queueing.
- `finished`: observed completion, failure or confirmed cancellation.
- `collected`: the caller received the complete report or terminal outcome.

Late collection is not late execution. A completion notice containing only a
duration supplies `duration`, not invented start/finish timestamps. Failed
launches may have no execution interval. Unconfirmed cancellation leaves the
finish unknown. Corrected reports and retries retain their original observations;
do not reset the review clock or overwrite earlier attempts.

Use existing lifecycle timestamps before adding tool calls. Batch caller-clock
capture into existing launch/collection operations when possible; never poll
workers, add serial model turns just for timestamps, or fetch a new native
transcript for every event. If needed, this read-only helper emits a sourced
current observation:

```sh
python3 -B "/absolute/plugin/scripts/review_timing.py" stamp
```

`stamp` is the time of that observation, not evidence of an earlier event.
Sources must establish the timestamp's meaning and use comparable clocks.
Clock uncertainty remains a limitation. File modification times and guessed
durations are not substitutes for lifecycle evidence.

Record a wait only when an observation identifies what was waiting and why.
For example, the caller may record that merge was waiting for named assessments,
or an explicit native capacity limit prevented dispatch. A queue/collection
gap alone does not identify its cause. Include external permission or service
waits only when actually observed; do not infer them from slowness.
Waiting for dependencies can overlap useful work and is not automatically
avoidable delay. Do not call the longest agent the critical path without the
necessary dependency evidence.

## Private timing record

Keep one caller-owned JSON sidecar outside the reviewed tree and retain its
path in the consolidated handback as `timing_file`. Do not add fields to
PACKETS.md's exact-keyed category handoff, frozen packets or ledger events.
The sidecar has schema 1, independent of phase-plan schema 4.

```json
{
  "schema": 1,
  "review": "<review or run identity>",
  "started": {"at": "2026-11-28T12:00:00Z", "source": "<invocation observation>"},
  "finished": {"at": "2026-11-28T12:09:00Z", "source": "<reporting cutoff observation>"},
  "agents": [
    {
      "id": "security-initial",
      "role": "reviewer",
      "category": "security",
      "worker": null,
      "status": "complete",
      "queued": null,
      "started": null,
      "finished": null,
      "collected": null,
      "duration": {"seconds": 240, "source": "<native duration-only notice>"}
    }
  ],
  "stages": [
    {
      "id": "setup-1",
      "name": "setup",
      "status": "complete",
      "started": {"at": "2026-11-28T12:00:00Z", "source": "<setup start>"},
      "finished": {"at": "2026-11-28T12:01:00Z", "source": "<first dispatch>"}
    },
    {"id": "posting-1", "name": "posting", "status": "skipped"}
  ],
  "waits": [],
  "limitations": ["Example only; other agent and stage observations are omitted."]
}
```

Replace every placeholder with actual evidence. Every timestamp is an object
with `at` (ISO 8601 with explicit timezone) and `source`, or null.
`duration` is optional; never derive timeline positions from it. When both
endpoints exist, their difference supplies the displayed interval duration;
the separately reported duration remains in the JSON output.
`role: reviewer` identifies discovery workers for the maximum; other roles
retain their actual purpose. Status records the observed outcome, not acceptance.

Stages have unique `id` values and a `name` of `setup`, `adjudication`,
`final_merge`, or `posting`. Waits have unique `id`, `waiting` (assignment or
stage), `blocked_by` (identifier list), `reason`, `started` and `finished`.
Retain an unknown blocker as an empty list and explain what is actually known.
Use unique agent IDs for every physical attempt; do not merge retries.

## Final display and recovery

Resolve the helper relative to this installed skill. From the consuming
project, render the compact summary:

```sh
python3 -B "/absolute/plugin/scripts/review_timing.py" report "/private/timing.json"
```

Append `--run-details` only when the normalized request enables it. The expanded
output includes every recorded agent, relative starts/finishes, durations,
queue and collection gaps, an ASCII timeline and the observed waits.
Add `--format json` to retain all computed fields; JSON retains the same detail
whether or not the display flag is set. Preserve the original sidecar too.

The helper never writes files, starts agents, changes settings or publishes.
Malformed observations remain limitations while usable records are reported.
An unreadable or malformed document exits 2 with an unavailable total, not a
failed-review verdict. Recover from retained evidence without re-running
agents; if recovery is unavailable, deliver findings with unavailable timing.

The independent `review-timing` setting is enabled by default. Disabling it
stops collection and detailed reporting; still show
`Total elapsed: unavailable (timing reporting disabled)`.
Do not change adjudication topology, check permissions or category coverage.

Show timing in the final local response, including incomplete reviews when
available. Explicit cancellation still prioritizes stopping owned work; it
does not authorize completing the review to obtain timing. Keep raw observations,
native identities and the timeline private. `--post-comments` does not authorize
uploading timing evidence or adding it to PR comments.
