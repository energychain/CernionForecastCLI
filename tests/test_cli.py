import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = {**os.environ, 'PYTHONPATH': str(ROOT / 'src')}
SAMPLE_MSCONS = ''.join([
    "UNH+1+MSCONS:D:04B:UN:2.3e'",
    "BGM+7+DOC20261006001+9'",
    "DTM+137:20261007:102'",
    "NAD+MS+990****0003::293'",
    "NAD+MR+990****0008::293'",
    "LOC+172+DE0003966698900000000000052335107'",
    "CCI+11++Z06'",
    "QTY+220:1.25:KWH'",
    "DTM+163:202610060000:303'",
    "DTM+164:202610060015:303'",
    "STS+7++67'",
    "QTY+220:1.50:KWH'",
    "DTM+163:202610060015:303'",
    "DTM+164:202610060030:303'",
    "STS+7++79'",
    "UNT+16+1'",
])


def run_cli(*args, env=None):
    return subprocess.run(
        [sys.executable, '-m', 'cernion_forecast_cli.cli', *args],
        cwd=ROOT,
        env={**ENV, **(env or {})},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


class FakeAPI:
    def __init__(self):
        self.calls = []
        self.server = HTTPServer(('127.0.0.1', 0), self.handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return f'http://127.0.0.1:{self.server.server_port}'

    def close(self):
        self.server.shutdown()
        self.thread.join(timeout=2)

    def handler(self):
        owner = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                owner.calls.append((self.command, self.path, None, dict(self.headers)))
                if self.path.endswith('/api/jobs/job/status'):
                    self.reply({'status': 'completed'})
                elif self.path.endswith('/api/forecast-sandbox/consumption/portfolio/runs/' + 'a'*64):
                    self.reply({'status': 'completed', 'result': {'status': 'completed', 'series_id': 'meter-a', 'model_version': 'b'*64, 'forecast_for': '2026-09-28', 'forecast_values': []}})
                elif self.path.endswith('/api/forecast-sandbox/consumption/portfolio/runs/' + 'e'*64):
                    self.reply({'status': 'error', 'error': 'portfolio_failed: missing dependency'})
                elif self.path.endswith('/api/forecast-sandbox/consumption/portfolio/runs/' + 'd'*64):
                    values = []
                    for i in range(96):
                        hh, mm = divmod(i * 15, 60)
                        values.append({'timestamp': f'2026-09-28T{hh:02d}:{mm:02d}:00+02:00', 'predicted_value': 10.5})
                    self.reply({'status': 'completed', 'result': {'status': 'completed', 'series_id': 'meter-a', 'model_version': 'b'*64, 'forecast_for': '2026-09-28', 'timezone': 'Europe/Berlin', 'forecast_values': values}})
                else:
                    self.send_response(404); self.end_headers()

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                payload = json.loads(raw or b'{}')
                owner.calls.append((self.command, self.path, payload, dict(self.headers)))
                if self.path == '/api/tokens/verify':
                    self.reply({'valid': True, 'tenantId': 'tenant-a'})
                elif self.path == '/api/forecast-sandbox/consumption/day-ahead':
                    self.reply({'status': 'ok', 'method': {'id': 'baseline_weekday_profile_v0'}, 'forecast': [{'ts': '2026-09-16T00:00:00+02:00', 'value': 1.0}] * 96})
                elif self.path.endswith('/history'):
                    self.reply({'status': 'stored', 'series_id': payload['dataset']['series_id'], 'history_version': 'c'*64})
                elif self.path.endswith('/train'):
                    self.send_response(202)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    run_id = 'e'*64 if 'error-meter' in payload.get('series_ids', []) else 'a'*64
                    self.wfile.write(json.dumps({'jobId': 'job', 'run_id': run_id, 'status': 'queued'}).encode())
                elif self.path.endswith('/predict'):
                    self.send_response(202)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'jobId': 'job', 'run_id': 'd'*64, 'status': 'queued'}).encode())
                else:
                    self.send_response(404); self.end_headers()

            def reply(self, payload):
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode())
        return H


