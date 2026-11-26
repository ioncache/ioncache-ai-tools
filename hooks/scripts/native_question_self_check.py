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


def claude_group(data, *names):
    fixture = json.loads((ROOT / 'hooks/fixtures/claude-question-events.json').read_text())
    events = [event for name in names for event in fixture[name]]
    for event in events:
        event['sessionId'] = data['session_id']
    return events


@pytest.mark.parametrize('groups', [
    ('skill_tool_load',), ('skill_tool_load', 'skill_tool_reload'), ('image_read',),
    ('skill_tool_load', 'image_read'),
])
def test_claude_skill_and_image_loads_keep_the_question_turn(claude_question, groups):
    data, events = claude_question
    save_events(data, [*events, *claude_group(data, *groups)])
    assert tool(data)['hookSpecificOutput']['permissionDecision'] == 'deny'
    assert tool(data, 'cat seed.txt') == {}
    instruction = {**events[0], 'promptId': 'next-prompt', 'turnPromptId': 'next-prompt',
                   'message': {'role': 'user', 'content': 'Implement the change'}}
    later = claude_group(data, *groups)
    for event in later:
        event['promptId'] = 'next-prompt'
    save_events(data, [*events, *claude_group(data, *groups), instruction, *later])
    assert tool({**data, 'prompt_id': 'next-prompt'}) == {}


def test_claude_slash_command_with_question_arguments_is_an_instruction(claude_question):
    data, events = claude_question
    marker_path(data).write_text('')
    for groups in (('slash_command',), ('slash_command', 'skill_tool_load')):
        save_events(data, claude_group(data, *groups))
        assert tool(data) == {}
    question = {**events[0], 'promptId': 'next-prompt', 'turnPromptId': 'next-prompt'}
    save_events(data, [*claude_group(data, 'slash_command', 'skill_tool_load'), question])
    assert tool({**data, 'prompt_id': 'next-prompt'})['hookSpecificOutput']['permissionDecision'] == 'deny'


@pytest.mark.parametrize('change', [
    {'message': {'role': 'user', 'content': 'Another Claude session sent a message:\n<agent>Continue?</agent>'}},
    {'message': {'role': 'user', 'content': 'Stop hook feedback:\nWhy did this stop?'}},
    {'message': {'role': 'user', 'content': '[Image #1] What is shown?'}},
    {'sourceToolUseID': 'claude-skill-call', 'promptId': 'another-prompt'},
    {'message': {'role': 'user', 'content': '[Image: original 10x10, displayed at 10x10.]'},
     'promptId': 'another-prompt'},
])
def test_claude_other_meta_input_still_releases_the_question(claude_question, change):
    data, events = claude_question
    meta = {**claude_group(data, 'skill_tool_load')[-1], 'sourceToolUseID': None, **change}
    save_events(data, [*events, meta])
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
    next_turn = 'next-user-turn'
    start, message = copy.deepcopy(events[1:])
    start['payload']['turn_id'] = next_turn
    start['payload']['turn_attribution'].update(turn_id=next_turn, root_turn_id=next_turn)
    message['payload']['internal_chat_message_metadata_passthrough']['turn_id'] = next_turn
    message['payload']['content'][0]['text'] = 'Implement the change'
    events.extend([
        {'type': 'event_msg', 'payload': {'type': 'task_complete', 'turn_id': data['turn_id']}},
        start, message,
    ])
    save_events(data, events)
    assert codex_tool(data, turn_id=next_turn) == {}
    assert codex_tool(data) == {}


