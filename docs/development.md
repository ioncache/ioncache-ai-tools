# Development and plugin maintenance

Installation: [../README.md#install](../README.md#install).
Contributor requirements: [../AGENTS.md](../AGENTS.md) and
[../.github/copilot-instructions.md](../.github/copilot-instructions.md).

## Local development

Use Python 3.11+, Node.js 22.12.0+, npm, Git, and macOS or Linux.
From the repository root:

```sh
npm ci
```

This installs contributor tooling and activates Husky's `commit-msg` hook.
Repeat it in each checkout or worktree. This repository's worktree setup runs
it automatically. Plugin users do not need these npm dependencies.

Validation commands are maintained in
[../.github/copilot-instructions.md#validation-commands](../.github/copilot-instructions.md#validation-commands).

### Loading source changes

For a session using a live checkout, run one of these from its root:

```sh
claude --plugin-dir .
copilot --plugin-dir .
```

Claude relative-path plugins from local-directory marketplaces also load in
place. Reload with `/reload-plugins` or start a new session after changes.
Remote installs are cached.

Direct Copilot installs use a cached copy. Refresh a local installation with
`copilot plugin install .`, then start a new session.

Codex installs use cached copies too. Update the source referenced by the
marketplace, reinstall with
`codex plugin add ioncache-ai-tools --marketplace ioncache-ai-tools`, and start
a fresh thread. This repository's shipped Codex marketplace points to remote
`main`; local testing requires a marketplace entry pointing at the checkout.

Refresh installed copies when testing background reviewers or documentation
distillers, even if the main session uses a live checkout. Feature settings
live outside the plugin cache and need no reinstall.

Host documentation:

- https://code.claude.com/docs/en/plugins/loading
- https://developers.openai.com/plugins/build/plugins
- https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference

## Updating and removing installed plugins

Use Claude Code's `/plugin` interface to update or remove the plugin.
For Copilot, use `copilot plugin update ioncache-ai-tools` or
`copilot plugin uninstall ioncache-ai-tools`.

Refresh the Codex marketplace and reinstall:

```sh
codex plugin marketplace upgrade ioncache-ai-tools
codex plugin add ioncache-ai-tools --marketplace ioncache-ai-tools
```

To remove the Codex plugin and its marketplace:

```sh
codex plugin remove ioncache-ai-tools --marketplace ioncache-ai-tools
codex plugin marketplace remove ioncache-ai-tools
```

Start a fresh session or thread after updating. Settings reconcile on the next
hook invocation; explicit synchronization is described in
[configuration.md](configuration.md).

## Commit conventions

Commit messages and PR titles follow Conventional Commits, for example
`fix: preserve hook permissions` or `feat(review): add draft comments`.
Generated merge, revert, and version messages are not exempt. Write reverts as
`revert: describe the reverted change`.

The `Commit conventions` workflow checks PR titles, PR commits, and commits
pushed to `main`. Local hooks can be bypassed. Require that status check on
`main` to block merges on failures. Squash-only merging, PR titles as squash
messages, and linear history are separate GitHub repository settings; the
tooling does not configure them. A bad edited squash message is reported by
the push check after it reaches `main`.

## Version changes and changelog

Every version change must update [../CHANGELOG.md](../CHANGELOG.md) with New,
Updated, and Fixed sections. In a clean feature worktree, commit the intended
changes first, then run:

```sh
npm run release -- VERSION
```

Replace `VERSION` with an increasing `MAJOR.MINOR.PATCH` version.
The helper requires contributor dependencies and full Git history. It uses
https://conventional-changelog.js.org/ with the Conventional Commits preset.
It updates all three plugin manifests and prepends notes from commits since
the commit that introduced the current manifest version. Metadata-only
manifest edits do not reset that boundary; no release tags are required.

`feat` and `feature` commits become New items, `fix` commits become Fixed
items, and other commits become Updated items. Breaking changes get a separate
section. Merge commits are excluded; reverted commits and their reverts remain
visible. Items link to commits, and empty sections say `None.`.

Review the generated notes, then commit the manifests and changelog together.
The helper does not commit, tag, push, or include uncommitted changes.
Check manifest and changelog consistency with:

```sh
npm run release:check
```
