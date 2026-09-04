# SCT — Spec-Code-Test Consistency (Speckit Extension)

> **SCT 一句话：不追求"生成更多测试"，而是用最少的测试和最可信的证据，证明 Spec 被正确实现。**
>
> **SCT 是 Spec Kit 的验证内核（Verification Kernel）——它不生产测试，它生产可裁决的证据。**

A [Spec Kit](https://github.com/github/spec-kit) extension that turns the
requirement into a **quality gate** — and owns only the part that must never be
outsourced: the *verdict*.

## Verification Kernel — what SCT owns, and what it deliberately doesn't

SCT is **not** a test-generation extension. Test generation is a solved,
crowded space — and it is not where the hard problem is. The hard problem is:
*given a pile of tests, can you prove the spec was implemented correctly?*
That is a **verification** problem, and it is what SCT is built to answer.

So SCT owns exactly three things — the **Kernel**:

| Kernel component | Owns | Deliberately does NOT |
|---|---|---|
| **① Evidence Contract** | `acceptance.yaml` + JSON Schema + `--profile`；期望只能来自契约，**绝不来自代码** | 不生成测试代码 |
| **② Traceability** | `REQ → AC → TEST → EXECUTION → EVIDENCE` 追溯矩阵 + write-once sha256 manifest | 不执行测试 |
| **③ Gate** | 四维证据 → `PASS / BLOCK / UNPROVEN`，退出码 `0 / 1 / 2`，**确定性** | 不改测试、不让失败变绿 |

Everything else is an **Adapter**. An adapter is allowed to *emit* tests and
must *hand back* an `Evidence Record`; it is never allowed to decide the verdict.

```text
Spec Kit（需求，骨架所有）
   ↓  testing.plan
Acceptance Contract（acceptance.yaml —— 证据契约，期望的唯一合法来源）
   ↓  testing.design   ←── Adapter 接入点
Test Design + write-once cases       (JUnit / HTTP / Playwright / Golden / BDD …)
   ↓  testing.run      ←── Adapter 回传 Evidence Record
Evidence（执行结果 + 覆盖 + 缺陷 + 漂移 + 追溯矩阵）
   ↓
PASS / BLOCK / UNPROVEN（Quality Gate —— 确定性引擎裁决，AI 不参与）
```

> 完整架构、Kernel↔Adapter 边界、「什么东西该进内核」的判定规则，见
> [`docs/verification-kernel.md`](./docs/verification-kernel.md)。

Three non-negotiable principles hold the chain honest:

| # | 原则 | 含义 |
|---|---|---|
| ① | **Oracle Independence** | 期望结果只来自 Spec/Contract，**绝不来自 Code**（反推断言 = 自己出题自己改卷） |
| ② | **Write-once + Integrity** | 可以生成测试，但**不能反复改测试直到通过**（sha256 manifest 强制） |
| ③ | **PASS / BLOCK / UNPROVEN** | 证据不足不强行判定 PASS（`UNPROVEN ≠ PASS`） |

> 中文简介：SCT 是 spec-kit 主骨架之外的**验证内核（Verification Kernel）**——不生产测试，
> 只自有三件事：**Evidence Contract**（`acceptance.yaml`，期望只来自契约）、**Traceability**
> （追溯矩阵 + write-once manifest）、**Gate**（四维证据 → PASS/BLOCK/UNPROVEN 三态裁决）。
> 测试生成（JUnit / HTTP / Playwright / Golden / BDD）通过 **Adapter** 接入。面向内网/离线环境：
> 确定性脚本优先，AI 只辅助分析/生成/建议，最终判定永远由确定性引擎给出。

详细路线图见 [ROADMAP.md](./ROADMAP.md)。

## Methodology

SCT is a **test-domain extension — the verification kernel for Spec Kit**.  
It does not replace the backbone, invent a new source of truth, or dictate a  
language. It answers five practical questions — the same five a test lead asks  
before a release.

| # | Question   | How SCT answers it                                                                   |
| - | ---------- | ------------------------------------------------------------------------------------ |
| 1 | 测试不漏测？     | every acceptance point in the spec is mapped to a test — **no test = 漏测, gated**     |
| 2 | 需求都实现了？    | each requirement is checked against the code: declared-but-missing is a gate failure |
| 3 | 报告能不能人工审核？ | one report: what was tested, what was not, and why — reviewable, and re-runnable     |
| 4 | 测试手段齐不齐？   | three layers: **unit → API → e2e** (e2e = scenario cases only)                       |
| 5 | 门禁硬不硬？     | **coverage ≥ profile 阈值**（standard = 90%）, **cases 100% passing**, no missing coverage → merge blocked |

### 1. Not another source of truth — a test plan derived from the spec

Spec Kit's backbone already owns requirements: `spec.md` is the truth, and SCT  
never writes to it. SCT adds one artifact — **`acceptance.yaml`, the test plan**:  
a machine-readable list of what must be tested, derived from `spec.md` /  
`plan.md` / `data-model.md` / `api-contracts.md`.

```text
spec.md (requirement truth, backbone-owned)
    │  testing.plan
    ▼
acceptance.yaml (test plan: rules, APIs, scenarios, expected outcomes)
    │  testing.design
    ▼
three layers of tests → testing.run → gate + report
```

The relationship is **derived, never competing**: change the requirement in  
`spec.md`, re-merge the test plan. Change what you expect from a test, edit the  
test plan. There is exactly one place where an expectation lives — and it is  
never the test file itself.

### 2. No missing coverage — the requirement × test matrix

`漏测` (missed coverage) is the failure SCT is primarily built to prevent, and  
it is a **gate**, not a warning. For every item registered in the test plan,  
`testing.run` requires:

- an API contract → a test that exercises it (success **and** each declared error case)
- a business rule → a test asserting it
- an acceptance scenario → an e2e case

Anything in the plan without a test is reported as **MISSING_TEST** and blocks  
the merge. Anything declared in the plan but absent from the code is reported as  
**MISSING_IMPL** and blocks the merge. Together these answer question 2: *has  
the code actually implemented what the requirement asked?*

### 3. Three layers — adapters, not kernel

> 这三层是 **Adapter 层**，不是 Kernel。Kernel 不关心测试是用 JUnit 还是 pytest
> 写的、接口是走 HTTP 还是 gRPC —— 它只要求每层回传符合 `Evidence Record`
> 接口的执行证据。换掉某一层的 adapter，改变的是*证据怎么产生*，不是*谁裁决*。

| Layer       | Default adapter  | Derived from                  | Output                    | Notes                                                                              |
| ----------- | ---------------- | ----------------------------- | ------------------------- | ---------------------------------------------------------------------------------- |
| **L1 unit** | `junit5` emitter | `rules[]` + method signatures | language-native tests     | **language-agnostic** — Java/JUnit is the default emitter; the emitter is pluggable |
| **L2 API**  | `http` driver    | `apis[]` + contracts          | executable contract tests | **protocol-agnostic** — HTTP is the default driver, not a methodological assumption |
| **L3 e2e**  | `playwright`     | `acceptance_scenarios`        | Playwright scenario cases | **scenario cases only** — G/W/T, no DSL to learn                                   |

Two principles keep the layers honest:

- **Assertions never come from code.** The code is a black box under test. Input  
  *values* and expected outcomes come from the test plan; the code only supplies  
  the *shape* (parameter types). Inferring expectations from the implementation  
  is 自己出题自己改卷 — setting the exam and grading it yourself.
- **Generated tests are write-once.** Change the test plan and regenerate.  
  Hand-editing is detected via a sha256 manifest and blocks the gate.

### 4. The gate blocks — profile-driven coverage, 100% passing

`testing.run` produces structured evidence and takes the strictest verdict:

| 维度 | Evidence | PASS | BLOCK | UNPROVEN |
| --- | --- | --- | --- | --- |
| 需求覆盖 | `REQUIREMENT_COVERAGE` | every plan item has a test **and** an implementation | any 漏测 / 未实现 | no traceable plan items |
| 执行结果 | `EXECUTION_RESULT` | all cases pass (100%) | any failure | no `--junit` / zero executed |
| 执行结果 | `LINE_COVERAGE` | incremental line coverage ≥ profile 阈值 | below 阈值 | no `--jacoco` + `--base` |
| 证据完整性 | `EVIDENCE_COMPLETENESS` | execution + coverage evidence complete | — | missing `--junit` / `--jacoco` + `--base` |
| 测试完整性 | `TEST_INTEGRITY` | generated files match their sha256 manifest, intent complete | hand-edited / missing; intent missing (standard/strict) | legacy output without manifest; intent missing (fast) |

The coverage threshold is **not hardcoded** — it comes from a Quality Profile:

| Profile                       | Coverage | Use when                                                        |
| ----------------------------- | -------- | --------------------------------------------------------------- |
| `--profile fast`              | ≥ **70%** | spike / draft branches, fast feedback                            |
| `--profile standard` (default) | ≥ **90%** | the normal gate — this is the documented default                 |
| `--profile strict`            | ≥ **95%** | release / regulated change; 意图缺失 (missing intent) 直接 BLOCK |

**Optional 5th dimension — 测试有效性 (anti-hollow, v2.3).** The four dimensions
prove tests *exist, run and cover*; they do not prove they were *really executed*
or that claimed work isn't phantom. Pass any of `--surefire` (real execution
count) / `--tasks` (phantom tasks) / `--verify-compile` (compile gate) to `run`
and the corresponding evidence items join the verdict — 0 actually-executed tests
or a phantom task = **BLOCK**.

