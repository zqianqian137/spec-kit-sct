---
description: "SCT check: three-way consistency check (spec ↔ code ↔ test) with detailed test report. In post timing mode, first triggers deferred test generation (code is final)"
---

# SCT Consistency Check (spec ↔ code ↔ test)

Validate three-way consistency and produce the **detailed test report**
(`specs/{feature}/reports/test-report.md`) — the primary artifact for human review:
did tests cover the changed code, and is the business logic correctly implemented?

## Step 0 — Gates (L1 fast path → deferred generation)

**Gate 1 — L1 fast path**: read `变更级别` from `specs/{feature}/change-impact.md`.
If **L1**: run only the existing regression suite and give a one-line verdict —
no report file, no three-way check, no deferred generation:

```bash
pytest tests/ --junitxml=tests/generated/junit-report.xml -q
```

Output: `L1 回归: X passed, Y failed` (+ failed case names if any).
- All green → END here (L1 does not gate on coverage).
- Any failure → **escalate to L2**: continue with the full flow below
  (the change is bigger than the tier suggested).

**Gate 2 — Deferred generation (post timing mode)**:

Read `_meta.test_timing` from `specs/{feature}/acceptance.yaml` (**default
`post`** — the SCT canonical ordering is Spec→Code→Test).

If `post` AND `tests/generated/` is missing or contains no `test_*.py` files:

1. The implementation phase was granted exclusive AI resources; tests were
   intentionally deferred. **Generate them now** — the code is final, so this
   is the best moment: CodeGraph export reflects the real implementation
   (accurate examples, required-field annotations, FIELD_DRIFT).

2. If a CodeGraph tool is available, re-export `codegraph.json` from the
   current codebase first, then run:

   ```bash
   python $SCT_EXT_HOME/scripts/acceptance-codegen.py \
     --spec specs/{feature}/acceptance.yaml \
     --out tests/generated/ \
     --codegraph codegraph.json
   ```

   Without CodeGraph, omit `--codegraph` (pure-SoT generation).

3. Announce the generation summary, then continue to Step 1.

If `pre` (tests already generated before implementation) or tests exist,
continue directly.

## Step 1 — Execute the tests

```bash
pytest tests/generated/ --junitxml=tests/generated/junit-report.xml
```

JaCoCo (Java projects): run the build with coverage enabled and locate
`jacoco.xml` (e.g. `backend/target/site/jacoco/jacoco.xml`).

## Step 2 — Run the checker

```bash
python $SCT_EXT_HOME/scripts/consistency-check.py \
  --spec specs/{feature}/acceptance.yaml \
  --code backend/src/main/java \
  --tests tests/generated/ \
  --jacoco backend/target/site/jacoco/jacoco.xml \
  --junit tests/generated/junit-report.xml \
  --impact specs/{feature}/change-impact.md \
  --report specs/{feature}/reports/test-report.md
```

Coverage mode resolution: CLI `--mode` > SoT `_meta.coverage_mode` > `full`.
CodeGraph annotations and FIELD_DRIFT are auto-merged into the report via
`tests/generated/_codegen_meta.json` (or pass `--codegen-meta` explicitly).

## Step 3 — Report and gate

Present the test report summary:
- HIGH drift count (gate: 0) and failed cases
- Incremental line coverage (gate: ≥ 90%)
- Changed-point review table (section 5) — pending human review sign-off
- FIELD_DRIFT count (section 6.2, advisory)

Gate: FAIL blocks merge.

**失败归因（修断掉的环节，不是盲目重试）**——check 是前向保证链的最终确认门，
FAIL 意味着某一环断了，按漂移类型定位：

| 漂移/失败 | 断掉的环节 | 修复方向 |
|---|---|---|
| `MISSING_IMPL` | Spec→Code（实现没按 SoT 契约写） | 对照 change-impact.md「实现需求」补实现 |
| `MISSING_TEST` | Code→Test 派生缺失 | 跑 `sct.codegen`（勿手补测试） |
| `UNSPEC_API` | SoT 登记缺失 | 补 SoT 条目再 codegen |
| 失败案例 | 业务实现 ≠ SoT 口径 | **举证责任在 code 侧**：默认 SoT 是真相 → 修 code；仅当有证据证明 spec 本身错了（需求理解错误/口径过时）才改 SoT（连带改 spec 再重生成）。禁止"测试迁就实际行为"——那是放弃验证 |

一次归因修复后重跑 `sct.check` 属正常；**反复 FAIL 说明前向链路没在运转**
（实现没对照契约 / 测试非派生）——停下来修流程，不要继续打补丁。
