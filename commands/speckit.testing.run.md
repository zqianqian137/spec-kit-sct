---
description: "Testing run: execute the derived tests, verify requirements are implemented, apply the hard gate (coverage ≥90%, cases 100% passing, no missing coverage) and write a human-reviewable report. Honest PASS/BLOCK/UNPROVEN"
---

# Testing Run — Execute, Gate, Report

Run the derived tests, check the code actually implements what the plan declares,
apply the gate, and produce a report a human can review.

```
testing.plan  →  testing.cases  →  testing.run
                                    ├─ execute (unit + interface + e2e)
                                    ├─ gate    (PASS 0 / BLOCK 1 / UNPROVEN 2)
                                    └─ report  (requirement × code × test matrix)
```

## Step 0 — Preconditions

| Check | Requirement |
|---|---|
| Tests derived | `tests/generated/` exists (see `testing.cases`) |
| Code root | `--code` points at the real source root (the directory where you see `com/...`) |
| Evidence | `--junit` (execution results) and `--jacoco` + `--base` (coverage) — **without these the verdict is UNPROVEN, not PASS** |

## Step 1 — Execute and gate

```bash
python $SCT_EXT_HOME/scripts/consistency-check.py \
  --spec specs/{feature}/acceptance.yaml \
  --code backend/src/main/java \
  --tests tests/generated/ \
  --junit tests/generated/junit-report.xml \
  --jacoco backend/target/site/jacoco/jacoco.xml \
  --base main \
  --report specs/{feature}/reports/test-report.md
# --impact specs/{feature}/change-impact.md   priorities in the report
# --mode full|incremental       coverage mode (default: plan's _meta.coverage_mode)
# --module <name>               multi-module: {code}/{module}/src/main/java
# --module-src src/main/kotlin  module source path when not src/main/java
# --skip-api-tests / --skip-rule-tests   skip a layer (its evidence becomes N/A)
# --prereq-timeout 3.0          interface reachability pre-check timeout
```

### Interface layer pre-check

When interface tests will run, the tool probes the target first. Unreachable target
→ **exit code 3** (a question, not a failure): provide credentials / fix the
environment, or re-run with `--skip-api-tests`.

## Step 2 — The gate

Four evidence items, each judged independently; the overall verdict is the strictest:

| Evidence | PASS | BLOCK | UNPROVEN |
|---|---|---|---|
| `NO_MISSING` | every plan item has a test **and** an implementation | 漏测 (`MISSING_TEST`) / 未实现 (`MISSING_IMPL`) | — |
| `LINE_COVERAGE` | incremental line coverage ≥ **90%** | < 90% | no `--jacoco` + `--base` |
| `TEST_EXECUTION` | all cases pass (**100%**) | any failure/error | no `--junit` or zero executed |
| `ARTIFACT_INTEGRITY` | generated files match their sha256 manifest | hand-edited / missing | legacy output without manifest |

**Exit codes: PASS 0 · BLOCK 1 · UNPROVEN 2.** Anything other than 0 blocks the merge.
`UNPROVEN ≠ PASS` — missing evidence must never masquerade as green.

## Step 3 — Optional: verify the tests are real

The gate above proves "tests exist, run, and cover". It does not prove they are not
hollow. When you need that (typically L3), run the effectiveness check:

```bash
python $SCT_EXT_HOME/scripts/verification-gate.py \
  --spec specs/{feature}/acceptance.yaml \
  --code backend/src/main/java \
  --tests tests/generated/ \
  --tasks specs/{feature}/tasks.md \
  --surefire backend/target/surefire-reports
# --mutation-score 78.0   optional PITest/mutmut score to gate on (default threshold 60)
# --skip-compile          skip the compile gate
```

| Check | Catches |
|---|---|
| `PHANTOM_TASK` | tasks.md says `[X]` but no class/method evidence exists — claimed done, not done |
| `COMPILE` | generated tests were never compiled |
| `REAL_TESTS` | the report shows **0 actually executed** tests |
| `MUTATION` | injected defects don't turn tests red |

Same three-state output: **PASS / BLOCK / UNPROVEN**.

## Step 4 — The report is the deliverable

The verdict is one line; the report is what a human reviews. It contains:

- the **requirement × code × test matrix** — what is covered, what is not, and why not
- per-layer execution results (pass / fail / skip counts)
- coverage — overall and incremental, with the classes this change touched
- a **missing-coverage list**: the concrete items a human must still handle
- drift classification, so a failure points at the link that broke

## Failure triage — fix the link that broke

| Signal | Broken link | Fix |
|---|---|---|
| `MISSING_IMPL` | plan → code | implement what the plan declares |
| `MISSING_TEST` | plan → test | re-run `testing.cases` (never hand-write a test to silence it) |
| `FIELD_DRIFT` / `BINDING_DRIFT` | plan ↔ code | reconcile which side is right, then regenerate |
| `MISSING_INTENT` | test without intent | regenerate intent-carrying cases |
| `ARTIFACT_INTEGRITY` | write-once violated | re-run `testing.cases --force` |

> The gate is a **confirmation gate, not a rescue net**. A pipeline that depends on
> `testing.run` to catch what the forward flow should have prevented is a process
> problem — fix the flow, not the report.
