---
description: Create a plan and store it in plan.md. (SCT) also enforces data-model.md + api-contracts.md outputs for SoT merge.
---

## User Input

```text
$ARGUMENTS
```

## Outline

1. Read `.specify/feature.json` to get the feature directory path.

2. **Load context**: `.specify/memory/constitution.md` and `<feature_directory>/spec.md`.

3. Create an implementation plan and store it in `<feature_directory>/plan.md`.
   - Technical context: tech stack, dependencies, project structure
   - Design decisions, architecture, file structure

4. **(SCT) Enforce SoT inputs** — the SCT consistency workflow needs more than plan.md to
   build the single source of truth. Produce both of the following alongside the plan:
   - `<feature_directory>/data-model.md` — entities, key fields, relationships, and the
     invariants/business rules they must satisfy (these become `rules[]` in `acceptance.yaml`).
   - `<feature_directory>/api-contracts.md` — every endpoint this feature exposes: method,
     path, request/response schema, success/error codes (these become `apis[]` in
     `acceptance.yaml`). Use the format the `## API 契约` section in spec.md follows.
   - If the feature has no APIs or no data model, write a one-line note stating so (don't omit
     the file silently — `speckit.sct.merge` auto-discovers these paths).

5. **(SCT) Optional SoT hint**: once the plan artifacts exist, the user MAY, at their
   discretion, run `speckit.sct.merge` to consolidate `spec.md` + `plan.md` +
   `data-model.md` + `api-contracts.md` into `<feature_directory>/acceptance.yaml`
   (the single source of truth). This is NOT run automatically — SCT is
   non-intrusive. Suggest it as a next step; do not invoke the command here.
   Use `--ai` only when the user wants the LLM to auto-extract additional
   acceptance scenarios.
