# SCT — Spec-Code-Test Consistency (Speckit Extension)

A [Spec Kit](https://github.com/github/spec-kit) extension that implements the
**SCT methodology**: keep a single source of truth, derive tests from it, and
gate every change on a three-way consistency check — so quality is *built in*
by the forward chain (spec → code → test), not patched on afterward.

```text
spec ──(merge → SoT)──> acceptance.yaml ──(impact scopes)──> implementation contract
                                                              ↓
                                              implement against the contract
                                                              ↓
SoT × real code ──(codegen derives)──> write-once tests
                                                              ↓
check: confirm the forward chain holds (3-way consistency + execution + coverage gate)
```

## What it provides

5 commands — non-intrusive (zero hooks, original flow untouched):

| Command | Purpose | Key artifact |
|---------|---------|--------------|
| `speckit.sct.merge` | Build `acceptance.yaml` (SoT) from spec / plan / data-model / api-contracts | `acceptance.yaml` |
| `speckit.sct.codegen` | Derive unit + e2e tests from the SoT (write-once) | `tests/generated/*` |
| `speckit.sct.check` | Three-way consistency check spec ↔ code ↔ test + human-review report | `test-report.md` |
| `speckit.sct.impact` | Reverse-trace code changes → affected scenarios (P0/P1/P2) + L1/L2/L3 tier | `change-impact.md` |
| `speckit.sct.e2e` | Bridge impact + SoT into Playwright auto-regression | `e2e/auto_generated/*` |

**Non-intrusive by design.** SCT registers **no lifecycle hooks** and never
alters the original `specify / plan / implement / constitution` flow. The 5
commands above are invoked **manually by the user**, after implementation — the
user decides, per change, whether and when to run `merge` / `codegen` / `check`
/ `impact` / `e2e`. The companion preset (below) only appends optional
methodology hints; it never auto-runs an SCT command either.

## Installation

### Extension (commands + scripts)

Install the released extension from its GitHub archive:

```bash
specify extension add sct --from https://github.com/zqianqian137/spec-kit-sct/archive/refs/tags/v1.0.3.zip
```

Or install from a local checkout during development:

```bash
specify extension add --dev /path/to/spec-kit-sct
```

### Companion preset (optional, hint-only command overrides)

If you want SCT-flavored `speckit.specify` / `speckit.plan` / `speckit.implement`
/ `speckit.constitution` **without** changing their behavior, add the companion
preset. Its overrides only append **optional methodology hints** (keep an
`acceptance.yaml` SoT, run the sct commands after implementation) — they never
auto-run an SCT command and never alter the original flow:

```bash
specify preset add sct --from https://github.com/zqianqian137/spec-kit-sct/archive/refs/tags/v1.0.3.zip
```

The preset lives in `presets/sct/` and requires the `sct` extension (or can be
used standalone for terminology-only projects).

> 已指向真实仓库 `zqianqian137/spec-kit-sct`。catalog 的 `documentation` /
> `download_url` / `homepage` 均指向该仓库，发布时无需再替换。

## When to use it

- You want spec, code, and tests to stay consistent automatically as the project evolves.
- You run brownfield / incremental work and only want to test what actually changed.
- You want AI-assisted SoT extraction and semantic drift detection (`--ai` flags).

## When NOT to use it

- You only need light terminology/template overrides — a **preset** is simpler.
- You expect SCT to auto-run inside your `plan`/`implement` flow — it does not;
  the 5 commands are manual by design, so you must invoke them yourself after
  implementation.

## Quick start

```bash
# 1. Build the single source of truth from your spec artifacts
specify sct.merge --spec specs/001/spec.md --out specs/001/acceptance.yaml

# 2. Derive write-once tests
specify sct.codegen --spec specs/001/acceptance.yaml --out tests/generated

# 3. After implementation, run these manually (nothing auto-fires):
specify sct.impact            # optional: reverse-trace the change first
specify sct.check --spec specs/001/acceptance.yaml --code backend/src/main/java --tests tests/generated

# 4. Reverse-trace a change and (optionally) generate e2e regression
specify sct.impact
specify sct.e2e
```

The `--ai` flag on `merge` and `check` requires `SILICONFLOW_API_KEY`
(optional). When the `codebase-memory-mcp` connector is connected, `sct.impact`
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

`speckit.sct.codegen` generates **executable JUnit unit tests** for business rules
that carry `target` + `test_cases` in the SoT. Generated tests follow the classic
**AAA** structure with a `@DisplayName` intent annotation (JUnit 5):

```java
@Test
@DisplayName("BR-001: VIP3 会员购买 100 元商品应返回 85 元折后价 | 输入 originalPrice=100.0, vipLevel=3 时应返回 85.0")
void testCalculateDiscountPrice_WithVip3_ShouldReturn85() throws Exception {
    // 1. Arrange (准备/输入)
    double originalPrice = 100.0d;
    int vipLevel = 3;
    double expectedResult = 85.0;            // 预期结果来自 SoT
    // 2. Act (执行)
    var actual = service.calculateDiscountPrice(originalPrice, vipLevel);
    // 3. Assert (断言)
    assertEquals(expectedResult, actual, "BR-001: ... 返回值与预期不符");
}
```

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
  SoT, or pass `--mode incremental` to `sct.check`.
- A `codegraph.json` (schema in `templates/codegraph-template.json`) upgrades
  generated API tests from skeleton to near-executable (real examples, required
  fields, field-level `FIELD_DRIFT`); without it, pure-SoT generation is used.

## License

[MIT](LICENSE)
