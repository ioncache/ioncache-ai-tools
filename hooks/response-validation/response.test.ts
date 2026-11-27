import { expect, test } from 'claude-code/testing';
import { UNAVAILABLE } from './reviewer.mjs';

function setup(on, options = {}) {
  const calls = { model: [], history: [], source: 0 };
  on('session.cwd', () => ({ value: '/fixture' }));
  on('process.run', () => ({ value: {
    exitCode: options.configError ? 1 : 0,
    stdout: JSON.stringify({ enabled: options.enabled !== false }),
    stderr: '', isStdoutTruncated: false, isStderrTruncated: false,
  } }));
  on('session.messages', ($, event) => {
    calls.history.push(event);
    return { value: options.history || [{ role: 'user', text: 'Only the local key was tested.', toolUses: [] }] };
  });
  on('model.complete', async ($, event) => {
    calls.model.push(event);
    if (options.review) return { value: await options.review(event) };
    return { value: { isAnswered: true, text: options.verdict || '{"edits":[]}', usage: {} } };
  });
  on('turn.step', async function* ($, event) {
    calls.source++;
    const chunks = options.chunks || [
      { kind: 'text', index: 0, text: 'The deployed key ' },
      { kind: 'text', index: 0, text: 'was tested.' },
    ];
    for (const chunk of chunks) yield chunk;
    if (options.streamError) throw new Error('source interrupted');
    return {
      turnId: event.turnId, index: event.index, answer: 'The deployed key was tested.',
      toolUses: options.toolUses || [], stopReason: options.stopReason || 'end_turn', usage: null,
    };
  });
  return calls;
}

function step($, agentId, index = 0) {
  return $.turn.step({ turnId: `turn-${agentId || 'main'}`, index, model: 'claude-test', messageCount: 1, agentId });
}

async function collect(stream) {
  const chunks = [];
  let result = await stream.next();
  while (!result.done) {
    chunks.push(result.value);
    result = await stream.next();
  }
  return { chunks, result: result.value, text: chunks.filter(c => c.kind === 'text').map(c => c.text).join('') };
}

test('holds all text until review finishes and releases only the rewrite', async ($, on) => {
  let entered;
  let finish;
  const reviewing = new Promise(resolve => { entered = resolve; });
  const verdict = new Promise(resolve => { finish = resolve; });
  const calls = setup(on, { review: async () => { entered(); return verdict; } });
  const stream = step($);
  let delivered = false;
  const first = stream.next().then(value => { delivered = true; return value; });
  await reviewing;
  expect(delivered).toBe(false);
  finish({ isAnswered: true, text: '{"edits":[{"id":"text:0","text":"Only the local key was tested."}]}', usage: {} });
  const initial = await first;
  const rest = await collect(stream);
  expect(initial.value.text + rest.text).toBe('Only the local key was tested.');
  expect(rest.result.answer).toBe('Only the local key was tested.');
  expect(calls.model.length).toBe(1);
  expect(calls.source).toBe(1);
  expect(calls.model[0].model).toBe('haiku');
});

test('reviews each interim and final response without reading parent history for a child', async ($, on) => {
  const calls = setup(on);
  await collect(step($, 'child', 0));
  await collect(step($, 'child', 1));
  expect(calls.history.map(call => call.agentId)).toEqual(['child', 'child']);
  expect(calls.model.length).toBe(2);
});

test('rewrites handback arguments before yielding them and preserves other tool calls', async ($, on) => {
  const original = { message: 'The deployed key was tested.', reportPath: '/private/report' };
  const chunks = [
    { kind: 'tool', index: 0, id: 'read', name: 'Read' },
    { kind: 'input', index: 0, json: '{"file_path":"file.py"}' },
    { kind: 'tool', index: 1, id: 'handback', name: 'SubagentHandback' },
    { kind: 'input', index: 1, json: '{"message":"The deployed key ' },
    { kind: 'input', index: 1, json: 'was tested.","reportPath":"/private/report"}' },
  ];
  setup(on, {
    chunks,
    toolUses: [{ name: 'Read', input: { file_path: 'file.py' } }, { name: 'SubagentHandback', input: original }],
    verdict: '{"edits":[{"id":"tool:1:message","text":"Only the local key was tested."}]}',
  });
  const output = await collect(step($, 'child'));
  expect(output.chunks.slice(0, 3)).toEqual(chunks.slice(0, 3));
  const input = JSON.parse(output.chunks.filter(c => c.kind === 'input' && c.index === 1).map(c => c.json).join(''));
  expect(input).toEqual({ ...original, message: 'Only the local key was tested.' });
  expect(output.result.toolUses[1].input).toEqual(input);
});

