# SCT 内网实践操作手册

> 版本：v2.3.0（对应 spec-kit-sct 发布包。**v2.2.0 定位收敛为 Verification Kernel（验证内核）**：SCT 只自有 Evidence Contract / Traceability / Gate 三件事，测试生成（JUnit / HTTP / E2E / Golden / BDD）全部归 Adapter，adapter 只产出证据、**裁决权不下放**；命令名 `speckit.testing.*` 保持不变。历史：v1.0.4 独立跳过层与预检退出码 3；v1.0.5 JDK 8 兼容；v1.0.6 实战问题全修；v1.1.0 新增有效性门；v1.1.2 移除 preset；v1.1.3 check 三态证据门禁；v1.2.0 方法论重构 + 覆盖率门禁 90%；v1.3.0 命令精简 6→3；v1.4.0 after_plan 钩子 + 统一报告 + 案例正反例；v1.5.0 代码减法；**v2.0.0** 定位升级 Spec→Contract→Test→Evidence→Gate + 三大原则 + `testing.cases`→`testing.design`；**v2.1.0** P0 四件事落地（Contract Schema + 追溯矩阵 + 四维证据 + Quality Profile）+ self-test golden 回归；**v2.2.0** 架构文档 `docs/verification-kernel.md` + 发布前一致性 cleanup 14 项 + 自检脚本 `scripts/check-release-consistency.py`；**v2.3.0** 防空洞收编：Gate 可选「测试有效性」维度（`--surefire`→REAL_TESTS / `--tasks`→PHANTOM_TASK / `--verify-compile`→COMPILE），adapter 目录化触发式搁置，self-test 四档）  
> 适用对象：内网试点项目组成员  
> 宿主 Agent：**opencode**（离线部署，模型走内网网关）  
> 前置阅读：无需了解 spec-kit 源码，会用命令行即可

---

## 第一部分 方法论简介

### 1.1 SCT 是什么

SCT 是 **spec-kit 的验证内核（Verification Kernel）**。它不改骨架、不造新的真相源、不绑定语言，只做一件事：

> **用最少的测试和最可信的证据，证明 Spec 被正确实现。**

```text
Spec Kit（需求，骨架所有）
   ↓
Acceptance Contract  acceptance.yaml（需求与测试之间的标准契约）
   ↓
Test Design         testing.design（测试设计 + 制定任务，可调用 skill 池提升设计质量）
   ↓
Evidence            testing.run（执行结果 + 覆盖率 + 缺陷 + 漂移）
   ↓
PASS / BLOCK / UNPROVEN（质量门禁）
```

**三条不可妥协的原则**：

| # | 原则 | 含义 |
|---|---|---|
| ① | **Oracle Independence** | 期望结果只来自 Spec/Contract，**绝不来自 Code**（反推断言 = 自己出题自己改卷） |
| ② | **Write-once + Integrity** | 可以生成测试，但**不能反复改测试直到通过**（sha256 manifest 强制，手改即 BLOCK） |
| ③ | **PASS / BLOCK / UNPROVEN** | 证据不足不强行判定 PASS（`UNPROVEN ≠ PASS`） |

```text
【spec-kit 主骨架 · 不动】specify → plan → tasks → implement
                              │
                              │  (after_plan 钩子自动提示生成测试计划，可跳过/人工补充)
                              ▼
【SCT 验证内核 · 3 个命令】

  ① 测试计划 testing.plan    spec + plan 产物 → acceptance.yaml（测试契约）+ 变更影响定级
  ② 测试设计 testing.design  契约 → 测试设计 + 制定任务（三层：单测/接口/e2e 场景）
  ③ 测试执行 testing.run     真实执行 + 证据 + 门禁 + 统一报告

     硬门禁：覆盖率 ≥ profile 阈值 · 案例 100% 通过 · 无漏测无未实现 → 非 0 即阻断
     profile：fast 70% / standard 90%（默认）/ strict 95%（`--profile` 指定）
```

### 1.2 SCT 要解决的五个问题（方法论的全部目标）

| # | 目标 | SCT 的做法 | 对应能力 |
|---|---|---|---|
| 1 | **测试不漏测** | 测试契约里每个验收点必须映射到测试，没测试 = 漏测 = 阻断 | `MISSING_TEST` 门禁 |
| 2 | **需求都实现了** | 契约里声明的条目逐一对照代码，声明了但没实现 = 阻断 | `MISSING_IMPL` 门禁 |
| 3 | **输出真正的测试报告** | 需求 × 代码 × 测试矩阵 + 执行结果 + 覆盖率 + 漏测清单，人类可审核、可复跑 | `testing.run --report` |
| 4 | **测试手段分层** | 单测（规则/方法）→ 接口（契约/异常码）→ e2e（**只要场景案例**） | `testing.design` |
| 5 | **门禁要阻断** | 覆盖率 < profile 阈值（standard 档默认 90%）、案例非 100% 通过、有漏测/未实现 → 退出码非 0 | 三态门禁 |

### 1.3 三条铁律

1. **断言期望只来自测试计划，绝不从代码反推。**  
   代码是被测黑盒。生成器可以读代码的**公开签名**（参数类型/顺序）绑定输入的"形状"，但输入的"值"和断言的"期望"永远来自测试计划。
   测试跟着代码走 = 代码的错误被测试合法化（自己出题自己改卷）。

2. **测试是 write-once 的：只改测试计划，重新生成，不手改生成的测试。**  
   （由 sha256 manifest 强制：手改会被 `testing.run` 判 BLOCK，且击穿缓存自动重生成）  
   生成的测试失败时禁止把测试改绿来迁就代码——分歧是信号，交人工裁决：代码错了改代码；计划/规格错了改计划再重生成。

3. **UNPROVEN ≠ PASS：证据不足不得冒充通过。**  
   `testing.run`（底层 `consistency-check` / `verification-gate`）均为三态：PASS(0) / BLOCK(1) / UNPROVEN(2)。缺 junit、缺 jacoco 时结论是 UNPROVEN，
   不是 PASS——补齐证据重跑才放行。

> **定位澄清**：`acceptance.yaml` 是**测试计划**（spec 在测试域的派生投影），不是"第二个真相源"。
> 需求改了 → 改 `spec.md` 再 re-merge；测试期望改了 → 直接改 `acceptance.yaml`。派生关系，不是平行关系。

### 1.3.1 语言中立

