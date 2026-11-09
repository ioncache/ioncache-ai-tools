# Documentation cache

Installation and basic usage: [../README.md](../README.md).
Disable with `docs-cache` in [configuration.md](configuration.md).

## Reuse and live fetches

Claude Code, Codex, and Copilot CLI share short facts distilled from successful
documentation fetches. Supported tools are Claude `WebFetch`, Codex single-URL
`web.run` opens, and Copilot `web_fetch`.

A cache hit supplies facts, source URL, and fetch date instead of downloading
the page again. Repeating the identical call bypasses the hit once and fetches
live. Verified conversation facts or fresh cached facts can be reused only
when they cover the required detail and version. Summaries are not full pages.

Copilot requests need an explicit positive `max_length`. Cached chunks must
start at the same offset and cover at least the requested length. Claude
answers and Codex excerpts are reference-only summaries; URL-level requests
can reuse their stated facts, not infer page coverage.

Codex caches a single literal HTTP(S) URL opened from the beginning. Searches,
batched operations, session-local references, line continuations, and hosted
search stay live. Claude redirects and Codex results without a matching source
stay uncached. Raw HTML, failed or empty results, and volatile pages such as
release notes, changelogs, and `/latest` always fetch live.

## Storage and model usage

The cache lives at
`${XDG_CACHE_HOME:-~/.cache}/ioncache-ai-tools/docs-cache/`, shared across
projects, sessions, and hosts. Bypass and notification state remain separate
per host and session.

Claude cache entries retain the original `WebFetch` question alongside the
distilled fact. A later hit for the same URL can show that question in another
project or host. Disable `docs-cache` before submitting sensitive questions.

Facts expire after seven days, with up to three facts per URL/chunk and a
20 MB entry budget. Each summary is limited to 150 whitespace-separated
words. Overlong output is rejected rather than truncated into partial facts.
New URL metadata omits userinfo, query strings, and fragments; cache keys hash
the full normalized URL. Existing files are not scrubbed.

Distillation runs outside the conversation through the originating host's CLI
and login. It uses Haiku for Claude and `gpt-6-luna` with low reasoning effort
for Codex and Copilot. These fixed model choices consume additional host usage.
Claude and Copilot distillers disable tools. Codex runs read-only with shell,
web, and native subagent tools disabled, but may expose utility tools.
The plugin suppresses its own adapters in these runs.

## Troubleshooting

Cache failures leave normal fetch permissions unchanged. Post-tool and Stop
hooks report each distinct problem once per host/session until notification
state expires. Diagnostics use host display output, not extra model context or
mandatory answer text.

Silent or noninteractive interfaces can suppress warnings. Inspect
`events.jsonl` in the cache directory for misses, hits, bypasses, stores, and
distiller outcomes. `distill-status.json` holds the latest problem.

Removing the cache's contents resets it, including previously stored URL
metadata. Cache limits and cleanup do not govern the CLI's own session history.
When testing a live plugin checkout, refresh installed copies too so background
distillers use the intended adapter version.
