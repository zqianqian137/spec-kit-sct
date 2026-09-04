# SCT — Spec-Code-Test Consistency (Speckit Extension)

> **SCT 2.0 一句话：不追求"生成更多测试"，而是用最少的测试和最可信的证据，证明 Spec 被正确实现。**

A [Spec Kit](https://github.com/github/spec-kit) extension that turns the
requirement into a **quality gate** through a minimal evidence chain:

```text
Spec Kit (需求，骨架所有)
   ↓
Acceptance Contract (acceptance.yaml：需求与测试之间的标准契约)
   ↓
Test Design   (testing.design：测试设计 + 制定任务)
   ↓
Evidence      (testing.run：执行结果 + 覆盖 + 缺陷 + 漂移)
   ↓
PASS / BLOCK / UNPROVEN (质量门禁)
```

Three non-negotiable principles hold the chain honest:

| # | 原则 | 含义 |
|---|---|---|
| ① | **Oracle Independence** | 期望结果只来自 Spec/Contract，**绝不来自 Code**（反推断言 = 自己出题自己改卷） |
| ② | **Write-once + Integrity** | 可以生成测试，但**不能反复改测试直到通过**（sha256 manifest 强制） |
| ③ | **PASS / BLOCK / UNPROVEN** | 证据不足不强行判定 PASS（`UNPROVEN ≠ PASS`） |

> 中文简介：SCT 是 spec-kit 主骨架之外的**测试域扩展**——从 `spec.md` 派生测试契约
> `acceptance.yaml`，`testing.design` 做测试设计与制定任务（可调用 skill 池提升设计质量），
> `testing.run` 真实执行并用三态证据门（PASS/BLOCK/UNPROVEN）判定放行。面向内网/离线环境：
> 确定性脚本优先，AI 只辅助分析/生成/建议，最终判定永远由确定性引擎给出。

详细路线图见 [ROADMAP.md](./ROADMAP.md)。

## Methodology

SCT is a **test-domain extension for Spec Kit**. It does not replace the  
backbone, invent a new source of truth, or dictate a language. It answers five  
practical questions — the same five a test lead asks before a release.

| # | Question   | How SCT answers it                                                                   |
| - | ---------- | ------------------------------------------------------------------------------------ |
| 1 | 测试不漏测？     | every acceptance point in the spec is mapped to a test — **no test = 漏测, gated**     |
| 2 | 需求都实现了？    | each requirement is checked against the code: declared-but-missing is a gate failure |
| 3 | 报告能不能人工审核？ | one report: what was tested, what was not, and why — reviewable, and re-runnable     |
| 4 | 测试手段齐不齐？   | three layers: **unit → API → e2e** (e2e = scenario cases only)                       |
| 5 | 门禁硬不硬？     | **coverage ≥ 90%**, **cases 100% passing**, no missing coverage → merge blocked      |

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
`check` requires:

- an API contract → a test that exercises it (success **and** each declared error case)
- a business rule → a test asserting it
- an acceptance scenario → an e2e case

Anything in the plan without a test is reported as **MISSING_TEST** and blocks  
the merge. Anything declared in the plan but absent from the code is reported as  
**MISSING_IMPL** and blocks the merge. Together these answer question 2: *has  
the code actually implemented what the requirement asked?*

### 3. Three layers — unit, API, e2e (scenarios only)

| Layer       | Derived from                  | Output                    | Notes                                                                          |
| ----------- | ----------------------------- | ------------------------- | ------------------------------------------------------------------------------ |
| **L1 unit** | `rules[]` + method signatures | language-native tests     | **language-agnostic** — Java/JUnit today via adapter; the emitter is pluggable |
| **L2 API**  | `apis[]` + contracts          | executable HTTP tests     | success path + every declared error code                                       |
| **L3 e2e**  | `acceptance_scenarios`        | Playwright scenario cases | **scenario cases only** — G/W/T, no DSL to learn                               |

Two principles keep the layers honest:

- **Assertions never come from code.** The code is a black box under test. Input  
  *values* and expected outcomes come from the test plan; the code only supplies  
  the *shape* (parameter types). Inferring expectations from the implementation  
  is 自己出题自己改卷 — setting the exam and grading it yourself.
- **Generated tests are write-once.** Change the test plan and regenerate.  
  Hand-editing is detected via a sha256 manifest and blocks the gate.

### 4. The gate blocks — 90% coverage, 100% passing

`check` produces structured evidence and takes the strictest verdict:

| Evidence             | PASS                                                 | BLOCK                 | UNPROVEN                     |
| -------------------- | ---------------------------------------------------- | --------------------- | ---------------------------- |
| `NO_MISSING`         | every plan item has a test **and** an implementation | any 漏测 / 未实现          | —                            |
| `LINE_COVERAGE`      | ≥ **90%**                                            | below 90%             | no `--jacoco` + `--base`     |
| `TEST_EXECUTION`     | all cases pass (100%)                                | any failure           | no `--junit` / zero executed |
| `ARTIFACT_INTEGRITY` | generated files match their manifest                 | hand-edited / missing | legacy output                |

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

## What it provides

**3 commands** — non-intrusive (zero hooks, original flow untouched):

| Command                 | Purpose                                                                                                                                                                                                                          | Key artifact                                |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| `speckit.testing.plan`  | **Auto-generate the test plan** from `spec.md` + plan artifacts (`plan.md` / `data-model.md` / `api-contracts.md`); optional change-impact tiering (P0/P1/P2 + L1/L2/L3)                                                         | `acceptance.yaml`, `change-impact.md`       |
| `speckit.testing.design` | **Test design + task planning**: turn the plan into a test design, then derive write-once cases across three layers — unit (language-pluggable), interface (**protocol-agnostic**), e2e (**scenario cases only**). May consult a skill pool to raise design quality | `tests/generated/*`, `e2e/auto_generated/*` |
| `speckit.testing.run`   | **Execute + gate + report**: verify requirements are implemented, apply the hard gate (coverage ≥90%, 100% passing, no missing coverage), write a unified report (unit + interface + coverage + defects + drift + change impact) | `test-report.md`                            |

**Mostly non-intrusive, one opt-in hook.** SCT never alters the original  
`specify / plan / tasks / implement` flow. It registers **one** optional  
lifecycle hook — `after_plan` — which *suggests* auto-generating the test plan  
right after `specify plan` (you can skip it; the generated plan is always  
hand-enrichable). Everything else is **manual**: the user decides, per change,  
whether and when to run `plan` / `cases` / `run`.

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
specify extension add sct --from https://github.com/zqianqian137/spec-kit-sct/archive/refs/tags/v2.0.0.zip
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
- You want AI-assisted SoT extraction and semantic drift detection (`--ai` flags).

## When NOT to use it

- You want the original Speckit flow to stay untouched AND want light  
  overrides — install the extension only and manually run `sct.*` per change;  
  there is no auto-attach preset in this release.
- You expect SCT to auto-run inside your `plan`/`implement` flow — it does not;  
  the 6 commands are manual by design, so you must invoke them yourself after  
  implementation.

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
every business rule registered in the SoT has a corresponding piece of evidence in  
the code (annotation / method / exception / constant), without starting any service.  
To make a rule's assertion precise, add a `checks` list to the rule in your SoT  
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
`codegen` receives the code root via `--code` (default `backend/src/main/java`);  
you can also override at runtime with env `SCT_CODE_ROOT`.

If a rule has **no `checks`**, codegen falls back to a best-effort loose text match;  
if that still finds nothing, the test **fails clearly** (telling you to add `checks`)  
instead of being silently skipped. Acceptance scenarios are end-to-end journeys and  
are validated at the API / E2E layers, so `test_scenarios.py` fails with a clear  
pointer rather than a false green.

## Java unit tests — AAA pattern, signature-bound, SoT-anchored

`speckit.testing.design` generates **executable JUnit unit tests** for business rules  
that carry `target` + `test_cases` in the SoT. Generated tests follow the classic  
**AAA** structure with a `@DisplayName` intent annotation (JUnit 5):

增加测试计划生成立马也是测试design，代码实现之后测试执行，也可以--skip-api-tests --skip-unit-tests ...，测试cases，\`speckit.testing.design\`改为\`speckit.testing.design\`  
也等于测试设计和制定任务（可以调用项组ga专用的skill池提高测试设计质量），便于后面的执行，\`speckit.testing.run\`

How the three JUnit parts are sourced — so the test is **not biased by the code**:

- **Inputs (values)** come from `test_cases.inputs` in the SoT.
- **Inputs (shape)** — parameter types / order — come from the **public signature**  
  of the target method, parsed at generation time when `--code` is passed. The  
  generator binds SoT inputs to parameters by name (else position) and auto-detects  
  collaborators (constructor params + injected fields) to `@Mock` them — Spring is  
  **never** used (`@ExtendWith(MockitoExtension.class)` on JUnit 5,  
  `@RunWith(MockitoJUnitRunner.class)` on JUnit 4). It reads the signature, not the  
  method body, so it cannot reverse-engineer the assertion.
- **Assertions / exceptions** come from `test_cases.expect` (SoT), never from the code.

**Mock stubs are SoT-anchored too.** When a rule depends on a collaborator, add a  
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

**Divergence is a signal, not a verdict.** When the SoT and the code disagree, the  
generator emits a `BINDING_DRIFT` entry (also written to `_codegen_meta.json` and the  
coverage report) instead of a confusing red:

- `METHOD_NOT_FOUND` — the SoT target method was renamed / removed in code.
- `MISSING_INPUT` — a parameter has no value in `test_cases.inputs`.
- `UNCONSTRUCTABLE_ARG` — a complex object / object list can't be auto-built (e.g.  
  `List<Case>`); the arg is set to `null` and the test fails honestly so a human fills  
  a `call` or a constructible value.
- `MOCK_NOT_STUBBED` — a collaborator is mocked but no `given` stub was provided.

When a generated test fails, **never silently edit it green**. Escalate to a human:  
code is wrong → fix the code; SoT / test is wrong → fix the SoT and regenerate. Both  
fixes must trace back to the requirement — the test is the alarm, not the verdict.

> Generated `.java` files may carry **Chinese** `@DisplayName` / comments. Compile with  
> UTF-8: `javac -encoding UTF-8 ...`, or set `project.build.sourceEncoding=UTF-8` in  
> Maven. JUnit 5 is preferred; if the project already uses JUnit 4, codegen follows 4  
> (the two are never mixed).

## Notes

- Tests are **write-once**: change the SoT, then regenerate — do not hand-edit  
  generated tests.
- Brownfield incremental mode: set `_meta.coverage_mode: incremental` in the  
  SoT, or pass `--mode incremental` to `testing.run`.
- A `codegraph.json` (schema in `templates/codegraph-template.json`) upgrades  
  generated API tests from skeleton to near-executable (real examples, required  
  fields, field-level `FIELD_DRIFT`); without it, pure-SoT generation is used.

## License

[MIT](LICENSE)
