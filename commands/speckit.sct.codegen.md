---
description: "SCT codegen: generate write-once tests from acceptance.yaml. Timing controlled by SoT _meta.test_timing (pre = test-first, post = deferred to protect implementation resources)"
---

# SCT Test Generation (acceptance-codegen)

Generate tests from the acceptance.yaml single source of truth (SoT).
Tests are **write-once**: manual edits are forbidden; changes go through the SoT.

## Step 0 — Gates (tier → timing)

**Gate 1 — L1 fast path**: read `变更级别` from `specs/{feature}/change-impact.md`.
If **L1** (or the change meets L1 criteria), output this notice and END —
L1 runs only the existing-test regression, no new tests, no tokens:

> ⏭️ L1 小改：跳过测试生成。存量回归即可（由 sct.check 的 L1 快通道执行）。

**Gate 2 — timing mode**: read `_meta.test_timing` from
`specs/{feature}/acceptance.yaml` (**default `post`** when absent — the SCT
canonical ordering is Spec→Code→Test). Also accept `$ARGUMENTS` override.

- **`post` (code-first, SCT canonical, default)**: **STOP HERE. Do not generate
  tests now.** Implementation owns the AI resources.

  Output exactly this notice and end the command (no test files, no tokens spent):

  > ⏸️ test_timing=post：代码先行（SCT 正统时序 Spec→Code→Test）。实现期间不
  > 生成测试——代码编写独占资源。测试生成与执行推迟到实现完成后：由
  > after_implement 的 `sct.check` 钩子补生成并校验（此时代码已定稿、CodeGraph
  > 最新，示例值/必填判定/FIELD_DRIFT 基于真实实现，一致性比对质量最高）。

- **`pre` (test-first, optional TDD-style variant)**: continue to Step 1 below.
  The forward guarantee chain is equivalent in both timings — the guarantee
  comes from derivation (tests derive from SoT, implementation codes against
  the SoT contract in change-impact.md), not from tests being written early.
  Choose pre only when the team explicitly wants a failing-suite guardrail
  before implementation. When invoked from `sct.impact` Step 4 (same session),
  use `--only` to scope generation to the P0/P1 APIs from change-impact.md.

Rationale: SCT is a forward guarantee chain — spec drives code (via the
implementation contract), spec × code derive tests, check is the final
confirmation gate. `post` matches the methodology's own ordering
(Spec→Code→Test) and gives implementation exclusive resources; `pre` trades
that for a red-first guardrail. In `post` mode the pipeline is: `impact
(lightweight, emits implementation contract) → implement (codes against the
contract, exclusive resources) → codegen + check (after code is final)`.

Note: the generator short-circuits on its own hash cache — if neither
`acceptance.yaml` nor `codegraph.json` changed since the last run, it exits in
seconds with 0 regenerated files (override with `--force`).

## Step 1 — Inputs

| Input | Path | Required |
|---|---|---|
| SoT | `specs/{feature}/acceptance.yaml` | yes |
| Change impact scope | `specs/{feature}/change-impact.md` | recommended (from `sct.impact`) |
| CodeGraph export | `codegraph.json` (schema: `extensions/sct/templates/codegraph-template.json`) | optional, highly recommended |

When `change-impact.md` exists, generate tests only for the P0/P1 scope it
lists (brownfield/incremental discipline: test what changed).

**测试独立性（CodeGraph 的角色边界）**：断言期望值的唯一来源是 SoT。
CodeGraph 只允许辅助**构造请求**（字段类型/格式/枚举值/示例值、必填并集）、
提供 FIELD_DRIFT 比对和派生异常用例（cg_error：验证代码声明的约束被代码
自己执行——技术约束自洽检查，不替代 SoT 业务断言）。**绝不从代码反推
断言期望**——测试跟着 code 走 = code 的错误被测试合法化（自己出题自己
改卷）。post 时序（代码先行）下尤其如此：代码已存在不构成期望基准。

## Step 2 — Run the generator

```bash
python $SCT_EXT_HOME/scripts/acceptance-codegen.py \
  --spec specs/{feature}/acceptance.yaml \
  --out tests/generated/ \
  --codegraph codegraph.json   # optional; enables real-code examples,
                               # required-annotation merge and FIELD_DRIFT
```

Outputs (all under `tests/generated/`):
- `test_api_*.py` / `test_rules.py` / `test_scenarios.py` — write-once tests,
  each case carries intent annotation: `[意图]` + truth source + Given/When/Then
- `COVERAGE_REPORT.md` — spec→test derivation map (+ FIELD_DRIFT section when
  CodeGraph is provided)
- `_codegen_meta.json` — machine-readable metadata (API annotations +
  FIELD_DRIFT); `sct.check` auto-discovers it and merges into the final test report

## Step 3 — Report

Summarize for the user: number of APIs/rules/scenarios covered, files generated,
FIELD_DRIFT count (if any), and the write-once rule (edits forbidden; change the
SoT instead, then regenerate).

**示例值失败的调整闭环**（无 CodeGraph 时启发式值可能过不了后端校验）：
1. 看失败类型：构造失败（请求被 400 校验拒绝，未到业务逻辑）≠ 断言失败
   （响应到达但与 SoT 期望不符）
2. 构造失败 → 给 SoT 字段补 `example` 标注（`request.body[].example`）
3. 重跑本命令（SoT hash 已变，自动重新生成，无需 --force）→ 重跑 pytest
4. 全程不碰生成文件（write-once）；example 是构造侧修正，不是迁就 code
   的行为——若想改的是 Then 期望值，那是断言侧问题，走 sct.check 的
   举证责任流程（默认 SoT 是真相 → 修 code）

Next steps: implementation (pre mode) or `sct.check` validation (post mode).
