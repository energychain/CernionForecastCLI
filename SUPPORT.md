# Support

Cernion Forecast CLI is an open-source integration layer for Cernion Energy Tools forecast capabilities.

## Public support

Use GitHub issues for reproducible bugs, documentation gaps and feature requests:

- Bug reports: include CLI version, command, input format and redacted artifacts.
- Feature requests: describe the operational workflow and expected artifact/command behavior.

Do not post API tokens, credentials, real customer data, private MSCONS/EDIFACT payloads or confidential utility documents.

## Security-sensitive support

Use `SECURITY.md` for vulnerability reports or findings involving tokens, tenant isolation, credential leakage or confidential data exposure.

## CET tenant/API support

Tenant-bound live API behavior may depend on your CET contract, token permissions and hosted backend state. When reporting a live issue, include only sanitized metadata:

- CLI version or commit,
- command without token values,
- tenant-bound or sandbox route,
- job ID / run ID / diagnostic ID if available,
- redacted `doctor.json`, `run.json`, `quality_report.json` or `e2e-summary.json`.

## What maintainers cannot do in public issues

Maintainers cannot debug with live credentials, validate private customer data, give regulatory/legal advice, or guarantee forecast quality from a single sample. Use synthetic or redacted reproductions whenever possible.