SCT **不是 Java 工具**。Java/JUnit 只是当前默认的 adapter（因为行内现状如此），
测试计划格式、覆盖率门禁、报告都与语言无关，emitter 可插拔——未来接 pytest / Go test 不需要改方法论。

### 1.3.2 关键概念速查

| 概念 | 文件/位置 | 说明 |
| --- | --- | --- |
| **测试计划** | `specs/{feature}/acceptance.yaml` | 由 spec/plan/契约合并而来的**测试域清单**：apis + rules + 验收场景都登记在这里 |
| **实现契约** | `specs/{feature}/change-impact.md` 的「实现需求」段 | 把本次范围内测试计划条目原文转录，开发对照它写代码，逐条可勾选 |
| **变更分级** | change-impact.md 头部 `**变更级别**: L1/L2/L3` | 控制下游投入多少资源（见 3.2） |
| **测试时序** | 测试计划 `_meta.test_timing: post/pre` | post=代码先行（默认）；pre=测试先行（TDD 变体），两档保证等价 |
| **BINDING_DRIFT** | `_codegen_meta.json` / 覆盖率报告 | 测试计划与代码对不上时的分类信号（见 6.3） |
| **CodeGraph** | `codegraph.json`（可选） | 代码知识图谱导出，让 API 测试从骨架升级为近可执行；**只辅助构造请求，绝不参与断言** |

### 1.4 非侵入设计（对原流程几乎零影响）

- SCT **只注册 1 个生命周期钩子** `after_plan`（v1.4.0 起）：`specify plan` 完成后自动提示
  生成测试计划草稿（可跳过，生成后仍可人工补充调整）；`specify / tasks / implement` 流程完全不变；
- 其余 3 个 `speckit.testing.*` 命令全部**手动执行**，跑不跑、何时跑由人决定；
- 当前发布包**只含扩展**（v1.1.2 起），不含配套 preset。

---

## 第二部分 内网环境准备

### 2.1 依赖清单

| 依赖                    | 版本要求                          | 用途                          | 内网备注                                                                                                                                                                                                                                                 |
| --------------------- | ----------------------------- | --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| specify CLI（spec-kit） | ≥ 0.9.0                       | 扩展安装与命令运行                   | 提前在内网机器装好                                                                                                                                                                                                                                            |
| **opencode CLI**      | 最新                            | 运行 SCT 命令的宿主 Agent          | 内网离线安装；项目需用 `specify init --ai opencode` 初始化（或已有 `.opencode/` 目录）                                                                                                                                                                                    |
| **内网大模型网关**           | —                             | opencode 的 provider baseURL | 在 opencode 配置里指向内网模型网关，**不使用任何外网 API key**                                                                                                                                                                                                           |
| Python                | 3.x                           | 运行 7 个脚本                    | 需在 PATH 中，opencode 通过 bash 工具调用它                                                                                                                                                                                                                     |
| PyYAML                | 任意                            | 脚本依赖                        | `pip install pyyaml`（走内网 pip 源）                                                                                                                                                                                                                      |
| **requests**          | 任意                            | 跑 `test_api_*.py` 必备        | `pip install requests`；codegen 会生成 `conftest.py`，pytest 启动时读 `BASE_URL` / `API_AUTH_TOKEN` 环境变量                                                                                                                                                      |
| JDK + Maven           | **JDK 8（项目主流）/ JDK 17+（新项目）** | 编译运行生成的 JUnit 测试            | **pom 必须设 `<project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>`**，否则中文 @DisplayName 在 GBK 环境编译失败。**v1.0.5 起生成的代码已全面 JDK 8 兼容**：Act 段用 `Object actual`（不再写 `var`），集合用 `Arrays.asList`/`Collections.emptyXxx`（不再用 `List.of`/`Map.of`），集合形参自动补 import；已用 `javac --release 8` 验证可编译。Mockito 用 **4.x**（5.x 要求 JDK 11+） |
| JaCoCo                | 任意                            | 覆盖率门禁数据源                    | 接入试点项目 pom，产出 `target/site/jacoco/jacoco.xml`                                                                                                                                                                                                        |
| pytest                | 任意                            | 运行 Python 侧 API/规则测试        | `pip install pytest`                                                                                                                                                                                                                                 |
| Playwright            | 任意                            | 仅 L3 变更的 e2e 回归             | 可选，不跑 e2e 可不装                                                                                                                                                                                                                                        |
| codebase-memory-mcp   | —                             | impact 反向追溯增强               | **可选**，没有时自动回退 ripgrep 静态扫描                                                                                                                                                                                                                          |

### 2.2 内网限制（先知悉）

- **`--ai` 参数不可用**：它调用外部 SiliconFlow API。内网请勿在 merge/check 上加 `--ai`，去掉后功能完整可用。
- **`--from <url>` 安装方式不可用**：它强制 HTTPS（GitHub）。内网一律走 `--dev` 本地目录安装。

### 2.3 安装步骤（5 分钟）

> 本文以 **opencode** 为宿主 Agent；若用其他 Agent（Claude Code / Cursor 等），仅命令目录不同，其余完全一致。

```bash
# 0.（新项目）用 opencode 初始化 spec-kit，生成 .opencode/ 与 .specify/
specify init <项目名> --ai opencode        # 已初始化过可跳过

# 1. 把发布包整个目录拷进内网（U盘/内网制品库），例如 D:\tools\spec-kit-sct
#    必需内容：extension.yml、commands/、scripts/、templates/

# 2. 在试点项目根目录安装扩展（--dev = 从本地目录安装，无需网络）
#    安装时 spec-kit 会自动识别本项目是 opencode 项目，把命令渲染到 .opencode/commands/
specify extension add D:\tools\spec-kit-sct --dev

# 4. 验证安装
cat .specify/extensions/.registry        # 应看到 sct 条目
ls .opencode/commands/                   # 应看到 speckit.testing.plan.md 等 3 个文件
ls .specify/extensions/sct/scripts/      # 7 个 Python 脚本已就位（含 sct_ids.py 公共层）
```

升级方式：外网改完发布包 → 重新拷目录 → `specify extension add <路径> --dev --force`。

### 2.4 opencode 下命令在哪、怎么调

