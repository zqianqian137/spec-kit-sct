# Verification Kernel —— SCT 架构边界与接入规范

> **版本**：v3.0（设计 + 渐进落地中）　**适用**：SCT 维护者 / 想接 adapter 的接入方 / 技术评审
>
> **一句话**：SCT 是 Spec Kit 的**验证内核**——它不生产测试，它生产**可裁决的证据**。
> 内核只管三件事：**Evidence Contract（证据契约）· Traceability（追溯）· Gate（裁决）**；
> 其余一切（JUnit / HTTP / E2E / Golden / BDD / 变异）都是 **Adapter** 或 **Community Extension**。
>
> ⚠️ **状态如实标注**：本文是架构规范。第 2 节的三个内核组件在 v2.1.0 已**落地并运行**；
> v2.3.0 把「防空洞」收编进门禁（Gate 可选第五维「测试有效性」，见 §6 Step 0.5）；
> v2.5.0 语言中立触发条件达成，最小落地 `--lang` 多 emitter + 非标准工程降级（见 §6 Step 2）。
> 第 3 节的 `Evidence Record` 接口与第 6 节的 adapter 目录化结构仍按用户拍板**触发式搁置**
> （社区 adapter 真实接入才启动，见 §6），当前状态 **UNPROVEN**——不假装完成。

---

## 1. 为什么要从 "Test Extension" 收敛成 "Verification Kernel"

名字里带 "Test"，会让 SCT 被当成"测试生成工具"来评估，代价是三个具体的：

| 代价 | 表现 | 后果 |
|---|---|---|
| **① 期望错位** | 评审拿 SCT 和 SpecTest / AI 生成工具比"生成质量、生成量" | 这是 SCT **最弱**的赛道，而且赢不了——通用工具生成量必然更大 |
| **② 边界失守** | 一旦被当成测试工具，每个新需求都变成"再支持一种测试类型"（性能？安全？契约？） | 内核被稀释，三个命令装不下，被迫加命令 |
| **③ 重复建设** | 社区 163 个扩展里 44 个测试相关，SCT 继续横向扩测试能力必然正面相撞 | 投入产出比持续恶化，且社区不认同 |

**收敛后的收益**：社区里每一个测试生成/执行扩展，都从"竞争对手"变成"上游 adapter"。
它们负责把测试跑起来，SCT 负责回答那个它们不回答的问题——
**跑完了，凭什么说 Spec 被正确实现了？**

---

## 2. Kernel：SCT 自有，不可妥协的三件事

| # | 内核组件 | 拥有什么 | 代码位置 | 为什么不能外包 |
|---|---|---|---|---|
| ① | **Evidence Contract** | `acceptance.yaml` 契约格式 + JSON Schema + 版本 + `--profile` | `templates/acceptance-schema.json`<br>`scripts/contract-validate.py` | 契约一旦由**执行方**定义，"期望"就滑向"实现"——即**自己出题自己改卷** |
| ② | **Traceability** | `REQ → AC → TEST → EXECUTION → EVIDENCE` 追溯矩阵 + write-once sha256 manifest | `scripts/consistency-check.py`（矩阵）<br>`_codegen_meta.json`（manifest） | 追溯是门禁的**输入**；断掉任一环，三态门就退化成布尔门 |
| ③ | **Gate** | 四维证据 → `PASS / BLOCK / UNPROVEN`，退出码 `0 / 1 / 2` | `scripts/consistency-check.py`<br>`scripts/verification-gate.py` | 裁决权一旦让渡给生成方或 LLM，`UNPROVEN` 就会消失，绿灯开始说谎 |

### 三条内核公理（任何 adapter 都不得违反）

1. **Oracle Independence** — 期望结果只能来自 Spec/Contract，**绝不来自 Code**。
2. **Write-once + Integrity** — 测试可以生成，但不得被反复修改直到通过（sha256 manifest 强制，手改即 BLOCK）。
3. **PASS / BLOCK / UNPROVEN** — 证据不足不强行判 PASS（`UNPROVEN ≠ PASS`），退出码非 0 即阻断。

---

## 3. Adapter 契约

### 3.1 Adapter 只做两件事

```
emit(test_design) -> 测试产物          # 把契约变成可执行的测试
collect(execution) -> Evidence Record  # 把执行结果交回内核
```

**Adapter 不做的三件事**（违反即为内核污染）：

- ❌ 不写 `acceptance.yaml`（契约只能由 `testing.plan` 从 spec 派生）
- ❌ 不参与最终裁决（它可以给建议，不能给出 verdict）
- ❌ 不把失败改绿——包括不得把 `UNPROVEN` 升格为 `PASS`

