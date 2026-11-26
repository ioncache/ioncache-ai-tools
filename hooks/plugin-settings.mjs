const PANE = 'ioncache-plugin-settings';
const RECOVERY = 'Use /ioncache-ai-tools:plugin-settings --list for the text interface, or run the standalone plugin_settings.py helper.';

let snapshot;
let scope = 'project';
let project;
let busy = false;
let message = '';
let messageColor = 'green';

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
    $.ui.invalidate('ui.render');
  }
}

function settingRows($, elements) {
  const { Box, Text, Button } = elements;
  if (!snapshot || busy) return [];
  if (!snapshot.uiEnabled) {
    return [Text({ color: 'yellow', children: [
      'Native pane disabled. Re-enable with /ioncache-ai-tools:plugin-settings --hook:plugin-settings-ui=enabled.',
    ] })];
  }
  return snapshot.groups.map(group => Box({
    key: 'group:' + group.title,
    flexDirection: 'column',
    marginTop: 1,
    children: [
      Text({ bold: true, color: 'cyan', children: [group.title + ' (' + group.settings.length + ')'] }),
      ...group.settings.map(setting => Box({
        flexDirection: 'column',
        children: [
          Box({
            flexDirection: 'row',
            flexWrap: 'wrap',
            columnGap: 1,
            children: [
              Button({
                key: setting.name,
                plain: true,
                label: setting.name + (setting.enabled ? ' [x]' : ' [ ]'),
                onPress: () => refresh($, {
                  change: '--' + setting.name + '=' + (setting.enabled ? 'disabled' : 'enabled'),
                }),
              }),
              Text({
                color: setting.enabled ? 'green' : 'red',
                children: [setting.enabled ? 'enabled' : 'disabled'],
              }),
            ],
          }),
          ...(scope === 'global' && setting.enabled !== setting.effective
            ? [Text({ color: 'yellow', children: [
                '  Effective project: ' + (setting.effective ? 'enabled' : 'disabled'),
              ] })]
            : []),
        ],
      })),
    ],
  }));
}

function catalogSummary(elements) {
  if (!snapshot?.uiEnabled || busy) return [];
  const { Text } = elements;
  const count = snapshot.groups.reduce((total, group) => total + group.settings.length, 0);
  return [
    Text({ color: 'cyan', children: [
      count + ' settings below. PgUp/PgDn or Home/End to scroll.',
    ] }),
    Text({ dimColor: true, children: [snapshot.groups.map(group => group.title).join(' | ')] }),
  ];
}

export function register(on) {
  on('command.run', { command: 'ioncache-ai-tools:plugin-settings' }, async ($, e) => {
    if (busy) return { text: 'A settings operation is still running.', isTextDisplayOnly: true };
    if (e.args.trim()) return listOrChange($, e.args);
    project = undefined;
    scope = 'project';
    await refresh($);
    if (!snapshot || !snapshot.uiEnabled) return listOrChange($);
    try {
      const placement = await $.ui.open({
        id: PANE, title: 'ioncache-ai-tools | Settings', rows: 24, focus: true, closeOnEscape: true,
      });
      if (!placement.isPlaced) return listOrChange($);
    } catch {
      return listOrChange($);
    }
    return {};
  });

  on('ui.render', { component: 'Pane' }, async ($, e, next) => {
    if (e.requestId !== PANE) return next(e);
    const elements = $.ui.resolve(e);
    const { Box, Text, Button } = elements;
    const scopeButtons = busy ? [] : [
      Button({
        key: 'project', label: scope === 'project' ? 'Project (editing)' : 'Project',
        variant: scope === 'project' ? 'primary' : 'secondary',
        onPress: () => refresh($, { scope: 'project' }),
      }),
      Button({
        key: 'global', label: scope === 'global' ? 'Global (editing)' : 'Global',
        variant: scope === 'global' ? 'primary' : 'secondary',
        onPress: () => refresh($, { scope: 'global' }),
      }),
      Button({ key: 'refresh', label: 'Refresh', onPress: () => refresh($) }),
    ];
    return Box({
      flexDirection: 'column',
      children: [
        Text({ bold: true, color: 'cyan', children: ['ioncache-ai-tools | Settings'] }),
        Text({ dimColor: true, children: ['Project: ' + (project || '(current directory)')] }),
        Text({ bold: true, children: ['Editing: ' + scope + ' settings (Claude, Copilot, Codex)'] }),
        Box({
          flexDirection: 'row',
          flexWrap: 'wrap',
          columnGap: 1,
          children: [
            ...scopeButtons,
            Button({ key: 'close', label: 'Close', onPress: () => $.ui.close({ id: PANE }) }),
          ],
        }),
        Text({ children: ['Changes save immediately. Global keeps project overrides.'] }),
        Text({ dimColor: true, children: ['Tab: move | Enter: toggle | Esc: close'] }),
        ...catalogSummary(elements),
        ...(message ? [Text({ color: messageColor, children: [message] })] : []),
        ...settingRows($, elements),
      ],
    });
  });
}
