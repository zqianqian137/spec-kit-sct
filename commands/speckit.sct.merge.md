---
description: "SCT merge: build acceptance.yaml (the single source of truth) from spec / api-contracts / data-model / plan. Manual, non-intrusive; optional --ai edge-case enrichment"
---

# SCT Merge — Build the Single Source of Truth (acceptance.yaml)

Merge the spec artifacts into `acceptance.yaml` — the **SoT**: the only file that
later drives test derivation (`sct.codegen`), the three-way check (`sct.check`) and
change-impact tracing (`sct.impact`).

Position in the chain: this is **step 1 of the forward guarantee chain**
(Spec → Code → Test). Everything downstream reads this file and nothing else.

## Step 0 — Preconditions

| Check | Requirement |
|---|---|
| Feature directory | `specs/{feature}/` with `spec.md` present |
| Spec reviewed | The spec must be **reviewed and stable** — the SoT records acceptance criteria, not drafts |
| Mode decision | `coverage_mode`: `full` (new module / refactor) or `incremental` (brownfield: only this change's scope) |
| Timing decision | `test_timing`: `post` (default, code-first) or `pre` (TDD-style variant) |

Also accept `$ARGUMENTS` overrides (e.g. `--coverage-mode incremental`).

## Step 1 — Collect inputs

| Input | Required | Notes |
|---|---|---|
| `specs/{feature}/spec.md` | **yes** | Source of `features[]` / acceptance scenarios (parses `## 业务规则`, `## API 契约` sections) |
| `specs/{feature}/api-contracts.md` | recommended | Source of `apis[]` — without it, API tests have no contract to derive from |
| `specs/{feature}/data-model.md` | optional | Source of `rules[]` |
| `specs/{feature}/plan.md` | optional | Additional API/rule detail |

> ⚠️ **Re-merge safety.** If `specs/{feature}/acceptance.yaml` already exists and has been
> **hand-enriched** (`target` / `test_cases` / `given` / `checks` / `example` — see Step 3),
> do **not** overwrite it blindly. Write to a temp path first, diff the two, and re-apply
> the manual fields:

```bash
python $SCT_EXT_HOME/scripts/spec-merge.py --spec specs/{feature}/spec.md --out /tmp/acceptance.new.yaml
diff specs/{feature}/acceptance.yaml /tmp/acceptance.new.yaml
```

## Step 2 — Run the merge

```bash
python $SCT_EXT_HOME/scripts/spec-merge.py \
  --spec specs/{feature}/spec.md \
  --api-contracts specs/{feature}/api-contracts.md \
  --data-model specs/{feature}/data-model.md \
  --out specs/{feature}/acceptance.yaml
# --plan specs/{feature}/plan.md     optional extra source
# --feature-id F001                  override the inferred feature id
# --ai                               optional: LLM enrichment of edge_cases
#                                    (needs an LLM endpoint; SKIP on air-gapped networks)
```

Output: `specs/{feature}/acceptance.yaml` (schema: see
`$SCT_EXT_HOME/templates/acceptance-template.yaml`).

## Step 3 — Enrich and self-check (the step that decides whether the chain works)

The script transcribes what the spec **states**. It never invents test data, it never
reads code. So a human (or an AI anchored on the requirement) must fill in the fields
that make tests derivable:

| Field | Where | Why it matters | If missing |
|---|---|---|---|
| `target` | `rules[]` | Points the rule at a class/method (Java unit tests) | No JUnit test is generated for that rule |
| `test_cases[].inputs` | `rules[]` | Concrete input values | No unit test |
| `test_cases[].expect` | `rules[]` | **The assertion** (`returns` / `throws`) | No unit test |
| `test_cases[].given` | `rules[]` | Mock stubs; without them a mock returns 0/null | Test fails honestly → `MOCK_NOT_STUBBED` |
| `checks[]` | `rules[]` | Offline static anchors (`annotation` / `method` / `exception` / `constant` / `text`) | Rule test degrades to loose matching and may fail asking for anchors |
| `example` | `apis[].request.body[]` | Real sample values | Heuristic values may be rejected by backend validation (construction failure ≠ assertion failure) |

**SoT completeness self-check — report these counts before declaring done:**

- `features[].acceptance_scenarios[]` — each has a complete `given` / `when` / `then`
- `apis[]` — each has `method`, `path`, `request.body` (`required` flags), `response.success`, `response.errors[]`
- `rules[]` — each has `text` + `priority`; **count how many also have `target` + `test_cases`** (those are the ones that will become executable Java tests) and how many have `checks` (those are the ones with precise offline assertions)

Report the numbers so the human knows exactly how much of the SoT can actually be
exercised downstream. A SoT with 12 rules and 0 `test_cases` produces almost no
executable tests — say so explicitly instead of implying full coverage.

## Step 4 — Report and next steps

Summarize: features / scenarios / APIs / rules merged, which optional sources were found,
the completeness counts from Step 3, and which fields still need human input.

Then state the rule that governs everything after this:

> **The SoT is the only truth.** Assertions are never reverse-engineered from code. Tests
> are **write-once**: change the SoT and regenerate (`sct.codegen`) — never hand-edit a
> generated test.

Next steps:
- `test_timing: post` (default) → proceed to implementation (`speckit.implement`), then
  `sct.impact` → `sct.codegen` → `sct.check` after the code is final.
- `test_timing: pre` → `speckit.implement` may be preceded by `sct.codegen` to land a
  red-first guardrail.

This command is **manual**: SCT registers no lifecycle hooks, so nothing fires
automatically.
