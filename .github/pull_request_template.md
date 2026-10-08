## Summary

- 

## Type of change

- [ ] Bug fix
- [ ] Feature
- [ ] Documentation/examples
- [ ] Tests/CI/packaging
- [ ] Refactor without behavior change

## Verification

Please paste the commands you ran:

```bash
python -m unittest discover -s tests -v
python -m compileall src tests
cernion-forecast --help
```

If you changed examples, also run the relevant example commands from `examples/README.md`.

## Data and security checklist

- [ ] No API tokens, authorization headers or secret files are committed.
- [ ] No real customer data is committed.
- [ ] No non-public MSCONS/EDIFACT payloads are committed.
- [ ] Meter, market-party and account identifiers are synthetic or intentionally masked.
- [ ] Generated artifacts (`runs/`, `out/`, `build/`, `dist/`, `*.egg-info`, `.venv/`, `__pycache__/`, `*.pyc`) are not committed.

## Notes for reviewers

Mention any live API test separately, including only sanitized job IDs/diagnostic IDs and never token values.
