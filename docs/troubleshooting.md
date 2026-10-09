# Troubleshooting

This guide lists common failures and safe diagnostic steps.

## First diagnostics

```bash
cernion-forecast --version
cernion-forecast doctor --out doctor
cernion-forecast describe
```

For tenant-bound API calls, use a token file outside the repository:

```bash
chmod 600 /path/to/token.txt
cernion-forecast doctor --token-file /path/to/token.txt --out doctor-live
```

Do not paste token values into issues or logs.

## Token is invalid or missing

Symptoms:

```text
Provide CET_API_TOKEN or --token-file; tokens are never stored
Token is invalid or has no bound tenant
Token is bound to another tenant
```

Actions:

- Verify that `CET_API_TOKEN` is set or `--token-file` points to the intended file.
- Check token-file permissions and line endings.
- Run `doctor` with the same token source.
- Do not override tenant IDs locally; tenant binding is checked server-side.

## Insufficient training history

Symptoms:

```text
at least 28 observed history days required before D-2; missing history is not zero
history contains values after the D-2 information cutoff
```

Meaning:

- For `forecast_for = D`, CET portfolio training expects at least 28 observed days up to and including `D-2`.
- `D-1` and `D` do not count as training history.
- Values from `D-1` or `D` must not be present in the training upload; keep them as separate actuals/score data.
- Missing intervals are missing, not zero.

Actions:

- Provide 30-35 complete observed days for first live tests.
- Keep target-day `actuals` in a separate file.
- Do not use `--min-history-days-before-d2 0` for live tenant-bound calls.

## Timestamp or quality-gate failures

Symptoms:

```text
Timestamps require an offset and a PT15M grid
Duplicate actual timestamp
Quality gate failed
Missing intervals
```

Actions:

- Use timestamps such as `2026-09-24T00:00:00+02:00`.
- Ensure quarter-hour intervals.
- Remove duplicates.
- Treat zero as a measured value only; do not fill missing history with zero.
- For DST days, expect 92 or 100 intervals depending on the day.

## Forecast quality gate fails

Symptoms:

```text
exit code 50
quality_gate.status = fail
baseline_delta = false
```

Meaning: the API call may have succeeded, but the forecast is not operationally acceptable under the selected profile and baseline comparison.

Actions:

- Inspect `e2e-summary.json`, `quality_gate.json`, `baseline_metrics.json` and `residuals.csv`.
- Try a less strict profile only if it matches the operational use case.
- Check whether `rolling-mean` or `previous-week` is already good enough for the tested day.
- Use multiple target days before drawing product-quality conclusions.

## Backend job status is error

Symptoms:

```text
Server job ended with status error: portfolio_failed: Forecast worker failed. Diagnostic ID: ...
```

Actions:

- Capture the job ID, run ID, tenant, `forecast_for`, `series_id` and diagnostic ID.
- Share only redacted artifacts with maintainers.
- If the job error says insufficient history, fix local data first.
- Otherwise provide the diagnostic ID to CET backend maintainers.

## MSCONS parser failures

Symptoms:

```text
UNT segment count mismatch
MSCONS input derives the unit from QTY segments; do not pass --unit
Supported inputs are JSON, CSV and MSCONS/EDIFACT
```

Actions:

- Use one meter/time series per import.
- Do not pass `--unit` or `--timezone` with MSCONS unless using the supported MSCONS timezone option.
- Validate that `QTY`, `DTM+163`, `LOC+172`, `CCI` and `UNT` are present and consistent.

## Safe bug reports

When opening an issue, include:

- CLI version,
- command without tokens,
- input format,
- redacted artifact excerpts,
- whether the command was dry-run, public sandbox or tenant-bound.

Never attach tokens, real customer data, unredacted MSCONS or confidential utility documents.