@pytest.mark.parametrize('evidence', ['missing', 'question', 'instruction', 'task_complete', 'turn_aborted'])
def test_codex_truncated_history_requires_a_current_turn_boundary(codex_question, monkeypatch, evidence):
    import codex_question as native
    from question_history import history_tail

    data, events = codex_question
    large_output = {'type': 'response_item', 'payload': {
        'type': 'function_call_output', 'call_id': 'read-call', 'output': 'x' * 2048,
    }}
    if evidence in ('question', 'instruction'):
        if evidence == 'instruction':
            events[-1]['payload']['content'][0]['text'] = 'Implement the change'
        events.insert(0, large_output)
    else:
        events.append(large_output)
        if evidence != 'missing':
            events.append({'type': 'event_msg', 'payload': {
                'type': evidence, 'turn_id': data['turn_id'],
            }})
    save_events(data, events)
    lines, truncated = history_tail(data['transcript_path'], 1024)
    assert truncated
    assert any(json.loads(line)['payload'].get('type') == 'task_started' for line in lines) == (
        evidence in ('question', 'instruction')
    )
    monkeypatch.setattr(native, 'history_tail', lambda path: history_tail(path, 1024))
    marker_path(data).write_text('')
    output = codex_tool(data)
    if evidence == 'missing':
        assert 'permissionDecision' not in str(output)
        assert 'unavailable' in output['systemMessage']
    elif evidence == 'question':
        assert output['hookSpecificOutput']['permissionDecision'] == 'deny'
        assert 'systemMessage' not in output
    else:
        assert output == {}


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


def codex_item(name, **changes):
    fixture = json.loads((ROOT / 'hooks/fixtures/codex-question-events.json').read_text())
    item = fixture[name]
    metadata = item['payload']['internal_chat_message_metadata_passthrough']
    metadata.update(changes)
    return item


def codex_text(events, text):
    events[-1]['payload']['content'][0]['text'] = text


@pytest.mark.parametrize('text', [
    'Why does $ioncache-ai-tools:investigate fail here?',
    'Use [$ioncache-ai-tools:investigate](/plugin/skills/investigate/SKILL.md). Why does it fail?',
    '$other-skill why does it fail?',
])
def test_codex_skill_context_keeps_the_question_turn(codex_question, text):
    data, events = codex_question
    codex_text(events, text)
    events.insert(2, codex_item('environment_context'))
    events.extend([codex_item('skill_injection'), codex_item('environment_context'),
                   codex_item('skill_injection')])
    save_events(data, events)
    assert codex_tool(data)['hookSpecificOutput']['permissionDecision'] == 'deny'
    assert codex_tool(data, tool_input={'command': 'cat seed.txt'}) == {}
    next_turn = 'next-user-turn'
    start, message = copy.deepcopy(events[1]), copy.deepcopy(events[3])
    start['payload']['turn_id'] = next_turn
    start['payload']['turn_attribution'].update(turn_id=next_turn, root_turn_id=next_turn)
    message['payload']['internal_chat_message_metadata_passthrough']['turn_id'] = next_turn
    codex_text([message], 'Implement the change')
    events.extend([
        {'type': 'event_msg', 'payload': {'type': 'task_complete', 'turn_id': data['turn_id']}},
        start, message, codex_item('skill_injection', turn_id=next_turn),
    ])
    save_events(data, events)
    assert codex_tool(data, turn_id=next_turn) == {}


@pytest.mark.parametrize('text', [
    '$ioncache-ai-tools:investigate why does it fail?',
    '  [$ioncache-ai-tools:investigate](skill:///plugin/skills/investigate/SKILL.md) why does it fail?',
])
def test_codex_leading_skill_invocation_is_an_instruction(codex_question, text):
    data, events = codex_question
    codex_text(events, text)
    events.append(codex_item('skill_injection'))
    save_events(data, events)
    marker_path(data).write_text('')
    assert codex_tool(data) == {}


@pytest.mark.parametrize('item', [
    {'content_item_kinds': ['skills.selected_skill_instructions', 'user.text']},
    {'content_item_kinds': []},
    {'content_item_kinds': None},
    {'turn_id': 'other-turn'},
])
def test_codex_unrecognized_later_input_releases_the_question(codex_question, item):
    data, events = codex_question
    assert codex_tool(data)['hookSpecificOutput']['permissionDecision'] == 'deny'
    events.append(codex_item('skill_injection', **item))
    save_events(data, events)
    assert codex_tool(data) == {}


def test_codex_first_authored_input_owns_the_turn(codex_question):
    data, events = codex_question
    image = copy.deepcopy(events[-1])
    image['payload']['internal_chat_message_metadata_passthrough']['content_item_kinds'] = ['user.image']
    image['payload']['content'] = [{'type': 'input_image', 'image_url': 'data:image/png;base64,AA=='}]
    events.insert(2, image)
    save_events(data, events)
    marker_path(data).write_text('')
    assert codex_tool(data) == {}
