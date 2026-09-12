#!/usr/bin/env node
// Wraps the git worktree add command and applies the repo's
// .worktree-setup.json, so a new worktree isn't missing untracked local
// config, generated caches, or per-repo setup steps that the main worktree has.
//
// Usage: node create-worktree.js <same args you'd pass to the git command>
// Self-test: node create-worktree.js --self-test
//
// A repo with no .worktree-setup.json gets one written with generic defaults
// (Claude Code local config symlinks) on first use, so the file is always
// there to extend with repo-specific copies, symlinks and commands.

const { execFileSync, spawnSync } = require('child_process')
const fs = require('fs')
const path = require('path')

const SETUP_FILE = '.worktree-setup.json'

/**
 * @typedef {Object} AfterCopyEntry
 * @property {string} path - Destination, relative to the worktree root
 * @property {string} content - File body; `${worktreePath}` and `${mainRoot}` are expanded
 * @typedef {Object} WorktreeSetup
 * @property {string[]} [copies]
 * @property {AfterCopyEntry[]} [afterCopy]
 * @property {string[]} [symlinks]
 * @property {string[]} [commands]
 */

const DEFAULT_SETUP = {
  copies: [],
  afterCopy: [],
  symlinks: [
    '.claude/settings.local.json',
    '.claude/hooks',
    'CLAUDE.local.md',
    '.claude/hookify.*.local.md'
  ],
  commands: []
}

function listWorktrees(cwd) {
  const out = execFileSync('git', ['worktree', 'list', '--porcelain'], {
    cwd,
    encoding: 'utf8'
  })
  return out
    .split('\n')
    .filter((line) => line.startsWith('worktree '))
    .map((line) => line.slice('worktree '.length))
}

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

// Only a single `*` wildcard within one path segment is supported - the one
// real use case is matching a set of sibling files (e.g. `rules.*.local.md`).
function expandGlob(root, pattern) {
  if (!pattern.includes('*')) return [pattern]

  const dir = path.dirname(pattern)
  const base = path.basename(pattern)
  const regex = new RegExp('^' + base.split('*').map(escapeRegExp).join('.*') + '$')
  const absDir = path.join(root, dir)
  if (!fs.existsSync(absDir)) return []

  return fs
    .readdirSync(absDir)
    .filter((name) => regex.test(name))
    .map((name) => path.join(dir, name))
}

/**
 * Reads the repo's setup file, writing the generic default first if none exists.
 *
 * @param {string} mainRoot - Absolute path of the main worktree
 * @returns {WorktreeSetup} Parsed setup config
 * @throws {SyntaxError} When an existing setup file is not valid JSON
 *
 * @example
 * const config = loadSetup('/Users/mark/projects/my-repo')
 * // config.copies, config.afterCopy, config.symlinks, config.commands
 */
function loadSetup(mainRoot) {
  const configPath = path.join(mainRoot, SETUP_FILE)
  if (fs.existsSync(configPath)) {
    return JSON.parse(fs.readFileSync(configPath, 'utf8'))
  }
  fs.writeFileSync(configPath, JSON.stringify(DEFAULT_SETUP, null, 2) + '\n')
  console.log(
    `create-worktree: wrote default ${SETUP_FILE} to ${mainRoot} - extend it with repo-specific copies, symlinks and commands`
  )
  return DEFAULT_SETUP
}

/**
 * Runs a repo's post-create setup commands in the new worktree, in order.
 * The first failing command stops the run and exits the process; every item
 * applied so far (including from earlier setup steps) is reported first, so
 * a half-applied setup is visible rather than silently skipped.
 *
 * @typedef {Object} RunSetupCommandsOptions
 * @property {WorktreeSetup} config - Parsed setup config
 * @property {string} worktreePath - Absolute path of the new worktree
 * @property {(text: string) => string} expand - Substitutes `${worktreePath}`/`${mainRoot}` placeholders
 * @property {string[]} applied - Descriptions of setup already applied; mutated with one entry per command run
 *
 * @param {RunSetupCommandsOptions} options
 * @returns {void}
 */
function runSetupCommands({ config, worktreePath, expand, applied }) {
  for (const command of config.commands || []) {
    const expanded = expand(command)
    const result = spawnSync(expanded, { cwd: worktreePath, shell: true, stdio: 'inherit' })
    if (result.status !== 0) {
      report(applied, worktreePath)
      console.error(`create-worktree: command failed (exit ${result.status}): ${expanded}`)
      process.exit(result.status ?? 1)
    }
    applied.push(`ran ${expanded}`)
  }
}

/**
 * Confirms `absPath`'s real, symlink-resolved location stays within
 * `resolvedRoot`. A lexically-safe path (no literal `..`) can still land
 * outside root if a symlink anywhere along it redirects there, so this
 * resolves the nearest EXISTING ancestor (the target itself may not exist
 * yet, e.g. a destination being created) with `fs.realpathSync`, which
 * follows every symlink in that chain, and checks the result.
 *
 * @param {string} resolvedRoot - Root directory, already path.resolve'd
 * @param {string} absPath - Absolute path to check
 * @param {string} rel - Original relative path, for the error message
 * @throws {Error} If a symlink redirects the real path outside root
 */
function assertRealPathWithinRoot(resolvedRoot, absPath, rel) {
  const realRoot = fs.realpathSync(resolvedRoot)
  let existing = absPath
  while (!fs.existsSync(existing)) {
    const parent = path.dirname(existing)
    if (parent === existing) break
    existing = parent
  }
  const real = fs.realpathSync(existing)
  if (real !== realRoot && !real.startsWith(realRoot + path.sep)) {
    throw new Error(`.worktree-setup.json path escapes its root via a symlink (${resolvedRoot}): ${rel}`)
  }
}

