---
name: comments
description: Use before adding a code comment, for the rule on when comments are warranted and how to write them (why, not what).
---

# Comments and Documentation

## CRITICAL RULES (NEVER VIOLATE)

1. **DEFAULT: NO COMMENT**, only add comments when absolutely necessary
2. **ONLY WHY, NEVER WHAT**, explain the reason/decision, not what the code
   does
3. **NEVER comment about removed/refactored/changed code**, comments describe
   present code only
4. **NEVER mention LLM actions**, no "imported function", "removed code",
   "refactored", etc.
5. **Code should be self-documenting**, fix unclear code instead of commenting
   it

## When Comments ARE Allowed

Add a WHY comment ONLY when the reader would genuinely struggle to understand
the decision without it:

- **Non-obvious decisions**: Why this approach over alternatives
- **Edge cases**: Why special handling is needed
- **Performance trade-offs**: Why we accept certain costs
- **Magic numbers**: Why this specific value

## Forbidden Comment Patterns

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

## Checklist (Verify EVERY Comment)

- [ ] No comment added unless truly necessary
- [ ] Comment explains WHY, never WHAT
- [ ] No mention of removed/refactored/changed code
- [ ] No LLM action descriptions ("imported", "removed", "refactored")
- [ ] Comment is about present behavior only
- [ ] Could not make code clearer instead of commenting