Exit codes: **PASS 0 · BLOCK 1 · UNPROVEN 2** — missing evidence never  
masquerades as green (`UNPROVEN ≠ PASS`). Anything other than 0 blocks the merge.

### 5. A report a human can actually review

The gate verdict is one line; the report is the deliverable. It contains, for  
human review:

- the full **requirement × code × test matrix** (what is covered, what is not, and why not)
- per-layer execution results with pass/fail/skip counts
- coverage (overall and incremental) with the classes touched by this change
- a **missing-coverage list** — the concrete items a human must still handle

It is written to be re-run after fixes and to be handed to a reviewer who never  
saw the generation step.

### Language neutrality

SCT is not a Java tool. Java/JUnit is the **default adapter** because that is  
the stack it was built against first — but the test-plan format, the coverage  
gate, and the report are language-independent, and the emitter is pluggable.  
The test plan describes *what* must be true; the adapter decides *how* to say it  
in a given language.

> 这其实是 Kernel / Adapter 切分的一个直接推论：**语言属于 adapter，裁决属于 kernel**。
> 所以新增一门语言的支持，不需要动门禁、追溯矩阵和报告——只需要加一个 emitter。

## What it provides

**3 commands + 1 optional hook** — the original `specify / plan / tasks / implement` flow is never altered:

