# E2E acceptance

`e2e` is the command for a live operational proof. It does not merely test whether API calls succeed; it checks whether the produced forecast is acceptable for a selected operating profile.

This behavior is governed by the proposed binding data-integrity contract [CET-FC-DIC-001](data-integrity-contract.md). The contract is the fachliche reference for D-2 information cutoff, forecast-horizon integrity, baseline availability and Evidence Receipts; its current status is `Proposed / Nicht freigegeben`, so implementation claims must stay limited to tested rules.

## Flow

```text
history → train → predict → score → baseline comparison → quality gate → report
```

## Required history depth

For live CET portfolio training:

```text
forecast_for = D
at least 28 observed history days are required up to and including D-2
D-1 and D are not counted
missing history is not zero
```

The command also enforces the information boundary on two independent axes:

- `event_time` / `timestamp` must be before the local D-1 cutoff for D-2 forecasting.
- `available_at` must be less than or equal to the run's `as_of` timestamp.

A value measured before D-2 but first available after `as_of` is rejected for point-in-time backtesting. If historical input lacks `available_at`, `e2e` fails by default. Operators must either provide evidence timestamps or explicitly choose `--availability-mode event-time|ingested-at|assume-event-time|assume-ingested`; the selected mode is recorded in `integrity_receipt.json`.

The computed `information_cutoff`, `as_of`, availability gate and any rejection reason are written to the E2E manifest/summary and receipt.

The default preflight is:

```bash
--min-history-days-before-d2 28
```

Only set it to `0` for local fake-server tests.

## Baselines

The CLI can compare a model forecast to simple operator baselines:

- `previous-day` / `persistence` (only when available before the configured information cutoff)
- `previous-week` / `weekly_naive`
- `rolling-mean`

A forecast can be technically complete and still fail acceptance when a naive baseline performs better.

## Profiles

Profiles encode use-case-oriented tolerances:

- `monitoring`
- `portfolio`
- `system-load`
- `household`
- `industrial`
- `volatile`
- `strict`

Use the profile that matches the operational decision, not the profile that makes the test pass.

## Outputs

`e2e` writes:

- `run_manifest.json`
- `integrity_receipt.json`
- `prediction_result.json`
- `baseline_metrics.json`
- `quality_gate.json`
- `e2e-summary.json`
- `e2e-report.md`
- `residuals.json`
- `residuals.csv`

Exit code `50` means the run completed but the quality/acceptance gate failed. Validation failures before API calls return `1` and do not upload data.

## Example

```bash
cernion-forecast e2e \
  --series-id meter-42 \
  --history meter-42-history.json \
  --actuals meter-42-actuals.json \
  --forecast-for 2026-09-29 \
  --quality-profile portfolio \
  --baselines previous-week,rolling-mean \
  --min-observed-history-days 28 \
  --availability-mode verified \
  --out runs/meter-42-e2e
```
