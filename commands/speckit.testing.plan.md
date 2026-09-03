---
description: "Testing plan: auto-generate the test plan (acceptance.yaml) from spec.md + plan artifacts (plan/data-model/api-contracts) + code diff; optional change-impact tiering (P0/P1/P2 + L1/L2/L3). Manual, non-intrusive"
---

# Testing Plan — Auto-generate the Test Plan

Generate `acceptance.yaml` — **the test plan**: the file that later drives test
derivation (`testing.cases`) and the gate (`testing.run`).

**It is auto-generated, and it runs after `speckit.plan`.** The plan is derived
from requirement *and design* artifacts, not invented by hand:

| Source | Kind | What it contributes |
|---|---|---|
| `spec.md` | requirement (backbone) | `features[]` + acceptance scenarios, business rules |
| `plan.md` | **plan artifact** | implementation approach, module boundaries, technical constraints |
| `data-model.md` | **plan artifact** | `rules[]` — entities, field constraints, validation rules |
| `api-contracts.md` | **plan artifact** | `apis[]` — contracts and declared error cases |
| code diff (optional) | change input | change-impact tiering: which scenarios are affected (P0/P1/P2) |

> The test plan is a **derived projection** of these artifacts, never a second
> source of truth. Requirement changes → update `spec.md` and re-run this.
> Test-expectation changes → edit `acceptance.yaml` directly.

## Step 0 — Preconditions

| Check | Requirement |
|---|---|
| Feature directory | `specs/{feature}/` with `spec.md` present |
| Plan artifacts | `plan.md` / `data-model.md` / `api-contracts.md` — **pass whatever exists**; more artifacts = a more complete plan |
| Spec reviewed | The spec should be stable — the plan records acceptance criteria, not drafts |
| Mode | `coverage_mode`: `full` (new module) or `incremental` (brownfield: this change's scope only) |
| Timing | `test_timing`: `post` (default, code-first) or `pre` (TDD-style) |

Also accept `$ARGUMENTS` overrides (e.g. `--coverage-mode incremental`).

## Step 1 — Run the generator

```bash
python $SCT_EXT_HOME/scripts/spec-merge.py \
  --spec specs/{feature}/spec.md \
  --plan specs/{feature}/plan.md \
  --api-contracts specs/{feature}/api-contracts.md \
  --data-model specs/{feature}/data-model.md \
  --out specs/{feature}/acceptance.yaml
# --feature-id F001      override the inferred feature id
# --ai                   optional LLM enrichment of edge_cases
#                        (needs an LLM endpoint; SKIP on air-gapped networks)
```

Output: `specs/{feature}/acceptance.yaml`
(schema: `$SCT_EXT_HOME/templates/acceptance-template.yaml`).

> ⚠️ **Re-run safety.** If `acceptance.yaml` already exists and was **hand-enriched**
> (`target` / `test_cases` / `checks` / `example`), do not overwrite blindly.
> Generate to a temp path, diff, then re-apply the manual fields:
>
> ```bash
> python $SCT_EXT_HOME/scripts/spec-merge.py --spec specs/{feature}/spec.md --out /tmp/acceptance.new.yaml
> diff specs/{feature}/acceptance.yaml /tmp/acceptance.new.yaml
> ```

## Step 2 — Optional: change-impact tiering

When the code already changed (typical `post` flow), add impact analysis to the plan —
this reverse-traces the diff to affected scenarios and sets the tier that controls
downstream effort:

```bash
python $SCT_EXT_HOME/scripts/change-impact.py \
  --spec specs/{feature}/acceptance.yaml \
  --out specs/{feature}/change-impact.md
# --base main --head HEAD     diff range
```

Outputs `change-impact.md` with **P0/P1/P2** priorities and an **L1/L2/L3** tier
(小改 / 中改 / 大改) that decides how much downstream work `testing.cases` and
`testing.run` do.

## Step 3 — Enrich and self-check (the step that decides plan quality)

The generator transcribes what the artifacts **state**. It never invents test data
and never reads code. A human (or an AI anchored on the requirement) must fill the
fields that make tests derivable:

| Field | Where | Why it matters | If missing |
|---|---|---|---|
| `target` | `rules[]` | Points a rule at a class/method | No unit test for that rule |
| `test_cases[].inputs` | `rules[]` | Concrete input values | No unit test |
| `test_cases[].expect` | `rules[]` | **The assertion** (`returns` / `throws`) | No unit test |
| `test_cases[].given` | `rules[]` | Mock stubs | Test fails honestly → `MOCK_NOT_STUBBED` |
| `checks[]` | `rules[]` | Offline static anchors | Degrades to loose matching |
| `example` | `apis[].request.body[]` | Real sample values | Heuristic values may be rejected |

**Report these counts before declaring done:**

- `features[].acceptance_scenarios[]` — each with a complete `given` / `when` / `then`
- `apis[]` — each with a contract and its declared error cases
- `rules[]` — how many have `target` + `test_cases` (these become executable unit
  tests) vs how many only have `checks`

A plan with 12 rules and 0 `test_cases` yields almost no executable tests — say so
explicitly instead of implying full coverage.

## Step 4 — Report and next steps

Summarize: which artifacts were consumed, how many scenarios/APIs/rules were
registered, the completeness counts, and what still needs human input.

Then state the rule that governs everything downstream:

> **Expectations live in the test plan, never in the tests.** Assertions are never
> reverse-engineered from code. Tests are **write-once**: change the plan and
> regenerate (`testing.cases`) — never hand-edit a generated test.

Next: `testing.cases` (derive tests) → `testing.run` (execute + gate + report).

This command is **manual**: no lifecycle hooks, nothing fires automatically.
