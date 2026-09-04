# SCT 方法论评估（v2.1.0）

> 评估对象：SCT 2.x 方法论（Spec → Contract → Test → Evidence → Gate）
> 评估时点：v2.1.0（P0 四件事 + P1 自测落地后）
> 评估方式：对照 2.0 目标逐项核查「文档宣称 × 代码强制 × 证据可追溯」

---

## 一、总体结论

**方法论成立，核心主张被代码强制而非仅文档宣称。**
"用最少的测试和最可信的证据证明 Spec 被正确实现"从一句口号变成了可运行的链路：
坏契约在进入下游前被拒（Contract 校验），每条契约条目都能追溯到测试与证据（追溯矩阵），
放行与否由四维证据 × 三态门禁决定（Quality Gate），且覆盖率门槛不再是拍脑袋的 90%。

## 二、三大原则核查（宣称 vs 强制）

| 原则 | 文档宣称 | 代码强制点 | 评估 |
|---|---|---|---|
| ① Oracle Independence | 期望只来自 Spec/Contract | codegen 只读 `test_cases[].expect` / `apis[].error_codes` / `scenario.then`；**没有任何一条路径从源码反推断言** | ✅ 真强制（架构层保证，非自觉） |
| ② Write-once + Integrity | 生成测试不可手改 | sha256 manifest 全量比对，手改即 TEST_INTEGRITY BLOCK；自测 golden 覆盖 | ✅ 真强制 |
| ③ PASS / BLOCK / UNPROVEN | 证据不足不 PASS | 每个 gate 独立三态；`UNPROVEN ≠ PASS` 由退出码 2 强制；contract-validate 同语义 | ✅ 真强制 |

> 三大原则从 v1.0 至今没有一条被破坏过——这是方法论的**信任基石**，也是 2.0 保留三个特色的原因成立。

## 三、架构主线核查（Spec → Contract → Test → Evidence → Gate）

| 环节 | 产物 | 是否可审计 |
|---|---|---|
| Spec（需求） | `spec.md`（spec-kit 骨架所有） | 需求真相源，SCT 不动 ✅ |
| Contract（契约） | `acceptance.yaml` + **Schema 校验** | 每个条目有 ID、唯一、格式受约束 ✅ |
| Test（测试设计） | `testing.design` 产物（write-once） | sha256 manifest 可审计 ✅ |
| Evidence（证据） | 追溯矩阵 + 四维门禁 | **每条 REQ → AC → TEST → EXECUTION → EVIDENCE 可见** ✅ |
| Gate（判定） | PASS/BLOCK/UNPROVEN + 退出码 | 确定性引擎判定，AI 不参与 ✅ |

> 最小追踪链路（REQ → AC → TEST → EXECUTION → EVIDENCE）在 v2.1.0 之前靠"产物索引"拼，
> 现在报告里有**一行一条的矩阵**，这是从"相信"到"可核对"的关键跃迁。

## 四、P0 四件事落地质量

| P0 项 | 实现 | 质量判断 |
|---|---|---|
| Contract | JSON Schema（文档标准）+ 零依赖校验器（确定性执行） | ✅ 双轨制合理：Schema 给外部工具/编辑器，校验器给内网确定性执行 |
| Traceability | 报告固定章节 + 三态证据推导 + Java 单测识别 | ✅ 覆盖三类型条目；发现并修复了 Java 单测误判漏测的真实 bug |
| Evidence | 四维 × 三态 | ✅ 维度清晰；注意：**覆盖率归入"执行结果"维度**，需求覆盖单独成维——符合"Evidence 优先" |
| Gate | Profile 三档 | ✅ 90% 不再硬编码；fast 档给开发期快速反馈，strict 档给发布期 |

## 五、风险与遗留（诚实清单）

1. **P1 两个架构重构是设计预留，未完整落地**（如实标注，不假装完成）：
   - SoT 三层拆分（generated/overrides/lock）——当前 write-once manifest 已部分承担"lock"职责，
     但"派生产物 vs 人工 SoT"双重身份仍在；迁移需配套工具
   - codegen Java adapter 化——1933 行里 Java 硬编码仍是实现事实，语言中立靠"文档声明"而非"架构强制"
2. **契约校验是"脚本接入"而非"命令级强制"**：plan/design/run 命令文件里要求先跑 contract-validate，
   但若使用者绕过命令直接调脚本，校验可能被跳过（非阻断）。
3. **追溯矩阵的执行结果依赖 junit 提供的质量**：junit 缺、错、或用了未识别的命名，EXECUTION 列退化为
   UNPROVEN——这是保守设计（宁可 UNPROVEN 不冒充 PASS），符合原则 ③，但会推高"证据不足"频次。
4. **覆盖率只判"增量行覆盖"**：全量覆盖仅供参考，存量代码的正确性不在门禁内（incremental 模式的设计取舍）。

## 六、给 2.2 的建议（按价值排序）

1. **把契约校验变成命令级前置**：testing.run/design 入口先跑 contract-validate，BLOCK 直接停（现在靠命令文件约定）
2. **Java adapter 化的最小一步**：把 gen_rule_tests 的 Java 类名/包路径约定提取为可配置常量
   （`EMITTER_JAVA=true/false`），为 pytest/Go 留口，不动整体结构
3. **追溯矩阵导出结构化 JSON**：`--trace-json <path>`，让 CI/看板能消费（现在只有 markdown 表）
4. **self-test 纳入更多反例**：手改生成文件 → BLOCK、坏 junit → UNPROVEN、strict 档意图缺失 → BLOCK

## 七、一句话评估

> SCT 2.1 的定位从"一个会生成测试的扩展"变成了"一个**用证据说话的质量门禁**"——
> 判断标准已经站在正确的位置上（契约 + 证据 + 三态），剩下的主要是工程完整性
> （adapter 化、命令级强制、CI 落地），不是方法论方向的错误。
