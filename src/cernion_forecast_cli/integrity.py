"""Integrity gate decisions and contract-level classification."""
from __future__ import annotations


def integrity_gate(name: str, result: dict, *, required=True):
    raw = result.get('status') or result.get('decision') or result.get('ok')
    passed = raw in ('ok', 'pass', True)
    if raw == 'warning' and not required:
        passed = True
    payload = {'name': name, 'required': required, 'status': 'pass' if passed else 'fail'}
    if isinstance(result, dict):
        payload.update(result)
    else:
        payload['result'] = result
    return payload


def compute_integrity_decision(gates):
    required = [g for g in gates if g.get('required', True)]
    if any(g.get('status') not in ('pass', 'ok') for g in required):
        return {'status': 'REJECTED', 'availability_evidence': 'UNVERIFIABLE'}
    availability = next((g for g in gates if g.get('name') == 'information_availability_check' or g.get('name') == 'information_availability'), {})
    evidence = availability.get('evidence_level') or 'VERIFIED'
    return {'status': 'PROVISIONAL' if evidence == 'ASSUMED' else 'ACCEPTED', 'availability_evidence': evidence}


def compute_forecast_acceptance_decision(gate):
    return {'status': 'ACCEPTED' if gate.get('status') == 'pass' else 'REJECTED', 'quality_gate_status': gate.get('status'), 'checks': gate.get('checks')}
