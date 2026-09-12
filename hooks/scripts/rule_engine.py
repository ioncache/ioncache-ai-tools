#!/usr/bin/env python3
"""Generic hook rule engine. See
docs/superpowers/specs/2026-09-04-generic-rule-engine-design.md

Python, not Node: this engine needs to read Codex's config.toml, and
Python's stdlib has a real TOML parser (tomllib, 3.11+) where Node has
none. An earlier version of this engine was JS and shelled out to a
python3 subprocess just for that one need; that cross-language subprocess
call (with its own timeout/error-surface problems) is worse than just
writing the whole engine in the language that has the parser natively.
"""
import importlib.util
import json
import os
import re
import signal
import sys
import tomllib

RULES_DIRNAME = 'rules'
CLAUDE_LOCAL_CONFIG = os.path.join('.claude', 'ioncache-ai-tools.local.json')
DEFAULT_CODEX_HOME = os.path.join(os.path.expanduser('~'), '.codex')
HANG_TIMEOUT_SECONDS = 5


def get_field(obj, dot_path):
    value = obj
    for key in dot_path.split('.'):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def tool_name_matches(rule, hook_input):
    tool_names = rule.get('toolNames')
    if not tool_names:
        return True
    return hook_input.get('tool_name') in tool_names


# Bash removes a backslash before a character and strips matching quotes
# before command lookup, so `\kill`, `k\ill`, and `'kill'` all execute
# plain `kill`. This normalizes those forms before a regex rule sees the
# command, so a rule doesn't have to special-case them itself. Meant for
# Bash's own command field: normalizing an unrelated tool input field
# (e.g. Write content) would apply shell semantics where none exist.
#
# This tracks single-quote state because Bash treats everything inside
# single quotes as fully literal: no backslash-escaping, no nested-quote
# closing, no line continuation. A naive "strip every backslash and every
# quote character" pass doesn't track that, so `git commit -m "note about
# 'kill'"` gets every quote stripped instead of just the outer, real
# delimiters, and `echo '\kill'` (a literal 6-character string, since
# backslash isn't special in single quotes) gets its backslash stripped
# into a false match. Double-quote content isn't tracked separately from
# unquoted text here, since for this rule's purposes ("does a guarded
# word appear as its own token") the only behavior that actually needs to
# differ is single-quote literalness.
#
# Known residual gap (not fixed here): stripping quote delimiters also
# exposes any boundary-class character (e.g. `|`) that was safely inside
# the quotes, so `grep "kill|pkill|killall" file` can still false-match a
# boundary-anchored regex looking for `kill`. Closing that fully means
# real shell tokenization, not a flat-text normalization pass.
def normalize_shell_command(command):
    result = []
    quote = None  # None | "'" | '"'
    i = 0
    n = len(command)
    while i < n:
        ch = command[i]
        if ch == '\\' and quote != "'":
            nxt = command[i + 1] if i + 1 < n else None
            if nxt == '\n':
                i += 2  # line continuation: Bash splices these away entirely
                continue
            if nxt is not None:
                result.append(nxt)
                i += 2
                continue
        if ch in ("'", '"') and (quote is None or quote == ch):
            quote = None if quote == ch else ch
            i += 1
            continue
        result.append(ch)
        i += 1
    return ''.join(result)


def match_rule(rule, hook_input):
    if not tool_name_matches(rule, hook_input):
        return False
    matches_fn = rule.get('matches')
    if callable(matches_fn):
        return bool(matches_fn(hook_input))
    matcher = rule.get('matcher') or {}
    if matcher.get('type') == 'always':
        return True
    if matcher.get('type') == 'regex':
        value = get_field(hook_input, matcher.get('field', ''))
        if not isinstance(value, str):
            return False
        if hook_input.get('tool_name') == 'Bash' and matcher.get('field') == 'tool_input.command':
            value = normalize_shell_command(value)
        return re.search(matcher['pattern'], value) is not None
    return False


def resolve_action(rule, hook_input):
    check_fn = rule.get('check')
    if callable(check_fn):
        return check_fn(hook_input)
    if rule.get('action') == 'deny':
        return {'action': 'deny', 'message': rule.get('message')}
    if rule.get('action') == 'inject':
        return {'action': 'inject', 'message': rule.get('message')}
    return None


