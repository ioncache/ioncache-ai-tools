"""Exact outgoing-artifact inventories and structural claim review checks."""
from pathlib import Path
import re
import subprocess

from evidence_source import digest, encoded, source_snapshot, source_unit
from evidence_store import reference_key
from hook_adapter_common import patch_inputs
from rule_engine import is_shell_operator, skip_wrappers, split_into_simple_commands, tokenize_command

EDIT_TOOLS = {'Write', 'Edit', 'MultiEdit', 'apply_patch', 'Answer'}


def review_metadata_request(data, store):
    name, args = data['tool_name'], data['tool_input']
    if name == 'apply_patch':
        paths = [item['file_path'] for item in patch_inputs(args['command'])]
    elif name in ('Write', 'Edit', 'MultiEdit'):
        paths = [args['file_path']]
    else:
        return False
    for path in paths:
        destination = (Path(data['cwd']) / path).resolve()
        if not re.fullmatch(r'[a-f0-9]{64}\.review\.json', destination.name):
            return False
        request = destination.with_name(destination.name.replace('.review.json', '.json'))
        if destination.parent != store.requests or not request.is_file():
            return False
    store.validate_requests()
    return bool(paths)


def command_words(tokens):
    index = 1
    value_options = {'-C', '-c', '--git-dir', '--work-tree', '--namespace', '--config-env', '-R', '--repo'}
    while index < len(tokens) and tokens[index].startswith('-'):
        option = tokens[index]
        index += 2 if option in value_options else 1
    return tokens[index:]


def publication_commands(command):
    commands = split_into_simple_commands(tokenize_command(command))
    found = []
    for simple in commands:
        tokens = skip_wrappers(simple)
        if not tokens:
            continue
        executable = Path(tokens[0]).name
        words = command_words(tokens)
        if executable == 'git' and words[:1] == ['commit']:
            found.append(tokens)
        elif executable == 'gh' and words[:2] in (['pr', 'create'], ['pr', 'new'], ['pr', 'edit'], ['pr', 'comment']):
            found.append(tokens)
    return found


def guarded_request(name, args):
    return name in EDIT_TOOLS or (
        name == 'Bash' and bool(publication_commands(args.get('command', '')))
    )


def canonical_request(request, cwd):
    if not isinstance(request, dict):
        raise ValueError('request must be an object')
    name = request['tool_name']
    args = request['tool_input']
    if not isinstance(name, str) or not isinstance(args, dict) or not guarded_request(name, args):
        raise ValueError('request must name a supported edit, publication, or Answer tool')
    args = dict(args)
    if 'file_path' in args:
        args['file_path'] = str((Path(cwd) / args['file_path']).resolve())
    if name == 'Bash':
        args = {'command': args['command']}
    return {'tool_name': name, 'tool_input': args}


def file_state(path):
    path = Path(path)
    try:
        return source_snapshot(path)['sha256']
    except FileNotFoundError:
        return None


def option_values(tokens, flags):
    values = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        flag, separator, value = token.partition('=')
        if flag in flags:
            if not separator:
                index += 1
                if index >= len(tokens):
                    raise ValueError(f'{flag} requires a value')
                value = tokens[index]
            values.append(value)
        index += 1
    return values


def git_output(cwd, args):
    try:
        result = subprocess.run(
            ['git', '--no-pager', *args], cwd=cwd, capture_output=True, timeout=2,
        )
    except subprocess.TimeoutExpired as error:
        raise ValueError('publication source inspection timed out') from error
    if result.returncode:
        raise ValueError(f'cannot inspect publication source: {result.stderr.decode("utf-8", errors="replace").strip()}')
    if len(result.stdout) > 4 * 1024 * 1024:
        raise ValueError('publication source exceeds the 4 MiB review limit')
    return result.stdout.decode('utf-8')


