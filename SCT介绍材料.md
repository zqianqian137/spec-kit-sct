# SCT 介绍材料

> SCT = **S**pec-**C**ode-**T**est，spec-kit 的**验证内核（Verification Kernel）**  
> 版本：v2.2.0　适用：内网试点项目组 / 技术评审  
> 收敛后的定位：**SCT 不生产测试，它生产可裁决的证据**

---

## 一、SCT 是什么

一句话：

> **用最少的测试和最可信的证据，证明 Spec 被正确实现。**

```text
Spec Kit（需求）→ Acceptance Contract（契约）→ Test Design（测试设计）→ Evidence（证据）→ PASS/BLOCK/UNPROVEN
```

它**不改** spec-kit 的原有流程（specify → plan → tasks → implement 原样跑），
只在旁边补一条验证链路：从需求派生测试契约，做测试设计与制定任务，真实执行后用三态证据门判定放行。

**SCT 只自有内核三件事**：① **Evidence Contract**（证据契约，期望只来自 Spec/契约，绝不来自代码）
② **Traceability**（`REQ → AC → TEST → EXECUTION → EVIDENCE` 追溯）
③ **Gate**（四维证据 → PASS/BLOCK/UNPROVEN 三态裁决）。

测试**怎么生成**（JUnit / HTTP / Playwright / Golden / BDD）属于 **Adapter**——
adapter 只负责产出证据，**裁决权不下放**。这样做的好处是：社区里每一个测试生成
扩展都从"竞争对手"变成"上游 adapter"。详见 `docs/verification-kernel.md`。

**三条不可妥协的原则**：

| # | 原则 | 含义 |
|---|---|---|
| ① | **Oracle Independence** | 期望结果只来自 Spec/Contract，绝不来自 Code |
| ② | **Write-once + Integrity** | 可以生成测试，但不能反复改测试直到通过 |
| ③ | **PASS / BLOCK / UNPROVEN** | 证据不足不强行判定 PASS |

**SCT 不做的三件事**（划清边界，避免误用）：

1. 不造"第二个真相源"——`spec.md` 仍是需求来源，SCT 只从它派生**测试契约**；
2. 不绑定语言——Java/JUnit 只是当前默认 adapter，契约格式与门禁与语言无关；
3. 不做测试/性能/安全平台——3 个命令封顶，通过 Adapter 对接外部能力。

---

## 二、解决什么问题

SCT 的全部目标就是这五条，每条都有对应的硬机制：

| # | 目标            | 具体做法                               | 不达标会怎样                         |
| - | ------------- | ---------------------------------- | ------------------------------ |
| 1 | **测试不漏测**     | 测试计划里每个验收点必须映射到测试                  | 有条目没测试 → `MISSING_TEST` → 阻断   |
| 2 | **需求都实现了**    | 计划声明的条目逐一对照代码验证                    | 声明了代码里没有 → `MISSING_IMPL` → 阻断 |
| 3 | **输出真正的测试报告** | 需求 × 代码 × 测试矩阵 + 执行结果 + 覆盖率 + 漏测清单 | 报告是交付物，供人工审核与复跑                |
| 4 | **测试手段分层**    | 单测 → 接口 → e2e（e2e 只要场景案例）          | 三层各自出证据                        |
| 5 | **门禁要阻断**     | 覆盖率 ≥ profile 阈值（standard 档默认 90%）、案例 100% 通过、无漏测无未实现 | 任一不满足 → 退出码非 0 → 阻断合并          |

---

## 三、怎么工作

```text
【spec-kit 主骨架 · 不动】specify → plan → tasks → implement
                              │
                              │  (after_plan 钩子自动提示生成测试计划，可跳过/人工补充)
                              ▼
【SCT 验证内核 · 3 个命令】

  ① 测试计划 testing.plan
     spec.md + plan.md + data-model.md + api-contracts.md → acceptance.yaml
     （可选）变更影响定级 P0/P1/P2 + L1/L2/L3

  ② 测试设计 testing.design
     契约 → 测试设计 + 制定任务（可调用 skill 池提升设计质量）
     派生三层测试（write-once：改契约重生成，不手改测试）

  ③ 测试执行 testing.run
     真实执行 + 门禁 + 出统一详尽报告
       ├ 单测 + 接口测试 + 覆盖率
       ├ 缺陷汇总（执行失败 + 漂移 + 未实现）
       ├ 变更影响分析 + 漂移检测
       └ 功能测试案例（正例/反例）+ Playwright 脚本

     硬门禁：覆盖率 ≥ profile 阈值（standard 档默认 90%）· 案例 100% 通过 · 无漏测 · 无未实现
     → PASS(0) / BLOCK(1) / UNPROVEN(2)，非 0 即阻断
     profile：fast 70% / standard 90%（默认）/ strict 95%（--profile 指定）
```

### 三层测试各自管什么

| 层          | 从什么派生                  | 产出                       | 说明                         |
| ---------- | ---------------------- | ------------------------ | -------------------------- |
| **L1 单测**  | `rules[]` + 方法签名       | 语言原生测试（当前 JUnit+Mockito） | 规则级验证；emitter 可换           |
| **L2 接口**  | `apis[]` + 契约          | 契约测试（**协议无关**，默认 HTTP） | 成功路径 + 每个声明的异常码；不假定传输协议 |
| **L3 e2e** | `acceptance_scenarios` | Playwright 场景案例          | **只要场景案例**（G/W/T），不需要学 DSL |

