import { featureEnabled, reviewDrafts, unavailableEdits, UNAVAILABLE } from './reviewer.mjs';
import { responseDrafts, rewriteResponse, rewrittenResult, cancelledResult } from './response.mjs';

export function register(on) {
  on('turn.step', validateResponse).catch(unavailableResponse);
}

export async function* validateResponse($, event, next) {
  let enabled;
  try {
    enabled = await featureEnabled($);
  } catch {
    enabled = null;
  }
  if (enabled === false) return yield* next(event);
  const stream = next(event);
  const chunks = [];
  let step;
  try {
    step = await stream.next();
    while (!step.done) {
      chunks.push(step.value);
      step = await stream.next();
    }
  } finally {
    if (!step?.done) await stream.return();
  }
  if (next.signal?.aborted) return cancelledResult(step.value);
  const response = responseDrafts(chunks);
  if (!response.drafts.length) {
    yield* chunks;
    return step.value;
  }
  let edits;
  try {
    if (enabled === null) throw new Error('Configuration unavailable');
    edits = await reviewDrafts($, { drafts: response.drafts, agentId: event.agentId }, next.signal);
  } catch {
    edits = unavailableEdits(response.drafts);
  }
  if (next.signal?.aborted) return cancelledResult(step.value);
  const rewritten = rewriteResponse(chunks, response, edits);
  const result = rewrittenResult(step.value, rewritten, response);
  yield* rewritten;
  return result;
}

export async function* unavailableResponse($, event, next) {
  if (!next.signal?.aborted) {
    yield { kind: 'text', index: 0, text: UNAVAILABLE };
    yield { kind: 'stop', stopReason: 'end_turn', usage: null };
  }
  return {
    turnId: event.turnId, index: event.index, answer: next.signal?.aborted ? '' : UNAVAILABLE,
    toolUses: [], stopReason: 'end_turn', usage: null,
  };
}