### 3.2 `Evidence Record` —— adapter 与内核之间的唯一接口

> **状态**：设计目标（v3.0 Step 1）。当前 adapter 是直连脚本调用，尚未走此接口。

```json
{
  "schema": "sct.evidence_record/1",
  "contract_id": "API-F003-001",
  "adapter": "http",
  "adapter_version": "1.0.0",
  "status": "PASS | BLOCK | UNPROVEN",
  "oracle_source": "contract",
  "test_ref": "tests/generated/test_api_001.py::test_import_rejects_1001_rows",
  "execution": { "executed": 12, "passed": 11, "failed": 1, "skipped": 0 },
  "coverage":  { "line": 0.93, "incremental": 0.88, "source": "jacoco" },
  "integrity": { "sha256": "…", "write_once": true },
  "evidence_refs": ["backend/target/surefire-reports/TEST-*.xml"]
}
```

**内核侧的强制校验**：

| 字段 | 内核如何校验 | 违反时 |
|---|---|---|
| `oracle_source` | 必须等于 `contract` | 直接 BLOCK（反推断言） |
| `contract_id` | 必须存在于 `acceptance.yaml`，且 ID 格式合法 | 追溯矩阵记 UNPROVEN |
| `integrity.sha256` | 必须与 manifest 一致 | `TEST_INTEGRITY` = BLOCK |
| `status` | 只能是三态之一；adapter 不得自造 `PASS_WITH_WARNING` 之类 | 解析失败即 UNPROVEN |
| `execution.executed` | `0` 时不允许报 PASS | `EXECUTION_RESULT` = UNPROVEN |

> 最后一条是内核存在的理由之一：**adapter 说"我通过了"不算数，得拿出执行证据。**

---

## 4. 判定规则：什么进内核，什么进 adapter

新增任何能力前，依次问三个问题，**第一个回答"是"的地方就是归属**：

```
Q1 它决定「放不放行」吗？      → 是 = 内核（Gate）
Q2 它决定「期望是什么」吗？    → 是 = 内核（Evidence Contract）
Q3 它决定「证据怎么产生」吗？  → 是 = Adapter
```

### 4.1 归类速查表

| 能力 | 归属 | 理由 |
|---|---|---|
| JUnit5 单测生成 | **Adapter** | 只决定"证据怎么产生"（Q3） |
| HTTP 接口驱动 | **Adapter** | 同上；HTTP 只是默认 driver，不是方法论假设 |
| Playwright e2e | **Adapter** | 同上；仅场景用例，不引入 DSL |
| Golden vectors | **Adapter** | 喂进契约的行为 oracle，判定仍归内核 |
| BDD（G/W/T） | **Adapter** 侧表达 | G/W/T 存在契约里，由 adapter 翻译成执行 |
| 变异测试（PITest/mutmut） | **Adapter**（可选） | 强度证据，产出喂进四维证据 |
| **覆盖率采集**（JaCoCo） | **Adapter** | 采集是产生证据（Q3） |
| **覆盖率阈值判定** | **内核** | 决定放行（Q1）——`--profile` 属于内核 |
| 契约 Schema 校验 | **内核** | 决定期望合法性（Q2） |
| 追溯矩阵渲染 | **内核** | 门禁输入（Q1） |
| 缺陷汇总 / 报告 | **内核** | 裁决的可审计出口（Q1） |
| 性能测试 / 安全扫描 | **不实现** → Community Extension | 通过 adapter 或外部平台对接 |
| CI 编排执行 | **不实现** → 消费方 | CI Guard 类扩展消费退出码 + Evidence Record |

> 覆盖率这条最容易判错，特意列出：**采集归 adapter，阈值归内核。**
> 换个覆盖率工具（JaCoCo → Istanbul）不影响门禁；但改阈值口径必须动内核、必须发版。

---

## 5. 与社区扩展的关系：从对立到接入

| 社区能力 | 未收敛时（对立） | 收敛后（接入） | SCT 提供什么 |
|---|---|---|---|
| **SpecTest**（测试生成） | 竞品，比生成量 | **上游 adapter**：用它生成测试 | 追溯矩阵 + 三态门禁，让它的产物可裁决 |
| **Golden Demo**（golden 行为 oracle） | 功能重叠 | **golden adapter** | 契约锚定 + 三态门，golden 失败不会被改绿 |
| **Evaluator Contract**（评价契约） | 概念重叠 | **对齐/互导** | SCT 的 Evidence Contract 是它在"Spec 实现验证"场景的实现 |
| **CI Guard**（门禁执行） | 重复造轮子 | **消费方** | 标准退出码 `0/1/2` + `Evidence Record` |
| **变异测试类** | SCT 缺失能力 | **可选 adapter** | 变异得分作为"测试完整性"维度证据进门禁 |

