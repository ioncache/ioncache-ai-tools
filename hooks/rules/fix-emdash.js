// Ports fix_emdash_tool_input.py: silently rewrites em-dashes in Bash /
// Write / Edit / MultiEdit tool input before the tool runs. Builds the
// target character from its code point, never a literal, so this file
// itself is never mangled by the very rule it implements.

const EM_DASH = String.fromCharCode(0x2014)
const EM_DASH_PATTERN = new RegExp('\\s*' + EM_DASH + '\\s*', 'g')
const REPLACEMENT = ', '

function fix(text) {
  return text.replace(EM_DASH_PATTERN, REPLACEMENT)
}

function containsEmDash(text) {
  return typeof text === 'string' && text.includes(EM_DASH)
}

module.exports = {
  event: 'PreToolUse',
  toolNames: ['Bash', 'Write', 'Edit', 'MultiEdit'],
  matches(input) {
    const toolInput = input.tool_input || {}
    if (input.tool_name === 'Bash') return containsEmDash(toolInput.command)
    if (input.tool_name === 'Write') return containsEmDash(toolInput.content)
    if (input.tool_name === 'Edit') return containsEmDash(toolInput.new_string)
    if (input.tool_name === 'MultiEdit') return (toolInput.edits || []).some((edit) => containsEmDash(edit.new_string))
    return false
  },
  async check(input) {
    const toolInput = { ...(input.tool_input || {}) }
    if (input.tool_name === 'Bash') {
      toolInput.command = fix(toolInput.command)
    } else if (input.tool_name === 'Write') {
      toolInput.content = fix(toolInput.content)
    } else if (input.tool_name === 'Edit') {
      toolInput.new_string = fix(toolInput.new_string)
    } else if (input.tool_name === 'MultiEdit') {
      toolInput.edits = (toolInput.edits || []).map((edit) =>
        containsEmDash(edit.new_string) ? { ...edit, new_string: fix(edit.new_string) } : edit
      )
    }
    return {
      action: 'rewrite',
      updatedInput: toolInput,
      systemMessage: 'Auto-fixed em-dash(es) in tool input before execution.'
    }
  }
}
