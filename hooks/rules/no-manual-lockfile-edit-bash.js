// Bash-side companion to no-manual-lockfile-edit.json: that rule only
// matches Edit/Write/MultiEdit, so a Bash mutation (redirection, sed -i,
// tee, perl -i) targeting a lockfile bypasses it entirely.

const LOCKFILE_PATTERN = /(package-lock\.json|yarn\.lock|pnpm-lock\.yaml)/
const MUTATION_PATTERN = /(>{1,2}|\btee\b|\bsed\s+-i\b|\bperl\s+-i\b)/

module.exports = {
  event: 'PreToolUse',
  toolNames: ['Bash'],
  matches(input) {
    const command = (input.tool_input || {}).command || ''
    return LOCKFILE_PATTERN.test(command) && MUTATION_PATTERN.test(command)
  },
  action: 'deny',
  message:
    'Never hand-edit a lockfile from Bash (redirection, sed -i, tee, perl -i). ' +
    'Resolve the conflict in package.json first, then regenerate the lockfile ' +
    "by running the package manager's install command."
}
