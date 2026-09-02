---
description: "SCT verify: test-effectiveness gate (honest three-state PASS/BLOCK/UNPROVEN) — phantom task detection, real compile, real executed test count, optional mutation score. Answers 'do these tests actually catch bugs?'"
---

# SCT Verification Gate — Test Effectiveness (honest three-state)

`sct.check` answers "are there tests, and do they cover the spec?". This command
answers a different and harder question: **do these tests actually catch bugs?**

It closes the gap where a pipeline looks green because tests *exist and run*,
while the tests are hollow (never compiled, never executed, or too weak to fail).

## Step 0 — Gate: when to run

- **L1** → skip this command (存量回归即可).
- **L2 / L3** → run it after `sct.check`, before declaring the change done.

It is **manual** (SCT registers no lifecycle hooks) and is the last gate of the
SCT pipeline.

## Step 1 — Inputs

| Input | Flag | Required | Purpose |
|---|---|---|---|
| SoT | `--spec` | yes | 上下文与报告来源 |
| Source root | `--code` | yes | 编译门 + 幻影检测的代码语料 |
| Test root | `--tests` | yes | 幻影检测的第二语料 |
| tasks.md | `--tasks` | recommended | 幻影任务检测数据源 |
| surefire 报告目录 | `--surefire` | recommended | 真实执行测试数 |
| PITest 报告 | `--mutation` | optional | 变异得分 |

## Step 2 — Run

```bash
python $SCT_EXT_HOME/scripts/verification-gate.py \
  --spec specs/{feature}/acceptance.yaml \
  --code backend/src/main/java \
  --tests tests/generated/ \
  --tasks specs/{feature}/tasks.md \
  --surefire backend/target/surefire-reports \
  --report specs/{feature}/reports/verification.md

# 可选增强：变异测试强度（PITest）
python ... --mutation backend/target/pit-reports/mutations.xml --mutation-threshold 60

# mutmut 等无 XML 报告的工具：直接给分
python ... --mutation-score 72.5

# 内网无构建环境时
python ... --skip-compile
```

## Step 3 — Read the three states (do not let UNPROVEN pass as green)

| State | Meaning | Action |
|---|---|---|
| **PASS** | 编译通过 + 测试真实执行且全绿 + 无幻影（变异得分达标，如启用） | 放行 |
| **BLOCK** | 发现幻影 / 编译失败 / 实际执行测试数为 0 / 有失败 / 变异得分低于阈值 | ❌ 阻断，修复后再走 |
| **UNPROVEN** | **无法验证**（缺 mvn/gradle、缺 surefire 报告、缺 tasks.md） | ⚠️ 不等于通过——补齐环境重跑，或人工确认风险 |

退出码：`0=PASS` `1=BLOCK` `2=UNPROVEN`。

**核心纪律：UNPROVEN 不是 PASS。** 没验证就说"验证通过"是这个门要消灭的行为。

## Step 4 — What each check catches

| 检查 | 它抓的是什么 | 与 sct.check 的关系 |
|---|---|---|
| `PHANTOM_TASK` | tasks.md 标 `[X]` 但代码中找不到类名/方法名证据——**声称做了实际没做** | 与 `MISSING_IMPL` 反向互补：那里查"SoT 定义了代码没做" |
| `COMPILE` | 测试代码根本编译不过（生成了但没验证过） | check 不编译，只看文本 |
| `REAL_TESTS` | surefire 报告里实际执行数是 0——声称有测试但没真跑 | check 统计的是"生成了多少" |
| `MUTATION` | 注入缺陷后测试不红——测试抓不住 bug（可选） | check 完全不覆盖 |

## Step 5 — Report and remediation

- **幻影任务** → 补实现，或把 `tasks.md` 的 `[X]` 改回 `[ ]`（诚实标注未完成）。
  不要为了让门变绿而删除任务或伪造证据。
- **编译失败** → 修测试代码；是生成代码的问题就改 SoT 后重新 `sct.codegen`。
- **真实测试数 0** → 先让测试真正执行起来（构建配置 / 测试发现路径）。
- **变异得分低** → 加强断言。**断言期望仍须来自 SoT，不得为提分而迎合代码行为。**

## Boundary that must not be crossed

This gate may be made green by **deleting honest signal** (removing tasks,
lowering thresholds, marking things untestable). That defeats its purpose.
If a check cannot be run, leave it `UNPROVEN` and let a human decide — never
downgrade it to `PASS`.
