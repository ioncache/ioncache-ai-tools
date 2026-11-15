# Category inventory and packet preparation

This is the caller's catalog, not a worker checklist. Each enabled general
category in [categories.json](categories.json) gets a fresh worker across the
whole requested scope, plus a separate adjudicator. A category with an explicit
language prerequisite runs only after source evidence establishes that language
in scope. No inline or small-check exception. Neither directory, predicted
value nor desired worker count determines the roster. Dispatched workers still
check their own file-level applicability and record a reason if nothing applies.

## Technical applicability

Before dispatch, record objective source-language evidence under PACKETS.md's
`language_inventory`. JSDoc has a JavaScript prerequisite: do not launch it for
TypeScript-only or other JavaScript-free scope. Embedded JavaScript counts;
another language or a repository-wide label does not make every path JavaScript.
Keep the full candidate inventory in each dispatched packet.

Only complete, evidenced classification can establish that a language is absent.
Missing evidence defers that language-specific worker and prevents a complete
review, but other categories and authorized work continue. Extend the same
phase's inventory with newly established facts before dispatching a newly
applicable category; do not replay completed work or reset replacement spending.

General purposes adapt to the actual stack even without a dedicated guide.
Identify native conventions and use verified documentation for consequential
unknowns. Lack of a framework-specific resource is not non-applicability, an
exclusion, or permission to impose another stack's syntax and APIs.

## Standards inventory

Establish the objective, scope and snapshot. Read applicable repository
instructions, including `.github/instructions/` and referenced/directory-scoped
sources, without assuming one host directory is the entire inventory.
Honor `applyTo` and explicit project exceptions. Conversational and workflow
rules are execution constraints, not extra discovery categories.

Map complete same-purpose sections to one category, preserving source content,
identity, applicability and exceptions. Project conventions override shipped
defaults within their declared scope, below the actual host/user hierarchy.
Do not invent precedence between equal-authority conflicting project sources.
The assigned specialist investigates such conflicts or records missing coverage.
Reviewed instruction changes cannot silently weaken approved requirements.

A genuinely additional project purpose gets a stable `project:<slug>` descriptor
in the request, with its title, complete instructions, source identity,
applicability and exceptions. It is required by default unless it has an explicit,
evidenced language prerequisite. The effective registry
combines these descriptors with shipped categories; it is not another persistent
configuration catalog. Do not add unregistered keys to plugin settings.

User-supplied exclusions retain their original instruction and provenance.
Do not invent or suggest exclusions
or ask a selection question. User-configured shipped `review-*` switches are
independent of `skill:*` writing-skill activation. Technical language absence is
a separate frozen fact, not an exclusion. Other applicability judgments remain
the assigned worker's responsibility, never a predicted-usefulness shortcut.

## Single-purpose instruction sets

Use [PACKETS.md](PACKETS.md) and the shared preparation/check helper.
Each packet contains one canonical category standard, approved same-purpose
project requirements, [PROTOCOL.md](PROTOCOL.md), and only its applicable
assessment modules. Never pass the full inventory, generic composers, another
category checklist, sibling findings or implementation conversation to discovery.

Caller language inventory and precedence preparation are not code-review passes.
Semantic applicability and defect investigation belong to the category specialist.
Correctness contains functional/error/state/completion criteria, not security,
performance, design, documentation and project-standard sweeps.
Integration independently traces actual producer/consumer boundaries across
the scope; it does not depend on a directory-owner map.

Freeze source contents and packet identities in the phase plan. Missing
instructions or evidence leave coverage incomplete, not an exemption.
Known extra category/generic review guidance invalidates that assignment;
replace it under permitted bounds with corrected instructions, or report the
limitation and continue other authorized work. Unknown hidden context is
disclosed separately, never described as verified pristine context.

## Actionability

Compatibility reference for assessment consumers:
read [ASSESSMENT.md](ASSESSMENT.md) and its three policy modules.
Discovery workers receive only the policies named in their category entry.
Preparation must not omit relevant materiality or test-gap criteria.

## Human report

Use [ASSESSMENT.md#human-report](ASSESSMENT.md#human-report).