def publication_artifacts(command, cwd):
    found = publication_commands(command)
    simple = split_into_simple_commands(tokenize_command(command))
    if len(found) != 1 or len(simple) != 1:
        raise ValueError('review publication as a single command, without pipelines or chained commands')
    if any(character in command for character in ('$', '`')):
        raise ValueError('publication text must be literal; shell expansion cannot be reviewed')
    tokens = found[0]
    if any(is_shell_operator(token, {'>', '>>', '<', '<<', '<<<', '>&', '<&'}) for token in tokens):
        raise ValueError('publication redirection is unsupported; use an explicit message or body file')
    git_commit = Path(tokens[0]).name == 'git'
    prefix = ['commit'] if git_commit else command_words(tokens)[:2]
    if tokens[1:1 + len(prefix)] != prefix:
        raise ValueError('run publication from its working directory without executable-level options')
    flags = {token.partition('=')[0] for token in tokens[1:]}
    forbidden = {'--editor', '--web', '--fill', '--fill-first', '--fill-verbose', '--recover',
                 '-e', '-f', '-T', '--template', '--attach'}
    if git_commit:
        forbidden = {'-a', '--all', '-p', '--patch', '-i', '--include', '-o', '--only',
                     '-e', '--edit', '-c', '-C', '--reuse-message', '--reedit-message',
                     '--fixup', '--squash', '-t', '--template'}
    if flags & forbidden:
        raise ValueError('publication must use explicit reviewed text and a fixed staged snapshot')
    message_flags = {'-m', '--message'} if git_commit else {'-t', '--title', '-b', '--body'}
    file_flags = {'-F', '--file'} if git_commit else {'-F', '--body-file'}
    messages = option_values(tokens, message_flags)
    files = option_values(tokens, file_flags)
    if not messages and not files:
        raise ValueError('publication needs explicit message/body text or a file; interactive text cannot be checked')
    if git_commit:
        validate_commit_options(tokens[2:])
    elif tokens[1:3] in (['pr', 'create'], ['pr', 'new']):
        if not option_values(tokens, {'-t', '--title'}) or not (option_values(tokens, {'-b', '--body'}) or files):
            raise ValueError('PR creation requires both an explicit title and body to avoid unreviewed prompts')
    artifacts = [('command', command)]
    artifacts.extend(('message', value) for value in messages)
    dependencies = {}
    for filename in files:
        if filename == '-':
            raise ValueError('stdin publication text cannot be checked; use a file')
        snapshot = source_snapshot(Path(cwd) / filename)
        dependencies[snapshot['path']] = snapshot['sha256']
        artifacts.append((snapshot['path'], snapshot['text']))
    if git_commit:
        artifacts.append(('staged diff', git_output(cwd, [
            'diff', '--cached', '--no-ext-diff', '--no-textconv', '--binary', '--',
        ])))
    return artifacts, dependencies


def validate_commit_options(tokens):
    value_flags = {'-m', '--message', '-F', '--file'}
    switches = {'--allow-empty', '--allow-empty-message', '--no-verify', '--no-gpg-sign', '-q', '--quiet'}
    index = 0
    while index < len(tokens):
        flag, separator, _ = tokens[index].partition('=')
        if flag in value_flags:
            index += 1 if separator else 2
        elif flag in switches:
            index += 1
        else:
            raise ValueError('unsupported commit option or path selection; review an explicit message and the staged snapshot')


def outgoing_artifacts(request, cwd):
    name, args = request['tool_name'], request['tool_input']
    if name == 'Bash':
        return publication_artifacts(args['command'], cwd)
    if name == 'Answer':
        return [('answer', args['text'])], {}
    if name == 'apply_patch':
        edits = patch_inputs(args['command'])
    elif name == 'MultiEdit':
        edits = [{**edit, 'file_path': args['file_path']} for edit in args['edits']]
    else:
        edits = [args]
    artifacts, dependencies = [], {}
    for edit in edits:
        path = str((Path(cwd) / edit['file_path']).resolve())
        text = edit.get('content', edit.get('new_string', ''))
        if not isinstance(text, str):
            raise ValueError('outgoing content must be text')
        artifacts.append((path, text))
        dependencies[path] = file_state(path)
    return artifacts, dependencies


