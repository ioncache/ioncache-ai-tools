const PANE = 'ioncache-plugin-settings';
const RECOVERY = 'Use /ioncache-ai-tools:plugin-settings --list for the text interface, or run the standalone plugin_settings.py helper.';

let snapshot;
let scope = 'project';
let project;
let busy = false;
let paneOpen = false;
let message = '';
let messageColor = 'green';
let scrollOffset = 0;
let layout;

function updateStatus($) {
  const label = scope === 'project' ? 'Project' : 'Global';
  if (!paneOpen || (snapshot && !snapshot.uiEnabled)) {
    $.ui.status(undefined);
  } else if (busy) {
    $.ui.status(label + ' | Reading settings...');
  } else if (!snapshot) {
    $.ui.status('Read failed | Refresh to retry');
  } else {
    $.ui.status(label + ' | PgUp/PgDn: scroll');
  }
}

async function closePane($) {
  await $.ui.close({ id: PANE });
  paneOpen = false;
  updateStatus($);
}

async function run($, args) {
  const root = $.plugin.root;
  const result = await $.process.run(
    ['python3', root + '/hooks/scripts/plugin_settings.py', ...args],
    { timeoutMs: 15000 },
  );
  if (result.exitCode !== 0) {
    throw new Error(result.stderr.trim() || 'Settings helper failed without a diagnostic.');
  }
  return result.stdout;
}

async function listOrChange($, args = '--list') {
  try {
    return { text: await run($, ['--command', args]), isTextDisplayOnly: true };
  } catch (error) {
    return { text: error.message + '\n' + RECOVERY, isTextDisplayOnly: true };
  }
}

async function refresh($, options = {}) {
  if (busy) return;
  busy = true;
  message = 'Reading settings...';
  messageColor = 'cyan';
  updateStatus($);
  $.ui.invalidate('ui.render');
  const requestedScope = options.scope || scope;
  try {
    const args = ['--json', '--ui'];
    if (project) args.push('--project', project);
    if (requestedScope === 'global') args.push('--global');
    if (options.change) args.push(options.change);
    const result = JSON.parse(await run($, args));
    if (result.version !== 1 || !Array.isArray(result.groups)) {
      throw new Error('Unsupported settings helper response.');
    }
    snapshot = result;
    project = result.project;
    scope = result.scope;
    message = result.saved.length ? 'Saved and verified across Claude, Copilot, and Codex.' : '';
    messageColor = 'green';
  } catch (error) {
    snapshot = undefined;
    message = 'No success confirmed. ' + error.message + '\n' + RECOVERY;
    messageColor = 'red';
  } finally {
    busy = false;
    updateStatus($);
    $.ui.invalidate('ui.render');
  }
}

function linesOf(text, columns) {
  return text.split('\n').flatMap(line => Array.from(
    { length: Math.max(1, Math.ceil(line.length / columns)) },
    (_, index) => line.slice(index * columns, (index + 1) * columns),
  ));
}

function settingRow($, elements, row) {
  const { Box, Text, Button } = elements;
  const { setting, columns, from = 0, count = row.height } = row;
  const nameColumns = Math.max(1, columns - 13);
  const name = linesOf(setting.name, nameColumns);
  const lines = name.slice(from, from + count);
  const checked = setting.enabled ? '[x]' : '[ ]';
  const state = setting.enabled ? 'enabled' : 'disabled';
  const override = row.override.slice(Math.max(0, from - name.length), Math.max(0, from + count - name.length));
  const height = lines.length + override.length;
  return Box({
    height, flexShrink: 0, flexDirection: 'column',
    children: [
      ...(lines.length ? [Button({
        key: setting.name, plain: true, label: setting.name + ' ' + checked,
        children: [
          Text({ children: [lines[0].padEnd(nameColumns) + ' '] }),
          Text({ color: setting.enabled ? 'green' : 'red', children: [checked + ' ' + state] }),
          ...(lines.length > 1 ? [Text({ children: ['\n' + lines.slice(1).join('\n')] })] : []),
        ],
        onPress: () => refresh($, { change: '--' + setting.name + '=' + (setting.enabled ? 'disabled' : 'enabled') }),
      })] : []),
      ...(override.length ? [Text({ color: 'yellow', children: [override.join('\n')] })] : []),
    ],
  });
}

