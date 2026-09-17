# Rule Roadmap

## Shipped

- **`never_kill_without_asking`**: denies `kill`/`pkill`/`killall` unless the user has explicitly said yes first, even for the assistant's own leftover process. Prevents the assistant from killing a process based on its own judgment that it's "safe" or "leftover", that judgment is often wrong: the process could be a dev server holding state, a debugger session, or something the user is actively relying on, and killing it can't be undone. Uses real command tokenization (Python's `shlex`), not a regex, to check whether the guarded word is actually the command being run rather than an argument or a substring elsewhere in the text.
- **`git push` agent hook** (`hooks/hooks.json`, not a `hooks/rules/*` rule): denies `git push` unless the current turn explicitly and unambiguously authorized this specific push. A deterministic tokenizing rule (matching `never_kill_without_asking`'s approach) was tried first, but "did the user explicitly authorize this" is a judgment call over open-ended natural language, not something an exact-phrase or keyword match can cover without either missing real phrasing or accepting a loose match that risks a false authorization. Uses Claude Code's experimental `type: "agent"` PreToolUse hook instead: a subagent reads the transcript and judges the current turn's messages, denying on any doubt or ambiguity. Prior or implied permission never carries over, only the current turn's own message can authorize a given push. The `if: "Bash(*git*push*)"` pre-filter only decides whether to spawn the subagent, never whether to deny: it is a raw-text glob that both over-fires (on text merely mentioning "git" and "push") and under-fires (the docs confirm `Bash(git push *)` misses `git -C . push`), and Claude Code additionally spawns the hook whenever it cannot statically resolve a command. The subagent's prompt therefore checks as an explicit first step whether the command really is a push, returning allow immediately if not, without reading the transcript. An earlier version asserted "this is a push" as a premise instead, which turned every over-fire into a denial and blocked unrelated commands such as `gh api ... -f body="$(cat file)"`; that was a defect in the prompt, not in the filter. Letting the subagent judge intent rather than spelling also catches `git${IFS}push`, which no pattern-matching rule can. Remaining gap: indirection the command text does not reveal, such as a wrapper script that runs `git push` internally (see README's `git push` agent hook section).
- **`no-manual-lockfile-edit` / `no_manual_lockfile_edit_bash`**: denies hand-editing a lockfile (via Edit/Write/MultiEdit or via Bash redirection/`sed -i`/`tee`/`perl -i`); the fix is to resolve `package.json` first, then regenerate the lockfile via install. A lockfile records the exact resolved dependency tree, transitive versions and integrity hashes, that satisfies `package.json`'s ranges. Hand-editing it (including splicing in unresolved merge-conflict markers) desyncs that recorded tree from what the resolver would actually produce, so a later install either silently reverts the edit or, worse, leaves other developers and CI running a different dependency tree than what was tested. The Bash-side check uses the same command tokenization as `never_kill_without_asking`, binding each mutation's operation, options, and target together so an unrelated command that merely mentions a lockfile name isn't denied.
- **`fix_emdash`**: rewrites em-dashes to `, ` in Write/Edit/MultiEdit content; denies (asks for a manual fix) in Bash. The em-dash itself is a banned stylistic tic; the reason Bash gets a deny instead of the same silent rewrite is that inserting a space where the em-dash was can split one shell argument into two (e.g. turning one filename into two separate arguments to `rm --`), silently changing what the command actually does.
- **`scope-exactly-what-asked`**: reminds the assistant it isn't authorized to make changes beyond the literal request. Noticing an unrelated issue while working is not license to fix it in the same change: unrequested edits expand the diff being reviewed, mix unrelated concerns together, and can hand the user changes they never asked for or agreed to.
- **`verify-state-before-claiming`**: reminds the assistant to check live push/PR/CI/branch state in the same turn rather than stating it from memory or from what it believes it already did. "I did not push" is a claim about the assistant's own actions; "nothing was pushed" is a claim about the actual state of a shared system, and only checking that system directly can confirm which is true. Stating status from recollection risks confidently asserting something false about state other people also rely on.
- **`docs_first_guard.py`**: unconditionally reminds the assistant, on every prompt, to verify library/API/CLI/service specifics via a real lookup instead of stating them from training data. An earlier version tried to detect *when* a lookup was needed first from prompt keywords, then from the project's dependency manifest, but both missed real cases (a request that never mentions docs, a package that isn't a dependency yet), and a classifier broad enough to catch what matters fires on nearly every turn anyway, so there was no accuracy actually being bought by the extra machinery. Training data has a cutoff and can be wrong for the exact version actually in use, even for something the project already depends on.
- **`answer-questions` skill + `require_answer_questions_skill.py`**: requires a direct, explicit answer to a question, with reasoning, before any other output; no acknowledgment, apology, or pre-emptive work product unless the question's own content asks for one. Acknowledgment and apology don't answer what was asked, they cost the user time reading past them to find the actual answer. Drafting a solution before it was asked for spends real generation cost on work that may get thrown away, and anchors the next reply to a specific version the user never approved.
- **`.worktree-setup.json`'s `symlinks` key**: replaces hand-copying untracked local files (like env files) into a new worktree. A copy silently diverges from its source the moment either one is edited afterward; a symlink keeps a single source of truth. Copying a secrets-bearing file into every worktree also multiplies how many places on disk that secret exists, with no benefit.

## Next

The highest-value, least-ambiguous candidates, each with enough detail to
implement directly:

