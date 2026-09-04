# SCT 2.0 路线图

> SCT 2.0 一句话：**不追求"生成更多测试"，而是用最少的测试和最可信的证据，证明 Spec 被正确实现。**

---

## 一、定位升级

从「测试生成 Extension」升级为 **Spec → Test → Evidence → Quality Gate**：

```text
Spec Kit (需求，骨架所有)
   ↓
Acceptance Contract (acceptance.yaml：需求与测试之间的标准契约)
   ↓
Test (testing.design：测试设计 + 制定任务)
   ↓
Evidence (testing.run：执行结果 + 覆盖率 + 缺陷 + 漂移)
   ↓
PASS / BLOCK / UNPROVEN (Quality Gate)
```

## 二、最小追踪链路

`REQ → AC → TEST → EXECUTION → EVIDENCE`

每个需求（REQ）都能追溯到验收契约（AC）、测试（TEST）、执行结果（EXECUTION）和证据（EVIDENCE）。
当前进度：契约 + 测试 + 执行 + 三态证据已具备，缺的是**一条显式的 REQ→AC→TEST 追溯矩阵**（当前靠 `COVERAGE_REPORT.md` 的 spec→test 映射部分覆盖）。

## 三、三大特色（不可妥协的设计原则）

| # | 特色 | 含义 |
|---|---|---|
| ① | **Oracle Independence** | Expected Result 必须来自 Spec/Contract，**绝不能来自 Code**（反推断言 = 自己出题自己改卷） |
| ② | **Write-once + Integrity** | AI 可以生成代码，但**不能反复改测试直到自己通过**（sha256 manifest 强制，手改即 BLOCK） |
| ③ | **PASS / BLOCK / UNPROVEN** | 证据不足时不强行判定 PASS（`UNPROVEN ≠ PASS`） |

## 四、八大优化方向与状态

| # | 方向 | 说明 | 状态 |
|---|---|---|---|
| 1 | 定位升级 | Spec → Test → Evidence → Quality Gate | 🟢 架构主线 + 三大原则已落地并写入全部文档 |
| 2 | Acceptance Contract | 强化 acceptance.yaml 作为需求与测试之间的标准契约 | 🟢 JSON Schema + 版本 + ID 唯一性校验（contract-validate.py） |
| 3 | 追踪闭环 | REQ → AC → TEST → EXECUTION → EVIDENCE 最小链路 | 🟢 追溯矩阵为报告固定章节（含 Java 单测识别） |
| 4 | AI 与规则分离 | AI 负责分析/生成/建议；确定性 Engine 负责最终判定 | 🟢 已贯彻（`--ai` 仅辅助，门禁确定性） |
| 5 | 保留核心能力 | 三个命令即可，不增加命令 | 🟢 Plan / Design / Run |
| 6 | Evidence 优先 | 不只 Coverage，还看执行结果/需求覆盖/证据完整性/测试完整性 | 🟢 四维证据（需求覆盖/执行结果/证据完整性/测试完整性） |
| 7 | Quality Profile | Fast / Standard / Strict 替代硬编码「90%」 | 🟢 `--profile fast|standard|strict`（standard=90% 默认） |
| 8 | 控制边界 | 不做测试/性能/安全平台，通过 Adapter/Extension 对接 | 🟢 已明确 |

## 五、优先级建议（P0 优先）

### P0 — Contract + Traceability + Evidence + Gate（✅ v2.1.0 已落地）

1. **Contract** ✅：`templates/acceptance-schema.json` + `scripts/contract-validate.py`（零依赖三态校验，plan/design/run 全接入）
2. **Traceability** ✅：报告固定章节「需求追溯矩阵（REQ → AC → TEST → EXECUTION → EVIDENCE）」，含 Java 单测识别
3. **Evidence** ✅：门禁重构为四维证据（需求覆盖/执行结果/证据完整性/测试完整性），终端与报告同步
4. **Gate** ✅：`--profile fast(70%) / standard(90%) / strict(95%)`，覆盖率门槛不再硬编码

### P1 — 架构演进（v2.1.0 部分落地）

- **自测 + golden fixtures** ✅：`scripts/self-test.py` 三档回归（golden 全链路 / blocker 坏契约 / gate 漏测），
  零外部依赖。已捕获并修复 2 个真实缺陷（manifest 相对路径、Java 单测追溯误判）
- **SoT 三层拆分**（generated / overrides / lock）：⏸ 设计预留——当前以「派生字段 vs 人工字段」分区 +
  write-once manifest 守卫；完整拆分为独立文件需配套迁移工具，标记为下个里程碑
- **codegen adapter 化**（语言中立）：⏸ 设计预留——Java/JUnit 为默认 emitter，self-test 已固定 Java
  测试路径约定；完整 adapter 接口 + 多语言接入需配套重构，标记为下个里程碑
- 跨平台 CI：内网无 CI 条件，以 `scripts/self-test.py` 替代（手动/定时可跑）

### P2 — 边界控制（✅ 已明确，写入方法论评估）

- 不做测试/性能/安全/架构治理平台。外部能力一律通过 **Adapter/Extension 对接**：
  - **测试平台对接**：`e2e/auto_generated/_intent_tests.json` 是唯一对接契约（外部平台按 intent 驱动执行），
    SCT 不实现平台自身的执行编排
  - **CodeGraph/MCP**：只增强 analysis（示例值、调用链、字段比对），不参与判定
  - **skill 池**：testing.design 可调用，只提升设计质量，不改变契约、不让失败测试变绿
  - 判定权始终在确定性引擎（contract-validate / consistency-check / verification-gate）

## 六、命令体系（2.0）

| 命令 | 阶段 | 职责 |
|---|---|---|
| `speckit.testing.plan` | 契约 | 从 spec + plan 产物生成 acceptance.yaml（测试契约）+ 变更影响定级 |
| `speckit.testing.design` | 测试设计 | 把契约变成测试设计 + 制定任务，派生 write-once 测试案例（可调用 skill 池提升设计质量） |
| `speckit.testing.run` | 证据 + 门禁 | 真实执行 + 四维证据 + 三态门禁 + 统一报告 |

> 关键约束：**三个命令封顶**，新能力通过参数/Adapter 扩展，不再增加命令。
