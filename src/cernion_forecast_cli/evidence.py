"""Evidence receipts, artifact hashing and verification."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path

from .integrity import compute_integrity_decision

UTC = dt.timezone.utc


def chmod_private(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError as error:
        raise PermissionError(f'Could not restrict permissions on {path}') from error


def save_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(value, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write('\n')
    chmod_private(tmp)
    tmp.replace(path)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_json(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def artifact_manifest(out: Path, names):
    items = []
    for name in names:
        path = out / name
        if path.exists():
            data = path.read_bytes()
            items.append({'path': name, 'sha256': sha256_bytes(data), 'size_bytes': len(data)})
    manifest = {'schema_version': 'cernion.forecast.artifact-manifest.v1', 'created_at': dt.datetime.now(UTC).isoformat(), 'artifacts': items}
    save_json(out / 'artifact_manifest.json', manifest)
    manifest['sha256'] = sha256_bytes((out / 'artifact_manifest.json').read_bytes())
    return manifest


def build_integrity_receipt(*, operation: str, tenant_id=None, series_id=None, as_of=None, information_cutoff_value=None, artifacts=None, gates=None, links=None, integrity_decision=None, forecast_acceptance_decision=None, cli_version='unknown'):
    gate_items = gates or []
    gate_map = {}
    for gate in gate_items:
        key = gate.get('name', 'gate')
        if key.startswith('information_availability'):
            key = 'availability'
        elif key.endswith('_quality') or key == 'quality_report':
            key = key.replace('_quality', '_quality_report') if key.endswith('_quality') else 'quality_report'
        gate_map[key] = {k: v for k, v in gate.items() if k != 'name'}
    integrity_decision = integrity_decision or compute_integrity_decision(gate_items)
    status = 'pass' if integrity_decision.get('status') in ('ACCEPTED', 'PROVISIONAL') else 'fail'
    receipt = {
        'contract_id': 'CET-FC-DIC-001',
        'receipt_schema_version': 'cernion.forecast.integrity-receipt.v1',
        'status': status,
        'operation': operation,
        'created_at': dt.datetime.now(UTC).isoformat(),
        'created_by': f'cernion-forecast-cli/{cli_version}',
        'tenant_id': tenant_id,
        'series_id': series_id,
        'as_of': as_of.isoformat() if isinstance(as_of, dt.datetime) else as_of,
        'information_cutoff': information_cutoff_value.isoformat() if isinstance(information_cutoff_value, dt.datetime) else information_cutoff_value,
        'integrity_decision': integrity_decision,
        'forecast_acceptance_decision': forecast_acceptance_decision,
        'gates': gate_map,
        'artifacts': artifacts or {},
        'links': links or {},
    }
    receipt['receipt_hash'] = sha256_json({k: v for k, v in receipt.items() if k != 'receipt_hash'})
    return receipt


def save_integrity_receipt(out: Path, receipt: dict):
    save_json(out / 'integrity_receipt.json', receipt)
    return receipt


def verify_receipt(receipt_path: Path):
    receipt = read_json(receipt_path)
    run_dir = receipt_path.parent
    manifest_ref = (receipt.get('artifacts') or {}).get('artifact_manifest') or {}
    manifest_path = run_dir / (manifest_ref.get('path') or 'artifact_manifest.json')
    manifest = read_json(manifest_path)
    checks = []
    expected_manifest_hash = manifest_ref.get('sha256')
    if expected_manifest_hash and sha256_bytes(manifest_path.read_bytes()) != expected_manifest_hash:
        checks.append({'path': manifest_path.name, 'status': 'failed', 'reason': 'artifact manifest hash mismatch'})
    for item in manifest.get('artifacts') or []:
        path = run_dir / item['path']
        if not path.exists():
            checks.append({'path': item['path'], 'status': 'failed', 'reason': 'artifact missing'})
            continue
        actual = sha256_bytes(path.read_bytes())
        if actual != item.get('sha256'):
            checks.append({'path': item['path'], 'status': 'failed', 'reason': 'artifact hash mismatch', 'expected': item.get('sha256'), 'actual': actual})
        else:
            checks.append({'path': item['path'], 'status': 'ok'})
    status = 'ok' if all(c['status'] == 'ok' for c in checks) else 'failed'
    return {'status': status, 'receipt': str(receipt_path), 'artifact_manifest': str(manifest_path), 'checks': checks}
