# Input formats

Cernion Forecast CLI accepts JSON, CSV and a focused MSCONS/EDIFACT subset.

## Dataset JSON

Use dataset JSON when you can export structured interval values from an EDM, billing, analytics or data-platform system.

```json
{
  "series_id": "meter-42",
  "unit": "kWh",
  "timezone": "Europe/Berlin",
  "value_semantics": "interval_energy",
  "source": {
    "system": "edm-export",
    "context_dataset_id": "optional-source-id"
  },
  "values": [
    {"timestamp": "2026-09-24T00:00:00+02:00", "available_at": "2026-09-24T01:00:00+02:00", "value": 1.25},
    {"timestamp": "2026-09-24T00:15:00+02:00", "available_at": "2026-09-24T01:00:00+02:00", "value": 1.30}
  ]
}
```

Rules:

- `series_id` is stable per meter, portfolio or aggregate.
- `unit` is `kWh` or `kW`.
- `timezone` names the local timezone used for quality reports.
- Timestamps must carry an explicit UTC offset.
- `timestamp`/`event_time` describes the observation interval; `available_at` describes when this value version was available for the forecast decision; `ingested_at` describes technical ingestion. They are separate concepts.
- Historical backtests reject missing availability proof unless an explicit `--availability-mode` is chosen.
- Values are quarter-hour interval values.
- Missing values are absent, not zero-filled.
- Productive quality defaults are strict: daily coverage is expected to be complete unless you explicitly choose `--quality-policy warn|lenient`, lower `--min-coverage`, or allow gaps for exploratory/local tests.

## CSV

Minimal CSV:

```csv
timestamp,value
2026-09-24T00:00:00+02:00,1.25
2026-09-24T00:15:00+02:00,1.30
```

When CSV lacks metadata, provide it via flags:

```bash
cernion-forecast history \
  --series-id meter-42 \
  --input meter-42-history.csv \
  --unit kWh \
  --timezone Europe/Berlin \
  --out runs/meter-42-history
```

## MSCONS / EDIFACT

MSCONS input is supported for one selected meter/time series per import. The CLI normalizes values into the forecast dataset contract and preserves envelope provenance.

Supported scope:

- one `LOC+172` location / MeLo,
- one supported `CCI` time series,
- `QTY` values with `KWH` or `KW`,
- `DTM+163` interval start timestamps,
- `STS` quality/status metadata,
- `UNT` segment count validation.

If a message contains multiple supported candidates, the import fails until exactly one candidate remains after applying `--melo-id`, `--obis`, `--cci-code`, `--message-ref` or `--document-number`. `--series-id` is only the internal CET series identifier and does not select a MSCONS candidate.

MSCONS timestamps are interpreted in the source timezone selected by `--mscons-timezone` and default to `Europe/Berlin`. Ambiguous or nonexistent local timestamps around DST transitions are rejected so operators must resolve the source interpretation explicitly.

The CLI does not generate MSCONS output messages.

## History versus actuals

For `score`, `acceptance-test` and `e2e`, keep history and actuals separate:

- `history` contains observations available before the forecast decision.
- `actuals` contains later target-day measurements.

`e2e` checks that actuals do not overlap the training/history window and that uploaded history contains no values after the D-2 information cutoff.
