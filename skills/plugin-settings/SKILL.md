---
name: plugin-settings
description: Manages plugin settings through the namespaced plugin-settings command, with a native Claude pane or grouped text and typed flags. Use when the user invokes plugin-settings to inspect settings or explicitly enable or disable plugin features.
---

# Plugin settings

Use a command interface, not a conversational configuration interview.

There is one command: `/ioncache-ai-tools:plugin-settings`. Claude Code with
mods enabled handles this existing namespaced command natively: no arguments
opens a pane when available, otherwise it prints the grouped listing.
`--list` and setting flags use the text interface without an assistant turn.
No second slash command or unnamespaced alias is registered.

When the host loads this skill instead, run the text interface below. Do not
imitate the native pane with conversational questions.

## Invocation

Claude and Copilot:

```text
/ioncache-ai-tools:plugin-settings
/ioncache-ai-tools:plugin-settings --list
/ioncache-ai-tools:plugin-settings --hook:answer-questions=disabled
/ioncache-ai-tools:plugin-settings --hook:answer-questions=enabled
/ioncache-ai-tools:plugin-settings --skill:review-code=disabled --hook:docs-cache=disabled
/ioncache-ai-tools:plugin-settings --instruction:documentation-first=enabled
/ioncache-ai-tools:plugin-settings --autonomous-development:audit=disabled
/ioncache-ai-tools:plugin-settings --global --review:comments=enabled
```

In Codex, replace the leading `/` with `$`, retaining the plugin namespace.
Only Claude currently has a native pane; Copilot and Codex use text.

With no setting flags, list every shipped setting and its effective
`enabled` or `disabled` state. Preserve the helper's separate groups: Hooks,
Instructions, Autonomous development, Reviews, and Skills. Keep the typed names
shown by the helper, without abbreviating names or omitting enabled entries.
`--help` lists accepted flags. Accept only the helper's exact setting IDs and
`enabled` or `disabled` values; do not infer changes from prose.

`hook:` names control automatic checks or services; `instruction:` names control
guidance only. `skill:` names control skill availability. Related workflow
settings use `autonomous-development:<setting>` or `review:<setting>`.
The execution switch is `autonomous-development:execution`, not the skill switch.
The invocation guard is `hook:autonomous-development:explicit-only` because it
is enforced by a hook. CLI names map to existing JSON keys; never rename those
keys or pass unprefixed storage IDs as flags.

Changes default to the current project and apply across Claude, Copilot, and
Codex. `--global` updates all three global files without removing project
overrides. Its output distinguishes global values from the effective state in
the current project. `--project PATH` selects another project directory.

## Execution

Resolve `../../hooks/scripts/plugin_settings.py` relative to this skill's
installed directory, not the working directory. Run it with Python 3.11+ from
the user's project directory. Pass only the supplied arguments as separate,
shell-quoted arguments. Quote the resolved script path too:

```sh
python3 "/absolute/plugin root/hooks/scripts/plugin_settings.py" --hook:answer-questions=disabled
```

Arguments are data, never shell code. Do not paste raw argument text into a
shell command, use shell evaluation, generate a replacement script, or edit
settings JSON yourself. With no arguments, run the helper without arguments;
the listing is read-only and creates no settings or lock files.

Return the helper's grouped tables and necessary diagnostics, not a sentence-by-sentence
summary. After updates, it prints saved paths and re-reads effective settings.
Do not claim success on a nonzero exit. Validation precedes writes, but a write
failure can leave a partial cross-host update; inspect and resolve the cause
before retrying. Never claim the files form one atomic transaction.

`skill:plugin-settings` disables this skill like any other. The standalone
helper remains available for explicitly requested settings management, including
re-enabling the skill. Do not re-enable it without a user request.
`hook:plugin-settings-ui` independently controls Claude's interactive pane.
Disabling it makes the same command print the listing instead.
Neither switch disables the standalone helper.
Settings changes need no reinstall; instructions already in conversation may
need a new session to refresh. Do not reload hosts or change native permissions.

Details: [../../docs/configuration.md](../../docs/configuration.md).
