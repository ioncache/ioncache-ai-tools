import {
  featureEnabled, reviewDrafts, unavailableEdits, failureReason, validationNotice, ValidationFailure,
} from './reviewer.mjs';
import { readResponse, responseDrafts, rewriteResponse, rewrittenResult, cancelledResult } from './response.mjs';

export function register(on) {
  const responses = new WeakMap();
  on('turn.step', async function* ($, event, next) {
    const buffer = {};
    responses.set(event, buffer);
    const result = yield* validateResponse($, event, next, buffer);
    if (!next.signal?.aborted) responses.delete(event);
    return result;
  }).catch(async function* ($, event, next) {
    const buffer = responses.get(event);
    responses.delete(event);
    return yield* unavailableResponse($, event, next, buffer);
  });
}

export async function* validateResponse($, event, next, buffer = {}) {
  let enabled;
  let configurationFailure;
  try {
    enabled = await featureEnabled($);
  } catch (error) {
    enabled = null;
    configurationFailure = failureReason(error, 'The configuration lookup failed unexpectedly.');
  }
  if (enabled === false) return yield* next(event);
  const source = await (buffer.source = readResponse(next(event)));
  if (next.signal?.aborted) return cancelledResult(source.result);
  if (source.interrupted) return yield* failedResponse(source, event);
  const { chunks } = source;
  const response = responseDrafts(chunks);
  if (!response.drafts.length) {
    yield* chunks;
    return source.result;
  }
  let edits;
  try {
    if (enabled === null) throw new ValidationFailure(configurationFailure);
    edits = await reviewDrafts($, { drafts: response.drafts, agentId: event.agentId }, next.signal);
  } catch (error) {
    edits = unavailableEdits(response.drafts, failureReason(error, 'The response validator failed unexpectedly.'));
  }
  if (next.signal?.aborted) return cancelledResult(source.result);
  const rewritten = rewriteResponse(chunks, response, edits);
  const result = rewrittenResult(source.result, rewritten, response);
  yield* rewritten;
  return result;
}

export async function* unavailableResponse($, event, next, buffer = {}) {
  if (next.signal?.aborted) return cancelledResult({ turnId: event.turnId, index: event.index });
  const source = await (buffer.source ?? readResponse(next(event)));
  if (next.signal?.aborted) return cancelledResult(source.result);
  const reason = next.error?.kind === 'timeout'
    ? 'The response validation hook exceeded its execution time limit.'
    : 'The response validation hook failed unexpectedly.';
  return yield* failedResponse(source, event, reason);
}

function* failedResponse(source, event, reason) {
  let { chunks, result } = source;
  if (source.interrupted) {
    reason = 'The source response was interrupted; only received text is available.';
    chunks = chunks.filter(chunk => chunk.kind === 'text');
    result = { turnId: event.turnId, index: event.index, toolUses: [], stopReason: 'end_turn', usage: null };
    if (!chunks.some(chunk => chunk.text.trim())) {
      chunks = [{ kind: 'text', index: 0, text: validationNotice(reason) }];
    } else {
      const response = responseDrafts(chunks);
      chunks = rewriteResponse(chunks, response, unavailableEdits(response.drafts, reason));
    }
    chunks.push({ kind: 'stop', stopReason: 'end_turn', usage: null });
  } else {
    const response = responseDrafts(chunks);
    chunks = rewriteResponse(chunks, response, unavailableEdits(response.drafts, reason));
  }
  const response = responseDrafts(chunks);
  const output = rewrittenResult(result, chunks, response);
  yield* chunks;
  return output;
}
