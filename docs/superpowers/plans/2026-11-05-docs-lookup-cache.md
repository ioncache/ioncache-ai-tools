# Docs lookup cache plan

Scope: implement and validate the shared cache in Claude Code, Codex, and
Copilot CLI. All three fetch integrations are required for completion.

## Goal

Stop repeating the same documentation lookup when a recent result already exists, while keeping the rule that specifics come from current documentation rather than training data.

Requirement: the cache stores a distilled answer (the specific facts the lookup established, plus source and date), never the page or the full fetch result.

Scope: one machine-wide cache for Claude Code, Codex, and Copilot CLI, across
sessions and projects. Bypass state and problem-notification deduplication
are separate per harness and session.

## Measured baseline

Historical measurements recorded on 2026-11-05. The Claude Code extraction
covered WebFetch, WebSearch, and context7 calls in
`~/.claude/projects/**/*.jsonl`; Copilot measurements are separate below.

- Window: 2026-07-20 to 2026-11-05, 49 sessions, 5 projects (94% `coral-platform`).
- Lookups: 1,693 total.
  - WebFetch: 1,383. Result median 864 characters (about 216 tokens), mean about 535 tokens, about 740000 tokens in total. Latency median 5.0 seconds, p90 10.1 seconds.
  - WebSearch: 305. Result median 2,859 characters (about 715 tokens), about 223000 tokens in total. Latency median 5.6 seconds.
  - context7: 5 calls, which is negligible.
- Subagents made 38% of the lookups.
- Git documentation: 3 fetches and 0 searches. The over-checking of git you saw in Copilot doesn't show up in Claude Code.

### Repeats

A repeat means a fetch of a URL that had already been fetched before. URLs are normalized by lowercasing the host, dropping `www.`, and ignoring a trailing `/` or `.md`.

| Repeat kind | Count | Tokens |
| --- | --- | --- |
| Same session, within 15 minutes | 204 | 70000 tokens |
| Same session, within 1 day | 101 | 65000 tokens |
| Same session, 1 to 7 days later | 24 | 10000 tokens |
| Same session, 7 or more days later | 24 | 4000 tokens |
| Different session, within 15 minutes | 12 | 2000 tokens |
| Different session, within 1 day | 23 | 23000 tokens |
| Different session, 1 to 7 days later | 44 | 52000 tokens |
| Different session, 7 or more days later | 37 | 9000 tokens |
| All WebFetch URL repeats | 469 (34%) | 234000 tokens |

- 170 of the same-session repeats came from subagents. A subagent can't see what its parent or a sibling already fetched, so it fetches again.
- Same URL with the exact same WebFetch prompt: only 67 repeats (5%). WebFetch returns an answer to its prompt, not the page, so most repeats ask a different question about the same page.
- WebSearch repeats: 11 of 305 (3.6%), even after ignoring word order. Searches are almost never repeated, so caching them isn't worth it.
- The most-repeated pages are hosted-service docs: DigitalOcean (250 fetches), FusionAuth (214), Stripe (95), GitHub, Playwright, and Notion. FusionAuth release notes alone were fetched 26 times.

### Copilot CLI

Source: `~/.copilot/session-state/*/events.jsonl`, 2026-05-01 to 2026-11-05. Almost all lookups fall between 2026-09-29 and 2026-11-05.

- Lookups: 1,244 in 14 sessions.
  - `web_fetch`: 1,152.
  - context7: 69.
  - Copilot docs tool: 23.
- Recorded `web_fetch` results were page text, not model-written answers. Their median was about 1339 tokens, mean about 1766 tokens, and total about 2000000 tokens.
- URL repeats: 722 of 1,127 successful fetches (64%), about 1290000 tokens.
  - 573 of the repeats happened within the same session.
  - 149 happened in a different session.
- git-scm.com: 210 fetches across 10 sessions, about 289000 tokens. 168 of them were repeats.
  - Most fetched: `git-commit` (33), `git-worktree` (30), `git-status` (20), `git-add` (17), `git-diff` (12), `git-branch` (11), `git-push` (10).
- The `docs_first_guard.py` reminder appeared 719 times in the Copilot logs.
  - All 210 git-scm fetches happened in sessions where the reminder fired. There were none in sessions without it.
  - Only 2 sessions with lookups had no reminder, so this is strong but not conclusive.
  - The reminder then said "even for something already used in this project, and even when confident". Copilot appeared to follow that literally for routine git commands.

## Estimated savings

### Claude Code