| Command                 | Purpose                                                                                                                                                                                                                          | Key artifact                                |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| `speckit.testing.plan`  | **Auto-generate the test plan** from `spec.md` + plan artifacts (`plan.md` / `data-model.md` / `api-contracts.md`); optional change-impact tiering (P0/P1/P2 + L1/L2/L3)                                                         | `acceptance.yaml`, `change-impact.md`       |
| `speckit.testing.design` | **Test design + task planning**: turn the plan into a test design, then derive write-once cases across three layers — unit (language-pluggable), interface (**protocol-agnostic**), e2e (**scenario cases only**). May consult a skill pool to raise design quality | `tests/generated/*`, `e2e/auto_generated/*` |
| `speckit.testing.run`   | **Execute + gate + report**: verify requirements are implemented, apply the hard gate (coverage ≥ profile 阈值, 100% passing, no missing coverage), write a unified report (unit + interface + coverage + defects + drift + change impact) | `test-report.md`                            |

**Mostly non-intrusive, one opt-in hook.** SCT never alters the original  
`specify / plan / tasks / implement` flow. It registers **one** optional  
lifecycle hook — `after_plan` — which *suggests* auto-generating the test plan  
right after `specify plan` (you can skip it; the generated plan is always  
hand-enrichable). Everything else is **manual**: the user decides, per change,  
whether and when to run `plan` / `design` / `run`.

> Command naming: `speckit.testing.*` — the extension id stays `sct` (repo  
> identity), while the commands say what they are for.

## The unified test report

`testing.run` produces **one report** that ties the whole test flow together,  
for a human reviewer:

