# Changelog

All notable changes to the SCT extension are documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

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
