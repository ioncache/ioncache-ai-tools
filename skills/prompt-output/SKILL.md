---
name: prompt-output
description: Use whenever the task is to produce a prompt file (a .prompt.md file, or any "write me a prompt" request), for the required output format.
---

# Prompt Output Format

## Hard Rule

When the task is to produce a prompt, any phrasing of "write me a prompt,"
"create a prompt for X," "generate a prompt," or the output is a `.prompt.md`
file, the ENTIRE output MUST be a single code-fenced `markdown` block and
nothing else.

**Correct:**

````markdown
```markdown
---
description: '...'
---

Prompt content here.
```
````

**Forbidden:**

- Any prose before or after the code fence
- Labels such as "Here's the prompt:" or "Prompt:"
- Summary text such as "I've created the following prompt..."
- Multiple code fences
- Markdown rendered outside a code fence

## Why

Chat interfaces render markdown as HTML automatically. Text outside a code
fence is rendered into formatted HTML and loses its raw markdown, the user
cannot copy-paste it. A single code-fenced block is the only format that
survives rendering intact and is directly usable.
