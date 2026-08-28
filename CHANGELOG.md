# Changelog

All notable changes to the SCT extension are documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [1.0.1] - 2026-08-28

### Added — Java unit tests now follow the classic AAA pattern
- Generated JUnit tests use the **Arrange / Act / Assert** structure with a
  `@DisplayName` intent annotation (JUnit 5) describing the rule, inputs, and expected
  result — matching hand-written unit-test conventions.
- **Signature-bound generation.** When `--code` is given, `codegen` parses the target
  method's **public signature** to bind SoT inputs to parameters (by name, else position)
  and to auto-detect collaborators for `@Mock`. Spring is never used
  (`MockitoExtension` on JUnit 5, `MockitoJUnitRunner` on JUnit 4). The code body is never
  read, so assertions cannot be reverse-engineered from the implementation.
- **SoT-anchored mock stubs.** A new `given` list on a `test_case` emits
  `when(collaborator.method()).thenReturn(value)` in Arrange, so collaborator behavior is
  pinned by the requirement rather than the mock's default. Without `given` on a mocked
  dependency, a `MOCK_NOT_STUBBED` drift is raised.
- **`BINDING_DRIFT` divergence signals.** When the SoT and code disagree, codegen emits a
  structured drift (also in `_codegen_meta.json` and the coverage report) instead of a
  confusing failure: `METHOD_NOT_FOUND`, `MISSING_INPUT`, `UNCONSTRUCTABLE_ARG`,
  `MOCK_NOT_STUBBED`. Each points to the exact element a human must adjudicate.
- **UTF-8 Chinese output.** Generated `.java` files may carry Chinese `@DisplayName` /
  comments; documented the `javac -encoding UTF-8` / Maven `sourceEncoding=UTF-8`
  requirement (supersedes the earlier ASCII-only hardening — the test is now readable and
  still compiles under UTF-8).

### Changed
- The assertion-authority note in generated tests now reads: *the test is the alarm, not
  the verdict* — when it fails, escalate to a human (code wrong → fix code; SoT wrong →
  fix SoT and regenerate). It no longer asserts tests must never be edited to please code;
  the correct action is to resolve the divergence at its source.
- Removed the dead `scripts/python/sct_hooks.py` and `run_sct_hooks.py` (leftover from the
  pre-non-intrusive draft; `extension.yml` declares no hooks, so they were never loaded).

## [1.0.0] - 2026-08-27

### Added
- `speckit.sct.merge` — generate `acceptance.yaml` (single source of truth) from
  spec / plan / data-model / api-contracts, with `--ai` LLM auto-extraction.
- `speckit.sct.codegen` — derive write-once unit/e2e tests from the SoT.
- `speckit.sct.check` — three-way spec ↔ code ↔ test consistency check with
  detailed human-review report (JaCoCo incremental coverage, API execution,
  rule verification, change-point audit), and `--ai` semantic drift analysis.
- `speckit.sct.impact` — reverse-trace code changes to affected spec scenarios
  (P0/P1/P2) with an L1/L2/L3 tier decision; runs after implementation.
- `speckit.sct.e2e` — bridge change-impact + SoT into Playwright auto-regression.
- (Non-intrusive) SCT registers **no lifecycle hooks** — the 5 `speckit.sct.*`
  commands run manually after implementation; the original `specify/plan/
  implement` flow is untouched. (An earlier draft wired `after_implement` /
  `after_plan` / `after_e2e` hooks, but that was dropped so SCT never affects
  the base Spec Kit flow.)
- Optional `codebase-memory-mcp` integration for enriched impact reverse tracing.
- Brownfield incremental mode, CodeGraph-driven request enrichment, full
  exception-value coverage, and multi-dimensional impact matching.

### Changed
- `test_rules.py` is no longer an empty skeleton: each business rule is now
  generated as an **offline static assertion** that verifies the rule has a
  corresponding piece of evidence in the code (annotation / method / exception /
  constant). Rules can carry a `checks` list in the SoT for precise assertions;
  anchorless rules fail clearly instead of being silently skipped.
- `test_scenarios.py` now fails with a clear pointer (API / E2E layers) instead of
  a false-green `NotImplementedError`.
- `speckit.sct.codegen` accepts `--code` (code root for rule assertions, default
  `backend/src/main/java`); override at runtime with env `SCT_CODE_ROOT`.

### Non-intrusive redesign
- **Removed all lifecycle hooks.** `extension.yml` no longer declares
  `provides.hooks`. SCT never alters the original `specify / plan / implement /
  constitution` flow — the 5 `speckit.sct.*` commands are invoked **manually by
  the user after implementation**; nothing auto-fires. This honors the principle
  that test steps (merge / codegen / check / impact / e2e) wait until after
  implementation and are executed only when the user confirms.
- The companion preset (`presets/sct/`) is now **hint-only**: its overrides of
  `speckit.specify / plan / implement / constitution` append optional SCT
  methodology reminders but never auto-run an SCT command and never change the
  original command behavior.

### Hardened — unit tests are SoT-anchored (anti code-bias)
- Generated Java unit tests now carry an inline **assertion-authority comment**
  citing `acceptance.yaml#rules[<id>]` as the sole source of truth, explicitly
  stating the expectation comes from the requirement, not the implementation, and
  must fail (not be edited to please code) if the implementation deviates.
- `gen_java_unit_tests` documents that it reads only `rule.target / mocks /
  test_cases` and never opens the code body to synthesize assertions — the unit
  test is derived from the SoT, the code is a black box under test.
- The assertion-authority comment is emitted in ASCII (English) so generated
  `.java` files compile under a default (GBK) Windows `javac` without `-encoding
  UTF-8`.