def merge_pre_tool_use(results):
    deny = next((r for r in results if r and r.get('action') == 'deny'), None)
    if deny:
        return {
            'hookSpecificOutput': {
                'hookEventName': 'PreToolUse',
                'permissionDecision': 'deny',
                'permissionDecisionReason': deny.get('message'),
            }
        }
    rewrites = [r for r in results if r and r.get('action') == 'rewrite']
    if len(rewrites) > 1:
        print(
            f'rule-engine: {len(rewrites)} rules returned a rewrite for the same event; '
            "only the first is applied, the rest are silently dropped (see spec's known limitation)",
            file=sys.stderr,
        )
    rewrite = rewrites[0] if rewrites else None
    if rewrite:
        return {
            'hookSpecificOutput': {
                'hookEventName': 'PreToolUse',
                'permissionDecision': 'allow',
                'updatedInput': rewrite.get('updatedInput'),
            },
            'systemMessage': rewrite.get('systemMessage'),
        }
    return None


def merge_user_prompt_submit(results):
    messages = [r['message'] for r in results if r and r.get('action') == 'inject']
    if not messages:
        return None
    return {'additionalContext': '\n\n'.join(messages)}


def _validated_result(result, rule_name):
    """A scripted rule's check() is arbitrary code; it can return
    anything, not just the {action, message/updatedInput} shape the
    merge functions expect. Validating here, inside the same per-rule
    try/except resolve_action already runs in, means a malformed result
    from one rule degrades to "no action from this rule" instead of
    raising inside merge_pre_tool_use/merge_user_prompt_submit, outside
    any per-rule boundary, where it would silently drop every other
    rule's valid results too (main()'s broad except swallows it).
    """
    if result is None:
        return None
    if not isinstance(result, dict):
        print(f'rule-engine: rule "{rule_name}" returned a non-dict result, ignoring it', file=sys.stderr)
        return None
    if result.get('action') == 'inject' and not isinstance(result.get('message'), str):
        print(f'rule-engine: rule "{rule_name}" returned an inject action with a non-string message, ignoring it', file=sys.stderr)
        return None
    return result


def run_rules(rules, event, hook_input):
    matched = []
    for rule in rules:
        try:
            if match_rule(rule, hook_input):
                matched.append(rule)
        except Exception as err:
            print(f'rule-engine: matcher threw for rule "{rule.get("name", "unknown")}": {err}', file=sys.stderr)

    results = []
    for rule in matched:
        try:
            result = resolve_action(rule, hook_input)
            results.append(_validated_result(result, rule.get('name', 'unknown')))
        except Exception as err:
            print(f'rule-engine: check threw for rule "{rule.get("name", "unknown")}": {err}', file=sys.stderr)
            results.append(None)

    if event == 'PreToolUse':
        return merge_pre_tool_use(results)
    if event == 'UserPromptSubmit':
        return merge_user_prompt_submit(results)
    return None