/**
 * Resolves `rel` against `root` and rejects it if the result would land
 * outside `root`, lexically (a `..`-escaping entry) or via a symlink
 * component. .worktree-setup.json is committed repo content, not
 * necessarily trustworthy.
 *
 * @param {string} root - Absolute path the result must stay inside
 * @param {string} rel - Path from the setup config, relative to root
 * @returns {string} The resolved absolute path
 * @throws {Error} If the resolved path escapes root
 */
function resolveWithinRoot(root, rel) {
  const resolvedRoot = path.resolve(root)
  const resolved = path.resolve(resolvedRoot, rel)
  if (resolved !== resolvedRoot && !resolved.startsWith(resolvedRoot + path.sep)) {
    throw new Error(`.worktree-setup.json path escapes its root (${root}): ${rel}`)
  }
  assertRealPathWithinRoot(resolvedRoot, resolved, rel)
  return resolved
}

/**
 * Applies a repo's .worktree-setup.json to a freshly created worktree:
 * copies, generated files, symlinks, then post-create commands, in order.
 *
 * @param {string} mainRoot - Absolute path of the main worktree
 * @param {string} worktreePath - Absolute path of the new worktree
 * @returns {void}
 */
function applySetup(mainRoot, worktreePath) {
  const config = loadSetup(mainRoot)
  const expand = (text) =>
    text.replaceAll('${worktreePath}', worktreePath).replaceAll('${mainRoot}', mainRoot)
  const applied = []

  for (const rel of config.copies || []) {
    const src = resolveWithinRoot(mainRoot, rel)
    if (!fs.existsSync(src)) continue
    fs.cpSync(src, resolveWithinRoot(worktreePath, rel), { recursive: true })
    applied.push(`copied ${rel}`)
  }

  for (const { path: rel, content } of config.afterCopy || []) {
    const dest = resolveWithinRoot(worktreePath, rel)
    fs.mkdirSync(path.dirname(dest), { recursive: true })
    fs.writeFileSync(dest, expand(content))
    applied.push(`wrote ${rel}`)
  }

  for (const pattern of config.symlinks || []) {
    for (const rel of expandGlob(mainRoot, pattern)) {
      const src = resolveWithinRoot(mainRoot, rel)
      if (!fs.existsSync(src)) continue

      const dest = resolveWithinRoot(worktreePath, rel)
      fs.mkdirSync(path.dirname(dest), { recursive: true })
      try {
        fs.symlinkSync(src, dest, fs.statSync(src).isDirectory() ? 'dir' : 'file')
        applied.push(`linked ${rel}`)
      } catch (err) {
        if (err.code !== 'EEXIST') {
          report(applied, worktreePath)
          throw err
        }
      }
    }
  }

  runSetupCommands({ config, worktreePath, expand, applied })
  report(applied, worktreePath)
}

/**
 * Prints the list of setup items applied to a worktree.
 *
 * @param {string[]} applied - Human-readable descriptions of each applied item
 * @param {string} worktreePath - Absolute path of the new worktree
 * @returns {void}
 */
function report(applied, worktreePath) {
  console.log(`create-worktree: applied ${SETUP_FILE} (${applied.length} item(s)) into ${worktreePath}`)
  for (const item of applied) console.log(`  ${item}`)
}

function selfTest() {
  const assert = require('assert')
  const os = require('os')

  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'create-worktree-self-test-'))
  const root = fs.mkdtempSync(path.join(tmp, 'root-'))
  const outside = fs.mkdtempSync(path.join(tmp, 'outside-'))

  assert.strictEqual(resolveWithinRoot(root, 'a/b.txt'), path.resolve(root, 'a/b.txt'))
  assert.throws(() => resolveWithinRoot(root, '../../etc/passwd'), /escapes its root/)
  assert.throws(() => resolveWithinRoot(root, `../${path.basename(outside)}/x`), /escapes its root/)

  // Symlink-based escape: no literal ".." in the config, but an existing
  // ancestor is a symlink that redirects outside root once resolved.
  fs.symlinkSync(outside, path.join(root, 'escape-link'), 'dir')
  fs.writeFileSync(path.join(outside, 'x'), 'secret')
  assert.throws(() => resolveWithinRoot(root, 'escape-link/x'), /escapes its root/, 'source path via a symlinked ancestor should be rejected')
  assert.throws(() => resolveWithinRoot(root, 'escape-link/new-file.txt'), /escapes its root/, 'destination path via a symlinked ancestor should be rejected, even though the file itself does not exist yet')

  fs.rmSync(tmp, { recursive: true, force: true })
  console.log('create-worktree self-test passed')
}

function main() {
  if (process.argv[2] === '--self-test') {
    selfTest()
    return
  }

  const args = process.argv.slice(2)
  if (args.length === 0) {
    console.error('usage: create-worktree.js <same args as the git command>')
    process.exit(1)
  }

  const cwd = process.cwd()
  const before = new Set(listWorktrees(cwd))

  const result = spawnSync('git', ['worktree', 'add', ...args], { cwd, stdio: 'inherit' })
  if (result.status !== 0) process.exit(result.status ?? 1)

  const after = listWorktrees(cwd)
  const newWorktree = after.find((worktreePath) => !before.has(worktreePath))
  if (!newWorktree) return

  const mainWorktree = listWorktrees(newWorktree)[0]
  applySetup(mainWorktree, newWorktree)
}

main()
