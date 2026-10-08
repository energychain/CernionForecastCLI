# Cernion Forecast CLI

[![CI](https://github.com/energychain/CernionForecastCLI/actions/workflows/ci.yml/badge.svg)](https://github.com/energychain/CernionForecastCLI/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

Open-source command line client for using forecast capabilities provided by Cernion Energy Tools (CET) from existing operational systems.

The package is a value-added integration tool: it does **not** run local ML training and it is not the forecasting product by itself. Business value comes from connecting Stadtwerke, Direktvermarkter and service-provider workflows to the hosted CET forecast API while preserving the operational context needed for daily work: meter identity, weather/site context, market-message provenance, run artifacts and forecast-quality evidence. API tokens are never stored in result files.

Default API base URL: `https://api.cernion.de`

Local commands such as `history --dry-run`, `score`, `acceptance-test`, `describe` and the bundled examples work without a token. Tenant-bound live commands such as `history`, `train`, `predict`, `enroll` and `e2e` require a Cernion API token.

## Business value

`cernion-forecast` lets existing systems use CET forecasting without a deep product integration. A Stadtwerk or Direktvermarkter can export measured histories from EDM, MaKo, billing or portfolio systems as JSON, CSV or MSCONS, call the CLI in a batch job, and read back machine-readable results and quality reports.

Typical operational uses:

- turn yesterday's 96 quarter-hour values into an updated forecast context for a meter or portfolio;
- keep MSCONS envelope provenance alongside the values so downstream users can trace which market message informed a forecast;
- pass weather region and site context so CET can select or document the relevant external/context features;
- train or reuse tenant-bound CET models without leaking tokens into artifacts;
- score forecast quality against later actuals and produce evidence for tuning, portfolio operations or service discussions.

The CLI is therefore the integration and provenance layer around CET forecast capabilities. CET provides the hosted forecasting, model lifecycle and tenant-bound API; the CLI makes those capabilities usable from command line, cron, job runners, ETL pipelines and existing utility back-office systems.

## Features

- Use hosted Cernion Energy Tools forecast capabilities from scripts and batch processes
- Production-safe run artifacts with schema metadata, `clientRunId` and idempotency support
- Public sandbox day-ahead baseline forecast (`day-ahead`)
- Tenant-bound meter history import into CET (`history`)
- Enroll a meter and request CET model training (`enroll`)
- Request training for already imported meters (`train`) with selectable strategy
- Request a forecast with a persisted CET model (`predict`)
- Resume an accepted CET run (`resume`)
- Local forecast quality scoring against actuals (`score`) with residual exports and threshold exit codes
- Batch history imports for operational inboxes (`batch-history`) and manifest-based batches (`batch`)
- Installation/API diagnostics (`doctor`) and machine-readable self-description (`describe`)
- JSON/CSV/MSCONS input, JSON/CSV/Markdown output artifacts
- MSCONS/EDIFACT envelope provenance is preserved in local artifacts and forecast results
- Optional weather-region and site context parameters for operational feature/context selection
- Data-quality gate for quarter-hour histories, DST days, gaps and coverage policy
- JSON config profiles for repeatable operational jobs
- Structured JSON logs for job runners and support diagnostics
- No automatic retry of write operations; explicit ledger-based skip of already processed inputs
- Token is read from `CET_API_TOKEN` or `--token-file` and never archived

## Install from source

```bash
git clone https://github.com/energychain/CernionForecastCLI.git
cd CernionForecastCLI
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

No runtime dependency is required for JSON/CSV workflows.

## Quickstart without a CET token

Use the synthetic examples to validate the CLI locally without API credentials:

```bash
cernion-forecast history --dry-run \
  --series-id synthetic-meter-42 \
  --input examples/data/synthetic_history_35d.json \
  --out runs/quickstart-history

cernion-forecast score \
  --series-id synthetic-meter-42 \
  --predictions examples/predictions/synthetic_previous_week_prediction_2026-09-29.json \
  --actuals examples/data/synthetic_actuals_2026-09-29.json \
  --out runs/quickstart-score

cernion-forecast acceptance-test \
  --series-id synthetic-meter-42 \
  --predictions examples/predictions/synthetic_previous_week_prediction_2026-09-29.json \
  --actuals examples/data/synthetic_actuals_2026-09-29.json \
  --history examples/data/synthetic_history_35d.json \
  --acceptance-profile monitoring \
  --require-better-than previous-week \
  --out runs/quickstart-acceptance
```

Expected result: the dry-run validates 35 days of synthetic history, `score` writes metrics/residuals, and `acceptance-test` writes an acceptance report without calling CET.

## Quickstart with a CET token

Tenant-bound history/train/predict/E2E calls require a CET token. Keep token files outside the repository.

```bash
chmod 600 /path/to/cet-token.txt
cernion-forecast doctor --token-file /path/to/cet-token.txt --out runs/doctor-live
```

Then run `e2e` with your own history and actuals. Provide at least 28 observed history days up to D-2; see [E2E acceptance](docs/e2e-acceptance.md).

## Synthetic examples

The repository includes one consolidated set of deterministic synthetic example data under `examples/`. These files are safe to use in documentation, local dry-runs and score/acceptance examples because they are not customer data and not copied from SMARD/MSCONS.

Start with:

```bash
cernion-forecast history --dry-run \
  --series-id synthetic-meter-42 \
  --input examples/data/synthetic_history_35d.json \
  --out runs/example-history-dry-run
```

For local quality examples without CET API calls, use `examples/predictions/synthetic_previous_week_prediction_2026-09-29.json` together with `examples/data/synthetic_actuals_2026-09-29.json` and `examples/data/synthetic_history_35d.json`. See `examples/README.md` for commands.

## Public sandbox: day-ahead baseline

Create a small history file. Real use should provide a meaningful historic period.

```json
{
  "values": [
    {"ts": "2026-08-01T00:00:00+02:00", "value": 1.0},
    {"ts": "2026-08-01T00:15:00+02:00", "value": 1.1}
  ]
}
```

Run:

```bash
cernion-forecast day-ahead \
  --series-id demo-meter \
  --forecast-for 2026-09-16 \
  --history history.json \
  --out out/day-ahead-demo
```

The sandbox endpoint returns a baseline profile and is marked by the API as non-production: no SLA, no quality guarantee, no balancing-risk guarantee.

## Weather region and site context

For decoration-pattern integrations the CLI accepts optional site/context metadata on `day-ahead`, `history`, `enroll`, `train` and `predict`:

```bash
cernion-forecast history \
  --series-id meter-42 \
  --input meter-42-history.json \
  --weather-region DE-BY-Kempten-87435 \
  --postal-code 87435 \
  --municipality Kempten \
  --latitude 47.726 \
  --longitude 10.314 \
  --out runs/meter-42-history
```

Supported context flags are `--location`, `--weather-region`, `--weather-dataset-id`, `--context-dataset-id`, `--postal-code`, `--municipality`, `--country`, `--latitude` and `--longitude`. The CLI records them in `forecast_context`, `site_context` and, for compatibility, `weather_region` in request/run artifacts and forwards them to the API payload. They are metadata for weather/context selection and provenance; they do not by themselves create or validate a weather dataset.

Use local site semantics for backend weather context: `--location` is a city/municipality such as `Kempten`, not a country like `Germany`. Put the country into `--country DE` and prefer `--municipality` plus postal code/coordinates when available. `--weather-region` must name a backend-supported weather region such as `DE-BY-Kempten-87435`; national load-source labels such as `DE-National-SMARD` are not weather regions. If SMARD or another public load source should be recorded for provenance, use `--context-dataset-id` or the dataset `source` metadata instead of pretending it is a weather region.

## MSCONS / EDIFACT input and envelope provenance

`history`, `enroll` and `score --actuals` accept `.mscons`, `.edi` and `.edifact` files in addition to dataset JSON and CSV. The CLI normalizes one MSCONS meter time series into the forecast dataset contract and keeps the market-message envelope metadata attached to the local artifacts.

Example:

```bash
cernion-forecast history \
  --series-id meter-42 \
  --input mscons/METER_42_20261006.edi \
  --out runs/meter-42-history-20261006
```

Supported MSCONS scope:

- exactly one `LOC+172` location / MeLo in the file for one CLI import;
- exactly one supported `CCI` time series per file;
- `QTY` values with `KWH` or `KW` units;
- `DTM+163` interval start timestamps;
- `STS` status codes mapped to value quality, e.g. measured/estimated/provisional/corrected.

The normalized dataset sent to the API contains `source` and `source_envelope` with `messageRef`, `documentNumber`, `documentDate`, `sender`, `receiver`, `meloId`, `cciCode` and OBIS-equivalent context. The local `run.json` / `result.json` additionally expose compact `input_provenance` and `source_provenance` fields. `predict --model-file ...` copies this model-input provenance into the forecast result so downstream systems can trace which MSCONS history envelope informed the model.

The CLI does **not** generate, alter or send MSCONS/market-communication output messages. It only reads MSCONS, normalizes measured values and preserves provenance.

## Preparing your own data

Use one stable `series_id` per meter, portfolio or aggregate load series. The same `series_id` must be used for history import, training, prediction, scoring and acceptance tests. Do not encode secrets, customer names or API credentials into `series_id` values.

### Required history depth for live CET training

Tenant-bound portfolio training needs enough observed history. The CLI enforces the same operational preflight in `e2e` before making API write calls:

```text
forecast_for = D
training history must contain at least 28 observed days up to and including D-2
D-1 and D are not counted as training history
missing history is not zero
```

Example: for `--forecast-for 2024-02-12`, the latest counted history day is `2024-02-10`. Provide at least 28 complete observed days ending on or before that date. A practical first live test should provide 30–35 days of quarter-hour history plus one separate actuals file for the forecast target day.

You can override the E2E preflight only for local/fake tests:

```bash
--min-history-days-before-d2 0
```

Do not use that override for real tenant-bound API tests. `--min-observed-history-days` remains accepted as a backwards-compatible alias.

### Dataset JSON

History and actuals JSON use the same dataset contract:

```json
{
  "series_id": "meter-42",
  "unit": "kWh",
  "timezone": "Europe/Berlin",
  "value_semantics": "interval_energy",
  "source": {
    "system": "edm-export",
    "context_dataset_id": "optional-public-or-internal-source-id"
  },
  "values": [
    {"timestamp": "2026-09-24T00:00:00+02:00", "value": 1.25},
    {"timestamp": "2026-09-24T00:15:00+02:00", "value": 1.30}
  ]
}
```

Rules:

- `timestamp` must include an explicit timezone offset.
- Values must be quarter-hour interval values on a PT15M grid.
- `unit` is `kWh` for interval energy or `kW` for average power.
- `value_semantics` may be `interval_energy` or `average_power`.
- Missing intervals must be absent, not filled with zero unless zero is a measured value.
- Duplicate timestamps are rejected.
- Cumulative register readings must be converted to interval values before import.

### CSV input

CSV input is accepted for `history`, `enroll`, `score --actuals`, `acceptance-test --actuals` and `e2e`.

Minimal CSV:

```csv
timestamp,value
2026-09-24T00:00:00+02:00,1.25
2026-09-24T00:15:00+02:00,1.30
```

When CSV does not carry metadata, pass it on the command line:

```bash
cernion-forecast history \
  --series-id meter-42 \
  --input meter-42-history.csv \
  --unit kWh \
  --timezone Europe/Berlin \
  --out runs/meter-42-history
```

### Separate history and actuals

For quality checks, keep these files separate:

- `history`: only observations available before the forecast decision time.
- `actuals`: later measured values for the target forecast day.

`e2e` checks that actuals do not leak into the training/history window.

## Tenant-bound product flow

The production portfolio endpoints require a Cernion token bound to a tenant.

```bash
read -r -s -p 'CET API token: ' CET_API_TOKEN
export CET_API_TOKEN
```

### 1. Validate your own history data

Prepare the input as described in [Preparing your own data](#preparing-your-own-data). Before writing to the API, validate the file locally:

```bash
cernion-forecast history \
  --dry-run \
  --series-id meter-42 \
  --input meter-42-history.json \
  --quality-policy strict \
  --expected-intervals auto \
  --out runs/meter-42-history-dry-run
```

For live training and E2E acceptance, make sure the history contains at least 28 observed local days ending no later than `forecast_for - 2 days`.

### 2. Import a meter history and train a model

Run:

```bash
cernion-forecast enroll \
  --series-id meter-42 \
  --input meter-42-history.json \
  --forecast-for 2026-09-28 \
  --out runs/meter-42-training
```

The CLI imports history using `historical_import: true`, starts `strategy: shared_baseline` training, polls the accepted run and writes:

- `run.json` — local state without token
- `result.json` — API result without token

### 3. Predict

```bash
cernion-forecast predict \
  --series-id meter-42 \
  --model-file runs/meter-42-training/result.json \
  --forecast-for 2026-09-29 \
  --out runs/meter-42-forecast-20260929
```

### 4. Score after actual values arrive

```bash
cernion-forecast score \
  --series-id meter-42 \
  --predictions runs/meter-42-forecast-20260929/result.json \
  --actuals meter-42-actuals.json \
  --out runs/meter-42-score-20260929
```

Outputs: `metrics.json`, `residuals.json`, `residuals.csv` and `report.md`.

Thresholds can make the command fail with exit code `50`, for example:

```bash
cernion-forecast score \
  --series-id meter-42 \
  --predictions runs/meter-42-forecast-20260929/result.json \
  --actuals meter-42-actuals.json \
  --fail-if-wape-above 10 \
  --out runs/meter-42-score-20260929
```

### 5. Acceptance-test operational usefulness

`score` answers whether a forecast matches actuals. `acceptance-test` adds an operational decision layer: the forecast must also beat naive alternatives such as yesterday's profile (`persistence` / `previous-day`) or the same weekday from the previous week (`weekly_naive` / `previous-week`) and stay within a use-case quality profile.

```bash
cernion-forecast acceptance-test \
  --series-id meter-42 \
  --predictions runs/meter-42-forecast-20260929/result.json \
  --actuals meter-42-actuals.json \
  --history meter-42-history.json \
  --acceptance-profile portfolio \
  --require-better-than previous-day previous-week \
  --min-relative-improvement 0.05 \
  --out runs/meter-42-acceptance-20260929
```

Profiles:

- `system-load`: national or aggregate load profiles with stable behavior.
- `portfolio`: default profile for portfolio/beschaffungsnahe usage.
- `monitoring`: wider tolerance for operational orientation.
- `household`, `industrial`, `volatile`: profile-specific quality gates for less stable loads.
- `strict`: stricter threshold for sensitive or high-impact usage.

The command writes `acceptance_report.json`, `acceptance_report.md`, `residuals.json` and `residuals.csv`. It exits with code `50` if the model forecast is not operationally acceptable, for example because WAPE/bias thresholds fail or because it is not better than the required naive benchmark.

### 6. Live E2E operational acceptance

`e2e` runs the complete tenant-bound live path and then applies the same operational acceptance logic. It validates data quality and leakage boundaries before writing, then executes:

```text
history → train → predict → score → baseline comparison → quality gate → report
```

Example:

```bash
cernion-forecast e2e \
  --series-id meter-42 \
  --history meter-42-history.json \
  --actuals meter-42-actuals.json \
  --forecast-for 2026-09-29 \
  --location Berlin \
  --weather-region DE-BE-Berlin \
  --quality-profile system-load \
  --baselines previous-day,previous-week,rolling-mean \
  --min-history-days-before-d2 28 \
  --max-wape 10 \
  --baseline-tolerance 1.0 \
  --out runs/meter-42-e2e-20260929
```

The command writes:

- `run_manifest.json` — periods, API run IDs, context, leakage check and raw API results.
- `prediction_result.json` — forecast envelope from CET.
- `baseline_metrics.json` — naive baseline metrics.
- `quality_gate.json` — machine-readable pass/fail decision.
- `e2e-summary.json` — compact operational summary.
- `e2e-report.md` — human-readable acceptance report.
- `residuals.json` / `residuals.csv` — per-timestamp forecast errors.

A successful `e2e` run means more than “API call succeeded”: the CLI verified input quality, no actuals leaked into the training window, the forecast has complete actual coverage, and the result is acceptable for the selected quality profile compared with simple operator baselines.

For CET portfolio training the default preflight requires at least 28 observed history days ending no later than `forecast_for - 2 days`. This mirrors the backend worker contract and prevents a live job from being started with too little history.

## Production controls

### Idempotency and processed ledger

Every write call carries a deterministic `clientRunId` / `Idempotency-Key`. For scheduled imports, use a ledger to avoid reprocessing an already accepted input:

```bash
cernion-forecast history \
  --series-id meter-42 \
  --input meter-42-history.json \
  --idempotency-key auto \
  --processed-ledger state/processed.jsonl \
  --skip-if-processed \
  --out runs/meter-42-history
```

If the input was already processed, the command writes `summary.json` with `status: skipped_already_processed` and exits with code `10`.

### Data-quality gate

History and actuals are checked before use. Relevant options:

- `--quality-policy strict|warn|lenient`
- `--min-coverage <0..1>`
- `--expected-intervals auto|96|92|100`
- `--allow-gaps`
- `--allow-negative`

The CLI writes `quality_report.json` for imports and score actuals.

### Batch inbox processing

```bash
cernion-forecast batch-history \
  --input-dir inbox \
  --glob '*.json' \
  --series-id-field series_id \
  --log-format json \
  --out runs/batch-20261007
```

The result is summarized in `summary.json`.

### Config profiles

Repeated operational jobs can load JSON config profiles:

```json
{
  "profiles": {
    "ops": {
      "base_url": "https://api.cernion.de",
      "weather_region": "DE-BY-Kempten-87435"
    }
  }
}
```

```bash
cernion-forecast train \
  --config forecast-config.json \
  --profile ops \
  --series-ids meter-42 \
  --strategy evu_operational \
  --forecast-for 2026-09-29 \
  --out runs/train
```

### Diagnostics

```bash
cernion-forecast doctor --out doctor
cernion-forecast describe
```

`doctor` checks the base URL, OpenAPI reachability, expected CET forecast routes and token binding. `describe` prints the machine-readable CLI contract.

## Data contract

- Granularity: quarter-hour values.
- Units: `kWh` interval energy or `kW` average power.
- Timestamps require explicit offset and PT15M grid.
- Cumulative OBIS register readings such as `1.8.0` must be converted to interval values before import.
- Missing values remain missing; zero is a real measured zero.
- Days with DST changes may contain 92 or 100 intervals.

## Safety boundaries

- Write calls are never retried automatically.
- HTTP redirects are refused so credentials are not forwarded to unexpected origins.
- Token values are not written to `run.json`, `result.json`, `metrics.json` or logs.
- `--dry-run` validates local input and writes a request plan without API calls.
- Tenant access is determined by the server-side token binding, not by a local header claim.

## Commands

```bash
cernion-forecast --help
cernion-forecast day-ahead --help
cernion-forecast history --help
cernion-forecast enroll --help
cernion-forecast train --help
cernion-forecast predict --help
cernion-forecast resume --help
cernion-forecast score --help
cernion-forecast acceptance-test --help
cernion-forecast e2e --help
```

## Development

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall src tests
```

A live smoke against the public sandbox can be run without a token. Tenant-bound product calls need a valid `CET_API_TOKEN`.

## Community and security

- See `CONTRIBUTING.md` for development setup, test expectations and data-safety rules.
- See `SECURITY.md` for private vulnerability reporting guidance.
- See `SUPPORT.md` for public support boundaries and safe live-API issue data.
- See `CHANGELOG.md` for release notes.
- See `docs/input-formats.md`, `docs/e2e-acceptance.md`, `docs/troubleshooting.md` and `docs/release.md` for focused operator and maintainer documentation.
- Issues and pull requests should use the templates under `.github/`.
- Do not post API tokens, real customer data, private MSCONS/EDIFACT payloads or non-public market communication content in issues or PRs.

## License

MIT.
