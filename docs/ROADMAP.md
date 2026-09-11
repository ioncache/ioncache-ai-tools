# Rule Roadmap

Candidate rules for `hooks/rules/`, sourced from behavioral-rule memories
accumulated in other projects (mainly `coral-platform`'s `~/.claude/`
memory store). This is the itemized list referenced but never enumerated
in `2026-09-04-generic-rule-engine-design.md`'s "~40 candidate rules."
Not a work item for the current PR, that PR ships and hardens the 5
pilot rules plus the disable-config feature. This file just tracks what
comes after.

Source files are named as they exist in `coral-platform`'s own memory
store, not in this repo.

## Shipped

- `never-kill-without-asking` (from `feedback_never_kill_process_without_asking`)
- `no-manual-lockfile-edit` / `no_manual_lockfile_edit_bash` (from `feedback_never_hand_edit_lockfile`)
- `fix_emdash` (from `feedback_no_emdashes`)
- `scope-exactly-what-asked` (from `feedback_scope_exactly_what_asked`)
- `verify-state-before-claiming` (from `feedback_verify_state_before_claiming`)

Already solved by a different mechanism, not a rule-engine rule:

- Docs-first discipline (`feedback_always_read_current_docs`) is `docs_first_guard.py`.
- Question-answering discipline (`feedback_answer_questions_first`, from `data-sanitization`) is the `answer-questions` skill, now enforced by `require_answer_questions_skill.py`.
- Never copy env files into a worktree (`feedback_env_symlink_only`) is what `.worktree-setup.json`'s `symlinks` key already does generically.

## Candidates

Roughly 45 of 87 memories audited as generic and portable. Grouped by theme.

**Approval/scope discipline**: `feedback_clarifying_question_not_approval`,
`feedback_exit_plan_mode_not_approval`, `feedback_no_autonomous_commits`,
`feedback_never_offer_to_push`, `feedback_no_verify_permission_scope`,
`feedback_no_automatic_infra_commands`, `feedback_mandatory_instructions_no_asking`

**Verification/honesty**: `feedback_deployed_state_is_source_of_truth`,
`feedback_no_fabricated_decision_rationale`,
`feedback_no_intent_inference_from_names`,
`feedback_no_cross_prompt_memory_for_live_state`,
`feedback_no_downgrade_for_difficulty`

**Git/tooling habits**: `feedback_git_permission_scope`,
`feedback_no_manual_reverts`, `feedback_no_sed`, `feedback_no_curl_github`,
`feedback_use_gh_stack_for_stacked_prs`, `feedback_prefer_libs_over_handrolling`,
`feedback_prefer_js_over_python` (this plugin's own equivalent memory is
`js-vs-python-means-better-fit`: prefer means better fit, not JS
unconditionally, and never have one language shell out to spawn the
other as a subprocess)

**PR-review method/style**: `feedback_pr_body_updates`,
`feedback_pr_comments_require_diff_hunk`,
`feedback_quote_human_review_comments_in_full`,
`feedback_review_comments_describe_behaviour`,
`feedback_review_means_critical_thinking`, `feedback_review_only_no_code_offers`,
`feedback_review_check_pr_and_ticket_by_default`, `feedback_minimal_suggestion_scope`,
`feedback_no_keys_in_pr_bodies`, `feedback_pr_descriptions`,
`feedback_pr_comment_brevity` (mostly generic; cites one Coral-specific companion doc)

**Docs/comms discipline**: `feedback_markdown_cross_reference_links`,
`feedback_notion_becomes_source_of_truth`, `feedback_incremental_notion_pushes`,
`feedback_no_superfluous_doc_examples`, `feedback_jsdoc_no_package_repetition`,
`feedback_no_version_numbers_in_comments`, `feedback_plan_docs_living_document`,
`feedback_plan_docs_pristine_no_status`, `feedback_question_responses`,
`feedback_flag_offtopic_questions`, `feedback_full_paths_only`

**Session/workflow mechanics**: `feedback_plan_mode_descriptive_names`,
`feedback_pretooluse_plan_mode` (a Claude Code product fact, PreToolUse
doesn't block in Plan mode, relevant to this plugin's own hooks rather
than a portable rule itself), `feedback_workflow_visibility`,
`feedback_no_verification_during_live_debugging`, `feedback_manual_testing_first`,
`feedback_no_hardcoded_config`, `feedback_scope_commands_to_active_worktree`
(principle generalizes even though its examples are Coral paths)

## Ambiguous

Rule generalizes, needs its examples/references swapped out before porting:

- `feedback_always_read_current_docs` (rule generic; apiVersion-pinning example is Stripe/Coral)
- `feedback_fix_wrong_jsdoc_even_if_preexisting` (rule generic; cites Coral's own jsdoc.instructions.md line numbers)
- `feedback_ignore_volta_pinning` (rule generalizes; names AGENTS.md)
- `feedback_isolate_before_implementing` (rule generic; paths are Coral's worktree convention)
- `feedback_lint_format_before_push` (rule universal; commands are `--workspace=apps/api`)
- `feedback_plans_in_main_tmp` (rule generalizes; doc names are Coral's)
- `reference_pr_review_comment_process` (points at a Coral-repo doc, but that doc's content, per `feedback_pr_comment_brevity`, reads as generic methodology)

## Not portable

Coral-platform business/infra: `project_ai_agent_config_sync`,
`project_agent_sync_candidate_flaw`, `project_member_dashboard`,
`project_privacy_update_notification`, `project_graphify_mandatory_query`,
`reference_local_stream_webhook`, `reference_local_api_env`,
`project_worktree_directory`, `feedback_never_edit_app_platform_specs`,
`feedback_reuse_api_email_functions`, `feedback_do_index_name_not_an_issue`,
`feedback_no_rate_limiting_suggestions`.

Coral-platform repo/team conventions: `feedback_additional_properties_false`,
`feedback_canadian_spelling`, `feedback_conventional_pr_titles`,
`feedback_one_line_commit_messages` (contradicts this repo's own
multi-line commit-message style, would be actively wrong to port),
`feedback_one_test_file_per_component`, `feedback_query_by_testid_in_tests`,
`feedback_strict_equality_only`, `feedback_pr_size_excludes_jsdoc`,
`feedback_scripts_in_javascript` (superseded by the generic
prefer-JS-over-Python rule above), `feedback_ignore_ongoing_files`,
`feedback_no_browser_tools` (explicitly scoped to the coral-platform
project), `feedback_graphify_not_in_branches`, `feedback_graphify_worktree_setup`.

One library gotcha worth flagging separately, not a behavioral rule:
`reference_mui_datagrid_server_pagination` documents a genuine MUI X
DataGrid v8 + SWR bug (unmemoized `sortModel` and missing
`keepPreviousData` both silently reset pagination to page 1). Reusable
knowledge for any MUI+SWR project, filed as a Coral-PR reference memory
only because that's where it was found.

## Next step, undecided

Three options on the table, none chosen yet:

1. Port the approval/scope-discipline group first, it's the most reused.
2. Upgrade this plugin's `/review-code` command with the multi-pass
   methodology the PR-review-method/style group and
   `feedback_review_means_critical_thinking` describe.
3. Something else.