| 项目     | 位置 / 用法                                                                                                         |
| ------ | --------------------------------------------------------------------------------------------------------------- |
| 命令文件路径 | `.opencode/commands/speckit.testing.{plan,cases,run}.md`（旧版目录为 `.opencode/command/`，spec-kit 会自动兼容） |
| 触发方式   | 在 opencode 输入 `/` + 命令名，例如 `/speckit.testing.plan`、`/speckit.testing.run`；可带参数：`/speckit.testing.design --only BR-001`  |
| 参数占位   | 命令文件内用 `$ARGUMENTS`，opencode 会把 `/` 后面的内容传进去                                                                    |
| 执行位置   | 在**项目根目录**启动 opencode，脚本相对路径（`specs/...`、`tests/generated/`）才能解析                                                |
| 脚本路径   | 安装时 spec-kit 已把命令里的脚本引用改写为 `.specify/extensions/sct/scripts/...`，无需手工配置                                         |

内网模型配置要点：在 opencode 的 provider 配置里把 baseURL 指向**内网大模型网关**，不要配置任何外网 key；SCT 的 3 个命令本身不联网，联网需求只来自 opencode 自身的模型调用。

> ℹ️ **版本提示**：v1.0.1 及更早的发布包中，`speckit.testing.plan.md` 与 `speckit.testing.design.md` 是**空文件**，在 opencode 里调这两个命令没有效果。**v1.0.2 已修复**。若手上只有旧包，请用第 4.1 / 4.5 节给出的脚本命令代替（脚本本身一直是好的）。

---

## 第三部分 端到端使用流程

### 3.1 总流程

```text
【正常 spec-kit 流程，不受任何影响】
  specify → plan →（先别 implement）

【SCT 第 1 步】merge：spec → acceptance.yaml（测试计划）
       ↓ 人工补充关键字段（target / test_cases / given / checks / example）★成败关键
【SCT 第 2 步】implement：开发对照契约写代码（原流程）
       ↓ 代码定稿
【SCT 第 3 步】impact：反向追溯变更 → change-impact.md（定 L1/L2/L3 级）
       ↓
  ┌─ L1 小改 → 只跑存量回归，结束
  ├─ L2 中改 → codegen（定向生成）→ check（完整报告+门禁）
  └─ L3 大改 → codegen → check → e2e（Pla
ywright 回归）
```

### 3.2 变更分级（L1/L2/L3，机器可判，拿不准往上升一级）

| 级别        | 判定条件（满足其一）                                   | 后续动作                                |
| --------- | -------------------------------------------- | ----------------------------------- |
| **L1 小改** | 改动 ≤2 个文件，且不动 Controller/DTO/API 契约，且 测试计划 未变 | 只跑存量回归；codegen / check 报告 / e2e 全跳过 |
| **L2 中改** | API 契约或规则变更，受影响 API ≤5 个                     | impact + 定向 codegen + 完整 check      |
| **L3 大改** | 新功能 / 跨模块 / 数据库迁移 / 受影响 API >5 个             | 全流程 + e2e                           |

### 3.3 推荐节奏（新项目 vs 存量项目）

- **新项目/新模块**：测试计划 `_meta.coverage_mode: full`，测试计划 应覆盖全部接口，门禁从严；
- **存量（brownfield）项目**：测试计划 `_meta.coverage_mode: incremental`，只登记本次变更范围，存量未登记代码不算漂移。门禁 = 测试点覆盖 100% + 增量行覆盖率 ≥ profile 阈值（standard 档默认 90%，`--profile` 可调）+ 无 HIGH 漂移。

---

## 第四部分 命令详解

> 每个命令都可以在 opencode 里用 `/speckit.testing.<name>` 触发（由 Agent 读命令文件、按步骤执行）。  
> 下面同时给出**底层脚本命令行**：便于接入 CI 或命令文件异常时兜底。
> SCT 只有 **3 个命令**：`testing.plan`（测试计划，含变更影响定级）→ `testing.design`（测试案例，含 e2e 场景）→ `testing.run`（测试执行 + 门禁 + 报告，含有效性验证）。

### 4.1 testing.plan —— 建测试计划（含变更影响定级）

**干什么**：把 spec.md（必选）+ plan.md / data-model.md / api-contracts.md（可选）合并为 `acceptance.yaml`（测试计划）；可选做变更影响定级。
**何时跑**：`specify plan` 之后、写代码之前（自动生成）。  
**底层脚本**：`scripts/spec-merge.py`（+ `scripts/change-impact.py` 做定级）

在 opencode 中触发：`/speckit.testing.plan`。等价的脚本命令（可放 CI / 旧包兜底）：

```bash
python .specify/extensions/sct/scripts/spec-merge.py \
  --spec specs/001-xxx/spec.md \
  --plan specs/001-xxx/plan.md \
  --api-contracts specs/001-xxx/api-contracts.md \
  --data-model specs/001-xxx/data-model.md \
  --out specs/001-xxx/acceptance.yaml
# --feature-id F001   手动指定 feature ID（默认从 spec.md 推断）
# --ai                内网不可用，勿加
```

> 变更影响定级（原独立命令已并入）：代码变更后可加跑
> `python .specify/extensions/sct/scripts/change-impact.py --spec .../acceptance.yaml --out .../change-impact.md`
> 产出 P0/P1/P2 + L1/L2/L3 定级，控制下游 `testing.design` / `testing.run` 投入多少。详见 4.4。

**产出后必须人工补充的字段（生成器不反推，缺了整条链就空转）**：

| 字段           | 位置                    | 作用                                                  | 不补的后果                                       |
| ------------ | --------------------- | --------------------------------------------------- | ------------------------------------------- |
| `target`     | rules[]               | 规则对应的目标类/方法                                         | 无法生成 Java 单测                                |
| `test_cases` | rules[]               | 输入值 + 期望（断言唯一来源）                                    | 无法生成单测                                      |
| `given`      | test_cases[]          | mock 协作者桩（`call` + `returns`）                       | mock 默认返回 0/null，测试误失败（触发 MOCK_NOT_STUBBED） |
| `checks`     | rules[]               | 离线静态断言锚点（annotation/method/exception/constant/text） | 规则测试降级为宽松匹配，可能 FAIL 提示补锚点                   |
| `example`    | apis[].request.body[] | 字段真实示例值                                             | 启发式取值可能过不了后端 @Pattern 校验（构造失败≠断言失败）         |

### 4.2 testing.design —— 测试设计 + 制定任务（含 e2e）

