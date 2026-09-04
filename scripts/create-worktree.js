#!/usr/bin/env node
// Wraps `git worktree add` and applies a repo's optional
// .worktree-setup.json, so a new worktree isn't missing untracked local
// config, generated caches, or env files that the main worktree has.
//
// Usage: node create-worktree.js <same args you'd pass to `git worktree add`>
//
// A repo with no .worktree-setup.json gets a plain `git worktree add` -
// this is safe to use anywhere, not just repos that opt in.

const { execFileSync, spawnSync } = require('child_process')
const fs = require('fs')
const path = require('path')

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

function applySetup(mainRoot, worktreePath) {
  const configPath = path.join(mainRoot, '.worktree-setup.json')
  if (!fs.existsSync(configPath)) {
    console.log('create-worktree: no .worktree-setup.json in this repo, plain worktree created')
    return
  }

  const config = JSON.parse(fs.readFileSync(configPath, 'utf8'))
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
    fs.writeFileSync(dest, content.replaceAll('${worktreePath}', worktreePath))
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

  console.log(`create-worktree: applied .worktree-setup.json (${applied.length} item(s)) into ${worktreePath}`)
}

function main() {
  const args = process.argv.slice(2)
  if (args.length === 0) {
    console.error('usage: create-worktree.js <git worktree add args>')
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
