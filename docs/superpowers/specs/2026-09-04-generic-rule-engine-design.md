# Generic Rule Engine: Design

> **Note:** this doc predates the Node-to-Python rewrite in
> `2026-09-11-python-rule-engine-rewrite.md`. The architecture, rule
> shapes, and matching semantics below are all still accurate. The code
> samples are JavaScript; the shipped engine is now `hooks/scripts/rule_engine.py`,
> and scripted rules are `.py` modules, not `.js`. See the rewrite doc for
> the current implementation and the scripted-rule contract.

## Problem

Behavioral rules the user has taught Claude over many sessions currently live
as auto-memory files. Memory is recalled conditionally, based on perceived
relevance, and is routinely ignored under context pressure or when a rule
never gets surfaced. A rule that must always hold (never kill a process
without asking, never hand-edit a lockfile) needs a mechanism stronger than
"the model might recall this," and one that ships with `ioncache-ai-tools` so
it travels with the plugin to any machine or repo, rather than living in a
memory store scoped to one project's conversation history.

`ioncache-ai-tools` already proves the pattern works: `fix_emdash_tool_input.py`
and `block_raw_worktree_add.js` are hard, code-level enforcement of rules that
used to be (and kept being violated as) prose instructions. But that pattern
doesn't scale past a handful of rules: each one is a bespoke script, wired
individually into `hooks/hooks.json`. Roughly 40 more generic, portable rules
have been identified in the user's memory store as candidates for this
treatment.

## Goals

- One generic engine that can express any of three rule shapes: an always-on
  reminder, a pattern match against tool input, or a fully scripted check.
- Adding a rule is adding a file under `hooks/rules/`, never touching engine
  code.
- Stays fast as the rule count grows into the hundreds: match-then-act split,
  cheap matching runs synchronously, expensive scripted checks run
  concurrently.
- Validate the design with a small pilot (5 rules, all three shapes) before
  porting the remaining ~40 candidate rules from memory.

## Non-goals (for this pilot)

- Migrating every candidate rule from memory. Only the 5 pilot rules below.
- A semantic/LLM-based classifier to decide which rules "might" apply. Cheap
  per-rule matchers (regex/keyword) are fast enough at this scale; revisit
  only if a future rule count actually demonstrates a slowdown.
- Touching the existing standalone hooks (`classify_question.py`,
  `block_pending_question.py`, `docs_first_guard.py`,
  `block_raw_worktree_add.js`, `graphify_context.js`,
  `block_emdash_turn.py`) beyond the one hooks.json change noted below. They
  keep working exactly as they do today, alongside the new engine.
- Per-project rule overrides/disabling. Not requested; add later if needed.

## Architecture

One engine script, `hooks/scripts/rule-engine.js`, invoked once per
lifecycle event that has rules registered. `hooks/hooks.json` passes the
event name as an argument:

```json
{
  "type": "command",
  "command": "node \"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/rule-engine.js\" UserPromptSubmit"
}
```

and similarly for `PreToolUse`. The engine only needs `__dirname` to find its
own `../rules` directory; `${CLAUDE_PLUGIN_ROOT}` is resolved by Claude Code
before the process ever starts, so no extra environment lookups are needed.

### Rule shapes

All three live under `hooks/rules/`, one file per rule, named for the rule
(`never-kill-without-asking.json`, `fix-emdash.js`, etc.):

**1. Always-on prompt rule** (declarative JSON):

```json
{
  "event": "UserPromptSubmit",
  "matcher": { "type": "always" },
  "action": "inject",
  "message": "Do exactly what was asked, nothing more. If something else seems worth doing, mention it and stop; don't act on it unless asked."
}
```

**2. Pattern rule** (declarative JSON):