- **Network fetches avoided:** 67 to 265 over 3.5 months, which is 5% to 19% of WebFetch calls, or about 0.6 to 2.5 per day.
  - The low end assumes only exact URL and prompt matches can be served from the cache.
  - The high end assumes every URL repeat can be served, except the 204 same-session repeats within 15 minutes. The original estimate assumed those were already served by WebFetch's own cache.
  - The ceiling of 469 only applies if WebFetch's own cache didn't exist.
- **Searches avoided:** about 0, because WebSearch isn't cached.
- **Time saved:** about 6 to 22 minutes in total over 3.5 months, at 5 seconds per avoided fetch.
- **Context saved:** about 9000 to 150000 tokens over 3.5 months, roughly 200 to 3000 tokens per session.
  - This assumes a distilled entry of 60 to 100 tokens. Only the 1,260 fetches that have timestamps and didn't error were counted.
  - Low end: 63 exact URL and prompt hits. Those answers were already small (about 223 tokens each), so distilling them saves little.
  - High end: 260 URL hits. Those answers averaged about 634 tokens, so each hit saves about 530 to 575 tokens.
  - A hit that doesn't answer the new question costs the distilled entry plus a real fetch, which pulls the real number toward the low end.
- **Where distillation runs decides whether there's any net saving:**
  - If the main model distills each fetch in its own context, it writes 60 to 100 tokens for every fetch, not just the repeats. That's 76000 to 126000 tokens, so the cache saves less than it costs, or about breaks even.
  - The distillation has to happen outside the main context, in a background hook that calls a small model, so the main context pays nothing to store an entry.

### Copilot CLI

- **Fetches avoided:** up to 722 of 1,127 (64%) in about 5 weeks. git-scm.com accounts for 168 of them.
- **Context saved:** about 1210000 to 1240000 tokens in about 5 weeks, with distilled entries of 60 to 100 tokens. git-scm.com alone accounts for about 237000 tokens.
- **Distillation cost:** distilling inside the main context would cost 68000 to 113000 tokens, so it pays off even there. Doing it in a background hook is still better.
- These are upper bounds. A hit that doesn't answer the new question still costs a real fetch.
- The enforced limit is 150 words per summary, so actual entries can exceed
  the 60 to 100 tokens assumed here. Background jobs also incur separate model
  usage; their production cost needs measurement.

### Sharing across harnesses

- Only 58 URLs were fetched by both harnesses, out of 813 in Claude Code and 426 in Copilot. Most are code.claude.com, DigitalOcean, and `gh` manual pages.
- Separate caches would already catch repeats within each harness. Sharing adds hits only on the first fetch of a URL in the second harness, so at most about 58 extra fetches avoided, and fewer once the 7-day age limit applies.
- One shared cache is still the choice. It costs nothing beyond picking the path, and one cache is simpler to inspect and clear than two.

## Design

### 1. Store distilled results outside the main context

`hooks/scripts/docs_cache.py` owns the shared cache and worker. Each native
post-tool hook starts the same detached Python worker and returns without
waiting for model inference. Fetched text travels over stdin; the cache never
writes that text to a file.

- Claude's `WebFetch` hook reads `tool_input.url`, `tool_input.prompt`, and
  a successful `tool_response.result`. The result is already a question-specific
  extraction, not the raw page. Response byte counts are not chunk coverage.
- Copilot's `postToolUse` adapter reads `toolArgs` and a successful
  `toolResult.textResultForLlm`.
- Codex's `webrun` hook accepts a single literal HTTP(S) URL in `open`.
  It extracts line-prefixed page text from `tool_response`'s `input_text`
  item after verifying the source URL and page header. Citation IDs and source
  metadata are not passed to the distiller as page text. These excerpts can be
  truncated, so line counts are never represented as character coverage.

Codex searches, mixed or batched calls, reference IDs, and nonzero line
continuations stay live. Hosted search does not emit the local tool hooks;
this integration uses the native local `web.run` path.

The worker uses the originating harness's CLI and login. All three harnesses
submit jobs through their native post-tool hooks.
Copilot uses `gpt-6-luna` with low reasoning effort; the other builders specify
Haiku for Claude and `gpt-6-luna` for Codex. Model choices are fixed in code.
The distiller prompt aims for 100 words, with a hard storage limit of 150
whitespace-separated words, or `NONE` when no useful reference facts exist.
Overlong output is rejected and reported as a distiller failure. It is not
truncated, because that could drop a qualification or split a command.
Existing overlong entries are excluded from cache hits.

