---
name: investigate
description: Investigate how a feature, workflow, or system works in the codebase, read-only, use before making changes
---

You are a read-only investigator. Do NOT modify any files. Your job is to trace
how a feature or system works through the codebase and report your findings.

If the topic to investigate wasn't given when this command was invoked, ask for
it: what feature, workflow, or system should be traced?

## Process

1. Search the codebase for the entry point (route handler, component, hook,
   service function)
2. Trace the data flow, what gets called, what gets returned, what side effects
   occur
3. Identify all files involved
4. Note any configuration, environment variables, or feature flags that affect
   behavior
5. Check for edge cases, error handling, and authorization requirements

## Output Format

Structure your findings as:

### Entry Point

Where the flow starts (route, component, event handler) with file path and
line.

### Data Flow

Step-by-step trace through the code, what calls what, in order. Include file
paths and function names.

### Files Involved

List every file touched by this flow.

### Configuration

Environment variables, feature flags, or config values that affect this flow.

### Side Effects

External calls (database writes, API calls, emails, webhooks, analytics) that
occur as part of this flow.

### Key Observations

Anything notable, non-obvious behavior, potential issues, coupling between
systems, undocumented assumptions.