**干什么**：从 测试计划 生成 write-once 测试：JUnit 单测（rules 带 target+test_cases 时）+ Python 规则静态断言 + 场景占位。  
**何时跑**：`test_timing=post`（默认）时**代码定稿后**跑（此时公开签名最新，绑定质量最高）；`pre` 时实现前跑。  
**底层脚本**：`scripts/acceptance-codegen.py`

```bash
python .specify/extensions/sct/scripts/acceptance-codegen.py \
  --spec specs/001-xxx/acceptance.yaml \
  --out tests/generated/ \
  --code backend/src/main/java \
  --codegraph codegraph.json        # 可选但强烈推荐
# --only API-001,BR-002             定向再生成（配合 impact 的 P0/P1 范围）
# --only-rules BR-001,BR-002        定向再生成指定 rule（与 --skip-api-tests 配合）
# --force                           忽略 hash 缓存强制全量再生成
# --junit auto|4|5                  默认 auto：跟随项目已有版本，4/5 不混用
# --java-test-root src/test/java    Java 测试输出根
# --base-url http://staging:8080     接口测试 base_url（优先级 CLI > env BASE_URL > codegraph > 默认）
# --skip-unit-tests                      不生成 Java/规则测试（纯 API-only 项目）
# --skip-api-tests                  不生成接口测试与 conftest（纯库/工具项目）
# --module scenario-service         多模块：输出隔离到 {out}/{module}/（v1.0.6）
```

**4.2.1 哪些层被生成——独立开关组合**

| 项目类型 | 推荐开关 | 说明 |
|---|---|---|
| 纯前端（无 Java 后端） | `--skip-unit-tests` | 只生成 `test_api_*.py` + `conftest.py` |
| 纯库/工具（无 Controller） | `--skip-api-tests` | 只生成 Java 单测 + `test_rules.py` |
| 全栈项目 | （默认） | 两层都生成 |
| 单测定向再生成 | `--only-rules BR-001,BR-002` + `--skip-api-tests` | 只重生指定 rule |

**关键机制**：

- **签名绑定**：`--code` 传入时解析目标方法公开签名（参数类型/顺序 + 构造器/字段协作者），按名（否则按位置）绑定 测试计划 输入值；自动识别协作者生成 `@Mock`（不用 Spring）。
- **生成风格**：经典 AAA 三段注释 + `@DisplayName` 意图注解（JUnit5）。
- **hash 短路**：测试计划 和 codegraph 都没变时秒级退出，0 文件再生成。
- **产出**：`tests/generated/` 下测试文件 + `COVERAGE_REPORT.md`（spec→test 派生映射）+ `_codegen_meta.json`（供 check 自动合并）。

### 4.3 testing.run —— 测试执行与门禁（核心）

**干什么**：执行测试 → 跑 consistency-check → 产出**统一详尽的测试报告** `test-report.md`，并给门禁结论。  
**报告内容（v1.4.0 起）**：产物索引 / 执行摘要 / 覆盖率 / 单测+接口测试 / **缺陷汇总** / 变更影响分析 / 漂移检测——一份报告串起全部维度，供人工审核。  
**何时跑**：codegen 之后；`post` 时序下如果测试还没生成，本命令会先补生成再校验。  
**底层脚本**：`scripts/consistency-check.py`

```bash
# 先执行测试
pytest tests/generated/ --junitxml=tests/generated/junit-report.xml
# Java 侧跑带覆盖率的构建，拿到 jacoco.xml

python .specify/extensions/sct/scripts/consistency-check.py \
  --spec specs/001-xxx/acceptance.yaml \
  --code backend/src/main/java \
  --tests tests/generated/ \
  --jacoco backend/target/site/jacoco/jacoco.xml \
  --junit tests/generated/junit-report.xml \
  --impact specs/001-xxx/change-impact.md \
  --report specs/001-xxx/reports/test-report.md
# --mode full|incremental        覆盖模式（CLI > 测试计划 _meta.coverage_mode > 默认 full）
# --base main                    增量覆盖率 git 基线
# --skip-api-tests                跳过接口测试层（环境无 token/不可达时，避免阻塞）
# --skip-rule-tests               跳过规则测试层（只关心 API 行为时）
# --prereq-timeout 3.0            BASE_URL 预检超时（秒，默认 3）
# --module scenario-service       多模块：源码根= {code}/{module}/src/main/java（v1.0.6）
# --module-src src/main/kotlin    模块内源码相对路径（不在 src/main/java 时用，v1.0.6）
```

**4.3.1 接口层预检**（v1.0.4 起，`--skip-api-tests` 未传时自动执行）：

```
🔎 接口测试预检：
   BASE_URL = <当前值>
   API_AUTH_TOKEN = 已设置 / 未设置
   可达性 = 可达 / 不可达（<原因>）

- 可达 → 继续跑 pytest
- 不可达 + 无 token → 退出码 3，打印「确认输入」诊断给 agent 让你在对话框选
- 不可达 + 有 token → 退出码 3，提示「服务未启动/端口被挡/环境不通」

退出码 3 = 询问，不是失败。opencode 收到后会在对话框跟您确认是否跳过接口层
（重跑命令加 `--skip-api-tests`）。
```

**门禁口径（v2.1 起：四维证据 × 三态模型，与 testing.run 同语义）**：

| 维度 | 证据项 | PASS | BLOCK | UNPROVEN |
|---|---|---|---|---|
| 需求覆盖 | `REQUIREMENT_COVERAGE` | 每个计划条目都有测试且已实现 | 漏测 / 未实现 | 无契约条目可追溯 |
| 执行结果 | `EXECUTION_RESULT` | 全部生成测试通过（含 rules/scenarios，不只 `test_api_`） | 有失败/错误 | 未给 `--junit` 或 0 执行 |
| 执行结果 | `LINE_COVERAGE` | 增量行覆盖率 ≥ profile 阈值（standard 档 90%） | < 阈值 | 未给 `--jacoco`+`--base` |
| 证据完整性 | `EVIDENCE_COMPLETENESS` | 执行 + 覆盖证据齐备 | — | 缺 `--junit` 或 `--jacoco`+`--base` |
| 测试完整性 | `TEST_INTEGRITY` | 生成文件 sha256 全部一致且意图完整 | **手改/缺失生成文件**；意图缺失（standard/strict） | 旧版产物无 manifest；意图缺失（fast 档） |

