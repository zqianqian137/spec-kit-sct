---
description: Execute the implementation plan by processing all tasks in tasks.md. (SCT) same as core; after implementing, append an OPTIONAL reminder that the user MAY manually run speckit.sct.* commands. It does NOT auto-generate tests or run any SCT command.
---

## User Input

```text
$ARGUMENTS
```

## Outline

1. Read `.specify/feature.json` to get the feature directory path.

2. **Load context**: `.specify/memory/constitution.md` and `<feature_directory>/spec.md` and
   `<feature_directory>/plan.md` and `<feature_directory>/tasks.md`.

3. **Execute tasks** in order:
   - Complete each task before moving to the next
   - Mark completed tasks by changing `- [ ]` to `- [x]` in `<feature_directory>/tasks.md`
   - Halt on failure and report the issue

4. **Validate**: verify all tasks are completed and the implementation matches the spec.

5. **(SCT) Optional reminder — NOT executed automatically**: SCT is non-intrusive.
   After you finish implementing, the user MAY, at their discretion, run the SCT
   commands manually to apply the Spec-Code-Test methodology:
   - `speckit.sct.merge` — consolidate `spec.md` + `plan.md` + `data-model.md` +
     `api-contracts.md` into `<feature_directory>/acceptance.yaml` (the SoT).
   - `speckit.sct.impact` — reverse-trace the code just written to affected spec
     scenarios (P0/P1/P2) and decide an L1/L2/L3 tier.
   - `speckit.sct.codegen` — derive write-once tests (api / rule / scenario) from the SoT.
   - `speckit.sct.check` — three-way consistency check (spec ↔ code ↔ test).
   - `speckit.sct.e2e` — bridge impact + SoT into Playwright regression scripts (L3).
   Do NOT auto-run any of these; the user decides whether and when to execute them.
