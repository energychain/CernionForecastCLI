import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from cernion_forecast_cli.availability import resolve_available_at
from cernion_forecast_cli.evidence import artifact_manifest, build_integrity_receipt, save_json, save_integrity_receipt, verify_receipt
from cernion_forecast_cli.integrity import compute_forecast_acceptance_decision, compute_integrity_decision, integrity_gate
from cernion_forecast_cli.versioning import materialize_dataset_as_of

UTC = dt.timezone.utc


class ContractModuleConformanceTests(unittest.TestCase):
    def test_availability_assumption_is_classified(self):
        row = {'timestamp': '2026-09-01T00:00:00+00:00', 'value': 1.0}
        resolved = resolve_available_at(row, mode='event-time')
        self.assertEqual(resolved['evidence_level'], 'ASSUMED')
        self.assertEqual(resolved['availability_source'], 'event_time_assumption')

    def test_versioning_rejects_equal_rank_conflicting_corrections(self):
        dataset = {
            'values': [
                {'timestamp': '2026-09-01T00:00:00+00:00', 'available_at': '2026-09-02T00:00:00+00:00', 'value': 1.0},
                {'timestamp': '2026-09-01T00:00:00+00:00', 'available_at': '2026-09-02T00:00:00+00:00', 'value': 2.0},
            ]
        }
        with self.assertRaisesRegex(ValueError, 'ambiguous correction versions'):
            materialize_dataset_as_of(dataset, as_of=dt.datetime(2026, 9, 3, tzinfo=UTC), mode='reject-missing')

    def test_integrity_decision_does_not_depend_on_forecast_quality(self):
        gates = [integrity_gate('information_availability', {'status': 'ok', 'evidence_level': 'VERIFIED'})]
        integrity_decision = compute_integrity_decision(gates)
        forecast_decision = compute_forecast_acceptance_decision({'status': 'fail', 'checks': {'wape': False}})
        self.assertEqual(integrity_decision['status'], 'ACCEPTED')
        self.assertEqual(forecast_decision['status'], 'REJECTED')

    def test_evidence_manifest_detects_artifact_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            save_json(out / 'run_manifest.json', {'ok': True})
            manifest = artifact_manifest(out, ['run_manifest.json'])
            receipt = build_integrity_receipt(
                operation='e2e',
                artifacts={'artifact_manifest': {'path': 'artifact_manifest.json', 'sha256': manifest['sha256']}},
                gates=[integrity_gate('information_availability', {'status': 'ok', 'evidence_level': 'VERIFIED'})],
                cli_version='test',
            )
            save_integrity_receipt(out, receipt)
            self.assertEqual(verify_receipt(out / 'integrity_receipt.json')['status'], 'ok')
            save_json(out / 'run_manifest.json', {'ok': False})
            self.assertEqual(verify_receipt(out / 'integrity_receipt.json')['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