**退出码：PASS=0 / BLOCK=1 / UNPROVEN=2**（预检询问仍为 3）。整体取最严；
`--skip-api-tests` 时覆盖与执行两项记 N/A 不参与（显式跳过 ≠ 证据缺失）。

> **v2.3 可选防空洞维度**：给 testing.run 加 `--surefire` / `--tasks` / `--verify-compile`
> 即追加 REAL_TESTS（真实执行数，0 执行 → BLOCK）/ PHANTOM_TASK（标 [X] 但代码无证据）/
> COMPILE（编译门）证据项——回答"测试不仅存在，而且真的执行了"。

> ⚠️ **UNPROVEN 不是 PASS**：缺 junit/jacoco 证据时结论为 UNPROVEN（退出码 2），
> 补齐证据重跑才放行。v1.1.2 及之前覆盖率只打印不阻断、手改生成测试不感知——
> 这两个漏洞已在 v1.1.3 堵上（分别对应证据项 2 和 4）。

**失败归因表（修断掉的环节，不要盲目重试）**：

| 漂移/失败          | 断掉的环节          | 修复方向                                                             |
| -------------- | -------------- | ---------------------------------------------------------------- |
| `MISSING_IMPL` | Spec→Code      | 对照 change-impact.md「实现需求」补实现                                     |
| `MISSING_TEST` | Code→Test 派生缺失 | 跑 testing.design（勿手补测试）                                             |
| `UNSPEC_API`   | 测试计划 登记缺失       | 补 测试计划 条目再 codegen                                                |
| 测试用例失败         | 业务实现 ≠ 测试计划 口径  | **举证责任在代码侧**：默认 测试计划 是真相→修代码；仅有证据证明 spec 错了才改 测试计划（连带改 spec 后重新生成） |

**跑 API 测试的环境变量**（v1.0.3 起，codegen 自带 `conftest.py`，pytest 启动时按环境变量配）：

```bash
# 必须：API 测试要发到哪
export BASE_URL=http://staging.internal:8080     # 默认 localhost:8080；CLI --base-url > env > codegraph

# 可选：鉴权头（Bearer token）
export API_AUTH_TOKEN=eyJhbGciOi...              # 缺则不设 Authorization（开放接口/本地开发）
export API_AUTH_HEADER=X-API-Token              # 缺则默认 Authorization

# 收完测试结果
pytest tests/generated/ --junitxml=tests/generated/junit-report.xml
```

`BASE_URL` 与 `API_AUTH_TOKEN` 都不需要重新生成代码——换 CI 环境或换 token 直接改环境变量即可。GET 接口已正确用 `params=`，POST/PUT/PATCH 用 `json=`，**自跑能起来**（前提：服务在 `BASE_URL` 上可用、token 有效）。

### 4.4 变更影响定级（testing.plan 的一步，原独立命令已并入）

**干什么**：实现完成后反向追溯：git diff → 调用链（controller→service→mapper）→ 对照 测试计划 → 产出 `change-impact.md`（P0/P1/P2 + 变更级别 + 「实现需求」契约段）。**轻量设计，静态扫描，不启动应用。**  
**何时跑**：代码定稿后、`testing.run` 之前；它是整条流水线的分级闸门。  
**底层脚本**：`scripts/change-impact.py`

```bash
python .specify/extensions/sct/scripts/change-impact.py \
  --spec specs/001-xxx/acceptance.yaml \
  --base main --head HEAD \
  --out specs/001-xxx/change-impact.md
# --staged    只看暂存区（与 --base/--head 互斥）
```

**优先级含义**：P0=场景直接实现被改代码（本轮必测）；P1=共用 service/rule（应回归）；P2=边缘影响（可选/下轮）。  
连接 codebase-memory-mcp 时调用链/DTO 解析更准，没有则回退 ripgrep。

### 4.5 e2e 场景案例（testing.design 的一步，原独立命令已并入）

**干什么**：把 change-impact.md 的 P0/P1 场景 + 测试计划 的 `e2e` 段桥接成 Playwright 场景案例（只要 G/W/T）与意图导出（`E2E_TESTCASES.md` / `_intent_tests.json`）。  
**何时跑**：仅 L3 大改。  
**底层脚本**：`scripts/change-impact-e2e-bridge.py`

在 opencode 中触发：`/speckit.testing.design`（v1.0.2 起可用，命令内置 L3 闸门）。等价脚本命令（可放 CI / 旧包兜底）：

```bash
python .specify/extensions/sct/scripts/change-impact-e2e-bridge.py \
  --spec specs/001-xxx/acceptance.yaml \
  --impact specs/001-xxx/change-impact.md \
  --out e2e/auto_generated/
# --dry-run       只打印不写文件
# --include-p2    无 impact 文件时也包含 P2 场景（v1.0.6，默认只跑 P0/P1）
```

**支持的 action / assertion 类型（v1.0.6 起）**：
- `action.type`：`upload_file`（file_input/drag_drop）、`click`、`double_click`、`double_click_node`、`fill`、`navigate`、`batch_confirm_nodes`；其他类型仍写 `// TODO` 占位需人工补写
- `assertion.type`：`ui_message`、`ui_visible`、`url_contains`；其他类型 TODO
- `pre_steps` 的 inline flow（`[login, navigate:/x?y=1]`）含 `?` 时脚本自动拆 block 解析（v1.0.6）

**两个消费路径（SCT 的 e2e 是"生成器"不是"执行器"）**：桥只写产物、从不启动浏览器，产物给谁用取决于环境——

| 路径 | 消费产物 | 前提 | 怎么跑 |
|---|---|---|---|
| **A — Playwright 直接回归** | `*.spec.js` + `E2E_TESTCASES.md` | 该环境已装 Playwright 与浏览器 | `npx playwright test e2e/auto_generated/`，人工对照 `E2E_TESTCASES.md` 勾选 |
| **B — AI 测试平台** | `_intent_tests.json` | 内网已部署 AI 测试平台（AI 脚本生成/调度） | 平台导入 intent 文件生成并执行；**本机无需装 Playwright** |

> **内网没装 Playwright ≠ 不能走 e2e 桥**：路径 B 依然成立——本机只负责生成，
> Playwright 依赖全部落在 AI 测试平台侧。`_intent_tests.json` 是路径 B 的唯一数据契约
> （G/W/T 意图 + 关联脚本名），平台据此重建可执行用例；路径 A 的 `.spec.js` 在
> 路径 B 下只是参考物，不是执行物。

