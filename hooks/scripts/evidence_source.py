"""Snapshot-based source units and bounded, verifiable delivery pages."""
import ast
import hashlib
import json
from pathlib import Path

SMALL_FILE_LINES = 400
MAX_SOURCE_BYTES = 4 * 1024 * 1024
PAGE_CHARACTERS = 2000


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def source_snapshot(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ValueError('source must be a regular file')
    with path.open('rb') as stream:
        raw = stream.read(MAX_SOURCE_BYTES + 1)
    if len(raw) > MAX_SOURCE_BYTES:
        raise ValueError('source exceeds the 4 MiB evidence-reader limit')
    text = raw.decode('utf-8')
    if '\0' in text:
        raise ValueError('binary source cannot establish text coverage')
    lines = text.split('\n')
    if lines[-1] == '':
        lines.pop()
    return {
        'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(),
        'text': text, 'lines': lines,
    }


def unit_bounds(snapshot):
    count = len(snapshot['lines'])
    units = {'file': (1, count)}
    if count <= SMALL_FILE_LINES or Path(snapshot['path']).suffix not in ('.py', '.pyi'):
        return units
    if '\r' in snapshot['text'].replace('\r\n', ''):
        raise ValueError('bare CR source requires a whole-file read')
    try:
        tree = ast.parse(snapshot['text'])
    except (SyntaxError, ValueError, RecursionError) as error:
        raise ValueError(f'cannot parse source units; use the whole file: {error}') from error
    nodes = list(tree.body)
    nodes.extend(
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    )
    for node in nodes:
        start = min([node.lineno] + [item.lineno for item in getattr(node, 'decorator_list', [])])
        end = node.end_lineno
        units[f'{start}:{end}'] = (start, end)
    return units


def source_unit(snapshot, unit):
    if unit == 'file':
        return snapshot['text'], (1, len(snapshot['lines']))
    bounds = unit_bounds(snapshot)
    if unit not in bounds:
        raise ValueError('unknown or partial unit; use units to list exact boundaries')
    start, end = bounds[unit]
    lines = snapshot['text'].split('\n')
    text = '\n'.join(lines[start - 1:end])
    if end < len(lines):
        text += '\n'
    return text, (start, end)


def read_page(options):
    snapshot = source_snapshot(options.path)
    if options.sha256 and options.sha256 != snapshot['sha256']:
        raise ValueError('source changed; restart the logical read with its current snapshot')
    text, (start, end) = source_unit(snapshot, options.unit)
    pages = max(1, (len(text) + PAGE_CHARACTERS - 1) // PAGE_CHARACTERS)
    if not 1 <= options.page <= pages:
        raise ValueError(f'page must be between 1 and {pages}')
    offset = (options.page - 1) * PAGE_CHARACTERS
    record = {
        'path': snapshot['path'], 'sha256': snapshot['sha256'], 'unit': options.unit,
        'start_line': start, 'end_line': end, 'page': options.page, 'pages': pages,
        'content': text[offset:offset + PAGE_CHARACTERS],
    }
    return record, 'CLAIM_EVIDENCE_SOURCE ' + json.dumps(record, ensure_ascii=False, sort_keys=True)


def check_native_read(args, cwd):
    if not any(key in args for key in ('offset', 'limit')):
        return
    path = Path(cwd) / args['file_path']
    if path.is_dir():
        return
    snapshot = source_snapshot(path)
    count = len(snapshot['lines'])
    if count <= SMALL_FILE_LINES:
        raise ValueError('files of 400 lines or fewer require a whole-file request without offset or limit')
    start = args.get('offset', 1)
    limit = args.get('limit')
    if type(start) is not int or start < 1 or (limit is not None and (type(limit) is not int or limit < 1)):
        raise ValueError('read ranges require positive integer line numbers')
    end = count if limit is None else start + limit - 1
    if (start, end) == (1, count):
        return
    if (start, end) not in unit_bounds(snapshot).values():
        raise ValueError('range must match a complete parser-defined unit or the whole file; use the evidence reader')
