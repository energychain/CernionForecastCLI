# Changelog

All notable changes to this project will be documented in this file.

The project follows semantic-versioning intent. Before `1.0.0`, command names and core artifact names are intended to be stable, but JSON artifact details may still evolve when necessary.

## [Unreleased]

### Added

- Added executable availability semantics for point-in-time backtests: `event_time`, `available_at`, `ingested_at` and `as_of` are separate concepts; `e2e` rejects missing availability proof unless an explicit `--availability-mode` is selected and materializes the latest value version available at `as_of`.
- Added provisional integrity decisions for assumed availability modes, with `VERIFIED`/`ASSUMED`/`UNVERIFIABLE` evidence classification.
- Added artifact-manifest binding plus `verify-receipt` so `integrity_receipt.json` can verify SHA-256 hashes of persisted E2E artifacts.
- Added `integrity_receipt.json` as a versioned machine-readable `CET-FC-DIC-001` evidence receipt for E2E runs, linked to import, training, prediction, horizon, quality and gate artifacts.
- Added JSON Schemas under `docs/schemas/` for canonical time series, information cutoff, integrity receipt and validation errors.
- Added strict productive conformance schemas for canonical time series, information cutoff, integrity receipts and validation errors, separating permissive exchange objects from contract-bound production evidence.
- Added `verify-receipt` to verify artifact-manifest hashes bound by `integrity_receipt.json`.

### Changed

- Refactored integrity-related responsibilities out of `cli.py` into `availability.py`, `versioning.py`, `integrity.py` and `evidence.py`, with executable conformance tests under `tests/conformance/`.

### Fixed

- `--allow-partial` no longer accepts forecasts with duplicate timestamps or predictions outside the expected horizon; it only tolerates missing values.
- Partial scoring now keeps the forecast-day expected interval count independent of delivered prediction count and reports `coverage`, `forecast_coverage` and `matched_coverage` separately.
- Integrity receipts now separate `integrity_decision` from `forecast_acceptance_decision`; a poor forecast no longer invalidates data-integrity evidence.
- E2E point-in-time materialization rejects equally ranked conflicting value versions unless a stable `value_version`/`revision` ordering is supplied.

### Documentation

- Added `docs/data-integrity-contract.md` as the binding proposed fachliche data-integrity contract (`CET-FC-DIC-001`) for CernionForecastCLI, CET Forecast API and forecast validation work. The contract is explicitly `Proposed / Nicht freigegeben`; implementations may only claim conformance to implemented and tested parts until section 14 is resolved.

## [0.2.2] - 2026-10-09

### Critical fixes

- Enforced the D-2 information cutoff in `e2e`: history containing D-1 or D values is rejected before API upload, and the cutoff is recorded in E2E artifacts.
- Tightened MSCONS series selection so `series_id` no longer masks ambiguous message/location/OBIS candidates; operators must select exactly one candidate with MeLo/OBIS/CCI/message/document filters.
- Made MSCONS timestamp handling internally consistent: source timezone defaults to `Europe/Berlin`, is persisted in provenance, and ambiguous/nonexistent local DST timestamps are rejected.
- Scoring and acceptance now validate the requested forecast horizon against forecast date, timezone and PT15M grid instead of treating a partial prediction result as complete.
- Baselines respect the D-2 availability cutoff and use local calendar-day shifts instead of UTC-only timedeltas.

### Hardened

- Quality defaults are production-strict (`--quality-policy strict`, `--min-coverage 1.0`); exploratory runs must opt into lenient/warn behavior.
- Remote HTTP API base URLs are rejected unless explicitly enabled for local/test endpoints with `--allow-insecure-http`; `doctor` now fails if required API routes are missing.
- Acceptance/E2E reports handle undefined WAPE/bias as a valid metric state instead of crashing on zero-actual totals.

## [0.2.1] - 2026-10-09

### Hardened

- Config profiles can now set explicit boolean flags such as `quiet`, `resume_out` and `debug_http`.
- History-only runs no longer carry an unused training request object in `run.json`; context stays in `forecast_context`/`site_context`.
- `batch-history` calls the history command implementation directly instead of recursively invoking the top-level CLI parser for every file.
- MSCONS/EDIFACT parsing now rejects malformed trailing release characters instead of silently dropping them.
- Optional `--debug-http` logging emits sanitized HTTP diagnostics without exposing tokens.

### Documentation

- Security notes now clarify that token verification sends the token to the verify endpoint while still redacting it from logs and artifacts.

## [0.2.0] - 2026-10-09

### Added

- Production-oriented CLI flows for `history`, `enroll`, `train`, `predict`, `resume`, `score`, `acceptance-test`, `e2e`, `batch-history`, `batch`, `doctor` and `describe`.
- JSON, CSV and MSCONS/EDIFACT input support.
- MSCONS envelope provenance preservation in local artifacts and forecast result envelopes.
- Weather/site/context metadata flags and validation for city-level location semantics.
- Data-quality reports, idempotency keys, processed-ledger support and structured run artifacts.
- Forecast scoring with residual exports and threshold exit code `50`.
- Operational acceptance testing against naive baselines.
- Live E2E workflow with history-depth preflight requiring at least 28 observed days before D-2 by default.
- Synthetic example data under `examples/`.
- Community documentation, security policy and contribution guidance.

### Security

- Token values are read from environment or token files and are not written to artifacts.
- HTTP redirects are refused to avoid forwarding credentials to unexpected origins.

## [0.1.0] - Initial local version

- Initial command-line client skeleton for CET forecast workflows.
