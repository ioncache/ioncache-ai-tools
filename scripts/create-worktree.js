#!/usr/bin/env node
// Wraps the git worktree add command and applies the repo's
// .worktree-setup.json, so a new worktree isn't missing untracked local
// config, generated caches, or per-repo setup steps that the main worktree has.
//
// Usage: node create-worktree.js <same args you'd pass to the git command>
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

function applySetup(mainRoot, worktreePath) {
  const config = loadSetup(mainRoot)
  const expand = (text) =>
    text.replaceAll('${worktreePath}', worktreePath).replaceAll('${mainRoot}', mainRoot)
  const applied = []

  for (const rel of config.copies || []) {
    const src = path.join(mainRoot, rel)
    if (!fs.existsSync(src)) continue
    fs.cpSync(src, path.join(worktreePath, rel), { recursive: true })
    applied.push(`copied ${rel}`)
  }

  for (const { path: rel, content } of config.afterCopy || []) {
    const dest = path.join(worktreePath, rel)
    fs.mkdirSync(path.dirname(dest), { recursive: true })
    fs.writeFileSync(dest, expand(content))
    applied.push(`wrote ${rel}`)
  }

  for (const pattern of config.symlinks || []) {
    for (const rel of expandGlob(mainRoot, pattern)) {
      const src = path.join(mainRoot, rel)
      if (!fs.existsSync(src)) continue

      const dest = path.join(worktreePath, rel)
      fs.mkdirSync(path.dirname(dest), { recursive: true })
      try {
        fs.symlinkSync(src, dest, fs.statSync(src).isDirectory() ? 'dir' : 'file')
        applied.push(`linked ${rel}`)
      } catch (err) {
        if (err.code !== 'EEXIST') throw err
      }
    }
  }

  // The first failing command stops the run, and what was already applied is
  // reported so a half-applied setup is visible rather than silently skipped.
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

function main() {
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
