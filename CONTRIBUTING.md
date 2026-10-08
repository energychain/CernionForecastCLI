# Contributing

Thank you for considering a contribution to Cernion Forecast CLI.

This project is a command-line integration layer for Cernion Energy Tools (CET) forecast capabilities. Contributions should keep the boundary clear: the CLI normalizes inputs, preserves context/provenance, calls CET REST APIs and writes operational artifacts; it does not implement a replacement forecasting backend.

## Ways to contribute

- Improve documentation, examples or troubleshooting notes.
- Add support for well-defined input/export formats.
- Improve validation, diagnostics, exit codes or artifact contracts.
- Add tests for bugs, edge cases or operational workflows.
- Report safe, minimal reproductions for failures.

## Safe issue data

Do not upload real customer data, real MSCONS messages, API tokens, credentials, private market-party identifiers or confidential utility documents to GitHub issues or pull requests.

Prefer:

- synthetic examples from `examples/`,
- minimized JSON/CSV snippets with fake IDs,
- redacted `run.json` / `quality_report.json` / `doctor.json`,
- command lines with token values removed.

## Development setup

```bash
git clone git@github.com:energychain/CernionForecastCLI.git
cd CernionForecastCLI
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

## Test commands

Run these before opening a pull request:

```bash
python -m unittest discover -s tests -v
python -m compileall -q -f src tests
cernion-forecast describe
```

The default test suite must not require a CET API token and must not call live tenant-bound APIs. Live API checks belong in manual maintainer workflows or documented local smoke tests.

## Code expectations

- Add or update tests for behavior changes.
- Keep token values and secrets out of artifacts and logs.
- Preserve machine-readable artifact compatibility where possible.
- Use explicit exit codes for job runners instead of relying on console text.
- Keep examples synthetic unless a public-data source and license are clearly documented.

## Pull request checklist

- [ ] Tests pass locally.
- [ ] Documentation updated for new flags, input formats or artifacts.
- [ ] No token, customer data or confidential utility data included.
- [ ] New behavior has tests or a clear reason why not.
- [ ] Live API behavior, if relevant, is described separately from local tests.