```json
{
  "event": "PreToolUse",
  "toolNames": ["Bash"],
  "matcher": { "type": "regex", "field": "tool_input.command", "pattern": "(^|[\\s;&|(`<>])(?:[\\w./-]*/)?(kill|pkill|killall)($|[\\s;&|)`<>])" },
  "action": "deny",
  "message": "Never run kill/pkill/killall without asking the user first, even for your own leftover process. Ask, then wait."
}
```

`toolNames` is an optional restriction (checked before `matcher`); `field` is
a dot-path into the hook's JSON stdin payload.

When `field` is `tool_input.command` on a `Bash` tool call, the engine
normalizes the command before testing the pattern: it strips a backslash
immediately before a word character and strips quote characters, mirroring
what Bash itself does before command lookup. This closes the otherwise
trivial `\kill`, `k\ill`, and `'kill'` bypasses of a rule like
`never-kill-without-asking`. It's still text normalization, not a shell
parser, so it doesn't cover every form of shell quoting or expansion.

**3. Scripted rule** (JS module, the escape hatch for anything a regex can't
express):

```js
module.exports = {
  event: 'PreToolUse',
  toolNames: ['Bash', 'Edit', 'Write', 'MultiEdit'],
  matches(input) {
    const emDash = String.fromCharCode(0x2014)
    return JSON.stringify(input.tool_input || {}).includes(emDash)
  },
  async check(input) {
    // returns a rewrite, a deny, or null (no-op)
  }
}
```

### Data flow, per invocation

1. Read stdin once, `JSON.parse` it.
2. Read every file in `hooks/rules/` whose `event` matches the CLI arg
   (declarative rules read their JSON directly; scripted rules are
   `require()`'d for their exported shape).
3. For each candidate rule, apply `toolNames` (if present) then run its
   matcher synchronously: `matcher.type === 'always'` short-circuits true;
   `'regex'` reads the field and tests the pattern; a scripted rule's own
   `matches(input)` runs inline. This synchronous pass is the "classifier":
   distributed per-rule rather than a separate model, and cheap even at
   hundreds of rules since it's just string/regex tests.
4. For the (typically small) subset that matched, resolve their action
   concurrently: declarative rules resolve instantly; scripted rules'
   `check(input)` runs as a promise. All run via `Promise.all`, so the total
   cost is bounded by the slowest single check, not the sum.
5. Merge results by event type:
   - `PreToolUse`: all matched rules' `check()` calls resolve concurrently
     (via `Promise.all`, since none of the pilot rules depend on another's
     result). Once every result is in: if any is a `deny`, use the first one
     in rule-file declaration order and ignore the rest (no true early
     cancellation; at pilot scale the checks are cheap enough that running
     them all to completion costs nothing). Otherwise, if exactly one rule
     returned a `rewrite`, emit its `updatedInput` as-is, matching
     `fix_emdash_tool_input.py`'s existing contract (a full copy of
     `tool_input` with the target field(s) modified, since Claude Code
     replaces `tool_input` wholesale, not a patch). Otherwise emit nothing.
   - **Known limitation, not solved by this pilot:** if two rules both
     return a `rewrite` for the same event, applying both is not yet
     defined, since each computed its full replacement independently
     against the same original input, so combining them naively would drop
     whichever ran second. The pilot has exactly one rewrite rule
     (`fix-emdash`), so this never triggers. Before a second rewrite rule is
     added, revisit this: the likely fix is running rewrite rules
     sequentially, each against the previous one's already-updated input,
     rather than concurrently against the pristine original.
   - `UserPromptSubmit`: concatenate every matched `inject` rule's `message`
     (blank-line separated) into one `additionalContext` string. Emit
     `{"additionalContext": "..."}` (the same bare shape
     `classify_question.py` and `graphify_context.js` already use
     successfully), no result means no stdout.
6. Exit 0 always. A rule that throws during matching or checking is caught
   at the per-rule level, logged to stderr, and treated as "didn't match."
   The engine must never crash or block the prompt/tool-call over a bug in
   one rule.

## Pilot rule set

| Rule | Shape | Event | Action | Source memory |
| --- | --- | --- | --- | --- |
| `never-kill-without-asking` | Pattern | `PreToolUse` | deny | `feedback_never_kill_process_without_asking` |
| `no-manual-lockfile-edit` | Pattern | `PreToolUse` | deny | `feedback_never_hand_edit_lockfile` |
| `fix-emdash` | Scripted | `PreToolUse` | rewrite | `feedback_no_emdashes` |
| `scope-exactly-what-asked` | Always-on | `UserPromptSubmit` | inject | `feedback_scope_exactly_what_asked` |
| `verify-state-before-claiming` | Always-on | `UserPromptSubmit` | inject | `feedback_verify_state_before_claiming` |

`fix-emdash` replaces `fix_emdash_tool_input.py` entirely: same rewrite
behavior via the engine's rule, and the now-redundant script file is deleted
rather than left orphaned. The existing `block_emdash_turn.py` `Stop` hook is
untouched; it's a different event, out of scope for this pilot.

## `hooks/hooks.json` changes

- Add one `PreToolUse` entry: `node "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/rule-engine.js" PreToolUse`.
- Add one `UserPromptSubmit` entry: `node "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/rule-engine.js" UserPromptSubmit`.
- Remove the existing `fix_emdash_tool_input.py` `PreToolUse` entry (superseded
  by the `fix-emdash` rule).
- Every other existing hook entry is untouched.

## Error handling

- Per-rule try/catch around both `matches()` and `check()`/action
  resolution. A thrown error is logged to stderr and the rule is treated as
  not matched.
- The engine's own top-level `main()` also has a catch-all: on any
  unexpected failure (bad stdin JSON, missing rules directory), print
  nothing and exit 0. A hook that errors out non-zero on `UserPromptSubmit`
  blocks and erases what the user typed; this must never happen.

## Testing

`ioncache-ai-tools` has no test framework and the pilot doesn't justify
adding one. Per the user's standing preference for minimal-but-present
verification, one self-check script,
`hooks/scripts/rule-engine.self-check.js`, uses Node's built-in `assert` to
feed synthetic stdin-shaped payloads through the engine's internals and
verify: each of the 5 pilot rules fires correctly in isolation, `PreToolUse`
deny short-circuits over a rewrite, `UserPromptSubmit` concatenates multiple
`inject` messages into one block, and a rule that throws doesn't take down
the run. Runnable directly: `node hooks/scripts/rule-engine.self-check.js`.

## Success criteria

- All 5 pilot rules behave correctly when exercised through the self-check
  script and through a live Claude Code session with the plugin installed
  locally.
- `fix-emdash` behaves identically to the `fix_emdash_tool_input.py` hook it
  replaces.
- No measurable added latency on a normal prompt/tool-call (5 rules is not a
  real stress test, but the merge/concurrency logic should already be
  exercised correctly at this scale before trusting it at "hundreds").
- If this holds up, the remaining ~40 candidate rules from memory get ported
  as additional rule files, no engine changes needed.
