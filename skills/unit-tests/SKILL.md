---
name: unit-tests
description: Use when writing or explicitly reviewing unit tests in the target project's language and framework. Apply Vitest conventions only to Vitest tests. Do not activate for an assigned review or validation of another category; supplied category packets need no wrapper load.
---

# Unit tests

Apply [../review-code/categories/unit-tests.md](../review-code/categories/unit-tests.md).
Keep this purpose bounded; do not load other categories or generic composers.

After any authorized test file change, run the modified test file and fix
failures until it passes within the task's limits. Do not consider test changes
complete while tests fail. This writing requirement grants no edits or execution
outside a read-only review's permissions.
