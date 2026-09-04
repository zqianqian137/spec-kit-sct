# SCT 路线图（2.0 → 3.0）

> SCT 2.0 一句话：**不追求"生成更多测试"，而是用最少的测试和最可信的证据，证明 Spec 被正确实现。**
>
> SCT 3.0 收敛方向：**从 Test Extension 收敛为 Verification Kernel** —— 见[第七节](#七v30从-test-extension-收敛为-verification-kernel)。

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

- **自测 + golden fixtures** ✅：`scripts/self-test.py` 四档回归（golden 全链路 / blocker 坏契约 / gate 漏测 /
  anti-hollow 0 真实执行），零外部依赖。已捕获并修复 2 个真实缺陷（manifest 相对路径、Java 单测追溯误判）
- **SoT 三层拆分**（generated / overrides / lock）：⏸ 设计预留——当前以「派生字段 vs 人工字段」分区 +
  write-once manifest 守卫；完整拆分为独立文件需配套迁移工具，标记为下个里程碑
- **codegen adapter 化**（语言中立）：⏸ **触发式搁置（v2.3 起）**——见[第七节 7.3](#七v30从-test-extension-收敛为-verification-kernel)。
  当前 Java/JUnit 为默认 emitter、无第二个接入方，目录化重构不服务"不遗漏/到位"目标，不做；
  触发条件（第二语言/社区 adapter 真实接入）满足才启动。架构接口（`Evidence Record` +
  `scripts/adapters/...`）设计见 `docs/verification-kernel.md`
- **防空洞收编** ✅ v2.3.0：verification-gate 的 REAL_TESTS / PHANTOM_TASK / COMPILE
  以 `--surefire` / `--tasks` / `--verify-compile` 收编进 testing.run 门禁（可选「测试有效性」维度），
  堵"声称有测试实际 0 执行"的假绿；self-test 增第 4 档 anti-hollow 反例
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

---

## 七、v3.0：从 Test Extension 收敛为 Verification Kernel

### 7.1 为什么收敛

"Test Extension" 这个定位会把 SCT 拖进「测试生成」赛道——那是它**最弱**、
竞争最激烈、也最容易被社区扩展碾压的方向（社区 163 个扩展里 44 个测试相关）。
SCT 真正难以替代的是**验证**：证明 Spec 被正确实现，而不是生成更多测试。

收敛后，社区的每一个测试生成/执行扩展，都从**竞争对手**变成**上游 adapter**。

### 7.2 内核边界

| 层 | 内容 | 归属 |
|---|---|---|
| **Kernel** | **Evidence Contract · Traceability · Gate** | SCT 自有，不可妥协 |
| **Adapter** | JUnit5 / HTTP / Playwright / Golden vectors / BDD / 变异测试 | 外部接入 |
| **Community Extension** | 性能测试 / 安全扫描 / CI 编排 / 测试平台 | 不实现，只留对接契约 |

完整架构、「什么进内核」的判定规则、Adapter 接入规范见
[`docs/verification-kernel.md`](./docs/verification-kernel.md)。

### 7.3 落地状态

| Step | 内容 | 状态 |
|---|---|---|
| 0 | **文档层收敛**：README / 方法论 / 架构文档统一 Kernel 叙事 | ✅ 完成 |
| 0.5 | **防空洞收编（v2.3 落地）**：verification-gate 三态（REAL_TESTS / PHANTOM_TASK / COMPILE）<br>以 `--surefire` / `--tasks` / `--verify-compile` 收编进 testing.run 门禁，成为可选第五维「测试有效性」 | ✅ v2.3.0 |
| 1 | `Evidence Record` schema（`templates/evidence-record-schema.json`）+ `scripts/evidence-collect.py` | ⏸ **触发式搁置** |
| 2 | 现有能力 adapter 目录化：`scripts/adapters/{junit5,http,playwright}/` | ⏸ **触发式搁置** |
| 3 | 首个社区 adapter 接入示例（验证接口够用） | ⏸ 待触发条件 |
| 4 | 命令命名（保持 `speckit.testing.*` vs 改 `speckit.verify.*`） | ⏸ **待决策** |

> **Step 1-2 为何搁置（2026-09-04 用户拍板）**：adapter 目录化 / Evidence Record 代码化
> 服务的是"多语言、多生成器可插拔"——当前只有 Java 一个生成器、无第二个接入方，为它付钱
> 属于**为架构而架构（跑偏）**。用户目标只有两条：**测试不遗漏 + 测试到位（防空洞）**。
> 触发条件（满足其一才启动）：出现第二语言/生成器需求，或社区 adapter 真实接入。
> 在此之前：Kernel/Adapter 的**叙事与红线保留**（已让社区扩展从竞品变上游），工程不先行。
> 优先级让给 Step 0.5 这类直接服务"不遗漏/到位"的收口工作。

> **Step 4 立场（建议）**：v3.0 **不改命令名**。内核化是架构与叙事的变化，
> 命令名是用户肌肉记忆；等 adapter 接口稳定（Step 2-3）后一次性评估，成本更低、决策更准。
> 在此之前命令名保持不变，**定位与文档先行收敛**。

### 7.4 对「三命令封顶」的再确认

收敛**不是**加命令的理由——恰恰相反，它让「三命令封顶」更站得住：
新的测试类型进 **adapter**，不进命令表。