**判定权始终在内核**——这条不谈判。外部能力可以*增强*分析（示例值、调用链、字段比对），
可以*提升*设计质量（skill 池），但**不能给出 verdict，也不能让失败变绿**。

---

## 6. 落地路径（v3.0 —— 不破坏现有命令）

| Step | 内容 | 状态 |
|---|---|---|
| **0** | **文档层收敛**：README / 方法论 / 本文统一 Kernel 叙事 | ✅ v2.2.0 |
| **0.5** | **防空洞收编（v2.3.0 落地）**：verification-gate 三态（REAL_TESTS / PHANTOM_TASK / COMPILE）<br>以 `--surefire` / `--tasks` / `--verify-compile` 收编进 testing.run 门禁，成为可选「测试有效性」维度 | ✅ v2.3.0 |
| **1** | `Evidence Record` schema 落地为 `templates/evidence-record-schema.json` + `scripts/evidence-collect.py` | ⏸ **触发式搁置** |
| **2** | 现有能力 adapter 目录化：`scripts/adapters/{junit5,http,playwright}/`，每个 adapter 暴露 `emit` / `collect` | 🟡 **最小语言中立已落地（v2.5.0）**：触发条件（第二语言需求）达成后，`--lang auto\|java\|python\|none` + pytest emitter + 非标准工程静态断言降级 + 门禁 cobertura 支持落地；**目录化结构仍触发式评估**（不为目录化而目录化） |
| **3** | 首个社区 adapter 接入示例（验证接口够用） | ⏸ 待触发条件 |
| **4** | 命令命名（保持 `speckit.testing.*` 还是改 `speckit.verify.*`） | ⏸ **待决策** |

### 关于 Step 1-2 的立场（2026-09-04 更新）

**Step 1-2 触发式搁置，不再作为主线推进**。理由（用户拍板）：

- 这两步服务的是"多语言 / 多生成器可插拔"——当前只有 Java 一个生成器、无第二个接入方，
  目录化重构不服务 SCT 的目标（**测试不遗漏 + 测试到位**），属于为架构而架构；
- Kernel/Adapter 的**叙事与红线保留**（它已把社区扩展从竞品变成上游），只是**工程不先行**；
- 触发条件（满足其一才启动）：① 出现第二语言/生成器需求；② 社区 adapter 真实接入；
  ③ Step 0.5 收口完成后仍有效益空间。
- 优先级让给直接服务目标的工作：如 Step 0.5 防空洞收编（把"存在≠执行"堵进门禁）。

### 关于 Step 4 的立场（建议）

**建议 v3.0 不改命令名**。理由：

- 内核化是**内部架构 + 对外叙事**的改变，不必然要求命令改名；
- 命令名是用户肌肉记忆，改一次要动全部文档、手册、培训材料；
- 等 adapter 接口稳定（Step 2-3 完成）后，再一次性评估改名，成本更低、决策更准。

在此之前，命令名 `speckit.testing.*` 保持不变，**定位与文档先行收敛**。

---

## 7. 反模式（这些事做了就是内核污染）

- ❌ 在内核里实现某一门语言的测试生成 —— 语言属于 adapter。
- ❌ 让 adapter 写 `acceptance.yaml` —— 契约只能从 spec 派生。
- ❌ 让 LLM 参与最终裁决 —— 它可以辅助填充、检测漂移、给修复建议，**不能判 verdict**。
- ❌ 把 `UNPROVEN` 当 PASS（绿灯说谎），或当 BLOCK（掩盖"证据不足"这个真问题）。
- ❌ 为"覆盖更多测试类型"增加命令 —— **三个命令封顶**，新能力走参数/Adapter。

---

## 8. 新增能力自检清单

每次往 SCT 加东西前，逐条打勾；**任何一条不过，就不该进内核**：

- [ ] 回答了 Q1/Q2/Q3，归属明确？
- [ ] 若归属 adapter：是否只调 `emit` / `collect`，不碰契约？
- [ ] 是否引入了新的"期望来源"？（期望只能来自契约）
- [ ] 是否会让某个失败变成绿色？（包括把 UNPROVEN 升格）
- [ ] 是否需要新增命令？（需要 → 重新设计，走参数或 adapter）
- [ ] 若它产出证据：能否表达为 `Evidence Record`？
- [ ] 裁决是否仍在确定性引擎？（AI 只辅助）
