# =====================================================================
# SCT 测试报告产物模板（阶段 3：speckit.sct.check）
# ---------------------------------------------------------------------
# 生成器：consistency-check.py（--report 输出，--jacoco/--junit 注入数据）
# 落盘位置：specs/{feature}/reports/test-report.md
# 定位：**人工审查核心产物** —— 审查者据此回答两个问题：
#   Q1 测试是否测到了本次改动点？（第 5 节 改动点审查）
#   Q2 业务逻辑是否被正确实现？（第 3/4 节 接口与规则执行情况）
# 放行规则：存在 HIGH 漂移 或 P0 场景未覆盖/未通过 → FAIL，禁止合入。
# =====================================================================

# SCT 测试报告（一致性 × 覆盖率 × 执行情况）

**Generated**: {ISO8601 时间戳}
**SoT**: `specs/001-xxx/acceptance.yaml`
**Code Scope**: `backend/src/main/java`（scope=batch）
**Tests**: `tests/generated/`
**Diff Base**: `main...HEAD`（增量覆盖率的基线）
**覆盖模式**: full（全量）/ incremental（增量：存量项目 SoT 只登记变更范围，存量未登记代码不算漂移）
**CodeGraph**: `已接入（codegraph.json）`——示例值/必填/异常值取自真实代码，实现标注见 3.2，字段级漂移见 6.2，系统级异常见 6.3，派生异常用例 {n} 个（test_*_cg_error_*） / 未接入（示例值为 SoT 启发式，无字段级比对与异常值派生）
**JaCoCo 报告**: `target/site/jacoco/jacoco.xml` + `index.html`
**Tool**: consistency-check.py

> **增量模式（brownfield）**：存量项目不做全量补测。门禁 = SoT 范围内 API/规则覆盖
> 100% + 增量行覆盖率 ≥ 80%；`UNSPEC_API` 不上报，全量覆盖率仅供参考。

## 1. 执行摘要

| 维度 | 结果 | 门禁 |
|------|------|------|
| 三方一致性 | {0 个 HIGH 漂移} | 无 HIGH |
| 增量行覆盖率 | {85.2%} | ≥ 80% |
| 接口测试执行 | {12/12 通过} | 全部通过 |
| P0 改动点覆盖 | {4/4 已测且通过} | 100% |
| 字段级漂移 (FIELD_DRIFT) | {2 个} | 建议 0（不阻塞放行） |
| **总结论** | ✅ PASS / ❌ FAIL | — |

## 2. JaCoCo 代码覆盖率

### 2.1 总体覆盖率

| 维度 | 未覆盖 | 已覆盖 | 总量 | 覆盖率 |
|------|--------|--------|------|--------|
| 指令 (INSTRUCTION) | 1,200 | 6,800 | 8,000 | 85.0% |
| 行 (LINE) | 150 | 850 | 1,000 | 85.0% |
| 方法 (METHOD) | 12 | 88 | 100 | 88.0% |

### 2.2 增量覆盖率（本次改动，人工审查重点）

> 仅统计本次 diff 涉及的类；回答"改动是否被测试执行过"。

| 维度 | 未覆盖 | 已覆盖 | 总量 | 覆盖率 |
|------|--------|--------|------|--------|
| 指令 (INSTRUCTION) | 60 | 340 | 400 | 85.0% |
| 行 (LINE) | 8 | 42 | 50 | 84.0% |
| 方法 (METHOD) | 1 | 9 | 10 | 90.0% |

**本次改动的类**：`BatchTaskController.java`、`BatchTaskService.java`

**未覆盖的增量方法**（若为空则全部覆盖）：

| 类 | 方法 | 原因分析（人工填写） |
|----|------|----------------------|
| BatchTaskService | retryTask() | 分支未被任何案例触发，需补 test_api_002_error_2 |

### 2.3 报告产物

- HTML 明细：`target/site/jacoco/index.html`（逐行染色）
- XML 数据：`target/site/jacoco/jacoco.xml`（本报告数据来源）

## 3. 接口测试覆盖与执行情况

### 3.1 覆盖情况

> API 总数来自 SoT `apis[]`；已测 = 存在对应 `test_api_{id}` 案例且已执行。

| 指标 | 数值 |
|------|------|
| API 总数 | 5 |
| 已测 | 5 |
| 未测 | 0 |

### 3.2 案例情况与执行结果

> 「实现」列来自生成测试文件头部的 CodeGraph 标注（Controller → Service）；
> 「其中派生异常」为 CodeGraph 约束派生的 `cg_error` 用例数（含在案例数内）。
> CodeGraph 未接入或未匹配的 API 显示「未匹配」/省略该列。

| API ID | 接口名 | 方法 | 路径 | 实现（Controller → Service） | 案例数 | 其中派生异常 | 通过 | 失败 | 跳过 | 状态 |
|--------|--------|------|------|------------------------------|--------|--------------|------|------|------|------|
| API-001 | 创建批量导入任务 | POST | `/api/batch-tasks` | BatchTaskController → BatchTaskService | 9（1 正常 + 8 异常） | 6 | 9 | 0 | 0 | ✅ |
| API-002 | 重试失败用例 | POST | `/api/batch-tasks/:id/retry` | BatchTaskController → BatchTaskService | 3 | 2 | 3 | 0 | 0 | ✅ |

