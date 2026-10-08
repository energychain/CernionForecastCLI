# Cernion Forecast CLI examples

This directory contains small **synthetic** datasets for local CLI validation and documentation examples. The files are not customer data, not market-message data and not intended as benchmark evidence.

## Files

- `data/synthetic_history_35d.json` — 35 observed local days ending at `forecast_for - 2 days`; suitable for local validation and live E2E shape checks.
- `data/synthetic_history_35d.csv` — same history as CSV.
- `data/synthetic_actuals_2026-09-29.json` — actuals for the forecast target day.
- `data/synthetic_actuals_2026-09-29.csv` — same actuals as CSV.
- `predictions/synthetic_previous_week_prediction_2026-09-29.json` — local previous-week baseline prediction for `score` examples.

## Validate history without API writes

```bash
cernion-forecast history \
  --dry-run \
  --series-id synthetic-meter-42 \
  --input examples/data/synthetic_history_35d.json \
  --quality-policy strict \
  --expected-intervals auto \
  --location Berlin \
  --weather-region DE-BE-Berlin \
  --country DE \
  --out runs/examples/synthetic-history-dry-run
```

## Score the sample prediction

```bash
cernion-forecast score \
  --series-id synthetic-meter-42 \
  --predictions examples/predictions/synthetic_previous_week_prediction_2026-09-29.json \
  --actuals examples/data/synthetic_actuals_2026-09-29.json \
  --out runs/examples/synthetic-score
```

## Live E2E shape

With a tenant-bound token you can use the same files for a smoke-style E2E command. The data satisfies the default CET portfolio preflight of 28 observed days before D-2, but the values are synthetic and should not be used for product quality claims.

```bash
cernion-forecast e2e \
  --series-id synthetic-meter-42 \
  --history examples/data/synthetic_history_35d.json \
  --actuals examples/data/synthetic_actuals_2026-09-29.json \
  --forecast-for 2026-09-29 \
  --location Berlin \
  --weather-region DE-BE-Berlin \
  --country DE \
  --quality-profile monitoring \
  --baselines previous-week,rolling-mean \
  --min-history-days-before-d2 28 \
  --out runs/examples/synthetic-e2e
```
