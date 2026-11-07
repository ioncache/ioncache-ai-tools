#!/usr/bin/env node
const { execFileSync } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')
const semver = require('semver')

const MANIFESTS = [
  '.claude-plugin/plugin.json',
  '.codex-plugin/plugin.json',
  '.github/plugin/plugin.json'
]
const CATEGORIES = ['New', 'Updated', 'Fixed']
const COMMIT_TYPES = [
  { type: 'feat', section: 'New' },
  { type: 'feature', section: 'New' },
  { type: 'chore', section: 'Updated' },
  { type: 'revert', section: 'Updated' },
  { type: 'fix', section: 'Fixed' }
]

/**
 * @typedef {Object} PluginManifest
 * @property {string} version - Stable plugin version
 * @typedef {Object} CommitRange
 * @property {string} from - Exclusive release-boundary SHA
 * @property {string} to - Inclusive, pinned HEAD SHA
 */

/**
 * Runs Git without a shell so arguments remain literal.
 * @param {string} root - Repository directory
 * @param {...string} args - Git arguments
 * @returns {string} Trimmed stdout
 * @throws {Error} When Git fails
 * @example
 * const head = git(process.cwd(), 'rev-parse', 'HEAD')
 */
function git(root, ...args) {
  return execFileSync('git', ['--no-pager', ...args], {
    cwd: root,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe']
  }).trim()
}

/**
 * Restricts releases to canonical, stable versions.
 * @param {string} version - Candidate version
 * @returns {void}
 * @throws {Error} When the version is not stable MAJOR.MINOR.PATCH
 * @example
 * assertVersion('1.8.0')
 */
function assertVersion(version) {
  if (semver.valid(version) !== version || !/^\d+\.\d+\.\d+$/.test(version)) {
    throw new Error('Versions must use MAJOR.MINOR.PATCH with no leading zeroes.')
  }
}

/**
 * Retains complete manifests so version updates preserve unrelated metadata.
 * @param {string} root - Repository directory
 * @returns {Map<string, PluginManifest>} Manifests keyed by relative path
 * @throws {Error} When a manifest cannot be read or versions differ
 * @throws {SyntaxError} When a manifest is invalid JSON
 * @example
 * const manifests = readManifests(process.cwd())
 */
function readManifests(root) {
  const manifests = new Map()
  const versions = new Set()
  for (const name of MANIFESTS) {
    const manifest = JSON.parse(fs.readFileSync(path.join(root, name), 'utf8'))
    assertVersion(manifest?.version)
    manifests.set(name, manifest)
    versions.add(manifest.version)
  }
  if (versions.size !== 1) {
    throw new Error('All three plugin manifests must have the same version.')
  }
  return manifests
}

/**
 * Checks the latest release without requiring tags or complete Git history.
 * @param {string} text - Existing changelog
 * @param {string} version - Expected manifest version
 * @returns {number} Offset where a new release can be prepended
 * @throws {Error} When the version, date, sections or bullet lists are invalid
 * @example
 * const insertion = checkChangelog(fs.readFileSync('CHANGELOG.md', 'utf8'), '1.7.0')
 */
