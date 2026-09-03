# =====================================================================
# E2E 回归报告产物模板（SCT 阶段 5：speckit.testing.cases）
# ---------------------------------------------------------------------
# 生成物：e2e/auto_generated/_summary.json（机器可读）+ 本报告（人类可读）
# 生成器：change-impact-e2e-bridge.py（生成 spec.js），报告由 CI 执行后汇总
# 用途：记录本轮变更触发的回归范围、执行结果与失败修复建议（--ai-fix）。
# =====================================================================

# E2E 回归测试报告

**Generated**: {ISO8601 时间戳}
**Impact Source**: `change-impact.md`（P0={n}, P1={n}）
**SoT**: `specs/001-xxx/acceptance.yaml`
**Runner**: Playwright（e2e/auto_generated/*.spec.js）
**Tool**: change-impact-e2e-bridge.py

## 1. 回归范围

| Priority | 计划 | 已执行 | 通过 | 失败 | 跳过 |
|----------|------|--------|------|------|------|
| P0 | {n} | {n} | {n} | {n} | 0 |
| P1 | {n} | {n} | {n} | {n} | 0 |
| **Total** | **{n}** | **{n}** | **{n}** | **{n}** | 0 |

## 2. 执行明细

> 每行对应 SoT 中一个 acceptance_scenario；意图说明见生成脚本头部注释。

| Scenario | Priority | Given → When → Then | 状态 | 耗时 | 产物 |
|----------|----------|---------------------|------|------|------|
| F001-1 | P0 | 已登录用户 → 上传合法 CSV → 返回 taskId | ✅ PASS | 3.2s | trace/F001-1.zip |
| F001-2 | P1 | 同名任务已存在 → 再次上传 → 409 冲突 | ❌ FAIL | 2.8s | trace/F001-2.zip |

## 3. 失败分析与修复建议（--ai-fix）

### F001-2 ❌

- **现象**: 断言 ui_message 未包含「导入成功」（实际返回 500）
- **AI 诊断**: `BatchTaskService.checkDuplicate()` 未按 BR-002 抛出冲突异常
- **建议 diff**:

```diff
- if (exists(task.getFileName())) { log.warn("duplicate"); }
+ if (exists(task.getFileName())) { throw new ConflictException("duplicate fileName"); }
```

- **处置**: 修复后重跑 `speckit.testing.run` → `speckit.testing.cases`

## 4. 结论

- **回归结论**: ✅ ALL PASS / ❌ {n} FAILED
- **是否放行**: P0 全部通过即可放行；P1 失败需记录缺陷并限期修复
