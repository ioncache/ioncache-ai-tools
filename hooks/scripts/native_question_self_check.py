"""Replay native question provenance through the registered hook entry points."""
import copy
import json
import os
from pathlib import Path
import sys
import uuid

import pytest

import block_pending_question
import codex_adapter
import guidance
from classify_question import marker_path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
from self_check_support import inprocess_hooks, run_main


@pytest.fixture
def claude_question(tmp_path, monkeypatch):
    monkeypatch.delenv('IONCACHE_DOCS_DISTILLER', raising=False)
    fixture = json.loads((ROOT / 'hooks/fixtures/claude-question-events.json').read_text())
    session = f'native-question-{uuid.uuid4()}'
    data = {**fixture['hook'], 'session_id': session, 'cwd': str(tmp_path),
            'transcript_path': str(tmp_path / 'transcript.jsonl')}
    events = copy.deepcopy(fixture['events'])
    events[0]['sessionId'] = session
    save_events(data, events)
    yield data, events
    marker_path(data).unlink(missing_ok=True)


def save_events(data, events):
    Path(data['transcript_path']).write_text(''.join(json.dumps(event) + '\n' for event in events))


def tool(data, command='printf forbidden > forbidden.txt', **fields):
    result = run_main(block_pending_question, input=json.dumps({
        **data, 'tool_name': 'Bash', 'tool_input': {'command': command}, **fields,
    }))
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout) if result.stdout else {}


def test_claude_native_question_denial_and_recovery(claude_question):
    data, events = claude_question
    guidance.run_hook('UserPromptSubmit', {**data, 'prompt': events[0]['message']['content']})
    assert not marker_path(data).exists()
    output = tool(data)
    assert output['hookSpecificOutput']['permissionDecision'] == 'deny'
    assert 'Read-only research remains available' in str(output)
    assert tool(data, 'cat seed.txt') == {}
    assert tool(data, tool_name='Agent', tool_input={'prompt': 'Implement it'})[
        'hookSpecificOutput']['permissionDecision'] == 'deny'
    assert tool(data, agent_id='child', agent_type='general-purpose') == {}
    assert tool(data)['hookSpecificOutput']['permissionDecision'] == 'deny'
    events.append({**events[0], 'promptId': 'next-prompt', 'turnPromptId': 'next-prompt',
                   'message': {'role': 'user', 'content': 'Implement the change'}})
    save_events(data, events)
    assert tool({**data, 'prompt_id': 'next-prompt'}) == {}
    assert tool(data) == {}


@pytest.mark.parametrize('change', [
    {'origin': {'kind': 'peer'}},
    {'origin': {'kind': 'task-notification'}},
    {'origin': {'kind': 'coordinator'}},
    {'origin': {'kind': 'auto-continuation'}},
    {'origin': {'kind': 'unclassified'}},
    {'origin': None, 'turnOrigin': 'sdk'},
    {'isSidechain': True, 'agentId': 'child'},
    {'isMeta': True},
    {'sessionId': 'other-session'},
    {'promptId': 'different-prompt'},
    {'turnPromptId': 'different-prompt'},
    {'message': {'role': 'user', 'content': '<task-notification>Why did it fail?</task-notification>'}},
])
def test_claude_nonuser_evidence_never_fences(claude_question, change):
    data, events = claude_question
    events[0].update(change)
    save_events(data, events)
    marker_path(data).write_text('')
    assert tool(data) == {}


def test_claude_completion_and_new_host_prompt_release_question(claude_question):
    data, events = claude_question
    assert tool(data)['hookSpecificOutput']['permissionDecision'] == 'deny'
    events.append({'type': 'assistant', 'sessionId': data['session_id'], 'isSidechain': False,
                   'message': {'role': 'assistant', 'stop_reason': 'end_turn'}})
    save_events(data, events)
    assert tool(data) == {}
    events.append({**events[0], 'origin': {'kind': 'task-notification'},
                   'promptId': 'host-prompt', 'turnPromptId': 'host-prompt'})
    save_events(data, events)
    assert tool({**data, 'prompt_id': 'host-prompt'}) == {}


def test_claude_child_questions_and_tool_results_do_not_change_root_turn(claude_question):
    data, events = claude_question
    child = {**events[0], 'isSidechain': True, 'agentId': 'child'}
    handback = {
        'type': 'user', 'sessionId': data['session_id'], 'isSidechain': False,
        'message': {'role': 'user', 'content': [
            {'type': 'tool_result', 'tool_use_id': 'child-call', 'content': 'Why did this change?'},
        ]},
    }
    save_events(data, [*events, child, handback])
    assert tool(data)['hookSpecificOutput']['permissionDecision'] == 'deny'
    events[0]['message']['content'] = 'Continue the authorized work'
    save_events(data, [*events, child, handback])
    assert tool(data) == {}


