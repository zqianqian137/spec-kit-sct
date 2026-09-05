# Changelog

All notable changes to the SCT extension are documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [2.5.0] - 2026-09-05

### Added — L1 语言中立：Python emitter + 非标准工程降级（触发条件达成：用户明确第二语言需求）

ROADMAP §7.3 Step 2 的触发条件（出现第二语言/生成器需求）已满足，落地**最小**语言中立：

- `acceptance-codegen.py --lang auto|java|python|none`（默认 auto，按工程标记探测：
  pom/gradle/*.java → java；*.py/pyproject/requirements → python；否则 none）；
- **python emitter** `gen_pytest_unit_tests`：为带 `target+test_cases` 的规则生成
  `test_unit_py.py`（函数名 `test_br_{suffix}`，与规则覆盖率/追溯矩阵既有约定兼容）；
  输入值来自 SoT、形状经 `inspect.signature` 读公共签名、依赖用 stdlib
  `unittest.mock.MagicMock` 注入（零外部依赖）；断言支持 `returns` / `throws`；
  分歧如实报 drift（`MODULE_NOT_FOUND` / `MISSING_INPUT` / `SIGNATURE_MISMATCH`），不静默；
- **非标准工程（none）**：不生成 target 单测、不崩溃，`test_rules.py` 静态断言层兜底；
- self-test 增至**六档**：新增 python 档（派生 → pytest 真执行 → 门禁 PASS）与
  none 档（非标准工程降级）。

### Added — 门禁语言中立

- `consistency-check.py` 覆盖率解析支持 **coverage.py 的 cobertura XML**
  （`coverage xml`，类级行计数按 `<line hits>` 统计）——Python 项目与 Java
  JaCoCo 走同一 `--jacoco` 参数、同一覆盖率门禁；增量匹配扩展到 `.py` 变更文件；
- **Python 路由提取**（Flask / FastAPI / aiohttp 声明式路由）→ MISSING_IMPL 证据；
  自造路由表的工程以契约 `_meta.impl_evidence: none` 显式声明后降级为人工核对项
  （MEDIUM），接口层的真实执行证据仍然把关；
- 接口测试预检提示语言无关的启动方式（uvicorn / manage.py / mvn spring-boot:run / java -jar）。

### Added — L3 e2e 可选执行器（内网友好）

- `scripts/e2e-runner.py`：环境齐备才执行 playwright specs（产出 junit 证据）；
  缺 pytest-playwright / 浏览器时**一次说全缺失清单**（含内网离线安装提示），
  退出码 2（UNPROVEN）——用户不装则 e2e 不参与门禁，UNPROVEN ≠ PASS；
  浏览器二进制缺失（"Executable doesn't exist"）自动识别为 UNPROVEN 而非 BLOCK。

### Fixed

- `verification-gate.py` REAL_TESTS：兼容 pytest `--junitxml` 格式（根 `<testsuites>`，
  计数在子节点）——此前读成 0 而误报 BLOCK；
- `self-test.py` golden 补 `--code`（此前依赖不存在的默认 code root）。

### Removed — 仓库卫生

- `docs/methodology-assessment.md` 移出版本库（本地保留，`.gitignore` 忽略）。

## [2.4.0] - 2026-09-05

### Added — 内网工程级收口（全链路演练验证：门禁 PASS）

**全链路演练**（contract → codegen 三层派生 → L1 `mvn test`+JaCoCo 真实执行 →
L2 pytest 对活服务执行 → L3 场景执行 → 六维门禁 **PASS(exit 0)**），期间发现并修复
1 个 codegen 缺陷：

- `acceptance-codegen.py`：目标方法公共签名**零参数**而 SoT `inputs` 非空时，原先静默把
  参数硬塞进调用（`upload(arg0)`，必然编译失败）且无任何 drift。现报
  **`SIGNATURE_MISMATCH`** BINDING_DRIFT 并生成可编译的诚实调用，交人工裁决。

### Changed — 契约校验命令级强制（P0 遗留风险收口）

- `consistency-check.py`（`testing.run`）入口内置 `contract-validate.validate`：
  坏契约（结构错误/重复 ID）直接 **BLOCK(exit 1)**，绕过命令直调脚本也拦得住——
  消掉方法论评估中的风险 2（"脚本级接入而非命令级强制"）。

### Added — 追溯矩阵结构化导出

- `testing.run --trace-json <path>`：输出 `{source_spec, profile, verdict, gates[], items[]}`，
  CI / 看板可直接消费（原只有 markdown 报告表格）。

### Changed — self-test 环境探针 + 新断言

- 启动探针：Python ≥ 3.10（脚本使用 `X | Y` 类型标注）+ PyYAML，缺失给明确报错退出 2，
  不再半路难排查失败；
- 新增 2 档断言：坏契约直调门禁 → 入口 CONTRACT BLOCK；golden `--trace-json`
  可解析且 verdict=PASS。

### Removed — 仓库卫生

- 移除内部材料《SCT介绍材料》《SCT内网实践操作手册》（本地保留，`.gitignore` 已忽略）；
  本地演练 scratch `src/` 同样忽略。

## [2.3.0] - 2026-09-04

### Changed — 路线纠偏：v3.0 主线 = 防漏测 / 防空洞收口（用户拍板）

用户判定「adapter 目录化」跑偏——它的目的是"多语言 / 多生成器可插拔"，而用户的目的是
**测试不遗漏 + 测试到位**。当前只有 Java 一个生成器、无第二个接入方，为可插拔做重构
属于为架构而架构：

- ROADMAP 第七节 / `docs/verification-kernel.md` §6 的 **Step 1-2（`Evidence Record` 代码化 +
  adapter 目录化）从主线改为「⏸ 触发式搁置」**：触发条件（第二语言/生成器需求，或社区 adapter
  真实接入）满足才启动；
- Kernel / Adapter 的**叙事与红线保留**（社区扩展仍是上游 adapter），工程不先行；
- 优先级让给直接服务"不遗漏 / 到位"的收口工作（见下）。

### Added — Gate 可选第五维「测试有效性」（防空洞）

把 `verification-gate.py` 的三个三态检查**收编进 `testing.run` 门禁**（consistency-check.py）：

- `--surefire <dir>` → **`REAL_TESTS`**（真实执行数）：surefire 报告实际执行为 0 → **BLOCK**，
  堵"声称有测试、实际一个都没跑"的假绿；
- `--tasks <tasks.md>` → **`PHANTOM_TASK`**（幻影任务）：tasks.md 标 `[X]` 但代码无实现证据 → BLOCK；
- `--verify-compile` → **`COMPILE`**（编译门）：显式开启才跑——内网无 mvn/gradle 时不拖累门禁
  （有 surefire 真实执行即隐含已编译）；
- 任一旗标提供即在报告 §1 与终端摘要追加「测试有效性」维度证据项；`verification-gate.py`
  缺失时降级 **UNPROVEN**（不假装完成）；整体取最严的语义不变。

`verification-gate.py` 保留独立使用（三检查 + 编译门一把梭）。

### Changed — self-test 增至四档

- 新增第 4 档 **anti-hollow**：surefire 真实执行 0 → `REAL_TESTS` BLOCK(exit 1)；
  有真实执行（2 个全过）→ PASS(exit 0)。golden / blocker / gate / anti-hollow 四档全绿。

## [2.2.0] - 2026-09-04

### Changed — 定位收敛：从 Test Extension 到 Verification Kernel

一句话：**SCT 不生产测试，它生产可裁决的证据。**

- **内核边界明确**：SCT 只自有三件事 —— **Evidence Contract**（`acceptance.yaml` + Schema + `--profile`）、
  **Traceability**（`REQ → AC → TEST → EXECUTION → EVIDENCE` + write-once manifest）、
  **Gate**（四维证据 → PASS/BLOCK/UNPROVEN，退出码 0/1/2）。
  测试生成 / JUnit / HTTP / E2E / Golden / BDD 全部归 **Adapter**，通过 `Evidence Record`
  接口回传证据，**裁决权不下放**
- 新增 `docs/verification-kernel.md`：Kernel/Adapter 边界、`Evidence Record` 接口、
  「什么进内核」三问判定规则（Q1 放行 / Q2 期望 / Q3 证据产生）、与社区扩展
  （SpecTest / Golden Demo / Evaluator Contract / CI Guard）的接入关系、反模式与自检清单
- README / ROADMAP / extension.yml / catalog-entry.json 定位统一为 Verification Kernel
- 本版是 **v3.0 方向的 Step 0**；adapter 接口代码化（Step 1-2）仍为设计预留，**未假装完成**

> **命令名不变**：`speckit.testing.*` 三个命令保持不动。是否改为 `speckit.verify.*`
> 留到 adapter 接口稳定后决策（ROADMAP 第七节 Step 4），改名成本与用户肌肉记忆都已纳入考量。

### Added — `scripts/check-release-consistency.py`（发布前一致性自检）

用 SCT 自己的三态门守 SCT 自己的发布，7 项检查每项独立判 PASS/BLOCK/UNPROVEN、整体取最严：

`VERSION`（三处版本号 + README 安装链接）· `COMMANDS` · `HOOKS` · `DESCRIPTION`
· `TAGS` · `LEGACY_CMD`（旧命令名残留，CHANGELOG 历史除外）· `PROFILE_DOC`（覆盖率口径硬编码）

- 零硬依赖：`pyyaml` 缺失时降级为 **UNPROVEN**（不假装通过），符合 `UNPROVEN ≠ PASS`
- 用法：`python scripts/check-release-consistency.py [root1] [root2] ...`
- 首跑即抓到一个自检 bug 并修复：**无 pyyaml 降级路径把命令数解析为 0 → 假 BLOCK**；
  改为按 `commands:` 实际缩进解析；扫描边界补充「不扫入嵌套 git 仓库」（别人的地盘不归本扩展管）

### Fixed — 发布前一致性 cleanup（10 → 14 项）

| # | 问题 | 修复 |
|---|---|---|
| 1 | 工作区根目录是 **v1.1.2 陈旧快照**（6 个 `speckit.sct.*`，引用的 `commands/*.md` 根本不存在） | 根目录 README / extension.yml / catalog-entry.json 对齐 v2.x 真源 |
| 2 | README 残留旧命令名 `check` / `codegen` / `sct.*` 与 "the 6 commands are manual by design" | 全部更正为 `testing.design` / `testing.run` 与 3 命令 |
| 3 | README 称 "zero hooks"，但 extension.yml 声明了 `after_plan` hook | 改为「3 commands + 1 optional hook」，并说明 hook 只*建议*生成测试计划 |
| 4 | README 一处未整理的编辑草稿混入正文章节 | 删除，改写为正式的「时序（重要）」说明（计划→立即 design→编码→run） |
| 5 | `catalog-entry.json` 写 `"hooks": 0`，与 extension.yml 的 1 个 hook 不符 | 改为 `1` |
| 6 | README 通篇硬编码「coverage ≥ 90%」，代码已支持 `--profile fast/standard/strict` | 门禁章节改为 profile 驱动，补三档阈值表（70/90/95） |
| 7 | 术语 `SoT` 在 v1.2.0 已正名为「测试计划（test plan）」，两节未跟上（14 处） | 全文统一为 test plan / contract-anchored |
| 8 | `extension.yml` 与 `catalog-entry.json` 描述与 tags 不一致（"scenario cases" vs "…only"；catalog 缺 `ai-assisted`/`methodology`） | 两处 description 与 tags 完全对齐 |
| 9 | `spec-kit-sct/`（发布包）与 `spec-kit-main/extensions/sct/`（仓库副本）**内容分叉**：<br>commands/ 三个命令文件、templates/ 六个模板均落后一版；文档集互有缺失 | 以 `spec-kit-sct`（09-04 09:27，较新）为准全量同步，两处文件集与内容完全一致 |
| 10 | README 引用 `./ROADMAP.md`，但发布包内无此文件 | ROADMAP.md 纳入发布包，补齐文档集 |
| 11 | 各文档门禁表 gate id 停在 **v1.1.3**（`NO_MISSING` / `TEST_EXECUTION` / `ARTIFACT_INTEGRITY`…），<br>与 v2.1 代码里的四维 id（`REQUIREMENT_COVERAGE` / `EXECUTION_RESULT` / `EVIDENCE_COMPLETENESS` / `TEST_INTEGRITY`）不一致 | README / `testing.run` 命令文档 / 介绍材料 / 手册 / 报告模板统一为「维度 × 五证据项」表，与报告 §1 输出对齐 |
| 12 | `testing.run` 命令描述与 extension.yml 仍写「coverage ≥90%」；介绍材料 / 手册多处硬编码 90% | 全部改为 profile 驱动口径（fast 70 / standard 90 / strict 95），命令文档补 `--profile` 参数说明 |
| 13 | README「中文简介」与方法论首段仍自称 **test-domain extension / 测试域扩展** | 统一为「verification kernel（验证内核）」，与顶部 Kernel 定位一致 |
| 14 | `docs/methodology-assessment.md` 停在 v2.1.0，与 Step 0「方法论统一 Kernel 叙事」宣称不符 | 追加第八节 v2.2.0 回访：收敛后三原则复核 + 第六节建议落地回访 + 风险更新 |

> **遗留项（未处理，需人工决策）**：`spec-kit-main/presets/sct/` 仍存在
> （`preset.yml` + 四个 override 命令），但 v1.1.2 已声明删除 preset 产物。
> 另 `spec-kit-main/extensions/sct/scripts/python/{sct_hooks.py, run_sct_hooks.py}`
> 为 v1.0.1 已声明删除的 dead code（全仓无引用）。二者位于上游仓库副本内，未擅自删除。

## [2.1.0] - 2026-09-04

### Added — P0 全部落地（Contract + Traceability + Evidence + Gate）

**P0-1 Contract**：`acceptance.yaml` 从「yaml.safe_load 就读进来」升级为标准契约
- 新增 `templates/acceptance-schema.json`（契约 JSON Schema：版本/ID 格式/字段约束）
- 新增 `scripts/contract-validate.py`（零依赖确定性校验：结构 + ID 唯一性 + ID 格式 + 完整性提示，
  三态 PASS/BLOCK/UNPROVEN）；plan / design / run 三个命令文件已接入

**P0-2 Traceability**：报告新增固定章节「需求追溯矩阵（REQ → AC → TEST → EXECUTION → EVIDENCE）」——
每条契约条目（API/RULE/SCENARIO）追溯到测试、执行结果与证据状态（含 Java 单测 `<Class>Test.java` 识别）

**P0-3 Evidence**：门禁重构为**四维证据**：需求覆盖 / 执行结果 / 证据完整性 / 测试完整性，
终端摘要与报告均按「维度 × 证据项」展示

**P0-4 Quality Profile**：`--profile fast(70%) / standard(90%) / strict(95%)` 替代硬编码 90%，
strict 档把意图缺失视为 BLOCK

### Added — P1 自测 + golden fixtures（scripts/self-test.py）

- 三档回归：golden（合法契约全链路 PASS）/ blocker（重复 ID 契约被拒）/ gate（漏测契约可跑）
- 已捕获并修复 2 个真实缺陷：① manifest 记录 Java 单测只记文件名（带包路径找不到 → 误 BLOCK），
  改为记录相对 out_dir 路径；② 追溯矩阵不识别 Java 单测（有 target 的规则误判漏测），
  新增 java_tests 收集 + `<Class>Test.java` 匹配

### Fixed

- 代码减法阶段误删函数的风险点已在自测中覆盖（golden 链路兜底）

### Docs

- ROADMAP：P0 四件事标 ✅，P1 自测 ✅ + 两个架构重构标 ⏸ 设计预留（如实标注，不假装完成）
- 方法论评估：新增 `docs/methodology-assessment.md`（v2.1.0 对照 2.0 目标的完整评估）

## [2.0.0] - 2026-09-04

### Changed — SCT 2.0 定位升级：Spec → Test → Evidence → Quality Gate

一句话：**不追求"生成更多测试"，而是用最少的测试和最可信的证据，证明 Spec 被正确实现。**

- 架构主线：`Spec Kit → Acceptance Contract → Test Design → Evidence → PASS/BLOCK/UNPROVEN`
- 确立**三大不可妥协原则**并写入所有文档：① Oracle Independence（期望只来自 Spec/Contract）
  ② Write-once + Integrity（不得反复改测试直到通过）③ PASS/BLOCK/UNPROVEN（证据不足不放行）

### Changed — `testing.cases` → `testing.design`（测试设计 + 制定任务）

- 命令语义升级：不再只是"派生测试"，而是**测试设计 + 制定任务**——把契约变成测试设计
  （每层测什么、怎么测、哪些可执行、哪些需人工补），可调用项目 skill 池提升设计质量，再派生 write-once 案例
- 命令文件重写：`speckit.testing.design.md`；README / 手册 / 介绍材料 / extension.yml / catalog 同步
- 明确"测试计划生成后 → 立即 design；代码实现后 → run"的时序

### Changed — 跳过开关统一命名

- `--skip-rules` → `--skip-unit-tests`（统一为 `--skip-unit-tests` / `--skip-api-tests` 两层跳过）

### Added — ROADMAP.md

- 记录 2.0 八大优化方向（含状态）、三大特色、最小追踪链路（REQ→AC→TEST→EXECUTION→EVIDENCE）、
  优先级建议（P0 = Contract + Traceability + Evidence + Gate）

### Docs

- README / 手册 / 介绍材料更新为 2.0 定位；命令表统一为 Plan / Design / Run 三命令

## [1.5.0] - 2026-09-03

### Removed — 代码减法：删掉两个"五目标之外"的功能（净删 214 行）

按用户明确指令做减法，删除与五个核心目标（不漏测/需求实现/可审核报告/三层覆盖/硬门禁）
无关的过度扩展：

- **非 HTTP 适配器**（`gen_non_http_tests` + `check_non_http_consistency` + `extract_non_http_annotations`
  + `MISSING_NON_HTTP_IMPL` 漂移类型 + `--non-http` 参数 + 模板 `non_http_interfaces` 段 + `sct_ids.non_http_test_filename`）
  ——接口层保持"协议无关"的**文档定位**，但不再维护独立的非 HTTP 测试桩生成与扫描
- **变异测试**（`check_mutation` 函数 + `--mutation`/`--mutation-score`/`--mutation-threshold`/`--skip-mutation`
  参数 + `MUTATION` 检查项）——`sct.verify` 保留幻影检测/编译门/真实测试计数三态

影响：已含 `non_http_interfaces` 段的 SoT 不再生成非 HTTP 桩（该段被忽略，不报错）。

## [1.4.0] - 2026-09-03

### Added — 测试计划 hook 自动触发（`after_plan`）

- `extension.yml` 新增 `hooks.after_plan` → `speckit.testing.plan`（`optional: true`）：
  `specify plan` 完成后自动提示生成测试计划草稿，用户可跳过；生成后始终可人工补充调整。
  这是 SCT 唯一的生命周期集成点，其余命令仍手动、非侵入

### Added — `testing.run` 报告扩展为统一详尽的测试报告

- 报告新增 **「测试报告产物索引」**（报告开头）：串起本次测试流全部产物——
  本报告 / 测试计划 / 变更影响分析 / 覆盖映射 / 功能测试案例 / Playwright 脚本 / 场景未实现清单
- 报告新增 **「6.4 缺陷汇总」**：整合执行失败（junit FAIL/ERROR）+ 漂移（HIGH/MEDIUM）+
  未实现，统一成带「缺陷单」列的缺陷清单供人工跟进
- 报告标题更新为「一致性 × 覆盖率 × 执行情况 × 缺陷 × 变更影响」

### Changed — 功能测试案例结构化字段补全（`E2E_TESTCASES.md`）

- 案例字段对齐测试行业标准，新增/重命名：
  **案例编号 / 案例类型（正例·反例）/ 案例优先级 / 案例意图 / 前置条件 / 测试步骤 / 预期结果**
- 新增 `case_type` 判断：SoT `e2e.case_type` 显式指定优先，否则启发式（then 文本含
  「拒绝/失败/报错/错误/异常/不允许/无权限…」→ 反例，否则正例）
- 执行汇总表新增「案例类型」列

## [1.3.0] - 2026-09-03

### Changed — 命令体系精简 6 → 3（`speckit.sct.*` → `speckit.testing.*`）

按"测试计划 → 测试案例 → 测试执行"三阶段重组命令，命名直接表达用途：

| 旧命令 | 新命令 | 说明 |
|---|---|---|
| `sct.merge` + `sct.impact` | **`testing.plan`** | 测试计划 = 合并 + 变更影响定级 |
| `sct.codegen` + `sct.e2e` | **`testing.cases`** | 测试案例 = 三层派生 + e2e 场景 |
| `sct.check` + `sct.verify` | **`testing.run`** | 测试执行 = 门禁 + 报告 + 有效性验证 |

- 删除 3 个命令文件（`speckit.sct.impact/e2e/verify.md`），能力通过参数与新命令文档暴露；
  底层脚本不变（`spec-merge.py` / `change-impact.py` / `acceptance-codegen.py` /
  `change-impact-e2e-bridge.py` / `consistency-check.py` / `verification-gate.py`）
- `extension.yml` / `catalog-entry.json`：commands 6→3，description/tags 更新

### Changed — 测试计划输入扩展到 plan 产物

- `testing.plan` 明确从 **spec.md + plan.md + data-model.md + api-contracts.md** 自动生成，
  不再是"只从需求派生"；位置明确为 `specify plan` 之后

### Changed — 接口层协议无关

- 接口层从"HTTP 接口测试"改为"契约测试（protocol-agnostic）"：测试计划声明*要验证什么*，
  emitter 决定*怎么驱动*（默认 HTTP），不把 HTTP 写死进方法论与文档

### Docs

- 重写三个命令文件（`speckit.testing.{plan,cases,run}.md`）
- README 命令表 6 行→3 行；快速开始按三阶段重排
- 手册第四部分重组（4.1~4.3 主命令 + 4.4/4.5/4.7 标为"已并入"子步骤）
- `SCT介绍材料.md` 同步三命令与协议无关表述

## [1.2.0] - 2026-09-03

### Changed — 方法论重构：从"一致性理论"回归"测试域扩展"

上一版（v1.1.x）累积了 10 节方法论、8 类漂移归因、前向保证链等重理论，维护性差且偏离实际需求。
本次按五个实际目标重构，砍掉理论包袱：

- **定位重述**：SCT = spec-kit 的**测试域扩展**，不是新真相源理论。`spec.md` 是需求来源，
  `acceptance.yaml` 是**测试计划**（派生投影）。README 方法论从 10 节精简为 5 节（不漏测 / 需求实现 /
  可审核报告 / 三层覆盖 / 硬门禁），篇幅减半
- **语言中立**：明确 Java/JUnit 只是**默认 adapter**，测试计划格式、覆盖率门禁、报告均与语言无关，
  emitter 可插拔。README 与手册新增"Language neutrality"章节

### Changed — 门禁标准收紧

- **增量行覆盖率门禁 80% → 90%**（`line_coverage_target`；命令文档与 `docs/unit-test-standards.md` 同步）
- 门禁表述统一为"覆盖 ≥90% + 案例 100% 通过 + 无漏测无未实现"，非 0 退出码即阻断

### Added

- `SCT介绍材料.md`：中文一页纸介绍材料，供内网团队培训与技术评审使用——
  是什么 / 解决五个问题 / 怎么工作 / 四条铁律 / 门禁标准 / 快速上手 / FAQ / 与其他实践的关系

### Docs

- 手册第一部分重写：1.1 定位、1.2 五个目标表、1.3 三条铁律、1.3.1 语言中立、1.3.2 概念速查；
  全文术语统一（SoT / 测试契约 → 测试计划）

## [1.1.3] - 2026-09-03

### Fixed — P0 级：让 README 宣称的不变量真正被代码强制（外部源码审查响应）

- **P0-2 `sct.check` 三态门禁**：最终判定从临时布尔（`p0_fail = high or api_fail>0`）改为结构化证据模型——
  `NO_HIGH_DRIFT` / `LINE_COVERAGE`（≥80% 真阻断，不再只打印）/ `TEST_EXECUTION`（覆盖全部生成测试，
  不再只看 `test_api_` 前缀）/ `GENERATED_ARTIFACT_INTEGRITY`，每项独立判 PASS/BLOCK/UNPROVEN，
  整体取最严；退出码对齐 `sct.verify`：PASS=0 / BLOCK=1 / UNPROVEN=2（预检确认跳过仍为 3）
- **P0-3 场景/非 HTTP/规则无锚点桩**：`pytest.fail` → `pytest.skip(reason="UNPROVEN: ...")`——
  "无可执行 adapter/环境"是证据不足（UNPROVEN），不是行为违约（BLOCK）；消除 check 第一步 pytest 全跑结构性必红。
  场景 gap 另落机器可读产物 `_scenario_gaps.json`（status/reason/required_adapter）
- **P0-5 write-once 真强制**：`_codegen_meta.json` 新增 `generator_version` + `expected_outputs`（每个生成文件 sha256）。
  缓存命中条件从"存在任意 test_*.py"改为 manifest 完整匹配——手改/删文件/生成器升级全部击穿缓存重新生成；
  `sct.check` 新增 `GENERATED_ARTIFACT_INTEGRITY` 证据项，手改即 BLOCK 并给出 `--force` 恢复路径
- **P0-4 canonical ID 层**：新增 `scripts/sct_ids.py`（`id_suffix`/`safe_slug`/文件名与函数名换算），
  消除四个脚本散落的 `split("-")`；修复报告渲染中 JUnit 结果关联仍用中段（`split("-")[1]`）导致多段 ID
  （`API-F003-001`）执行结果永远关联不上的残留 bug

### Changed — 方法论重定位：独立测试流，不动 spec-kit 骨架

- `acceptance.yaml` 从"唯一真相源（SoT）"正名为**测试契约（test contract）**：`spec.md` 仍是需求真相源
  （spec-kit 骨架所有，SCT 不碰），acceptance.yaml 是测试域的派生投影——派生关系，非平行关系
- README 方法论章节新增"测试流四阶段"框架：**测试计划**（merge+impact）→ **测试案例**（codegen）→
  **测试执行**（check+e2e）→ **测试覆盖**（check 覆盖段+verify），命令名不变

## [1.1.2] - 2026-09-03

### Removed — 取消 preset 产物（社区目录只收录扩展）
- 删除 `presets/sct/preset.yml` 及 `presets/sct/commands/` 下四个 override 命令文件（`speckit.specify`/`plan`/`implement`/`constitution`）
- `catalog-entry.json` 删除 `provides.presets` 段（含 path 引用 + overrides 列表）；README 移除 Companion preset 章节与"the companion preset"提及，匹配社区目录只接受扩展的口径
- 行为零变化：`extension.yml` 早已不依赖 preset；新用户只看扩展即可

## [1.1.1] - 2026-09-02

### Added — README 方法论详解章节（社区展示 + 内网研读）
- 新增 **Methodology** 大章节（README 第 13 行起，含中文简介与 Mermaid 流水线图）：
  1. 要解决的问题（spec/code/test 三方漂移）
  2. SoT 唯一真相源
  3. 前向保证链 vs 传统"事后修补"对比表
  4. write-once 派生测试 + "断言永不来自代码"（反推断言 = 自己出题自己改卷）
  5. 8 类漂移归因表（断掉的是哪一环）
  6. check 是确认门不是补救兜底
  7. 分级闸门 L1/L2/L3（token 按风险花）
  8. 测试存在性 ≠ 测试有效性（sct.verify 三态，UNPROVEN ≠ PASS）
  9. 与 TDD / BDD / 覆盖率工具 / LLM 审查的定位对比表
  10. SCT 要消灭的 6 种反模式
- 顶部简介区加中文一句话定位；删除旧的 ASCII 流程图（由 Mermaid 替代）

## [1.1.0] - 2026-09-02

### Added — `sct.verify` 测试有效性验证门（补上"测试真能抓住 bug 吗"的实质缺口）

借鉴社区扩展调研结论（TDD Extension 变异测试 / Golden Demo 行为 oracle /
Vurnix Honest Gate / Verify Tasks 幻影检测），新增第 6 个命令：

- **`scripts/verification-gate.py`** + **`commands/speckit.sct.verify.md`**
- **PHANTOM_TASK 幻影检测**：tasks.md 标 `[X]` 的任务在代码中找不到类名/方法名证据
  → 抓"声称做了实际没做"；与 `sct.check` 的 `MISSING_IMPL` 反向互补
- **COMPILE 编译门**：自动探测 pom.xml / build.gradle 并执行测试编译
  （`mvn -DskipTests test-compile` / `gradle compileTestJava`），抓"生成了但编译不过"
- **REAL_TESTS 真实测试计数**：读 surefire `TEST-*.xml` 实际执行数，
  抓"声称有测试但实际执行 0 个"
- **MUTATION 变异强度（可选）**：PITest `mutations.xml` 变异得分（或
  `--mutation-score` 直接给分，兼容 mutmut 等），低于阈值（默认 60%）→ BLOCK
- **诚实三态输出**：`PASS` / `BLOCK` / `UNPROVEN`（退出码 0/1/2），
  整体取最严（BLOCK > UNPROVEN > PASS）——**UNPROVEN ≠ PASS**，
  没验证就不许冒充通过；内网无 Maven/surefire 时明确提示而非静默放行

### Added — 社区目录提交元数据
- extension.yml / catalog-entry.json 增加 `category: process` + `effect: read-write`
  （spec-kit 社区目录必需字段）
- 命令数 5 → 6；catalog tags 增补 verification / mutation-testing

## [1.0.6] - 2026-09-02

### Fixed — 移植 ai-test-platform 实战（sct-improvements.md F-1~F-20）全部问题

**命名冲突（阻塞级，同 feature 多 API/多规则不再互相覆盖）**
- F-2：API 测试文件名 `split('-')[1]` → `[-1]`，`API-F003-001~006` 生成
  `test_api_001.py`~`test_api_006.py`，不再全部落成 `test_api_f003.py`
- F-5：规则测试方法名 `split("-")[1]` → `[-1]`，`test_br_001/002/003` 不再重名
  （pytest 只跑最后一个同名函数的 bug 消除）
- 连带修复：consistency-check 的 API/规则匹配口径同步为**按 ID 末段**匹配
  （`API-F003-001` ↔ `test_api_001.py`；`BR-F003-001` ↔ `test_br_001`），
  API/规则覆盖率不再虚高或归零

**数据正确性**
- F-3：`render_api_test` 兼容两种 response schema——
  新规范 `response_200.fields` + `error_codes: [400,...]`、旧规范
  `response.success/errors`，成功/异常用例都能生成；报告计数同步
- F-7：COVERAGE_REPORT 场景覆盖列改为**扫描实际生成的测试函数数**
  （`scan_generated_scenario_funcs`），不再用 `len(scenarios)` 自欺欺人
- F-8：规则覆盖列用与生成代码一致的函数名（`test_br_{末段}`），报告与代码对得上
- F-1：spec-merge 识别 Speckit 编号 G/W/T 列表（`1. **Given**` 形式），
  编号 Given 自动分隔新场景；兼容器 bullet 与加粗续行

**e2e bridge 扩展（F-13/F-14/F-15/F-16）**
- F-13：action 支持 `upload_file | click | double_click | double_click_node |
  fill | navigate | batch_confirm_nodes`（其他 type 仍 TODO 占位）
- F-14：assertion 支持 `ui_message | ui_visible | url_contains`
- F-15：`--include-p2` 参数，无 impact 文件时可选包含 P2 场景（默认仍 P0/P1）
- F-16：`pre_steps` inline flow 含 `?`（如 `[login, navigate:/x?y=1]`）自动拆
  block 序列解析，解析失败给出 block 写法提示

**多模块 + 非 HTTP（F-17/F-18/F-19/F-20，W4 新功能移植）**
- F-17：consistency-check 支持 `--module`（默认 `{code}/{module}/src/main/java`）
  与 `--module-src`（源码不在 src/main/java 时覆盖）
- F-18：consistency-check `--non-http` 扫描 `@RabbitListener/@KafkaListener/@Scheduled`
  与 SoT `non_http_interfaces` 比对，缺适配器报 `MISSING_NON_HTTP_IMPL`（HIGH）
- F-19：codegen 支持 `--module`（输出隔离到 `{out}/{module}/`）与 `--non-http`
  （生成 `test_non_http_*.py` 测试桩）
- F-20：`templates/acceptance-template.yaml` 新增 `non_http_interfaces` 段示例
  （RABBIT_LISTENER / KAFKA_LISTENER / SCHEDULED）

## [1.0.5] - 2026-09-02

### Fixed — 生成代码全面 JDK 8 兼容（内网主流 JDK 8 可直接编译）
- Act 段不再写 `var actual = ...`（Java 10+ 语法），统一 `Object actual = ...`，
  任意返回类型均可编译（已用 `javac --release 8` 验证）
- 集合输入不再用 `List.of` / `Map.of`（Java 9+ API），改用
  `java.util.Arrays.asList(...)` / `java.util.Collections.emptyList()` / `emptyMap()`
- 集合形参（`List<...>`、`Map<...>` 等 java.util 常见类型）自动补 `import java.util.*`，
  修复"形参用了 `List` 却没 import"导致的编译失败
- 同步更新：`unit-test-standards.md` 移除"等 --java-target 8"的待办说明，
  README 示例改为 `Object actual`

### Added — `sct.e2e` 两个消费路径说明
- 命令文件新增 Step 3.1：路径 A（Playwright 直接回归，需本机装 Playwright）vs
  路径 B（AI 测试平台消费 `_intent_tests.json`，本机无需装 Playwright）
- 明确 SCT e2e 是"生成器不是执行器"：内网没装 Playwright 不影响走 e2e 桥

## [1.0.4] - 2026-09-01

### Added — `sct.codegen` 独立开关 + `sct.check` 接口层预检
- **`--skip-rules` / `--skip-api-tests` / `--only-rules`** on `acceptance-codegen.py`:
  - `--skip-rules`：纯 API-only 项目，只生成 `test_api_*.py` + `conftest.py`
  - `--skip-api-tests`：纯库/工具项目，只生成规则/单测
  - `--only-rules BR-001,BR-002`：定向再生成指定 rule（配合 `--skip-api-tests` 用）
  - 这三层彼此**独立可选**——按项目类型选最合适的组合
- **`--skip-api-tests` / `--skip-rule-tests` / `--prereq-timeout`** on `consistency-check.py`:
  - 跳过对应测试层；预检失败时不再让 pytest 跑出无意义的红
- **`preflight_api_tests`** 在 `sct.check` 起跑前探测：
  - `BASE_URL` 可达性（HEAD，超时默认 3s，可调）
  - `API_AUTH_TOKEN` 存在性（提示用，不强制）
  - **不可达且无 token** → 退出码 **3**，打印结构化诊断给 agent，
    让用户在对话框确认「修环境再跑 / 跳过接口层（`--skip-api-tests`）」
  - **可达** → 继续正常 pytest

### Changed
- `acceptance-codegen.py` 在生成接口测试前会提示「base_url 用默认值」+ 给出运行所需环境变量（一次性提醒，非阻塞）。
- 内网手册同步更新：依赖表 + 新增「跳过开关与预检」章节。

## [1.0.3] - 2026-09-01

### Fixed — API tests were actually broken in three concrete ways
- **GET requests sent `payload` as a JSON body** instead of as query parameters.
  Generated `test_api_*.py` used `requests.{method}(url, json=payload)` for every method,
  so every GET test ran against the server with the query string empty — Spring's
  `@GetMapping` reads from `params`, not body. Fixed: GET now uses
  `session.get(url, params=payload)`; all other methods use `session.request(method, url, json=payload)`.
- **No authentication header.** Generated tests had no `Authorization` and went straight
  to `401` on any bank-internal API. Fixed: codegen now writes a `conftest.py` next to
  `test_api_*.py` with a `session` fixture that reads `API_AUTH_TOKEN` (Bearer token) from
  the environment — no token, no header (open API / local dev still works).
- **No way to override `BASE_URL` per environment.** It was hardcoded as the
  codegen-time default (or came only from codegraph). Fixed: resolution order is now
  CLI `--base-url` > env `BASE_URL` > `codegraph.project.base_url` > `http://localhost:8080`,
  and the actual `BASE_URL` lookup happens in conftest at pytest start — no regeneration
  needed when switching CI / staging / local.

### Added — `conftest.py` is now generated by codegen
- One file per `tests/generated/` directory, providing:
  - `s.base_url` read from env `BASE_URL` (with default fallback)
  - `s.headers['Authorization']` set from env `API_AUTH_TOKEN` (Bearer prefix; header name
    customizable via env `API_AUTH_HEADER`)
  - `Connection: close` to surface connection errors immediately
- Generated `test_api_*.py` takes `session` as a parameter and uses `session.base_url`,
  `session.headers` — no module-level `BASE_URL` constant.

### Changed
- `--base-url` CLI argument added to `acceptance-codegen.py` (see resolution order above).
- README / unit-test-standards now list `requests` as a required Python dep for running
  API tests: `pip install requests pytest`.

## [1.0.2] - 2026-08-31

### Fixed — `sct.merge` and `sct.e2e` commands were empty
- The two command files shipped in the extension (`commands/speckit.sct.merge.md`,
  `commands/speckit.sct.e2e.md`) were **empty since v1.0.0**, so invoking
  `/speckit.sct.merge` or `/speckit.sct.e2e` from an agent produced no effect even though
  the underlying scripts (`spec-merge.py`, `change-impact-e2e-bridge.py`) worked. Both
  commands are now fully written.

### Added — `speckit.sct.merge`
- Guided SoT build: input collection table, `coverage_mode` / `test_timing` decision, and
  the exact `spec-merge.py` invocation.
- **Re-merge safety**: warns that re-running merge overwrites an existing
  `acceptance.yaml` and instructs writing to a temp path + diffing so hand-enriched
  fields are not silently lost.
- **SoT completeness self-check**: requires reporting the counts of scenarios with full
  given/when/then, APIs with request+errors, and rules carrying `target` + `test_cases`
  vs `checks` — so a SoT that cannot produce executable tests is surfaced immediately
  instead of implying full coverage.

### Added — `speckit.sct.e2e`
- **L3-only gate**: reads `变更级别` from `change-impact.md`; L1/L2 stop with a notice.
- Documents the `e2e:` scenario block schema (W1 scope: `upload_file` action,
  `ui_message` assertion, `pre_steps`), the `e2e/fixtures/` path convention, and all four
  artifacts (`<id>.spec.js`, `E2E_TESTCASES.md`, `_intent_tests.json`, `_summary.json`).
- Requires reporting **in-scope scenarios without an `e2e:` block** as explicit coverage
  gaps, and states that generated specs are **not** runnable-as-is (selector / text review
  + `// TODO` for unsupported action or assertion types).

## [1.0.1] - 2026-08-28

### Added — Java unit tests now follow the classic AAA pattern
- Generated JUnit tests use the **Arrange / Act / Assert** structure with a
  `@DisplayName` intent annotation (JUnit 5) describing the rule, inputs, and expected
  result — matching hand-written unit-test conventions.
- **Signature-bound generation.** When `--code` is given, `codegen` parses the target
  method's **public signature** to bind SoT inputs to parameters (by name, else position)
  and to auto-detect collaborators for `@Mock`. Spring is never used
  (`MockitoExtension` on JUnit 5, `MockitoJUnitRunner` on JUnit 4). The code body is never
  read, so assertions cannot be reverse-engineered from the implementation.
- **SoT-anchored mock stubs.** A new `given` list on a `test_case` emits
  `when(collaborator.method()).thenReturn(value)` in Arrange, so collaborator behavior is
  pinned by the requirement rather than the mock's default. Without `given` on a mocked
  dependency, a `MOCK_NOT_STUBBED` drift is raised.
- **`BINDING_DRIFT` divergence signals.** When the SoT and code disagree, codegen emits a
  structured drift (also in `_codegen_meta.json` and the coverage report) instead of a
  confusing failure: `METHOD_NOT_FOUND`, `MISSING_INPUT`, `UNCONSTRUCTABLE_ARG`,
  `MOCK_NOT_STUBBED`. Each points to the exact element a human must adjudicate.
- **UTF-8 Chinese output.** Generated `.java` files may carry Chinese `@DisplayName` /
  comments; documented the `javac -encoding UTF-8` / Maven `sourceEncoding=UTF-8`
  requirement (supersedes the earlier ASCII-only hardening — the test is now readable and
  still compiles under UTF-8).

### Changed
- The assertion-authority note in generated tests now reads: *the test is the alarm, not
  the verdict* — when it fails, escalate to a human (code wrong → fix code; SoT wrong →
  fix SoT and regenerate). It no longer asserts tests must never be edited to please code;
  the correct action is to resolve the divergence at its source.
- Removed the dead `scripts/python/sct_hooks.py` and `run_sct_hooks.py` (leftover from the
  pre-non-intrusive draft; `extension.yml` declares no hooks, so they were never loaded).

## [1.0.0] - 2026-08-27

### Added
- `speckit.sct.merge` — generate `acceptance.yaml` (single source of truth) from
  spec / plan / data-model / api-contracts, with `--ai` LLM auto-extraction.
- `speckit.sct.codegen` — derive write-once unit/e2e tests from the SoT.
- `speckit.sct.check` — three-way spec ↔ code ↔ test consistency check with
  detailed human-review report (JaCoCo incremental coverage, API execution,
  rule verification, change-point audit), and `--ai` semantic drift analysis.
- `speckit.sct.impact` — reverse-trace code changes to affected spec scenarios
  (P0/P1/P2) with an L1/L2/L3 tier decision; runs after implementation.
- `speckit.sct.e2e` — bridge change-impact + SoT into Playwright auto-regression.
- (Non-intrusive) SCT registers **no lifecycle hooks** — the 5 `speckit.sct.*`
  commands run manually after implementation; the original `specify/plan/
  implement` flow is untouched. (An earlier draft wired `after_implement` /
  `after_plan` / `after_e2e` hooks, but that was dropped so SCT never affects
  the base Spec Kit flow.)
- Optional `codebase-memory-mcp` integration for enriched impact reverse tracing.
- Brownfield incremental mode, CodeGraph-driven request enrichment, full
  exception-value coverage, and multi-dimensional impact matching.

### Changed
- `test_rules.py` is no longer an empty skeleton: each business rule is now
  generated as an **offline static assertion** that verifies the rule has a
  corresponding piece of evidence in the code (annotation / method / exception /
  constant). Rules can carry a `checks` list in the SoT for precise assertions;
  anchorless rules fail clearly instead of being silently skipped.
- `test_scenarios.py` now fails with a clear pointer (API / E2E layers) instead of
  a false-green `NotImplementedError`.
- `speckit.sct.codegen` accepts `--code` (code root for rule assertions, default
  `backend/src/main/java`); override at runtime with env `SCT_CODE_ROOT`.

### Non-intrusive redesign
- **Removed all lifecycle hooks.** `extension.yml` no longer declares
  `provides.hooks`. SCT never alters the original `specify / plan / implement /
  constitution` flow — the 5 `speckit.sct.*` commands are invoked **manually by
  the user after implementation**; nothing auto-fires. This honors the principle
  that test steps (merge / codegen / check / impact / e2e) wait until after
  implementation and are executed only when the user confirms.
- The companion preset (`presets/sct/`) is now **hint-only**: its overrides of
  `speckit.specify / plan / implement / constitution` append optional SCT
  methodology reminders but never auto-run an SCT command and never change the
  original command behavior.

### Hardened — unit tests are SoT-anchored (anti code-bias)
- Generated Java unit tests now carry an inline **assertion-authority comment**
  citing `acceptance.yaml#rules[<id>]` as the sole source of truth, explicitly
  stating the expectation comes from the requirement, not the implementation, and
  must fail (not be edited to please code) if the implementation deviates.
- `gen_java_unit_tests` documents that it reads only `rule.target / mocks /
  test_cases` and never opens the code body to synthesize assertions — the unit
  test is derived from the SoT, the code is a black box under test.
- The assertion-authority comment is emitted in ASCII (English) so generated
  `.java` files compile under a default (GBK) Windows `javac` without `-encoding
  UTF-8`.
