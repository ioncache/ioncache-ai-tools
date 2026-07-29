---
name: triage-errors
description: Systematically triage and fix errors after a large change, use when you have many test failures or lint errors to work through
---

You are fixing a batch of errors systematically. Do not fix them one at a time
in the order they appear, group them by root cause first.

## Process

1. **Collect all errors.** Run the failing command and capture every error.
2. **Group by root cause.** Many errors share a single cause (missing import,
   renamed function, changed signature, removed file). Identify the groups.
3. **Prioritize by dependency.** Fix upstream causes first, a missing export
   causes import errors in every consumer. Fix the export once, not each import
   individually.
4. **Fix one group.** Apply the fix for one root cause across all affected
   files.
5. **Re-run and repeat.** After each group fix, re-run the command to get a
   fresh error list. Some errors will have resolved as side effects.
6. **Stop when clean.** Continue until the command passes.

## Rules

- Never fix a downstream symptom when the upstream cause is unfixed
- After each fix group, re-run the check, do not assume which errors remain
- If an error is ambiguous, read the surrounding code before guessing at a fix
- If a fix would change behavior (not just fix a mechanical error), stop and ask
