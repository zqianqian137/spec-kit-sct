---
description: "SCT impact: lightweight change impact analysis (call chain + spec) after implementation. Reverse-traces the just-written code to affected spec scenarios; outputs change-impact.md with P0/P1/P2"
---

# SCT Change Impact Analysis (call chain × spec)

Reverse-trace code changes to affected spec scenarios. This command is
**lightweight by design**: it is run **manually after implementation** (the user
invokes it once the code is written), typically right before `sct.check`. It
reverse-traces the code that was just written. It must not consume significant
AI resources. It is also the **tier gate for the whole SCT pipeline** — the tier
decided here controls how many downstream agent turns are spent.

## Step 0 — 变更分级（SOP 时长控制，先分级再决定跑多少）

Classify the change FIRST; machine-checkable criteria, round up when in doubt:

| Tier | Criteria (any one) | SCT pipeline from here |
|---|---|---|
| **L1 小改** | ≤ 2 files touched AND no Controller/DTO/API-contract change AND `acceptance.yaml` unchanged | impact only → 存量回归。codegen / check 报告 / e2e **全部跳过** |
| **L2 中改** | API contract or rule change, ≤ 5 APIs affected | impact + codegen（定向）+ check（完整报告） |
| **L3 大改** | New feature / multi-module / DB migration / > 5 APIs | Full SOP + e2e |

Write the tier into change-impact.md header (`**变更级别**: L1|L2|L3`).

**If L1**: write a minimal change-impact.md (tier + one-line rationale +
"存量回归即可"), announce "L1 fast path — 后续 SCT 步骤全部跳过（由用户决定是否跑 codegen/check）",
and **END the command here**. Do NOT update the SoT, do NOT generate tests,
do NOT produce reports.

## Step 1 — Collect the change surface

```bash
git diff --name-only $BASE...HEAD          # changed files ($BASE default: main)
```

For each changed backend file, identify the call chain it belongs to
(controller → service → mapper). Use ripgrep to find callers/callees; static
analysis only — do not start the application.

**Optional — codebase-memory-mcp enrichment**: if the `codebase-memory-mcp`
connector is connected, prefer it over manual ripgrep for call-chain and
DTO-field resolution. Query it for (a) the callers/callees of each changed
symbol and (b) the set of endpoints/rules transitively touched. This yields a
more accurate change surface than filename-only diffing. Treat it as a
best-effort enhancement — fall back to ripgrep when the connector is
unavailable or returns nothing.

## Step 2 — Cross-reference the SoT

Load `specs/{feature}/acceptance.yaml` and match each touched call chain to:

- `apis[]` — endpoints whose controller/service is in the chain
- `rules[]` — business rules implemented by touched services
- `features[].acceptance_scenarios[]` — scenarios exercising those APIs/rules

When a CodeGraph export (`codegraph.json`) is available, use it for accurate
call-chain and DTO-field matching instead of manual ripgrep.

## Step 3 — Produce change-impact.md (含「实现需求」契约)

Write `specs/{feature}/change-impact.md` (template:
`extensions/sct/templates/change-impact-template.md`):

| Priority | Meaning |
|---|---|
| **P0** | Scenario directly implements the changed code — must be tested this round |
| **P1** | Scenario shares a service/rule with the change — should be regression-tested |
| **P2** | Peripheral impact — optional / next round |

**「实现需求」section（Spec→Code 前向驱动的关键产物）**: copy the in-scope
(P0/P1) SoT items verbatim into change-impact.md — for each API: method, path,
request fields (required/optional), success response, `errors[]`; for each
rule: the BR statement; for each scenario: Given/When/Then. This is the
**implementation contract**: the implement session must code against THIS
list, not free-hand from plan.md narrative. SoT 条目即验收口径——实现完成时
逐条可勾选。L1 跳过本节（无 SoT 变更）。

## Step 4 — Tier dispatch（分流调度，避免多余 agent 轮次）

Announce the tier and dispatch accordingly:

1. **L2/L3 + post timing** (default; SCT canonical Spec→Code→Test): skip
   codegen entirely — implementation gets exclusive resources; the user runs
   `sct.codegen` (then `sct.check`) manually once the code is final.
2. **L2/L3 + pre timing** (optional TDD-style variant, `_meta.test_timing: pre`):
   the user MAY run `sct.codegen` **right after this command** (same session) —
   scope generation to the P0/P1 APIs (`--only API-001,...` for targeted
   regeneration). This is still a manual user decision, not an auto-fired hook.
3. **check**: the changed-point review table (test-report.md section 5) is
   built from this file × execution results. L2/L3 only.
4. **e2e**: L3 only — P0/P1 scenarios become Playwright scripts and the
   human-facing `E2E_TESTCASES.md` / `_intent_tests.json` exports.

This command is invoked **manually** by the user after implementation (paired
with `sct.check` when both are used) to reverse-trace the just-written code and
re-verify that the diff is fully covered by the recorded impact scope (L2/L3
changes only). SCT registers no lifecycle hooks, so nothing fires automatically.