def test_claude_lagging_and_bounded_history_cannot_reuse_old_question(claude_question, monkeypatch):
    import claude_question as native
    from question_history import history_tail

    data, events = claude_question
    assert tool({**data, 'prompt_id': 'not-yet-recorded'}) == {}
    Path(data['transcript_path']).write_text(
        json.dumps(events[0]) + '\n' + json.dumps({'type': 'attachment', 'text': 'x' * 2048}) + '\n'
    )
    monkeypatch.setattr(native, 'history_tail', lambda path: history_tail(path, 1024))
    output = tool(data)
    assert 'permissionDecision' not in str(output)
    assert 'unavailable' in output['systemMessage']


@pytest.mark.parametrize('failure', ['missing', 'partial', 'malformed', 'symlink', 'fifo'])
def test_claude_unavailable_history_does_not_fence(claude_question, failure):
    data, _ = claude_question
    path = Path(data['transcript_path'])
    path.unlink()
    if failure == 'partial':
        path.write_text('{"type":"user"')
    elif failure == 'malformed':
        path.write_text('not json\n')
    elif failure == 'symlink':
        target = path.with_suffix('.target')
        target.write_text('{}\n')
        path.symlink_to(target)
    elif failure == 'fifo':
        os.mkfifo(path)
    marker_path(data).write_text('')
    output = tool(data)
    assert 'permissionDecision' not in str(output)
    if failure != 'missing':
        assert 'unavailable' in output['systemMessage']


def test_claude_question_opt_out(claude_question):
    data, _ = claude_question
    path = Path(data['cwd']) / '.claude/ioncache-ai-tools.local.json'
    path.parent.mkdir()
    path.write_text(json.dumps({'features': {'answer-questions': False}}))
    assert tool(data) == {}


@pytest.fixture
def codex_question(tmp_path):
    fixture = json.loads((ROOT / 'hooks/fixtures/codex-question-events.json').read_text())
    session = f'native-question-{uuid.uuid4()}'
    data = {**fixture['hook'], 'session_id': session, 'cwd': str(tmp_path),
            'transcript_path': str(tmp_path / 'transcript.jsonl')}
    events = fixture['events']
    events[0]['payload'].update(id=session, session_id=session)
    save_events(data, events)
    yield data, events
    marker_path(data).unlink(missing_ok=True)


def codex_tool(data, **fields):
    with inprocess_hooks():
        return codex_adapter.run_hook('PreToolUse', {**data, **fields}) or {}


def test_codex_native_question_denial_and_recovery(codex_question):
    data, events = codex_question
    assert codex_tool(data)['hookSpecificOutput']['permissionDecision'] == 'deny'
    assert codex_tool(data, tool_input={'command': 'cat seed.txt'}) == {}
    assert codex_tool(data, tool_name='spawn_agent', tool_input={'prompt': 'Continue'})[
        'hookSpecificOutput']['permissionDecision'] == 'deny'
    assert codex_tool(data, agent_id='child', agent_type='worker') == {}
    assert codex_tool(data)['hookSpecificOutput']['permissionDecision'] == 'deny'
    events[-1]['payload']['content'][0]['text'] = 'Implement the change'
    save_events(data, events)
    assert codex_tool(data) == {}


@pytest.mark.parametrize('attribution', [
    {'turn_trigger': 'exec'}, {'turn_trigger': 'goal'},
    {'turn_trigger': 'automation_heartbeat_scheduled'},
    {'turn_trigger': 'daemon_recovery'}, {'turn_trigger': None},
    {'parent_turn_id': 'parent'}, {'initiating_agent_path': '/root/worker'},
    {'root_turn_id': 'another-root'}, {'turn_id': 'different-turn'},
])
def test_codex_automation_and_delegation_never_fence(codex_question, attribution):
    data, events = codex_question
    events[1]['payload']['turn_attribution'].update(attribution)
    save_events(data, events)
    marker_path(data).write_text('')
    assert codex_tool(data) == {}


@pytest.mark.parametrize('ending', ['task_complete', 'turn_aborted', 'other-turn', 'steering', 'host'])
def test_codex_later_events_cannot_inherit_question(codex_question, ending):
    data, events = codex_question
    assert codex_tool(data)['hookSpecificOutput']['permissionDecision'] == 'deny'
    if ending in ('task_complete', 'turn_aborted'):
        events.append({'type': 'event_msg', 'payload': {'type': ending, 'turn_id': data['turn_id']}})
    elif ending == 'other-turn':
        events.append({'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'other'}})
    else:
        message = copy.deepcopy(events[-1])
        if ending == 'host':
            message['payload']['internal_chat_message_metadata_passthrough']['content_item_kinds'] = [
                'multi_agent.message']
        events.append(message)
    save_events(data, events)
    assert codex_tool(data) == {}


def test_codex_unavailable_evidence_and_opt_out(codex_question):
    data, _ = codex_question
    marker_path(data).write_text('')
    Path(data['transcript_path']).write_text('invalid\n')
    output = codex_tool(data)
    assert 'permissionDecision' not in str(output)
    assert 'unavailable' in output['systemMessage']
    config = Path(data['cwd']) / '.codex/ioncache-ai-tools.local.json'
    config.parent.mkdir(exist_ok=True)
    config.write_text(json.dumps({'features': {'answer-questions': False}}))
    assert codex_tool(data) == {}