function catalog(columns) {
  const entries = [];
  const items = [];
  let height = 0;
  if (busy) return { items, entries, height: layout?.contentRows || 0 };
  if (!snapshot?.uiEnabled) {
    const text = snapshot
      ? 'Native pane disabled. Re-enable with /ioncache-ai-tools:plugin-settings --hook:plugin-settings-ui=enabled.'
      : message;
    const lines = linesOf(text, columns);
    return { items: [{ top: 0, height: lines.length, lines, color: snapshot ? 'yellow' : 'red' }],
      entries, height: lines.length };
  }
  snapshot.groups.forEach((group, index) => {
    if (index) items.push({ top: height++, height: 1, lines: [''] });
    items.push({ key: 'group:' + group.title, top: height++, height: 1, color: 'cyan',
      lines: [group.title + ' (' + group.settings.length + ')'] });
    group.settings.forEach(setting => {
      const override = scope === 'global' && setting.enabled !== setting.effective
        ? linesOf('  Effective project: ' + (setting.effective ? 'enabled' : 'disabled'), columns) : [];
      const row = { key: setting.name, setting, columns, override, top: height,
        height: linesOf(setting.name, Math.max(1, columns - 13)).length + override.length };
      entries.push(row);
      items.push(row);
      height += row.height;
    });
  });
  return { items, entries, height };
}

function visibleRows($, elements, rows) {
  const { Box, Text } = elements;
  return rows.items.filter(row => row.top + row.height > scrollOffset &&
    row.top < scrollOffset + layout.listRows).map(row => {
    const from = Math.max(0, scrollOffset - row.top);
    const count = Math.min(row.height - from, scrollOffset + layout.listRows - row.top - from);
    if (row.setting) return settingRow($, elements, { ...row, from, count });
    return Box({ key: row.key, height: count, flexShrink: 0, marginTop: 0,
      children: [Text({ color: row.color, bold: Boolean(row.key), wrap: 'truncate-end',
        children: [row.lines.slice(from, from + count).join('\n')] })] });
  });
}

function moveList($, offset) {
  if (!layout) return;
  scrollOffset = Math.max(0, Math.min(offset, layout.maxOffset));
  $.ui.invalidate('ui.render');
}

function paneHeader($, elements, showPath) {
  const { Box, Text, Button } = elements;
  const scopeButtons = busy ? [] : ['project', 'global'].map(value => {
    const active = scope === value;
    const name = value === 'project' ? 'Project' : 'Global';
    const label = active ? '[' + name + ']' : name;
    return Button({
      key: value, plain: true, label, variant: active ? 'primary' : 'secondary',
      children: [Text({ color: active ? 'cyan' : undefined, bold: active, children: [label] })],
      onPress: () => refresh($, { scope: value }),
    });
  });
  const controls = Box({
    height: 1, flexShrink: 0, flexDirection: 'row', columnGap: 1,
    children: [
      ...scopeButtons,
      ...(!busy ? [Button({ key: 'refresh', plain: true, label: 'Refresh', onPress: () => refresh($) })] : []),
      Button({ key: 'close', plain: true, label: 'Close', onPress: () => closePane($) }),
    ],
  });
  return Box({
    key: 'settings-header', height: showPath ? 3 : 2, flexShrink: 0, flexDirection: 'column',
    children: [
      Text({ bold: true, color: 'cyan', wrap: 'truncate-end', maxLines: 1,
        children: ['ioncache-ai-tools | Settings'] }),
      controls,
      ...(showPath ? [Text({ dimColor: true, wrap: 'truncate-middle', maxLines: 1,
        children: ['Project: ' + (project || '(current directory)')] })] : []),
    ],
  });
}

function paneFooter($, elements, rows) {
  const { Box, Text, Button } = elements;
  const visible = rows.entries.filter(entry =>
    entry.top + entry.height > scrollOffset && entry.top < scrollOffset + layout.listRows);
  const first = visible.length ? rows.entries.indexOf(visible[0]) + 1 : 0;
  const last = visible.length ? rows.entries.indexOf(visible[visible.length - 1]) + 1 : 0;
  const label = scope === 'project' ? 'Project' : 'Global';
  let status = (message ? 'Saved | ' : '') + label + ' | ' + first + '-' + last +
    '/' + rows.entries.length + ' settings';
  if (busy) status = 'Reading settings...';
  else if (!snapshot) status = 'Read failed | Refresh to retry';
  else if (!snapshot.uiEnabled) status = 'Pane disabled | use --list';
  return Box({
    key: 'settings-footer', height: 2, flexShrink: 0, flexDirection: 'column',
    children: [
      Text({ color: message ? messageColor : 'cyan', wrap: 'truncate-end', maxLines: 1, children: [status] }),
      Box({ height: 1, flexDirection: 'row', columnGap: 1, children: [
        ...(!busy ? [
          Button({ key: 'previous-page', plain: true, label: 'Prev',
            onPress: () => moveList($, scrollOffset - layout.listRows) }),
          Button({ key: 'next-page', plain: true, label: 'Next',
            onPress: () => moveList($, scrollOffset + layout.listRows) }),
        ] : []),
        Text({ dimColor: true, wrap: 'truncate-end', maxLines: 1, children: ['PgUp/PgDn Tab/Enter'] }),
      ] }),
    ],
  });
}

