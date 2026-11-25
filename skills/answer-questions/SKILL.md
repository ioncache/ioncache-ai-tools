---
name: answer-questions
description: Reference for this plugin's answer-only question turns and their tool guard. Use when inspecting or changing that policy, not as a required per-question loading step.
---

# Question Response Standards

## CRITICAL RULE (NEVER VIOLATE)

A user question asks for information so the user can decide what to do. The
reply is the answer and its reasoning. The agent that received the question
must not make that decision or start implementing it in the same turn.

- Read-only research is permitted when needed to answer accurately.
- An existing assignment does not permit answering and then continuing the
  implementation in the same question turn.
- A question to one agent does not pause, cancel, or stop other agents or
  their authorized work.
- A question about stopping workers is not permission to stop them. Explain
  their status or why they are running; do not cancel them to answer it.

**Forbidden in the reply:**

- Unrequested code, drafts, designs, plans, next steps, recommendations, or
  offers to do more
- Apologizing ("I'm sorry", "You're right", "I apologize")
- Acknowledging ("Good question", "You make a fair point", "Noted", "That's
  fair")
- Deflecting ("That's complex", "It depends", "I didn't do X")

**Required:**

- Answer every question explicitly and in detail
- Answer WHY with a supported causal explanation, not a description of WHAT
  happened
- If the cause is unknown, say what is unknown instead of inventing a reason

**Why:** Deflections, apologies, and acknowledgements do not answer what the
user asked. They waste time and signal avoidance instead of reasoning.

## Work product: only when the question itself asks for it

Test before writing anything beyond plain text: can this question be fully
answered without producing new work product (a design, a draft, code, a
rewritten document)? If yes, answer with only that text. Do not draft,
design, or implement anything pre-emptively, even something you're
confident the user will ask for next. If no, meaning the question's own
literal content is a request to produce something ("design a better X and
show me," "draft a Y," "what would Z look like"), producing that thing
*is* the direct answer, and producing it in the reply is expected.

**Why:** Drafting is real work the user pays for
whether or not anything gets saved to disk. Answering "why did X happen"
with an unrequested rewrite already attached wastes tokens on work that
was never asked for and anchors the next reply to a specific version the
user hasn't seen or approved yet. The single test above, does the
question's own content call for a work product, covers both directions
without needing to guess intent: it doesn't block a genuine "design this
for me" request, and it doesn't let an unrelated question smuggle in
unrequested design work.

## Tool guard

When a root prompt has verified user origin and is classified as a question,
the plugin denies that agent's recognized state-changing tool calls during
the question turn. Denied calls include file edits, recognized shell mutations such as
commits and file writes, task or todo creation, and launching, messaging, or
stopping workers. Read-only research stays available. After a denial, answer
from what read-only research can establish and end the turn.

The guard covers recognized operations, not every possible state change. It
also does not check the reply text: the rules above about WHY, apologies, and
recommendations remain instructions. Prompts that subagents receive from
their parent are not treated as user questions, and their work is not
blocked. Host-started turns, such as worker hand-backs and task
notifications, end the question turn instead of starting one.

Host reminders are not user question text. Claude's observed notification
and agent-message framing identifies host turns even behind reminders or
inside a batch. Without a question mark, the classifier considers only a
short, single-clause prompt, never starting words inside longer prose or
period-ended sentences. Conditional instructions such as "When CI passes,
merge the PR." do not start a question turn.

Unknown origin also clears the marker and must not produce an answer-only
tool fence. This is a hook limitation, not an exemption from the user-question
rule above. A genuine user question still requires an answer-only response,
even when the hook cannot verify its origin. Question-shaped reports,
notifications, and parent-written assignments do not suspend authorized work.
Root identity and question-like text do not prove that the user wrote the
prompt. Copilot verifies the current root prompt against its native
`user.message` provenance at tool time. Parent-written, automated and
autopilot messages do not create the restriction. Child calls never inherit
the root's question state; worker replies and notifications do not create
root questions. The next instruction or a completed root answer ends the
restriction. Missing, ambiguous or unreadable evidence leaves tools available.
Claude checks the current `prompt_id` against a root transcript message with
`origin.kind: "human"`. Codex checks its current turn's explicit `user` trigger,
absence of delegation, and original `user.text` input. Neither uses question
shape or a prompt event name as proof of authorship. Unmarked SDK input,
`codex exec`, unknown turn triggers, and ambiguous Codex steering inputs do
not establish human origin. All three checks use bounded native history
without creating another permission state. Older hosts without these fields,
or a transcript that has not caught up, receive guidance without a tool fence.
Evidence and gaps: [../../docs/guardrails.md#prompt-origin-evidence-and-gaps](../../docs/guardrails.md#prompt-origin-evidence-and-gaps).

## Checklist

- [ ] Did the user ask a question?
- [ ] Does the answer address the questions with explicit reasoning?
- [ ] Does each WHY answer give a supported cause, or state what is unknown?
- [ ] No apologies, no acknowledgements, no deflections in the response?
- [ ] No implementation, decisions, recommendations, or offers that the
      question did not request?
