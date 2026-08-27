# Changelog

All notable changes to the SCT extension are documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

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
- Four hook points: `after_implement` (impact → check), `after_plan` (merge),
  `after_e2e` (bridge). `before_commit` intentionally omitted (no commit flow).
- Optional `codebase-memory-mcp` integration for enriched impact reverse tracing.
- Brownfield incremental mode, CodeGraph-driven request enrichment, full
  exception-value coverage, and multi-dimensional impact matching.
