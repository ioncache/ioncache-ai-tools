import { expect, mock, test } from 'claude-code/testing';

const COMMAND = 'ioncache-ai-tools:plugin-settings';
const PANE = {
  plugin: 'ioncache-ai-tools',
  component: 'Pane',
  requestId: 'ioncache-plugin-settings',
  viewport: { columns: 100, rows: 30 },
  props: {
    title: 'ioncache-ai-tools | Settings',
    isFocused: true,
    bodyColumns: 60,
    placement: 'inline',
    scroll: { offset: 0, bodyRows: 20 },
    view: {},
  },
} as const;

function backend(on, clock?) {
  const state = {
    enabled: true, effective: true, uiEnabled: true, failSave: false,
    requests: [] as string[][], opened: 0, closed: 0,
    titles: [] as string[],
    placement: 'shown', delayMs: 0,
  };
  on('process.run', async ($, e) => {
    state.requests.push(e.argv);
    if (state.delayMs) await clock.sleep(state.delayMs);
    if (e.argv.includes('--ui') && !state.uiEnabled) {
      return { value: {
        exitCode: 1, stdout: '', stderr: 'Native settings pane is disabled.',
      } };
    }
    const change = e.argv.find(arg => arg.startsWith('--hook:answer-questions='));
    const uiChange = e.argv.find(arg => arg.startsWith('--hook:plugin-settings-ui='));
    if (change) state.enabled = change.endsWith('=enabled');
    if (uiChange) state.uiEnabled = uiChange.endsWith('=enabled');
    if (change && state.failSave) {
      return { value: { exitCode: 1, stdout: '', stderr: 'Partial write; inspect and retry.' } };
    }
    if (!e.argv.includes('--json')) {
      return { value: { exitCode: 0, stdout: 'Settings listing', stderr: '' } };
    }
    return { value: {
      exitCode: 0,
      stderr: '',
      stdout: JSON.stringify({
        version: 1,
        project: '/project with spaces',
        scope: e.argv.includes('--global') ? 'global' : 'project',
        saved: change || uiChange ? ['/settings.json'] : [],
        uiEnabled: state.uiEnabled,
        groups: [
          { title: 'Hooks', settings: [
            { name: 'hook:answer-questions', enabled: state.enabled, effective: state.effective },
            { name: 'hook:plugin-settings-ui', enabled: state.uiEnabled, effective: state.uiEnabled },
          ] },
          { title: 'Skills', settings: [
            { name: 'skill:answer-questions', enabled: true, effective: true },
          ] },
        ],
      }),
    } };
  });
  on('ui.open', ($, e) => {
    state.opened += 1;
    state.titles.push(e.title);
    if (state.placement === 'error') return { deny: 'UI unavailable' };
    return { value: { isPlaced: state.placement === 'shown' } };
  });
  on('ui.close', () => {
    state.closed += 1;
    return { value: undefined };
  });
  return state;
}

async function expectSettingStatus(ui, key, enabled) {
  const boxes = await ui.findAll({ type: 'Box' });
  const row = boxes.find(box => box.children.some(child =>
    child?.type === 'Button' && child.props.key === key));
  expect(row).toBeDefined();
  const status = row.children.find(child => child?.type === 'Text');
  expect(status).toBeDefined();
  expect(status.children).toEqual([enabled ? 'enabled' : 'disabled']);
  expect(status.props.color).toBe(enabled ? 'green' : 'red');
}

async function expectScopeEmphasis(ui, active) {
  for (const scope of ['project', 'global']) {
    expect((await ui.find({ key: scope })).props.variant)
      .toBe(scope === active ? 'primary' : 'secondary');
  }
}

async function expectCatalogSummary(ui, available) {
  const count = await ui.find({ type: 'Text', text: /^\d+ settings below\./ });
  const groups = await ui.find({ type: 'Text', text: /^Hooks \| Skills$/ });
  if (!available) {
    expect(count).toBeUndefined();
    expect(groups).toBeUndefined();
    return;
  }
  expect(count).toBeDefined();
  expect(count.text).toMatch(/^3 settings below\./);
  expect(groups).toBeDefined();
}

