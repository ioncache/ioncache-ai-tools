# Rule Engine Rewrite: Node to Python

## Why

The rule engine (`hooks/scripts/rule-engine.js`, designed in
`2026-09-04-generic-rule-engine-design.md`) needed to read Codex's
`config.toml` for the per-rule disable-config feature
(`2026-09-11-rule-config-design.md`). Node has no TOML parser in its
standard library; Python's does (`tomllib`, 3.11+). The engine's first
version handled that gap by having the running Node process shell out to a
`python3` subprocess (`read_codex_disabled_rules.py`) just for that one
read.

That cross-language subprocess call turned out to be the actual problem,
not a detail to patch around. A code review surfaced two failures rooted
in it directly: `spawnSync` had no timeout, so a hang there could block
Node's single-threaded event loop long enough that the engine's own
hang-watchdog (a `setTimeout`) could never fire, since timers can't run
during synchronous JS execution; and the subprocess's `result.error` field
(set when `python3` itself can't be spawned) was never checked, so a
missing Python silently produced an empty result instead of a logged one.
Both are symptoms of one Node process reaching out to spawn another
language's interpreter as a child process mid-execution, not bugs specific
to this one helper.

The fix: the whole engine is Python now, not just the one TOML read.
Python's standard library covers everything this engine needs natively
(`json`, `tomllib`, `re`), so there's no cross-language boundary left to
have a timeout or error-surface gap in.

## What changed

- `hooks/scripts/rule-engine.js` → `hooks/scripts/rule_engine.py`. Same
  matching/loading/merging logic, ported directly; see
  `2026-09-04-generic-rule-engine-design.md` and
  `2026-09-11-rule-config-design.md` for the design this preserves. Two
  differences from a pure port:
  - No async/Promise machinery. There's no concurrent I/O to justify it in
    a small CLI script that reads stdin once and writes stdout once, and
    Python doesn't need it for the same reason JS's version did (avoiding
    blocking the process while awaiting I/O that here never actually
    happens concurrently).
  - The hang-watchdog is `signal.alarm()` plus a `SIGALRM` handler instead
    of a timer racing a promise. This is strictly stronger: a real signal
    interrupts even a blocking synchronous call (a tight loop, a blocking
    C call), which is exactly the class of hang the old `spawnSync` finding
    exposed as unreachable by a same-thread JS timer.
- `hooks/scripts/read_codex_disabled_rules.py` is deleted. Its logic
  (`tomllib.load`, walk `projects."<path>".ioncache-ai-tools.disabled_rules`)
  is now a few lines directly inside `get_disabled_rule_ids`, no subprocess
  involved.
- Scripted rules are Python modules now: `fix-emdash.js` →
  `hooks/rules/fix_emdash.py`, `no-manual-lockfile-edit-bash.js` →
  `hooks/rules/no_manual_lockfile_edit_bash.py`. The scripted-rule contract
  is module-level `EVENT`, optional `TOOL_NAMES`, a `matches(hook_input)`
  function, and either a `check(hook_input)` function or module-level
  `ACTION`/`MESSAGE` (declarative-with-custom-matcher, replacing JS's
  `module.exports` shape).
- `hooks/scripts/block_raw_worktree_add.js`, previously a standalone
  `hooks.json` entry with its own stdin parsing and deny-JSON shape (not a
  rule-engine rule at all), is now `hooks/rules/block_raw_worktree_add.py`,
  a scripted rule like the other two. This also fixes an inconsistency a
  later review caught: it wasn't reachable through the documented
  `disabledRules`/`disabled_rules` config, unlike every other check in this
  repo. It is now.
- Declarative `.json` rules (`never-kill-without-asking.json`,
  `no-manual-lockfile-edit.json`, `scope-exactly-what-asked.json`,
  `verify-state-before-claiming.json`) are unchanged. JSON isn't tied to
  either language.
- `scripts/create-worktree.js` is unchanged. It does pure git/filesystem
  work with no config-format need, no reason to touch it.
- `hooks/scripts/rule-engine.self-check.js` →
  `hooks/scripts/rule_engine_self_check.py`, same coverage, ported test by
  test, plus a `contextlib.redirect_stderr` capture in place of monkey-
  patching `console.error`.
- `hooks/hooks.json`, `.github/workflows/validate.yml`, and `README.md`
  updated for the new filenames and `python3` invocation.

## Known limitation carried forward unchanged

`normalize_shell_command`'s quote-stripping still has the gap a later
review found: stripping quote delimiters to catch `'kill'`/`"kill"`
bypasses also exposes any boundary-class character (e.g. `|`) that was
safely inside the quotes, so `grep "kill|pkill|killall" file` can still
false-match a boundary-anchored pattern. This rewrite preserves that
behavior exactly rather than fixing it, since it's orthogonal to the
language migration; see the README's "Known limitations and security
considerations" section. Closing it properly means real shell
tokenization, for which Python's stdlib `shlex` (with
`punctuation_chars=True` for operator-aware splitting) is a strong
candidate, unlike the current flat-text `normalize_shell_command` pass.
That's a follow-up, not part of this change.