def _load_python_rule(full_path):
    spec = importlib.util.spec_from_file_location(f'rule_{os.path.basename(full_path)}', full_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {
        'event': getattr(module, 'EVENT', None),
        'toolNames': getattr(module, 'TOOL_NAMES', None),
        'matches': getattr(module, 'matches', None),
        'check': getattr(module, 'check', None),
        'action': getattr(module, 'ACTION', None),
        'message': getattr(module, 'MESSAGE', None),
    }


def load_rule_file(rules_dir, name):
    full_path = os.path.join(rules_dir, name)
    try:
        if name.endswith('.json'):
            with open(full_path, 'r', encoding='utf-8') as f:
                rule = json.load(f)
        else:
            rule = _load_python_rule(full_path)
        rule = dict(rule)
        rule['name'] = name
        return rule
    except Exception as err:
        print(f'rule-engine: skipping rule file "{name}": {err}', file=sys.stderr)
        return None


def _as_rule_list(value):
    return value if isinstance(value, list) else []


def get_disabled_rule_ids(project_root, codex_config_path=None, claude_global_path=None):
    """Global config sets the baseline; project-level config overrides it
    per rule, in either direction. A project can force-disable a rule the
    global config leaves enabled (add it to that scope's disabledRules), or
    force-enable one the global config disables (add it to the project
    scope's enabledRules). Global-only config has no equivalent
    enabledRules: with nothing disabled globally, every rule already runs,
    so there is nothing for a global enabledRules to override.
    """
    if codex_config_path is None:
        codex_home = os.environ.get('CODEX_HOME') or DEFAULT_CODEX_HOME
        codex_config_path = os.path.join(codex_home, 'config.toml')
    if claude_global_path is None:
        claude_global_path = os.path.join(os.path.expanduser('~'), CLAUDE_LOCAL_CONFIG)

    disabled = set()

    # Claude Code: two separate files, one per scope.
    claude_project_path = os.path.join(project_root, CLAUDE_LOCAL_CONFIG)
    claude_disabled = set()
    if os.path.exists(claude_global_path):
        try:
            with open(claude_global_path, 'r', encoding='utf-8') as f:
                claude_disabled.update(_as_rule_list(json.load(f).get('disabledRules')))
        except Exception as err:
            print(f'rule-engine: failed to read {claude_global_path}: {err}', file=sys.stderr)
    if os.path.exists(claude_project_path):
        try:
            with open(claude_project_path, 'r', encoding='utf-8') as f:
                project_config = json.load(f)
            claude_disabled.update(_as_rule_list(project_config.get('disabledRules')))
            claude_disabled -= set(_as_rule_list(project_config.get('enabledRules')))
        except Exception as err:
            print(f'rule-engine: failed to read {claude_project_path}: {err}', file=sys.stderr)
    disabled.update(claude_disabled)

    # Codex: one file, both scopes live in it as different tables.
    if os.path.exists(codex_config_path):
        try:
            with open(codex_config_path, 'rb') as f:
                codex_config = tomllib.load(f)
        except Exception as err:
            print(f'rule-engine: failed to read {codex_config_path}: {err}', file=sys.stderr)
            codex_config = None
        if codex_config is not None:
            codex_disabled = set(_as_rule_list(codex_config.get('ioncache-ai-tools', {}).get('disabled_rules')))
            project_section = codex_config.get('projects', {}).get(project_root, {}).get('ioncache-ai-tools', {})
            codex_disabled.update(_as_rule_list(project_section.get('disabled_rules')))
            codex_disabled -= set(_as_rule_list(project_section.get('enabled_rules')))
            disabled.update(codex_disabled)

    return disabled


def load_rules_for_event(rules_dir, event, disabled_rule_ids=None):
    disabled_rule_ids = disabled_rule_ids or set()
    if not os.path.isdir(rules_dir):
        return []
    rules = []
    for name in sorted(os.listdir(rules_dir)):
        if not (name.endswith('.json') or name.endswith('.py')):
            continue
        # Compute and check the disabled-id before load_rule_file, which
        # imports and executes a .py rule's module-level code. Checking
        # after loading meant a "disabled" rule still ran on every
        # invocation, its own top-level side effects (or a hang, caught
        # only by the full watchdog timeout) happened regardless of
        # whether the rule was ever actually used.
        rule_id = os.path.splitext(name)[0]
        if rule_id in disabled_rule_ids:
            continue
        rule = load_rule_file(rules_dir, name)
        if rule is None or rule.get('event') != event:
            continue
        rules.append(rule)
    return rules


def run_hook(override_rules_dir=None):
    event = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        hook_input = json.loads(sys.stdin.read())
    except Exception:
        return None

    script_dir = os.path.dirname(os.path.abspath(__file__))
    rules_dir = override_rules_dir or os.path.join(script_dir, '..', RULES_DIRNAME)
    disabled_rule_ids = get_disabled_rule_ids(os.getcwd())
    try:
        rules = load_rules_for_event(rules_dir, event, disabled_rule_ids)
    except Exception as err:
        print(f'rule-engine: failed to load rules from {rules_dir}: {err}', file=sys.stderr)
        rules = []

    return run_rules(rules, event, hook_input)


def _handle_alarm(signum, frame):
    # A scripted rule's check() that never returns (e.g. a blocking call
    # with no timeout) would otherwise keep this process alive forever,
    # since nothing else forces exit. This fires regardless of what
    # run_hook() is doing, including inside a blocking C call, unlike a
    # single-threaded async watchdog that can't preempt synchronous work.
    sys.exit(0)


def main():
    signal.signal(signal.SIGALRM, _handle_alarm)
    signal.alarm(HANG_TIMEOUT_SECONDS)
    try:
        output = run_hook()
        if output:
            print(json.dumps(output))
    except Exception:
        pass
    finally:
        signal.alarm(0)
    sys.exit(0)


if __name__ == '__main__':
    main()
