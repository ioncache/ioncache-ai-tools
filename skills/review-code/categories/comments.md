# Comments and Documentation

## Distinguish implementation comments from API documentation

Implementation comments explain non-obvious reasoning inside code. Apply the
why-only rules below to those comments, not to caller-facing API documentation.

Native doc comments and docstrings may need to describe what an operation does:
parameters, returns, failures, side effects and caller-visible guarantees. Keep
that contract information when the project's documentation conventions or
tools use it. Readable implementation does not replace a public contract.
Use the target language's established format; do not impose JSDoc on another
language or omit native documentation because no dedicated guide is shipped.

Keep both kinds accurate and about the present contract. Do not add narration
about an assistant's edits or invent documentation obligations unsupported by
the project.

## Implementation comment rules

1. **DEFAULT: NO COMMENT**, only add comments when absolutely necessary
2. **ONLY WHY, NEVER WHAT**, explain the reason/decision, not what the code
   does
3. **NEVER comment about removed/refactored/changed code**, comments describe
   present code only
4. **NEVER mention LLM actions**, no "imported function", "removed code",
   "refactored", etc.
5. **Code should be self-documenting**, fix unclear code instead of commenting
   it

## When implementation comments are useful

Add a WHY comment ONLY when the reader would genuinely struggle to understand
the decision without it:

- **Non-obvious decisions**: Why this approach over alternatives
- **Edge cases**: Why special handling is needed
- **Performance trade-offs**: Why we accept certain costs
- **Magic numbers**: Why this specific value

## Implementation comment examples

```javascript
// BAD: Describing what code does
// Loop through items and sum prices
const total = items.reduce((sum, item) => sum + item.price, 0)

// BAD: Redundant with function name
// Calculate the total
function calculateTotal() {}

// BAD: Describing removed code
// Removed the old validation logic

// BAD: Mentioning refactoring
// Refactored to use new helper function

// BAD: LLM action commentary
// Imported the helper function
// Updated this section per requirements

// GOOD: Explains WHY
// Using reduce instead of forEach to avoid mutation
const total = items.reduce((sum, item) => sum + item.price, 0)

// GOOD: Explains non-obvious decision
// 0.7 threshold balances precision/recall based on historical data analysis
const DETECTION_THRESHOLD = 0.7
```

## Implementation comment checklist

- [ ] No comment added unless truly necessary
- [ ] Comment explains WHY, never WHAT
- [ ] No mention of removed/refactored/changed code
- [ ] No LLM action descriptions ("imported", "removed", "refactored")
- [ ] Comment is about present behavior only
- [ ] Could not make code clearer instead of commenting
