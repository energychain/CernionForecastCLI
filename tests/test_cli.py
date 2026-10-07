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
                    self.reply({'status': 'completed', 'result': {'status': 'completed', 'model_version': 'b'*64, 'forecast_for': '2026-09-28'}})
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
                    self.wfile.write(json.dumps({'jobId': 'job', 'run_id': 'a'*64, 'status': 'queued'}).encode())
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
                p = run_cli('day-ahead', '--base-url', api.url, '--series-id', 'meter-1', '--forecast-for', '2026-09-16', '--history', str(hist), '--out', str(out))
                self.assertEqual(p.returncode, 0, p.stderr)
                result = json.loads((out / 'result.json').read_text())
                self.assertEqual(result['result']['status'], 'ok')
                self.assertEqual(len(result['result']['forecast']), 96)
                post = [c for c in api.calls if c[1].endswith('/day-ahead')][0]
                self.assertEqual(post[2]['seriesId'], 'meter-1')
                self.assertEqual(post[2]['granularity'], 'PT15M')
        finally:
            api.close()

    def test_history_dry_run_never_calls_api_and_validates_dataset(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            dataset = tmp / 'meter.json'
            dataset.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': [{'timestamp': '2026-09-24T00:00:00+02:00', 'value': 1.2}]}))
            out = tmp / 'plan'
            p = run_cli('history', '--dry-run', '--tenant-id', 'tenant-a', '--series-id', 'meter-a', '--input', str(dataset), '--out', str(out))
            self.assertEqual(p.returncode, 0, p.stderr)
            run = json.loads((out / 'run.json').read_text())
            self.assertEqual(run['operation'], 'history')
            self.assertEqual(run['status'], 'dry_run')
            self.assertEqual(run['inputs'][0]['series_id'], 'meter-a')

    def test_enroll_verifies_token_imports_history_then_trains_without_leaking_token(self):
        api = FakeAPI()
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                dataset = tmp / 'meter.json'
                dataset.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': [{'timestamp': '2026-09-24T00:00:00+02:00', 'value': 1.2}]}))
                out = tmp / 'enroll'
                secret = 'ck_supersecret'
                p = run_cli('enroll', '--base-url', api.url, '--tenant-id', 'tenant-a', '--series-id', 'meter-a', '--input', str(dataset), '--forecast-for', '2026-09-28', '--out', str(out), env={'CET_API_TOKEN': secret})
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

    def test_score_rejects_partial_actuals_unless_explicit(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            prediction = tmp / 'pred.json'
            prediction.write_text(json.dumps({'tenant_id': 'tenant-a', 'result': {'status': 'completed', 'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'forecast_for': '2026-09-28', 'forecast_values': [{'timestamp': '2026-09-28T00:00:00+02:00', 'predicted_value': 1.0}, {'timestamp': '2026-09-28T00:15:00+02:00', 'predicted_value': 2.0}]}}))
            actual = tmp / 'actual.json'
            actual.write_text(json.dumps({'series_id': 'meter-a', 'unit': 'kWh', 'timezone': 'Europe/Berlin', 'values': [{'timestamp': '2026-09-28T00:00:00+02:00', 'value': 1.5}]}))
            p = run_cli('score', '--series-id', 'meter-a', '--predictions', str(prediction), '--actuals', str(actual), '--out', str(tmp / 'score'))
            self.assertEqual(p.returncode, 1)
            self.assertIn('Missing actual values', p.stderr)
            p2 = run_cli('score', '--series-id', 'meter-a', '--predictions', str(prediction), '--actuals', str(actual), '--allow-partial', '--out', str(tmp / 'score2'))
            self.assertEqual(p2.returncode, 0, p2.stderr)


if __name__ == '__main__':
    unittest.main()
