# Unit testing standards

## Scope and framework selection

Review unit-test quality in the target code's actual language and framework.
Identify the runner and conventions from test imports, configuration, commands
and nearby tests. A dependency declaration alone does not establish which
framework runs a particular suite. Mixed-framework projects retain one
unit-testing purpose, with the appropriate conventions applied to each suite.

No dedicated framework guide does not mean unit testing is inapplicable.
Use the repository's established conventions and verified native documentation
for framework-specific details. Report a missing consequential fact rather than
inventing an API, changing frameworks or importing another framework's rules.

## Framework-neutral quality

- Assert observable behavior, including relevant supported failures and side
  effects. Assertions must fail when that behavior regresses, not merely repeat
  the implementation or confirm that a mock returned its configured value.
- Keep tests independent of order, shared mutable state and accidental timing.
  Use the framework's lifecycle and cleanup mechanisms to restore modified
  resources, mocks, clocks and environment values, including after failures.
- Prefer real dependencies when practical. Mock a meaningful boundary when
  needed, without hiding the failure or contract the test is meant to exercise.
  Explain non-obvious mock choices; do not refactor production code solely to
  satisfy a different framework's testing idiom.
- Preserve native test discovery, names, layout, fixtures and assertion APIs.
  Do not require `describe`/`it`, `should` titles, AAAR comments or colocated tests
  outside the Vitest conventions below or an explicit project requirement.
- Keep the pass about unit-test quality and unit-level behavior. Do not replace
  it with general production-code discovery or a whole-system coverage review.

Aim for 100% coverage with meaningful assertions. Coverage percentages do not
prove assertion quality, and missing measurements are not proof of a gap.
Use only the configured coverage provider's documented exclusion mechanism,
with a concrete justification for each exclusion.

## Vitest conventions

The rest of this file applies only to suites actually using Vitest. Approved
project requirements override these defaults in their declared scope.
These examples are not instructions to convert another runner to Vitest.

- Use AAAR (Arrange, Act, Assert, Revert) comments for non-trivial test clarity.
- Use BDD `describe()` blocks and `it()` cases, not `test()`.
- Start test titles with `should` and describe observable behavior.
- Colocate tests with the source they cover unless the project specifies another
  layout.

### Test structure

```javascript
import { describe, it, expect, beforeEach } from 'vitest'
import { functionToTest } from './moduleToTest'

describe('moduleToTest.js', () => {
  describe('functionToTest', () => {
    it('should do something specific when given certain input', () => {
      // Arrange
      const input = 'test'

      // Act
      const result = functionToTest(input)

      // Assert
      expect(result).toBe('expected')
    })
  })
})
```

### Mocking

Use the actual dependency seam rather than mocking more than the test needs.
For example, an explicit clock value can avoid a global clock mock:

```javascript
// Before: requires mocking Date
function getCurrentTime() {
  return new Date().toISOString()
}

// After: testable via dependency injection
function getCurrentTime(date = new Date()) {
  return date.toISOString()
}
```

### BDD format requirements

- Use `describe()` for context and unit under test
- Use `it()` for test cases (NEVER use `test()`)
- Titles MUST start with `should` + observable behavior
- One behavior per test when possible

```javascript
describe('Calculator', () => {
  describe('add', () => {
    it('should return sum of two positive numbers', () => {})
    it('should handle negative numbers correctly', () => {})
    it('should throw error for non-numeric input', () => {})
  })
})
```

### AAAR comments

Use in every non-trivial test:

- `// Arrange`, setup/given
- `// Act`, when
- `// Assert`, then
- `// Revert`, cleanup (or use `afterEach`)

Simple tests with obvious steps may omit these.

### Example test

```javascript
import { describe, it, expect, beforeEach } from 'vitest'
import { processRanges } from './labResults'

describe('labResults.js', () => {
  describe('processRanges', () => {
    let ranges, value, options

    beforeEach(() => {
      // Arrange
      ranges = {
        optimal: [[0, 10]],
        warning: [[11, 20]],
        danger: [[21, 30]]
      }
      value = 15
      options = {}
    })

    it('should return correct range info for value in warning range', () => {
      // Act
      const result = processRanges(ranges, value, options)

      // Assert
      expect(result.activeRange.type).toBe('warning')
      expect(result.percent).toBeGreaterThan(0)
      expect(result.percent).toBeLessThan(100)
    })

    it('should handle null ranges gracefully', () => {
      // Arrange
      ranges = null

      // Act
      const result = processRanges(ranges, value, options)

      // Assert
      expect(result.noRanges).toBe(true)
      expect(result.percent).toBe(50)
    })
  })
})
```
