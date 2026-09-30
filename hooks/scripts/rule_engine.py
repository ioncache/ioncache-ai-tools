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
import shlex
import signal
import sys

from hook_adapter_common import PATCH_REWRITE_REASON, patch_inputs

try:
    import tomllib
except ImportError:
    tomllib = None

RULES_DIRNAME = 'rules'
CLAUDE_LOCAL_CONFIG = os.path.join('.claude', 'ioncache-ai-tools.local.json')
COPILOT_LOCAL_CONFIG = os.path.join('.github', 'copilot', 'ioncache-ai-tools.local.json')
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


# Shell control operators that separate one simple command from the next
# within a compound Bash command (`a; b`, `a && b`, `a | b`, ...). Used by
# rules that need to know "is this token in command position" rather than
# just "does this text appear somewhere in the command", something a flat
# regex over the whole string can't express: `ls /tmp/kill` and
# `printf x > out && cat package-lock.json` both contain a guarded word or
# filename, but neither actually invokes or mutates it.
# A newline separates two commands exactly as `;` does, so it belongs in
# this set. Without it a multi-line script collapses into a single
# "command" whose first word is whatever came first (often `cd`), and
# every rule asking "what is actually being invoked here" reads the wrong
# answer for every line but the first.
CONTROL_OPERATORS = {';', '&&', '||', '|', '&', '(', ')', '\n'}


# shlex's own punctuation set plus the newline. Newline has to be listed
# as punctuation rather than split off the raw string beforehand, because
# only the lexer knows whether a given newline is a separator or an
# ordinary character inside a quoted argument: pre-splitting the text
# turns `printf 'a\ngit commit\nb'` into three "commands", one of which
# looks exactly like a real commit.
SHELL_PUNCTUATION = '();<>|&\n'
SHELL_FRAGMENTS = re.compile(r"""('(?:[^']*)'|"(?:\\[\s\S]|[^"\\])*"|\\[\s\S])|([();<>|&\n]+)""")
SHELL_OPERATORS = re.compile(r'\(\(|\)\)|&>>|<<<|<<-|&&|\|\||>>|<<|>&|<&|<>|>\||&>|[();<>|&\n]')


def _space_shell_operators(match):
    if match[1] is not None:
        return match[0]
    return ' ' + ' '.join(SHELL_OPERATORS.findall(match[2])) + ' '


def tokenize_command(command):
    """Splits a Bash command into real shell tokens: quoting and
    backslash-escaping are resolved the way Bash itself resolves them
    (shlex's posix mode), and control operators (;, &&, ||, |, &, (, ))
    come out as their own tokens instead of being glued to an adjacent
    word (shlex's punctuation_chars mode). A newline is one of those
    operators, so newline is removed from the lexer's whitespace set and
    added to its punctuation set. Falls back to a plain whitespace split
    on unbalanced quoting rather than raising, since a hook must never
    throw on attacker- or mistake-controlled input; that fallback loses
    newline separation, which is acceptable for an input already too
    malformed to lex.

    Known, accepted gap: a heredoc body is not opaque to the lexer, so
    `cat <<EOF` followed by a line reading `git push` yields tokens that
    look like a real invocation. Closing that means tracking heredoc
    state, which is a real shell parser rather than a lexer.

    Bash splices a backslash immediately before a newline away entirely
    (line continuation), joining the two lines before it even starts
    tokenizing; shlex does not do this on its own; it just escapes the
    newline character literally into the token, so it's spliced here
    first. This also splices inside a single-quoted string, where real
    Bash would keep the backslash-newline literal, an accepted gap for
    a case this narrow.
    """
    command = command.replace('\\\n', '')
    # shlex groups adjacent punctuation; separate actual operators before
    # lexing, while leaving quoted and escaped fragments untouched.
    command = SHELL_FRAGMENTS.sub(_space_shell_operators, command)
    lexer = shlex.shlex(command, posix=True, punctuation_chars=SHELL_PUNCTUATION)
    lexer.whitespace_split = True
    lexer.whitespace = ' \t\r'
    try:
        return list(lexer)
    except ValueError:
        return command.split()


def split_into_simple_commands(tokens):
    """Splits a token list into one list per simple command, cutting at
    each control operator. `a && b; c` becomes [[a], [b], [c]].
    """
    commands = []
    current = []
    for token in tokens:
        if token in CONTROL_OPERATORS:
            if current:
                commands.append(current)
            current = []
            continue
        current.append(token)
    if current:
        commands.append(current)
    return commands


