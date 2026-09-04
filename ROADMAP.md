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
| 1 | 定位升级 | Spec → Test → Evidence → Quality Gate | 🟡 文档已定调，代码待对齐 |
| 2 | Acceptance Contract | 强化 acceptance.yaml 作为需求与测试之间的标准契约 | 🟢 已有（契约 + 断言不反推代码） |
| 3 | 追踪闭环 | REQ → AC → TEST → EXECUTION → EVIDENCE 最小链路 | 🟡 部分（缺显式追溯矩阵） |
| 4 | AI 与规则分离 | AI 负责分析/生成/建议；确定性 Engine 负责最终判定 | 🟢 已贯彻（`--ai` 仅辅助，门禁确定性） |
| 5 | 保留核心能力 | 三个命令即可，不增加命令 | 🟢 Plan / Design / Run |
| 6 | Evidence 优先 | 不只 Coverage，还看执行结果/需求覆盖/证据完整性/测试完整性 | 🟡 已有四证据项，可再强化 |
| 7 | Quality Profile | Fast / Standard / Strict 替代硬编码「90%」 | ⚪ 待实现 |
| 8 | 控制边界 | 不做测试/性能/安全平台，通过 Adapter/Extension 对接 | 🟢 已明确 |

## 五、优先级建议（P0 优先）

### P0 — Contract + Traceability + Evidence + Gate（下个里程碑）

1. **Contract**：为 `acceptance.yaml` 定义 JSON Schema + 版本 + ID 唯一性校验（当前只 `yaml.safe_load`）
2. **Traceability**：新增显式 `REQ → AC → TEST` 追溯矩阵（每条需求追溯到契约条目和测试），作为报告的固定章节
3. **Evidence**：把证据项从 4 项扩展到「需求覆盖 + 执行结果 + 证据完整性 + 测试完整性」四维
4. **Gate**：Quality Profile（Fast / Standard / Strict）替代硬编码 90% 覆盖率

### P1 — 架构演进

- SoT 三层拆分（generated / overrides / lock），解决"派生产物 vs 人工 SoT"双重身份
- codegen 1933 行 Java 硬编码 adapter 化（语言真正中立）
- 自测 + golden fixtures + 跨平台 CI

### P2 — 边界控制

- 通过 Adapter 对接外部测试平台 / 性能 / 安全，不自己做

## 六、命令体系（2.0）

| 命令 | 阶段 | 职责 |
|---|---|---|
| `speckit.testing.plan` | 契约 | 从 spec + plan 产物生成 acceptance.yaml（测试契约）+ 变更影响定级 |
| `speckit.testing.design` | 测试设计 | 把契约变成测试设计 + 制定任务，派生 write-once 测试案例（可调用 skill 池提升设计质量） |
| `speckit.testing.run` | 证据 + 门禁 | 真实执行 + 四维证据 + 三态门禁 + 统一报告 |

> 关键约束：**三个命令封顶**，新能力通过参数/Adapter 扩展，不再增加命令。