function renderPane($, e) {
  const elements = $.ui.resolve(e);
  const { Box, Text, Button } = elements;
  const bodyRows = e.props.scroll.bodyRows;
  const columns = e.props.bodyColumns;
  if (bodyRows < 5 || columns < 30) {
    layout = undefined;
    return Box({ height: bodyRows, overflow: 'hidden', flexDirection: 'column', children: [
      Button({ key: 'close', plain: true, label: 'Close settings', onPress: () => closePane($) }),
      Text({ wrap: 'truncate-end', maxLines: 1, children: ['Enlarge pane or use --list.'] }),
    ] });
  }
  const showPath = bodyRows >= 12;
  const listRows = bodyRows - (showPath ? 3 : 2) - 2;
  const rows = catalog(columns - 2);
  layout = { listRows, contentRows: rows.height, entries: rows.entries, maxOffset: Math.max(0, rows.height - listRows) };
  scrollOffset = Math.min(scrollOffset, layout.maxOffset);
  const thumb = Math.max(1, Math.floor(listRows * listRows / Math.max(listRows, rows.height)));
  const thumbTop = layout.maxOffset ? Math.round(scrollOffset / layout.maxOffset * (listRows - thumb)) : 0;
  const frame = Box({
    key: 'settings-frame', mono: true, width: columns, height: bodyRows,
    flexDirection: 'column', overflow: 'hidden',
    children: [
      paneHeader($, elements, showPath),
      Box({ key: 'settings-list', height: listRows, flexShrink: 0, overflow: 'hidden', children: [
        Box({ key: 'settings-content', width: columns - 2, height: listRows, flexDirection: 'column',
          children: visibleRows($, elements, rows) }),
        ...(layout.maxOffset ? [Box({ position: 'absolute', right: 0, top: 0, width: 1,
          children: [Text({ color: 'cyan', children: [Array.from({ length: listRows }, (_, index) =>
            index >= thumbTop && index < thumbTop + thumb ? '#' : '|').join('\n')] })],
        })] : []),
      ] }),
      paneFooter($, elements, rows),
    ],
  });
  // Native scroll keys need the full extent to distinguish a page from Home/End.
  return Box({ key: 'settings-scroll-extent', height: bodyRows + layout.maxOffset,
    flexDirection: 'column', children: [frame] });
}

export function register(on) {
  on('command.run', { command: 'ioncache-ai-tools:plugin-settings' }, async ($, e) => {
    if (busy) return { text: 'A settings operation is still running.', isTextDisplayOnly: true };
    if (e.args.trim()) return listOrChange($, e.args);
    project = undefined;
    scope = 'project';
    scrollOffset = 0;
    await refresh($);
    if (!snapshot || !snapshot.uiEnabled) return listOrChange($);
    try {
      const placement = await $.ui.open({
        id: PANE, title: 'ioncache-ai-tools | Settings', rows: 24, focus: true, closeOnEscape: true,
        columns: Math.max(64, ...snapshot.groups.flatMap(group => group.settings.map(setting => setting.name.length + 15))),
      });
      paneOpen = placement.isPlaced;
      updateStatus($);
      if (!placement.isPlaced) return listOrChange($);
    } catch {
      paneOpen = false;
      updateStatus($);
      return listOrChange($);
    }
    return {};
  });

  on('ui.close', { id: PANE }, async ($, e, next) => {
    const result = await next(e);
    if (!result.deny) {
      paneOpen = false;
      updateStatus($);
    }
    return result;
  });

  on('ui.render', { component: 'Pane' }, async ($, e, next) => {
    if (e.requestId !== PANE) return next(e);
    return renderPane($, e);
  });

  on('ui.scroll', { component: 'Pane', requestId: PANE }, ($, e, next) => {
    if (!paneOpen || !layout) return next(e);
    const magnitude = Math.abs(e.by);
    if (e.origin.kind === 'person' && !e.pointer && magnitude === e.contentRows) {
      moveList($, e.by < 0 ? 0 : layout.maxOffset);
    } else {
      const by = !e.pointer && magnitude === e.bodyRows ? Math.sign(e.by) * layout.listRows : e.by;
      moveList($, scrollOffset + by);
    }
    return next({ ...e, offset: 0 });
  });

  on('ui.focus', { component: 'Pane', requestId: PANE }, ($, e, next) => {
    const row = layout?.entries.find(entry => entry.key === e.element);
    if (row && row.top < scrollOffset) moveList($, row.top);
    else if (row && row.top + row.height > scrollOffset + layout.listRows) {
      moveList($, Math.min(row.top, row.top + row.height - layout.listRows));
    }
    return next(e);
  });
}
