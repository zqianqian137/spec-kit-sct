# =====================================================================
# 变更影响报告产物模板（SCT 阶段 4：speckit.testing.plan）
# ---------------------------------------------------------------------
# 生成物：change-impact.md
# 生成器：change-impact.py（render_report）
# 消费方：change-impact-e2e-bridge.py（阶段 5 按 P0/P1 挑选回归场景）
# =====================================================================

# Change Impact Report

**Date**: {YYYY-MM-DD HH:MM:SS}
**SoT**: `specs/001-xxx/acceptance.yaml`
**Tool**: change-impact.py v1.0-W2-INTERNAL
**Diff**: base=main head=HEAD（或 --staged）
**变更级别**: L1（小改：存量回归即可，本文件到此为止）/ L2（中改：定向 codegen + check）/ L3（大改：完整 SOP + e2e）

> 级别由 testing.plan Step 0 判定，写入本行；下游命令（codegen/check/e2e）
> 读取此行决定是否短路。L1 时本文件只需级别 + 一行理由。

## 📊 Summary

| Priority | Count |
|----------|-------|
| **P0**   | **{n}** |
| P1       | {n} |
| P2       | {n} |
| **Total**| **{n}** |

## 📁 Changed Files

| Type | File |
|------|------|
| api | `backend/src/main/java/.../BatchTaskController.java` |
| service | `backend/src/main/java/.../BatchTaskService.java` |
| ui / test / config / other | ... |

## 📋 实现需求（Spec→Code 契约，implement 照此单实现）

> 从 SoT (acceptance.yaml) P0/P1 范围**原文转录**，是实现阶段的输入契约。
> L1 变更跳过本节（无 SoT 变更）。实现完成时逐条勾选（[ ]→[x]）。

### APIs

- [ ] **API-001 创建批量导入任务** `POST /api/batch-tasks`
  - 请求：`fileName*`(string, 必填)、`mode`(enum: full|increment)
  - 成功：200 `{taskId, status}`
  - 异常：400 参数缺失 / 409 同名任务冲突
- [ ] **API-002 重试失败用例** `POST /api/batch-tasks/:id/retry`
  - （SoT 原文转录同上）

### Rules

- [ ] **BR-001**：单次导入上限 10000 行，超出拒绝并提示

### Scenarios

- [ ] **F001-1**：已登录用户 → 上传合法 CSV → 返回 taskId

## 🎯 Recommended E2E Scenarios

> 每个场景均来自 SoT 的 acceptance_scenarios（given/when/then），
> 供阶段 5（testing.design）生成 Playwright 回归脚本。

| Priority | Scenario | Given → When → Then | Match Rule |
|----------|----------|---------------------|------------|
| **P0** | F001-1 | 已登录用户 → 上传合法 CSV → 返回 taskId | W1 保守匹配（W2 实现 4 维度） |
| P1 | F001-2 | 同名任务已存在 → 再次上传 → 409 冲突 | 同上 |

## ⚠️ Risk Zones

- **{n} 个 API 文件变更** — 影响范围最大
- **{n} 个 service 文件变更** — 业务规则可能漂移
- **{n} 个前端文件变更** — UI 状态机可能有隐藏 bug

---

> W1 阶段：保守匹配所有 scenario 为 P0/P1。
> W2 计划：实现 SCT §18 4 维度匹配算法（API/UI/Rule/Scenario）。