# Wrapper commands that run their own argument as the actual command, so
# a guarded word behind one of these is still the thing actually invoked
# (`timeout 5 kill -9 1234` really does run kill). Matches the wrapper
# set Claude Code's own permissions.deny documents stripping for the
# same reason. NO_ARG_WRAPPERS handles the bare-invocation case (no
# flags of their own: `nice kill`, `nohup kill`), by skipping exactly
# the wrapper token; `timeout` is special-cased since its own first
# argument is a mandatory duration, not part of the wrapped command.
# Invoked WITH their own flags (`nice -n 10 kill`, `stdbuf -o0 kill`),
# these wrappers are not recognized: their flags can take a value of
# their own, and telling a flag from its value needs per-wrapper
# knowledge, real scope beyond what this covers, and stays a known,
# accepted gap.
NO_ARG_WRAPPERS = {'nohup', 'command', 'builtin', 'nice', 'time', 'stdbuf'}
DURATION_ARG_WRAPPERS = {'timeout'}


def skip_wrappers(simple_command):
    """Returns the simple command's tokens starting from its actual
    executable, past any recognized wrapper commands.
    """
    i = 0
    n = len(simple_command)
    while i < n:
        name = os.path.basename(simple_command[i])
        if name in NO_ARG_WRAPPERS:
            i += 1
            continue
        if name in DURATION_ARG_WRAPPERS and i + 1 < n:
            i += 2
            continue
        break
    return simple_command[i:]


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
                'updatedInput': rewrite.get('updatedInput'),
            },
            'systemMessage': rewrite.get('systemMessage'),
        }
    return None


def merge_user_prompt_submit(results):
    messages = [r['message'] for r in results if r and r.get('action') == 'inject']
    if not messages:
        return None
    return {
        'hookSpecificOutput': {
            'hookEventName': 'UserPromptSubmit',
            'additionalContext': '\n\n'.join(messages),
        }
    }


