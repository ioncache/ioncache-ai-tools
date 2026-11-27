const MESSAGE_FIELDS = {
  SubagentHandback: ['message'],
  SendMessage: ['message', 'content', 'summary'],
};

export async function readResponse(stream) {
  const chunks = [];
  let step;
  try {
    step = await stream.next();
    while (!step.done) {
      chunks.push(step.value);
      step = await stream.next();
    }
    return { chunks, result: step.value, interrupted: false };
  } catch {
    return { chunks, interrupted: true };
  } finally {
    if (!step?.done) {
      try {
        await stream.return();
      } catch {}
    }
  }
}

export function responseDrafts(chunks) {
  const text = new Map();
  const tools = new Map();
  for (const chunk of chunks) {
    if (chunk.kind === 'text') {
      text.set(chunk.index, (text.get(chunk.index) || '') + chunk.text);
    } else if (chunk.kind === 'tool' && MESSAGE_FIELDS[chunk.name]) {
      tools.set(chunk.index, { name: chunk.name, json: '' });
    } else if (chunk.kind === 'input' && tools.has(chunk.index)) {
      tools.get(chunk.index).json += chunk.json;
    }
  }
  const drafts = [...text].filter(([, value]) => value.trim())
    .map(([index, value]) => ({ id: `text:${index}`, text: value }));
  for (const [index, tool] of tools) {
    try {
      tool.input = JSON.parse(tool.json);
    } catch {
      tool.input = null;
    }
    if (tool.input === null || typeof tool.input !== 'object' || Array.isArray(tool.input)) {
      tools.delete(index);
      continue;
    }
    for (const field of MESSAGE_FIELDS[tool.name]) {
      if (typeof tool.input[field] === 'string' && tool.input[field].trim()) {
        drafts.push({ id: `tool:${index}:${field}`, text: tool.input[field] });
      }
    }
  }
  return { drafts, tools };
}

export function rewriteResponse(chunks, response, edits) {
  const replacements = new Map();
  for (const [index, tool] of response.tools) {
    const input = { ...tool.input };
    let changed = false;
    for (const field of MESSAGE_FIELDS[tool.name]) {
      const id = `tool:${index}:${field}`;
      if (edits.has(id)) {
        input[field] = edits.get(id);
        changed = true;
      }
    }
    if (changed) replacements.set(index, JSON.stringify(input));
  }
  const emitted = new Set();
  return chunks.map(chunk => {
    const id = `text:${chunk.index}`;
    if (chunk.kind === 'text' && edits.has(id)) {
      const text = emitted.has(id) ? '' : edits.get(id);
      emitted.add(id);
      return { ...chunk, text };
    }
    if (chunk.kind === 'input' && replacements.has(chunk.index)) {
      const key = `tool:${chunk.index}`;
      const json = emitted.has(key) ? '' : replacements.get(chunk.index);
      emitted.add(key);
      return { ...chunk, json };
    }
    return chunk;
  });
}

export function rewrittenResult(result, chunks, response) {
  const indices = chunks.filter(chunk => chunk.kind === 'tool').map(chunk => chunk.index);
  const toolUses = (result.toolUses || []).map((tool, ordinal) => {
    const index = indices[ordinal];
    if (!response.tools.has(index)) return tool;
    const json = chunks.filter(chunk => chunk.kind === 'input' && chunk.index === index)
      .map(chunk => chunk.json).join('');
    return { ...tool, input: JSON.parse(json) };
  });
  return {
    ...result,
    answer: chunks.filter(chunk => chunk.kind === 'text').map(chunk => chunk.text).join(''),
    toolUses,
  };
}

export function cancelledResult(result) {
  return { ...result, answer: '', toolUses: [], stopReason: null };
}
