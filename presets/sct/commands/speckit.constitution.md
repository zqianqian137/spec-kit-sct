---
description: Create or update the project constitution. (SCT) adds the Spec-Code-Test consistency principle.
---

## User Input

```text
$ARGUMENTS
```

## Scope Guard

This command's own work is limited to creating or updating the project constitution and
propagating constitution-driven changes to dependent Spec Kit artifacts.

- Classify every part of the user input as constitution content or a separate non-governance
  intent. Feature implementation, code generation, refactoring, build, and deployment requests
  are examples of non-governance intents.
- You **MUST NOT** execute any non-governance intent. Defer each one to `Next Actions`.
- You **MUST NOT** create, modify, or delete application source files or other artifacts
  unrelated to the constitution workflow.
- If an instruction could be either constitution content or a non-governance intent, ask for
  clarification before making changes.
- After updating the constitution, list each deferred intent in a `Next Actions` section with an
  appropriate follow-up Spec Kit command, such as `__SPECKIT_COMMAND_SPECIFY__`, but do not
  invoke it.
- Omit `Next Actions` when there are no non-governance intents.

## Outline

1. Create or update the project constitution and store it in `.specify/memory/constitution.md`.
   - Project name, guiding principles, non-negotiable rules
   - Derive from user input and existing repo context (README, docs)

2. **(SCT) Add the Spec-Code-Test consistency principle** as a non-negotiable rule, e.g.:
   - *Single Source of Truth*: `acceptance.yaml` (produced by `speckit.sct.merge` from
     spec/plan/data-model/api-contracts) is the only contract for implementation and tests.
   - *Write-once generated tests*: tests are derived from the SoT via `speckit.sct.codegen` and
     must not be hand-edited.
   - *Three-way consistency*: every implementation must pass `speckit.sct.check`
     (spec ↔ code ↔ test) before it is considered done.
   - *Change impact gating*: code changes are reverse-traced by `speckit.sct.impact` (after
     implement) to scope regression to what actually changed.