### 4.6 跳过开关与接口层预检（v1.0.4 起）

**接口测试/单测是独立可选的**——按项目类型选最合适的组合，不会阻塞流程。

| 命令            | 开关                           | 作用                                  |
| ------------- | ---------------------------- | ----------------------------------- |
| `testing.design` | `--skip-unit-tests`               | 不生成规则/单测（纯 API-only 项目）             |
| `testing.design` | `--skip-api-tests`           | 不生成接口测试与 conftest（纯库/工具项目）          |
| `testing.design` | `--only-rules BR-001,BR-002` | 定向再生成指定 rule（配合 `--skip-api-tests`） |
| `testing.run`   | `--skip-api-tests`           | 跳过接口测试层（用于环境无 token/不可达时）           |
| `testing.run`   | `--skip-rule-tests`          | 跳过规则测试层（只关心 API 行为时）                |
| `testing.run`   | `--prereq-timeout 3.0`       | BASE_URL 预检超时（秒，默认 3）               |

**`testing.run` 起跑前预检**：

- 如果有 `test_api_*.py` 且没传 `--skip-api-tests`，会先 HEAD 一下 `BASE_URL`：
  - **可达** → 继续跑 pytest，pytest 自身决定通过/失败
  - **不可达 + 无 token** → 退出码 **3**，打印下面这段给 opencode，让它在对话框跟您确认：
    ```
    ⚠️  [prereq] 接口测试缺前：
        - BASE_URL 不可达：<原因>
        - API_AUTH_TOKEN 未设
        在对话框确认输入：
          1) 提供 token / 修环境后再跑：`export API_AUTH_TOKEN=...` 后重跑 testing.run
          2) 跳过接口层：`testing.run --skip-api-tests ...`
    ```
  - **不可达 + 有 token** → 退出码 3，提示「服务未启动 / 端口被挡 / 环境不通」
- 退出码 3 不是失败，是**询问**——opencode 会把诊断贴到对话框等您拍板；您说"跳过"它就带 `--skip-api-tests` 重跑，check 继续走规则/覆盖率/漂移门禁。

**典型用法**：

```bash
# 纯前端项目（无 Java 后端）：跳过单测层
specify testing.design --skip-unit-tests ...

# 纯库/工具项目（无 Controller）：跳过接口层
specify testing.design --skip-api-tests ...

# 内网临时服务挂掉：check 不要阻塞，临时跳过接口层
specify testing.run --skip-api-tests --skip-rule-tests ...   # 两个都跳 → 只看覆盖率/漂移
```

### 4.7 测试有效性验证（testing.run 的一步，原独立命令已并入）

**干什么**：回答门禁回答不了的问题——**这些测试真能抓住 bug 吗**。  
`testing.run` 的门禁验证"测试有没有、覆盖到没有、有没有通过"；本步验证"测试有没有效"（幻影/编译/真实计数）。  
**何时跑**：L2/L3 变更，在 `testing.run` 之后、宣布完成之前。L1 跳过。  
**底层脚本**：`scripts/verification-gate.py`

```bash
python .specify/extensions/sct/scripts/verification-gate.py \
  --spec specs/001-xxx/acceptance.yaml \
  --code backend/src/main/java \
  --tests tests/generated/ \
  --tasks specs/001-xxx/tasks.md \
  --surefire backend/target/surefire-reports \
  --report specs/001-xxx/reports/verification.md
# --skip-compile                                        内网无 Maven/Gradle 时跳过编译门
```

**三项检查**：

| 检查 | 抓的是 | 与 check 的关系 |
|---|---|---|
| `PHANTOM_TASK` | tasks.md 标 `[X]` 但代码中找不到类名/方法证据——**声称做了实际没做** | 与 `MISSING_IMPL` **反向互补**（那里查"测试计划 定义了代码没做"） |
| `COMPILE` | 测试代码根本编译不过（生成了但从未验证过） | check 只看文本，不编译 |
| `REAL_TESTS` | surefire 报告里实际执行数是 0——声称有测试但没真跑 | check 统计的是"生成了多少" |

**三态语义（重点）**：退出码 `0=PASS` `1=BLOCK` `2=UNPROVEN`

| 状态 | 含义 | 处置 |
|---|---|---|
| **PASS** | 编译过 + 真实执行且全绿 + 无幻影 | 放行 |
| **BLOCK** | 发现幻影 / 编译失败 / 实际执行数为 0 / 有失败 | ❌ 阻断，修复后再走 |
| **UNPROVEN** | **无法验证**（缺 mvn/gradle、缺 surefire、缺 tasks.md） | ⚠️ **不等于通过**——补齐环境重跑或人工确认 |

> **纪律：UNPROVEN 不是 PASS。** 没验证就说"验证通过"正是这个门要消灭的行为。
> 整体结论取最严（BLOCK > UNPROVEN > PASS），所以只要有一项 UNPROVEN，整体就不会是 PASS。
> 内网常见：无 Maven → `--skip-compile`；无 surefire 报告 → 先真正执行测试。

**修复动作**：幻影 → 补实现或把 `[X]` 改回 `[ ]`（诚实标注）；编译失败 → 修测试代码或改 测试计划 重新 codegen；执行数 0 → 修构建/测试发现路径。



---

## 第五部分 测试计划（acceptance.yaml）字段速查

```yaml
_meta:
  coverage_mode: full | incremental   # 全量/增量（见 3.3）
  test_timing: post | pre             # 代码先行（默认）/ 测试先行

features:                             # 来源 spec.md
  - id: F001
    acceptance_scenarios:
      - id: F001-1                    # {feature_id}-{序号}，全局唯一
        given: ...                    # 三要素必填
        when: ...
        then: ...
        edge_cases: []                # --ai 产物，内网手工维护

apis:                                 # 来源 api-contracts.md / plan.md
  - id: API-001                       # 测试文件命名依据 test_api_001_*（取 ID 末段，v1.0.6 起）
                                      # 三段式写法也支持：API-F003-001 → test_api_001.py
    method: POST
    path: /api/batch-tasks
    spec_ref: "specs/001/spec.md#xx"  # 反向追溯锚点
    request: { body: [{name, type, required, example}] }
    # response 两种 schema 都支持（v1.0.6 起）：
    #   旧: response.success + response.errors
    #   新: response_200.fields + error_codes: [400, 404, ...]
    response:
      success: { status: 200, body: {...} }
      errors: [{condition, status, message}]   # 生成异常路径用例

rules:                                # 来源 data-model.md / spec.md
  - id: BR-001                        # 测试函数命名依据 test_br_001（取 ID 末段，v1.0.6 起）
                                      # 三段式 BR-F003-001 → test_br_001（同 feature 多条规则不重名）
    text: 单次导入不超过 1000 条
    priority: P0
    target: { class: com.x.OrderService, method: calculate }   # 生成 Java 单测前提
    checks: [{kind: annotation, target: XxxClass, expect: "@Max(1000)"}]
    test_cases:
      - name: testXxx_ShouldYyy
        inputs: { originalPrice: 100.0, vipLevel: 3 }
        given: [{ call: "batchRepository.count()", returns: 5 }]  # mock 桩
        expect: { returns: 85.0 }      # 或 { throws: XxxException }
```

