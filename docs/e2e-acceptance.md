# E2E acceptance

`e2e` is the command for a live operational proof. It does not merely test whether API calls succeed; it checks whether the produced forecast is acceptable for a selected operating profile.

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

The default preflight is:

```bash
--min-history-days-before-d2 28
```

Only set it to `0` for local fake-server tests.

## Baselines

The CLI can compare a model forecast to simple operator baselines:

- `previous-day` / `persistence`
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
- `prediction_result.json`
- `baseline_metrics.json`
- `quality_gate.json`
- `e2e-summary.json`
- `e2e-report.md`
- `residuals.json`
- `residuals.csv`

Exit code `50` means the run completed but the quality/acceptance gate failed.

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
  --out runs/meter-42-e2e
```
