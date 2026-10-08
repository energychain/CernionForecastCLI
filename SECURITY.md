# Security Policy

## Supported versions

This repository is pre-1.0. Security fixes are applied to the default branch. Releases should document whether a fix is included.

## Reporting a vulnerability

Please do not open a public GitHub issue for security-sensitive findings.

Report privately to the maintainers via the security contact configured on the GitHub repository, or contact STROMDAO/Cernion through the established business support channel if no GitHub private advisory is available.

Include:

- affected version or commit,
- command used,
- impact,
- safe reproduction steps,
- redacted logs/artifacts.

Do not include API tokens, real customer datasets, real MSCONS payloads, credentials, private keys or unredacted tenant information.

## Token and credential handling

The CLI reads tokens from `CET_API_TOKEN` or `--token-file`. It is designed not to write token values into `run.json`, `result.json`, `metrics.json`, reports or logs.

Users should still:

- store token files outside the repository,
- set restrictive file permissions such as `chmod 600 token.txt`,
- avoid shell history exposure,
- rotate tokens if they were pasted into logs, issues or chat.

## Data sensitivity

Energy time series, MSCONS messages, meter identifiers and utility/customer process data can be sensitive. Public issue reports should use synthetic data from `examples/` or minimal redacted reproductions.

Do not submit:

- live customer load profiles,
- real market-communication envelopes,
- API tokens or connection strings,
- private tenant IDs unless explicitly cleared by the maintainer process.

## Live API tests

Tenant-bound live tests require authorization and must not run automatically on untrusted pull requests. CI should remain offline/local unless maintainers explicitly trigger a separate live smoke workflow.