**失败案例明细**（若为空则全部通过）：

| 案例 | 真相来源 | 失败原因 | 缺陷单 |
|------|----------|----------|--------|
| test_api_003_error_1 | apis[API-003].errors[1] | 返回 500，预期 409 | BUG-1024 |

### 3.3 案例意图说明完整性

> 按单元测试模板约定，每个案例必须带 `[意图]/真相来源/Given/When/Then`。

- 检查案例数：12
- 缺失意图说明：0（若有列出：`test_xxx.py::test_yyy`）

## 4. 业务规则验证情况

> 回答"业务逻辑是否实现"：每条规则必须有案例且通过。

| Rule ID | 规则（意图） | 优先级 | 对应测试 | 执行结果 | 结论 |
|---------|--------------|--------|----------|----------|------|
| BR-001 | 单次导入不超过 1000 条用例 | P0 | test_rules.py::test_br_001 | ✅ PASS | 已实现 |
| BR-002 | 同名任务拒绝创建 | P1 | test_rules.py::test_br_002 | ❌ FAIL | 未通过，见 BUG-1024 |

## 5. 改动点审查（人工审查核心）

> 数据来自 `change-impact.md`（阶段 4）× 测试执行结果。
> 审查者逐行确认：每个 P0/P1 改动点是否被测试覆盖并通过，并填写审查意见。

| 场景 ID | 优先级 | Given → When → Then | 覆盖测试 | 执行结果 | 测到改动点 | 审查意见（人工填写） |
|---------|--------|---------------------|----------|----------|------------|----------------------|
| F001-1 | P0 | 已登录用户 → 上传合法 CSV → 返回 taskId | test_sc_f001_1 + F001-1.spec.js | ✅ | ✅ 是 | |
| F001-2 | P1 | 同名任务已存在 → 再次上传 → 409 冲突 | test_sc_f001_2 | ❌ FAIL | ⚠️ 已测未过 | 需修复后回归 |

## 6. 漂移明细

### 6.1 三方一致性漂移（spec ↔ code ↔ test）

> 漂移类型：`MISSING_IMPL`(HIGH) / `UNSPEC_API`(MEDIUM) / `MISSING_TEST`(HIGH) / `MISSING_RULE_TEST`(MEDIUM) / `MISSING_INTENT`(MEDIUM)

| # | 严重级别 | 类型 | 描述 | 修复建议 |
|---|----------|------|------|----------|
| 1 | HIGH | MISSING_IMPL | spec 定义但未实现: POST /api/batch-tasks/:id/retry | 补实现或修正 SoT |

### 6.2 FIELD_DRIFT（SoT ↔ 代码 DTO 字段比对）

> 来源：acceptance-codegen（CodeGraph `codegraph.json`，经 `_codegen_meta.json` 自动发现）。
> `MISSING_IN_CODE` 优先处理（SoT 改了代码没跟上）；`UNSPEC_IN_SOT` 增量模式下建议
> 补登记；`REQUIRED_MISMATCH` 核对必填口径。未接入 CodeGraph 时本节显示「未接入，无字段级比对」。

| API | 字段 | 类型 | 说明 |
|-----|------|------|------|
| POST /api/batch-tasks | mode | MISSING_IN_CODE | SoT 定义字段 mode 但代码 DTO 无此字段 |
| POST /api/batch-tasks | remark | UNSPEC_IN_SOT | 代码 DTO 有字段 remark 但 SoT 未登记 |
| POST /api/batch-tasks | count | REQUIRED_MISMATCH | 字段 count 必填性不一致：SoT=True 代码=False |

### 6.3 系统级异常清单（@ControllerAdvice，测试文件头部标注）

> 来源：CodeGraph `global_exceptions`（同步写入各生成测试文件头部）。全接口适用、
> 不可自动触发（401 需无 token、500 需故障注入），故不生成用例，由安全/框架测试
> 覆盖——本清单供人工审查系统异常值全集。

| Status | Code | Message | Exception | 覆盖方式 |
|--------|------|---------|-----------|----------|
| 400 | VALIDATION_FAILED | 参数校验失败 | MethodArgumentNotValidException | 安全/框架测试 |
| 401 | UNAUTHORIZED | 未认证 | UnauthorizedException | 安全/框架测试 |
| 404 | NOT_FOUND | 资源不存在 | NoSuchResourceException | 安全/框架测试 |
| 409 | DUPLICATE | 资源重复 | DuplicateException | 安全/框架测试 |
| 500 | INTERNAL_ERROR | 系统内部错误 | Exception | 安全/框架测试 |

## 7. 结论与放行

- HIGH 漂移: {n} 个
- P0 改动点: {n}/{n} 已覆盖且通过
- 增量行覆盖率: {x%}（门禁 ≥ 80%）
- 字段级漂移 (FIELD_DRIFT): {n} 个（见 6.2，不阻塞放行）
- 派生异常用例: {n} 个（CodeGraph 约束/枚举/类型派生，见 3.2「其中派生异常」列）
- 系统级异常清单: {n} 个（见 6.3，供人工审查）
- **最终结论**: ✅ PASS（可合入）/ ❌ FAIL（先消除 HIGH 漂移与 P0 失败再合入）

> FAIL 处置路径：改 spec / 改 code / 改 SoT → 重跑 `sct.codegen` → `sct.check` → `sct.e2e`。
