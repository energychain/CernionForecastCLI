# Changelog

All notable changes to this project will be documented in this file.

The project follows semantic-versioning intent. Before `1.0.0`, command names and core artifact names are intended to be stable, but JSON artifact details may still evolve when necessary.

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
