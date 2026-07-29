---
name: jsdoc
description: Use when writing or reviewing JSDoc on JavaScript/TypeScript functions, for required tags, typedef rules, and formatting. Opinionated JS/TS documentation standard.
---

# JSDoc Documentation Standards

## CRITICAL REQUIREMENTS

1. **Every function MUST have JSDoc**, no exceptions
2. **NO inline type definitions**, use typedefs or imported types
3. **Import types from packages**, use `import('package').Type` syntax
4. **Include function description**, clear explanation of what it does
5. **Add @example for functions with I/O**, show actual usage patterns
6. **Add @throws for each error type**, document every throw statement with
   specific error condition

## Type Definition Rules

**Use `import()` for external types:**

```javascript
/**
 * @typedef {import('fastify').FastifyInstance} FastifyInstance
 * @typedef {import('mongodb').Collection} Collection
 */
```

**Define custom types as typedefs:**

```javascript
/**
 * @typedef {'optimal'|'warning'|'danger'} RangeType
 * @typedef {Object} EncounterFilters
 * @property {string} [member_id] - Member UUID
 * @property {string} [staff_id] - Staff UUID
 * @property {number} [page=1] - Page number
 * @property {number} [limit=100] - Items per page
 */
```

**Use `[...]` for arrays, not `Array<...>`:**

```javascript
@param {[number, number][]} ranges - Array of [min, max] pairs
@returns {string[]} Array of user IDs
```

## Complete Function Documentation

Every function needs:

1. **Description**, what the function does
2. **@param**, all parameters with imported/typedef types
3. **@returns**, return type (use `Promise<Type>` for async)
4. **@throws**, document error conditions
5. **@example**, usage example for functions with parameters or return values

```javascript
/**
 * Retrieves and enriches records with optional pagination.
 *
 * @param {import('mongodb').Collection} collection - MongoDB collection
 * @param {EncounterFilters} filters - Filter criteria
 * @returns {Promise<object>} Enriched results
 * @throws {Error} When the database operation fails
 *
 * @example
 * const result = await getRecords(collection, {
 *   member_id: 'uuid-123',
 *   page: 1,
 *   limit: 50
 * })
 */
async function getRecords(collection, filters) {
  // Implementation
}
```

## Type Accuracy Checklist

When documenting types, verify:

- [ ] Types match actual data passed to function
- [ ] Return types match actual returned data
- [ ] Optional params marked with `[param]` or `[param=default]`
- [ ] Nullable types marked with `|null` or `|undefined`
- [ ] Union types used for multiple accepted types
- [ ] No inline `Object`, use typedef or imported type
- [ ] Array element types specified: `[ElementType]`
- [ ] Async functions return `Promise<Type>`

## Common Patterns

**Optional parameters with defaults:**

```javascript
@param {number} [page=1] - Page number
@param {boolean} [include_counts=false] - Include counts
```

**Multiple type options:**

```javascript
@param {string|number} id - User ID
@returns {User|null} User object or null if not found
```

**Destructured parameters:**

Define a typedef for the parameter object and reference it. Never use an inline
`{Object}` (see CRITICAL REQUIREMENTS).

```javascript
/**
 * @typedef {Object} ProcessOptions
 * @property {string} memberId - Member UUID
 * @property {boolean} [includeCounts] - Include counts
 */

/**
 * @param {ProcessOptions} options
 */
function process({ memberId, includeCounts }) {}
```

**Callback/function types:**

```javascript
@param {(error: Error|null, result: any) => void} callback
```
