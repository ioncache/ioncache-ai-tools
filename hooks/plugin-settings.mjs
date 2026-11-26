const PANE = 'ioncache-plugin-settings';
const RECOVERY = 'Use /ioncache-ai-tools:plugin-settings --list for the text interface, or run the standalone plugin_settings.py helper.';

let snapshot;
let scope = 'project';
let project;
let busy = false;
let message = '';

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
  } catch (error) {
    snapshot = undefined;
    message = 'No success confirmed. ' + error.message + '\n' + RECOVERY;
  } finally {
    busy = false;
    $.ui.invalidate('ui.render');
  }
}

function settingRows($, elements) {
  const { Box, Text, Button } = elements;
  if (!snapshot || busy) return [];
  if (!snapshot.uiEnabled) {
    return [Text({ children: [
      'Native pane disabled. Re-enable with /ioncache-ai-tools:plugin-settings --hook:plugin-settings-ui=enabled.',
    ] })];
  }
  return snapshot.groups.flatMap(group => [
    Text({ bold: true, children: [group.title] }),
    Text({ dimColor: true, children: ['------------------------'] }),
    ...group.settings.map(setting => Box({
      flexDirection: 'column',
      children: [
        Button({
          key: setting.name,
          plain: true,
          label: (setting.enabled ? 'enabled   ' : 'disabled  ') + setting.name,
          onPress: () => refresh($, {
            change: '--' + setting.name + '=' + (setting.enabled ? 'disabled' : 'enabled'),
          }),
        }),
        ...(scope === 'global' && setting.enabled !== setting.effective
          ? [Text({ dimColor: true, children: [
              '  Effective project: ' + (setting.effective ? 'enabled' : 'disabled'),
            ] })]
          : []),
      ],
    })),
    Text({ children: [' '] }),
  ]);
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
        id: PANE, title: 'Plugin settings', focus: true, closeOnEscape: true,
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
      Button({ key: 'project', label: 'Project', onPress: () => refresh($, { scope: 'project' }) }),
      Button({ key: 'global', label: 'Global', onPress: () => refresh($, { scope: 'global' }) }),
      Button({ key: 'refresh', label: 'Refresh', onPress: () => refresh($) }),
    ];
    return Box({
      flexDirection: 'column',
      children: [
        Text({ children: ['Project: ' + (project || '(current directory)')] }),
        Text({ children: ['Scope: ' + scope + ' (Claude, Copilot, Codex)'] }),
        Text({ children: ['Select a setting to toggle it. Changes save immediately.'] }),
        Text({ dimColor: true, children: ['Global changes preserve project overrides. Tab to move; Enter to toggle; Esc to close.'] }),
        Box({
          flexDirection: 'row',
          columnGap: 1,
          children: [
            ...scopeButtons,
            Button({ key: 'close', label: 'Close', onPress: () => $.ui.close({ id: PANE }) }),
          ],
        }),
        Text({ children: [message || ' '] }),
        ...settingRows($, elements),
      ],
    });
  });
}
