#!/usr/bin/env python3
"""Self-check for classify_question.py and block_pending_question.py.

Run: python3 hooks/scripts/pending_question_self_check.py < /dev/null

The has_question() fixture below is drawn from this project's own real
session history (grepped from ~/.claude/projects/.../*.jsonl), not
invented, after a real incident where two unpunctuated "why" questions
were missed entirely. Inventing plausible-looking test strings would
have missed the actual failure shape: real messages are typo-laden,
multi-clause, and mix instructions with questions in ways synthetic
examples tend not to.
"""
import json
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from classify_question import has_question  # noqa: E402
from block_pending_question import is_mutating  # noqa: E402

# (message, expected has_question() result, note). Real messages pulled
# from this project's own Claude Code session history.
QUESTION_FIXTURES = [
    # Real questions with NO "?" (the bug this file exists to catch).
    (
        'why is the pr body written like this" Two new broadcast email templates need to go out '
        'to two distinct audiences, and bin/send-notifications.js had no way to target anything '
        'narrower than "the entire registered base" (plus a single-member test mode). This adds a '
        '--recipients CSV option so an operator can send to exactly the members named in a file.\n\n\n'
        'why are we mentioning 2 audiences, you are being very very specific here\n\n'
        "this pr is generic, it doesn't need to know aobgut 2 new audiences",
        True,
        'the reported incident message, verbatim',
    ),
    ('what is the currebt session id', True, 'real question, typo, no ?'),
    ('what is DIGITALOCEAN_ACCESS_TOKEN', True, 'real question, no ?'),
    ('did you oush tge cgabgtes/.', True, 'real question, typo-laden, ends in period not ?'),
    ("which agent is doing the work right now,. I don't see them in the agent list", True, 'real question, no ?'),
    ('where is the list of previouslt created users', True, 'real question, typo, no ?'),
    ('how do I do this: Create a 20%-off promotion code in Stripe, then apply it at checkout.', True, 'real question, colon not ?'),
    ('what do you mean "For sale"  we are not using that term ever', True, 'real clarifying question, no ?'),
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
    # Known, accepted false positives: a genuinely ambiguous interrogative
    # opener ("when"/"what") that's also a common conditional/declarative
    # sentence shape. Not special-cased, per this file's own stated design
    # principle (prefer over-blocking to an ordering-sensitive classifier).
    (
        "when you use references to steps or other parts of the document, ALWAYS use links to "
        "that section.  if that seciton isn't using a header of some sort that is linkable, "
        "change the format",
        True,
        'accepted false positive: conditional instruction opening with "when"',
    ),
    (
        "what I want is an instruction telling it to NEVER use it's training data ever",
        True,
        'accepted false positive: declarative "what I want is X" opening with "what"',
    ),
]

# (tool_name, tool_input, expected is_mutating() result, note)
MUTATION_FIXTURES = [
    ('Edit', {}, True, 'Edit is always mutating'),
    ('Write', {}, True, 'Write is always mutating'),
    ('NotebookEdit', {}, True, 'NotebookEdit is always mutating'),
    ('MultiEdit', {}, True, 'MultiEdit is always mutating'),
    ('Read', {}, False, 'Read is never in ALWAYS_MUTATING_TOOLS'),
    ('Bash', {'command': 'git commit -m msg'}, True, 'git commit'),
    ('Bash', {'command': 'git push'}, True, 'git push'),
    ('Bash', {'command': 'git log --oneline -5'}, False, 'git log is read-only'),
    ('Bash', {'command': 'git diff HEAD'}, False, 'git diff is read-only'),
    ('Bash', {'command': 'rm -rf /tmp/x'}, True, 'rm'),
    ('Bash', {'command': 'mv a b'}, True, 'mv'),
    ('Bash', {'command': 'npm install lodash'}, True, 'npm install'),
    ('Bash', {'command': 'cat file.txt'}, False, 'cat is read-only'),
    ('Bash', {'command': 'ls -la'}, False, 'ls is read-only'),
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
]


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

    # End-to-end: classify_question.py's real stdout, not just has_question()
    # in isolation, catches a bare top-level additionalContext field (the
    # real bug found here) that a unit-level check on has_question() alone
    # would never see, since has_question() itself was never wrong about
    # that.
    result = subprocess.run(
        [sys.executable, os.path.join(SCRIPT_DIR, 'classify_question.py')],
        input=json.dumps({'session_id': 'self-check', 'prompt': 'why is this broken'}),
        capture_output=True,
        text=True,
        check=True,
    )
    output = json.loads(result.stdout)
    hook_output = output.get('hookSpecificOutput') or {}
    if hook_output.get('hookEventName') != 'UserPromptSubmit' or not hook_output.get('additionalContext'):
        failures.append(f'classify_question.py stdout is not wrapped in hookSpecificOutput: {result.stdout!r}')

    if failures:
        print(f'{len(failures)} failure(s):', file=sys.stderr)
        for failure in failures:
            print(f'  - {failure}', file=sys.stderr)
        sys.exit(1)

    print('All pending-question self-checks passed.')


if __name__ == '__main__':
    main()
