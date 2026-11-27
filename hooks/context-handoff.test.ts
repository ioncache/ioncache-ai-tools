import { expect, test } from 'claude-code/testing';

const MESSAGES = [
  { role: 'user', text: 'Only change the README.', toolUses: [], handle: 'user-handle' },
  { role: 'assistant', text: '', toolUses: [
    { tool_use_id: 'read-1', tool: 'Read', input: { file_path: 'README.md' } },
  ], handle: 'tool-handle' },
  { role: 'user', text: '', toolUses: [], toolResults: [
    { tool_use_id: 'read-1', text: '# Project' },
  ], handle: 'result-handle' },
];

function backend(on) {
  const state = {
    enabled: true, configError: false, configText: undefined, configStderr: '',
    truncated: false, skip: undefined, compactError: false,
    compactions: [], reads: [], notices: [],
    result: { messages: [
      { role: 'user', text: 'Goal: shorten README. Next: inspect README.', toolUses: [], handle: 'summary' },
      ...MESSAGES.slice(1),
    ], tokensBefore: 90000, tokensAfter: 8000, usage: {
      input_tokens: 90000, output_tokens: 1000, cache_creation_input_tokens: 0, cache_read_input_tokens: 0,
    } },
  };
  on('session.cwd', () => ({ value: '/fixture with spaces' }));
  on('process.run', ($, e) => {
    state.reads.push(e.argv);
    return { value: {
      exitCode: state.configError ? 1 : 0,
      stdout: state.configText ?? JSON.stringify({ enabled: state.enabled }),
      stderr: state.configStderr, isStdoutTruncated: state.truncated, isStderrTruncated: false,
    } };
  });
  on('ui.log', ($, e) => {
    state.notices.push(e);
    return { value: undefined };
  });
  on('session.compact', ($, e) => {
    state.compactions.push(e);
    if (state.compactError) throw new Error('Native compaction failed');
    return state.skip ? { skip: state.skip } : state.result;
  });
  on('command.run', () => ({ text: 'Ordinary work continued.' }));
  return state;
}

test('native compaction gets task handoff instructions without changing messages or metadata', async ($, on) => {
  const state = backend(on);
  const result = await $.session.compact({
    trigger: 'auto', messages: MESSAGES, instructions: 'Keep the release target.',
  });

  expect(state.compactions.length).toBe(1);
  expect(state.compactions[0].trigger).toBe('auto');
  expect(state.compactions[0].messages).toEqual(MESSAGES);
  expect(state.compactions[0].instructions).toStartWith('Keep the release target.');
  expect(state.compactions[0].instructions).toMatch('User instructions: quote');
  expect(state.compactions[0].instructions).toMatch('A question remains answer-only');
  expect(result).toEqual(state.result);
});

test('manual and precomputed handoffs use the same native boundary without forcing a swap', async ($, on) => {
  const state = backend(on);
  for (const trigger of ['manual', 'plugin', 'precompute']) {
    await $.session.compact({ trigger, messages: MESSAGES });
  }
  expect(state.compactions.map(e => e.trigger)).toEqual(['manual', 'plugin', 'precompute']);
  for (const event of state.compactions) {
    expect(event.messages).toEqual(MESSAGES);
    expect(event.instructions).toMatch('self-contained task handoff');
  }
});

test('child compaction stays unchanged even when root settings are unavailable', async ($, on) => {
  const state = backend(on);
  state.configError = true;
  await $.session.compact({
    trigger: 'auto', agentId: 'child-1', messages: MESSAGES, instructions: 'Child task only.',
  });
  expect(state.reads).toEqual([]);
  expect(state.notices).toEqual([]);
  expect(state.compactions[0].agentId).toBe('child-1');
  expect(state.compactions[0].instructions).toBe('Child task only.');
});

test('disabling and re-enabling is effective without stale state or a session restart', async ($, on) => {
  const state = backend(on);
  state.enabled = false;
  await $.session.compact({ trigger: 'manual', messages: MESSAGES, instructions: 'Caller summary.' });
  expect(state.compactions[0].instructions).toBe('Caller summary.');
  state.enabled = true;
  await $.session.compact({ trigger: 'manual', messages: MESSAGES, instructions: 'Caller summary.' });
  expect(state.compactions[1].instructions).toMatch('self-contained task handoff');
  expect(state.reads.length).toBe(2);
});

test('settings failure falls back to native compaction and a corrected request can proceed', async ($, on) => {
  const state = backend(on);
  state.configError = true;
  const result = await $.session.compact({ trigger: 'auto', messages: MESSAGES, instructions: 'Original.' });
  expect(result).toEqual(state.result);
  expect(state.compactions[0].instructions).toBe('Original.');
  expect(state.notices.length).toBe(1);
  expect((await $.command.run({ command: 'fixture-work' })).text).toBe('Ordinary work continued.');

  state.configError = false;
  await $.session.compact({ trigger: 'auto', messages: MESSAGES });
  expect(state.compactions[1].instructions).toMatch('self-contained task handoff');
});

test('malformed and truncated settings do not veto native compaction', async ($, on) => {
  const state = backend(on);
  for (const text of ['not json', '{}', '{"enabled":"true"}']) {
    state.configText = text;
    await $.session.compact({ trigger: 'auto', messages: MESSAGES, instructions: 'Original.' });
  }
  state.configText = '{"enabled":true}';
  state.truncated = true;
  await $.session.compact({ trigger: 'auto', messages: MESSAGES, instructions: 'Original.' });
  state.truncated = false;
  state.configText = '{"enabled":false}';
  state.configStderr = 'plugin-config: plugin features paused until this configuration is repaired.';
  await $.session.compact({ trigger: 'auto', messages: MESSAGES, instructions: 'Original.' });
  expect(state.compactions.length).toBe(5);
  expect(state.notices.length).toBe(5);
  expect(state.compactions.map(e => e.instructions)).toEqual(Array(5).fill('Original.'));
});

test('another compaction veto remains a veto and causes no automatic retry', async ($, on) => {
  const state = backend(on);
  state.skip = 'Native work is still running.';
  expect(await $.session.compact({ trigger: 'plugin', messages: MESSAGES }))
    .toEqual({ skip: state.skip });
  expect(state.compactions.length).toBe(1);
  expect((await $.command.run({ command: 'fixture-work' })).text).toBe('Ordinary work continued.');
  state.skip = undefined;
  expect(await $.session.compact({ trigger: 'plugin', messages: MESSAGES })).toEqual(state.result);
});

test('native compaction errors are not relabelled as success or retried', async ($, on) => {
  const state = backend(on);
  state.compactError = true;
  await expect($.session.compact({ trigger: 'auto', messages: MESSAGES })).rejects.toThrow();
  expect(state.compactions.length).toBe(1);
  state.compactError = false;
  expect(await $.session.compact({ trigger: 'auto', messages: MESSAGES })).toEqual(state.result);
});