| Section   | What it shows                                                                                                              |
| --------- | -------------------------------------------------------------------------------------------------------------------------- |
| 产物索引      | pointers to every artifact: test plan, change-impact, coverage map, functional test cases, Playwright specs, scenario gaps |
| 执行摘要      | the three-state gate verdict and its evidence                                                                              |
| 覆盖率       | overall + incremental JaCoCo coverage                                                                                      |
| 单测 + 接口测试 | per-rule and per-API results, pass/fail/skip                                                                               |
| 缺陷汇总      | a defect list (execution failures + drifts + missing impls) with a defect-ticket column                                    |
| 变更影响分析    | P0/P1/P2 scenarios × execution results                                                                                     |
| 漂移检测      | spec ↔ code ↔ test drift, field drift, system-level exceptions                                                             |

## Installation

### Extension (commands + scripts)

Install the released extension from its GitHub archive:

```bash
specify extension add sct --from https://github.com/zqianqian137/spec-kit-sct/archive/refs/tags/v2.3.0.zip
```

Or install from a local checkout during development:

```bash
specify extension add --dev /path/to/spec-kit-sct
```

> 已指向真实仓库 `zqianqian137/spec-kit-sct`。catalog 的 `documentation` /  
> `download_url` / `homepage` 均指向该仓库，发布时无需再替换。

## When to use it

- You want spec, code, and tests to stay consistent automatically as the project evolves.
- You run brownfield / incremental work and only want to test what actually changed.
- You want AI-assisted test-plan extraction and semantic drift detection (`--ai` flags).
- You want the gate to be **honest**: no green without evidence (`UNPROVEN ≠ PASS`).

## When NOT to use it

- You want the original Speckit flow to stay untouched AND want light  
  overrides — install the extension only and manually run `testing.*` per  
  change; there is no auto-attach preset in this release.
- You expect SCT to auto-run inside your `plan`/`implement` flow — it does not.  
  Only the optional `after_plan` hook *suggests* generating the test plan;  
  `design` and `run` are manual by design, so you must invoke them yourself  
  after implementation.

## Quick start

```bash
# ① 测试计划 — auto-generated after `specify plan`, from spec + plan artifacts
specify testing.plan --spec specs/001/spec.md --out specs/001/acceptance.yaml
#   plan.md / data-model.md / api-contracts.md are consumed when present

# ② 测试案例 — derive write-once cases (unit + interface + e2e scenarios)
specify testing.design --spec specs/001/acceptance.yaml --out tests/generated

# ③ 测试执行 + 门禁 + 报告 — after implementation; nothing auto-fires
specify testing.run --spec specs/001/acceptance.yaml --code backend/src/main/java \
  --tests tests/generated \
  --junit tests/generated/junit-report.xml \
  --jacoco backend/target/site/jacoco/jacoco.xml --base main \
  --report specs/001/reports/test-report.md
```

Exit code 0 = PASS · 1 = BLOCK · 2 = UNPROVEN. Anything other than 0 blocks the merge.

The `--ai` flag on `testing.plan` and `testing.run` requires `SILICONFLOW_API_KEY`  
(optional). When the `codebase-memory-mcp` connector is connected, `testing.plan`  
enriches the reverse trace via semantic code search (otherwise it falls back to  
a ripgrep static scan).

## Making rule tests truly executable (no more empty skeletons)

`test_rules.py` is generated as an **offline static assertion** — it verifies that  
every business rule registered in the test plan has a corresponding piece of evidence in  
the code (annotation / method / exception / constant), without starting any service.  
To make a rule's assertion precise, add a `checks` list to the rule in your test plan  
(`acceptance.yaml` or an `--api-contracts` YAML):

```yaml
rules:
  - id: BR-001
    text: 单次导入不超过 1000 条用例
    priority: P0
    checks:
      - kind: annotation          # 在代码中应出现该注解
        target: BatchImportRequest # 可选：限定文件名/类名以缩小扫描范围
        expect: "@Max(1000)"
      - kind: exception           # 应抛出该异常类
        expect: "BatchSizeExceededException"
```

`kind` may be `annotation` / `method` / `exception` / `constant` / `text`.  
`testing.design` receives the code root via `--code` (default `backend/src/main/java`);  
you can also override at runtime with env `SCT_CODE_ROOT`.

