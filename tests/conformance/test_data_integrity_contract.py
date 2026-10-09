import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from cernion_forecast_cli.availability import parse_stamp, resolve_available_at
from cernion_forecast_cli.evidence import artifact_manifest, build_integrity_receipt, verify_receipt
from cernion_forecast_cli.integrity import compute_forecast_acceptance_decision, compute_integrity_decision, integrity_gate
from cernion_forecast_cli.versioning import materialize_dataset_as_of


class DataIntegrityContractConformanceTests(unittest.TestCase):
    def test_at_006_assumed_availability_is_provisional(self):
        row = {'timestamp': '2026-09-21T00:00:00+02:00', 'value': 10.0}
        resolved = resolve_available_at(row, mode='assume-event-time')
        self.assertEqual(resolved['evidence_level'], 'ASSUMED')
        gate = integrity_gate('information_availability_check', {'status': 'ok', 'evidence_level': 'ASSUMED'})
        self.assertEqual(compute_integrity_decision([gate])['status'], 'PROVISIONAL')

    def test_at_006_rejects_equal_rank_conflicting_corrections(self):
        dataset = {
            'series_id': 'meter-a',
            'unit': 'kWh',
            'timezone': 'Europe/Berlin',
            'values': [
                {'timestamp': '2026-09-21T00:00:00+02:00', 'available_at': '2026-09-21T01:00:00+02:00', 'value': 10.0},
                {'timestamp': '2026-09-21T00:00:00+02:00', 'available_at': '2026-09-21T01:00:00+02:00', 'value': 11.0},
            ],
        }
        with self.assertRaisesRegex(ValueError, 'stable value_version/revision'):
            materialize_dataset_as_of(dataset, as_of=parse_stamp('2026-09-22T00:00:00+02:00'), mode='reject-missing')

    def test_at_008_artifact_manifest_binds_persisted_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / 'run_manifest.json').write_text('{"ok": true}\n', encoding='utf-8')
            manifest = artifact_manifest(run_dir, ['run_manifest.json'])
            receipt = build_integrity_receipt(
                operation='e2e',
                series_id='meter-a',
                artifacts={'artifact_manifest': {'path': 'artifact_manifest.json', 'sha256': manifest['sha256']}},
                gates=[integrity_gate('information_availability_check', {'status': 'ok', 'evidence_level': 'VERIFIED'})],
                cli_version='test',
            )
            (run_dir / 'integrity_receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
            self.assertEqual(verify_receipt(run_dir / 'integrity_receipt.json')['status'], 'ok')
            (run_dir / 'run_manifest.json').write_text('{"ok": false}\n', encoding='utf-8')
            self.assertEqual(verify_receipt(run_dir / 'integrity_receipt.json')['status'], 'failed')

    def test_section_6_separates_integrity_from_forecast_acceptance(self):
        integrity = compute_integrity_decision([
            integrity_gate('information_availability_check', {'status': 'ok', 'evidence_level': 'VERIFIED'})
        ])
        forecast = compute_forecast_acceptance_decision({'status': 'fail', 'checks': {'wape': False}})
        self.assertEqual(integrity['status'], 'ACCEPTED')
        self.assertEqual(forecast['status'], 'REJECTED')


if __name__ == '__main__':
    unittest.main()
