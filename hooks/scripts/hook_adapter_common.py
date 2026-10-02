import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
PATCH_REWRITE_REASON = (
    'This patch contains added text that a rule would rewrite. '
    'Remove em-dashes from the added text and resubmit the patch. '
    'Patch context and removed lines must not be auto-rewritten.'
)


def run_shared_hooks(event, hook_input):
    """Use the shared manifest as the sole source of hook order and commands."""
    manifest = json.loads((PLUGIN_ROOT / 'hooks' / 'hooks.json').read_text())
    outputs = []
    deadline = time.monotonic() + (5 if event == 'Stop' else 20)
    for group in manifest['hooks'].get(event, []):
        for hook in group['hooks']:
            command = [
                arg.replace('${CLAUDE_PLUGIN_ROOT}', str(PLUGIN_ROOT))
                for arg in shlex.split(hook['command'])
            ]
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f'{event} hooks exceeded their internal deadline')
            result = subprocess.run(
                command, input=json.dumps(hook_input), capture_output=True,
                text=True, cwd=hook_input['cwd'], timeout=min(hook.get('timeout', 5), remaining),
            )
            if result.stderr:
                print(result.stderr, file=sys.stderr, end='')
            if result.returncode:
                raise RuntimeError(f'{Path(command[1]).name} exited with {result.returncode}')
            if result.stdout.strip():
                output = json.loads(result.stdout)
                if not isinstance(output, dict):
                    raise ValueError(f'{Path(command[1]).name} returned a non-object result')
                outputs.append(output)
    return outputs


class AmbiguousPatchHeader(ValueError):
    """Header ambiguity must deny the patch, not check a different destination."""


def patch_inputs(patch):
    """Check patch targets and added text without rewriting matching context."""
    inputs = []
    current = None
    operation = None
    for line in patch.replace('\r\n', '\n').split('\n'):
        header = line.rstrip() if operation == 'Update File' else line.strip()
        match = re.match(r'^\*\*\* (Add File|Update File|Delete File|Move to): (.+)$', header)
        if match:
            if line != header:
                raise AmbiguousPatchHeader('Ambiguous patch header whitespace; use unpadded file headers and paths.')
            if match[1] != 'Move to':
                operation = match[1]
            current = {'file_path': match[2], 'new_string': ''}
            inputs.append(current)
        elif line.startswith('+') and current is not None:
            current['new_string'] += line[1:] + '\n'
    if not inputs:
        raise ValueError('apply_patch input has no recognized file headers')
    return inputs
