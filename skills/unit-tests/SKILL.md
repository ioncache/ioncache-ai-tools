---
name: unit-tests
description: Use when writing or reviewing JavaScript/TypeScript unit tests with Vitest, for BDD structure, AAAR comments, and coverage/mocking conventions. Opinionated, assumes Vitest.
---

# Unit Testing Standards (Vitest)

**Applies to:** JavaScript/TypeScript with Vitest.

## Core Principles

1. Use AAAR (Arrange, Act, Assert, Revert) comments for test clarity
2. Aim for 100% coverage; use `/* istanbul ignore next */` with justification
3. BDD format: `describe()` blocks + `it()` (NEVER use `test()`)
4. Test titles MUST start with `should` and describe behavior
5. Colocate tests with the source file they cover

## Test Structure

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

## Coverage & Mocking

**Coverage:** Use `/* istanbul ignore next */` only when necessary (error
boundaries, third-party code, platform-specific, E2E-tested UI). Add a comment
explaining why.

**Mocking:** Avoid when possible. If needed, mock at the lowest level and
document why. Prefer refactoring for testability:

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

## Test Execution (MANDATORY)

**After ANY test file change** (new tests, edits, refactors), you MUST:

1. Run the modified test file
2. Fix failures
3. Repeat until green

Do not consider test changes complete until tests pass.

## BDD Format Requirements

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

## AAAR Comments

Use in every non-trivial test:

- `// Arrange`, setup/given
- `// Act`, when
- `// Assert`, then
- `// Revert`, cleanup (or use `afterEach`)

Simple tests with obvious steps may omit these.

## Example Test

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
