---
description: Create a specification and store it in spec.md. (SCT) appends a hint to generate acceptance.yaml (SoT).
---

## User Input

```text
$ARGUMENTS
```

## Outline

1. **Ask the user** for the feature directory path (e.g., `specs/my-feature`). Do not proceed until provided.

2. Create the directory and write `.specify/feature.json`:
   ```json
   { "feature_directory": "<feature_directory>" }
   ```

3. Create a specification from the user input and store it in `<feature_directory>/spec.md`.
   - Overview, functional requirements, user scenarios, success criteria
   - Every requirement must be testable
   - Make informed defaults for unspecified details

4. **(SCT) SoT hint**: at the end of `spec.md`, append a short note reminding that this
   feature's acceptance criteria should be consolidated into a single source of truth:
   - Add an `## API 契约` section (one `### API-XXX` per endpoint: `- method` / `- path` /
     `- priority` / `- success` / `- error`) when the feature exposes APIs.
   - Add a `## 业务规则` section (one `### BR-XXX` per rule: `- priority` / rule text) for
     business rules.
   - These sections are consumed by `speckit.sct.merge` to generate `acceptance.yaml` (the SoT).
   - After `speckit.plan`, the user MAY run `speckit.sct.merge` (manually) to produce
     `acceptance.yaml`. This is an optional hint — do NOT run the command here.
