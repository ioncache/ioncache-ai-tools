import assert from 'node:assert/strict';
import test from 'node:test';
import { evidencePacket, parseEdits, MAX_DRAFT_CHARACTERS } from './reviewer.mjs';
import { responseDrafts, rewriteResponse, rewrittenResult } from './response.mjs';
import { validateResponse } from './register.mjs';

test('reviewer edits must target each existing draft at most once', () => {
  const drafts = [{ id: 'text:0', text: 'The deployed key was tested.' }];
  for (const text of [
    'not JSON', '{"edits":null}', '{"edits":[],"other":true}',
    '{"edits":[{"id":"text:1","text":"Invented"}]}',
    '{"edits":[{"id":"text:0","text":""}]}',
    '{"edits":[{"id":"text:0","text":"x"},{"id":"text:0","text":"y"}]}',
    JSON.stringify({ edits: [{ id: 'text:0', text: 'x'.repeat(MAX_DRAFT_CHARACTERS + 1) }] }),
  ]) assert.throws(() => parseEdits(text, drafts));
  assert.deepEqual([...parseEdits('{"edits":[]}', drafts)], []);
});

test('bounded history keeps its incompleteness explicit and refuses missing identities', () => {
  assert.throws(() => evidencePacket({ deny: 'unavailable' }));
  const packet = evidencePacket([
    { role: 'user', text: 'Earlier evidence' },
    { role: 'assistant', text: 'x'.repeat(50000) },
    { role: 'user', text: 'Most recent result' },
  ]);
  assert.equal(packet.truncated, true);
  assert.equal(packet.messages.at(-1).text, 'Most recent result');
  assert.match(packet.coverage, /not complete evidence/);
  assert.equal(packet.messages[0].truncated, true);
});

test('the serialized evidence budget includes escaped excerpts and packet metadata', () => {
  const recent = { role: 'user', text: 'Most recent observation' };
  for (const content of ['x', '"\\\n']) {
    const packet = evidencePacket([
      { role: 'assistant', text: content.repeat(50000) }, recent,
    ]);
    assert.ok(JSON.stringify(packet).length <= 48000);
    assert.equal(packet.truncated, true);
    assert.deepEqual(packet.messages.at(-1), recent);
    assert.ok(packet.messages[0].excerpt.length > 0);
  }
});

test('rewrites preserve chunk handles, ordering and unrelated tool input', () => {
  const chunks = [
    { kind: 'engine', ref: 1 },
    { kind: 'text', index: 0, ref: 2, text: 'Local evidence ' },
    { kind: 'text', index: 0, ref: 3, text: 'proves prod works.' },
    { kind: 'tool', index: 1, name: 'Write', id: 'write', ref: 4 },
    { kind: 'input', index: 1, json: '{"content":"Do not rewrite code"}', ref: 5 },
    { kind: 'stop', stopReason: 'tool_use', usage: null, ref: 6 },
  ];
  const response = responseDrafts(chunks);
  const output = rewriteResponse(chunks, response, new Map([['text:0', 'Only local behavior was checked.']]));
  assert.equal(output[1].text, 'Only local behavior was checked.');
  assert.equal(output[2].text, '');
  assert.deepEqual(output.map(chunk => chunk.ref), chunks.map(chunk => chunk.ref));
  assert.deepEqual(output.slice(3), chunks.slice(3));
});

test('message payload review does not rewrite recipients or control fields', () => {
  const input = { to: 'worker', message: 'All tests passed.', resume: true };
  const chunks = [
    { kind: 'tool', index: 0, id: 'send', name: 'SendMessage' },
    { kind: 'input', index: 0, json: JSON.stringify(input) },
  ];
  const response = responseDrafts(chunks);
  const output = rewriteResponse(chunks, response, new Map([['tool:0:message', 'The targeted test passed.']]));
  assert.deepEqual(JSON.parse(output[1].json), { ...input, message: 'The targeted test passed.' });
});

test('identical tool messages keep separate corrections in the returned metadata', () => {
  const input = { message: 'All tests passed.' };
  const chunks = [0, 1].flatMap(index => [
    { kind: 'tool', index, id: `send-${index}`, name: 'SubagentHandback' },
    { kind: 'input', index, json: JSON.stringify(input) },
  ]);
  const response = responseDrafts(chunks);
  const rewritten = rewriteResponse(chunks, response, new Map([
    ['tool:0:message', 'First correction.'], ['tool:1:message', 'Second correction.'],
  ]));
  const result = rewrittenResult({
    toolUses: [0, 1].map(() => ({ name: 'SubagentHandback', input })),
  }, rewritten, response);
  assert.deepEqual(result.toolUses.map(tool => tool.input.message), ['First correction.', 'Second correction.']);
});

test('interruption during review discards buffered drafts and result metadata', async () => {
  const controller = new AbortController();
  const next = Object.assign(async function* () {
    yield { kind: 'text', index: 0, text: 'Unvalidated draft.' };
    return { answer: 'Unvalidated draft.', toolUses: [], stopReason: 'end_turn' };
  }, { signal: controller.signal });
  const api = {
    plugin: { root: '/plugin' },
    process: { run: async () => ({ exitCode: 0, stdout: '{"enabled":true}' }) },
    session: { cwd: async () => '/project', messages: async () => [] },
    model: { complete: async () => {
      controller.abort();
      return { isAnswered: false, reason: 'aborted' };
    } },
  };
  const result = await validateResponse(api, { turnId: 'turn', index: 0 }, next).next();
  assert.equal(result.done, true);
  assert.equal(result.value.answer, '');
  assert.deepEqual(result.value.toolUses, []);
});
