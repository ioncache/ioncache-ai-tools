#!/usr/bin/env python3
"""Self-check for question classification, state recording, and blocked tools.

Run: python3 hooks/scripts/pending_question_self_check.py < /dev/null

Question fixtures include real session messages, recorded host batches, and
synthetic boundary cases. Long unpunctuated questions intentionally fail open:
declarative report text must not fence an unattended worker.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import uuid
import pytest

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from classify_question import QUESTION_CONTRACT, has_question  # noqa: E402
from block_pending_question import WORK_CONTROL_TOOLS, is_mutating, is_question_blocked  # noqa: E402
import block_pending_question
import guidance

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "tests"))
from self_check_support import run_main

RECORDED_CLAUDE = json.loads(
    (pathlib.Path(SCRIPT_DIR).parent / 'fixtures/claude-batched-prompts.json').read_text()
)
CLAUDE_BATCH = '\n'.join(RECORDED_CLAUDE[key] for key in RECORDED_CLAUDE['entry_419_blocks'])

# (message, expected has_question() result, note).
QUESTION_FIXTURES = [
    # Real unpunctuated questions, including deliberate conservative misses.
    (
        'why is the pr body written like this" Two new broadcast email templates need to go out '
        'to two distinct audiences, and bin/send-notifications.js had no way to target anything '
        'narrower than "the entire registered base" (plus a single-member test mode). This adds a '
        '--recipients CSV option so an operator can send to exactly the members named in a file.\n\n\n'
        'why are we mentioning 2 audiences, you are being very very specific here\n\n'
        "this pr is generic, it doesn't need to know aobgut 2 new audiences",
        False,
        'long multi-clause question now deliberately fails open without ?',
    ),
    ('what is the currebt session id', True, 'real question, typo, no ?'),
    ('what is DIGITALOCEAN_ACCESS_TOKEN', True, 'real question, no ?'),
    ('did you oush tge cgabgtes/.', False, 'period-ended text no longer counts by starter alone'),
    ("which agent is doing the work right now,. I don't see them in the agent list", False, 'multiple sentences without ?'),
    ('where is the list of previouslt created users', True, 'real question, typo, no ?'),
    ('how do I do this: Create a 20%-off promotion code in Stripe, then apply it at checkout.', False, 'multi-clause, period-ended text'),
    ('what do you mean "For sale"  we are not using that term ever', False, 'long prompt without ?'),
    ('what is the epiry of booking links', True, 'real question, typo, no ?'),
    ('what worktree was thjis in', True, 'real question, typo, no ?'),
    # Real questions that already had "?" (regression: worked before too).
    ('why did you say this? `The three commits remain local and unpushed.`', True, 'already had ?'),
    ('ok what is left on this PR to fix?', True, 'already had ?'),
    (
        'ok back to this PR, does the email broadcast code automatically use the correct '
        'languatge when sending out emails?',
        True,
        'already had ?',
    ),
    # Real non-questions, including interrogative-word-led imperatives.
    (
        "you are never allowed to push unless I explcitly tell you in a prompt.  that instruction "
        "would then only be valid for that 1 prompt and no other.  so telling me that you didn't "
        "push is meaningless so you would not have been allwoed to push.  it'sa  waste of time",
        False,
        'statement/correction, no interrogative opener',
    ),
    (
        'do not do a follow up pr pass, this is all part of the same pr, just add the issues we '
        'found int he the issue list, with description and example',
        False,
        'imperative opening with bare "do"; this is why bare "do" is excluded from QUESTION_STARTERS',
    ),
    (
        'do not use rapid relief, it does not exist anymore\n\nwe have 3 options now on first '
        'sign up:\n\ncomplete care\nhealthy weight\ninitial menopause consultation',
        False,
        'imperative opening with bare "do"',
    ),
    (
        'we are NOT writing our own csv parser.  ever.  even for a simple one.  that is out, stop '
        'suggesting it.  never ever suggest it again',
        False,
        'statement, no interrogative opener',
    ),
    ('update the PR body', False, 'imperative, no interrogative opener'),
    ('ok fix cor1/cpx2/cpx3/cpx4, separate commits for each', False, 'imperative, no interrogative opener'),
    (
        'no, please go resolve those threads if they are fixed, you can definitely do this',
        False,
        'encouragement/instruction, opens with "no"',
    ),
    (
        'give me a prompt I can take to another session that describes the issue and how to fix '
        'it, with suggestions of improvments',
        False,
        'imperative request, no interrogative opener',
    ),
    # Previously accepted false positives are unsafe for unattended workers.
    (
        "when you use references to steps or other parts of the document, ALWAYS use links to "
        "that section.  if that seciton isn't using a header of some sort that is linkable, "
        "change the format",
        False,
        'conditional instruction opening with "when"',
    ),
    (
        "what I want is an instruction telling it to NEVER use it's training data ever",
        False,
        'declarative "what I want is X" opening with "what"',
    ),
    (
        "ok I've just updated the ioncache-ai-tools plugin.  there is a new "
        '/ioncache-ai-tools:autonomous-development skill in it.  is there a good github issue '
        'we could use to test it?',
        True,
        'real question answered by writing a plan and run manifest in the same turn',
    ),
    (
        'but I told you to finish.  that is part of the skil. you wer supposed to finish it.  put '
        "up the pr and finish the work.  and what do you mean the hjelper won't run?",
        True,
        'accepted over-block: a mixed instruction and question stays answer-only until resubmitted',
    ),
    (
        'ok this is broken in the skill too, it is supposed to use a generic location',
        False,
        'known gap: feedback without a question form is not answer-only',
    ),
    ("when it's turned on, the review skill should automatically post comments", False, 'conditional feature request'),
    ("when it's turned on, the review skill should automatically post comments to the PR in the appropriate places",
     False, 'original conditional feature request'),
    ('were supposed to remove the scope guard, not remove all the functionality.', False, 'declarative correction'),
    ('When CI passes, merge the PR.', False, 'conditional instruction, not a question'),
    ('When the marker is unsafe, the `ValueError` escapes `run_hook`', False, 'unpunctuated declarative report'),
    ('why the fuck, why the fuck!!!!!', True, 'emphatic repetition of one short question'),
    ('why the fuck, why the fuck, why the fuck!!!!!', True, 'recorded repeated short question'),
    ('how do I fix this', True, 'short unpunctuated question'),
    ('The check finished. How the marker clears is explained below.', False, 'declarative sentence inside prose'),
    ('The check finished.\nWhy did it fail?', True, 'a question-mark clause inside prose still counts'),
    ('why did it fail; fix it', False, 'multiple clauses without ?'),
    ('Why did it fail! How do I fix it', False, 'multiple sentences without ?'),
    (RECORDED_CLAUDE['handback'], False, 'recorded standalone hand-back with a When clause'),
    (CLAUDE_BATCH, False, 'recorded entry 419 reminder, notification and hand-back without ?'),
]

# (tool_name, tool_input, expected is_mutating() result, note)
MUTATION_FIXTURES = [
    ('Edit', {}, True, 'Edit is always mutating'),
    ('Write', {}, True, 'Write is always mutating'),
    ('NotebookEdit', {}, True, 'NotebookEdit is always mutating'),
    ('MultiEdit', {}, True, 'MultiEdit is always mutating'),
    ('Read', {}, False, 'Read is never in ALWAYS_MUTATING_TOOLS'),
    ('mcp__issue-server__create-issue', {}, True, 'hyphens within a canonical MCP operation'),
    ('mcp__files__delete-file', {}, True, 'hyphenated MCP deletion'),
    ('mcp__files__update_file', {}, True, 'underscored MCP mutation'),
    ('mcp__files__write.file', {}, True, 'dotted MCP operation'),
    ('mcp.files.write_file', {}, True, 'legacy dotted MCP namespace'),
    ('mcp-files-write_file', {}, True, 'legacy hyphenated MCP namespace'),
    ('mcp__github__createIssue', {}, True, 'camelCase MCP mutation'),
    ('mcp__github__CreateIssue', {}, True, 'PascalCase MCP mutation'),
    ('mcp__files__UPDATE_FILE', {}, True, 'upper-case MCP mutation'),
    ('mcp__users__getUser', {}, False, 'camelCase read-only MCP operation'),
    ('mcp__srv__updateable', {}, False, 'a verb prefix without a word boundary'),
    ('mcp__srv__getLatestUpdate', {}, False, 'a camelCase read-only operation ending in Update'),
    ('mcp__create-server__get-issue', {}, False, 'server name does not authorize mutation classification'),
    ('mcp__files__get-update-status', {}, False, 'a mutation word inside a read-only operation'),
    ('mcp__srv__get-latest-update', {}, False, 'a read-only operation ending in update'),
    ('mcp__srv__get-last-push', {}, False, 'a read-only operation ending in push'),
    ('mcp__srv__preview.delete', {}, False, 'a dotted operation is not a namespace'),
    ('Bash', {'command': 'git commit -m msg'}, True, 'git commit'),
    ('Bash', {'command': 'git push'}, True, 'git push'),
    ('Bash', {'command': 'git checkout -- tracked.txt'}, True, 'checkout restores tracked content'),
    ('Bash', {'command': 'git branch -D old-branch'}, True, 'branch deletion stays blocked'),
    ('Bash', {'command': 'git clean -fd'}, True, 'clean flags stay blocked'),
    ('Bash', {'command': "grep -n 'git commit' README.md"}, False, 'mutation words in search arguments'),
    ('Bash', {'command': 'ls ./tee'}, False, 'a filename is not an executable'),
    ('Bash', {'command': "git log --grep='git commit'"}, False, 'read-only git arguments'),
    ('Bash', {'command': "git 'commit -m example'"}, False, 'a quoted argument is not multiple subcommand words'),
    ('Bash', {'command': "printf '%s' 'rm file; git push'"}, False, 'quoted compound command text'),
    ('Bash', {'command': "grep 'git commit' README.md && git push"}, True, 'real mutation after a read'),
    ('Bash', {'command': "grep 'git commit' README.md | tee result.txt"}, True, 'real tee in a pipeline'),
    ('Bash', {'command': 'timeout 5 /usr/bin/git checkout -- tracked.txt'}, True, 'wrapped executable path'),
    ('Bash', {'command': 'if true; then git push; fi'}, True, 'mutation in a conditional'),
    ('Bash', {'command': 'LABEL=example git commit -m msg'}, True, 'assignment before executable'),
    ('Bash', {'command': 'env LABEL=example git push'}, True, 'environment wrapper'),
    ('Bash', {'command': 'env -i git reset --hard'}, True, 'env options before a mutation'),
    ('Bash', {'command': '/usr/bin/env --ignore-environment LABEL=example git push'},
     True, 'env executable path, long option, and assignment'),
    ('Bash', {'command': 'env -u LABEL -- git push'}, True, 'env option argument and terminator'),
    ('Bash', {'command': 'env --unset=LABEL timeout 5 git push'}, True, 'nested wrapper after env'),
    ('Bash', {'command': "env -i git log --grep='git commit'"}, False, 'read-only env command'),
    ('Bash', {'command': "env -u 'git push' cat README.md"}, False, 'env option value is not a command'),
    ('Bash', {'command': "env -i LABEL='git push'"}, False, 'env without an executable'),
    ('Bash', {'command': """env -i gh api graphql -f 'query=mutation { x }'"""},
     True, 'GraphQL mutation behind env'),
    ('Bash', {'command': """env -i gh api graphql -f 'query=query { viewer { login } }'"""},
     False, 'GraphQL query behind env'),
    ('Bash', {'command': '2>/dev/null git push'}, True, 'redirection before executable'),
    ('Bash', {'command': """gh api graphql -f 'query=query { repository(name: "git commit") { id } }'"""},
     False, 'mutation words inside a GraphQL query'),
    ('Bash', {'command': 'git log --oneline -5'}, False, 'git log is read-only'),
    ('Bash', {'command': 'git diff HEAD'}, False, 'git diff is read-only'),
    ('Bash', {'command': 'rm -rf /tmp/x'}, True, 'rm'),
    ('Bash', {'command': 'mv a b'}, True, 'mv'),
    ('Bash', {'command': 'npm install lodash'}, True, 'npm install'),
    ('Bash', {'command': 'cat file.txt'}, False, 'cat is read-only'),
    ('Bash', {'command': 'ls -la'}, False, 'ls is read-only'),
    (
        'Bash',
        {'command': 'touch /tmp/x'},
        True,
        'creating files is a mutation even without a redirect',
    ),
    ('Bash', {'command': 'gh pr view --json number'}, False, 'gh pr view is read-only'),
    (
        'Bash',
        {'command': "gh api graphql -f query='query($owner: String!) { repository(owner: $owner, name: \"x\") { id } }'"},
        False,
        'gh api graphql with a query document is read-only',
    ),
    (
        'Bash',
        {
            'command': (
                "gh api graphql -f query='mutation($id: ID!) { resolveReviewThread(input: "
                '{threadId: $id}) { thread { id } } }\''
            )
        },
        True,
        'gh api graphql with a mutation document is mutating',
    ),
    (
        'Bash',
        {'command': 'gh api graphql -f query=@payload.json'},
        True,
        'gh api graphql with an unparseable query document defaults to mutating',
    ),
    (
        'Bash',
        {'command': "gh api graphql -f query='# a leading comment\nmutation { x }'"},
        True,
        'a mutation prefixed with a GraphQL comment must still be caught',
    ),
    (
        'Bash',
        {'command': "gh api graphql -f query=',mutation { x }'"},
        True,
        'a mutation prefixed with a leading comma must still be caught',
    ),
    (
        'Bash',
        {'command': "gh api graphql -f query='# a leading comment\nquery { x }'"},
        False,
        'a query prefixed with a GraphQL comment stays read-only',
    ),
    (
        'Bash',
        {'command': "gh api graphql -f query='query { viewer { login } }' && rm -rf /tmp/important"},
        True,
        'a read-only graphql query chained with a real bash mutation must still be caught',
    ),
    (
        'Bash',
        {'command': "gh api graphql -f query='mutation { x }' && echo done"},
        True,
        'a graphql mutation chained with a harmless command stays caught',
    ),
    (
        'Bash',
        {'command': "gh api graphql -f query='fragment F on X { id } mutation { m }'"},
        True,
        'a mutation preceded by a fragment definition must still be caught',
    ),
    (
        'Bash',
        {'command': "gh api graphql -f query='fragment F on X { id } query { q }'"},
        False,
        'a query preceded by a fragment definition stays read-only',
    ),
    (
        'Bash',
        {'command': "gh api graphql -f query='fragment A on X {a} fragment B on Y {b} mutation {m}'"},
        True,
        'multiple leading fragments before a mutation must still be caught',
    ),
    (
        'Bash',
        {'command': "gh api graphql -f query='fragment F on X {id} { viewer { login } }'"},
        False,
        'a fragment before an anonymous (keyword-less) query stays read-only',
    ),
    (
        'Bash',
        {'command': "gh api graphql -f query='{ viewer { login } }'"},
        False,
        "GraphQL's anonymous-query shorthand (no leading keyword) is always a query, never a mutation",
    ),
    (
        'Bash',
        {'command': "gh api graphql -f query='subscription { s }'"},
        True,
        'a subscription is not an explicit query, defaults to mutating',
    ),
    (
        'Bash',
        {'command': "gh api graphql -f 'query=query { viewer { login } }'"},
        False,
        'the whole key=value pair quoted together (a different valid shell form) stays read-only',
    ),
    (
        'Bash',
        {'command': "gh api graphql -f 'query=mutation { m }'"},
        True,
        'the whole key=value pair quoted together, a mutation, must still be caught',
    ),
    (
        'Bash',
        {'command': 'echo "example: gh api graphql -f query=x"'},
        False,
        '"gh api graphql" mentioned inside an unrelated quoted argument is not a graphql call',
    ),
    ('Bash', {'command': 'printf x &>/tmp/out'}, True, '&> redirects both streams into a real file'),
    ('Bash', {'command': 'printf x &>>/tmp/out'}, True, '&>> appends both streams into a real file'),
    ('Bash', {'command': 'printf x >|/tmp/out'}, True, '>| force-writes into a real file'),
    ('Bash', {'command': 'cmd &>/dev/null'}, False, '&> to /dev/null stays safe, same as > and >&'),
    ('Bash', {'command': ': <> /tmp/pending-question-bypass'}, True, '<> opens for read+write, can create the target file'),
    (
        'Bash',
        {'command': "gh api graphql -f query='query { x }' && gh api graphql -f query='mutation { m }'"},
        True,
        'chained graphql calls: the second, mutating call must still be caught, not just the first',
    ),
    (
        'Bash',
        {'command': "gh api graphql -f query='mutation { m }' && gh api graphql -f query='query { x }'"},
        True,
        'chained graphql calls: the first, mutating call must still be caught',
    ),
    (
        'Bash',
        {'command': "gh api graphql -f query='query { x }' && gh api graphql -f query='query { y }'"},
        False,
        'chained graphql calls: both read-only stays safe',
    ),
    (
        'Bash',
        {'command': "node -e \"require('fs').writeFileSync('/tmp/x', 'y')\""},
        True,
        'node -e is unconditionally mutating (bypass this file exists to close)',
    ),
    (
        'Bash',
        {'command': "python3 -c \"open('/tmp/x', 'w').write('y')\""},
        True,
        'python3 -c is unconditionally mutating (bypass this file exists to close)',
    ),
    ('Bash', {'command': 'echo hi | tee /tmp/out.txt'}, True, 'tee writes a file'),
    ('Bash', {'command': 'printf x > /tmp/out.txt'}, True, 'redirect into a file'),
    ('Bash', {'command': 'printf x >> /tmp/out.txt'}, True, 'append redirect into a file'),
    ('Bash', {'command': 'some-command 2>&1'}, False, 'fd duplication 2>&1 must not be caught'),
    ('Bash', {'command': 'some-command 1>&2'}, False, 'fd duplication 1>&2 must not be caught'),
    ('Bash', {'command': 'printf x >&created.txt'}, True, '>&file redirects both streams into a real file'),
    ('Bash', {'command': 'printf x 2>&created.txt'}, True, '2>&file redirects into a real file'),
    ('Bash', {'command': 'some-command >&-'}, False, 'closing a descriptor with >&- must not be caught'),
    (
        'Bash',
        {'command': 'grep "usage: cmd > out" file.txt'},
        False,
        'a > inside a quoted argument is not a redirect (needs tokenization, not text-scanning)',
    ),
    (
        'Bash',
        {'command': '(( $a > $b )) && echo yes'},
        False,
        'a > inside a (( )) arithmetic comparison is not a redirect',
    ),
    (
        'Bash',
        {'command': 'cmd 2>/dev/null'},
        False,
        '2>/dev/null is a common read-only idiom for suppressing stderr noise, not a mutation',
    ),
    ('Bash', {'command': 'echo "a > b"'}, False, 'a > inside a quoted argument is not a redirect'),
    (
        'Bash',
        {'command': 'true &&\ngh api graphql -f "query=mutation { m }"'},
        True,
        'a multiline GraphQL mutation is still a separate command',
    ),
    ('apply_patch', {'command': '*** Begin Patch\n*** Add File: x\n+y\n*** End Patch'}, True, 'native patches mutate files'),
    ('Bash', {'command': "echo '>' output.txt"}, False, 'a standalone quoted redirect is only an argument'),
    ('Bash', {'command': r'echo \> output.txt'}, False, 'a standalone escaped redirect is only an argument'),
    ('Bash', {'command': 'echo ">" > output.txt'}, True, 'a real redirect after a literal operator'),
    (
        'Bash',
        {'command': "echo ready # status\ngh api graphql -f 'query=mutation { m }'"},
        True,
        'a shell comment must not hide a later GraphQL mutation',
    ),
    (
        'Bash',
        {'command': "gh api graphql -f 'query=query { viewer { login } }' -f note=operationName=Read"},
        False,
        'an unrelated field value is not an operation selector',
    ),
    (
        'Bash',
        {'command': "gh api graphql -f 'query=query { q }' -f 'query=mutation { m }'"},
        True,
        'duplicate query fields are unverified, not last-field-wins',
    ),
    (
        'Bash',
        {'command': "gh api graphql -f 'query=mutation { m }' -f 'query=query { q }'"},
        True,
        'duplicate query fields are unverified in either order',
    ),
    (
        'Bash',
        {'command': "echo ready; gh api graphql -f 'query=mutation { m }'\nprintf 'unfinished"},
        True,
        'a malformed suffix cannot hide an earlier GraphQL mutation',
    ),
]

# (tool_name, expected is_question_blocked() result): work control beyond mutations.
WORK_CONTROL_FIXTURES = [
    ('Agent', True), ('Task', True), ('task', True), ('Workflow', True), ('spawn_agent', True),
    ('send_input', True), ('SendMessage', True), ('TaskStop', True), ('TaskCreate', True),
    ('TaskUpdate', True), ('TodoWrite', True), ('run_dynamic_workflow', True),
    ('write_agent', True), ('resume_agent', True), ('stop_agent', True), ('Read', False), ('Grep', False),
    ('TaskList', False), ('WebFetch', False),
]

for option in ('--template', '-t', '--jq', '-q', '--header', '-H'):
    for operation, expected in (('query', False), ('mutation', True)):
        for value in ('-fquery=query { q }', '-foperationName=Read', '-f'):
            MUTATION_FIXTURES.append((
                'Bash', {'command': f"gh api graphql -f 'query={operation} {{ field }}' {option} '{value}'"},
                expected, 'option values are not field flags',
            ))

for args, expected in (
    ("--template '-f' -f 'query=query { q }'", False),
    ("--template=-fquery=mutation -f 'query=query { q }'", False),
    ("-t-fquery=mutation -f 'query=query { q }'", False),
    ("-f 'query=query { q }' -f 'query=query { q }'", True),
    ("-F 'query=mutation { m }' -f 'query=query { q }'", True),
    ("--unknown '-fquery=query { q }'", True),
    ("-f 'query=query { q }' --input body.json", True),
    ("-- -f 'query=query { q }'", True),
    ("-f 'query=query { q }' -f", True),
    ("-f 'query=query { q }' --template", True),
    ("--paginate --cache 1h -H 'Accept: application/json' -f 'query=query { q }' 2>/dev/null", False),
    ("-f 'query=query { q }' 2>&1", False),
    ("-f 'query=mutation { m }' < '-fquery=query { q }'", True),
):
    MUTATION_FIXTURES.append(('Bash', {'command': f'gh api graphql {args}'}, expected, 'GraphQL option boundaries'))

for field_flag in ('-f ', '-F ', '--raw-field ', '--field ', '--raw-field=', '--field=', '-f', '-F', '-f='):
    for operation, expected in (('query', False), ('mutation', True)):
        MUTATION_FIXTURES.append((
            'Bash', {'command': f"gh api graphql {field_flag}'query={operation} {{ field }}'"},
            expected, 'inline documents use the same field flag forms as operation selectors',
        ))

for selector in (
    '-f operationName=Change', '-F operationName=Change',
    '--raw-field operationName=Change', '--field operationName=Change',
    '--raw-field=operationName=Change', '--field=operationName=Change',
    '-foperationName=Change', '-FoperationName=Change', '-f=operationName=Change',
):
    for fields in (
        f"-f 'query=query Read {{ q }} mutation Change {{ m }}' {selector}",
        f"{selector} -f 'query=query Read {{ q }} mutation Change {{ m }}'",
        f"-f 'query=query Change {{ q }}' {selector}",
    ):
        MUTATION_FIXTURES.append((
            'Bash', {'command': f'gh api graphql {fields}'}, True,
            'explicit operation selection is conservatively blocked while a question is pending',
        ))


def main():
    failures = []

    for message, expected, note in QUESTION_FIXTURES:
        got = has_question(message)
        if got is not expected:
            failures.append(f'has_question mismatch ({note}): got {got}, expected {expected}: {message[:60]!r}')

    for tool_name, tool_input, expected, note in MUTATION_FIXTURES:
        got = is_mutating(tool_name, tool_input)
        if got is not expected:
            failures.append(f'is_mutating mismatch ({note}): got {got}, expected {expected}')

    if {name for name, blocked in WORK_CONTROL_FIXTURES if blocked} != WORK_CONTROL_TOOLS:
        failures.append('WORK_CONTROL_FIXTURES must cover every WORK_CONTROL_TOOLS name')
    for tool_name, expected in WORK_CONTROL_FIXTURES:
        if is_question_blocked(tool_name, {}) is not expected:
            failures.append(f'is_question_blocked mismatch for {tool_name}: expected {expected}')

    # Verified-user cases exercise the shared contract, not native origin detection.
    session_id = f'self-check-{uuid.uuid4()}'
    flag_path = pathlib.Path(f'/tmp/.ioncache-pending-question-{session_id}')
    with tempfile.TemporaryDirectory(prefix='question-check-') as home:
        try:
            settings = pathlib.Path(home) / '.claude/ioncache-ai-tools.local.json'
            settings.parent.mkdir()
            settings.write_text(json.dumps({'features': {}}))

            def classify(**fields):
                result = run_main(
                    guidance, ['UserPromptSubmit'],
                    input=json.dumps({'session_id': session_id, 'cwd': home, **fields}),
                    env={**os.environ, 'HOME': home, 'CODEX_HOME': home, 'COPILOT_HOME': home},
                )
                result.check_returncode()
                return result.stdout

            def guard(tool_name, **fields):
                result = run_main(
                    block_pending_question,
                    input=json.dumps({'session_id': session_id, 'cwd': home,
                                      'tool_name': tool_name, 'tool_input': {}, **fields}),
                    env={**os.environ, 'HOME': home, 'CODEX_HOME': home, 'COPILOT_HOME': home},
                )
                result.check_returncode()
                return json.loads(result.stdout) if result.stdout.strip() else {}

            fixtures = json.loads((pathlib.Path(SCRIPT_DIR).parent / 'fixtures/prompt-origins.json').read_text())
            cases = fixtures['claude'] + [{
                'case': 'synthetic-unknown-bare-report',
                'payload': {'prompt': 'Why did the test finish? What should happen next? Can the parent continue?'},
            }]
            for fixture in cases:
                payload = {**fixture['payload'], 'session_id': session_id, 'cwd': home}
                classify(prompt='Why did it fail?', _ioncache_prompt_origin='user')
                if guard('Write').get('hookSpecificOutput', {}).get('permissionDecision') != 'deny':
                    failures.append('the verified shared question must block before recovery')
                stdout = classify(**payload)
                if flag_path.exists() or QUESTION_CONTRACT in stdout:
                    failures.append(f'Claude unverified origin fenced: {fixture["case"]}')
                if guard('Write') or guard('Agent'):
                    failures.append(f'Claude authorized work could not resume: {fixture["case"]}')

            host_prompts = [
                RECORDED_CLAUDE['handback'], CLAUDE_BATCH,
                *(reminder + RECORDED_CLAUDE['handback']
                  for reminder in RECORDED_CLAUDE['summary_reminders']),
                'Queued report follows.\n<agent-message from="worker">\nWhy did it fail?\n</agent-message>',
                'Queued event follows.\n<task-notification>\nWhat next?\n</task-notification>',
            ]
            for prompt in host_prompts:
                # The supplied user origin makes this fail if host text reaches classification.
                classify(prompt='Why did it fail?', _ioncache_prompt_origin='user')
                stdout = classify(prompt=prompt + '\nCan the parent continue?', _ioncache_prompt_origin='user')
                if flag_path.exists() or QUESTION_CONTRACT in stdout:
                    failures.append('Claude host batch overrode user-origin evidence')
                if guard('Agent') or guard('Write'):
                    failures.append('Claude host batch did not release same-turn worker launch and edits')

            reminder = '<system-reminder>\nWhy did the host add this?\n</system-reminder>\n'
            for prompt, expected in (
                (reminder + 'Continue the work', False),
                ('Continue.\n' + reminder + 'Finish the work', False),
                (reminder + 'how do I fix this', True),
                ('<system-reminder>\n' + reminder + 'Why another reminder?\n</system-reminder>\nContinue', False),
                ('<system-reminder>\nWhy is this truncated?', False),
            ):
                stdout = classify(prompt=prompt, _ioncache_prompt_origin='user')
                if flag_path.exists() is not expected or (QUESTION_CONTRACT in stdout) is not expected:
                    failures.append('Claude reminder text leaked into user question classification')

            for message, expected, note in QUESTION_FIXTURES:
                classify(prompt=message, _ioncache_prompt_origin='user')
                if flag_path.exists() is not expected:
                    failures.append(f'Claude question lifecycle mismatch: {note}')
                denied = guard('Agent').get('hookSpecificOutput', {}).get('permissionDecision') == 'deny'
                if denied is not expected or guard('Read'):
                    failures.append(f'Claude question recovery mismatch: {note}')

            stdout = classify(prompt='why is this broken', _ioncache_prompt_origin='user')
            hook_output = json.loads(stdout).get('hookSpecificOutput') or {}
            if hook_output.get('hookEventName') != 'UserPromptSubmit' or not hook_output.get('additionalContext'):
                failures.append(f'guidance.py stdout is not wrapped in hookSpecificOutput: {stdout!r}')
            if QUESTION_CONTRACT not in hook_output.get('additionalContext', ''):
                failures.append('a root question must emit the answer-only contract')
            if not flag_path.exists():
                failures.append('a root question must record its own question state')
            if guard('Read') or guard('Bash', tool_input={'command': 'git status --short'}):
                failures.append('read-only research must remain available during a verified question')
            classify(prompt='Why did it fail?', agent_id='worker', _ioncache_prompt_origin='user')
            if not flag_path.exists() or guard('Write', agent_id='worker'):
                failures.append('a child must neither clear nor inherit the root question marker')
            classify(prompt='Why did it fail?', parent_agent_id='parent', _ioncache_prompt_origin='user')
            if not flag_path.exists() or guard('Write', parent_agent_id='parent'):
                failures.append('an incomplete child identity must not use the root marker')
            classify(prompt='fix it')
            if flag_path.exists():
                failures.append('a non-question instruction must clear the question state')
            classify(prompt='why is this broken', agent_id='worker', _ioncache_prompt_origin='user')
            if flag_path.exists() or any(pathlib.Path('/tmp').glob(f'.ioncache-pending-question-{session_id}-*')):
                failures.append('a parent-written child prompt must not record question state')
            manifest_path = pathlib.Path(SCRIPT_DIR).parent / 'hooks.json'
            manifest = json.loads(manifest_path.read_text())
            commands = [hook['command'] for group in manifest['hooks']['UserPromptSubmit'] for hook in group['hooks']]
            if any('require_answer_questions_skill.py' in command for command in commands):
                failures.append('a separate marker reader can race Claude prompt classification')
        finally:
            flag_path.unlink(missing_ok=True)
            for child in pathlib.Path('/tmp').glob(f'.ioncache-pending-question-{session_id}-*'):
                child.unlink(missing_ok=True)

    if failures:
        print(f'{len(failures)} failure(s):', file=sys.stderr)
        for failure in failures:
            print(f'  - {failure}', file=sys.stderr)
        sys.exit(1)

    print('All pending-question self-checks passed.')


def test_pending_question():
    main()


@pytest.mark.process
def test_question_process_recovery(tmp_path):
    session = f"self-check-{uuid.uuid4()}"
    payload = {"cwd": str(tmp_path), "session_id": session, "_ioncache_prompt_origin": "user"}
    marker = pathlib.Path(f"/tmp/.ioncache-pending-question-{session}")
    try:
        prompt = run_main(guidance, ["UserPromptSubmit"], process=True,
                          input=json.dumps({**payload, "prompt": "Why did it fail?"}))
        prompt.check_returncode()
        assert QUESTION_CONTRACT in prompt.stdout
        write = {**payload, "tool_name": "Write", "tool_input": {"file_path": "continued.txt"}}
        denied = run_main(block_pending_question, input=json.dumps(write), process=True)
        denied.check_returncode()
        assert json.loads(denied.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
        read = run_main(block_pending_question, process=True,
                        input=json.dumps({**payload, "tool_name": "Read", "tool_input": {}}))
        assert read.returncode == 0 and read.stdout == ""
        resumed = run_main(guidance, ["UserPromptSubmit"], process=True,
                           input=json.dumps({**payload, "prompt": "Continue the assignment"}))
        resumed.check_returncode()
        assert not marker.exists()
        allowed = run_main(block_pending_question, input=json.dumps(write), process=True)
        assert allowed.returncode == 0 and allowed.stdout == ""
    finally:
        marker.unlink(missing_ok=True)


if __name__ == '__main__':
    test_pending_question()