class CLITests(unittest.TestCase):
    def test_day_ahead_posts_public_sandbox_payload_and_writes_result(self):
        api = FakeAPI()
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                hist = tmp / 'history.json'
                hist.write_text(json.dumps({'values': [{'ts': '2026-08-01T00:00:00+02:00', 'value': 1.0}]}))
                out = tmp / 'out'
                p = run_cli('day-ahead', '--base-url', api.url, '--series-id', 'meter-1', '--forecast-for', '2026-09-16', '--history', str(hist), '--weather-region', 'DE-BY-Kempten-87435', '--location', 'Kempten', '--out', str(out))
                self.assertEqual(p.returncode, 0, p.stderr)
                result = json.loads((out / 'result.json').read_text())
                self.assertEqual(result['result']['status'], 'ok')
                self.assertEqual(len(result['result']['forecast']), 96)
                post = [c for c in api.calls if c[1].endswith('/day-ahead')][0]
                self.assertEqual(post[2]['seriesId'], 'meter-1')
                self.assertEqual(post[2]['granularity'], 'PT15M')
                self.assertEqual(post[2]['forecast_context']['weather_region'], 'DE-BY-Kempten-87435')
                self.assertEqual(post[2]['options']['forecastContext']['location'], 'Kempten')
        finally:
            api.close()

    def test_day_ahead_accepts_weather_region_and_location_context(self):
        api = FakeAPI()
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                hist = tmp / 'history.json'
                hist.write_text(json.dumps({'values': [{'ts': '2026-08-01T00:00:00+02:00', 'value': 1.0}]}))
                out = tmp / 'out'
                p = run_cli(
                    'day-ahead', '--base-url', api.url, '--series-id', 'meter-1',
                    '--forecast-for', '2026-09-16', '--history', str(hist), '--out', str(out),
                    '--weather-region', 'DE-BY-Kempten-87435', '--postal-code', '87435',
                    '--municipality', 'Kempten', '--latitude', '47.726', '--longitude', '10.314'
                )
                self.assertEqual(p.returncode, 0, p.stderr)
                post = [c for c in api.calls if c[1].endswith('/day-ahead')][0]
                self.assertEqual(post[2]['weather_region'], 'DE-BY-Kempten-87435')
                self.assertEqual(post[2]['site_context']['postal_code'], '87435')
                self.assertEqual(post[2]['site_context']['municipality'], 'Kempten')
                self.assertEqual(post[2]['site_context']['latitude'], 47.726)
                self.assertEqual(post[2]['site_context']['longitude'], 10.314)
        finally:
            api.close()

    def test_rejects_national_smard_as_weather_location_context(self):
        api = FakeAPI()
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                hist = tmp / 'history.json'
                hist.write_text(json.dumps({'values': [{'ts': '2026-08-01T00:00:00+02:00', 'value': 1.0}]}))
                p = run_cli(
                    'day-ahead', '--base-url', api.url, '--series-id', 'meter-1',
                    '--forecast-for', '2026-09-16', '--history', str(hist),
                    '--weather-region', 'DE-National-SMARD', '--location', 'Germany',
                    '--out', str(tmp / 'out')
                )
                self.assertNotEqual(p.returncode, 0)
                self.assertIn('location must be a city', p.stderr)
                self.assertFalse(api.calls)
        finally:
            api.close()

    def test_history_dry_run_never_calls_api_and_validates_dataset(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            dataset = tmp / 'meter.json'
            dataset.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': [{'timestamp': '2026-09-24T00:00:00+02:00', 'value': 1.2}]}))
            out = tmp / 'plan'
            p = run_cli('history', '--dry-run', '--tenant-id', 'tenant-a', '--series-id', 'meter-a', '--input', str(dataset), '--quality-policy', 'lenient', '--weather-region', 'DE-BY-Kempten-87435', '--out', str(out))
            self.assertEqual(p.returncode, 0, p.stderr)
            run = json.loads((out / 'run.json').read_text())
            self.assertEqual(run['operation'], 'history')
            self.assertEqual(run['status'], 'dry_run')
            self.assertEqual(run['inputs'][0]['series_id'], 'meter-a')
            self.assertEqual(run['forecast_context']['weather_region'], 'DE-BY-Kempten-87435')

    def test_history_dry_run_keeps_weather_region_and_site_context(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            dataset = tmp / 'meter.json'
            dataset.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': [{'timestamp': '2026-09-24T00:00:00+02:00', 'value': 1.2}]}))
            out = tmp / 'plan'
            p = run_cli(
                'history', '--dry-run', '--tenant-id', 'tenant-a', '--series-id', 'meter-a',
                '--input', str(dataset), '--quality-policy', 'lenient', '--weather-region', 'DE-BY-Kempten-87435',
                '--postal-code', '87435', '--municipality', 'Kempten', '--out', str(out)
            )
            self.assertEqual(p.returncode, 0, p.stderr)
            run = json.loads((out / 'run.json').read_text())
            self.assertEqual(run['weather_region'], 'DE-BY-Kempten-87435')
            self.assertEqual(run['site_context']['postal_code'], '87435')
            self.assertEqual(run['site_context']['municipality'], 'Kempten')
            self.assertEqual(run['forecast_context']['weather_region'], 'DE-BY-Kempten-87435')
            self.assertNotIn('request', run)


    def test_mscons_history_dry_run_preserves_envelope_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            mscons = tmp / 'meter.mscons'
            mscons.write_text(SAMPLE_MSCONS, encoding='utf-8')
            out = tmp / 'plan'
            p = run_cli(
                'history', '--dry-run', '--tenant-id', 'tenant-a',
                '--series-id', 'DE0003966698900000000000052335107',
                '--input', str(mscons), '--quality-policy', 'lenient', '--out', str(out)
            )
            self.assertEqual(p.returncode, 0, p.stderr)
            run = json.loads((out / 'run.json').read_text())
            self.assertEqual(run['inputs'][0]['source_format'], 'MSCONS')
            self.assertEqual(run['inputs'][0]['document_number'], 'DOC20261006001')
            self.assertEqual(run['input_provenance'][0]['source_format'], 'MSCONS')
            self.assertEqual(run['input_provenance'][0]['document_number'], 'DOC20261006001')
            self.assertEqual(run['input_provenance'][0]['sender']['id'], '990****0003')
            self.assertEqual(run['input_provenance'][0]['receiver']['id'], '990****0008')
            self.assertEqual(run['input_provenance'][0]['melo_id'], 'DE0003966698900000000000052335107')
            self.assertEqual(run['input_provenance'][0]['obis'], '1-0:1.8.0')

    def test_mscons_history_posts_dataset_with_source_envelope(self):
        api = FakeAPI()
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                mscons = tmp / 'meter.edi'
                mscons.write_text(SAMPLE_MSCONS, encoding='utf-8')
                out = tmp / 'history'
                p = run_cli(
                    'history', '--base-url', api.url, '--tenant-id', 'tenant-a',
                    '--series-id', 'DE0003966698900000000000052335107',
                    '--input', str(mscons), '--quality-policy', 'lenient', '--out', str(out), env={'CET_API_TOKEN': 'ck_12345678901234567890'}
                )
                self.assertEqual(p.returncode, 0, p.stderr)
                history_post = [c for c in api.calls if c[1].endswith('/history')][0][2]
                dataset = history_post['dataset']
                self.assertEqual(dataset['unit'], 'kWh')
                self.assertEqual([v['quality'] for v in dataset['values']], ['measured', 'estimated'])
                self.assertEqual(dataset['source']['format'], 'mscons')
                self.assertEqual(dataset['source']['documentNumber'], 'DOC20261006001')
                self.assertEqual(dataset['source_envelope']['format'], 'MSCONS')
                self.assertEqual(dataset['source_envelope']['document_number'], 'DOC20261006001')
                result = json.loads((out / 'result.json').read_text())
                self.assertEqual(result['input_provenance'][0]['document_number'], 'DOC20261006001')
        finally:
            api.close()

    def test_enroll_verifies_token_imports_history_then_trains_without_leaking_token(self):
        api = FakeAPI()
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                dataset = tmp / 'meter.json'
                dataset.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': [{'timestamp': '2026-09-24T00:00:00+02:00', 'value': 1.2}]}))
                out = tmp / 'enroll'
                secret = 'ck_12345678901234567890abcdef'
                p = run_cli('enroll', '--base-url', api.url, '--tenant-id', 'tenant-a', '--series-id', 'meter-a', '--input', str(dataset), '--quality-policy', 'lenient', '--forecast-for', '2026-09-28', '--out', str(out), env={'CET_API_TOKEN': secret})
                self.assertEqual(p.returncode, 0, p.stderr)
                combined = p.stdout + p.stderr + (out / 'run.json').read_text() + (out / 'result.json').read_text()
                self.assertNotIn(secret, combined)
                paths = [c[1] for c in api.calls]
                self.assertIn('/api/tokens/verify', paths)
                self.assertTrue(any(p.endswith('/history') for p in paths))
                self.assertTrue(any(p.endswith('/train') for p in paths))
                result = json.loads((out / 'result.json').read_text())
                self.assertEqual(result['tenant_id'], 'tenant-a')
        finally:
            api.close()

    def test_history_accepts_mscons_and_preserves_envelope_provenance(self):
        api = FakeAPI()
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                mscons = tmp / 'meter.edi'
                mscons.write_text(SAMPLE_MSCONS)
                out = tmp / 'mscons-history'
                p = run_cli('history', '--base-url', api.url, '--series-id', 'meter-a', '--input', str(mscons), '--quality-policy', 'lenient', '--out', str(out), env={'CET_API_TOKEN': 'ck_12345678901234567890abcdef'})
                self.assertEqual(p.returncode, 0, p.stderr)
                post = [c for c in api.calls if c[1].endswith('/history')][0]
                dataset = post[2]['dataset']
                self.assertEqual(dataset['series_id'], 'meter-a')
                self.assertEqual(dataset['values'][0]['timestamp'], '2026-10-05T22:00:00+00:00')
                self.assertEqual(dataset['values'][1]['quality'], 'estimated')
                self.assertEqual(dataset['source']['format'], 'mscons')
                self.assertEqual(dataset['source']['documentNumber'], 'DOC20261006001')
                self.assertEqual(dataset['source_envelope']['location']['melo_id'], 'DE0003966698900000000000052335107')
                run = json.loads((out / 'run.json').read_text())
                self.assertEqual(run['input_provenance'][0]['document_number'], 'DOC20261006001')
                result = json.loads((out / 'result.json').read_text())
                self.assertEqual(result['input_provenance'][0]['source_format'], 'MSCONS')
        finally:
            api.close()

    def test_predict_copies_model_input_provenance_to_result(self):
        api = FakeAPI()
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                model_file = tmp / 'model.json'
                model_file.write_text(json.dumps({
                    'tenant_id': 'tenant-a',
                    'result': {'model_version': 'b' * 64},
                    'input_provenance': [{'source_format': 'MSCONS', 'document_number': 'DOC20261006001', 'melo_id': 'DE0003966698900000000000052335107', 'obis': '1-0:1.8.0'}],
                }))
                out = tmp / 'predict'
                p = run_cli('predict', '--base-url', api.url, '--series-id', 'meter-a', '--model-file', str(model_file), '--forecast-for', '2026-09-29', '--out', str(out), env={'CET_API_TOKEN': 'ck_12345678901234567890abcdef'})
                self.assertEqual(p.returncode, 0, p.stderr)
                result = json.loads((out / 'result.json').read_text())
                self.assertEqual(result['result']['input_provenance'][0]['document_number'], 'DOC20261006001')
                self.assertEqual(result['result']['source_provenance']['last_history_message']['meloId'], 'DE0003966698900000000000052335107')
        finally:
            api.close()

    def test_score_rejects_partial_actuals_unless_explicit(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            prediction = tmp / 'pred.json'
            prediction.write_text(json.dumps({'tenant_id': 'tenant-a', 'result': {'status': 'completed', 'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'forecast_for': '2026-09-28', 'forecast_values': [{'timestamp': '2026-09-28T00:00:00+02:00', 'predicted_value': 1.0}, {'timestamp': '2026-09-28T00:15:00+02:00', 'predicted_value': 2.0}]}}))
            actual = tmp / 'actual.json'
            actual.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': [{'timestamp': '2026-09-28T00:00:00+02:00', 'value': 1.5}]}))
            p = run_cli('score', '--series-id', 'meter-a', '--predictions', str(prediction), '--actuals', str(actual), '--quality-policy', 'lenient', '--out', str(tmp / 'score'))
            self.assertEqual(p.returncode, 1)
            self.assertIn('forecast horizon incomplete', p.stderr)
            p2 = run_cli('score', '--series-id', 'meter-a', '--predictions', str(prediction), '--actuals', str(actual), '--quality-policy', 'lenient', '--allow-partial', '--out', str(tmp / 'score2'))
            self.assertEqual(p2.returncode, 0, p2.stderr)

    def test_acceptance_test_compares_forecast_against_naive_benchmarks(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            actual_values = []
            pred_values = []
            history_values = []
            for i in range(96):
                hh, mm = divmod(i * 15, 60)
                actual_values.append({'timestamp': f'2026-09-28T{hh:02d}:{mm:02d}:00+02:00', 'value': 100.0})
                pred_values.append({'timestamp': f'2026-09-28T{hh:02d}:{mm:02d}:00+02:00', 'predicted_value': 102.0})
                history_values.append({'timestamp': f'2026-09-27T{hh:02d}:{mm:02d}:00+02:00', 'value': 120.0})
                history_values.append({'timestamp': f'2026-09-21T{hh:02d}:{mm:02d}:00+02:00', 'value': 130.0})
            actual = tmp / 'actual.json'; actual.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': actual_values}))
            history = tmp / 'history.json'; history.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': history_values}))
            pred = tmp / 'pred.json'; pred.write_text(json.dumps({'tenant_id': 'tenant-a', 'result': {'series_id': 'meter-a', 'unit': 'kWh', 'forecast_values': pred_values}}))
            out = tmp / 'accept'
            p = run_cli('acceptance-test', '--series-id', 'meter-a', '--predictions', str(pred), '--actuals', str(actual), '--history', str(history), '--acceptance-profile', 'portfolio', '--require-better-than', 'persistence', '--min-relative-improvement', '0.05', '--max-wape', '5', '--out', str(out))
            self.assertEqual(p.returncode, 0, p.stderr)
            report = json.loads((out / 'acceptance_report.json').read_text())
            self.assertEqual(report['status'], 'pass')
            self.assertLess(report['model']['wape_percent'], report['benchmarks']['persistence']['wape_percent'])
            self.assertTrue(report['decision']['better_than_persistence'])
            self.assertTrue((out / 'acceptance_report.md').exists())

    def test_acceptance_test_fails_when_forecast_is_not_better_than_benchmark(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            actual_values = []
            pred_values = []
            history_values = []
            for i in range(96):
                hh, mm = divmod(i * 15, 60)
                actual_values.append({'timestamp': f'2026-09-28T{hh:02d}:{mm:02d}:00+02:00', 'value': 100.0})
                pred_values.append({'timestamp': f'2026-09-28T{hh:02d}:{mm:02d}:00+02:00', 'predicted_value': 130.0})
                history_values.append({'timestamp': f'2026-09-27T{hh:02d}:{mm:02d}:00+02:00', 'value': 101.0})
            actual = tmp / 'actual.json'; actual.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': actual_values}))
            history = tmp / 'history.json'; history.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': history_values}))
            pred = tmp / 'pred.json'; pred.write_text(json.dumps({'tenant_id': 'tenant-a', 'result': {'series_id': 'meter-a', 'unit': 'kWh', 'forecast_values': pred_values}}))
            p = run_cli('acceptance-test', '--series-id', 'meter-a', '--predictions', str(pred), '--actuals', str(actual), '--history', str(history), '--acceptance-profile', 'portfolio', '--require-better-than', 'persistence', '--out', str(tmp / 'accept'))
            self.assertEqual(p.returncode, 50)

    def test_mscons_timezone_segment_count_and_trailing_escape_are_validated(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bad = tmp / 'bad.edi'
            bad.write_text(SAMPLE_MSCONS.replace("UNT+16+1'", "UNT+99+1'"), encoding='utf-8')
            out = tmp / 'bad-out'
            p = run_cli('history', '--dry-run', '--tenant-id', 'tenant-a', '--series-id', 'meter-a', '--input', str(bad), '--out', str(out))
            self.assertEqual(p.returncode, 1)
            self.assertIn('UNT segment count mismatch', p.stderr)

            malformed = tmp / 'malformed.edi'
            malformed.write_text(SAMPLE_MSCONS + '?', encoding='utf-8')
            p_bad_escape = run_cli('history', '--dry-run', '--tenant-id', 'tenant-a', '--series-id', 'meter-a', '--input', str(malformed), '--out', str(tmp / 'bad-escape-out'))
            self.assertEqual(p_bad_escape.returncode, 1)
            self.assertIn('Malformed EDIFACT escape sequence', p_bad_escape.stderr)

            good = tmp / 'good.edi'
            good.write_text(SAMPLE_MSCONS, encoding='utf-8')
            out2 = tmp / 'good-out'
            p2 = run_cli('history', '--dry-run', '--tenant-id', 'tenant-a', '--series-id', 'meter-a', '--input', str(good), '--quality-policy', 'lenient', '--mscons-timezone', 'Europe/Berlin', '--out', str(out2))
            self.assertEqual(p2.returncode, 0, p2.stderr)
            run = json.loads((out2 / 'run.json').read_text())
            self.assertEqual(run['input_provenance'][0]['timezone'], 'Europe/Berlin')

    def test_idempotency_skips_processed_history_input_and_writes_summary(self):
        api = FakeAPI()
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                dataset = tmp / 'meter.json'
                dataset.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': [{'timestamp': '2026-09-24T00:00:00+02:00', 'value': 1.2}]}))
                ledger = tmp / 'processed.jsonl'
                out1 = tmp / 'first'
                p1 = run_cli('history', '--base-url', api.url, '--series-id', 'meter-a', '--input', str(dataset), '--quality-policy', 'lenient', '--processed-ledger', str(ledger), '--idempotency-key', 'auto', '--out', str(out1), env={'CET_API_TOKEN': 'ck_12345678901234567890'})
                self.assertEqual(p1.returncode, 0, p1.stderr)
                out2 = tmp / 'second'
                p2 = run_cli('history', '--base-url', api.url, '--series-id', 'meter-a', '--input', str(dataset), '--quality-policy', 'lenient', '--processed-ledger', str(ledger), '--idempotency-key', 'auto', '--skip-if-processed', '--out', str(out2), env={'CET_API_TOKEN': 'ck_12345678901234567890'})
                self.assertEqual(p2.returncode, 10, p2.stderr)
                summary = json.loads((out2 / 'summary.json').read_text())
                self.assertEqual(summary['status'], 'skipped_already_processed')
                self.assertEqual(len([c for c in api.calls if c[1].endswith('/history')]), 1)
        finally:
            api.close()

    def test_predict_can_export_csv_and_dataset_json_with_provenance_redaction(self):
        api = FakeAPI()
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                model_file = tmp / 'model.json'
                model_file.write_text(json.dumps({
                    'tenant_id': 'tenant-a',
                    'result': {'model_version': 'b' * 64},
                    'input_provenance': [{'source_format': 'MSCONS', 'document_number': 'DOC20261006001', 'melo_id': 'DE0003966698900000000000052335107', 'obis': '1-0:1.8.0'}],
                }))
                out = tmp / 'predict'
                p = run_cli('predict', '--base-url', api.url, '--series-id', 'meter-a', '--model-file', str(model_file), '--forecast-for', '2026-09-29', '--output-format', 'csv,dataset-json', '--provenance-level', 'pseudonymized', '--out', str(out), env={'CET_API_TOKEN': 'ck_12345678901234567890abcdef'})
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertTrue((out / 'forecast.csv').exists())
                self.assertTrue((out / 'forecast.dataset.json').exists())
                result = json.loads((out / 'result.json').read_text())
                self.assertNotIn('DE0003966698900000000000052335107', json.dumps(result))
                self.assertIn('melo_id_hash', json.dumps(result))
        finally:
            api.close()

    def test_batch_history_processes_input_directory_and_structured_logs(self):
        api = FakeAPI()
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                inbox = tmp / 'inbox'; inbox.mkdir()
                dataset = {'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': [{'timestamp': '2026-09-24T00:00:00+02:00', 'value': 1.2}]}
                (inbox / 'one.json').write_text(json.dumps(dataset))
                out = tmp / 'batch'
                p = run_cli('batch-history', '--base-url', api.url, '--input-dir', str(inbox), '--glob', '*.json', '--quality-policy', 'lenient', '--series-id-field', 'series_id', '--log-format', 'json', '--out', str(out), env={'CET_API_TOKEN': 'ck_12345678901234567890'})
                self.assertEqual(p.returncode, 0, p.stderr)
                summary = json.loads((out / 'summary.json').read_text())
                self.assertEqual(summary['processed'], 1)
                self.assertEqual(summary['failed'], 0)
                first_line = p.stdout.strip().splitlines()[0]
                self.assertEqual(json.loads(first_line)['event'], 'batch_started')
        finally:
            api.close()

    def test_config_profile_strategy_and_threshold_exit_codes(self):
        api = FakeAPI()
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                cfg = tmp / 'config.json'
                cfg.write_text(json.dumps({'profiles': {'ops': {'base_url': api.url, 'weather_region': 'DE-BY-Kempten-87435', 'quiet': True, 'debug_http': True}}}))
                dataset = tmp / 'meter.json'
                dataset.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': [{'timestamp': '2026-09-24T00:00:00+02:00', 'value': 1.2}]}))
                out = tmp / 'train'
                p = run_cli('train', '--config', str(cfg), '--profile', 'ops', '--series-ids', 'meter-a', '--forecast-for', '2026-09-28', '--strategy', 'evu_operational', '--out', str(out), env={'CET_API_TOKEN': 'ck_12345678901234567890'})
                self.assertEqual(p.returncode, 0, p.stderr)
                train_post = [c for c in api.calls if c[1].endswith('/train')][0][2]
                self.assertEqual(train_post['strategy'], 'evu_operational')
                self.assertEqual(train_post['weather_region'], 'DE-BY-Kempten-87435')

                failed = run_cli('train', '--base-url', api.url, '--series-ids', 'error-meter', '--forecast-for', '2026-09-28', '--poll-interval', '0', '--job-timeout', '5', '--out', str(tmp / 'failed-train'), env={'CET_API_TOKEN': 'ck_12345678901234567890'})
                self.assertEqual(failed.returncode, 1)
                self.assertIn('portfolio_failed: missing dependency', failed.stderr)

                debug = run_cli('train', '--base-url', api.url, '--series-ids', 'meter-a', '--forecast-for', '2026-09-28', '--poll-interval', '0', '--job-timeout', '5', '--debug-http', '--verbose', '--out', str(tmp / 'debug-train'), env={'CET_API_TOKEN': 'ck_abcdefghijklmnopqrstuvwxyz123456'})
                self.assertEqual(debug.returncode, 0, debug.stderr)
                self.assertIn('request_payload', debug.stderr)
                self.assertNotIn('ck_abcdefghijklmnopqrstuvwxyz123456', debug.stderr)

                pred = tmp / 'pred.json'
                pred.write_text(json.dumps({'tenant_id': 'tenant-a', 'result': {'series_id': 'meter-a', 'forecast_values': [{'timestamp': '2026-09-28T00:00:00+02:00', 'predicted_value': 10.0}]}}))
                actual = tmp / 'actual.json'
                actual.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': [{'timestamp': '2026-09-28T00:00:00+02:00', 'value': 1.0}]}))
                score = run_cli('score', '--series-id', 'meter-a', '--predictions', str(pred), '--actuals', str(actual), '--quality-policy', 'lenient', '--fail-if-wape-above', '10', '--out', str(tmp / 'score'))
                self.assertEqual(score.returncode, 50)
        finally:
            api.close()

    def test_config_profile_can_set_explicit_boolean_flags(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cfg = tmp / 'config.json'
            cfg.write_text(json.dumps({'profiles': {'ops': {'quiet': True, 'resume_out': True, 'debug_http': True}}}))
            sys.path.insert(0, str(ROOT / 'src'))
            from cernion_forecast_cli.cli import apply_config, build_parser
            args = build_parser().parse_args(['doctor', '--config', str(cfg), '--profile', 'ops', '--out', str(tmp / 'doctor')])
            configured = apply_config(args)
            self.assertTrue(configured.quiet)
            self.assertTrue(configured.resume_out)
            self.assertTrue(configured.debug_http)

    def test_e2e_acceptance_report_compares_baselines_and_quality_gate(self):
        api = FakeAPI()
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                history = tmp / 'history.json'
                actuals = tmp / 'actuals.json'
                history_values = []
                for day in range(1, 29):
                    history_values.extend([
                        {'timestamp': f'2026-08-{day:02d}T00:00:00+02:00', 'value': 9.0 + (day % 3)},
                        {'timestamp': f'2026-08-{day:02d}T00:15:00+02:00', 'value': 10.0 + (day % 3)},
                    ])
                # Baseline source points for forecast_for=2026-09-28; D-1 is intentionally absent.
                for i in range(96):
                    hh, mm = divmod(i * 15, 60)
                    history_values.append({'timestamp': f'2026-09-21T{hh:02d}:{mm:02d}:00+02:00', 'value': 12.0})
                history.write_text(json.dumps({
                    'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin',
                    'values': history_values,
                }))
                actuals.write_text(json.dumps({
                    'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin',
                    'values': [
                        {'timestamp': f'2026-09-28T{hh:02d}:{mm:02d}:00+02:00', 'value': 10.0}
                        for hh in range(24) for mm in (0, 15, 30, 45)
                    ]
                }))
                out = tmp / 'e2e'
                p = run_cli(
                    'e2e', '--base-url', api.url, '--series-id', 'meter-a',
                    '--history', str(history), '--actuals', str(actuals),
                    '--forecast-for', '2026-09-28', '--quality-policy', 'lenient', '--quality-profile', 'system-load',
                    '--baselines', 'previous-week', '--max-wape', '10',
                    '--baseline-tolerance', '1.0', '--location', 'Berlin',
                    '--weather-region', 'DE-BE-Berlin', '--min-observed-history-days', '0',
                    '--availability-mode', 'assume-event-time',
                    '--out', str(out), env={'CET_API_TOKEN': 'ck_12345678901234567890'}
                )
                self.assertEqual(p.returncode, 0, p.stderr)
                summary = json.loads((out / 'e2e-summary.json').read_text())
                self.assertEqual(summary['quality_gate']['status'], 'pass')
                self.assertEqual(summary['forecast_metrics']['coverage'], 1.0)
                self.assertLessEqual(summary['forecast_metrics']['wape_percent'], 10)
                self.assertIn('previous_week', summary['baseline_metrics'])
                self.assertNotIn('previous_day', summary['baseline_metrics'])
                self.assertEqual(summary['leakage_check']['status'], 'ok')
                self.assertEqual(summary['forecast_context']['location'], 'Berlin')
                self.assertTrue((out / 'e2e-report.md').exists())
                self.assertTrue((out / 'quality_gate.json').exists())
                paths = [c[1] for c in api.calls]
                self.assertTrue(any(path.endswith('/history') for path in paths))
                self.assertTrue(any(path.endswith('/train') for path in paths))
                self.assertTrue(any(path.endswith('/predict') for path in paths))
                receipt = json.loads((out / 'integrity_receipt.json').read_text())
                self.assertEqual(receipt['contract_id'], 'CET-FC-DIC-001')
                self.assertEqual(receipt['status'], 'pass')
                self.assertEqual(receipt['gates']['availability']['status'], 'ok')
                self.assertEqual(receipt['links']['run_manifest'], 'run_manifest.json')
        finally:
            api.close()

    def test_e2e_requires_explicit_availability_mode_when_evidence_is_missing(self):
        api = FakeAPI()
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                history = tmp / 'history.json'
                actuals = tmp / 'actuals.json'
                history.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': [
                    {'timestamp': '2026-09-21T00:00:00+02:00', 'value': 12.0},
                ]}))
                actuals.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': [{'timestamp': '2026-09-28T00:00:00+02:00', 'value': 10.0}]}))
                p = run_cli('e2e', '--base-url', api.url, '--series-id', 'meter-a', '--history', str(history), '--actuals', str(actuals), '--forecast-for', '2026-09-28', '--quality-policy', 'lenient', '--min-observed-history-days', '0', '--out', str(tmp / 'e2e'), env={'CET_API_TOKEN': 'ck_12345678901234567890'})
                self.assertEqual(p.returncode, 1)
                self.assertIn('availability evidence missing', p.stderr)
                self.assertFalse(api.calls)
        finally:
            api.close()

    def test_e2e_rejects_values_available_after_as_of_before_api_calls(self):
        api = FakeAPI()
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                history = tmp / 'history.json'
                actuals = tmp / 'actuals.json'
                history.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': [
                    {'timestamp': '2026-09-21T00:00:00+02:00', 'available_at': '2026-09-27T08:00:00+02:00', 'value': 12.0},
                ]}))
                actuals.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': [{'timestamp': '2026-09-28T00:00:00+02:00', 'value': 10.0}]}))
                p = run_cli('e2e', '--base-url', api.url, '--series-id', 'meter-a', '--history', str(history), '--actuals', str(actuals), '--forecast-for', '2026-09-28', '--quality-policy', 'lenient', '--min-observed-history-days', '0', '--out', str(tmp / 'e2e'), env={'CET_API_TOKEN': 'ck_12345678901234567890'})
                self.assertEqual(p.returncode, 1)
                self.assertIn('available after as_of', p.stderr)
                self.assertFalse(api.calls)
        finally:
            api.close()

    def test_e2e_uses_latest_value_available_as_of_for_historical_corrections(self):
        api = FakeAPI()
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                history = tmp / 'history.json'
                actuals = tmp / 'actuals.json'
                history_values = []
                for day in range(1, 29):
                    history_values.append({'timestamp': f'2026-08-{day:02d}T00:00:00+02:00', 'available_at': f'2026-08-{day:02d}T01:00:00+02:00', 'value': 9.0})
                history_values.extend([
                    {'timestamp': '2026-09-21T00:00:00+02:00', 'available_at': '2026-09-21T01:00:00+02:00', 'revision': 1, 'value': 10.0},
                    {'timestamp': '2026-09-21T00:00:00+02:00', 'available_at': '2026-09-25T01:00:00+02:00', 'revision': 2, 'value': 11.0},
                    {'timestamp': '2026-09-21T00:00:00+02:00', 'available_at': '2026-09-27T01:00:00+02:00', 'revision': 3, 'value': 99.0},
                ])
                history.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': history_values}))
                actuals.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': [{'timestamp': f'2026-09-28T{hh:02d}:{mm:02d}:00+02:00', 'value': 10.0} for hh in range(24) for mm in (0, 15, 30, 45)]}))
                out = tmp / 'e2e'
                p = run_cli('e2e', '--base-url', api.url, '--series-id', 'meter-a', '--history', str(history), '--actuals', str(actuals), '--forecast-for', '2026-09-28', '--quality-policy', 'lenient', '--quality-profile', 'system-load', '--baselines', 'previous-week', '--max-wape', '10', '--no-baseline-gate', '--min-observed-history-days', '0', '--out', str(out), env={'CET_API_TOKEN': 'ck_12345678901234567890'})
                self.assertEqual(p.returncode, 0, p.stderr)
                history_post = [c for c in api.calls if c[1].endswith('/history')][0][2]
                uploaded = {row['timestamp']: row['value'] for row in history_post['dataset']['values']}
                self.assertEqual(uploaded['2026-09-20T22:00:00+00:00'], 11.0)
                receipt = json.loads((out / 'integrity_receipt.json').read_text())
                self.assertEqual(receipt['gates']['availability']['selected_corrections'], 1)
                self.assertEqual(receipt['gates']['availability']['rejected_after_as_of'], 1)
        finally:
            api.close()

    def test_allow_partial_does_not_accept_outside_or_duplicate_predictions(self):
        sys.path.insert(0, str(ROOT / 'src'))
        from cernion_forecast_cli.cli import forecast_horizon_check, parse_stamp
        predictions = {
            parse_stamp('2026-09-28T00:00:00+02:00'): 1.0,
            parse_stamp('2026-09-29T00:00:00+02:00'): 2.0,
        }
        truth = {parse_stamp('2026-09-28T00:00:00+02:00'): 1.0}
        check = forecast_horizon_check(predictions, truth, forecast_for=__import__('datetime').date(2026, 9, 28), timezone='Europe/Berlin', allow_partial=True)
        self.assertEqual(check['status'], 'failed')
        self.assertTrue(check['outside_prediction_timestamps'])

    def test_e2e_rejects_equal_rank_corrections_without_revision_order(self):
        api = FakeAPI()
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                history = tmp / 'history.json'
                actuals = tmp / 'actuals.json'
                history.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': [
                    {'timestamp': '2026-09-21T00:00:00+02:00', 'available_at': '2026-09-21T01:00:00+02:00', 'value': 10.0},
                    {'timestamp': '2026-09-21T00:00:00+02:00', 'available_at': '2026-09-21T01:00:00+02:00', 'value': 11.0},
                ]}))
                actuals.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': [{'timestamp': '2026-09-28T00:00:00+02:00', 'value': 10.0}]}))
                p = run_cli('e2e', '--base-url', api.url, '--series-id', 'meter-a', '--history', str(history), '--actuals', str(actuals), '--forecast-for', '2026-09-28', '--quality-policy', 'lenient', '--min-observed-history-days', '0', '--out', str(tmp / 'e2e'), env={'CET_API_TOKEN': 'ck_12345678901234567890'})
                self.assertEqual(p.returncode, 1)
                self.assertIn('ambiguous correction versions', p.stderr)
                self.assertFalse(api.calls)
        finally:
            api.close()

    def test_assumed_availability_receipt_is_provisional_not_accepted(self):
        api = FakeAPI()
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                history = tmp / 'history.json'
                actuals = tmp / 'actuals.json'
                history_values = [{'timestamp': f'2026-08-{day:02d}T00:00:00+02:00', 'value': 9.0} for day in range(1, 29)]
                history_values.append({'timestamp': '2026-09-21T00:00:00+02:00', 'value': 10.0})
                history.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': history_values}))
                actuals.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': [{'timestamp': f'2026-09-28T{hh:02d}:{mm:02d}:00+02:00', 'value': 10.0} for hh in range(24) for mm in (0, 15, 30, 45)]}))
                out = tmp / 'e2e'
                p = run_cli('e2e', '--base-url', api.url, '--series-id', 'meter-a', '--history', str(history), '--actuals', str(actuals), '--forecast-for', '2026-09-28', '--quality-policy', 'lenient', '--quality-profile', 'system-load', '--baselines', 'previous-week', '--no-baseline-gate', '--min-observed-history-days', '0', '--availability-mode', 'assume-event-time', '--out', str(out), env={'CET_API_TOKEN': 'ck_12345678901234567890'})
                self.assertEqual(p.returncode, 0, p.stderr)
                receipt = json.loads((out / 'integrity_receipt.json').read_text())
                self.assertEqual(receipt['integrity_decision']['status'], 'ACCEPTED_WITH_ASSUMPTIONS')
                self.assertEqual(receipt['gates']['availability']['evidence_level'], 'ASSUMED')
                self.assertNotEqual(receipt['integrity_decision']['status'], 'ACCEPTED')
        finally:
            api.close()

    def test_score_allow_partial_reports_horizon_coverage_not_delivered_coverage(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            pred_values = []
            actual_values = []
            for i in range(96):
                hh, mm = divmod(i * 15, 60)
                actual_values.append({'timestamp': f'2026-09-28T{hh:02d}:{mm:02d}:00+02:00', 'value': 10.0})
                if i < 80:
                    pred_values.append({'timestamp': f'2026-09-28T{hh:02d}:{mm:02d}:00+02:00', 'predicted_value': 10.0})
            pred = tmp / 'pred.json'; pred.write_text(json.dumps({'tenant_id': 'tenant-a', 'result': {'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'forecast_for': '2026-09-28', 'forecast_values': pred_values}}))
            actual = tmp / 'actual.json'; actual.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': actual_values}))
            out = tmp / 'score'
            p = run_cli('score', '--series-id', 'meter-a', '--predictions', str(pred), '--actuals', str(actual), '--quality-policy', 'lenient', '--allow-partial', '--out', str(out))
            self.assertEqual(p.returncode, 0, p.stderr)
            metrics = json.loads((out / 'metrics.json').read_text())
            self.assertEqual(metrics['expected_intervals'], 96)
            self.assertAlmostEqual(metrics['coverage'], 80 / 96)
            self.assertAlmostEqual(metrics['forecast_coverage'], 80 / 96)
            self.assertAlmostEqual(metrics['matched_coverage'], 80 / 96)

    def test_quality_gate_failure_does_not_fail_integrity_receipt(self):
        api = FakeAPI()
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                history = tmp / 'history.json'
                actuals = tmp / 'actuals.json'
                history_values = [{'timestamp': f'2026-08-{day:02d}T00:00:00+02:00', 'available_at': f'2026-08-{day:02d}T01:00:00+02:00', 'value': 9.0} for day in range(1, 29)]
                history_values.append({'timestamp': '2026-09-21T00:00:00+02:00', 'available_at': '2026-09-21T01:00:00+02:00', 'value': 10.0})
                history.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': history_values}))
                actuals.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': [{'timestamp': f'2026-09-28T{hh:02d}:{mm:02d}:00+02:00', 'value': 10.0} for hh in range(24) for mm in (0, 15, 30, 45)]}))
                out = tmp / 'e2e'
                p = run_cli('e2e', '--base-url', api.url, '--series-id', 'meter-a', '--history', str(history), '--actuals', str(actuals), '--forecast-for', '2026-09-28', '--quality-policy', 'lenient', '--quality-profile', 'strict', '--baselines', 'previous-week', '--max-wape', '1', '--no-baseline-gate', '--min-observed-history-days', '0', '--out', str(out), env={'CET_API_TOKEN': 'ck_12345678901234567890'})
                self.assertEqual(p.returncode, 50, p.stderr)
                receipt = json.loads((out / 'integrity_receipt.json').read_text())
                self.assertEqual(receipt['integrity_decision']['status'], 'ACCEPTED')
                self.assertEqual(receipt['forecast_acceptance_decision']['status'], 'REJECTED')
                self.assertNotIn('quality_gate', receipt['gates'])
        finally:
            api.close()

    def test_integrity_receipt_binds_artifact_hashes_and_verify_detects_tampering(self):
        api = FakeAPI()
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                history = tmp / 'history.json'
                actuals = tmp / 'actuals.json'
                history_values = [{'timestamp': f'2026-08-{day:02d}T00:00:00+02:00', 'available_at': f'2026-08-{day:02d}T01:00:00+02:00', 'value': 9.0} for day in range(1, 29)]
                history_values.append({'timestamp': '2026-09-21T00:00:00+02:00', 'available_at': '2026-09-21T01:00:00+02:00', 'value': 10.0})
                history.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': history_values}))
                actuals.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': [{'timestamp': f'2026-09-28T{hh:02d}:{mm:02d}:00+02:00', 'value': 10.0} for hh in range(24) for mm in (0, 15, 30, 45)]}))
                out = tmp / 'e2e'
                p = run_cli('e2e', '--base-url', api.url, '--series-id', 'meter-a', '--history', str(history), '--actuals', str(actuals), '--forecast-for', '2026-09-28', '--quality-policy', 'lenient', '--quality-profile', 'system-load', '--baselines', 'previous-week', '--no-baseline-gate', '--min-observed-history-days', '0', '--out', str(out), env={'CET_API_TOKEN': 'ck_12345678901234567890'})
                self.assertEqual(p.returncode, 0, p.stderr)
                receipt = json.loads((out / 'integrity_receipt.json').read_text())
                self.assertIn('artifact_manifest', receipt['artifacts'])
                verify_ok = run_cli('verify-receipt', '--receipt', str(out / 'integrity_receipt.json'), '--out', str(tmp / 'verify-ok'))
                self.assertEqual(verify_ok.returncode, 0, verify_ok.stderr)
                prediction = json.loads((out / 'prediction_result.json').read_text())
                prediction['tampered'] = True
                (out / 'prediction_result.json').write_text(json.dumps(prediction))
                verify_bad = run_cli('verify-receipt', '--receipt', str(out / 'integrity_receipt.json'), '--out', str(tmp / 'verify-bad'))
                self.assertEqual(verify_bad.returncode, 1)
                self.assertIn('artifact hash mismatch', verify_bad.stderr)
        finally:
            api.close()

    def test_strict_contract_schemas_require_productive_fields(self):
        strict = json.loads((ROOT / 'docs' / 'schemas' / 'canonical-timeseries-strict.schema.json').read_text())
        required = set(strict['required'])
        self.assertTrue({'tenant_id', 'series_id', 'series_type', 'measurement_semantics', 'unit', 'timezone', 'values'} <= required)
        value_required = set(strict['properties']['values']['items']['required'])
        self.assertTrue({'timestamp', 'event_time', 'available_at', 'value', 'value_version'} <= value_required)
        receipt = json.loads((ROOT / 'docs' / 'schemas' / 'integrity-receipt-strict.schema.json').read_text())
        gates_required = set(receipt['properties']['gates']['required'])
        self.assertTrue({'history_quality_report', 'actual_quality_report', 'leakage_check', 'history_window_check', 'availability', 'forecast_horizon_check'} <= gates_required)

    def test_e2e_rejects_insufficient_observed_history_before_api_calls(self):
        api = FakeAPI()
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                history = tmp / 'history.json'
                actuals = tmp / 'actuals.json'
                values = []
                for day in range(1, 15):
                    values.append({'timestamp': f'2026-09-{day:02d}T00:00:00+02:00', 'value': 1.0})
                history.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': values}))
                actuals.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': [{'timestamp': '2026-10-01T00:00:00+02:00', 'value': 1.0}]}))
                p = run_cli(
                    'e2e', '--base-url', api.url, '--series-id', 'meter-a',
                    '--history', str(history), '--actuals', str(actuals),
                    '--forecast-for', '2026-10-01', '--quality-policy', 'lenient', '--out', str(tmp / 'e2e'),
                    env={'CET_API_TOKEN': 'ck_12345678901234567890'}
                )
                self.assertEqual(p.returncode, 1)
                self.assertIn('at least 28 observed history days required before D-2', p.stderr)
                self.assertFalse(api.calls)
        finally:
            api.close()

    def test_mscons_rejects_files_above_configured_size(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            mscons = tmp / 'too-large.mscons'
            mscons.write_text(SAMPLE_MSCONS, encoding='utf-8')
            p = run_cli(
                'history', '--dry-run', '--tenant-id', 'tenant-a', '--series-id', 'meter-a',
                '--input', str(mscons), '--out', str(tmp / 'out'),
                env={'CERNION_FORECAST_MSCONS_MAX_BYTES': '10'}
            )
            self.assertEqual(p.returncode, 1)
            self.assertIn('exceeds maximum size', p.stderr)

    def test_mscons_requires_filter_for_multiple_candidate_series(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            mscons = tmp / 'multi.mscons'
            second = SAMPLE_MSCONS.replace("LOC+172+DE0003966698900000000000052335107'", "LOC+172+DE0003966698900000000000099999999'").replace("UNH+1", "UNH+2").replace("UNT+16+1", "UNT+16+2")
            mscons.write_text(SAMPLE_MSCONS + second, encoding='utf-8')
            p = run_cli('history', '--dry-run', '--tenant-id', 'tenant-a', '--input', str(mscons), '--quality-policy', 'lenient', '--out', str(tmp / 'out'))
            self.assertEqual(p.returncode, 1)
            self.assertIn('multiple candidate time series', p.stderr)

    def test_predict_csv_export_escapes_formula_like_cells(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            sys.path.insert(0, str(ROOT / 'src'))
            from cernion_forecast_cli.cli import write_forecast_csv
            out = tmp / 'forecast.csv'
            write_forecast_csv(out, {'forecast_values': [{'timestamp': '=2026-09-28T00:00:00+02:00', 'predicted_value': '+10.5'}]})
            csv_text = out.read_text()
            self.assertIn("'=2026-09-28T00:00:00+02:00", csv_text)
            self.assertIn("'+10.5", csv_text)

    def test_batch_history_rejects_glob_that_escapes_input_dir(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            inbox = tmp / 'inbox'
            inbox.mkdir()
            outside = tmp / 'outside.json'
            outside.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': [{'timestamp': '2026-09-24T00:00:00+02:00', 'value': 1.0}]}))
            p = run_cli('batch-history', '--input-dir', str(inbox), '--glob', '../outside.json', '--base-url', 'http://127.0.0.1:1', '--out', str(tmp / 'batch'), env={'CET_API_TOKEN': 'ck_12345678901234567890'})
            self.assertEqual(p.returncode, 1)
            self.assertIn('escapes input directory', p.stderr)

    def test_e2e_rejects_history_after_d2_cutoff_before_api_calls(self):
        api = FakeAPI()
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                history_values = []
                for day in range(1, 29):
                    history_values.append({'timestamp': f'2026-08-{day:02d}T00:00:00+02:00', 'value': 1.0})
                history_values.append({'timestamp': '2026-09-27T00:00:00+02:00', 'value': 99.0})
                history = tmp / 'history.json'
                actuals = tmp / 'actuals.json'
                history.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': history_values}))
                actuals.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': [{'timestamp': '2026-09-28T00:00:00+02:00', 'value': 1.0}]}))
                p = run_cli('e2e', '--base-url', api.url, '--series-id', 'meter-a', '--history', str(history), '--actuals', str(actuals), '--forecast-for', '2026-09-28', '--min-coverage', '0', '--allow-gaps', '--out', str(tmp / 'e2e'), env={'CET_API_TOKEN': 'ck_12345678901234567890'})
                self.assertEqual(p.returncode, 1)
                self.assertIn('information cutoff', p.stderr)
                self.assertFalse(api.calls)
        finally:
            api.close()

    def test_mscons_series_id_does_not_resolve_multiple_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            mscons = tmp / 'multi.mscons'
            second = SAMPLE_MSCONS.replace("LOC+172+DE0003966698900000000000052335107'", "LOC+172+DE0003966698900000000000099999999'").replace("UNH+1", "UNH+2").replace("UNT+16+1", "UNT+16+2")
            mscons.write_text(SAMPLE_MSCONS + second, encoding='utf-8')
            p = run_cli('history', '--dry-run', '--tenant-id', 'tenant-a', '--series-id', 'internal-series', '--input', str(mscons), '--out', str(tmp / 'out'), '--quality-policy', 'lenient')
            self.assertEqual(p.returncode, 1)
            self.assertIn('multiple candidate time series', p.stderr)
            self.assertIn('DE0003966698900000000000052335107', p.stderr)

    def test_mscons_default_timezone_is_berlin_and_ambiguous_times_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            mscons = tmp / 'meter.mscons'
            mscons.write_text(SAMPLE_MSCONS, encoding='utf-8')
            p = run_cli('history', '--dry-run', '--tenant-id', 'tenant-a', '--series-id', 'DE0003966698900000000000052335107', '--input', str(mscons), '--out', str(tmp / 'out'), '--quality-policy', 'lenient')
            self.assertEqual(p.returncode, 0, p.stderr)
            run = json.loads((tmp / 'out' / 'run.json').read_text())
            self.assertEqual(run['input_provenance'][0]['timezone'], 'Europe/Berlin')
            self.assertEqual(run['inputs'][0]['timezone'], 'Europe/Berlin')

            ambiguous = tmp / 'ambiguous.mscons'
            ambiguous.write_text(SAMPLE_MSCONS.replace('202610060000', '202610250230').replace('202610060015', '202610250245').replace('202610060030', '202610250300'), encoding='utf-8')
            p2 = run_cli('history', '--dry-run', '--tenant-id', 'tenant-a', '--series-id', 'DE0003966698900000000000052335107', '--input', str(ambiguous), '--out', str(tmp / 'ambiguous-out'), '--quality-policy', 'lenient')
            self.assertEqual(p2.returncode, 1)
            self.assertIn('ambiguous local timestamp', p2.stderr)

    def test_score_rejects_incomplete_forecast_horizon(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            prediction = tmp / 'pred.json'
            prediction.write_text(json.dumps({'tenant_id': 'tenant-a', 'result': {'status': 'completed', 'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'forecast_for': '2026-09-28', 'forecast_values': [{'timestamp': '2026-09-28T00:00:00+02:00', 'predicted_value': 1.0}]}}))
            actual = tmp / 'actual.json'
            actual.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': [{'timestamp': '2026-09-28T00:00:00+02:00', 'value': 1.0}]}))
            p = run_cli('score', '--series-id', 'meter-a', '--predictions', str(prediction), '--actuals', str(actual), '--quality-policy', 'lenient', '--out', str(tmp / 'score'))
            self.assertEqual(p.returncode, 1)
            self.assertIn('forecast horizon incomplete', p.stderr)

    def test_previous_day_baseline_respects_d2_cutoff(self):
        sys.path.insert(0, str(ROOT / 'src'))
        from cernion_forecast_cli.cli import baseline_prediction, parse_stamp, information_cutoff
        history = {parse_stamp('2026-09-27T00:00:00+02:00'): 123.0, parse_stamp('2026-09-21T00:00:00+02:00'): 111.0}
        target = parse_stamp('2026-09-28T00:00:00+02:00')
        cutoff = information_cutoff(__import__('datetime').date(2026, 9, 28), 'Europe/Berlin')
        self.assertIsNone(baseline_prediction(target, history, 'previous-day', as_of=cutoff, timezone='Europe/Berlin'))
        self.assertEqual(baseline_prediction(target, history, 'previous-week', as_of=cutoff, timezone='Europe/Berlin'), 111.0)

    def test_quality_defaults_are_production_strict(self):
        sys.path.insert(0, str(ROOT / 'src'))
        from cernion_forecast_cli.cli import build_parser
        args = build_parser().parse_args(['history', '--input', 'x.json', '--out', 'out'])
        self.assertEqual(args.quality_policy, 'strict')
        self.assertEqual(args.min_coverage, 1.0)

    def test_remote_http_requires_explicit_insecure_flag(self):
        p = run_cli('doctor', '--base-url', 'http://api.example.invalid', '--out', str(Path(tempfile.mkdtemp()) / 'doctor'))
        self.assertEqual(p.returncode, 1)
        self.assertIn('HTTPS is required', p.stderr)

    def test_acceptance_report_handles_undefined_wape(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            actual_values = []
            pred_values = []
            history_values = []
            for i in range(96):
                hh, mm = divmod(i * 15, 60)
                actual_values.append({'timestamp': f'2026-09-28T{hh:02d}:{mm:02d}:00+02:00', 'value': 0.0})
                pred_values.append({'timestamp': f'2026-09-28T{hh:02d}:{mm:02d}:00+02:00', 'predicted_value': 0.0})
                history_values.append({'timestamp': f'2026-09-21T{hh:02d}:{mm:02d}:00+02:00', 'value': 0.0})
            actual = tmp / 'actual.json'; actual.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': actual_values}))
            history = tmp / 'history.json'; history.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': history_values}))
            pred = tmp / 'pred.json'; pred.write_text(json.dumps({'tenant_id': 'tenant-a', 'result': {'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'forecast_for': '2026-09-28', 'forecast_values': pred_values}}))
            p = run_cli('acceptance-test', '--series-id', 'meter-a', '--predictions', str(pred), '--actuals', str(actual), '--history', str(history), '--acceptance-profile', 'portfolio', '--benchmarks', 'previous-week', '--quality-policy', 'lenient', '--out', str(tmp / 'accept'))
            self.assertEqual(p.returncode, 50, p.stderr)
            report = (tmp / 'accept' / 'acceptance_report.md').read_text()
            self.assertIn('Model WAPE: undefined', report)


    def test_forecast_horizon_allow_partial_rejects_outside_predictions(self):
        sys.path.insert(0, str(ROOT / 'src'))
        from cernion_forecast_cli.cli import forecast_horizon_check, parse_stamp
        predictions = {
            parse_stamp('2026-09-28T00:00:00+02:00'): 1.0,
            parse_stamp('2026-09-29T00:00:00+02:00'): 2.0,
        }
        truth = {parse_stamp('2026-09-28T00:00:00+02:00'): 1.0}
        check = forecast_horizon_check(predictions, truth, forecast_for=__import__('datetime').date(2026, 9, 28), timezone='Europe/Berlin', allow_partial=True)
        self.assertEqual(check['status'], 'failed')
        self.assertIn('2026-09-28T22:00:00+00:00', check['outside_prediction_timestamps'])

    def test_information_availability_requires_available_at_or_explicit_mode(self):
        sys.path.insert(0, str(ROOT / 'src'))
        from cernion_forecast_cli.cli import information_availability_check, parse_stamp
        dataset = {'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': [{'timestamp': '2026-09-26T00:00:00+02:00', 'value': 1.0}]}
        with self.assertRaisesRegex(ValueError, 'availability proof missing'):
            information_availability_check(dataset, as_of=parse_stamp('2026-09-27T00:00:00+02:00'), mode='reject-missing')
        check = information_availability_check(dataset, as_of=parse_stamp('2026-09-27T00:00:00+02:00'), mode='event-time')
        self.assertEqual(check['status'], 'ok')
        self.assertEqual(check['availability_source_counts']['event_time_assumption'], 1)

    def test_information_availability_rejects_late_available_value(self):
        sys.path.insert(0, str(ROOT / 'src'))
        from cernion_forecast_cli.cli import information_availability_check, parse_stamp
        dataset = {'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': [{'timestamp': '2026-09-26T00:00:00+02:00', 'available_at': '2026-09-28T12:00:00+02:00', 'value': 1.0}]}
        check = information_availability_check(dataset, as_of=parse_stamp('2026-09-27T00:00:00+02:00'), mode='reject-missing')
        self.assertEqual(check['status'], 'fail')
        self.assertEqual(check['failures'][0]['code'], 'available_after_as_of')

    def test_history_dry_run_writes_integrity_receipt_with_availability_gate(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            history = tmp / 'history.json'
            history.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': [{'timestamp': '2026-09-26T00:00:00+02:00', 'available_at': '2026-09-26T01:00:00+02:00', 'value': 1.0}]}))
            p = run_cli('history', '--dry-run', '--tenant-id', 'tenant-a', '--input', str(history), '--as-of', '2026-09-27T00:00:00+02:00', '--out', str(tmp / 'out'), '--quality-policy', 'lenient')
            self.assertEqual(p.returncode, 0, p.stderr)
            receipt = json.loads((tmp / 'out' / 'integrity_receipt.json').read_text())
            self.assertEqual(receipt['contract_id'], 'CET-FC-DIC-001')
            self.assertEqual(receipt['receipt_schema_version'], 'cernion.forecast.integrity-receipt.v1')
            self.assertIn('availability', receipt['gates'])
            run = json.loads((tmp / 'out' / 'run.json').read_text())
            self.assertEqual(run['integrity_receipt']['path'], 'integrity_receipt.json')


    def test_assumed_availability_receipt_is_not_unrestricted_acceptance(self):
        api = FakeAPI()
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                history_values = []
                for day in range(1, 29):
                    history_values.append({'timestamp': f'2026-08-{day:02d}T00:00:00+02:00', 'value': 9.0})
                for i in range(96):
                    hh, mm = divmod(i * 15, 60)
                    history_values.append({'timestamp': f'2026-09-21T{hh:02d}:{mm:02d}:00+02:00', 'value': 10.0})
                history = tmp / 'history.json'; history.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': history_values}))
                actuals = tmp / 'actuals.json'; actuals.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': [{'timestamp': f'2026-09-28T{hh:02d}:{mm:02d}:00+02:00', 'value': 10.0} for hh in range(24) for mm in (0, 15, 30, 45)]}))
                out = tmp / 'e2e'
                p = run_cli('e2e', '--base-url', api.url, '--series-id', 'meter-a', '--history', str(history), '--actuals', str(actuals), '--forecast-for', '2026-09-28', '--quality-policy', 'lenient', '--quality-profile', 'system-load', '--baselines', 'previous-week', '--max-wape', '10', '--no-baseline-gate', '--min-observed-history-days', '0', '--availability-mode', 'assume-event-time', '--out', str(out), env={'CET_API_TOKEN': 'ck_12345678901234567890'})
                self.assertEqual(p.returncode, 0, p.stderr)
                receipt = json.loads((out / 'integrity_receipt.json').read_text())
                self.assertEqual(receipt['integrity_decision']['status'], 'ACCEPTED_WITH_ASSUMPTIONS')
                self.assertEqual(receipt['integrity_decision']['availability_evidence'], 'ASSUMED')
                self.assertNotEqual(receipt['integrity_decision']['status'], 'ACCEPTED')
        finally:
            api.close()

    def test_score_allow_partial_reports_full_horizon_coverage(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            pred_values = []
            actual_values = []
            for i in range(80):
                hh, mm = divmod(i * 15, 60)
                ts = f'2026-09-28T{hh:02d}:{mm:02d}:00+02:00'
                pred_values.append({'timestamp': ts, 'predicted_value': 1.0})
                actual_values.append({'timestamp': ts, 'value': 1.0})
            pred = tmp / 'pred.json'; pred.write_text(json.dumps({'tenant_id': 'tenant-a', 'result': {'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'forecast_for': '2026-09-28', 'forecast_values': pred_values}}))
            actual = tmp / 'actual.json'; actual.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': actual_values}))
            p = run_cli('score', '--series-id', 'meter-a', '--predictions', str(pred), '--actuals', str(actual), '--allow-partial', '--quality-policy', 'lenient', '--out', str(tmp / 'score'))
            self.assertEqual(p.returncode, 0, p.stderr)
            metrics = json.loads((tmp / 'score' / 'metrics.json').read_text())
            self.assertEqual(metrics['expected_intervals'], 96)
            self.assertAlmostEqual(metrics['coverage'], 80 / 96)
            self.assertAlmostEqual(metrics['forecast_coverage'], 80 / 96)
            self.assertAlmostEqual(metrics['matched_coverage'], 80 / 96)

    def test_e2e_forecast_failure_does_not_fail_integrity_decision(self):
        api = FakeAPI()
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                history_values = []
                for day in range(1, 29):
                    history_values.append({'timestamp': f'2026-08-{day:02d}T00:00:00+02:00', 'available_at': f'2026-08-{day:02d}T01:00:00+02:00', 'value': 9.0})
                for i in range(96):
                    hh, mm = divmod(i * 15, 60)
                    history_values.append({'timestamp': f'2026-09-21T{hh:02d}:{mm:02d}:00+02:00', 'available_at': f'2026-09-21T{hh:02d}:{mm:02d}:00+02:00', 'value': 10.0})
                history = tmp / 'history.json'; history.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': history_values}))
                actuals = tmp / 'actuals.json'; actuals.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': [{'timestamp': f'2026-09-28T{hh:02d}:{mm:02d}:00+02:00', 'value': 1000.0} for hh in range(24) for mm in (0, 15, 30, 45)]}))
                out = tmp / 'e2e'
                p = run_cli('e2e', '--base-url', api.url, '--series-id', 'meter-a', '--history', str(history), '--actuals', str(actuals), '--forecast-for', '2026-09-28', '--quality-policy', 'lenient', '--quality-profile', 'strict', '--baselines', 'previous-week', '--max-wape', '0.1', '--min-observed-history-days', '0', '--out', str(out), env={'CET_API_TOKEN': 'ck_12345678901234567890'})
                self.assertEqual(p.returncode, 50, p.stderr)
                receipt = json.loads((out / 'integrity_receipt.json').read_text())
                summary = json.loads((out / 'e2e-summary.json').read_text())
                self.assertEqual(receipt['integrity_decision']['status'], 'ACCEPTED')
                self.assertEqual(summary['forecast_acceptance_decision']['status'], 'REJECTED')
        finally:
            api.close()

    def test_verify_receipt_detects_modified_artifact(self):
        api = FakeAPI()
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                history_values = []
                for day in range(1, 29):
                    history_values.append({'timestamp': f'2026-08-{day:02d}T00:00:00+02:00', 'available_at': f'2026-08-{day:02d}T01:00:00+02:00', 'value': 9.0})
                for i in range(96):
                    hh, mm = divmod(i * 15, 60)
                    history_values.append({'timestamp': f'2026-09-21T{hh:02d}:{mm:02d}:00+02:00', 'available_at': f'2026-09-21T{hh:02d}:{mm:02d}:00+02:00', 'value': 10.0})
                history = tmp / 'history.json'; history.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': history_values}))
                actuals = tmp / 'actuals.json'; actuals.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': [{'timestamp': f'2026-09-28T{hh:02d}:{mm:02d}:00+02:00', 'value': 10.0} for hh in range(24) for mm in (0, 15, 30, 45)]}))
                out = tmp / 'e2e'
                p = run_cli('e2e', '--base-url', api.url, '--series-id', 'meter-a', '--history', str(history), '--actuals', str(actuals), '--forecast-for', '2026-09-28', '--quality-policy', 'lenient', '--quality-profile', 'system-load', '--baselines', 'previous-week', '--max-wape', '10', '--no-baseline-gate', '--min-observed-history-days', '0', '--out', str(out), env={'CET_API_TOKEN': 'ck_12345678901234567890'})
                self.assertEqual(p.returncode, 0, p.stderr)
                ok = run_cli('verify-receipt', '--run-dir', str(out), '--out', str(tmp / 'verify-ok'))
                self.assertEqual(ok.returncode, 0, ok.stderr)
                (out / 'prediction_result.json').write_text('{}')
                bad = run_cli('verify-receipt', '--run-dir', str(out), '--out', str(tmp / 'verify-bad'))
                self.assertEqual(bad.returncode, 1)
                self.assertIn('artifact hash mismatch', bad.stderr)
        finally:
            api.close()

    def test_materialize_rejects_equal_available_conflicting_versions_without_revision(self):
        sys.path.insert(0, str(ROOT / 'src'))
        from cernion_forecast_cli.cli import materialize_dataset_as_of, parse_stamp
        dataset = {'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': [
            {'timestamp': '2026-09-21T00:00:00+02:00', 'available_at': '2026-09-21T01:00:00+02:00', 'value': 10.0},
            {'timestamp': '2026-09-21T00:00:00+02:00', 'available_at': '2026-09-21T01:00:00+02:00', 'value': 11.0},
        ]}
        with self.assertRaisesRegex(ValueError, 'ambiguous data versions'):
            materialize_dataset_as_of(dataset, as_of=parse_stamp('2026-09-22T00:00:00+02:00'), mode='reject-missing')


if __name__ == '__main__':
    unittest.main()
