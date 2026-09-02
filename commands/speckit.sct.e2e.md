---
description: "SCT e2e: bridge change-impact.md (P0/P1) + acceptance.yaml e2e segments into Playwright regression scripts, a human test-case doc and an intent export. L3 only"
---

# SCT E2E Bridge — Change Impact → Playwright Regression

Turn the P0/P1 scenarios picked by `sct.impact` into Playwright specs, a
human-readable test-case document, and an intent-driven export.

## Step 0 — Gate: L3 only

Read `变更级别` from `specs/{feature}/change-impact.md`.

- **L1 / L2** (or no change-impact.md with an L3 verdict) → output this notice and END:

  > ⏭️ 当前为 L1/L2 变更：e2e 回归仅 L3 大改执行。本轮以单元/接口层（`sct.check`）门禁为准。

- **L3** → continue.

If `change-impact.md` does not exist at all, tell the user to run `sct.impact` first
(the bridge needs the P0/P1 scope) — or, when the user explicitly wants a full export,
the script falls back to **all scenarios marked P0/P1 in the SoT**.

## Step 1 — Inputs

| Input | Path | Required |
|---|---|---|
| SoT (with `e2e:` segments) | `specs/{feature}/acceptance.yaml` | yes |
| Change impact scope | `specs/{feature}/change-impact.md` | recommended |
| Test data | `e2e/fixtures/<file>` (relative to the generated specs' parent) | for `upload_file` actions |

Only scenarios that carry an **`e2e:` block** are bridged. A scenario without one is
simply not automatable by this bridge — it is not an error, but it must be reported
(see Step 3).

`e2e` block schema (W1 scope):

```yaml
acceptance_scenarios:
  - id: F001-1
    e2e:
      priority: P0                          # P0 / P1 / P2
      pre_steps: [login, navigate:/batch/import]
      action:
        type: upload_file                   # W1 only: upload_file
        file_ref: fixtures/tasks.csv        # → resolved to e2e/fixtures/tasks.csv
        method: file_input                  # file_input (default) | drag_drop
      assertion:
        type: ui_message                    # W1 only: ui_message
        text: "导入成功"
        timeout: 5000
```

## Step 2 — Check e2e coverage before generating

Before running the bridge, report how many of the **in-scope (P0/P1)** scenarios have an
`e2e:` block and how many do not. For the ones without it, list the scenario ids so a
human can either add the block to the SoT or execute them manually — an unautomatable
scenario is a coverage gap, not a silent skip.

## Step 3 — Run the bridge

```bash
python $SCT_EXT_HOME/scripts/change-impact-e2e-bridge.py \
  --spec specs/{feature}/acceptance.yaml \
  --impact specs/{feature}/change-impact.md \
  --out e2e/auto_generated/
# --dry-run   只打印不写文件（推荐先跑一次看内容）
```

Outputs (all under `e2e/auto_generated/`):

| Artifact | Audience |
|---|---|
| `<scenario-id>.spec.js` | Playwright — one file per scenario, carries priority + source-spec header |
| `E2E_TESTCASES.md` | 测试人员 — Given/When/Then 步骤 + 执行结果勾选 + 汇总回填表 |
| `_intent_tests.json` | UI 自动化测试平台 — intent + G/W/T + 关联脚本名（模板见 `templates/intent-test-template.json`） |
| `_summary.json` | 机器可读摘要（生成/跳过数量、文件清单） |

Fixture path convention: generated specs live in `e2e/auto_generated/`, so they resolve
fixtures as `../fixtures/<file_ref>` — keep test data in `e2e/fixtures/`.

## Step 3.1 — Two consumer paths (SCT e2e is a *generator*, not an executor)

The bridge only **writes** artifacts; it never runs a browser. Who consumes them depends
on the environment — pick the path your setup supports:

| Path | Consumer | Precondition | How it runs |
|---|---|---|---|
| **A — Playwright 直接回归** | `*.spec.js` + `E2E_TESTCASES.md` | 该环境已装 Playwright 与浏览器（`npx playwright install`） | `npx playwright test e2e/auto_generated/`，人工对照 `E2E_TESTCASES.md` 勾选结果 |
| **B — AI 测试平台** | `_intent_tests.json` | 内网已部署 AI 测试平台（AI 脚本生成/调度） | 平台导入 intent 文件生成并执行用例；**本机无需装 Playwright** |

- **内网没装 Playwright ≠ 不能走 e2e 桥**：路径 B 依然成立——本机只负责生成，
  Playwright 依赖完全落在 AI 测试平台侧。
- 同一个 `_intent_tests.json` 是路径 B 的**唯一数据契约**：G/W/T 意图 + 关联脚本名
  （模板见 `templates/intent-test-template.json`），平台据此重建可执行用例。
- 路径 A 的产物（`.spec.js`）在路径 B 下是**参考物而非执行物**——平台以自己的
  引擎跑，不用本地 spec 文件。

## Step 4 — Human review, then run

**Generated ≠ runnable.** Review the specs before trusting them: selectors
(`input[type="file"]`, `.dropzone`) and the asserted UI text come from the SoT, and the
W1 bridge only supports `upload_file` actions and `ui_message` assertions — anything else
is emitted as a `// TODO:` line for a human to complete.

```bash
npx playwright test e2e/auto_generated/
```

Release standard (from `E2E_TESTCASES.md`): **P0 全部通过**；P1 失败需记录缺陷并限期修复。

**Boundary that must not be crossed**: the asserted text and the scenario's
Given/When/Then come from the **SoT**. If a generated spec fails, escalate to a human —
UI behavior is wrong → fix the UI; SoT is wrong → fix the SoT and regenerate. Never
silently edit the generated spec green.

## Step 5 — Report

Summarize: tier, in-scope scenario count, generated vs skipped (with ids and reasons),
fixtures referenced, and the review/run instructions above.

This command is **manual** and runs only for L3: SCT registers no lifecycle hooks, so
nothing fires automatically.
