# Release process

This project uses semantic-versioning intent.

Before `1.0.0`, command names and core artifact names should remain stable where possible, but detailed JSON fields may still evolve when required for operational safety or CET API alignment.

## Pre-release checklist

```bash
python -m unittest discover -s tests -v
python -m compileall -q -f src tests
python -m pip wheel . -w dist
python -m venv /tmp/cernion-forecast-release-check
/tmp/cernion-forecast-release-check/bin/pip install dist/cernion_forecast_cli-*.whl
/tmp/cernion-forecast-release-check/bin/cernion-forecast --version
/tmp/cernion-forecast-release-check/bin/cernion-forecast describe
```

Also validate the bundled examples without a CET token:

```bash
cernion-forecast history --dry-run \
  --series-id synthetic-meter-42 \
  --input examples/data/synthetic_history_35d.json \
  --out runs/release-example-history

cernion-forecast score \
  --series-id synthetic-meter-42 \
  --predictions examples/predictions/synthetic_previous_week_prediction_2026-09-29.json \
  --actuals examples/data/synthetic_actuals_2026-09-29.json \
  --out runs/release-example-score
```

## Live API checks

Live tenant-bound tests require explicit maintainer authorization and a valid CET token. They must not run automatically for untrusted pull requests.

Recommended live path for a release candidate:

```text
doctor → history dry-run → history → train → predict → score → acceptance-test/e2e
```

Use non-repository public or synthetic data and never commit token files or live run artifacts.

## Tagging

```bash
git tag -a v0.2.0 -m "v0.2.0"
git push origin v0.2.0
```

Create release notes from `CHANGELOG.md` and attach built artifacts only after the package has passed the checklist.
