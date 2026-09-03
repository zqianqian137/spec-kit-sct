---
description: "Testing cases: derive write-once test cases from the test plan across three layers — unit / interface (protocol-agnostic) / e2e (scenario cases only). Manual, non-intrusive"
---

# Testing Cases — Derive the Test Cases

Turn the test plan (`acceptance.yaml`) into **write-once test cases** across three
layers. Nothing here invents an expectation: every input value and assertion comes
from the plan.

| Layer | Derived from | Output | Notes |
|---|---|---|---|
| **L1 unit** | `rules[]` + method signature | language-native tests | emitter is pluggable; Java/JUnit is the current default |
| **L2 interface** | `apis[]` contracts | contract tests | **protocol-agnostic** — see below |
| **L3 e2e** | `acceptance_scenarios` | Playwright scenario cases | **scenario cases only** (G/W/T) |

## Protocol-agnostic by design

The interface layer targets **contracts, not a transport**. A test plan entry may
describe an HTTP endpoint, an RPC method, a message-driven handler, or anything
else — the plan declares *what* must hold, and the emitter decides *how* to drive
it. Do not assume HTTP, and do not write `http`-specific expectations into the plan
unless the contract itself is HTTP.

## Step 0 — Preconditions

| Check | Requirement |
|---|---|
| Test plan | `specs/{feature}/acceptance.yaml` exists (see `testing.plan`) |
| Tier | If `change-impact.md` exists, read the **L1/L2/L3** tier — it decides scope |
| Output dir | `tests/generated/` (or your project's test root) |

## Step 1 — Derive unit + interface cases

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
# --skip-rules / --skip-api-tests skip a layer you do not need
# --only API-F003-001,API-F003-002   targeted regeneration only
# --force                         ignore the hash cache and regenerate
```

Outputs (under `tests/generated/`):

- `test_api_*.py` / `test_rules.py` / `test_scenarios.py` — write-once cases, each
  carrying its intent annotation: `[意图]` + truth source + Given/When/Then
- `COVERAGE_REPORT.md` — plan → test derivation map
- `_codegen_meta.json` — machine-readable metadata including the **sha256 manifest**
  of every generated file (hand-edits are detected by `testing.run`)
- `_scenario_gaps.json` — scenarios that have **no executable adapter** yet; these are
  `UNPROVEN` (skipped), not failures

## Step 2 — e2e scenario cases (only when the tier calls for it)

e2e is **scenario cases only** — no DSL, no action/assertion type system to learn.
Each acceptance scenario in the plan becomes one Playwright case carrying its
Given/When/Then.

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

## Step 3 — Report

Report per layer: how many cases were derived, how many plan items could **not**
become executable cases (and why), and where the artifacts are.

Be explicit about gaps. "12 rules, 4 with `test_cases`, so 4 executable unit tests"
is useful; "coverage complete" is not.

> **Write-once, enforced.** Generated files are tracked by a sha256 manifest.
> To change a test, change the plan and re-run this command — `testing.run` treats
> hand-edited generated files as a gate failure.

Next: `testing.run` (execute, gate, report).