test('opens native panes and saves toggles without a model or shell', async ($, on) => {
  const state = backend(on);
  for (const surface of ['terminal', 'desktop', 'vscode'] as const) {
    await $.command.run({ command: COMMAND, args: '' });
    const ui = await $.ui.mount({ ...PANE, surface });
    expect(await ui.find({ type: 'Text', text: 'Hooks (2)' })).toBeDefined();
    expect(await ui.find({ type: 'Text', text: 'ioncache-ai-tools | Settings' })).toBeDefined();
    expect(await ui.find({ key: 'skill:answer-questions' })).toBeDefined();
    for (const enabled of [false, true]) {
      await ui.press({ key: 'hook:answer-questions' });
      expect(state.enabled).toBe(enabled);
      const row = await ui.find({ key: 'hook:answer-questions' });
      expect(row.props.label).toBe('hook:answer-questions' + (enabled ? ' [x]' : ' [ ]'));
      await expectSettingStatus(ui, 'hook:answer-questions', enabled);
      await expectSettingStatus(ui, 'skill:answer-questions', true);
      expect((await ui.find({ type: 'Text', text: /^Saved and verified/ })).props.color).toBe('green');
    }
    await ui.press({ key: 'close' });
    await ui.unmount();
  }
  expect(state.opened).toBe(3);
  expect(state.closed).toBe(3);
  expect(state.titles).toEqual(Array(3).fill('ioncache-ai-tools | Settings'));
  expect(state.requests[1].slice(2)).toEqual([
    '--json', '--ui', '--project', '/project with spaces', '--hook:answer-questions=disabled',
  ]);
  expect(state.requests[1][0]).toBe('python3');
  expect(state.requests[1][1]).toMatch(/\/hooks\/scripts\/plugin_settings.py$/);
});

test('short panes announce the full catalog and its scrolling controls', async ($, on) => {
  backend(on);
  for (const surface of ['terminal', 'desktop', 'vscode'] as const) {
    await $.command.run({ command: COMMAND, args: '' });
    const ui = await $.ui.mount({
      ...PANE, surface,
      props: { ...PANE.props, bodyColumns: 35, scroll: { offset: 0, bodyRows: 12 } },
    });
    expect(await ui.find({
      type: 'Text', text: '3 settings below. PgUp/PgDn or Home/End to scroll.',
    })).toBeDefined();
    expect(await ui.find({ type: 'Text', text: 'Hooks | Skills' })).toBeDefined();
    for (const title of ['Hooks', 'Skills']) {
      expect(await ui.find({ key: 'group:' + title })).toBeDefined();
    }
    await ui.unmount();
  }
});

test('unrelated panes retain their downstream rendering', async ($, on) => {
  backend(on);
  const forwarded: string[] = [];
  on('ui.render', ($, e) => {
    forwarded.push(e.requestId);
    return { type: 'Text', props: {}, children: ['Other pane content'] };
  });
  await $.command.run({ command: COMMAND, args: '' });
  const ui = await $.ui.mount({ ...PANE, requestId: 'other-plugin-pane', surface: 'terminal' });
  expect(forwarded).toEqual(['other-plugin-pane']);
  expect(await ui.find({ type: 'Text', text: 'Other pane content' })).toBeDefined();
  expect(await ui.find({ key: 'hook:answer-questions' })).toBeUndefined();
  await ui.unmount();
});

test('global edits show project overrides and switching scopes does not write', async ($, on) => {
  const state = backend(on);
  await $.command.run({ command: COMMAND, args: '' });
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' });
  expect((await ui.find({ key: 'project' })).props.label).toBe('Project (editing)');
  await expectScopeEmphasis(ui, 'project');
  await ui.press({ key: 'global' });
  await expectScopeEmphasis(ui, 'global');
  expect((await ui.find({ key: 'project' })).props.label).toBe('Project');
  expect((await ui.find({ key: 'global' })).props.label).toBe('Global (editing)');
  expect(await ui.find({
    type: 'Text', text: 'Editing: global settings (Claude, Copilot, Codex)',
  })).toBeDefined();
  expect(state.requests[1].includes('--global')).toBe(true);
  expect(state.requests[1].some(arg => arg.startsWith('--hook:'))).toBe(false);
  expect(await ui.find({ type: 'Text', text: /Effective project:/ })).toBeUndefined();
  await ui.press({ key: 'hook:answer-questions' });
  expect(state.requests[2].includes('--global')).toBe(true);
  expect(await ui.find({ type: 'Text', text: '  Effective project: enabled' })).toBeDefined();
  state.effective = false;
  await ui.press({ key: 'hook:answer-questions' });
  expect((await ui.find({ key: 'hook:answer-questions' })).props.label).toMatch(/\[x\]$/);
  expect(await ui.find({ type: 'Text', text: '  Effective project: disabled' })).toBeDefined();
  expect(await ui.find({ type: 'Text', text: '  Effective project: enabled' })).toBeUndefined();
  state.effective = true;
  await ui.press({ key: 'refresh' });
  expect(await ui.find({ type: 'Text', text: /Effective project:/ })).toBeUndefined();
  await ui.press({ key: 'project' });
  await expectScopeEmphasis(ui, 'project');
  expect(state.requests[state.requests.length - 1].includes('--global')).toBe(false);
  await ui.unmount();
});