def _validated_result(result, rule_name):
    """A scripted rule's check() is arbitrary code; it can return
    anything, not just the {action, message/updatedInput} shape the
    merge functions expect. Validating here, inside the same per-rule
    try/except resolve_action already runs in, means a malformed result
    from one rule degrades to "no action from this rule" instead of
    raising inside merge_pre_tool_use/merge_user_prompt_submit, outside
    any per-rule boundary, where it would prevent every other rule's
    valid results from being returned.
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
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError('rule IDs must be a list of strings')
    return value


def _config_table(config, key):
    value = config.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f'config section {key!r} must be a table')
    return value


def _codex_disabled_rule_ids(config_path, project_root):
    try:
        with open(config_path, 'rb') as file:
            config = tomllib.load(file)
        global_section = _config_table(config, 'ioncache-ai-tools')
        project = _config_table(_config_table(config, 'projects'), project_root)
        local_section = _config_table(project, 'ioncache-ai-tools')
        disabled = set(_as_rule_list(global_section.get('disabled_rules')))
        disabled.update(_as_rule_list(local_section.get('disabled_rules')))
        return disabled - set(_as_rule_list(local_section.get('enabled_rules')))
    except (OSError, ValueError, TypeError) as err:
        print(f'rule-engine: failed to read {config_path}: {err}', file=sys.stderr)
        return set()


def _json_disabled_rule_ids(global_path, project_path):
    disabled = set()
    for config_path, is_project in ((global_path, False), (project_path, True)):
        if not os.path.exists(config_path):
            continue
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            disabled.update(_as_rule_list(config.get('disabledRules')))
            if is_project:
                disabled -= set(_as_rule_list(config.get('enabledRules')))
        except Exception as err:
            print(f'rule-engine: failed to read {config_path}: {err}', file=sys.stderr)
    return disabled


def get_disabled_rule_ids(project_root, codex_config_path=None, claude_global_path=None, copilot_global_path=None):
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
    if copilot_global_path is None:
        copilot_home = os.environ.get('COPILOT_HOME') or os.path.expanduser('~/.copilot')
        copilot_global_path = os.path.join(copilot_home, 'ioncache-ai-tools.local.json')

    disabled = set()

    # Claude Code and Copilot: separate files for global and project scope.
    disabled.update(_json_disabled_rule_ids(
        claude_global_path, os.path.join(project_root, CLAUDE_LOCAL_CONFIG),
    ))
    disabled.update(_json_disabled_rule_ids(
        copilot_global_path, os.path.join(project_root, COPILOT_LOCAL_CONFIG),
    ))

    # Codex: one file, both scopes live in it as different tables.
    if tomllib is None and os.path.exists(codex_config_path):
        print(
            f'rule-engine: tomllib unavailable (Python 3.11+ required), skipping Codex config at {codex_config_path}',
            file=sys.stderr,
        )
    elif os.path.exists(codex_config_path):
        disabled.update(_codex_disabled_rule_ids(codex_config_path, project_root))

    return disabled


def load_rules_for_event(rules_dir, event, disabled_rule_ids=None):
    """Return enabled rules for an event in filename order.

    Use this to evaluate a rule directory for ``PreToolUse`` or
    ``UserPromptSubmit``. For example, to omit a rule for one evaluation:
    ``load_rules_for_event('hooks/rules', 'PreToolUse', {'fix_emdash'})``.
    Disabled IDs are filenames without extensions; disabled Python rules
    are not imported. Other Python rule files may execute module-level code.

    An empty directory or no enabled rules for the event returns an empty
    list. An individual invalid rule is logged and skipped. An unavailable
    directory raises OSError, including FileNotFoundError,
    NotADirectoryError, or PermissionError; callers must not treat that as
    a successful evaluation with no applicable rules.
    """
    disabled_rule_ids = disabled_rule_ids or set()
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


def run_patch_rules(rules, hook_input):
    rewrite_needed = False
    patch = hook_input['tool_input']['command']
    for item in patch_inputs(patch):
        output = run_rules(rules, 'PreToolUse', {
            **hook_input, 'tool_name': 'Edit', 'tool_input': item,
        })
        decision = (output or {}).get('hookSpecificOutput', {})
        if decision.get('permissionDecision') == 'deny':
            return output
        rewrite_needed |= 'updatedInput' in decision
    if rewrite_needed:
        return merge_pre_tool_use([{'action': 'deny', 'message': PATCH_REWRITE_REASON}])
    return None


def run_hook(override_rules_dir=None):
    """Evaluate a shared hook request, returning a decision or no action.

    Supply the event as the first command-line argument and a JSON object
    on stdin. Prompt requests use ``prompt``; tool requests use
    ``tool_name`` and ``tool_input``. None means no rule action, not an
    explicit permission grant. Diagnostics go to stderr.

    Rules default to the bundled directory. Pass ``override_rules_dir``
    when evaluating a separate rule directory, such as a test fixture.
    Configuration is resolved for the process working directory.
    Discovery errors propagate to the caller; individual rule errors
    remain isolated. Invalid JSON currently returns None.
    """
    event = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        hook_input = json.loads(sys.stdin.read())
    except Exception:
        return None

    script_dir = os.path.dirname(os.path.abspath(__file__))
    rules_dir = override_rules_dir or os.path.join(script_dir, '..', RULES_DIRNAME)
    disabled_rule_ids = get_disabled_rule_ids(os.getcwd())
    rules = load_rules_for_event(rules_dir, event, disabled_rule_ids)

    if event == 'PreToolUse' and hook_input.get('tool_name') == 'apply_patch':
        return run_patch_rules(rules, hook_input)
    return run_rules(rules, event, hook_input)


def _handle_alarm(signum, frame):
    # A scripted rule's check() that never returns (e.g. a blocking call
    # with no timeout) would otherwise keep this process alive forever,
    # since nothing else forces exit. This fires regardless of what
    # run_hook() is doing, including inside a blocking C call, unlike a
    # single-threaded async watchdog that can't preempt synchronous work.
    print('rule-engine: evaluation exceeded the five-second deadline', file=sys.stderr)
    sys.exit(2)


def main():
    """Serve one shared hook request over stdin/stdout, then exit.

    Call as ``python3 hooks/scripts/rule_engine.py PreToolUse`` with a
    JSON payload on stdin, or use ``UserPromptSubmit`` for reminders.
    A policy denial is a successful evaluation: exit 0 with a JSON
    decision. No action produces no stdout. Unhandled engine failures,
    including rule-discovery failures, and watchdog expiry log to stderr
    and exit 2 rather than reporting successful evaluation.
    """
    signal.signal(signal.SIGALRM, _handle_alarm)
    signal.alarm(HANG_TIMEOUT_SECONDS)
    try:
        output = run_hook()
        if output:
            print(json.dumps(output))
    except Exception as err:
        print(f'rule-engine: evaluation failed: {err}', file=sys.stderr)
        sys.exit(2)
    finally:
        signal.alarm(0)
    sys.exit(0)


if __name__ == '__main__':
    main()