- **Never close a PR without asking.** Closing a PR is exclusively the repo owner's decision; deny the action, don't just recommend against it.
- **Never use curl for GitHub, use `gh`.** If `gh` returns 401, fix auth, don't fall back to curl.
- **Never `git commit` unless explicitly asked in that turn.** "Finish it" or "proceed" is not that instruction; a prior "commit" earlier in the session does not carry forward to later, unrelated changes.
- **Never remove functionality without asking first.** Any removal of existing code or planned functionality needs its own explicit "do you want X removed?" question, asked before removing it, not folded into a summary after the fact.
- **A clarifying question in reply to a proposal is not approval.** Answer it, take no action, wait for an explicit go-ahead.
- **Exiting plan mode is not approval to edit.** `ExitPlanMode` ends planning; it does not authorize edits. Stop after the plan and wait for an explicit "implement it."
- **Never run infrastructure mutations directly.** Write a reviewable script, wait for approval, and commit recurring ones to the repo instead of one-off inline commands.

## Later

Real candidates, lower urgency or more setup needed to adapt well:

**Verification and honesty**

- Treat deployed/live state as the source of truth; never reason or act from local files or stale exports.
- Never invent a rationale for a past decision to fill a gap; ask for the real reason and verify any factual premise in it.
- Never state a code's business intent as fact from a variable/function name alone; verify it or flag it explicitly as an assumption.
- Never reuse a cached live-state value (an API/DB/config value) across separate prompts; reuse within the same prompt/turn is fine.
- Never downgrade a valid review finding to no-fix because it's hard or wide-reaching; difficulty is a separate axis from validity.

**Git and tooling habits**

- Never hand-roll a revert; only `git revert <sha>` is acceptable. Drop noise commits with reset/rebase first, then revert the original.
- Scope a Bash permission request to the specific git subcommand needed (`git log`, `git diff`, `git show`), never a wildcard `git *`.
- Prefer an existing library dependency over hand-rolling equivalent logic; adding a dependency for this is fine, don't over-deliberate it.
- Use `gh stack` as the only method for stacked PRs; no manual `git rebase --onto` fallback even if `gh stack` seems unavailable.
- One bypass/`--no-verify` approval covers exactly one commit; ask again next time rather than treating an earlier bypass as standing permission.

**PR-review method and style**

- Every PR comment must be fetched with its diff hunk and surrounding code context, never composed from the comment body text alone.
- Quote a human reviewer's comment in full and verbatim, with author, file:line, and URL; only bot comments may be summarized.
- Describe a PR comment's behavior scenario for a human reader (how the business rule breaks, what should happen instead), not a line-by-line code prescription.
- Keep each PR suggestion to the smallest anchor and a minimal diff, one fix per comment, never bundled into one large comment.
- During a review, never offer or ask to apply the fixes found; report findings only, especially on a PR that isn't the reviewer's own.
- "Review this file/PR" implicitly means checking for an open PR, a linked ticket, and existing review comments first, without being told to.
- Never replace a PR body wholesale; fetch its current content and amend only what actually changed.

**Docs and communication discipline**

- Always cross-link internal doc references between related steps, sections, and decisions; add anchors if the target isn't already a header.
- Log every deviation from a written plan doc in that doc, in the same turn it happens: what changed, why, and the new steps.
- A question gets answered directly with its WHY; never pivot from answering into unrelated code or tasks in the same breath.
- An off-topic question (unrelated to the current work stream) gets flagged before being answered; let the user choose to proceed here or switch sessions.
- Always give a full or cwd-relative path when referencing a file, never a bare filename; a worktree path is always given in full, never shorthand.
- Don't cite an external library or tool as a risk precedent in docs unless it's actually part of this stack, citing one that isn't reads as if it is.
- Don't repeat what a package/library already does in a doc comment; only document the specific configuration choices made and why.
- A WHY comment can describe a dependency's behavior, but never cite its specific version number; version-pinned comments rot as the dependency updates.
- A plan or runbook doc lists only what still needs doing, never "Status:"/"Done:" progress callouts mixed into the steps.

**Session and workflow mechanics**

- Rename plan-mode's auto-generated codename filename to something descriptive before it's kept; never leave the generated name in place.
- Don't re-run full verification (tests/lint/format) after every attempt while iterating live with the user; verify once at the end of that loop.
- New agents or knowledge bases get human manual testing first; eval datasets and automated runs only apply once promoting past that stage, never as the initial validation.
- Never hardcode a config-shaped value (an ID, URL, or similar); resolve it from repo config, environment, or a runtime lookup by name. "Stable and non-secret" is not an exception.
- Once work concerns a specific PR or branch that has its own worktree, run all commands from that worktree's path, not the main checkout's ambient branch.
- `PreToolUse` deny/exit-2 does not block tool calls while in Plan mode; a rule that needs to hold during Plan mode has to use `UserPromptSubmit` plus injected context instead.

## Needs adaptation before porting

The underlying rule generalizes, but its concrete example or reference
needs replacing before the rule is useful outside its origin project:

- Always fetch and cite the current version of third-party API docs before describing their behavior; the existing example cites a specific Stripe API version that won't generalize.
- A doc correction is due regardless of whether the error pre-existed the current change; the existing example cites another project's specific doc line numbers.
- Ignoring a tool-version-pinning mismatch (e.g. a package manager's pinned version vs. an engine constraint) as a non-issue; the existing example names a specific pinning tool.
- Isolate work in its own workspace before implementing; the existing example assumes another project's specific worktree path convention.
- Run lint and format before every push, fixing what's found; the existing example cites another project's specific workspace-scoped command.
- Plan and runbook docs live in the repo's own tracked docs folder, never a temp directory; the existing example names another project's specific doc folder.

## Not planned

Business logic, team process, or tooling conventions specific to another
project, not generic. Includes at least one that would be actively wrong
to port here: a one-line-commit-message convention that contradicts this
repo's own multi-line commit style.

## Open

Not decided yet which "Next" item to build first, or whether to instead
spend that effort upgrading `/review-code` with the multi-pass review
methodology the PR-review-method group above describes.
