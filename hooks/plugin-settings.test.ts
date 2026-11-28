import { expect, mock, test } from 'claude-code/testing';

const COMMAND = 'ioncache-ai-tools:ioncache-ai-tools-settings';
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
    placement: 'shown', delayMs: 0, denyClose: false,
    project: '/project with spaces',
    status: undefined as string | undefined,
    statusSource: '',
    columns: 0,
    extraSettings: [] as string[],
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
        project: state.project,
        scope: e.argv.includes('--global') ? 'global' : 'project',
        saved: change || uiChange ? ['/settings.json'] : [],
        uiEnabled: state.uiEnabled,
        groups: [
          { title: 'Hooks', settings: [
            { name: 'hook:answer-questions', enabled: state.enabled, effective: state.effective },
            { name: 'hook:plugin-settings-ui', enabled: state.uiEnabled, effective: state.uiEnabled },
            ...state.extraSettings.map(name => ({ name, enabled: true, effective: true })),
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
    state.columns = e.columns;
    if (state.placement === 'error') return { deny: 'UI unavailable' };
    return { value: { isPlaced: state.placement === 'shown' } };
  });
  on('ui.close', () => {
    if (state.denyClose) return { deny: 'Keep this pane open' };
    state.closed += 1;
    return { value: undefined };
  });
  on('ui.status', ($, e, next) => {
    state.status = e.text;
    state.statusSource = next.origin.plugin;
    return { value: undefined };
  });
  return state;
}

async function expectSettingStatus(ui, key, enabled) {
  const row = await ui.find({ key });
  expect(row).toBeDefined();
  const status = row.children.find(child => child?.type === 'Text' &&
    /^\[[x ]\] (enabled|disabled)$/.test(child.children.join('')));
  expect(status).toBeDefined();
  expect(status.children).toEqual([enabled ? '[x] enabled' : '[ ] disabled']);
  expect(status.props.color).toBe(enabled ? 'green' : 'red');
}

async function expectScopeEmphasis(ui, active) {
  for (const scope of ['project', 'global']) {
    expect((await ui.find({ key: scope })).props.variant)
      .toBe(scope === active ? 'primary' : 'secondary');
  }
}

async function expectCatalogSummary(ui, available) {
  const count = await ui.find({ type: 'Text', text: /\b(Project|Global) \| \d+-\d+\/3 settings$/ });
  if (!available) {
    expect(count).toBeUndefined();
    return;
  }
  expect(count).toBeDefined();
  expect(count.text).toMatch(/\/3 settings$/);
}

