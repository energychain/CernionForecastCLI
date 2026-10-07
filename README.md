# Cernion Forecast CLI

Open-source command line client for the Cernion Forecast Sandbox and tenant-bound Lastgang / load-profile forecast API.

The CLI calls the hosted Cernion REST API. It does **not** run local ML training and it does not store API tokens in result files.

Default API base URL: `https://api.cernion.de`

## Features

- Public sandbox day-ahead baseline forecast (`day-ahead`)
- Tenant-bound meter history import (`history`)
- Enroll a meter and train a shared-baseline model (`enroll`)
- Train already imported meters (`train`)
- Predict with a persisted model (`predict`)
- Resume an accepted run (`resume`)
- Local forecast quality scoring (`score`)
- JSON/CSV input, JSON/Markdown output
- No automatic retry of write operations
- Token is read from `CET_API_TOKEN` or `--token-file` and never archived

## Install from source

```bash
git clone <repo-url>
cd cernion-forecast-cli
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

No runtime dependency is required for JSON/CSV workflows.

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

## Tenant-bound product flow

The production portfolio endpoints require a Cernion token bound to a tenant.

```bash
read -r -s -p 'CET API token: ' CET_API_TOKEN
export CET_API_TOKEN
```

### 1. Import a meter history and train a model

Dataset JSON:

```json
{
  "series_id": "meter-42",
  "unit": "kWh",
  "timezone": "Europe/Berlin",
  "value_semantics": "interval_energy",
  "values": [
    {"timestamp": "2026-09-24T00:00:00+02:00", "value": 1.25}
  ]
}
```

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

### 2. Predict

```bash
cernion-forecast predict \
  --series-id meter-42 \
  --model-file runs/meter-42-training/result.json \
  --forecast-for 2026-09-29 \
  --out runs/meter-42-forecast-20260929
```

### 3. Score after actual values arrive

```bash
cernion-forecast score \
  --series-id meter-42 \
  --predictions runs/meter-42-forecast-20260929/result.json \
  --actuals meter-42-actuals.json \
  --out runs/meter-42-score-20260929
```

Outputs: `metrics.json` and `report.md`.

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
```

## Development

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall src tests
```

A live smoke against the public sandbox can be run without a token. Tenant-bound product calls need a valid `CET_API_TOKEN`.

## License

MIT.
