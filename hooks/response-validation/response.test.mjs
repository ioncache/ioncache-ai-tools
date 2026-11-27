import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { evidencePacket, parseEdits, MAX_DRAFT_CHARACTERS } from './reviewer.mjs';
import { responseDrafts, rewriteResponse, rewrittenResult } from './response.mjs';
import { register, validateResponse, unavailableResponse } from './register.mjs';

async function collect(stream) {
  const chunks = [];
  let step = await stream.next();
  while (!step.done) {
    chunks.push(step.value);
    step = await stream.next();
  }
  return { chunks, result: step.value };
}

test('malformed host settings explain the failure and repaired opt-ins resume review', async t => {
  const root = mkdtempSync(join(tmpdir(), 'response-config-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const env = {
    ...process.env, HOME: join(root, 'home'),
    COPILOT_HOME: join(root, 'copilot'), CODEX_HOME: join(root, 'codex'),
  };
  const paths = [join(env.HOME, '.claude'), env.COPILOT_HOME, env.CODEX_HOME]
    .map(directory => {
      mkdirSync(directory, { recursive: true });
      return join(directory, 'ioncache-ai-tools.local.json');
    });
  writeFileSync(paths[1], '{broken');
  const diagnostics = [];
  let reviews = 0;
  let historyReads = 0;
  const api = {
    plugin: { root: fileURLToPath(new URL('../../', import.meta.url)) },
    process: { run: async (command, options) => {
      const result = spawnSync(command[0], command.slice(1), {
        cwd: options.cwd, env, encoding: 'utf8', timeout: options.timeoutMs,
      });
      assert.ifError(result.error);
      diagnostics.push(result.stderr);
      return { exitCode: result.status, stdout: result.stdout, stderr: result.stderr, isStdoutTruncated: false };
    } },
    session: {
      cwd: async () => root,
      messages: async () => {
        historyReads++;
        return [{ role: 'user', text: 'Only the local key was tested.' }];
      },
    },
    model: { complete: async () => {
      reviews++;
      return { isAnswered: true, text: '{"edits":[{"id":"text:0","text":"Only the local key was tested."}]}' };
    } },
  };
  const draft = { kind: 'text', index: 0, text: 'The deployed key was tested.' };
  const next = async function* () {
    yield draft;
    return { answer: draft.text, toolUses: [], stopReason: 'end_turn' };
  };
  const paused = validateResponse(api, { turnId: 'turn', index: 0 }, next);
  const text = '[Response could not be validated: The configuration query failed (exit code 1).]\n\n' + draft.text;
  assert.deepEqual(await paused.next(), { done: false, value: { ...draft, text } });
  assert.equal((await paused.next()).value.answer, text);
  assert.equal(reviews, 0);
  assert.equal(historyReads, 0);
  assert.match(diagnostics[0], /synchronization failed/);
  assert.equal(readFileSync(paths[1], 'utf8'), '{broken');

  for (const path of paths) writeFileSync(path, '{"features":{"response-validation":true}}');
  const resumed = validateResponse(api, { turnId: 'turn', index: 1 }, next);
  assert.equal((await resumed.next()).value.text, 'Only the local key was tested.');
  assert.equal((await resumed.next()).value.answer, 'Only the local key was tested.');
  assert.equal(reviews, 1);
  assert.equal(historyReads, 1);
  assert.equal(diagnostics[1], '');

  writeFileSync(paths[1], '{"features":{"response-validation":false}}');
  const disabled = await collect(validateResponse(api, { turnId: 'turn', index: 2 }, next));
  assert.deepEqual(disabled.chunks, [draft]);
  assert.equal(disabled.result.answer, draft.text);
  assert.equal(reviews, 1);
  assert.equal(historyReads, 1);
});

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

test('unvalidated reasons must identify known drafts and a supported, specific reason', () => {
  const drafts = [{ id: 'text:0', text: 'The deployed key was tested.' }];
  const reason = { id: 'text:0', reason: 'missing_evidence', detail: 'Deployment evidence is absent.' };
  for (const unvalidated of [
    null, {}, [null], [reason, reason], [{ ...reason, id: 'text:1' }],
    [{ ...reason, reason: 'api-error' }], [{ ...reason, reason: '__proto__' }],
    [{ ...reason, reason: ['missing_evidence'] }],
    [{ ...reason, detail: '' }], [{ ...reason, detail: 'x'.repeat(2001) }],
    [{ ...reason, other: true }],
  ]) {
    assert.throws(() => parseEdits(JSON.stringify({ edits: [], unvalidated }), drafts),
      /invalid validation reasons/);
  }
});

test('configuration, history and model exceptions preserve answers without exposing raw errors', async () => {
  for (const [stage, reason] of [
    ['configuration', 'The configuration lookup failed unexpectedly.'],
    ['history', 'The sending agent\'s history could not be read.'],
    ['review', 'The reviewer request failed unexpectedly.'],
  ]) {
    const fail = () => { throw new Error('private-error-body'); };
    const api = {
      plugin: { root: '/plugin' },
      process: { run: stage === 'configuration' ? fail : async () => ({ exitCode: 0, stdout: '{"enabled":true}' }) },
      session: { cwd: async () => '/project', messages: stage === 'history' ? fail : async () => [] },
      model: { complete: stage === 'review' ? fail : async () => ({ isAnswered: true, text: '{"edits":[]}' }) },
    };
    const next = async function* () {
      yield { kind: 'text', index: 0, text: 'The original answer.', ref: 17 };
      return { answer: 'The original answer.', toolUses: [], stopReason: 'end_turn' };
    };
    const output = await collect(validateResponse(api, { turnId: 'turn', index: 0 }, next));
    const text = `[Response could not be validated: ${reason}]\n\nThe original answer.`;
    assert.deepEqual(output.chunks, [{ kind: 'text', index: 0, text, ref: 17 }]);
    assert.equal(output.result.answer, text);
    assert.ok(!JSON.stringify(output).includes('private-error-body'));
  }
});

for (const [reason, config] of [
  ['The configuration query output was truncated.', { stdout: '{"enabled":true}', isStdoutTruncated: true }],
  ['The configuration query returned invalid JSON.', { stdout: '{broken' }],
  ['The configuration query returned an invalid setting.', { stdout: '{"enabled":"false"}' }],
]) {
  test(`unusable settings preserve the response: ${reason}`, async () => {
    let historyReads = 0;
    let reviews = 0;
    const api = {
      plugin: { root: '/plugin' },
      process: { run: async () => ({ exitCode: 0, ...config }) },
      session: { cwd: async () => '/project', messages: async () => { historyReads++; return []; } },
      model: { complete: async () => { reviews++; return { isAnswered: true, text: '{"edits":[]}' }; } },
    };
    const next = async function* () {
      yield { kind: 'text', index: 0, text: 'The original answer.' };
      return { answer: 'The original answer.', toolUses: [], stopReason: 'end_turn' };
    };
    const output = await collect(validateResponse(api, { turnId: 'turn', index: 0 }, next));
    const text = `[Response could not be validated: ${reason}]\n\nThe original answer.`;
    assert.deepEqual(output.chunks, [{ kind: 'text', index: 0, text }]);
    assert.equal(output.result.answer, text);
    assert.equal(historyReads, 0);
    assert.equal(reviews, 0);
  });
}

test('registered catch retains consumed chunk handles and respects explicit cancellation', async () => {
  let handler;
  let fallback;
  register((name, hook) => {
    assert.equal(name, 'turn.step');
    handler = hook;
    return { catch: hook => { fallback = hook; } };
  });
  const api = {
    plugin: { root: '/plugin' },
    process: { run: async () => ({ exitCode: 0, stdout: '{"enabled":true}' }) },
    session: { cwd: async () => '/project', messages: async () => [] },
    model: { complete: async () => ({ isAnswered: true, text: '{"edits":[]}' }) },
  };
  let reads = 0;
  const input = { message: 'The targeted test passed.', reportPath: '/private/report' };
  const toolUses = [{ name: 'SubagentHandback', input }];
  const chunks = [
    { kind: 'text', index: 0, text: 'The answer.', ref: 1 },
    { kind: 'tool', index: 1, name: 'SubagentHandback', id: 'handback', ref: 2 },
    { kind: 'input', index: 1, json: JSON.stringify(input), ref: 3 },
    { kind: 'stop', stopReason: 'tool_use', usage: null, ref: 4 },
  ];
  const source = (async function* () {
    reads++;
    yield* chunks;
    return { answer: 'The answer.', toolUses, stopReason: 'tool_use' };
  })();
  const next = Object.assign(() => source, { called: true, error: { kind: 'timeout' } });
  const event = { turnId: 'turn', index: 0 };
  const held = handler(api, event, next);
  await held.next();
  await held.return();
  const output = await collect(fallback({}, event, next));
  const prefix = '[Response could not be validated: The response validation hook exceeded its execution time limit.]\n\n';
  assert.equal(output.result.answer, prefix + 'The answer.');
  assert.deepEqual(output.result.toolUses, [{ name: 'SubagentHandback', input: { ...input, message: prefix + input.message } }]);
  assert.deepEqual(output.chunks.map(chunk => chunk.ref), [1, 2, 3, 4]);
  assert.deepEqual(JSON.parse(output.chunks[2].json), output.result.toolUses[0].input);
  assert.equal(output.result.stopReason, 'tool_use');
  assert.equal(reads, 1);

  const controller = new AbortController();
  const cancelSource = (async function* () {
    yield* chunks;
    return { answer: 'The answer.', toolUses, stopReason: 'tool_use' };
  })();
  const cancelNext = Object.assign(() => cancelSource, { signal: controller.signal });
  const cancelEvent = { turnId: 'turn', index: 1 };
  const cancelling = handler(api, cancelEvent, cancelNext);
  await cancelling.next();
  controller.abort();
  await cancelling.return();
  const cancelled = await collect(fallback({}, cancelEvent, cancelNext));
  assert.deepEqual(cancelled.chunks, []);
  assert.equal(cancelled.result.answer, '');
  assert.deepEqual(cancelled.result.toolUses, []);
  assert.equal(reads, 1);
});

for (const handler of [validateResponse, unavailableResponse]) {
  for (const interrupted of [false, true]) {
    test(`${handler.name} drops source-time cancellation before ${interrupted ? 'rejection' : 'completion'}`, async () => {
      const controller = new AbortController();
      let reviews = 0;
      const api = {
        plugin: { root: '/plugin' },
        process: { run: async () => ({ exitCode: 0, stdout: '{"enabled":true}' }) },
        session: { cwd: async () => '/project', messages: async () => [] },
        model: { complete: async () => { reviews++; return { isAnswered: true, text: '{"edits":[]}' }; } },
      };
      const next = Object.assign(async function* () {
        yield { kind: 'text', index: 0, text: 'Held answer.' };
        yield { kind: 'tool', index: 1, id: 'send', name: 'SendMessage' };
        yield { kind: 'input', index: 1, json: '{"message":"Held handback."}' };
        controller.abort();
        if (interrupted) throw new Error('cancelled source');
        return { answer: 'Held answer.', toolUses: [{ name: 'SendMessage', input: { message: 'Held handback.' } }] };
      }, { signal: controller.signal });
      const output = await collect(handler(api, { turnId: 'turn', index: 0 }, next));
      assert.deepEqual(output.chunks, []);
      assert.equal(output.result.answer, '');
      assert.deepEqual(output.result.toolUses, []);
      assert.equal(output.result.stopReason, null);
      assert.equal(reviews, 0);
    });
  }
}

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
