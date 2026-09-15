#!/usr/bin/env node
// UserPromptSubmit hook: when a project has a graphify knowledge graph,
// tells the agent to use graphify query for codebase questions instead of
// grep, Read, or find.

const fs = require('fs')
const path = require('path')

function main() {
  const graphPath = path.join(process.cwd(), 'graphify-out', 'graph.json')
  if (!fs.existsSync(graphPath)) return

  console.log(
    JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'UserPromptSubmit',
        additionalContext:
          "graphify-out/graph.json exists in this project. You MUST use graphify query for codebase questions instead of grep, Read, or find. Run: graphify query '<your question>' and use those results."
      }
    })
  )
}

main()