test('reopening after Global mode restores project-scoped reads and writes', async ($, on) => {
  const state = backend(on);
  await $.command.run({ command: COMMAND, args: '' });
  const first = await $.ui.mount({ ...PANE, surface: 'terminal' });
  await first.press({ key: 'global' });
  await expectScopeEmphasis(first, 'global');
  await first.press({ key: 'close' });
  await first.unmount();

  await $.command.run({ command: COMMAND, args: '' });
  const reopened = await $.ui.mount({ ...PANE, surface: 'terminal' });
  await expectScopeEmphasis(reopened, 'project');
  expect(await reopened.find({ type: 'Text', text: 'Editing: project settings (Claude, Copilot, Codex)' })).toBeDefined();
  expect(state.requests[2].slice(2)).toEqual(['--json', '--ui']);
  await reopened.press({ key: 'hook:answer-questions' });
  expect(state.requests[3].slice(2)).toEqual([
    '--json', '--ui', '--project', '/project with spaces', '--hook:answer-questions=disabled',
  ]);
  await reopened.unmount();
});

test('pending operations hide stale controls, serialize commands, and recover', async ($, on) => {
  const clock = mock.clock(on);
  const state = backend(on, clock);
  await $.command.run({ command: COMMAND, args: '' });
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' });
  await expectCatalogSummary(ui, true);

  for (const failSave of [false, true]) {
    state.failSave = failSave;
    state.delayMs = 1000;
    const before = state.requests.length;
    const pending = ui.press({ key: 'hook:answer-questions' });
    try {
      await clock.settle();
      expect(state.requests.length).toBe(before + 1);
      await expectCatalogSummary(ui, false);
      expect((await ui.find({ type: 'Text', text: /^Reading settings\.\.\.$/ })).props.color).toBe('cyan');
      for (const key of ['hook:answer-questions', 'hook:plugin-settings-ui', 'project', 'global', 'refresh']) {
        expect(await ui.find({ key })).toBeUndefined();
      }
      await ui.press({ key: 'close' });
      expect(state.closed).toBe(failSave ? 2 : 1);
      const blocked = $.command.run({ command: COMMAND, args: '--list' });
      await clock.settle();
      expect(state.requests.length).toBe(before + 1);
      expect((await blocked).text).toBe('A settings operation is still running.');
    } finally {
      state.delayMs = 0;
      await clock.advance(1000);
      await pending;
    }
    if (failSave) {
      expect(await ui.find({ key: 'hook:answer-questions' })).toBeUndefined();
      expect((await ui.find({ type: 'Text', text: /No success confirmed.*Partial write/ })).props.color).toBe('red');
      await expectCatalogSummary(ui, false);
      state.failSave = false;
      state.delayMs = 1000;
      const refresh = ui.press({ key: 'refresh' });
      try {
        await clock.settle();
        expect((await ui.find({ type: 'Text', text: /^Reading settings\.\.\.$/ })).props.color).toBe('cyan');
        await expectCatalogSummary(ui, false);
      } finally {
        state.delayMs = 0;
        await clock.advance(1000);
        await refresh;
      }
    }
    await expectCatalogSummary(ui, true);
    expect(await ui.find({ key: 'hook:answer-questions' })).toBeDefined();
    expect(await ui.find({ key: 'global' })).toBeDefined();
    await ui.press({ key: 'hook:answer-questions' });
    expect(await ui.find({ type: 'Text', text: /^Saved and verified/ })).toBeDefined();
  }
  await ui.unmount();
});