---

## 四、四条铁律

1. **断言期望只来自测试计划，绝不从代码反推。**  
   代码是被测黑盒；读代码只用来绑定参数"形状"，期望值永远来自计划。  
   从代码反推断言 = 自己出题自己改卷。
2. **测试 write-once：只改测试计划，重新生成，不手改生成的测试。**  
   由 sha256 manifest 强制——手改会被 `testing.run` 判 BLOCK 并自动击穿缓存重生成。
3. **UNPROVEN ≠ PASS：证据不足不得冒充通过。**  
   缺 junit、缺 jacoco 时结论是 UNPROVEN（退出码 2），不是 PASS。
4. **`testing.run` 是确认门，不是补救兜底。**  
   偶尔 BLOCK 后按归因修一次正常；长期靠它循环兜底，说明前向链路没转起来，要修流程。

---

## 五、门禁标准（可直接写进团队规范）

| 维度            | 证据项                  | PASS                          | BLOCK               | UNPROVEN                        |
| ------------- | --------------------- | --------------------------- | ------------------- | --------------------------- |
| 需求覆盖          | `REQUIREMENT_COVERAGE` | 每个计划条目都有测试 **且** 代码里有实现       | 有漏测 / 有未实现           | 无契约条目可追溯                    |
| 执行结果          | `EXECUTION_RESULT`    | 全部案例通过（100%）               | 有失败/错误             | 未给 `--junit` 或 0 执行           |
| 执行结果          | `LINE_COVERAGE`       | 增量行覆盖率 ≥ profile 阈值（standard 档 90%） | < 阈值            | 未给 `--jacoco` + `--base`       |
| 证据完整性         | `EVIDENCE_COMPLETENESS` | 执行 + 覆盖证据齐备                  | —                   | 缺 `--junit` 或 `--jacoco` + `--base` |
| 测试完整性         | `TEST_INTEGRITY`      | 生成文件 sha256 与 manifest 一致且意图完整 | 手改 / 缺失；意图缺失（standard/strict） | 旧版无 manifest；意图缺失（fast 档）     |

**覆盖率阈值由 Quality Profile 决定（`--profile`），不写死**：`fast` 70%（开发期快速反馈）/
`standard` 90%（默认门禁）`/ strict` 95%（发布/受监管变更，缺意图直接 BLOCK）。

**退出码：PASS=0 · BLOCK=1 · UNPROVEN=2。非 0 即阻断。**

---

## 六、快速上手

```bash
# ① 测试计划（specify plan 之后自动生成，从 spec + plan 产物派生）
specify testing.plan --spec specs/001/spec.md --out specs/001/acceptance.yaml
#   plan.md / data-model.md / api-contracts.md 存在时自动一并消费

# ② 人工校正测试计划（断言值、异常码、验收场景——测试质量的关键投入点）

# ③ 派生三层测试案例
specify testing.design --spec specs/001/acceptance.yaml --out tests/generated

# ④ 实现后执行 + 门禁 + 出报告
specify testing.run --spec specs/001/acceptance.yaml \
  --code backend/src/main/java --tests tests/generated \
  --junit tests/generated/junit-report.xml \
  --jacoco backend/target/site/jacoco/jacoco.xml --base main \
  --report specs/001/reports/test-report.md
```

---

## 七、常见问题

**Q：和 spec-kit 原有的 tasks/checklist 冲突吗？**  
不冲突。spec-kit 管"做什么、怎么做"，SCT 管"测没测、测全没、能不能放行"。SCT 读 spec 但不写回。

**Q：必须 Java 吗？**  
不是。当前默认 adapter 是 Java/JUnit（行内现状），测试计划格式、门禁、报告都与语言无关。

**Q：测试要不要人工写？**  
测试计划要人工定（这是测试设计的核心工作），测试代码由计划派生。落地后日常只维护计划。

**Q：覆盖率到不了 standard 档的 90% 怎么办？**  
  默认门禁是 standard=90%（`--profile` 可切 fast 70% / strict 95%）。到不了就两条路：
  补测试，或在计划里说明为何该分支不可测（走人工审核豁免）。降档（如 fast）是可审计的
  显式决定，要在计划 `_meta` 里记录原因——门禁的意义是让"达不到"这件事暴露出来，而不是悄悄过去。

**Q：报告给谁看？**  
给测试负责人和评审人——报告里有完整的"测了什么/没测什么/为什么"，不跑生成流程的人也能审核。

---

## 八、与其他实践的关系

| 实践                | 关系                                        |
| ----------------- | ----------------------------------------- |
| **TDD**           | 互补。SCT 默认 post（代码先行，适合存量项目），也支持 pre（测试先行） |
| **BDD**           | SCT 把 G/W/T 放在测试计划里，并桥接到 Playwright e2e   |
| **覆盖率工具（JaCoCo）** | 采集归 adapter、**阈值判定归内核**（`--profile`）：SCT 用它的覆盖率证据做门禁，但不止于此——还检查漏测与实现缺失 |
| **AI 审查**         | SCT 优先用确定性脚本，模型只辅助（提取、漂移建议），不作最终判决        |