def inventory(request, cwd):
    request = canonical_request(request, cwd)
    artifacts, dependencies = outgoing_artifacts(request, cwd)
    items = [
        {'artifact': index, 'destination': destination, 'text': text,
         'lines': len(text.split('\n')) if text else 0}
        for index, (destination, text) in enumerate(artifacts)
    ]
    result = {'cwd': str(Path(cwd).resolve()), 'request': request, 'artifacts': items, 'dependencies': dependencies}
    return {**result, 'fingerprint': digest(encoded(result))}


def checked_reference(reference, context):
    if not isinstance(reference, dict):
        raise ValueError('evidence references must be objects')
    snapshot = source_snapshot(Path(context['cwd']) / reference['path'])
    if snapshot['sha256'] != reference['sha256']:
        raise ValueError('evidence snapshot is stale; reread the complete source')
    unit = reference['unit']
    _, bounds = source_unit(snapshot, unit)
    lines = reference['lines']
    if (not isinstance(lines, list) or len(lines) != 2
            or any(type(line) is not int for line in lines)
            or not bounds[0] <= lines[0] <= lines[1] <= bounds[1]):
        raise ValueError('decisive lines must lie inside the complete evidence unit')
    ref = {'path': snapshot['path'], 'sha256': snapshot['sha256'], 'unit': unit}
    file_ref = {**ref, 'unit': 'file'}
    store = context['store']
    if not (store.get('coverage', reference_key(ref)) or store.get('coverage', reference_key(file_ref))):
        raise ValueError(f'no complete delivered coverage for {ref["path"]} unit {unit}')
    return {**ref, 'lines': lines}


def reviewed_claims(row, text, context):
    claims = row.get('claims', [])
    if not isinstance(claims, list):
        raise ValueError('claims must be a list')
    if row.get('kind') == 'non-behavior':
        if claims:
            raise ValueError('non-behavior classifications cannot contain claims')
        return []
    if row.get('kind') != 'behavior' or not claims:
        raise ValueError('behavior classifications require explicit claims')
    references = []
    for claim in claims:
        if not isinstance(claim, dict):
            raise ValueError('each claim must be an object')
        if not isinstance(claim.get('text'), str) or not claim['text'] or claim['text'] not in text:
            raise ValueError('claim text must quote the reviewed artifact exactly')
        if not isinstance(claim.get('reason'), str) or not claim['reason'].strip():
            raise ValueError('each claim needs a control-flow or supporting-evidence explanation')
        evidence = claim.get('evidence')
        if not isinstance(evidence, list) or not evidence:
            raise ValueError('each behavioral claim requires evidence')
        references.extend(checked_reference(ref, context) for ref in evidence)
    return references


def check_review(review, prepared, context):
    if not isinstance(review, dict) or review.get('fingerprint') != prepared['fingerprint']:
        raise ValueError('review fingerprint does not match the exact current outgoing artifacts')
    if not isinstance(review.get('reviewer'), str) or not review['reviewer'].strip():
        raise ValueError('review must identify its reviewer')
    rows = review.get('classifications')
    if not isinstance(rows, list):
        raise ValueError('review classifications must be a list')
    covered = [set() for _ in prepared['artifacts']]
    references = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('each review classification must be an object')
        index, start, end = row['artifact'], row['start'], row['end']
        if type(index) is not int or not 0 <= index < len(covered):
            raise ValueError('invalid review artifact index')
        artifact = prepared['artifacts'][index]
        if type(start) is not int or type(end) is not int or not 1 <= start <= end <= artifact['lines']:
            raise ValueError('invalid review line range')
        lines = set(range(start, end + 1))
        if covered[index] & lines:
            raise ValueError('review classifications must not overlap')
        if not isinstance(row.get('reason'), str) or not row['reason'].strip():
            raise ValueError('every classification needs a review rationale')
        text = '\n'.join(artifact['text'].split('\n')[start - 1:end])
        references.extend(reviewed_claims(row, text, context))
        covered[index].update(lines)
    expected = [set(range(1, artifact['lines'] + 1)) for artifact in prepared['artifacts']]
    if covered != expected:
        raise ValueError('every outgoing line must be classified; prose cannot be silently omitted')
    return references