---

## 第六部分 门禁、信号与裁决

### 6.1 门禁（合并前必须全绿）

测试点覆盖 100% ＋ 增量行覆盖率 ≥80% ＋ HIGH 漂移 = 0 ＋ 改动点审查表人工签字。

### 6.2 测试失败处置（铁律 2 的操作化）

1. 先分失败类型：**构造失败**（请求被 400 校验拒了，没到业务逻辑）≠ **断言失败**（响应到了但与 测试计划 期望不符）；
2. 构造失败 → 给 测试计划 字段补 `example`，重新生成（测试计划 hash 变了会自动再生成，不用 --force）；
3. 断言失败 → 走举证责任流程：默认 测试计划 是真相 → 修代码；确有证据证明 spec 错 → 改 测试计划 + 改 spec → 重新生成；
4. 全程不碰生成的测试文件。

### 6.3 BINDING_DRIFT 信号分类（测试计划 与代码对不上时）

| 信号                    | 含义                              | 处置                        |
| --------------------- | ------------------------------- | ------------------------- |
| `METHOD_NOT_FOUND`    | 测试计划 目标方法在代码中被改名/删除              | 人工裁决：改回代码 or 更新 测试计划 后重新生成 |
| `MISSING_INPUT`       | 某参数在 test_cases.inputs 缺值       | 补 测试计划 inputs              |
| `UNCONSTRUCTABLE_ARG` | 复杂对象/对象列表无法自动构造（置 null，测试诚实失败）  | 在 测试计划 补 `call` 或可构造值      |
| `MOCK_NOT_STUBBED`    | 依赖 mock 但 测试计划 漏写 `given`        | 补 given 桩                 |
| `FIELD_DRIFT`         | CodeGraph 与 测试计划 字段级不一致（建议性，不门禁） | 人工核对                      |

---

## 第七部分 内网 FAQ

**Q1：生成的 Java 测试编译报错"编码 GBK 不可映射字符"？**  
pom 加 `<project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>`；命令行编译加 `javac -encoding UTF-8`。

**Q2：/speckit.testing.plan 或 /speckit.testing.design 在 opencode 里没反应？**  
先看版本：v1.0.1 及更早的发布包里这两个命令文件是空的（已在 **v1.0.2** 修复）。旧包请直接跑脚本（4.1 / 4.5 节），或重装最新发布包（`specify extension add <路径> --dev --force`，当前最新 **v1.0.6**）。

**Q3：check 报一片 MISSING_IMPL？**  
先确认 `--code` 指向真实代码根（默认 `backend/src/main/java`，多模块项目要改）；再确认 测试计划 `coverage_mode` 是否应为 `incremental`（存量项目用 full 会把未登记的存量代码全报成漂移）。

**Q4：改了 测试计划 重新生成，之前在生成测试里手补的东西没了？**  
设计如此（write-once）。人工补充只能写回 测试计划（`call` / `example` / `inputs` / `given`），写进生成文件的内容一定会被再生成冲掉。

**Q5：--ai 内网用不了，影响大吗？**  
不大。`--ai` 只负责 edge_cases 辅助填充和语义漂移建议，不自动放行任何门禁。核心链路（merge→codegen→check）完全不依赖 AI。

**Q6：能接 CI 吗？**  
推荐做法：SCT 工具侧保持无钩子，把 `testing.run` 的脚本调用加为项目 CI（Jenkins/GitLab CI）的一个 stage，报告作为构建产物归档。

**Q7：JUnit4 老项目能用吗？**  
能。`--junit auto` 会跟随项目已有版本生成 JUnit4 风格（`@RunWith(MockitoJUnitRunner.class)`），4/5 不混用。

**Q8（opencode）：装完在 opencode 里输入 `/speckit.testing.run` 提示找不到命令？**  
按顺序查：① `ls .opencode/commands/` 看 5 个 md 在不在（旧版目录是 `.opencode/command/`）；② 是否在**项目根目录**启动的 opencode（子目录启动会找不到 `.specify/`）；③ `cat .specify/extensions/.registry` 确认扩展已登记；都没问题就重启一次 opencode 让它重新加载命令。

**Q9（opencode）：命令能触发，但脚本报 `python: command not found` 或路径找不到？**  
确认 Python 在 PATH；且必须在项目根目录执行——命令里的脚本路径是相对路径（`.specify/extensions/sct/scripts/...`、输出目录 `specs/`、`tests/generated/` 都是相对项目根）。

**Q10（opencode）：命令跑起来很慢 / 结果不稳定？**  
SCT 的 codegen/check 本身是确定性脚本，慢主要来自模型侧。建议：测试计划 分模块拆小、用 `--only` 定向生成；分区时优先让 impact 先跑出分级（L1 直接跳过下游）。

---

## 第八部分 试点落地建议

1. **先选一个真实小需求**跑通 merge→（补 测试计划）→implement→impact→codegen→check 全环，约半天；
2. **门禁分三阶段**：report-only 观察 2~4 周（积累误报数据）→ 新增 spec 硬门禁 → 全量硬门禁；
3. **测试计划 diff 进代码评审**，明确 测试计划 owner（建议测试负责人），spec.md 是输入、acceptance.yaml 是裁决后的真相；
4. 积累漂移发现数、人工裁决分布、误报率等度量，作为门禁阈值调优和成效证明的依据。

---

*本手册基于 spec-kit-sct **v1.0.6**（<https://github.com/zqianqian137/spec-kit-sct>），内容覆盖到最新发布包的以下演进：*