Copilot receives the page in its prompt argument. The full prompt, including
URL, optional question, and instructions, is capped at 100000 UTF-8 bytes.
Truncation preserves complete characters and reduces recorded chunk coverage.
This leaves headroom below Linux's per-string argument limit without writing
raw pages to temporary files. Excessive URL/question metadata is a reported
worker failure rather than an oversized process argument.

Workers set `IONCACHE_DOCS_DISTILLER=1`; this plugin's Copilot and Codex adapters
return immediately in those runs. The Copilot command disables tools, custom
instructions, and built-in MCP servers. Older installed plugin copies without
the guard still need updating. Cache retention does not control the harness's
own session history.
Claude uses safe mode with an empty tool list. Codex ignores user configuration
and disables web, shell, and native subagents in a read-only sandbox. It can
still expose utility tools; do not describe its distiller as tool-free.

Copilot and Codex jobs have no question, so summaries describe the fetched excerpt generally.
A summary can miss a later question even when the original chunk covered it.
The bypass is the escape hatch; its rate measures these misses.

Location: `${XDG_CACHE_HOME:-~/.cache}/ioncache-ai-tools/docs-cache/`. The root
directory is 0700; files are 0600. Each `entries/<sha256>.json` holds a normalized,
redacted URL and up to three facts with `fact`, `fetched_at`, `harness`, and `length`.
Claude and Codex facts also carry `reference_only: true`. Claude facts retain
the extraction `question`, so readers can see what the answer actually covers.
New entry and log URLs omit userinfo, query strings, and fragments. Existing
files are not scrubbed; clearing the cache removes old metadata.
Writes use temporary files and atomic replacement.

The key hashes normalized URL plus `start_index`, not `max_length`. Normalization
lowercases the host and drops `www.`, fragments, trailing slashes, and
`.md`/`.htm`/`.html` suffixes. Redaction applies only to persisted URL metadata,
not key inputs. Query strings and versioned paths remain distinct.
Coverage is recorded separately as the requested length, reduced if the worker
truncates the input. Unknown lengths never mean "whole page".
Reference-only summaries are candidates for URL-level lookups across all three
harnesses, not claims to cover a particular chunk. The assistant checks whether
the facts answer its question and repeats the identical call if they do not.

Both reading and writing skip raw requests and volatile URLs: release notes,
changelogs, `/latest`, what's-new pages, GitHub releases, and
`raw.githubusercontent.com` files not pinned to a full commit SHA. Failed and
empty results are not distilled. Copilot requests without an explicit positive
`max_length` do not participate.

### 2. Serve hits: PreToolUse on WebFetch

A Copilot chunk must match the URL/chunk key and cover at least the requested
length. URL-level lookups can also use reference-only summaries. Claude and
Codex read the shared facts for the URL's initial chunk, including Copilot facts.
A hit denies the fetch with facts, source, fetch dates, any extraction question,
and instructions to repeat the identical call for live results. It explicitly
identifies the results as facts, not a complete page. At most three facts appear.

Copilot and Codex run shared permission hooks first; only an otherwise
unchanged call reaches the cache. Claude runs its cache hook alongside the
existing guards. Cache misses and failures never emit an allow decision.

Bypass state hashes the complete fetch arguments, independent of the reusable
entry key. Changing `max_length` does not consume another request's bypass.
Repeating a denied call permits one live fetch, then the next call may hit again.
This state is isolated by harness and session.

Cache exceptions and uncertain coverage leave normal fetch permissions unchanged.
The cache must not turn an operational failure into a documentation gate.

### 3. Reminder text

`docs_first_guard.py` still requires current documentation rather than training
data. It permits reusing facts already verified in the conversation or served
fresh by the cache when they cover the exact detail and version needed.
Another turn or tool call alone is not a reason to repeat a lookup. Missing or
uncertain details, version changes, and time-sensitive questions require live
verification. Confidence and existing project usage are not substitutes.

### 4. Metrics

- Append one line per hit, miss, bypass, store, failed distillation, or empty
  distillation to `events.jsonl`. Rotate it at 1 MB, retaining one older log.
- After 2 to 4 weeks, compare the actual hit rate and bypass rate with this estimate, and remove the cache if hits stay near the low end.

### 5. Surface distiller problems

Missing executables, timeouts, non-zero exits, and unexpected worker failures
write `distill-status.json`. Warning lines from an otherwise successful CLI run
also persist there. A clean run clears the status.

