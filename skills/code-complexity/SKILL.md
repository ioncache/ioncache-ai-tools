---
name: code-complexity
description: Use when writing or reviewing functions, for guidance on parameter counts, nesting depth, function length, and single-responsibility structure.
---

# Code Complexity Guidelines

## Core Principles

1. Functions should be cohesive and focused on a clear responsibility
2. Prefer correctness and readability over strict metrics
3. Functions should be pure when possible
4. Avoid side effects and global state dependencies

Apply [engineering judgment](../engineering-judgment/SKILL.md) when a local
refactor affects contracts or responsibility boundaries. Do not split cohesive
logic, hide dependencies, or move work into the wrong layer to satisfy a metric.

## Guidelines

- Prefer at most 3 independent parameters. Group related values or options
  when that reflects their meaning, not merely to hide the parameter count.
- Prefer at most 3 nesting levels. Use early returns and guard clauses when
  they clarify control flow without changing behavior.
- **Target under 30 lines per function**, longer is fine if cohesive and clear
- **Target cyclomatic complexity under 15**, higher is fine if the logic is
  simple and related

## Key Patterns

**Use early returns to reduce nesting:**

```javascript
// Bad: Deep nesting
function process(order) {
  if (order.isValid) {
    if (order.items.length > 0) {
      if (order.customer.isActive) {
        return doWork(order)
      }
    }
  }
  return null
}

// Good: Guard clauses
function process(order) {
  if (!order.isValid) {
    return null
  }
  if (order.items.length === 0) {
    return null
  }
  if (!order.customer.isActive) {
    return null
  }
  return doWork(order)
}
```

**Use object parameters for related data:**

```javascript
// Bad: Too many params
function createUser(name, email, age, address, phone) {}

// Good: Grouped params
function createUser(userData) {
  const { name, email, age, address, phone } = userData
}
```

**Extract by responsibility, not line count:**

An orchestration function can coordinate validation, persistence, and
notifications as one cohesive operation. Extract a helper when it isolates a
meaningful rule or boundary, not just to shorten the caller. Preserve every
required step, its ordering, and its error and side-effect contracts.

## Review Checklist

- [ ] Single responsibility
- [ ] Parameters express meaningful inputs without hiding dependencies
- [ ] Control flow is clear; metric exceptions preserve cohesion
- [ ] Clear, descriptive names
- [ ] No global state dependencies
