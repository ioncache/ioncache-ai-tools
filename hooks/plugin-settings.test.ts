import { expect, test } from 'claude-code/testing';

const PANE = {
  plugin: 'ioncache-ai-tools',
  component: 'Pane',
  requestId: 'ioncache-plugin-settings',
  viewport: { columns: 100, rows: 30 },
  props: {
    title: 'Plugin settings',
    isFocused: true,
    bodyColumns: 60,
    placement: 'inline',
    scroll: { offset: 0, bodyRows: 20 },
    view: {},
  },
} as const;

function backend(on) {
  const state = { enabled: true, failSave: false, requests: [] as string[][], opened: 0, closed: 0 };
  on('process.run', ($, e) => {
    state.requests.push(e.argv);
    const change = e.argv.find(arg => arg.startsWith('--hook:answer-questions='));
    if (change) state.enabled = change.endsWith('=enabled');
    if (change && state.failSave) {
      return { value: { exitCode: 1, stdout: '', stderr: 'Partial write; inspect and retry.' } };
    }
    return { value: {
      exitCode: 0,
      stderr: '',
      stdout: JSON.stringify({
        version: 1,
        project: '/project with spaces',
        scope: e.argv.includes('--global') ? 'global' : 'project',
        saved: change ? ['/settings.json'] : [],
        uiEnabled: true,
        groups: [
          { title: 'Hooks', settings: [
            { name: 'hook:answer-questions', enabled: state.enabled, effective: true },
          ] },
          { title: 'Skills', settings: [
            { name: 'skill:answer-questions', enabled: true, effective: true },
          ] },
        ],
      }),
    } };
  });
  on('ui.open', () => {
    state.opened += 1;
    return { value: { isPlaced: true } };
  });
  on('ui.close', () => {
    state.closed += 1;
    return { value: undefined };
  });
  return state;
}

test('opens native panes and saves toggles without a model or shell', async ($, on) => {
  const state = backend(on);
  for (const surface of ['terminal', 'desktop', 'vscode'] as const) {
    await $.command.run({ command: 'plugin-settings-ui', args: '' });
    const ui = await $.ui.mount({ ...PANE, surface });
    expect(await ui.find({ type: 'Text', text: 'Hooks' })).toBeDefined();
    expect(await ui.find({ key: 'skill:answer-questions' })).toBeDefined();
    const previous = state.enabled;
    await ui.press({ key: 'hook:answer-questions' });
    expect(state.enabled).toBe(!previous);
    const row = await ui.find({ key: 'hook:answer-questions' });
    expect(row.props.label).toMatch(previous ? /^disabled/ : /^enabled/);
    expect(await ui.find({ type: 'Text', text: /^Saved and verified/ })).toBeDefined();
    await ui.press({ key: 'close' });
    await ui.unmount();
  }
  expect(state.opened).toBe(3);
  expect(state.closed).toBe(3);
  expect(state.requests[1].slice(2)).toEqual([
    '--json', '--ui', '--project', '/project with spaces', '--hook:answer-questions=disabled',
  ]);
  expect(state.requests[1][0]).toBe('python3');
  expect(state.requests[1][1]).toMatch(/\/hooks\/scripts\/plugin_settings.py$/);
});

test('global edits show project overrides and switching scopes does not write', async ($, on) => {
  const state = backend(on);
  await $.command.run({ command: 'plugin-settings-ui', args: '' });
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' });
  await ui.press({ key: 'global' });
  expect(state.requests[1].includes('--global')).toBe(true);
  expect(state.requests[1].some(arg => arg.startsWith('--hook:'))).toBe(false);
  await ui.press({ key: 'hook:answer-questions' });
  expect(state.requests[2].includes('--global')).toBe(true);
  expect(await ui.find({ type: 'Text', text: '  Effective project: enabled' })).toBeDefined();
  await ui.press({ key: 'project' });
  expect(state.requests[3].includes('--global')).toBe(false);
  await ui.unmount();
});

test('failed writes remove stale controls and refresh observes the partial write', async ($, on) => {
  const state = backend(on);
  await $.command.run({ command: 'plugin-settings-ui', args: '' });
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' });
  state.failSave = true;
  await ui.press({ key: 'hook:answer-questions' });
  expect(await ui.find({ key: 'hook:answer-questions' })).toBeUndefined();
  expect(await ui.find({ type: 'Text', text: /No success confirmed.*Partial write/ })).toBeDefined();
  expect(await ui.find({ type: 'Text', text: /^Saved and verified/ })).toBeUndefined();
  state.failSave = false;
  await ui.press({ key: 'refresh' });
  expect((await ui.find({ key: 'hook:answer-questions' })).props.label).toMatch(/^disabled/);
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
  const result = await $.command.run({ command: 'plugin-settings-ui', args });
  expect(result.text).toBe('Settings listing');
  expect(result.isTextDisplayOnly).toBe(true);
  expect(argv.slice(2)).toEqual(['--command', args]);
});

test('a disabled pane reports CLI recovery without opening a UI', async ($, on) => {
  let opened = false;
  on('process.run', () => ({ value: {
    exitCode: 1, stdout: '',
    stderr: 'Native pane disabled; use --hook:plugin-settings-ui=enabled without --ui.',
  } }));
  on('ui.open', () => {
    opened = true;
    return { value: { isPlaced: true } };
  });
  const result = await $.command.run({ command: 'plugin-settings-ui', args: '' });
  expect(result.text).toMatch(/--hook:plugin-settings-ui=enabled/);
  expect(opened).toBe(false);
});

test('an unavailable process reports failure and a later command still runs', async ($, on) => {
  let unavailable = true;
  on('process.run', () => unavailable
    ? { deny: 'Python could not start' }
    : { value: { exitCode: 0, stdout: 'Settings listing', stderr: '' } });
  const first = await $.command.run({ command: 'plugin-settings-ui', args: '' });
  expect(first.text).toMatch(/No success confirmed.*Python could not start/);
  unavailable = false;
  const next = await $.command.run({ command: 'plugin-settings-ui', args: '--list' });
  expect(next.text).toBe('Settings listing');
});

test('registration conflicts preserve session startup and provide the fallback', async ($, on) => {
  const logs: string[] = [];
  on('command.register', () => ({ deny: 'name already taken' }));
  on('ui.log', ($, e) => {
    logs.push(e.text);
    return { value: undefined };
  });
  on('session.start', () => ({ cwd: '/project' }));
  const result = await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/project' });
  expect(result.cwd).toBe('/project');
  expect(logs[0]).toMatch(/\/ioncache-ai-tools:plugin-settings/);
});