On a subsequent tool result, Copilot's adapter adds the notice to model context
without discarding shared post-tool context. The stop hook checks the current
root response after other shared stop guards pass. If the notice is missing,
it requests a corrected final answer containing the diagnostic verbatim, up to
twice per session and problem digest. Retry counts persist across hook processes
and turns. Exhausted notices stay pending for post-tool delivery without further
stop blocks. Delivery uses the assistant response, including under `--silent`,
rather than relying on terminal hook stderr.

The `.notified` marker is written only after that response contains the notice,
allowing whitespace differences. Merely returning post-tool context does not
acknowledge delivery. Each session reports a distinct problem once. Notices
normalize em-dashes so the punctuation guard cannot conflict with verbatim
reporting. The diagnostic is data, not an instruction to retry or run tools.
Fetch permissions and the cache's fail-open behavior are unchanged.

## Eviction

- **Age limit:** 7 days by default. Of the 116 cross-session repeats, 79 happened within 7 days, so a longer limit adds little and makes entries staler.
  - The age limit applies within sessions too.
- **Versioned URLs:** when the URL contains a version (for example `/v2/`, `/docs/v22`, or a tag or SHA), the version is part of the key, so a version change means a new URL and a new entry. Detecting installed versions isn't needed, because most repeated pages are hosted services with no local version.
- **Pages that change often:** never stored (see section 1).
- **Bypass:** the fresh result is stored at the top of that URL's list, so the newest answer is shown first next time.
- **Per-URL cap:** keep the 3 most recent answers.
- **Total size cap:** about 20 MB of entries. When writing would go over it,
  delete the entries with the oldest modification time.
- **Session state:** remove session files older than seven days during eviction.
- **Concurrent writes:** skip files that disappear during eviction and reuse
  captured metadata rather than repeatedly reading it.
- **Errors:** an entry that fails to parse or contains malformed fact fields is
  deleted and treated as a miss, allowing a later store to replace it.
- **Manual reset:** deleting the cache directory is safe at any time.

## Out of scope

- **WebSearch:** only 3.6% of searches repeat.
- **context7:** almost never used.
- **Injecting cache entries at UserPromptSubmit:** that needs a prompt classifier, which was already tried and dropped.

## Validation and rollout

`hooks/scripts/docs_cache_self_check.py` covers normalization, expiry, coverage,
raw and volatile exclusions, exact-call bypass, corrupt entries, eviction,
private files, the enforced summary cap, warnings, failures, and multibyte
argument limits. Adapter self-checks cover cache hits, fail-open handling,
final-response notice enforcement, acknowledgment after other stop guards,
and distiller guards. The validation workflow includes the cache self-check.

Run `.github/workflows/validate.yml` steps on Ubuntu 24.04 as a non-root user.
Live checks must exercise miss/store, a cross-session hit, and an identical-call
bypass in each of Claude Code, Codex, and Copilot using scratch `XDG_CACHE_HOME`
directories. Each harness must also consume facts produced by another harness.
Do not install, publish, or bump a version without authorization.

Live acceptance checks must keep the original strict assertions: every stored
summary has at most 150 words, and a pending diagnostic appears in captured
stdout with `--silent`. Exercise miss/store, a cross-session hit, and an
identical-call bypass. Also check a response with no preceding tool call so
the stop hook, not just post-tool context, must surface the diagnostic.

Acceptance includes real native hook payloads, not just direct Python calls.
Claude must register pre-tool, post-tool, and stop handlers in `hooks/hooks.json`.
Codex must register all three events in `hooks/codex-hooks.json`. Its installed
hooks need the normal Codex trust review; isolated verification can supply the
same vetted definitions inline without changing the user's configuration.

Possible follow-up work outside the required three-harness integration:

- Decide whether model choices need configuration.
- Measure real background-job cost, saved context, and bypass frequency.
- Check how host session retention affects repeated background runs.

## References

- [Claude hook payloads and decisions](https://code.claude.com/docs/en/hooks)
- [Claude WebFetch behavior](https://code.claude.com/docs/en/tools-reference#webfetch-tool-behavior)
- [Codex hook payloads, trust, and tool coverage](https://learn.chatgpt.com/docs/hooks)
- [Copilot hook payloads and decisions](https://docs.github.com/en/copilot/reference/hooks-reference)
- [Copilot CLI command reference](https://docs.github.com/en/copilot/reference/cli-command-reference)
- [Python subprocess handling](https://docs.python.org/3/library/subprocess.html)
- [Linux process argument limits](https://man7.org/linux/man-pages/man2/execve.2.html)
