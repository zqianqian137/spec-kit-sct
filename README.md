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
specify extension add sct --from https://github.com/zqianqian137/spec-kit-sct/archive/refs/tags/v1.0.0.zip
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