function checkChangelog(text, version) {
  const entries = [...text.matchAll(/^## (.+)$/gm)]
  const heading = new RegExp(`^${version.replaceAll('.', '\\.')} \\((\\d{4}-\\d{2}-\\d{2})\\)$`)
  const match = heading.exec(entries[0]?.[1] || '')
  if (!match) {
    throw new Error(`CHANGELOG.md must start with a release entry for ${version}.`)
  }
  const date = new Date(match[1])
  if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== match[1]) {
    throw new Error('The latest changelog entry must have a valid date.')
  }
  const body = text.slice(entries[0].index + entries[0][0].length, entries[1]?.index)
  const sections = body.matchAll(/^### ([^\n]+)\n([\s\S]*?)(?=^### |(?![\s\S]))/gm)
  const categories = []
  for (const [, name, items] of sections) {
    if (CATEGORIES.includes(name)) categories.push(name)
    if (!/^[*-] \S/m.test(items)) {
      throw new Error('Each changelog section needs a bullet list; use "- None." when empty.')
    }
  }
  if (categories.join(',') !== CATEGORIES.join(',')) {
    throw new Error('The latest changelog entry must have New, Updated and Fixed sections, in that order.')
  }
  return entries[0].index
}

/**
 * Finds the version transition rather than a later metadata-only edit.
 * @param {string} root - Repository directory
 * @param {string} version - Current plugin version
 * @param {string} head - Pinned HEAD SHA
 * @returns {string} Commit that introduced the current version
 * @throws {Error} When history is shallow, Git fails or the boundary is absent
 * @throws {SyntaxError} When a historical manifest is invalid JSON
 * @example
 * const from = releaseBoundary(process.cwd(), '1.7.0', git(process.cwd(), 'rev-parse', 'HEAD'))
 */
function releaseBoundary(root, version, head) {
  if (git(root, 'rev-parse', '--is-shallow-repository') === 'true') {
    throw new Error('Release generation requires full Git history, not a shallow checkout.')
  }
  let boundary
  const revisions = git(root, 'log', '--first-parent', '--format=%H', head, '--', MANIFESTS[0])
  for (const revision of revisions.split('\n')) {
    if (!revision) continue
    const manifest = JSON.parse(git(root, 'show', `${revision}:${MANIFESTS[0]}`))
    if (manifest.version !== version) break
    boundary = revision
  }
  if (!boundary) throw new Error(`No committed release boundary found for ${version}.`)
  return boundary
}

/**
 * Keeps legacy and non-feature/fix commits visible through the preset's Updated type.
 * @param {import('conventional-changelog').Commit} commit - Package-parsed commit
 * @returns {Partial<import('conventional-changelog').Commit>} Preset input overrides
 * @example
 * generator.options({ transformCommit: normalizeCommit })
 */
function normalizeCommit(commit) {
  const type = commit.type?.toLowerCase()
  return {
    type: ['feat', 'feature', 'fix'].includes(type) ? type : 'chore',
    subject: commit.subject || commit.header
  }
}

/**
 * Supplies empty categories while leaving all Markdown rendering to the preset.
 * @param {import('conventional-changelog').FinalizedContext} context - Writer context
 * @returns {import('conventional-changelog').FinalizedContext} Complete category list
 * @example
 * generator.writer({ finalizeContext: completeCategories })
 */
function completeCategories(context) {
  const groups = new Map()
  for (const group of context.commitGroups) groups.set(group.title, group)
  const commitGroups = []
  for (const title of CATEGORIES) {
    commitGroups.push(groups.get(title) || { title, commits: [{ subject: 'None.' }] })
  }
  return { ...context, commitGroups }
}

/**
 * Keeps generated note headings in the repository's plain punctuation style.
 * @returns {string} Empty icon
 * @example
 * const preset = { name: 'conventionalcommits', formatNoteIcon: omitNoteIcon }
 */
function omitNoteIcon() {
  return ''
}

/**
 * Uses the package parser and writer for one explicitly bounded release.
 * @param {string} root - Repository directory
 * @param {string} version - New plugin version
 * @param {CommitRange} range - Pinned release range
 * @returns {Promise<string>} Rendered release entry
 * @throws {Error} When package loading or changelog generation fails
 * @example
 * const entry = await releaseEntry(process.cwd(), '1.8.0', { from: boundary, to: head })
 */
async function releaseEntry(root, version, range) {
  const { ConventionalChangelog } = await import('conventional-changelog')
  const generator = new ConventionalChangelog(root)
    .loadPreset({ name: 'conventionalcommits', types: COMMIT_TYPES, formatNoteIcon: omitNoteIcon })
    .repository('https://github.com/ioncache/ioncache-ai-tools')
    .context({ version, linkCompare: false })
    .commits({ ...range, merges: false })
    .options({ transformCommit: normalizeCommit })
    .writer({
      generateOn: null,
      doFlush: true,
      ignoreReverted: false,
      finalizeContext: completeCategories
    })
  let entry = ''
  for await (const chunk of generator.write()) entry += chunk
  return entry.trimEnd().replaceAll('\u2014', ', ') + '\n\n'
}

/**
 * Prevents uncommitted changes from being omitted from Git-derived notes.
 * @param {string} root - Repository directory
 * @returns {void}
 * @throws {Error} When Git fails or tracked/untracked changes exist
 * @example
 * assertClean(process.cwd())
 */
function assertClean(root) {
  if (git(root, 'status', '--porcelain', '--untracked-files=all')) {
    throw new Error('Commit the intended changes and start with a clean worktree before releasing.')
  }
}

/**
 * Prepares coordinated release files without staging or publishing anything.
 * @param {string} root - Repository directory
 * @param {string} version - New stable version
 * @returns {Promise<void>}
 * @throws {Error} When validation, generation or file access fails
 * @throws {Error} When the version does not increase or HEAD changes during generation
 * @example
 * await bumpVersion(process.cwd(), '1.8.0')
 */
async function bumpVersion(root, version) {
  assertVersion(version)
  const manifests = readManifests(root)
  const current = manifests.get(MANIFESTS[0]).version
  if (!semver.gt(version, current)) {
    throw new Error(`The new version must be greater than ${current}.`)
  }
  const changelog = path.join(root, 'CHANGELOG.md')
  const previous = fs.readFileSync(changelog, 'utf8')
  const insertion = checkChangelog(previous, current)
  assertClean(root)
  const head = git(root, 'rev-parse', 'HEAD')
  const from = releaseBoundary(root, current, head)
  const entry = await releaseEntry(root, version, { from, to: head })
  const updated = previous.slice(0, insertion) + entry + previous.slice(insertion)
  checkChangelog(updated, version)
  if (git(root, 'rev-parse', 'HEAD') !== head) {
    throw new Error('HEAD changed while generating the changelog; retry from a stable worktree.')
  }
  assertClean(root)
  for (const [name, manifest] of manifests) {
    fs.writeFileSync(path.join(root, name), JSON.stringify({ ...manifest, version }, null, 2) + '\n')
  }
  fs.writeFileSync(changelog, updated)
}

/**
 * Separates read-only checks from release preparation at the CLI boundary.
 * @returns {Promise<void>}
 * @throws {Error} When arguments are invalid or the selected operation fails
 * @example
 * // node scripts/release.js --check
 * await main()
 */
async function main() {
  const args = process.argv.slice(2)
  if (args.length === 1 && ['--help', '-h'].includes(args[0])) {
    console.log('Usage: npm run release -- MAJOR.MINOR.PATCH | npm run release:check')
    console.log('Updates all three plugin manifests and CHANGELOG.md; does not commit, tag or push.')
    return
  }
  if (args.length !== 1) throw new Error('Provide either a version or --check.')
  const root = git(process.cwd(), 'rev-parse', '--show-toplevel')
  if (args[0] === '--check') {
    const version = readManifests(root).get(MANIFESTS[0]).version
    checkChangelog(fs.readFileSync(path.join(root, 'CHANGELOG.md'), 'utf8'), version)
    console.log(`Changelog and plugin manifests agree on ${version}.`)
    return
  }
  await bumpVersion(root, args[0])
  console.log(`Prepared ${args[0]} in all three manifests and CHANGELOG.md. Review and commit these files together.`)
}

/**
 * Reports CLI failures without an unhandled-rejection stack trace.
 * @param {Error} error - Failed operation
 * @returns {void}
 * @example
 * main().catch(reportError)
 */
function reportError(error) {
  console.error(`release: ${error.message}`)
  process.exitCode = 2
}

main().catch(reportError)