| 版本 | 手册对应内容 |
|---|---|
| v1.0.2 | 补全 `testing.plan` / `testing.design` 命令文件（此前为空文件）；4.1 / 4.5 节 |
| v1.0.3 | API 测试可自跑：`conftest.py`（session fixture 读 `BASE_URL`/`API_AUTH_TOKEN`）、GET 用 `params=`、`--base-url`；4.2 / 4.3 节 |
| v1.0.4 | `--skip-rules` / `--skip-api-tests` / `--only-rules` / `--skip-rule-tests` / `--prereq-timeout`，check 起跑前 BASE_URL 预检（退出码 3 询问用户）；4.2.1 / 4.3.1 / 4.6 节 |
| v1.0.5 | 生成代码全面 JDK 8 兼容（`Object actual`、`Arrays.asList`/`Collections.emptyXxx`、集合形参自动 import）；e2e 两个消费路径（Playwright 直跑 vs AI 测试平台）；第 2 部分环境清单 / 4.5 节 |
| v1.0.6 | 移植实战发现的全部问题（F-1~F-20）：同 feature 多 API/多规则不再重名覆盖（F-2/F-5）；兼容 `response_200`/`error_codes` 与 `response.success`/`errors`（F-3）；覆盖报告真实计数（F-7/F-8）；spec-merge 识别编号 G/W/T（F-1）；e2e 扩展 action/assertion 类型与 `--include-p2`（F-13/14/15/16）；`--module`/`--module-src` 多模块与非 HTTP 接口（F-17~F-20）；4.2 / 4.3 / 4.5 节 |
| v1.1.0 | 新增 `testing.run` 测试有效性验证门：幻影任务检测 / 编译门 / 真实测试计数 / 变异得分（可选），诚实三态 PASS/BLOCK/UNPROVEN（UNPROVEN ≠ PASS）；补齐社区目录 category/effect 元数据；4.7 节 |
| v1.1.1 | README 扩充 Methodology 方法论详解章节（三方漂移 / 前向保证链 / 断言不反推代码 / 反模式）；无功能变更 |
| v1.1.2 | 移除 preset 产物，发布包只含扩展（社区目录只收录扩展）；1.4 节 / 安装节 |
| v1.1.3 | **方法论重定位**：独立测试流四阶段（计划/案例/执行/覆盖），acceptance.yaml 正名"测试计划"（spec.md 仍是需求真相源）；**check 三态证据门禁**（覆盖率真阻断、全部测试参与判定、手改生成文件即 BLOCK、退出码 0/1/2）；场景/非HTTP/无锚点规则桩 `fail→skip`（UNPROVEN 语义）+ `_scenario_gaps.json`；write-once 由 sha256 manifest 强制；canonical ID 层 `sct_ids.py`；1.1 / 1.2 / 4.3 节 |
| v1.2.0 | 方法论重构（10 节→5 节，回归"测试域扩展"定位）；声明语言中立（Java=默认 adapter）；覆盖率门禁 80%→90%；新增中文介绍材料；README / 手册第一部分 |
| v1.3.0 | **命令精简 6→3**：`testing.plan`（合并 impact）/ `testing.design`（合并 e2e）/ `testing.run`（合并 verify）；测试计划从 spec + plan 产物自动生成；接口层协议无关；README / 手册第四部分 / 命令文件 |
| v1.4.0 | **after_plan 钩子**自动生成测试计划（可跳过、可人工补充）；`testing.run` 报告扩展为统一详尽报告（产物索引 + 6.4 缺陷汇总）；功能测试案例字段补全（案例编号/案例类型正反例/优先级/意图/前置/步骤/预期）；1.4 / 4.3 节 |
| v1.5.0 | **代码减法**：删非 HTTP 适配器（gen_non_http_tests + check_non_http_consistency + --non-http）与变异测试（check_mutation + --mutation*），净删 214 行；verify 保留幻影/编译/真实计数三态 |
| v2.0.0 | **定位升级** Spec→Contract→Test→Evidence→Gate，三大原则（Oracle Independence / Write-once / PASS-BLOCK-UNPROVEN）；`testing.cases`→`testing.design`（测试设计+制定任务，可调用 skill 池）；`--skip-rules`→`--skip-unit-tests`；新增 ROADMAP.md；1.1 / 4.2 节 |
| v2.1.0 | **P0 四件事落地**：① Contract（`templates/acceptance-schema.json` + `scripts/contract-validate.py` 零依赖三态校验）② Traceability（报告固定章节「需求追溯矩阵 REQ→AC→TEST→EXECUTION→EVIDENCE」，含 Java 单测识别）③ Evidence（门禁重构为四维证据：需求覆盖/执行结果/证据完整性/测试完整性）④ Quality Profile（`--profile fast 70% / standard 90% / strict 95%` 替代硬编码 90%）；另加 `scripts/self-test.py` 三档回归（golden/blocker/gate），已捕获并修复 2 个真实缺陷 |
| v2.2.0 | **定位收敛为 Verification Kernel（验证内核）**：只自有 Evidence Contract / Traceability / Gate 三件事，测试生成归 Adapter；新增 `docs/verification-kernel.md`（Kernel/Adapter 边界 + `Evidence Record` 接口 + 三问判定规则 + 社区扩展接入关系）；新增 `scripts/check-release-consistency.py` 发布前一致性自检（7 项三态检查）；**发布前一致性 cleanup 14 项**（根目录 v1.1.2 陈旧快照对齐、旧命令名残留、zero hooks 表述、hooks 计数、profile 文档、SoT 术语、描述/tags 对齐、两份副本内容分叉、门禁表四维 gate id 对齐、profile 口径、方法论 v2.2.0 回访）；**命令名 `speckit.testing.*` 不变**；1.1 / 4.2 节 |
| v2.3.0 | **防空洞收编**：`testing.run`（consistency-check）门禁增加可选「测试有效性」维度——`--surefire`→REAL_TESTS（surefire 真实执行为 0 即 BLOCK）、`--tasks`→PHANTOM_TASK（标 [X] 无代码证据）、`--verify-compile`→COMPILE（编译门，默认不跑）；adapter 目录化（v3.0 Step 1-2）按用户拍板改**触发式搁置**；self-test 增至四档（新增 anti-hollow）；ROADMAP / verification-kernel 同步 |
