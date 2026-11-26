# Response validation

When enabled, Claude's response-validation mod holds supported model responses
before forwarding their streams. A separate small-model completion checks
factual support and returns edits. The mod applies those edits before the
response reaches the display and conversation record. It does not ask the
authoring agent to regenerate an answer.

Use Claude Code 2.1.332 or later. The native mod checks run against 2.1.332.
Copilot and Codex do not load this Claude-specific module.

## What it checks

The reviewer checks claims about behavior, state, executed actions and results.
It narrows overclaims, corrects contradictions, and qualifies specific uncertainty
when the supplied evidence cannot establish a claim. It preserves questions,
acknowledgements, intentions, examples, and unaffected text. It is not a general
code review or style pass.

The reviewer receives the draft and the sending agent's recent conversation,
including recorded tool calls and results. Earlier assistant assertions are not
independent evidence. Root and child histories are kept separate; unavailable
child history never falls back to the parent's conversation.

This is model-based checking, not a proof of factual correctness. A reviewer can
miss errors or make an incorrect edit. It cannot verify unobserved production
state or recover evidence omitted from the conversation.

## Delivery and failure behavior

The `turn.step` hook covers intermediate commentary and final response text in
the main loop and subagent loops that expose this event. It also reviews string
`message` fields in `SubagentHandback` calls and string `message`, `content` and
`summary` fields in `SendMessage` calls before forwarding their argument chunks.
Recipients, control fields and other tool inputs are left unchanged.
Malformed message arguments remain subject to native tool validation; they do
not discard other calls or prevent valid drafts from being reviewed.

Responses without text or supported message payloads do not need a model call.
Ordinary text, including acknowledgements, goes through the reviewer.
Thinking blocks and unrelated tool arguments are not rewritten.

Malformed or unreadable host settings pause validation. The configuration helper
warns on stderr without changing the settings, and drafts pass through unchanged,
including when validation was already off. The next response checks the settings
again, so repair restores the configured behavior.

On a reviewer timeout, error, invalid edit, unavailable history, or failure to
run the configuration query, the mod replaces the affected drafts with:

> Response validation is unavailable. The unvalidated draft was not delivered.
> This does not block further work.

There is no retry loop, approval file or persistent permission state. Other tool
calls continue normally after a failed review. A broken source stream takes a
separate fallback that delivers only the notice; it cannot safely reconstruct
unfinished tool calls. Cancellation discards the held text.

The mod cannot promise interception when disabled, not loaded, or bypassed by a
host route that does not emit `turn.step`. Other mods can change text after this
mod in the middleware chain. External messaging through arbitrary tools, files,
other processes or another plugin's APIs is outside this hook's coverage.

## Usage and limits

The feature is off by default because it adds model usage and latency. Enable
it for the current project through the shared settings command:

```text
/ioncache-ai-tools:plugin-settings --hook:response-validation=enabled
```

The command updates all three hosts' settings together. Add `--global` to change
global settings while preserving project overrides. Alternatively, set the
following in all three hosts' global or project feature settings:

```json
{
  "features": {
    "response-validation": true
  }
}
```

Settings combine disables across hosts, including inherited defaults, so setting
`true` only for Claude is not enough. Use the three settings paths listed in
[configuration.md](configuration.md), even though only Claude runs validation.
Existing saved values are preserved when defaults change; set
`response-validation: false` in any host's effective settings to turn it off.

The next response reads the setting again. When disabled, the mod passes the
original stream through without a history read or reviewer request. The local
configuration lookup still runs.
See [configuration.md](configuration.md) for paths and precedence.

The reviewer uses Claude's native `haiku` alias through the session's own API
client and credentials. It has no tools, ambient project instructions, or
authoring-agent retry loop. Its own `model.complete` call does not enter
`turn.step`, so it does not recursively review itself.

When enabled, each textual response adds one review request, with a 30-second
timeout and an output ceiling of 16384 tokens. Unchanged responses return an
empty edit list rather than repeating the draft. Actual model usage is included
in Claude's session cost accounting; the ceiling is not an estimate of normal usage.

The evidence packet uses at most 64 recent conversation rows and 48000 characters
of serialized context, with explicit truncation indicators. A combined draft over
64000 characters receives the unavailability notice rather than partial review.
These bounds limit per-response cost but do not establish a percentage overhead.
No representative real-reply cost benchmark has been completed.

## Verification and references

The native offline suite exercises buffering before release, corrected stream
and result text, agent identity isolation, handback arguments, configuration
failures, opt-out, reviewer failure recovery, and native hook fallback. Separate
Node checks cover chunk handles, edit validation and cancellation. These checks
do not establish live interactive, remote-client or every native agent-delivery
route's behavior.

The implementation uses the documented stream-rewrite contract, not `Stop` or
the display-only `MessageDisplay` hook:

- https://code.claude.com/docs/en/plugins/mods/events#follow-a-turn
- https://code.claude.com/docs/en/plugins/mods/api#call-a-model
- https://code.claude.com/docs/en/plugins/mods/reference#limits
- https://code.claude.com/docs/en/plugins/mods/test
- https://github.com/anthropics/claude-code/blob/main/mods/types/claude-code.d.ts