test('opens native panes and saves toggles without a model or shell', async ($, on) => {
  const state = backend(on);
  for (const surface of ['terminal', 'desktop', 'vscode'] as const) {
    await $.command.run({ command: COMMAND, args: '' });
    const ui = await $.ui.mount({ ...PANE, surface });
    expect(state.status).toBe('Project | PgUp/PgDn: scroll');
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
      expect((await ui.find({ type: 'Text', text: /^Saved \|/ })).props.color).toBe('green');
    }
    await ui.press({ key: 'close' });
    expect(state.status).toBeUndefined();
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

test('small panes keep identity and controls outside the clipped list', async ($, on) => {
  const state = backend(on);
  state.project = '/a long project path with spaces/and several nested directories/current project';
  for (const surface of ['terminal', 'desktop', 'vscode'] as const) {
    for (const [bodyColumns, bodyRows] of [[56, 6], [35, 20]]) {
      await $.command.run({ command: COMMAND, args: '' });
      const ui = await $.ui.mount({
        ...PANE, surface,
        props: { ...PANE.props, bodyColumns, scroll: { offset: 0, bodyRows } },
      });
      expect(state.status).toBe('Project | PgUp/PgDn: scroll');
      expect(state.statusSource).toBe('ioncache-ai-tools');
      await expectCatalogSummary(ui, true);
      const location = await ui.find({ type: 'Text', text: 'Project: ' + state.project });
      if (bodyRows >= 12) expect(location.props.wrap).toBe('truncate-middle');
      else expect(location).toBeUndefined();
      expect(await ui.find({ type: 'Text', text: /^Editing:/ })).toBeUndefined();
      expect(await ui.find({ type: 'Text', text: /^Changes save/ })).toBeUndefined();
      expect(await ui.find({ type: 'Text', text: 'Hooks | Skills' })).toBeUndefined();
      expect((await ui.find({ key: 'group:Hooks' })).props.marginTop).toBe(0);
      for (const key of bodyRows < 12 ? ['hook:answer-questions']
        : ['hook:answer-questions', 'hook:plugin-settings-ui', 'skill:answer-questions']) {
        expect(await ui.find({ key })).toBeDefined();
      }
      await ui.press({ key: 'global' });
      await expectScopeEmphasis(ui, 'global');
      expect((await ui.find({ key: 'global' })).props.label).toBe('[Global]');
      expect(state.status).toBe('Global | PgUp/PgDn: scroll');
      await ui.press({ key: 'close' });
      expect(state.status).toBeUndefined();
      await ui.unmount();
    }
  }
});

test('a refused Close keeps the pinned status until closing succeeds', async ($, on) => {
  const state = backend(on);
  await $.command.run({ command: COMMAND, args: '' });
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' });
  state.denyClose = true;
  await expect(ui.press({ key: 'close' })).rejects.toThrow('Keep this pane open');
  expect(state.closed).toBe(0);
  expect(state.status).toBe('Project | PgUp/PgDn: scroll');
  state.denyClose = false;
  await ui.press({ key: 'close' });
  expect(state.closed).toBe(1);
  expect(state.status).toBeUndefined();
  await ui.unmount();
});

test('a dock requests enough width for the longest name and aligned state columns', async ($, on) => {
  const state = backend(on);
  const longest = 'hook:autonomous-development:explicit-only';
  state.extraSettings = [longest];
  await $.command.run({ command: COMMAND, args: '' });
  expect(state.columns).toBeGreaterThanOrEqual(longest.length + 15);
  for (const bodyColumns of [35, 72]) {
    const ui = await $.ui.mount({
      ...PANE, surface: 'terminal',
      props: { ...PANE.props, placement: 'dock', bodyColumns },
    });
    const keys = ['hook:answer-questions', longest, 'skill:answer-questions'];
    const columns: number[] = [];
    for (const key of keys) {
      const button = await ui.find({ key });
      const lines = button.text.split('\n');
      columns.push(lines[0].indexOf('[x]'));
      expect(lines[0]).toMatch(/\[x\] enabled$/);
      expect(lines.every(line => line.length <= bodyColumns - 2)).toBe(true);
    }
    expect(columns[0]).toBeGreaterThan(0);
    expect(new Set(columns).size).toBe(1);
    await ui.unmount();
  }
});

test('paging changes only the clipped list in both pane placements', async ($, on) => {
  const state = backend(on);
  state.extraSettings = Array.from({ length: 30 }, (_, i) => 'hook:long-setting-name-' + i);
  await $.command.run({ command: COMMAND, args: '' });
  for (const placement of ['inline', 'dock'] as const) {
    const ui = await $.ui.mount({
      ...PANE, surface: 'terminal',
      props: { ...PANE.props, placement, bodyColumns: 35, scroll: { offset: 0, bodyRows: 12 } },
    });
    const frame = await ui.find({ key: 'settings-frame' });
    expect(frame.props.height).toBe(12);
    const title = await ui.find({ type: 'Text', text: 'ioncache-ai-tools | Settings' });
    expect(title).toBeDefined();
    const viewport = await ui.find({ key: 'settings-list' });
    expect(viewport.props.overflow).toBe('hidden');
    const before = (await ui.findAll({ type: 'Button' })).map(button => button.props.key);
    await ui.press({ key: 'next-page' });
    expect((await ui.findAll({ type: 'Button' })).map(button => button.props.key)).not.toEqual(before);
    expect(await ui.find({ type: 'Text', text: title.text })).toBeDefined();
    expect((await ui.find({ key: 'project' })).props.label).toBe('[Project]');
    expect((await ui.find({ key: 'settings-frame' })).props.height).toBe(12);
    await ui.press({ key: 'previous-page' });
    expect((await ui.findAll({ type: 'Button' })).map(button => button.props.key)).toEqual(before);
    await ui.unmount();
  }
});

test('wheel, page and edge scrolling keep the outer window fixed and preserve recovery', async ($, on) => {
  const state = backend(on);
  state.extraSettings = Array.from({ length: 30 }, (_, i) => 'hook:long-setting-name-' + i);
  const offsets: number[] = [];
  on('ui.scroll', ($, e) => { offsets.push(e.offset); return {}; });
  on('ui.focus', { plugin: '*' }, () => ({}));
  await $.command.run({ command: COMMAND, args: '' });
  const ui = await $.ui.mount({
    ...PANE, surface: 'terminal',
    props: { ...PANE.props, bodyColumns: 35, placement: 'dock', scroll: { offset: 0, bodyRows: 12 } },
  });
  const event = {
    component: 'Pane' as const, requestId: PANE.requestId, offset: 4, by: 4,
    bodyRows: 12, contentRows: (await ui.find({ key: 'settings-scroll-extent' })).props.height,
    origin: { kind: 'person' as const },
  };
  await $.ui.scroll({ ...event, pointer: { row: 5, column: 4 } });
  expect((await ui.find({ key: 'hook:plugin-settings-ui' })).text).not.toMatch(/^hook:/);
  await $.ui.focus({
    component: 'Pane', requestId: PANE.requestId, plugin: PANE.plugin,
    element: 'hook:plugin-settings-ui', origin: { kind: 'person' },
  });
  expect((await ui.find({ key: 'hook:plugin-settings-ui' })).text).toMatch(/^hook:/);
  await $.ui.scroll({ ...event, by: event.bodyRows });
  expect(await ui.find({ key: 'hook:answer-questions' })).toBeUndefined();
  expect(await ui.find({ key: 'skill:answer-questions' })).toBeUndefined();
  await $.ui.scroll({ ...event, by: event.contentRows });
  expect(await ui.find({ key: 'skill:answer-questions' })).toBeDefined();
  await $.ui.scroll({ ...event, by: -event.contentRows });
  expect(await ui.find({ key: 'hook:answer-questions' })).toBeDefined();
  expect(offsets).toEqual([0, 0, 0, 0]);
  await $.ui.scroll({ ...event, requestId: 'another-pane' });
  expect(offsets[offsets.length - 1]).toBe(4);
  await ui.unmount();
});

test('an undersized pane retains Close and the text-interface alternative', async ($, on) => {
  const state = backend(on);
  await $.command.run({ command: COMMAND, args: '' });
  const ui = await $.ui.mount({
    ...PANE, surface: 'terminal',
    props: { ...PANE.props, bodyColumns: 24, scroll: { offset: 0, bodyRows: 3 } },
  });
  expect(await ui.find({ type: 'Text', text: 'Enlarge pane or use --list.' })).toBeDefined();
  expect(await ui.find({ key: 'hook:answer-questions' })).toBeUndefined();
  await ui.press({ key: 'close' });
  expect(state.closed).toBe(1);
  expect(state.status).toBeUndefined();
  await ui.unmount();
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
  expect((await ui.find({ key: 'project' })).props.label).toBe('[Project]');
  await expectScopeEmphasis(ui, 'project');
  await ui.press({ key: 'global' });
  expect(state.status).toBe('Global | PgUp/PgDn: scroll');
  await expectScopeEmphasis(ui, 'global');
  expect((await ui.find({ key: 'project' })).props.label).toBe('Project');
  expect((await ui.find({ key: 'global' })).props.label).toBe('[Global]');
  expect(await ui.find({ type: 'Text', text: /^Global \|/ })).toBeDefined();
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
  expect(state.status).toBe('Project | PgUp/PgDn: scroll');
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
  expect(state.status).toBe('Project | PgUp/PgDn: scroll');
  await expectScopeEmphasis(reopened, 'project');
  expect(await reopened.find({ type: 'Text', text: /^Project \|/ })).toBeDefined();
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
      expect(state.status).toBeUndefined();
      const blocked = $.command.run({ command: COMMAND, args: '--list' });
      await clock.settle();
      expect(state.requests.length).toBe(before + 1);
      expect((await blocked).text).toBe('A settings operation is still running.');
    } finally {
      state.delayMs = 0;
      await clock.advance(1000);
      await pending;
    }
    expect(state.status).toBeUndefined();
    if (failSave) {
      expect(await ui.find({ key: 'hook:answer-questions' })).toBeUndefined();
      expect((await ui.find({ type: 'Text', text: /No success confirmed[\s\S]*Partial write/ })).props.color).toBe('red');
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
    expect(await ui.find({ type: 'Text', text: /^Saved \|/ })).toBeDefined();
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
  expect(state.status).toBeUndefined();
  await expectCatalogSummary(ui, false);
  expect(await ui.find({ key: 'hook:answer-questions' })).toBeUndefined();
  expect(await ui.find({ key: 'hook:plugin-settings-ui' })).toBeUndefined();
  expect(await ui.find({
    type: 'Text', text: /^Native pane disabled\./,
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
  expect(state.status).toBe('Project | PgUp/PgDn: scroll');
  await expectCatalogSummary(reopened, true);
  await reopened.press({ key: 'hook:answer-questions' });
  expect(state.enabled).toBe(false);
  expect(await reopened.find({ type: 'Text', text: /^Saved \|/ })).toBeDefined();
  await reopened.unmount();
});

test('failed writes remove stale controls and refresh observes the partial write', async ($, on) => {
  const clock = mock.clock(on);
  const state = backend(on, clock);
  await $.command.run({ command: COMMAND, args: '' });
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' });
  state.failSave = true;
  await ui.press({ key: 'hook:answer-questions' });
  expect(await ui.find({ key: 'hook:answer-questions' })).toBeUndefined();
  expect(await ui.find({ type: 'Text', text: /No success confirmed[\s\S]*Partial write/ })).toBeDefined();
  expect(await ui.find({ type: 'Text', text: /^Saved \|/ })).toBeUndefined();
  expect(state.status).toBe('Read failed | Refresh to retry');
  state.failSave = false;
  state.delayMs = 1000;
  const refresh = ui.press({ key: 'refresh' });
  try {
    await clock.settle();
    expect(state.status).toBe('Project | Reading settings...');
  } finally {
    state.delayMs = 0;
    await clock.advance(1000);
    await refresh;
  }
  expect(state.status).toBe('Project | PgUp/PgDn: scroll');
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
  expect(state.status).toBeUndefined();
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
    expect(state.status).toBeUndefined();
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
  expect(first.text).toMatch(/\/ioncache-ai-tools:ioncache-ai-tools-settings --list/);
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
