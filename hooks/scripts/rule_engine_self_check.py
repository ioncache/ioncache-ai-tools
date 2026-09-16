#!/usr/bin/env python3
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
import rule_engine  # noqa: E402
from rule_engine import (  # noqa: E402
    match_rule,
    resolve_action,
    merge_pre_tool_use,
    merge_user_prompt_submit,
    run_rules,
    load_rules_for_event,
    get_disabled_rule_ids,
)

RULES_DIR = os.path.join(SCRIPT_DIR, '..', 'rules')


def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fix_emdash = _load_module(os.path.join(RULES_DIR, 'fix_emdash.py'), 'fix_emdash')
no_manual_lockfile_edit_bash = _load_module(
    os.path.join(RULES_DIR, 'no_manual_lockfile_edit_bash.py'), 'no_manual_lockfile_edit_bash'
)
never_kill_without_asking = _load_module(
    os.path.join(RULES_DIR, 'never_kill_without_asking.py'), 'never_kill_without_asking'
)


def main():
    # match_rule: always
    assert match_rule({'matcher': {'type': 'always'}}, {}) is True, 'always matcher should always match'

    # match_rule: regex + toolNames restriction
    regex_rule = {
        'toolNames': ['Bash'],
        'matcher': {'type': 'regex', 'field': 'tool_input.command', 'pattern': r'\bkill\b'},
    }
    assert (
        match_rule(regex_rule, {'tool_name': 'Bash', 'tool_input': {'command': 'kill -9 123'}}) is True
    ), 'regex matcher should match when pattern is present'
    assert (
        match_rule(regex_rule, {'tool_name': 'Bash', 'tool_input': {'command': 'ls'}}) is False
    ), 'regex matcher should not match unrelated command'
    assert (
        match_rule(regex_rule, {'tool_name': 'Read', 'tool_input': {'command': 'kill'}}) is False
    ), 'toolNames restriction should exclude other tools'

    # match_rule: custom matches() function is invoked and its result respected
    custom_matcher_called = {'value': False}

    def custom_matches(hook_input):
        custom_matcher_called['value'] = True
        return hook_input['tool_input']['command'] == 'trigger-me'

    custom_match_rule = {'toolNames': ['Bash'], 'matches': custom_matches}
    assert (
        match_rule(custom_match_rule, {'tool_name': 'Bash', 'tool_input': {'command': 'trigger-me'}}) is True
    ), 'custom matches() should be invoked and its true result respected'
    assert custom_matcher_called['value'] is True, 'custom matches() should actually be called'
    assert (
        match_rule(custom_match_rule, {'tool_name': 'Bash', 'tool_input': {'command': 'something-else'}}) is False
    ), 'custom matches() false result should be respected'

    # match_rule: custom matches() is still gated by toolNames
    custom_matcher_called['value'] = False
    assert (
        match_rule(custom_match_rule, {'tool_name': 'Read', 'tool_input': {'command': 'trigger-me'}}) is False
    ), 'toolNames should exclude the tool before custom matches() runs'
    assert custom_matcher_called['value'] is False, 'custom matches() should not be called when toolNames excludes the tool'

    # resolve_action: declarative deny/inject
    assert resolve_action({'action': 'deny', 'message': 'no'}, {}) == {'action': 'deny', 'message': 'no'}
    assert resolve_action({'action': 'inject', 'message': 'hi'}, {}) == {'action': 'inject', 'message': 'hi'}

    # resolve_action: scripted rule
    scripted_rule = {'check': lambda _input: {'action': 'rewrite', 'updatedInput': {'command': 'fixed'}}}
    assert resolve_action(scripted_rule, {}) == {'action': 'rewrite', 'updatedInput': {'command': 'fixed'}}

    # merge_pre_tool_use: deny wins over rewrite
    deny_wins = merge_pre_tool_use(
        [
            {'action': 'rewrite', 'updatedInput': {'command': 'fixed'}},
            {'action': 'deny', 'message': 'blocked'},
        ]
    )
    assert deny_wins['hookSpecificOutput']['permissionDecision'] == 'deny'
    assert deny_wins['hookSpecificOutput']['permissionDecisionReason'] == 'blocked'

    # merge_pre_tool_use: rewrite only
    rewrite_only = merge_pre_tool_use(
        [{'action': 'rewrite', 'updatedInput': {'command': 'fixed'}, 'systemMessage': 'msg'}]
    )
    assert rewrite_only['hookSpecificOutput']['permissionDecision'] == 'allow'
    assert rewrite_only['hookSpecificOutput']['updatedInput'] == {'command': 'fixed'}
    assert rewrite_only['systemMessage'] == 'msg'

    # merge_pre_tool_use: nothing matched
    assert merge_pre_tool_use([]) is None

    # merge_user_prompt_submit: concatenation, wrapped in hookSpecificOutput
    # (Claude Code requires additionalContext nested there with hookEventName
    # set, a bare top-level additionalContext field is silently ignored)
    injected = merge_user_prompt_submit([{'action': 'inject', 'message': 'first'}, {'action': 'inject', 'message': 'second'}])
    assert injected['hookSpecificOutput']['hookEventName'] == 'UserPromptSubmit'
    assert injected['hookSpecificOutput']['additionalContext'] == 'first\n\nsecond'

    # merge_user_prompt_submit: nothing matched
    assert merge_user_prompt_submit([]) is None

    # run_rules: a throwing rule does not break other rules
    def _throw(_input):
        raise RuntimeError('boom')

    rules_with_failure = [
        {'event': 'PreToolUse', 'matcher': {'type': 'always'}, 'check': _throw},
        {'event': 'PreToolUse', 'matcher': {'type': 'always'}, 'action': 'deny', 'message': 'caught the good one'},
    ]
    run_result = run_rules(rules_with_failure, 'PreToolUse', {'tool_name': 'Bash', 'tool_input': {}})
    assert run_result['hookSpecificOutput']['permissionDecisionReason'] == 'caught the good one'

    # run_rules: a rule returning a malformed result (not a dict, or an
    # inject with a non-string message) is dropped, not allowed to raise
    # inside the merge step where it would take every sibling result with it
    rules_with_malformed_result = [
        {'event': 'PreToolUse', 'matcher': {'type': 'always'}, 'check': lambda _input: 'not-a-dict'},
        {'event': 'UserPromptSubmit', 'matcher': {'type': 'always'}, 'check': lambda _input: {'action': 'inject', 'message': None}},
        {'event': 'PreToolUse', 'matcher': {'type': 'always'}, 'action': 'deny', 'message': 'still works'},
    ]
    malformed_pre_tool_use = [r for r in rules_with_malformed_result if r['event'] == 'PreToolUse']
    malformed_result = run_rules(malformed_pre_tool_use, 'PreToolUse', {'tool_name': 'Bash', 'tool_input': {}})
    assert (
        malformed_result['hookSpecificOutput']['permissionDecisionReason'] == 'still works'
    ), 'a non-dict result from one rule should not prevent a valid sibling deny from surfacing'
    malformed_prompt_submit = [r for r in rules_with_malformed_result if r['event'] == 'UserPromptSubmit']
    assert (
        run_rules(malformed_prompt_submit, 'UserPromptSubmit', {}) is None
    ), 'an inject result with a non-string message should be dropped, not raise'

    # load_rules_for_event: reads json + py rules, filters by event
    tmp_dir = tempfile.mkdtemp(prefix='rule-engine-test-')
    with open(os.path.join(tmp_dir, 'a.json'), 'w', encoding='utf-8') as f:
        json.dump({'event': 'PreToolUse', 'matcher': {'type': 'always'}, 'action': 'deny', 'message': 'a'}, f)
    with open(os.path.join(tmp_dir, 'b.json'), 'w', encoding='utf-8') as f:
        json.dump({'event': 'UserPromptSubmit', 'matcher': {'type': 'always'}, 'action': 'inject', 'message': 'b'}, f)
    with open(os.path.join(tmp_dir, 'c.py'), 'w', encoding='utf-8') as f:
        f.write("EVENT = 'PreToolUse'\ndef matches(hook_input):\n    return True\ndef check(hook_input):\n    return None\n")
    pre_tool_use_rules = load_rules_for_event(tmp_dir, 'PreToolUse')
    assert len(pre_tool_use_rules) == 2, 'should load both PreToolUse rules (json + py)'
    user_prompt_rules = load_rules_for_event(tmp_dir, 'UserPromptSubmit')
    assert len(user_prompt_rules) == 1, 'should load only the UserPromptSubmit rule'
    shutil.rmtree(tmp_dir, ignore_errors=True)

    # load_rules_for_event: missing directory returns empty list, never throws
    assert load_rules_for_event(os.path.join(tmp_dir, 'does-not-exist'), 'PreToolUse') == []

    # load_rules_for_event: a bad rule file is skipped, valid siblings still load
    bad_rules_dir = tempfile.mkdtemp(prefix='rule-engine-bad-')
    with open(os.path.join(bad_rules_dir, 'good.json'), 'w', encoding='utf-8') as f:
        json.dump({'event': 'PreToolUse', 'matcher': {'type': 'always'}, 'action': 'deny', 'message': 'good'}, f)
    with open(os.path.join(bad_rules_dir, 'bad.json'), 'w', encoding='utf-8') as f:
        f.write('{invalid json')
    with open(os.path.join(bad_rules_dir, 'throw.py'), 'w', encoding='utf-8') as f:
        f.write("raise RuntimeError('rule load error')\n")
    load_error = None
    bad_dir_rules = []
    try:
        bad_dir_rules = load_rules_for_event(bad_rules_dir, 'PreToolUse')
    except Exception as err:  # pragma: no cover - should never trigger
        load_error = err
    assert load_error is None, 'load_rules_for_event should not throw on invalid rule files'
    assert len(bad_dir_rules) == 1, 'only the valid rule should load, the bad ones are skipped'
    assert bad_dir_rules[0]['name'] == 'good.json', 'the valid rule should still be the one that loads'
    shutil.rmtree(bad_rules_dir, ignore_errors=True)

    # Real pilot rules load correctly for PreToolUse
    real_pre_tool_use_rules = [r['name'] for r in load_rules_for_event(RULES_DIR, 'PreToolUse')]
    assert 'never_kill_without_asking.py' in real_pre_tool_use_rules
    assert 'no-manual-lockfile-edit.json' in real_pre_tool_use_rules
    assert 'no_manual_lockfile_edit_bash.py' in real_pre_tool_use_rules
    assert 'block_raw_worktree_add.py' in real_pre_tool_use_rules

    # Real pilot rules load correctly for UserPromptSubmit
    real_user_prompt_rules = [r['name'] for r in load_rules_for_event(RULES_DIR, 'UserPromptSubmit')]
    assert 'scope-exactly-what-asked.json' in real_user_prompt_rules
    assert 'verify-state-before-claiming.json' in real_user_prompt_rules

    # never_kill_without_asking: exercises the shipped module directly, a
    # tokenizing scripted rule (not a regex Pattern rule), since matching
    # "is this word the command being run" reliably needs real command
    # tokenization, not a flat-text pattern.
    kill_cases = [
        ('kill -9 12345', True, 'a real kill invocation'),
        ('cat hooks/rules/never-kill-without-asking.json', False, 'its own filename substring (hyphen-boundary regression)'),
        ('/bin/kill -9 12345', True, 'a path-qualified kill invocation (e.g. /bin/kill)'),
        ('/usr/bin/pkill 12345', True, 'a path-qualified pkill invocation'),
        ('/sbin/killall 12345', True, 'a path-qualified killall invocation'),
        ('kill>/tmp/log -9 12345', True, 'redirection attached directly to the command name'),
        ('\\kill -9 12345', True, 'a backslash-escaped command name (Bash executes it as plain kill)'),
        ('k\\ill -9 12345', True, 'a mid-word backslash escape'),
        ("'kill' -9 12345", True, 'a single-quoted command name'),
        ('"kill" -9 12345', True, 'a double-quoted command name'),
        ('ki\\\nl\\\nl -9 12345', True, 'a command name split by backslash-newline line continuation'),
        (
            'git commit -m "note about \'kill\'"',
            False,
            "a single-quoted substring nested inside double quotes (real Bash treats it as literal text), regression check",
        ),
        ("echo '\\kill'", False, 'a backslash inside single quotes (Bash treats it as fully literal there), regression check'),
        ('ls /tmp/kill', False, 'a path argument to an unrelated command, not an invocation (prior false-positive regression)'),
        ('true; /bin/kill -9 12345', True, 'a path-qualified invocation as the second command in a chain'),
        ('sleep 1 && kill -9 12345', True, 'a bare invocation as the second command in a chain'),
        ('echo "(kill -9 12345)"', False, 'the guarded word mentioned inside an echoed string, never invoked'),
        ('timeout 5 kill -9 12345', True, 'a timeout wrapper around the invocation'),
        ('nohup kill -9 12345', True, 'a no-argument wrapper around the invocation'),
        ('nice kill -9 12345', True, 'a bare (no-flag) nice wrapper around the invocation'),
        ('timeout 5 ls /tmp/kill', False, 'a wrapper around an unrelated command should still not match'),
        (
            'nice -n 10 kill -9 12345',
            False,
            'a wrapper invoked with its own value-taking flag, a documented accepted gap, not a regression',
        ),
    ]
    for command, expected, label in kill_cases:
        got = never_kill_without_asking.matches({'tool_name': 'Bash', 'tool_input': {'command': command}})
        assert got is expected, f'never_kill_without_asking should {"" if expected else "not "}match {label}: {command!r}'

    # Real no-manual-lockfile-edit rule file, matched via match_rule directly
    with open(os.path.join(RULES_DIR, 'no-manual-lockfile-edit.json'), 'r', encoding='utf-8') as f:
        lockfile_rule = json.load(f)
    assert (
        match_rule(lockfile_rule, {'tool_name': 'Edit', 'tool_input': {'file_path': 'package-lock.json'}}) is True
    ), 'no-manual-lockfile-edit should match a real lockfile edit'
    # No hyphen-boundary regression case here: this pattern anchors on a
    # literal filename suffix ($), it never uses \b, so there's no
    # separator-class boundary for a hyphenated identifier to slip past.

    # no_manual_lockfile_edit_bash: catches Bash mutations the Edit/Write/
    # MultiEdit-only rule above can't see. Tokenization-based, same as
    # never_kill_without_asking: binds the mutation operation, its
    # options, and its target together per simple command, instead of
    # matching a lockfile name and a mutation pattern independently
    # anywhere in the whole command.
    lockfile_name = 'package-lock.json'
    lockfile_cases = [
        (f'printf x > {lockfile_name}', True, 'a redirection into a lockfile'),
        (f'sed -i s/a/b/ {lockfile_name}', True, 'sed -i targeting a lockfile'),
        (f'sed -E -i s/a/b/ {lockfile_name}', True, 'sed -E -i, a flag between sed and -i (prior bypass regression)'),
        (f'sed -i.bak s/a/b/ {lockfile_name}', True, 'sed -i.bak suffix form'),
        (f'tee {lockfile_name}', True, 'tee targeting a lockfile'),
        (f'cat {lockfile_name}', False, 'reading a lockfile without a mutation'),
        (
            f'printf x > output && cat {lockfile_name}',
            False,
            'an unrelated mutation with the lockfile only read elsewhere (prior false-positive regression)',
        ),
        (
            f's\\ed -i s/a/b/ {lockfile_name}',
            True,
            'a backslash-escaped sed -i targeting a lockfile (same escape bypass closed for never_kill_without_asking)',
        ),
        ('npm install', False, 'an unrelated Bash command'),
        (f'timeout 5 sed -i s/a/b/ {lockfile_name}', True, 'a timeout wrapper around an in-place sed targeting a lockfile'),
        (f'perl -pi -e s/a/b/ {lockfile_name}', True, "perl's combined -pi in-place flag"),
        (f'sed -Ei s/a/b/ {lockfile_name}', True, "GNU sed's combined -Ei in-place flag"),
        (f'sed --in-place s/a/b/ {lockfile_name}', True, "GNU sed's long-form --in-place flag"),
        (f'cp /tmp/fake-lock.json {lockfile_name}', True, 'a plain copy overwriting a lockfile'),
        (f'cp {lockfile_name} /tmp/backup.json', False, 'a plain copy reading a lockfile, not overwriting it'),
    ]
    for command, expected, label in lockfile_cases:
        got = no_manual_lockfile_edit_bash.matches({'tool_name': 'Bash', 'tool_input': {'command': command}})
        assert got is expected, f'no_manual_lockfile_edit_bash should {"" if expected else "not "}match {label}'

    # fix_emdash: matches per tool type
    em_dash = chr(0x2014)
    assert (
        fix_emdash.matches({'tool_name': 'Bash', 'tool_input': {'command': f'a{em_dash}b'}}) is True
    ), 'fix_emdash should match a Bash command containing an em-dash'
    assert (
        fix_emdash.matches({'tool_name': 'Bash', 'tool_input': {'command': 'a-b'}}) is False
    ), 'fix_emdash should not match a plain hyphen'

    # fix_emdash: check denies Bash instead of rewriting (an inserted space
    # could split one shell argument into two)
    bash_result = fix_emdash.check({'tool_name': 'Bash', 'tool_input': {'command': f'one{em_dash}two', 'description': 'keep me'}})
    assert bash_result['action'] == 'deny', 'fix_emdash should deny Bash rather than rewrite it'
    assert isinstance(bash_result.get('message'), str) and bash_result['message'], 'deny should include a message'

    # fix_emdash: check rewrites MultiEdit edits array, leaves unaffected edits untouched
    multi_edit_result = fix_emdash.check(
        {
            'tool_name': 'MultiEdit',
            'tool_input': {
                'file_path': 'f.py',
                'edits': [
                    {'old_string': 'x', 'new_string': f'a{em_dash}b'},
                    {'old_string': 'y', 'new_string': 'unchanged'},
                ],
            },
        }
    )
    assert multi_edit_result['updatedInput']['edits'][0]['new_string'] == 'a, b'
    assert multi_edit_result['updatedInput']['edits'][1]['new_string'] == 'unchanged'

    NO_CLAUDE_GLOBAL = '/does/not/exist-global.json'
    NO_CODEX = '/does/not/exist.toml'

    def write_json(path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f)

    def write_text(path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)

    # get_disabled_rule_ids: reads disabledRules from a Claude Code project settings file
    claude_project_root = tempfile.mkdtemp(prefix='rule-engine-claude-config-')
    write_json(os.path.join(claude_project_root, '.claude', 'ioncache-ai-tools.local.json'), {'disabledRules': ['test-rule-a']})
    claude_disabled = get_disabled_rule_ids(claude_project_root, codex_config_path=NO_CODEX, claude_global_path=NO_CLAUDE_GLOBAL)
    assert claude_disabled == {'test-rule-a'}, 'should read disabledRules from the Claude Code project settings file'
    shutil.rmtree(claude_project_root, ignore_errors=True)

    # get_disabled_rule_ids: a malformed Claude Code settings file degrades to empty, never throws
    malformed_project_root = tempfile.mkdtemp(prefix='rule-engine-malformed-config-')
    write_text(os.path.join(malformed_project_root, '.claude', 'ioncache-ai-tools.local.json'), '{not valid json')
    malformed_disabled = get_disabled_rule_ids(malformed_project_root, codex_config_path=NO_CODEX, claude_global_path=NO_CLAUDE_GLOBAL)
    assert malformed_disabled == set(), 'a malformed settings file should degrade to no disabled rules, not throw'
    shutil.rmtree(malformed_project_root, ignore_errors=True)

    # get_disabled_rule_ids: a string disabledRules value is ignored rather
    # than iterated character by character
    string_shape_project_root = tempfile.mkdtemp(prefix='rule-engine-string-shape-')
    write_json(os.path.join(string_shape_project_root, '.claude', 'ioncache-ai-tools.local.json'), {'disabledRules': 'test-rule-a'})
    string_shape_disabled = get_disabled_rule_ids(
        string_shape_project_root, codex_config_path=NO_CODEX, claude_global_path=NO_CLAUDE_GLOBAL
    )
    assert string_shape_disabled == set(), 'a string disabledRules value should be ignored, not iterated character by character'
    shutil.rmtree(string_shape_project_root, ignore_errors=True)

    # get_disabled_rule_ids: a global Claude Code config disables a rule with no project config at all
    claude_global_dir = tempfile.mkdtemp(prefix='rule-engine-claude-global-')
    claude_global_path = os.path.join(claude_global_dir, 'ioncache-ai-tools.local.json')
    write_json(claude_global_path, {'disabledRules': ['test-rule-a']})
    no_project_root = tempfile.mkdtemp(prefix='rule-engine-no-project-config-')
    global_only_disabled = get_disabled_rule_ids(no_project_root, codex_config_path=NO_CODEX, claude_global_path=claude_global_path)
    assert global_only_disabled == {'test-rule-a'}, 'a global Claude Code disable should apply with no project config present'

    # get_disabled_rule_ids: project disabledRules adds to the global set (union)
    project_adds_root = tempfile.mkdtemp(prefix='rule-engine-claude-project-adds-')
    write_json(os.path.join(project_adds_root, '.claude', 'ioncache-ai-tools.local.json'), {'disabledRules': ['test-rule-b']})
    project_adds_disabled = get_disabled_rule_ids(project_adds_root, codex_config_path=NO_CODEX, claude_global_path=claude_global_path)
    assert project_adds_disabled == {
        'test-rule-a',
        'test-rule-b',
    }, 'a project-level disable should add to the global set, not replace it'
    shutil.rmtree(project_adds_root, ignore_errors=True)

    # get_disabled_rule_ids: project enabledRules overrides a global disable for that project
    project_overrides_root = tempfile.mkdtemp(prefix='rule-engine-claude-project-overrides-')
    write_json(os.path.join(project_overrides_root, '.claude', 'ioncache-ai-tools.local.json'), {'enabledRules': ['test-rule-a']})
    project_overrides_disabled = get_disabled_rule_ids(
        project_overrides_root, codex_config_path=NO_CODEX, claude_global_path=claude_global_path
    )
    assert (
        project_overrides_disabled == set()
    ), 'a project-level enabledRules entry should re-enable a rule the global config disables, for that project'
    shutil.rmtree(project_overrides_root, ignore_errors=True)
    shutil.rmtree(claude_global_dir, ignore_errors=True)
    shutil.rmtree(no_project_root, ignore_errors=True)

    # These tests parse real TOML via tomllib and expect it to actually
    # work; on Python 3.10 or earlier tomllib is None (guarded import), so
    # get_disabled_rule_ids degrades to an empty set for all of them,
    # failing every assertion below with a confusing, unrelated-looking
    # error instead of a clear skip. The explicit no-tomllib fallback test
    # further below covers that degrade path directly and stays active
    # regardless of which Python this self-check itself runs under.
    codex_project_root = '/tmp/rule-engine-codex-test-project'
    if rule_engine.tomllib is None:
        print('rule-engine self-check: skipping Codex TOML-parsing tests, tomllib unavailable (Python 3.11+ required)')
    else:
        # get_disabled_rule_ids: reads disabled_rules from a Codex config.toml project section
        codex_config_dir = tempfile.mkdtemp(prefix='rule-engine-codex-config-')
        codex_config_path = os.path.join(codex_config_dir, 'config.toml')
        write_text(
            codex_config_path,
            f'[projects."{codex_project_root}"]\ntrust_level = "trusted"\n\n'
            f'[projects."{codex_project_root}".ioncache-ai-tools]\ndisabled_rules = ["test-rule-b"]\n',
        )
        codex_disabled = get_disabled_rule_ids(codex_project_root, codex_config_path=codex_config_path, claude_global_path=NO_CLAUDE_GLOBAL)
        assert codex_disabled == {'test-rule-b'}, 'should read disabled_rules from the Codex config.toml project section'
        shutil.rmtree(codex_config_dir, ignore_errors=True)

        # get_disabled_rule_ids: a non-list Codex disabled_rules value is ignored
        # rather than iterated character by character
        codex_string_shape_dir = tempfile.mkdtemp(prefix='rule-engine-codex-string-shape-')
        codex_string_shape_path = os.path.join(codex_string_shape_dir, 'config.toml')
        write_text(codex_string_shape_path, f'[projects."{codex_project_root}".ioncache-ai-tools]\ndisabled_rules = "test-rule-b"\n')
        codex_string_shape_disabled = get_disabled_rule_ids(
            codex_project_root, codex_config_path=codex_string_shape_path, claude_global_path=NO_CLAUDE_GLOBAL
        )
        assert (
            codex_string_shape_disabled == set()
        ), 'a non-list Codex disabled_rules value should be ignored, not iterated character by character'
        shutil.rmtree(codex_string_shape_dir, ignore_errors=True)

        # get_disabled_rule_ids: malformed Codex TOML degrades to empty and logs
        # to stderr rather than failing silently
        malformed_codex_dir = tempfile.mkdtemp(prefix='rule-engine-malformed-codex-')
        malformed_codex_path = os.path.join(malformed_codex_dir, 'config.toml')
        write_text(malformed_codex_path, 'not valid toml [[[')
        captured_stderr = io.StringIO()
        with contextlib.redirect_stderr(captured_stderr):
            malformed_codex_disabled = get_disabled_rule_ids(
                codex_project_root, codex_config_path=malformed_codex_path, claude_global_path=NO_CLAUDE_GLOBAL
            )
        assert malformed_codex_disabled == set(), 'malformed Codex TOML should degrade to no disabled rules'
        assert captured_stderr.getvalue(), 'a malformed Codex TOML parse failure should be logged, not silently swallowed'
        shutil.rmtree(malformed_codex_dir, ignore_errors=True)

        # get_disabled_rule_ids: a top-level Codex table disables a rule globally, with no project section at all
        codex_global_dir = tempfile.mkdtemp(prefix='rule-engine-codex-global-')
        codex_global_path = os.path.join(codex_global_dir, 'config.toml')
        write_text(codex_global_path, '[ioncache-ai-tools]\ndisabled_rules = ["test-rule-a"]\n')
        codex_global_only_disabled = get_disabled_rule_ids(
            '/tmp/rule-engine-codex-no-project-section', codex_config_path=codex_global_path, claude_global_path=NO_CLAUDE_GLOBAL
        )
        assert codex_global_only_disabled == {'test-rule-a'}, 'a top-level Codex table should disable a rule with no project section present'

        # get_disabled_rule_ids: a Codex project section's disabled_rules adds to the global set (union)
        write_text(
            codex_global_path,
            '[ioncache-ai-tools]\ndisabled_rules = ["test-rule-a"]\n\n'
            f'[projects."{codex_project_root}".ioncache-ai-tools]\ndisabled_rules = ["test-rule-b"]\n',
        )
        codex_project_adds_disabled = get_disabled_rule_ids(
            codex_project_root, codex_config_path=codex_global_path, claude_global_path=NO_CLAUDE_GLOBAL
        )
        assert codex_project_adds_disabled == {
            'test-rule-a',
            'test-rule-b',
        }, 'a Codex project-level disable should add to the global set, not replace it'

        # get_disabled_rule_ids: a Codex project section's enabled_rules overrides a global disable
        write_text(
            codex_global_path,
            '[ioncache-ai-tools]\ndisabled_rules = ["test-rule-a"]\n\n'
            f'[projects."{codex_project_root}".ioncache-ai-tools]\nenabled_rules = ["test-rule-a"]\n',
        )
        codex_project_overrides_disabled = get_disabled_rule_ids(
            codex_project_root, codex_config_path=codex_global_path, claude_global_path=NO_CLAUDE_GLOBAL
        )
        assert (
            codex_project_overrides_disabled == set()
        ), "a Codex project-level enabled_rules entry should re-enable a rule the global table disables, for that project"
        shutil.rmtree(codex_global_dir, ignore_errors=True)

        # get_disabled_rule_ids: both tools present at once union together, not error
        both_project_root = tempfile.mkdtemp(prefix='rule-engine-both-config-')
        write_json(os.path.join(both_project_root, '.claude', 'ioncache-ai-tools.local.json'), {'disabledRules': ['test-rule-a']})
        both_codex_dir = tempfile.mkdtemp(prefix='rule-engine-both-codex-')
        both_codex_path = os.path.join(both_codex_dir, 'config.toml')
        write_text(both_codex_path, f'[projects."{both_project_root}".ioncache-ai-tools]\ndisabled_rules = ["test-rule-b"]\n')
        both_disabled = get_disabled_rule_ids(both_project_root, codex_config_path=both_codex_path, claude_global_path=NO_CLAUDE_GLOBAL)
        assert both_disabled == {'test-rule-a', 'test-rule-b'}, 'both tools present at once should union together, not overwrite or error'
        shutil.rmtree(both_project_root, ignore_errors=True)
        shutil.rmtree(both_codex_dir, ignore_errors=True)

        # get_disabled_rule_ids: respects $CODEX_HOME for the default config path
        # when codex_config_path isn't explicitly overridden
        codex_home_dir = tempfile.mkdtemp(prefix='rule-engine-codex-home-')
        write_text(
            os.path.join(codex_home_dir, 'config.toml'), f'[projects."{codex_project_root}".ioncache-ai-tools]\ndisabled_rules = ["test-rule-c"]\n'
        )
        previous_codex_home = os.environ.get('CODEX_HOME')
        os.environ['CODEX_HOME'] = codex_home_dir
        try:
            codex_home_disabled = get_disabled_rule_ids(codex_project_root, claude_global_path=NO_CLAUDE_GLOBAL)
            assert codex_home_disabled == {
                'test-rule-c'
            }, 'should read config.toml from $CODEX_HOME when set, not the hard-coded ~/.codex default'
        finally:
            if previous_codex_home is None:
                os.environ.pop('CODEX_HOME', None)
            else:
                os.environ['CODEX_HOME'] = previous_codex_home
            shutil.rmtree(codex_home_dir, ignore_errors=True)

    # get_disabled_rule_ids: nothing configured anywhere returns an empty set
    empty_project_root = tempfile.mkdtemp(prefix='rule-engine-no-config-')
    no_config_disabled = get_disabled_rule_ids(empty_project_root, codex_config_path=NO_CODEX, claude_global_path=NO_CLAUDE_GLOBAL)
    assert no_config_disabled == set(), 'no config anywhere should mean no disabled rules'
    shutil.rmtree(empty_project_root, ignore_errors=True)

    # get_disabled_rule_ids: tomllib unavailable (pre-3.11 Python) degrades to
    # no Codex rules disabled instead of crashing the whole engine; module
    # import is guarded specifically so this can't happen before main() runs
    no_tomllib_dir = tempfile.mkdtemp(prefix='rule-engine-no-tomllib-')
    no_tomllib_path = os.path.join(no_tomllib_dir, 'config.toml')
    write_text(no_tomllib_path, '[ioncache-ai-tools]\ndisabled_rules = ["test-rule-a"]\n')
    original_tomllib = rule_engine.tomllib
    rule_engine.tomllib = None
    captured_stderr = io.StringIO()
    with contextlib.redirect_stderr(captured_stderr):
        no_tomllib_disabled = get_disabled_rule_ids(
            '/tmp/rule-engine-no-tomllib-project', codex_config_path=no_tomllib_path, claude_global_path=NO_CLAUDE_GLOBAL
        )
    rule_engine.tomllib = original_tomllib
    assert no_tomllib_disabled == set(), 'a missing tomllib should degrade to no Codex rules disabled, not raise'
    assert 'tomllib unavailable' in captured_stderr.getvalue(), 'the tomllib-unavailable case should be logged, not silent'
    shutil.rmtree(no_tomllib_dir, ignore_errors=True)

    # load_rules_for_event: disabled_rule_ids excludes the matching rule, keeps others
    filter_rules_dir = tempfile.mkdtemp(prefix='rule-engine-filter-')
    with open(os.path.join(filter_rules_dir, 'rule-one.json'), 'w', encoding='utf-8') as f:
        json.dump({'event': 'PreToolUse', 'matcher': {'type': 'always'}, 'action': 'deny', 'message': 'one'}, f)
    with open(os.path.join(filter_rules_dir, 'rule-two.json'), 'w', encoding='utf-8') as f:
        json.dump({'event': 'PreToolUse', 'matcher': {'type': 'always'}, 'action': 'deny', 'message': 'two'}, f)
    filtered_rules = [r['name'] for r in load_rules_for_event(filter_rules_dir, 'PreToolUse', {'rule-one'})]
    assert filtered_rules == ['rule-two.json'], 'a disabled rule id should exclude that rule and keep the other'
    shutil.rmtree(filter_rules_dir, ignore_errors=True)

    # load_rules_for_event: a disabled .py rule is never imported, so its
    # module-level side effects never run
    sentinel_rules_dir = tempfile.mkdtemp(prefix='rule-engine-sentinel-')
    sentinel_path = os.path.join(sentinel_rules_dir, 'sentinel.marker')
    with open(os.path.join(sentinel_rules_dir, 'writes-sentinel.py'), 'w', encoding='utf-8') as f:
        f.write(
            "import pathlib\n"
            f"pathlib.Path({sentinel_path!r}).write_text('imported')\n"
            "EVENT = 'PreToolUse'\n"
            "def matches(hook_input):\n"
            "    return True\n"
        )
    load_rules_for_event(sentinel_rules_dir, 'PreToolUse', {'writes-sentinel'})
    assert not os.path.exists(sentinel_path), 'a disabled .py rule should not be imported at all'
    load_rules_for_event(sentinel_rules_dir, 'PreToolUse', set())
    assert os.path.exists(sentinel_path), 'an enabled .py rule should still be imported normally'
    shutil.rmtree(sentinel_rules_dir, ignore_errors=True)

    # git push agent hook: its `if` filter and authorization judgment live
    # inside Claude Code itself, not in this repo's Python, so they can't be
    # unit-tested here (see README's "accepted false-positive tradeoff"
    # section for the manually-verified command shapes). This assertion is
    # a narrower regression guard: catch an accidental edit to the
    # configured pattern itself, not the matching behavior it produces.
    with open(os.path.join(SCRIPT_DIR, '..', 'hooks.json'), 'r', encoding='utf-8') as f:
        hooks_config = json.load(f)
    git_push_hooks = [
        handler
        for group in hooks_config['hooks']['PreToolUse']
        for handler in group['hooks']
        if handler.get('type') == 'agent'
    ]
    assert len(git_push_hooks) == 1, 'expected exactly one agent-type PreToolUse hook (the git push authorization hook)'
    assert git_push_hooks[0]['if'] == 'Bash(*git*push*)', 'git push agent hook if-filter changed unexpectedly'

    print('All rule-engine self-checks passed.')


if __name__ == '__main__':
    main()