If a rule has **no `checks`**, codegen falls back to a best-effort loose text match;  
if that still finds nothing, the test **fails clearly** (telling you to add `checks`)  
instead of being silently skipped. Acceptance scenarios are end-to-end journeys and  
are validated at the API / E2E layers, so `test_scenarios.py` fails with a clear  
pointer rather than a false green.

## Java unit tests — AAA pattern, signature-bound, contract-anchored

`speckit.testing.design` generates **executable JUnit unit tests** for business rules  
that carry `target` + `test_cases` in the test plan. Generated tests follow the classic  
**AAA** structure with a `@DisplayName` intent annotation (JUnit 5):

> **时序（重要）**：`specify plan` 产出计划 → 测试计划（`acceptance.yaml`）生成后
> **立即** 跑 `testing.design`——做测试设计并制定任务（可调用项目组 skill 池提高设计质量），
> 而不是等编码完再补设计；编码实现完成后，再跑 `testing.run` 执行 + 门禁 + 报告。
> `testing.run` 支持按层跳过：`--skip-unit-tests` / `--skip-api-tests`
> （纯库项目或纯接口项目按需只跑一层）。

How the three JUnit parts are sourced — so the test is **not biased by the code**:

- **Inputs (values)** come from `test_cases.inputs` in the test plan.
- **Inputs (shape)** — parameter types / order — come from the **public signature**  
  of the target method, parsed at generation time when `--code` is passed. The  
  generator binds the test plan's inputs to parameters by name (else position) and auto-detects  
  collaborators (constructor params + injected fields) to `@Mock` them — Spring is  
  **never** used (`@ExtendWith(MockitoExtension.class)` on JUnit 5,  
  `@RunWith(MockitoJUnitRunner.class)` on JUnit 4). It reads the signature, not the  
  method body, so it cannot reverse-engineer the assertion.
- **Assertions / exceptions** come from `test_cases.expect` (test plan), never from the code.

**Mock stubs are contract-anchored too.** When a rule depends on a collaborator, add a  
`given` list so the generator emits `when(...).thenReturn(...)` in Arrange; without it  
the test would silently fail on the mock's default value:

```yaml
test_cases:
  - name: testTotal_ShouldReturnRepoCount
    inputs: {}
    given:
      - call: batchRepository.count()   # stub the collaborator (Arrange)
        returns: 5
    expect: { returns: 5 }
```

**Divergence is a signal, not a verdict.** When the test plan and the code disagree, the  
generator emits a `BINDING_DRIFT` entry (also written to `_codegen_meta.json` and the  
coverage report) instead of a confusing red:

- `METHOD_NOT_FOUND` — the `target` method declared in the test plan was renamed / removed in code.
- `MISSING_INPUT` — a parameter has no value in `test_cases.inputs`.
- `UNCONSTRUCTABLE_ARG` — a complex object / object list can't be auto-built (e.g.  
  `List<Case>`); the arg is set to `null` and the test fails honestly so a human fills  
  a `call` or a constructible value.
- `MOCK_NOT_STUBBED` — a collaborator is mocked but no `given` stub was provided.

When a generated test fails, **never silently edit it green**. Escalate to a human:  
code is wrong → fix the code; test plan / test is wrong → fix the test plan and regenerate. Both  
fixes must trace back to the requirement — the test is the alarm, not the verdict.

> Generated `.java` files may carry **Chinese** `@DisplayName` / comments. Compile with  
> UTF-8: `javac -encoding UTF-8 ...`, or set `project.build.sourceEncoding=UTF-8` in  
> Maven. JUnit 5 is preferred; if the project already uses JUnit 4, codegen follows 4  
> (the two are never mixed).

## Notes

- Tests are **write-once**: change the test plan, then regenerate — do not hand-edit  
  generated tests.
- Brownfield incremental mode: set `_meta.coverage_mode: incremental` in the  
  test plan, or pass `--mode incremental` to `testing.run`.
- A `codegraph.json` (schema in `templates/codegraph-template.json`) upgrades  
  generated API tests from skeleton to near-executable (real examples, required  
  fields, field-level `FIELD_DRIFT`); without it, plan-only generation is used.

## License

[MIT](LICENSE)
