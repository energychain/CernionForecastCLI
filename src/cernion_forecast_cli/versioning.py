"""Historical correction versioning and point-in-time materialization."""
from __future__ import annotations

import datetime as dt
import math

from .availability import parse_stamp, resolve_available_at


def finite_number(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Expected a finite measurement value')
    return float(value)


def value_version_id(row):
    for field in ('value_version', 'version_id', 'revision'):
        if row.get(field) not in (None, ''):
            return str(row.get(field))
    return None


def version_sort_key(row):
    if row.get('revision') not in (None, ''):
        text = str(row.get('revision'))
        return (1, int(text)) if text.isdigit() else (1, text)
    if row.get('value_version') not in (None, ''):
        return (1, str(row.get('value_version')))
    if row.get('version_id') not in (None, ''):
        return (1, str(row.get('version_id')))
    return (0, '')


def materialize_dataset_as_of(dataset, *, as_of: dt.datetime, mode: str, information_cutoff_value: dt.datetime | None = None):
    selected = {}
    late_rows = []
    source_counts = {}
    evidence_levels = set()
    duplicate_events = set()
    selected_corrections = 0
    selection_decisions = []
    for row in dataset.get('values') or []:
        resolved = resolve_available_at(row, mode=mode)
        source_counts[resolved['availability_source']] = source_counts.get(resolved['availability_source'], 0) + 1
        evidence_levels.add(resolved['evidence_level'])
        event = resolved['event_time']; available = resolved['available_at']
        version_id = value_version_id(row)
        candidate = {'event_time': event.isoformat(), 'available_at': available.isoformat(), 'value_version': version_id, 'value': row.get('value')}
        if information_cutoff_value is not None and event >= information_cutoff_value:
            late_rows.append({**candidate, 'code': 'event_time_after_information_cutoff', 'message': 'event_time/timestamp is not before information_cutoff'})
            continue
        if available > as_of:
            late_rows.append({**candidate, 'code': 'available_after_as_of', 'message': 'value was available after as_of'})
            continue
        if event in selected:
            duplicate_events.add(event)
            current_available, current_resolved, current_row = selected[event]
            if available == current_available:
                current_version = value_version_id(current_row)
                if version_id is None or current_version is None or version_sort_key(row) == version_sort_key(current_row):
                    if finite_number(row.get('value')) != finite_number(current_row.get('value')):
                        raise ValueError('ambiguous correction versions / ambiguous data versions for ' + event.isoformat() + ': equal available_at requires a stable value_version/revision ordering')
                if version_sort_key(row) > version_sort_key(current_row):
                    selected_corrections += 1
                    selection_decisions.append({'event_time': event.isoformat(), 'selected_version': version_id, 'previous_version': current_version, 'reason': 'higher_revision_same_available_at'})
                    selected[event] = (available, resolved, row)
                else:
                    selection_decisions.append({'event_time': event.isoformat(), 'selected_version': current_version, 'rejected_version': version_id, 'reason': 'lower_or_equal_revision_same_available_at'})
            elif available > current_available:
                selected_corrections += 1
                selection_decisions.append({'event_time': event.isoformat(), 'selected_version': version_id, 'previous_version': value_version_id(current_row), 'reason': 'latest_available_before_as_of'})
                selected[event] = (available, resolved, row)
            else:
                selection_decisions.append({'event_time': event.isoformat(), 'selected_version': value_version_id(current_row), 'rejected_version': version_id, 'reason': 'older_available_at'})
        else:
            selected[event] = (available, resolved, row)
    missing_versions = [item for item in late_rows if parse_stamp(item['event_time']) not in selected]
    if missing_versions:
        raise ValueError('value available after as_of or after information cutoff: ' + str(missing_versions[:3]))
    values = []
    for event, (available, resolved, row) in sorted(selected.items(), key=lambda item: item[0]):
        item = dict(row)
        item['timestamp'] = event.isoformat()
        item['event_time'] = event.isoformat()
        item['available_at'] = available.isoformat()
        if resolved.get('ingested_at') is not None:
            item['ingested_at'] = resolved['ingested_at'].isoformat()
        item['availability_source'] = resolved['availability_source']
        item['availability_evidence'] = resolved['evidence_level']
        values.append(item)
    materialized = dict(dataset)
    materialized['values'] = values
    evidence_level = 'ASSUMED' if 'ASSUMED' in evidence_levels else 'VERIFIED' if evidence_levels else 'UNVERIFIABLE'
    check = {
        'status': 'ok',
        'mode': mode,
        'evidence_level': evidence_level,
        'as_of': as_of.isoformat(),
        'information_cutoff': information_cutoff_value.isoformat() if information_cutoff_value else None,
        'records': len(dataset.get('values') or []),
        'selected_records': len(values),
        'availability_source_counts': source_counts,
        'versioned_event_times': len(duplicate_events),
        'selected_corrections': selected_corrections,
        'rejected_after_as_of': len(late_rows),
        'rejected_examples': late_rows[:20],
        'selection_decisions': selection_decisions[:100],
    }
    return materialized, check
