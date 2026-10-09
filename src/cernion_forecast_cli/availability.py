"""Point-in-time information availability policies."""
from __future__ import annotations

import datetime as dt

UTC = dt.timezone.utc


def parse_stamp(value: str) -> dt.datetime:
    if not isinstance(value, str) or not value:
        raise ValueError('Timestamps require an offset and a PT15M grid')
    text = value.replace('Z', '+00:00')
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None or parsed.second or parsed.microsecond or parsed.minute % 15:
        raise ValueError('Timestamps require an offset and a PT15M grid')
    return parsed.astimezone(UTC)


def parse_optional_stamp(value, field: str, row_ts: str | None = None):
    if value in (None, ''):
        return None
    try:
        return parse_stamp(value)
    except Exception as error:
        where = f' for row {row_ts}' if row_ts else ''
        raise ValueError(f'{field}{where} must be an ISO timestamp with offset on a PT15M grid') from error


def row_event_time(row):
    return parse_stamp(row.get('event_time') or row.get('timestamp') or row.get('ts'))


def resolve_available_at(row, *, mode: str):
    aliases = {'assume-event-time': 'event-time', 'assume-ingested': 'ingested-at', 'verified': 'reject-missing'}
    mode = aliases.get(mode, mode)
    event = row_event_time(row)
    available = parse_optional_stamp(row.get('available_at'), 'available_at', row.get('timestamp') or row.get('ts'))
    ingested = parse_optional_stamp(row.get('ingested_at'), 'ingested_at', row.get('timestamp') or row.get('ts'))
    if available is not None:
        source = 'available_at'; evidence_level = 'VERIFIED'
    elif mode in ('event-time', 'assume-event-time'):
        available = event; source = 'event_time_assumption'; evidence_level = 'ASSUMED'
    elif mode == 'ingested-at' and ingested is not None:
        available = ingested; source = 'ingested_at'; evidence_level = 'ASSUMED'
    elif mode == 'reject-missing':
        raise ValueError('availability evidence missing / availability proof missing: provide available_at per value or choose an explicit --availability-mode')
    elif mode == 'ingested-at':
        raise ValueError('availability evidence missing / availability proof missing: --availability-mode ingested-at requires ingested_at per value')
    else:
        raise ValueError('Unsupported availability mode: ' + str(mode))
    return {'event_time': event, 'available_at': available, 'ingested_at': ingested, 'availability_source': source, 'evidence_level': evidence_level}


def select_versions_available_as_of(dataset, *, as_of: dt.datetime, mode: str = 'reject-missing'):
    grouped = {}
    rejected_after_as_of = 0
    source_counts = {}
    for row in dataset.get('values') or []:
        resolved = resolve_available_at(row, mode=mode)
        source_counts[resolved['availability_source']] = source_counts.get(resolved['availability_source'], 0) + 1
        event = resolved['event_time']
        available = resolved['available_at']
        if available > as_of:
            rejected_after_as_of += 1
            continue
        current = grouped.get(event)
        if current is None or available > current[0]:
            new_row = dict(row)
            new_row['timestamp'] = event.isoformat()
            new_row.setdefault('event_time', event.isoformat())
            new_row.setdefault('available_at', available.isoformat())
            if resolved['ingested_at'] is not None:
                new_row.setdefault('ingested_at', resolved['ingested_at'].isoformat())
            grouped[event] = (available, new_row)
    selected = [row for _, row in sorted(grouped.values(), key=lambda item: parse_stamp(item[1]['timestamp']))]
    out = dict(dataset)
    out['values'] = selected
    return out, {'selected_corrections': max(0, len(dataset.get('values') or []) - rejected_after_as_of - len(selected)), 'rejected_after_as_of': rejected_after_as_of, 'availability_source_counts': source_counts}


def information_availability_check(dataset, *, as_of: dt.datetime, mode: str = 'reject-missing', information_cutoff_value: dt.datetime | None = None):
    selected_dataset, versioning = select_versions_available_as_of(dataset, as_of=as_of, mode=mode)
    values = dataset.get('values') or []
    failures = []
    source_counts = dict(versioning.get('availability_source_counts') or {})
    latest_event = latest_available = latest_ingested = None
    for row in values:
        resolved = resolve_available_at(row, mode=mode)
        event = resolved['event_time']; available = resolved['available_at']; ingested = resolved['ingested_at']
        latest_event = event if latest_event is None or event > latest_event else latest_event
        latest_available = available if latest_available is None or available > latest_available else latest_available
        if ingested is not None:
            latest_ingested = ingested if latest_ingested is None or ingested > latest_ingested else latest_ingested
        if information_cutoff_value is not None and event >= information_cutoff_value:
            failures.append({'timestamp': event.isoformat(), 'code': 'event_time_after_information_cutoff', 'message': 'event_time/timestamp is not before information_cutoff'})
        if available > as_of:
            failures.append({'timestamp': event.isoformat(), 'available_at': available.isoformat(), 'code': 'available_after_as_of', 'message': 'value was available after as_of'})
    return {
        'status': 'ok' if not failures else 'fail',
        'mode': mode,
        'as_of': as_of.isoformat(),
        'information_cutoff': information_cutoff_value.isoformat() if information_cutoff_value else None,
        'records': len(values),
        'selected_corrections': versioning.get('selected_corrections', 0),
        'rejected_after_as_of': versioning.get('rejected_after_as_of', 0),
        'availability_source_counts': source_counts,
        'latest_event_time': latest_event.isoformat() if latest_event else None,
        'latest_available_at': latest_available.isoformat() if latest_available else None,
        'latest_ingested_at': latest_ingested.isoformat() if latest_ingested else None,
        'failures': failures[:50],
        'failure_count': len(failures),
    }
