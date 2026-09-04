---
description: "Testing design: turn the test plan into a test design + test tasks (unit / interface / e2e), then derive write-once test cases. May consult a skill pool to raise design quality. Manual, non-intrusive"
---

# Testing Design — Test Design + Task Planning

Turn the test plan (`acceptance.yaml`) into a **test design**: the concrete test
tasks and cases that will later be executed by `testing.run`. This is the "design
and task-planning" stage between the plan and the evidence.

```
testing.plan (契约)  →  testing.design (测试设计 + 制定任务)  →  testing.run (执行 + 证据)
```

## What this stage produces

| Layer | Derived from | Design output | Notes |
|---|---|---|---|
| **L1 unit** | `rules[]` + method signature | unit-test tasks + cases | emitter is pluggable; Java/JUnit is the current default |
| **L2 interface** | `apis[]` contracts | contract-test tasks + cases | **protocol-agnostic** — the contract says *what*, the adapter says *how* |
| **L3 e2e** | `acceptance_scenarios` | e2e scenario cases | **scenario cases only** (G/W/T) |

The design output is **write-once**: generated cases are tracked by a sha256
manifest, and `testing.run` treats hand-edited generated files as a gate failure.

## Step 0 — Preconditions

| Check | Requirement |
|---|---|
| Test plan | `specs/{feature}/acceptance.yaml` exists (see `testing.plan`) |
| Tier | If `change-impact.md` exists, read the **L1/L2/L3** tier — it decides scope |
| Output dir | `tests/generated/` (or your project's test root) |

## Step 1 — Design (may consult a skill pool to raise quality)
### Step 0.5 — Validate the contract (P0-1)

> **契约校验（v2.1 起，P0-1）**：契约进入下游前必须通过确定性校验
> （结构 + ID 唯一性 + 格式）。BLOCK 时先修契约，不要带着坏契约往下走。
>
> ```bash
> python $SCT_EXT_HOME/scripts/contract-validate.py --contract specs/{feature}/acceptance.yaml
> # 退出码 0=PASS 1=BLOCK 2=UNPROVEN；--json <path> 可落结构化结果
> ```


Before generating code, the design step decides **what to test and how**, anchored
on the contract. You may invoke a project skill pool (testing / QA expertise) here
to raise design quality — the skill pool helps *design* the cases; it never
changes the contract, and it never turns a failing test green.

For each plan item, the design answers:

- **rules[]** → which are executable unit tests (have `target` + `test_cases`),
  which are static anchors (`checks`), and which still need human input
- **apis[]** → success path + every declared error code → one case each
- **acceptance_scenarios** → one e2e scenario case each (positive / negative)

Report the design gap explicitly: "12 rules, 4 with `test_cases` → 4 executable
unit tests" is useful; "coverage complete" is not.

## Step 2 — Derive the write-once cases

```bash
python $SCT_EXT_HOME/scripts/acceptance-codegen.py \
  --spec specs/{feature}/acceptance.yaml \
  --out tests/generated/
# --code backend/src/main/java    code root for rule anchoring (or env SCT_CODE_ROOT)
# --java-test-root src/test/java  where generated unit tests land
# --junit auto|4|5                JUnit version (auto-detected by default)
# --base-url http://host:port     interface test target (or env BASE_URL)
# --codegraph codegraph.json      optional: real-code examples, FIELD_DRIFT detection
# --module <name>                 multi-module: generate under {out}/{module}/
# --skip-unit-tests               skip the unit-test layer (interface-only projects)
# --skip-api-tests                skip the interface-test layer (library/tool projects)
# --only API-F003-001,API-F003-002   targeted regeneration only
# --force                         ignore the hash cache and regenerate
```

Outputs (under `tests/generated/`):

- `test_api_*.py` / `test_rules.py` / `test_scenarios.py` — write-once cases, each
  carrying its intent annotation: `[意图]` + truth source + Given/When/Then
- `COVERAGE_REPORT.md` — plan → test derivation map
- `_codegen_meta.json` — machine-readable metadata including the **sha256 manifest**
  of every generated file (hand-edits are detected by `testing.run`)
- `_scenario_gaps.json` — scenarios with **no executable adapter** yet; these are
  `UNPROVEN` (skipped), not failures

## Step 3 — e2e scenario cases (only when the tier calls for it)

e2e is **scenario cases only** — no DSL, no action/assertion type system to learn.
Each acceptance scenario becomes one Playwright case carrying its Given/When/Then.

```bash
python $SCT_EXT_HOME/scripts/change-impact-e2e-bridge.py \
  --spec specs/{feature}/acceptance.yaml \
  --impact specs/{feature}/change-impact.md \
  --out e2e/auto_generated/
# --include-p2     include P2 scenarios (default: P0/P1 only)
# --dry-run        print without writing
```

Run this for **L3** changes (new feature / multi-module / migration); L1 and L2
normally do not need it.

Two ways to consume the output — SCT is a *generator*, not a runner:

1. **Path A — run it**: execute the generated specs with Playwright directly.
2. **Path B — hand it off**: the bridge also emits `_intent_tests.json` for an
   external test platform to consume (works even where Playwright is not installed).

## Step 4 — Report

Report per layer: how many cases were designed and derived, how many plan items
could **not** become executable cases (and why), and where the artifacts are.

> **Write-once, enforced.** To change a test, change the plan and re-run this
> command — `testing.run` treats hand-edited generated files as a gate failure.

Next: `testing.run` (execute, gate, evidence).
