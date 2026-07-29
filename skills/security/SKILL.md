---
name: security
description: Use when writing or reviewing API endpoints, database access, auth, or user input handling, for validation, sanitization, and secret-handling standards. Examples assume Fastify/MongoDB but the principles are general.
---

# Security Guidelines

## CRITICAL PRINCIPLES

1. **Validate at the edge**, JSON Schema validation on all API endpoints
2. **Sanitize all user input**, use `sanitize-html` for any user-generated
   content
3. **Verify webhook signatures**, always verify Stripe, Slack, Terra webhooks
4. **Use secure ObjectId conversion**, always use
   `ObjectId.createFromHexString()` with try/catch
5. **Fail securely**, never expose internal errors to clients, log details,
   return generic messages
6. **Least privilege**, use RBAC permissions to restrict protected routes
7. **Secrets in env only**, all secrets MUST be validated at startup

## Example Patterns (Fastify + JSON Schema + MongoDB)

### API Validation

```javascript
// Good: Fastify route with schema validation
fastify.post('/api/users', {
  schema: {
    body: {
      type: 'object',
      required: ['email', 'password'],
      properties: {
        email: { type: 'string', format: 'email' },
        password: { type: 'string', minLength: 8 }
      }
    }
  },
  handler: async (request, reply) => {
    // Data is already validated
    const { email, password } = request.body
  }
})

// Bad: No validation
fastify.post('/api/users', async (request, reply) => {
  const { email, password } = request.body // Unsafe!
})
```

### Security Headers

**Use @fastify/helmet for security headers:**

```javascript
import helmet from '@fastify/helmet'
// Fastify with @fastify/helmet
fastify.register(helmet, {
  contentSecurityPolicy: {
    directives: {
      defaultSrc: ["'self'"],
      connectSrc: ["'self'", 'https://api.example.com']
    }
  }
})
```

### Safe MongoDB ObjectId Conversion

**Always wrap ObjectId conversion in try/catch:**

```javascript
// Good: Safe ObjectId conversion
try {
  const objectId = ObjectId.createFromHexString(id)
  const doc = await mongo.collection('files').findOne({ _id: objectId })
} catch (err) {
  return reply.code(400).send({ error: 'Invalid ID format' })
}

// Bad: Unsafe conversion (can crash server)
const objectId = ObjectId.createFromHexString(untrustedId)
```

### Webhook Signature Verification

**Always verify webhook signatures for Stripe, Slack, Terra:**

```javascript
import config from '../../config.js'

// Good: Verify Stripe webhook signature
function verifyWebhook(req, secret, stripe, fastify) {
  if (!req.rawBody) {
    throw new fastify.httpErrors.badRequest('No body supplied')
  }
  try {
    const signature = req.headers['stripe-signature']
    return stripe.webhooks.constructEvent(req.rawBody, signature, secret)
  } catch (err) {
    req.log.error('Webhook signature verification failed', err.message)
    throw new fastify.httpErrors.unauthorized('Invalid signature')
  }
}

// Use in route
fastify.post('/stripe/webhook', async (req, reply) => {
  const event = fastify.stripe.verifyWebhook(
    req,
    config.STRIPE_EVENTS_SIGNING_SECRET,
    fastify.stripe.api,
    fastify
  )
  // Process verified event
})
```

## Authentication & Authorization

**Use JWT validation and role-based access control:**

```javascript
// Good: Protected route restricted via RBAC permissions
fastify.post('/admin/users', {
  config: {
    permissions: {
      any: [],
      all: [PERMISSIONS.member.create.all]
    }
  },
  handler: async (req, reply) => {
    // Only authorized users can access this
  }
})

// Good: Public endpoint (explicitly disable auth)
fastify.get('/public/data', {
  config: { authorization: false },
  handler: async (req, reply) => {
    // No auth required
  }
})

// JWT is automatically verified on all routes unless authorization: false
// Token can be in a cookie or Authorization header
```

## Data Protection

### Rate Limiting

```javascript
import rateLimit from '@fastify/rate-limit'

// Fastify with @fastify/rate-limit
fastify.register(rateLimit, {
  max: 100,
  timeWindow: '15 minutes'
})
```

### Input Sanitization

**Sanitize all user-generated content with `sanitize-html`:**

```javascript
import sanitizeHtml from 'sanitize-html'

// Good: Recursive sanitization for nested objects
function sanitizePropertiesObject(obj) {
  const output = {}
  const sanitizeOptions = {
    allowedTags: [],
    allowedAttributes: {}
  }

  for (const [key, value] of Object.entries(obj)) {
    if (typeof value === 'string') {
      output[key] = sanitizeHtml(value, sanitizeOptions)
    } else if (typeof value === 'object' && value !== null) {
      output[key] = sanitizePropertiesObject(value)
    } else {
      output[key] = value
    }
  }
  return output
}

const sanitized = sanitizePropertiesObject(userInput)

// Good: General sanitization hook (best practice)
fastify.addHook('preHandler', (request, reply, done) => {
  if (request.body) {
    request.body = sanitizeHtml(request.body)
  }
  done()
})
```

### Environment Variables & Secrets

**All secrets MUST be defined in an env schema and validated at startup:**

```javascript
import config from '../../config.js'

// Good: Required secrets validated at startup
const env = {
  required: ['JWT_SIGNING_KEY', 'STRIPE_API_SECRET'],
  properties: {
    JWT_SIGNING_KEY: { type: 'string', minLength: 32 },
    STRIPE_API_SECRET: { type: 'string', pattern: '^sk_' }
  }
}

// Access via config (validated at startup)
const secret = config.JWT_SIGNING_KEY
```

## Error Handling

**Never expose internal errors to clients:**

```javascript
// Good: Log details, return generic message
try {
  await riskyOperation()
} catch (err) {
  req.log.error('Operation failed', { error: err, context: req.params })
  return reply.code(500).send({ error: 'Internal server error' })
}

// Bad: Exposes stack trace and internal details
try {
  await riskyOperation()
} catch (err) {
  return reply.code(500).send({ error: err.message, stack: err.stack })
}
```

## React Security

### XSS Prevention

**Never use `dangerouslySetInnerHTML` with user content:**

```javascript
// Good: React auto-escapes
function UserProfile({ user }) {
  return <div>{user.bio}</div>
}

// Bad: XSS vulnerability
function UserProfile({ user }) {
  return <div dangerouslySetInnerHTML={{ __html: user.bio }} />
}
```

### Error Boundaries

```javascript
// Good: Error boundary for graceful failure
class ErrorBoundary extends React.Component {
  state = { hasError: false }

  static getDerivedStateFromError(error) {
    return { hasError: true }
  }

  componentDidCatch(error, errorInfo) {
    // Log error to monitoring service
    logErrorToService(error, errorInfo)
  }

  render() {
    if (this.state.hasError) {
      return <h1>Something went wrong.</h1>
    }
    return this.props.children
  }
}
```

## Checklist

- [ ] Input validation at API endpoints
- [ ] Proper authentication middleware
- [ ] Rate limiting implemented
- [ ] Security headers configured
- [ ] Error handling without information leakage
- [ ] Query injection prevention (validate query parameters, use safe ObjectId
      conversion)
- [ ] XSS prevention
- [ ] CSRF protection
- [ ] Proper logging (no sensitive data)
- [ ] Webhook signatures verified
- [ ] ObjectId conversion wrapped in try/catch
- [ ] User input sanitized with sanitize-html
- [ ] All secrets validated at startup
- [ ] Protected routes use RBAC permissions
- [ ] No dangerouslySetInnerHTML with user content
- [ ] Error boundaries implemented in React