test('a mounted pane can disable itself and recover through the same command', async ($, on) => {
  const state = backend(on);
  await $.command.run({ command: COMMAND, args: '' });
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' });
  await expectCatalogSummary(ui, true);
  await ui.press({ key: 'hook:plugin-settings-ui' });
  expect(state.uiEnabled).toBe(false);
  await expectCatalogSummary(ui, false);
  expect(await ui.find({ key: 'hook:answer-questions' })).toBeUndefined();
  expect(await ui.find({ key: 'hook:plugin-settings-ui' })).toBeUndefined();
  expect(await ui.find({
    type: 'Text',
    text: 'Native pane disabled. Re-enable with /ioncache-ai-tools:plugin-settings --hook:plugin-settings-ui=enabled.',
  })).toBeDefined();
  await ui.press({ key: 'close' });
  expect(state.closed).toBe(1);
  await ui.unmount();

  const listing = await $.command.run({ command: COMMAND, args: '' });
  expect(listing.text).toBe('Settings listing');
  expect(state.opened).toBe(1);
  const recovery = await $.command.run({ command: COMMAND, args: '--hook:plugin-settings-ui=enabled' });
  expect(recovery.text).toBe('Settings listing');
  expect(state.uiEnabled).toBe(true);
  await $.command.run({ command: COMMAND, args: '' });
  const reopened = await $.ui.mount({ ...PANE, surface: 'terminal' });
  await expectCatalogSummary(reopened, true);
  await reopened.press({ key: 'hook:answer-questions' });
  expect(state.enabled).toBe(false);
  expect(await reopened.find({ type: 'Text', text: /^Saved and verified/ })).toBeDefined();
  await reopened.unmount();
});

test('failed writes remove stale controls and refresh observes the partial write', async ($, on) => {
  const state = backend(on);
  await $.command.run({ command: COMMAND, args: '' });
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' });
  state.failSave = true;
  await ui.press({ key: 'hook:answer-questions' });
  expect(await ui.find({ key: 'hook:answer-questions' })).toBeUndefined();
  expect(await ui.find({ type: 'Text', text: /No success confirmed.*Partial write/ })).toBeDefined();
  expect(await ui.find({ type: 'Text', text: /^Saved and verified/ })).toBeUndefined();
  state.failSave = false;
  await ui.press({ key: 'refresh' });
  expect((await ui.find({ key: 'hook:answer-questions' })).props.label).toMatch(/\[ \]$/);
  await ui.press({ key: 'hook:answer-questions' });
  expect(state.enabled).toBe(true);
  await ui.unmount();
});

test('native flags stay literal data and do not open the pane', async ($, on) => {
  let argv: string[] = [];
  on('process.run', ($, e) => {
    argv = e.argv;
    return { value: { exitCode: 0, stdout: 'Settings listing', stderr: '' } };
  });
  const args = '--project "/project with spaces" --hook:answer-questions=disabled';
  const result = await $.command.run({ command: COMMAND, args });
  expect(result.text).toBe('Settings listing');
  expect(result.isTextDisplayOnly).toBe(true);
  expect(argv.slice(2)).toEqual(['--command', args]);
});

test('the same bare command lists settings when the pane is disabled', async ($, on) => {
  const state = backend(on);
  state.uiEnabled = false;
  const result = await $.command.run({ command: COMMAND, args: '' });
  expect(result.text).toMatch(/Settings listing/);
  expect(result.isTextDisplayOnly).toBe(true);
  expect(state.opened).toBe(0);
  state.uiEnabled = true;
  await $.command.run({ command: COMMAND, args: '' });
  expect(state.opened).toBe(1);
});

test('the same bare command lists settings when the host cannot place a pane', async ($, on) => {
  const state = backend(on);
  for (const placement of ['unplaced', 'error']) {
    state.placement = placement;
    const result = await $.command.run({ command: COMMAND, args: '' });
    expect(result.text).toMatch(/Settings listing/);
    expect(result.isTextDisplayOnly).toBe(true);
  }
  state.placement = 'shown';
  await $.command.run({ command: COMMAND, args: '' });
  expect(state.opened).toBe(3);
});

test('an unavailable process reports failure and a later command still runs', async ($, on) => {
  let unavailable = true;
  on('process.run', () => unavailable
    ? { deny: 'Python could not start' }
    : { value: { exitCode: 0, stdout: 'Settings listing', stderr: '' } });
  const first = await $.command.run({ command: COMMAND, args: '' });
  expect(first.text).toMatch(/Python could not start/);
  expect(first.text).toMatch(/\/ioncache-ai-tools:plugin-settings --list/);
  unavailable = false;
  const next = await $.command.run({ command: COMMAND, args: '--list' });
  expect(next.text).toBe('Settings listing');
});

test('uses the existing namespaced skill without registering another command', async ($, on) => {
  const registrations: string[] = [];
  on('command.register', ($, e) => {
    registrations.push(e.name);
    return { deny: 'a second command is not allowed' };
  });
  const state = backend(on);
  on('session.start', () => ({ cwd: '/project' }));
  const result = await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/project' });
  expect(result.cwd).toBe('/project');
  await $.command.run({ command: COMMAND, args: '' });
  expect(registrations).toEqual([]);
  expect(state.opened).toBe(1);
});
