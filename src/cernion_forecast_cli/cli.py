#!/usr/bin/env python3
"""Open REST CLI for Cernion load profile forecasts."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = '/api/forecast-sandbox/consumption/portfolio'
SANDBOX = '/api/forecast-sandbox/consumption'
UTC = dt.timezone.utc


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def save_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        json.dump(value, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write('\n')
    tmp.replace(path)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_stamp(value: str) -> dt.datetime:
    text = value.replace('Z', '+00:00')
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None or parsed.second or parsed.microsecond or parsed.minute % 15:
        raise ValueError('Timestamps require an offset and a PT15M grid')
    return parsed.astimezone(UTC)


def finite_nonnegative(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError('Expected a finite, nonnegative measurement value')
    return float(value)


def load_history_values(path: Path):
    data = read_json(path)
    values = data.get('historicalValues') or data.get('values')
    if not isinstance(values, list) or not values:
        raise ValueError('History JSON requires values or historicalValues')
    rows = []
    for row in values:
        ts = row.get('ts') or row.get('timestamp')
        val = row.get('value') if 'value' in row else row.get('predicted_value')
        parse_stamp(ts)
        rows.append({'ts': ts, 'value': finite_nonnegative(val)})
    return rows


def load_dataset(path: Path, series_id: str | None = None, unit: str | None = None, timezone: str | None = None):
    suffix = path.suffix.lower()
    if suffix == '.json':
        payload = read_json(path)
        dataset = payload.get('dataset', payload)
    elif suffix == '.csv':
        if not series_id or not unit or not timezone:
            raise ValueError('CSV input requires --series-id, --unit and --timezone')
        rows = []
        with path.open(newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts = row.get('timestamp') or row.get('ts')
                value = row.get('value')
                rows.append({'timestamp': ts, 'value': finite_nonnegative(float(value))})
        dataset = {'series_id': series_id, 'unit': unit, 'timezone': timezone, 'values': rows}
    else:
        raise ValueError('Supported inputs are JSON and CSV. Convert XLSX first or use the CET repo helper.')
    if series_id:
        dataset['series_id'] = series_id
    if unit and unit != dataset.get('unit'):
        raise ValueError('Requested unit differs from dataset unit')
    if timezone and timezone != dataset.get('timezone'):
        raise ValueError('Requested timezone differs from dataset timezone')
    if dataset.get('unit') not in ('kWh', 'kW') or not dataset.get('series_id') or not dataset.get('timezone'):
        raise ValueError('Dataset requires series_id, unit kWh/kW and timezone')
    if dataset.get('value_semantics') not in (None, 'interval_energy', 'average_power'):
        raise ValueError('Convert cumulative register readings to interval values before import')
    seen = set()
    for row in dataset.get('values') or []:
        ts = row.get('timestamp') or row.get('ts')
        t = parse_stamp(ts)
        if t in seen:
            raise ValueError('Duplicate actual timestamp')
        seen.add(t)
        finite_nonnegative(row.get('value'))
        if 'ts' in row and 'timestamp' not in row:
            row['timestamp'] = row.pop('ts')
    if not seen:
        raise ValueError('Dataset is empty')
    zone = ZoneInfo(dataset['timezone'])
    dataset['period_from'] = min(seen).astimezone(zone).date().isoformat()
    dataset['period_until'] = max(seen).astimezone(zone).date().isoformat()
    audit = {'file': path.name, 'sha256': sha256_bytes(path.read_bytes()), 'series_id': dataset['series_id'], 'records': len(seen)}
    return dataset, audit


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('HTTP redirect refused; use the final API base URL')


class Client:
    def __init__(self, base_url: str, token: str | None = None, tenant_header: str | None = None, timeout: float = 120):
        self.base = base_url.rstrip('/')
        split = urllib.parse.urlsplit(self.base)
        if split.scheme not in ('http', 'https') or not split.netloc or split.username or split.password or split.query or split.fragment:
            raise ValueError('Invalid API base URL; credentials do not belong in the URL')
        self.token = token or ''
        self.tenant_header = tenant_header
        self.timeout = timeout
        self.opener = urllib.request.build_opener(NoRedirect())

    def call(self, route: str, payload=None):
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        if self.tenant_header:
            headers['X-Tenant-Id'] = self.tenant_header
        req = urllib.request.Request(
            self.base + route,
            data=None if payload is None else json.dumps(payload, allow_nan=False).encode(),
            headers=headers,
        )
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                text = response.read().decode('utf-8')
                if self.token:
                    text = text.replace(self.token, '[REDACTED]')
                return json.loads(text) if text else {}
        except urllib.error.HTTPError as error:
            text = error.read().decode(errors='replace')
            if self.token:
                text = text.replace(self.token, '[REDACTED]')
            raise ValueError(f'HTTP {error.code}: {text}') from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            raise ConnectionError('API transport interrupted; writes are not automatically repeated') from error

    def verify(self):
        if not re.fullmatch(r'(?:ck_|csess_)[A-Za-z0-9_.-]+', self.token or ''):
            raise ValueError('Provide CET_API_TOKEN or --token-file; tokens are never stored')
        route = '/api/tokens/verify' if self.token.startswith('ck_') else '/api/auth/verify'
        result = self.call(route, {'token': self.token, 'trackUsage': False})
        tenant = result.get('tenantId')
        if result.get('valid') is not True or not isinstance(tenant, str) or not tenant.strip():
            raise ValueError('Token is invalid or has no bound tenant; no data was submitted')
        self.tenant_header = tenant
        return tenant


def identifier(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value):
        raise ValueError('Expected a SHA-256 model/run ID')
    return value


def token_from(args):
    if getattr(args, 'token_file', None):
        return args.token_file.read_text(encoding='utf-8').strip()
    return os.environ.get('CET_API_TOKEN', '').strip()


def client_for(args):
    return Client(args.base_url, token_from(args), None, args.timeout)


def await_result(client: Client, job, args):
    if job.get('status') == 'completed':
        return job
    run_id = identifier(job['run_id'])
    deadline = time.monotonic() + args.job_timeout
    while time.monotonic() < deadline:
        state = client.call(ROOT + '/runs/' + run_id)
        if state.get('status') == 'completed':
            return state.get('result', state)
        time.sleep(args.poll_interval)
    raise ValueError('Client wait expired; server job was not cancelled. Continue with resume.')


def fresh_out(path: Path):
    path.mkdir(parents=True, exist_ok=False, mode=0o700)


def cmd_day_ahead(args):
    fresh_out(args.out)
    history = load_history_values(args.history)
    payload = {
        'seriesId': args.series_id,
        'forecastDate': str(args.forecast_for),
        'granularity': 'PT15M',
        'timezone': args.timezone,
        'unit': args.unit,
        'historicalValues': history,
        'options': {'includeConfidenceBand': args.confidence_band, 'includeQualityHints': True, 'method': 'baseline'},
    }
    result = Client(args.base_url, timeout=args.timeout).call(SANDBOX + '/day-ahead', payload)
    save_json(args.out / 'request.json', payload)
    save_json(args.out / 'result.json', {'base_url': args.base_url.rstrip('/'), 'result': result})
    print('Completed: ' + str(args.out / 'result.json'))


def state_base(args, operation):
    return {'tenant_id': args.tenant_id, 'base_url': args.base_url.rstrip('/'), 'operation': operation, 'created_at': dt.datetime.now(UTC).isoformat(), 'uploads': []}


def cmd_history_like(args, train_after=False):
    fresh_out(args.out)
    dataset, audit = load_dataset(args.input, args.series_id, args.unit, args.timezone)
    state = state_base(args, 'enroll' if train_after else 'history')
    state['inputs'] = [audit]
    if train_after:
        request = {'series_ids': [dataset['series_id']], 'strategy': 'shared_baseline', 'forecast_for': str(args.forecast_for)}
    else:
        request = {}
    state['request'] = request
    if args.dry_run:
        state['status'] = 'dry_run'
        save_json(args.out / 'run.json', state)
        print('Plan validated without HTTP: ' + str(args.out / 'run.json'))
        return
    client = client_for(args)
    tenant = client.verify()
    state['tenant_id'] = tenant
    save_json(args.out / 'run.json', {**state, 'status': 'upload_submission_pending'})
    uploaded = client.call(ROOT + '/history', {'dataset': dataset, 'historical_import': args.historical_import or train_after, 'allow_corrections': args.allow_corrections})
    state['uploads'].append(uploaded)
    if not train_after:
        state['status'] = 'completed'
        save_json(args.out / 'run.json', state)
        save_json(args.out / 'result.json', {'tenant_id': tenant, 'base_url': client.base, 'result': uploaded})
        print('History stored: ' + str(args.out / 'result.json'))
        return
    state['status'] = 'job_submission_pending'
    save_json(args.out / 'run.json', state)
    job = client.call(ROOT + '/train', request)
    state['job'] = job
    save_json(args.out / 'run.json', state)
    result = await_result(client, job, args)
    save_json(args.out / 'result.json', {'tenant_id': tenant, 'base_url': client.base, 'result': result})
    state['status'] = 'completed'
    save_json(args.out / 'run.json', state)
    print('Completed: ' + str(args.out / 'result.json'))


def model_version(args):
    if args.model_version:
        return identifier(args.model_version)
    envelope = read_json(args.model_file)
    if args.tenant_id and envelope.get('tenant_id') != args.tenant_id:
        raise ValueError('Model file belongs to a different tenant')
    return identifier(envelope['result']['model_version'])


def cmd_train(args):
    fresh_out(args.out)
    request = {'series_ids': args.series_ids, 'strategy': 'shared_baseline', 'forecast_for': str(args.forecast_for)}
    state = {**state_base(args, 'train'), 'request': request}
    if args.dry_run:
        state['status'] = 'dry_run'; save_json(args.out / 'run.json', state); print('Plan validated without HTTP: ' + str(args.out / 'run.json')); return
    client = client_for(args); tenant = client.verify(); state['tenant_id'] = tenant
    job = client.call(ROOT + '/train', request); state['job'] = job; save_json(args.out / 'run.json', state)
    result = await_result(client, job, args)
    save_json(args.out / 'result.json', {'tenant_id': tenant, 'base_url': client.base, 'result': result})
    state['status'] = 'completed'; save_json(args.out / 'run.json', state)
    print('Completed: ' + str(args.out / 'result.json'))


def cmd_predict(args):
    fresh_out(args.out)
    request = {'series_id': args.series_id, 'model_version': model_version(args), 'forecast_for': str(args.forecast_for), 'allow_stale_model': args.allow_stale_model}
    if args.history_version:
        request['history_version'] = identifier(args.history_version)
    state = {**state_base(args, 'predict'), 'request': request}
    if args.dry_run:
        state['status'] = 'dry_run'; save_json(args.out / 'run.json', state); print('Plan validated without HTTP: ' + str(args.out / 'run.json')); return
    client = client_for(args); tenant = client.verify(); state['tenant_id'] = tenant
    job = client.call(ROOT + '/predict', request); state['job'] = job; save_json(args.out / 'run.json', state)
    result = await_result(client, job, args)
    save_json(args.out / 'result.json', {'tenant_id': tenant, 'base_url': client.base, 'result': result})
    state['status'] = 'completed'; save_json(args.out / 'run.json', state)
    print('Completed: ' + str(args.out / 'result.json'))


def cmd_resume(args):
    fresh_out(args.out)
    state = read_json(args.run_file)
    client = client_for(args); tenant = client.verify()
    if state.get('tenant_id') and state['tenant_id'] != tenant:
        raise ValueError('Resume requires the original tenant')
    run_id = identifier(state['job']['run_id'])
    job = client.call(ROOT + '/runs/' + run_id + '/resume', {}) if args.restart else state['job']
    result = await_result(client, job, args)
    save_json(args.out / 'result.json', {'tenant_id': tenant, 'base_url': client.base, 'result': result})
    state['status'] = 'completed'; save_json(args.out / 'run.json', state)
    print('Completed: ' + str(args.out / 'result.json'))


def prediction_rows(result):
    rows = result.get('forecast_values') or result.get('forecast')
    if not isinstance(rows, list):
        raise ValueError('Prediction has no forecast_values/forecast list')
    for row in rows:
        ts = row.get('timestamp') or row.get('ts')
        val = row.get('predicted_value') if 'predicted_value' in row else row.get('value')
        yield parse_stamp(ts), finite_nonnegative(val)


def cmd_score(args):
    fresh_out(args.out)
    actual, audit = load_dataset(args.actuals, args.series_id, args.unit, args.timezone)
    truth = {parse_stamp(r['timestamp']): finite_nonnegative(r['value']) for r in actual['values']}
    predictions = {}
    tenant = args.tenant_id
    for file in args.predictions:
        envelope = read_json(file)
        tenant = tenant or envelope.get('tenant_id')
        if envelope.get('tenant_id') and tenant and envelope.get('tenant_id') != tenant:
            raise ValueError('Prediction file belongs to another tenant')
        result = envelope['result']
        if result.get('series_id') and result.get('series_id') != args.series_id:
            raise ValueError('Prediction belongs to another series')
        for ts, val in prediction_rows(result):
            if ts in predictions:
                raise ValueError('Overlapping prediction files; choose one forecast per timestamp')
            predictions[ts] = val
    matching = sorted(predictions.keys() & truth.keys())
    if not matching or (len(matching) != len(predictions) and not args.allow_partial):
        raise ValueError('Missing actual values; use --allow-partial only for an explicitly partial report')
    errors = [predictions[t] - truth[t] for t in matching]
    absolute = math.fsum(abs(x) for x in errors)
    squared = math.fsum(x*x for x in errors)
    total = math.fsum(abs(truth[t]) for t in matching)
    metrics = {
        'tenant_id': tenant,
        'series_id': args.series_id,
        'unit': actual['unit'],
        'sample_count': len(matching),
        'expected_intervals': len(predictions),
        'coverage': len(matching) / len(predictions),
        'rmse': math.sqrt(squared / len(matching)),
        'mae': absolute / len(matching),
        'wape_percent': 100 * absolute / total if total else None,
        'actual_source': audit,
    }
    save_json(args.out / 'metrics.json', metrics)
    report = f"# Forecast quality — {args.series_id}\n\nTenant: {tenant or 'n/a'}. Unit: {actual['unit']}.\n\nN: {metrics['sample_count']}\nCoverage: {metrics['coverage']:.2%}\nRMSE: {metrics['rmse']:.6f}\nMAE: {metrics['mae']:.6f}\nWAPE: {'undefined' if metrics['wape_percent'] is None else f'{metrics['wape_percent']:.4f} %'}\n"
    (args.out / 'report.md').write_text(report, encoding='utf-8')
    print(report)


def add_common(sub, token=True):
    sub.add_argument('--base-url', default='https://api.cernion.de')
    sub.add_argument('--timeout', type=float, default=120)
    if token:
        sub.add_argument('--token-file', type=Path)
        sub.add_argument('--poll-interval', type=float, default=5)
        sub.add_argument('--job-timeout', type=float, default=86400)
        sub.add_argument('--dry-run', action='store_true')
        sub.add_argument('--tenant-id')
    sub.add_argument('--out', type=Path, required=True)


def build_parser():
    p = argparse.ArgumentParser(description='CLI for Cernion Lastgang-/load-profile forecasts')
    sub = p.add_subparsers(dest='command', required=True)

    day = sub.add_parser('day-ahead', help='Run public sandbox day-ahead baseline forecast')
    add_common(day, token=False)
    day.add_argument('--series-id', required=True)
    day.add_argument('--forecast-for', type=dt.date.fromisoformat, required=True)
    day.add_argument('--history', type=Path, required=True, help='JSON with values [{ts,value}]')
    day.add_argument('--timezone', default='Europe/Berlin')
    day.add_argument('--unit', choices=['kWh', 'kW'], default='kWh')
    day.add_argument('--confidence-band', action='store_true')
    day.set_defaults(func=cmd_day_ahead)

    for name in ('history', 'enroll'):
        sp = sub.add_parser(name)
        add_common(sp)
        sp.add_argument('--input', type=Path, required=True)
        sp.add_argument('--series-id', required=True)
        sp.add_argument('--unit', choices=['kWh', 'kW'])
        sp.add_argument('--timezone')
        sp.add_argument('--allow-corrections', action='store_true')
        sp.add_argument('--historical-import', action='store_true')
        if name == 'enroll':
            sp.add_argument('--forecast-for', type=dt.date.fromisoformat, required=True)
            sp.set_defaults(func=lambda args: cmd_history_like(args, train_after=True))
        else:
            sp.set_defaults(func=lambda args: cmd_history_like(args, train_after=False))

    train = sub.add_parser('train')
    add_common(train)
    train.add_argument('--series-ids', nargs='+', required=True)
    train.add_argument('--forecast-for', type=dt.date.fromisoformat, required=True)
    train.set_defaults(func=cmd_train)

    pred = sub.add_parser('predict')
    add_common(pred)
    pred.add_argument('--series-id', required=True)
    pred.add_argument('--forecast-for', type=dt.date.fromisoformat, required=True)
    g = pred.add_mutually_exclusive_group(required=True)
    g.add_argument('--model-version')
    g.add_argument('--model-file', type=Path)
    pred.add_argument('--history-version')
    pred.add_argument('--allow-stale-model', action='store_true')
    pred.set_defaults(func=cmd_predict)

    resume = sub.add_parser('resume')
    add_common(resume)
    resume.add_argument('--run-file', type=Path, required=True)
    resume.add_argument('--restart', action='store_true')
    resume.set_defaults(func=cmd_resume)

    score = sub.add_parser('score')
    score.add_argument('--tenant-id')
    score.add_argument('--out', type=Path, required=True)
    score.add_argument('--series-id', required=True)
    score.add_argument('--predictions', nargs='+', type=Path, required=True)
    score.add_argument('--actuals', type=Path, required=True)
    score.add_argument('--unit', choices=['kWh', 'kW'])
    score.add_argument('--timezone')
    score.add_argument('--allow-partial', action='store_true')
    score.set_defaults(func=cmd_score)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
        return 0
    except (ValueError, KeyError, OSError, ConnectionError) as error:
        message = str(error)
        secret = ''
        try:
            secret = token_from(args)
        except Exception:
            pass
        if secret:
            message = message.replace(secret, '[REDACTED]')
        print('ERROR: ' + message, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
