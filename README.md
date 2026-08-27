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

5 commands + 4 hook points (zero changes to Spec Kit core):

| Command | Purpose | Key artifact |
|---------|---------|--------------|
| `speckit.sct.merge` | Build `acceptance.yaml` (SoT) from spec / plan / data-model / api-contracts | `acceptance.yaml` |
| `speckit.sct.codegen` | Derive unit + e2e tests from the SoT (write-once) | `tests/generated/*` |
| `speckit.sct.check` | Three-way consistency check spec ↔ code ↔ test + human-review report | `test-report.md` |
| `speckit.sct.impact` | Reverse-trace code changes → affected scenarios (P0/P1/P2) + L1/L2/L3 tier | `change-impact.md` |
| `speckit.sct.e2e` | Bridge impact + SoT into Playwright auto-regression | `e2e/auto_generated/*` |

Hooks (auto-triggered): `after_plan → sct.merge` (suggest), `after_implement →
sct.impact` then `sct.check`, `after_e2e → sct.e2e`. (`before_commit` is
intentionally omitted — this workflow has no commit step.)

## Installation

### Extension (commands + hooks + scripts)

Install the released extension from its GitHub archive:

```bash
specify extension add sct --from https://github.com/zqianqian137/spec-kit-sct/archive/refs/tags/v1.0.0.zip
```

Or install from a local checkout during development:

```bash
specify extension add --dev /path/to/spec-kit-sct
```

### Companion preset (lightweight command overrides)

If you only want the SCT-flavored `speckit.specify` / `speckit.plan` /
`speckit.implement` / `speckit.constitution` command overrides without the full
extension machinery, add the companion preset:

```bash
specify preset add sct --from https://github.com/zqianqian137/spec-kit-sct/archive/refs/tags/v1.0.0.zip
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
- Your team has no Spec Kit `implement`/`plan` flow (the hooks attach to those).

## Quick start

```bash
# 1. Build the single source of truth from your spec artifacts
specify sct.merge --spec specs/001/spec.md --out specs/001/acceptance.yaml

# 2. Derive write-once tests
specify sct.codegen --spec specs/001/acceptance.yaml --out tests/generated

# 3. After implementation, the after_implement hook auto-runs impact + check.
#    Or run manually:
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
`codegen` receives the code root via `--code` (the `after_implement` hook auto-detects
it; you can also override at runtime with env `SCT_CODE_ROOT`).

If a rule has **no `checks`**, codegen falls back to a best-effort loose text match;
if that still finds nothing, the test **fails clearly** (telling you to add `checks`)
instead of being silently skipped. Acceptance scenarios are end-to-end journeys and
are validated at the API / E2E layers, so `test_scenarios.py` fails with a clear
pointer rather than a false green.

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