for (const malformed of ['{"message":', 'null']) {
  test(`invalid message arguments ${malformed} do not discard other calls or drafts`, async ($, on) => {
    const read = { name: 'Read', input: { file_path: 'file.py' } };
    const broken = { name: 'SendMessage', input: malformed };
    const handback = { name: 'SubagentHandback', input: { message: 'The deployed key was tested.' } };
    const chunks = [
      { kind: 'tool', index: 0, id: 'read', name: read.name },
      { kind: 'input', index: 0, json: JSON.stringify(read.input) },
      { kind: 'tool', index: 1, id: 'broken', name: broken.name },
      { kind: 'input', index: 1, json: malformed },
      { kind: 'tool', index: 2, id: 'handback', name: handback.name },
      { kind: 'input', index: 2, json: JSON.stringify(handback.input) },
      { kind: 'text', index: 3, text: 'The deployed key was tested.' },
      { kind: 'stop', stopReason: 'tool_use', usage: null },
    ];
    const calls = setup(on, {
      chunks, toolUses: [read, broken, handback], stopReason: 'tool_use',
      verdict: JSON.stringify({ edits: [
        { id: 'tool:2:message', text: 'Only the local key was tested.' },
        { id: 'text:3', text: 'Only the local key was tested.' },
      ] }),
    });
    const output = await collect(step($, 'child'));
    expect(output.chunks.slice(0, 5)).toEqual(chunks.slice(0, 5));
    expect(JSON.parse(output.chunks[5].json).message).toBe('Only the local key was tested.');
    expect(output.text).toBe('Only the local key was tested.');
    expect(output.result.answer).toBe(output.text);
    expect(output.result.toolUses).toEqual([
      read, broken, { ...handback, input: { message: 'Only the local key was tested.' } },
    ]);
    expect(output.result.stopReason).toBe('tool_use');
    expect(output.chunks.at(-1)).toEqual(chunks.at(-1));
    expect(calls.model.length).toBe(1);
  });
}

test('a reviewer failure replaces the draft without preventing the next response', async ($, on) => {
  let attempts = 0;
  setup(on, { review: async () => ++attempts === 1
    ? { isAnswered: false, reason: 'aborted', usage: null }
    : { isAnswered: true, text: '{"edits":[]}', usage: {} } });
  expect((await collect(step($))).text).toBe(UNAVAILABLE);
  expect((await collect(step($, undefined, 1))).text).toBe('The deployed key was tested.');
  expect(attempts).toBe(2);
});

test('malformed edits never release the unvalidated draft', async ($, on) => {
  setup(on, { verdict: '{"edits":[{"id":"not-a-draft","text":"Made up."}]}' });
  const output = await collect(step($));
  expect(output.text).toBe(UNAVAILABLE);
  expect(output.result.answer).toBe(UNAVAILABLE);
});

test('unavailable child history does not fall back to the root conversation', async ($, on) => {
  const calls = setup(on, { history: { deny: 'Agent not readable' } });
  expect((await collect(step($, 'missing'))).text).toBe(UNAVAILABLE);
  expect(calls.history.length).toBe(1);
  expect(calls.model.length).toBe(0);
});

test('explicit opt-out streams unchanged without history or reviewer calls', async ($, on) => {
  const calls = setup(on, { enabled: false });
  expect((await collect(step($))).text).toBe('The deployed key was tested.');
  expect(calls.model.length).toBe(0);
  expect(calls.history.length).toBe(0);
});

test('configuration failure replaces text while leaving a tool call intact', async ($, on) => {
  const tool = { kind: 'tool', index: 1, id: 'read', name: 'Read' };
  const input = { kind: 'input', index: 1, json: '{"file_path":"file.py"}' };
  const calls = setup(on, { configError: true, chunks: [
    { kind: 'text', index: 0, text: 'Unsupported draft' }, tool, input,
  ] });
  const output = await collect(step($));
  expect(output.text).toBe(UNAVAILABLE);
  expect(output.chunks.slice(1)).toEqual([tool, input]);
  expect(calls.model.length).toBe(0);
});

test('tool-only responses need no model review', async ($, on) => {
  const chunks = [
    { kind: 'tool', index: 0, id: 'read', name: 'Read' },
    { kind: 'input', index: 0, json: '{"file_path":"file.py"}' },
  ];
  const calls = setup(on, { chunks });
  expect((await collect(step($))).chunks).toEqual(chunks);
  expect(calls.model.length).toBe(0);
});

test('a broken source stream does not leak buffered text through native hook fallback', async ($, on) => {
  setup(on, { streamError: true });
  const output = await collect(step($));
  expect(output.text).toBe(UNAVAILABLE);
});

test('concurrent agents have independent buffered responses and evidence', async ($, on) => {
  let started;
  let finish;
  const waiting = new Promise(resolve => { started = resolve; });
  const verdict = new Promise(resolve => { finish = resolve; });
  let count = 0;
  const calls = setup(on, { review: async () => {
    if (++count === 1) { started(); return verdict; }
    return { isAnswered: true, text: '{"edits":[]}', usage: {} };
  } });
  const child = collect(step($, 'child'));
  await waiting;
  const root = await collect(step($));
  expect(root.text).toBe('The deployed key was tested.');
  finish({ isAnswered: true, text: '{"edits":[{"id":"text:0","text":"Child correction."}]}', usage: {} });
  expect((await child).text).toBe('Child correction.');
  expect(calls.history.map(call => call.agentId)).toEqual(['child', undefined]);
});

test('oversized drafts are replaced without sending an unbounded reviewer request', async ($, on) => {
  const calls = setup(on, { chunks: [{ kind: 'text', index: 0, text: 'x'.repeat(64001) }] });
  expect((await collect(step($))).text).toBe(UNAVAILABLE);
  expect(calls.model.length).toBe(0);
});

test('a correction to one block leaves the other block unchanged', async ($, on) => {
  setup(on, {
    chunks: [
      { kind: 'text', index: 0, text: 'Okay.' },
      { kind: 'text', index: 1, text: 'All environments passed.' },
    ],
    verdict: '{"edits":[{"id":"text:1","text":"Only the local check passed."}]}',
  });
  expect((await collect(step($))).chunks.map(chunk => chunk.text)).toEqual([
    'Okay.', 'Only the local check passed.',
  ]);
});
