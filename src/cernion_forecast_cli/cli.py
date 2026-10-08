#!/usr/bin/env python3
"""Production-oriented CLI for using Cernion Energy Tools forecast capabilities."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import logging
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
CLI_VERSION = '0.2.1'
ARTIFACT_SCHEMA = 'cernion.forecast-cli.artifact.v1'
MSCONS_SUFFIXES = {'.mscons', '.edi', '.edifact'}
MSCONS_MAX_BYTES = int(os.environ.get('CERNION_FORECAST_MSCONS_MAX_BYTES', str(50 * 1024 * 1024)))
CCI_TO_OBIS = {'Z06': '1-0:1.8.0', 'Z07': '1-0:2.8.0', 'Z10': '1-0:1.29.0', 'Z11': '1-0:2.29.0'}
STATUS_TO_QUALITY = {'67': 'measured', '79': 'estimated', '68': 'provisional', '220': 'corrected'}
LOG = logging.getLogger('cernion_forecast_cli')


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def chmod_private(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError as error:
        raise PermissionError(f'Could not restrict permissions on {path}') from error


def save_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    value = add_artifact_meta(value, path.stem) if isinstance(value, dict) else value
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(value, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write('\n')
    chmod_private(tmp)
    tmp.replace(path)


def add_artifact_meta(value: dict, artifact_type: str) -> dict:
    if 'schema_version' not in value:
        value = dict(value)
        value.setdefault('schema_version', ARTIFACT_SCHEMA)
        value.setdefault('artifact_type', artifact_type)
        value.setdefault('created_by', f'cernion-forecast-cli/{CLI_VERSION}')
    return value


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_json(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def parse_stamp(value: str) -> dt.datetime:
    if not isinstance(value, str) or not value:
        raise ValueError('Timestamps require an offset and a PT15M grid')
    text = value.replace('Z', '+00:00')
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None or parsed.second or parsed.microsecond or parsed.minute % 15:
        raise ValueError('Timestamps require an offset and a PT15M grid')
    return parsed.astimezone(UTC)


def finite_nonnegative(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError('Expected a finite, nonnegative measurement value')
    return float(value)


def finite_number(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Expected a finite measurement value')
    return float(value)


def csv_safe(value):
    if isinstance(value, str) and value[:1] in ('=', '+', '-', '@'):
        return "'" + value
    return value


def configure_logging(args):
    level = logging.WARNING
    if getattr(args, 'verbose', False):
        level = logging.INFO
    if getattr(args, 'quiet', False):
        level = logging.ERROR
    logging.basicConfig(level=level, format='%(message)s')


def log_event(args, event, **fields):
    if getattr(args, 'log_format', 'text') == 'json':
        payload = {'event': event, 'ts': dt.datetime.now(UTC).isoformat(), **fields}
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    else:
        suffix = ' '.join(f'{k}={v}' for k, v in fields.items())
        text = event + ((' ' + suffix) if suffix else '')
    if getattr(args, 'log_file', None):
        args.log_file.parent.mkdir(parents=True, exist_ok=True)
        with args.log_file.open('a', encoding='utf-8') as f:
            f.write(text + '\n')
    LOG.info(text)


def load_history_values(path: Path | str):
    path = Path(path)
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


def location_context(args):
    context = {}
    location = getattr(args, 'location', None)
    if location:
        if location.strip().casefold() in {'germany', 'deutschland', 'de', 'deutschland/bundesgebiet'}:
            raise ValueError('--location must be a city/municipality, not a country or national aggregate; use --country DE for the country and --municipality for the city')
        context['location'] = location
    weather_region = getattr(args, 'weather_region', None)
    if weather_region:
        if weather_region.strip().casefold() in {'de-national-smard', 'smard-de', 'smard-national'}:
            raise ValueError('--weather-region must identify a backend-supported weather region, not the national SMARD load aggregate; use --context-dataset-id for SMARD provenance')
        context['weather_region'] = weather_region
    for cli_name, field in (
        ('weather_dataset_id', 'weather_dataset_id'), ('context_dataset_id', 'context_dataset_id'), ('country', 'country'),
    ):
        value = getattr(args, cli_name, None)
        if value:
            context[field] = value
    site = {}
    for cli_name, field in (('postal_code', 'postal_code'), ('municipality', 'municipality')):
        value = getattr(args, cli_name, None)
        if value:
            site[field] = value
    for cli_name, field in (('latitude', 'latitude'), ('longitude', 'longitude')):
        value = getattr(args, cli_name, None)
        if value is not None:
            site[field] = float(value)
    if site:
        context['site_context'] = site
    return context


def apply_location_context(container, args):
    context = location_context(args)
    if context:
        container.setdefault('forecast_context', {}).update(context)
        if 'weather_region' in context:
            container['weather_region'] = context['weather_region']
        if 'site_context' in context:
            container['site_context'] = context['site_context']
    return context


def split_escaped(text: str, delimiter: str, release: str = '?'):
    parts, current, escaped = [], '', False
    for char in text:
        if escaped:
            current += char; escaped = False
        elif char == release:
            escaped = True
        elif char == delimiter:
            parts.append(current); current = ''
        else:
            current += char
    if escaped:
        raise ValueError('Malformed EDIFACT escape sequence: trailing release character')
    parts.append(current)
    return parts


def tokenize_edifact(raw: str):
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError('EDIFACT input is empty')
    if len(raw.encode('utf-8', errors='surrogatepass')) > MSCONS_MAX_BYTES:
        raise ValueError(f'EDIFACT input exceeds maximum size of {MSCONS_MAX_BYTES} bytes')
    separators = {'element': '+', 'component': ':', 'segment': "'", 'release': '?'}
    body = raw.replace('\r', '').replace('\n', '')
    una = None
    if body.startswith('UNA') and len(body) >= 9:
        una = body[:9]
        separators.update(component=body[3], element=body[4], release=body[6], segment=body[8])
        body = body[9:]
        if body.startswith(separators['segment']):
            body = body[1:]
    segments = []
    for segment in split_escaped(body, separators['segment'], separators['release']):
        if not segment.strip():
            continue
        elements = split_escaped(segment.strip(), separators['element'], separators['release'])
        tag = elements.pop(0).strip()
        segments.append({'tag': tag, 'elements': [split_escaped(e, separators['component'], separators['release']) for e in elements]})
    return {'una': una, 'separators': separators, 'segments': segments}


def parse_dtm(value, fmt, timezone='UTC'):
    if not value:
        return None
    if fmt == '102' and len(value) == 8:
        return f'{value[0:4]}-{value[4:6]}-{value[6:8]}'
    if fmt in ('203', '303') and len(value) >= 12:
        zone = UTC if timezone == 'UTC' else ZoneInfo(timezone)
        return dt.datetime(int(value[0:4]), int(value[4:6]), int(value[6:8]), int(value[8:10]), int(value[10:12]), tzinfo=zone).astimezone(UTC).isoformat()
    return None


def normalize_party_id(value):
    if not value:
        return None
    return value


def parse_mscons(raw: str, timezone='UTC'):
    tokenized = tokenize_edifact(raw)
    segments = tokenized['segments']
    unb = next((s for s in segments if s['tag'] == 'UNB'), None)
    unh_segments = [i for i, s in enumerate(segments) if s['tag'] == 'UNH']
    if not unh_segments:
        raise ValueError('Invalid MSCONS: missing UNH segment')
    messages = []
    warnings = []
    for msg_index, start in enumerate(unh_segments):
        end = next((i for i in range(start + 1, len(segments)) if segments[i]['tag'] == 'UNH'), len(segments))
        msg = segments[start:end]
        unh = msg[0]
        message_type = ':'.join(unh.get('elements', [[], []])[1] if len(unh.get('elements', [])) > 1 else [])
        if 'MSCONS' not in message_type:
            warnings.append(f'UNH message {msg_index} is not MSCONS')
            continue
        parsed = {'message_ref': unh['elements'][0][0] if unh.get('elements') and unh['elements'][0] else None,
                  'document_number': None, 'document_date': None, 'timezone': timezone,
                  'sender': {'id': None, 'qualifier': None}, 'receiver': {'id': None, 'qualifier': None},
                  'locations': [], 'parse_warnings': list(warnings), 'unb': unb, 'unt_valid': None}
        current_location = current_series = pending = None

        def push_pending():
            nonlocal pending
            if current_series is not None and pending is not None:
                pending.setdefault('quality', 'unknown')
                current_series['values'].append(pending)
            pending = None

        for offset, segment in enumerate(msg):
            tag, elements = segment['tag'], segment.get('elements', [])
            if tag == 'BGM':
                parsed['document_number'] = elements[1][0] if len(elements) > 1 and elements[1] else None
            elif tag == 'DTM':
                payload = elements[0] if elements else []
                qualifier = payload[0] if payload else None
                iso = parse_dtm(payload[1] if len(payload) > 1 else None, payload[2] if len(payload) > 2 else None, timezone)
                if qualifier == '137':
                    parsed['document_date'] = iso or (payload[1] if len(payload) > 1 else None)
                elif pending is not None:
                    if qualifier == '163': pending['timestamp'] = iso or payload[1]
                    if qualifier == '164': pending['to'] = iso or payload[1]
                elif current_location is not None:
                    if qualifier == '163': current_location['period_from'] = iso or payload[1]
                    if qualifier == '164': current_location['period_to'] = iso or payload[1]
            elif tag == 'NAD':
                role = elements[0][0] if elements and elements[0] else None
                party = elements[1] if len(elements) > 1 else []
                item = {'id': normalize_party_id(party[0] if party else None), 'qualifier': party[2] if len(party) > 2 else None}
                if role == 'MS': parsed['sender'] = item
                elif role == 'MR': parsed['receiver'] = item
            elif tag == 'LOC':
                push_pending()
                qualifier = elements[0][0] if elements and elements[0] else None
                location_id = elements[1][0] if len(elements) > 1 and elements[1] else None
                current_location = {'melo_id': location_id, 'loc_qualifier': qualifier, 'period_from': None, 'period_to': None, 'timeseries': []}
                parsed['locations'].append(current_location)
                current_series = None
            elif tag == 'CCI':
                push_pending()
                if current_location is None:
                    parsed['parse_warnings'].append('CCI segment outside of LOC group'); continue
                cci = elements[2][0] if len(elements) > 2 and elements[2] else None
                current_series = {'cci_code': cci, 'obis': CCI_TO_OBIS.get(cci), 'values': []}
                if not current_series['obis']:
                    parsed['parse_warnings'].append(f'Unsupported CCI code {cci}')
                current_location['timeseries'].append(current_series)
            elif tag == 'QTY':
                payload = elements[0] if elements else []
                if current_series is None:
                    parsed['parse_warnings'].append('QTY without active CCI context'); continue
                push_pending()
                try:
                    value = float(str(payload[1]).replace(',', '.'))
                except (IndexError, TypeError, ValueError):
                    parsed['parse_warnings'].append('QTY contains non-numeric value'); continue
                pending = {'timestamp': None, 'to': None, 'value': value, 'unit': payload[2] if len(payload) > 2 else None, 'status': None, 'quality': 'unknown'}
            elif tag == 'STS':
                if pending is None:
                    parsed['parse_warnings'].append('STS without pending QTY value'); continue
                status = elements[2][0] if len(elements) > 2 and elements[2] else None
                pending['status'] = status
                pending['quality'] = STATUS_TO_QUALITY.get(status, 'unknown')
                if status not in STATUS_TO_QUALITY:
                    parsed['parse_warnings'].append(f'Unknown STS code {status}')
                push_pending()
            elif tag == 'UNT':
                declared_ref = elements[1][0] if len(elements) > 1 and elements[1] else None
                declared_count = int(elements[0][0]) if elements and elements[0] and str(elements[0][0]).isdigit() else None
                if declared_count is not None and declared_count != len(msg):
                    raise ValueError('UNT segment count mismatch')
                parsed['unt_valid'] = declared_ref == parsed['message_ref']
                if not parsed['unt_valid']:
                    parsed['parse_warnings'].append('UNT reference does not match UNH message reference')
        push_pending()
        messages.append(parsed)
    if not messages:
        raise ValueError('Invalid MSCONS: no MSCONS UNH message found')
    return {'messages': messages, 'parse_warnings': warnings}


def select_mscons_series(parsed, *, series_id=None, melo_id=None, obis=None, cci_code=None, message_ref=None, document_number=None):
    candidates = []
    for message in parsed['messages']:
        if message_ref and message.get('message_ref') != message_ref:
            continue
        if document_number and message.get('document_number') != document_number:
            continue
        for location in message['locations']:
            if melo_id and location.get('melo_id') != melo_id:
                continue
            for timeseries in location['timeseries']:
                if obis and timeseries.get('obis') != obis:
                    continue
                if cci_code and timeseries.get('cci_code') != cci_code:
                    continue
                if not timeseries.get('obis'):
                    continue
                values = [v for v in timeseries['values'] if v.get('timestamp')]
                if values:
                    candidates.append((message, location, timeseries, values))
    if not candidates:
        raise ValueError('MSCONS contains no supported interval values for the selected filters')
    if len(candidates) > 1 and not (series_id or melo_id or obis or cci_code or message_ref or document_number):
        raise ValueError('MSCONS contains multiple candidate time series; select with --melo-id, --obis, --cci-code, --message-ref or --document-number')
    return candidates[0]


def dataset_from_mscons(path: Path, series_id: str | None = None, *, melo_id=None, obis=None, cci_code=None, message_ref=None, document_number=None, mscons_timezone='UTC'):
    if path.stat().st_size > MSCONS_MAX_BYTES:
        raise ValueError(f'MSCONS file exceeds maximum size of {MSCONS_MAX_BYTES} bytes')
    parsed = parse_mscons(path.read_text(encoding='utf-8-sig'), timezone=mscons_timezone)
    message, location, timeseries, raw_values = select_mscons_series(parsed, series_id=series_id, melo_id=melo_id, obis=obis, cci_code=cci_code, message_ref=message_ref, document_number=document_number)
    values, units = [], set()
    for row in raw_values:
        unit_raw = (row.get('unit') or '').upper()
        unit = 'kWh' if unit_raw in ('KWH', 'KWT') else 'kW' if unit_raw == 'KW' else None
        if not unit:
            raise ValueError('MSCONS contains unsupported unit')
        units.add(unit)
        values.append({'timestamp': row['timestamp'], 'value': finite_number(row['value']), 'quality': row.get('quality', 'unknown'), 'msconsStatus': row.get('status')})
    if len(units) != 1:
        raise ValueError('MSCONS input mixes units in one timeseries')
    unit = next(iter(units))
    sid = series_id or location['melo_id']
    source = {'format': 'mscons', 'messageRef': message['message_ref'], 'documentNumber': message['document_number'],
              'documentDate': message['document_date'], 'sender': message['sender'], 'receiver': message['receiver'],
              'meloId': location['melo_id'], 'locQualifier': location['loc_qualifier'], 'cciCode': timeseries['cci_code'],
              'obisEquivalent': timeseries['obis'], 'parseWarnings': message['parse_warnings']}
    envelope = {'format': 'MSCONS', 'message_ref': message['message_ref'], 'document_number': message['document_number'],
                'document_date': message['document_date'], 'timezone': message.get('timezone'), 'sender': message['sender'], 'receiver': message['receiver'],
                'location': {'melo_id': location['melo_id'], 'loc_qualifier': location['loc_qualifier']},
                'cci_code': timeseries['cci_code'], 'obis': timeseries['obis'], 'parse_warnings': message['parse_warnings']}
    dataset = {'series_id': sid, 'unit': unit, 'timezone': 'Europe/Berlin', 'mscons_timezone': 'Europe/Berlin',
               'value_semantics': 'interval_energy' if unit == 'kWh' else 'average_power',
               'source': source, 'source_envelope': envelope, 'values': values}
    audit = {'file': path.name, 'sha256': sha256_bytes(path.read_bytes()), 'series_id': sid,
             'records': len(values), 'source_format': 'MSCONS', 'document_number': message['document_number'],
             'message_ref': message['message_ref'], 'melo_id': location['melo_id'], 'obis': timeseries['obis'], 'cci_code': timeseries['cci_code']}
    return dataset, audit


def provenance_from_dataset(dataset):
    envelope = dataset.get('source_envelope') or {}
    source = dataset.get('source') or {}
    if not envelope and not source:
        return None
    return {'source_format': envelope.get('format') or str(source.get('format', '')).upper(),
            'message_ref': envelope.get('message_ref') or source.get('messageRef'),
            'document_number': envelope.get('document_number') or source.get('documentNumber'),
            'document_date': envelope.get('document_date') or source.get('documentDate'), 'timezone': envelope.get('timezone'),
            'sender': envelope.get('sender') or source.get('sender'), 'receiver': envelope.get('receiver') or source.get('receiver'),
            'melo_id': (envelope.get('location') or {}).get('melo_id') or source.get('meloId'),
            'cci_code': envelope.get('cci_code') or source.get('cciCode'), 'obis': envelope.get('obis') or source.get('obisEquivalent'),
            'parse_warnings': envelope.get('parse_warnings') or source.get('parseWarnings') or [],
            'timezone': dataset.get('mscons_timezone') or dataset.get('timezone')}


def source_provenance(items):
    items = [item for item in (items or []) if item]
    if not items:
        return None
    last = items[-1]
    return {'input_format': str(last.get('source_format') or '').lower() or None,
            'last_history_message': {'messageRef': last.get('message_ref'), 'documentNumber': last.get('document_number'),
                                     'documentDate': last.get('document_date'), 'sender': last.get('sender'), 'receiver': last.get('receiver'),
                                     'meloId': last.get('melo_id'), 'cciCode': last.get('cci_code'),
                                     'obisEquivalent': last.get('obis'), 'parseWarnings': last.get('parse_warnings') or []}}


def load_dataset(path: Path | str, series_id: str | None = None, unit: str | None = None, timezone: str | None = None, args=None):
    path = Path(path)
    suffix = path.suffix.lower()
    mscons_audit = None
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
                rows.append({'timestamp': ts, 'value': finite_number(float(value))})
        dataset = {'series_id': series_id, 'unit': unit, 'timezone': timezone, 'values': rows}
    elif suffix in MSCONS_SUFFIXES:
        if unit is not None:
            raise ValueError('MSCONS input derives the unit from QTY segments; do not pass --unit')
        if timezone is not None:
            raise ValueError('MSCONS input uses Europe/Berlin by default; do not pass --timezone')
        dataset, mscons_audit = dataset_from_mscons(path, series_id=series_id, melo_id=getattr(args, 'melo_id', None), obis=getattr(args, 'obis', None), cci_code=getattr(args, 'cci_code', None), message_ref=getattr(args, 'message_ref', None), document_number=getattr(args, 'document_number', None), mscons_timezone=(getattr(args, 'mscons_timezone', None) or 'UTC'))
        if getattr(args, 'mscons_timezone', None):
            dataset['mscons_timezone'] = args.mscons_timezone
    else:
        raise ValueError('Supported inputs are JSON, CSV and MSCONS/EDIFACT.')
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
    allow_negative = bool(getattr(args, 'allow_negative', False))
    for row in dataset.get('values') or []:
        ts = row.get('timestamp') or row.get('ts')
        t = parse_stamp(ts)
        if t in seen:
            raise ValueError('Duplicate actual timestamp')
        seen.add(t)
        val = row.get('value')
        finite_number(val) if allow_negative else finite_nonnegative(val)
        if 'ts' in row and 'timestamp' not in row:
            row['timestamp'] = row.pop('ts')
    if not seen:
        raise ValueError('Dataset is empty')
    zone = ZoneInfo(dataset['timezone'])
    dataset['period_from'] = min(seen).astimezone(zone).date().isoformat()
    dataset['period_until'] = max(seen).astimezone(zone).date().isoformat()
    audit = mscons_audit or {'file': path.name, 'sha256': sha256_bytes(path.read_bytes()), 'series_id': dataset['series_id'], 'records': len(seen)}
    return dataset, audit


def expected_intervals_for_day(day: dt.date, timezone: str) -> int:
    zone = ZoneInfo(timezone)
    start = dt.datetime.combine(day, dt.time(), zone).astimezone(UTC)
    stop = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(), zone).astimezone(UTC)
    return int((stop - start).total_seconds() // 900)


def quality_report(dataset, *, min_coverage=1.0, expected_intervals='auto', allow_gaps=False, allow_negative=False, policy='strict'):
    zone = ZoneInfo(dataset['timezone'])
    by_day = {}
    warnings, errors = [], []
    values = dataset.get('values') or []
    for row in values:
        ts = parse_stamp(row['timestamp'])
        day = ts.astimezone(zone).date()
        by_day.setdefault(day, []).append((ts, finite_number(row['value'])))
        if row['value'] < 0 and not allow_negative:
            errors.append(f'Negative value at {row["timestamp"]}')
    day_reports = []
    for day, rows in sorted(by_day.items()):
        timestamps = {ts for ts, _ in rows}
        expected = expected_intervals_for_day(day, dataset['timezone']) if expected_intervals == 'auto' else int(expected_intervals)
        coverage = len(timestamps) / expected if expected else 0
        item = {'day': day.isoformat(), 'records': len(timestamps), 'expected_intervals': expected, 'coverage': coverage}
        if len(timestamps) != len(rows):
            errors.append(f'Duplicate timestamps on {day}')
        if policy == 'strict' and coverage < min_coverage:
            errors.append(f'Coverage {coverage:.2%} below threshold on {day}')
        if policy == 'strict' and coverage < 1 and not allow_gaps:
            errors.append(f'Missing intervals on {day}')
        zero_count = sum(1 for _, value in rows if value == 0)
        if zero_count == len(rows) and rows:
            warnings.append(f'All values are zero on {day}')
        vals = [v for _, v in rows]
        if vals and max(vals) > 0 and sorted(vals)[int(0.95 * (len(vals) - 1))] > 0:
            p95 = sorted(vals)[int(0.95 * (len(vals) - 1))]
            if max(vals) > 10 * p95:
                warnings.append(f'Possible outlier on {day}: max exceeds 10x p95')
        day_reports.append(item)
    status = 'ok' if not errors else 'failed' if policy == 'strict' else 'warning'
    return {'status': status, 'policy': policy, 'series_id': dataset.get('series_id'), 'unit': dataset.get('unit'), 'timezone': dataset.get('timezone'), 'records': len(values), 'days': day_reports, 'warnings': warnings, 'errors': errors}


def enforce_quality(dataset, args, out: Path | None = None):
    report = quality_report(dataset, min_coverage=float(getattr(args, 'min_coverage', 1.0)), expected_intervals=getattr(args, 'expected_intervals', 'auto'), allow_gaps=bool(getattr(args, 'allow_gaps', False)), allow_negative=bool(getattr(args, 'allow_negative', False)), policy=getattr(args, 'quality_policy', 'strict'))
    if out:
        save_json(out / 'quality_report.json', report)
    if report['status'] == 'failed':
        raise ValueError('Quality gate failed: ' + '; '.join(report['errors']))
    return report


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('HTTP redirect refused; use the final API base URL')


class Client:
    def __init__(self, base_url: str, token: str | None = None, tenant_header: str | None = None, timeout: float = 120, debug_http: bool = False):
        self.base = base_url.rstrip('/')
        split = urllib.parse.urlsplit(self.base)
        if split.scheme not in ('http', 'https') or not split.netloc or split.username or split.password or split.query or split.fragment:
            raise ValueError('Invalid API base URL; credentials do not belong in the URL')
        self.token = token or ''
        self.tenant_header = tenant_header
        self.timeout = timeout
        self.debug_http = bool(debug_http)
        self.opener = urllib.request.build_opener(NoRedirect())

    def scrub(self, value):
        if isinstance(value, str):
            return value.replace(self.token, '[REDACTED]') if self.token else value
        if isinstance(value, list):
            return [self.scrub(item) for item in value]
        if isinstance(value, dict):
            return {key: ('[REDACTED]' if key.lower() in ('authorization', 'token') else self.scrub(item)) for key, item in value.items()}
        return value

    def call(self, route: str, payload=None, *, idempotency_key=None, method=None):
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        if self.tenant_header:
            headers['X-Tenant-Id'] = self.tenant_header
        if idempotency_key:
            headers['Idempotency-Key'] = idempotency_key
        data = None if payload is None else json.dumps(payload, allow_nan=False).encode()
        request_method = method or ('POST' if payload is not None else 'GET')
        req = urllib.request.Request(self.base + route, data=data, headers=headers, method=method)
        started = time.monotonic()
        attempts = 3 if request_method == 'GET' else 1
        last_transport_error = None
        for attempt in range(attempts):
            try:
                with self.opener.open(req, timeout=self.timeout) as response:
                    text = response.read().decode('utf-8')
                    if self.token:
                        text = text.replace(self.token, '[REDACTED]')
                    event = {'event': 'http_call', 'route': route, 'status': response.status, 'duration_ms': round((time.monotonic() - started) * 1000)}
                    if self.debug_http:
                        event['method'] = request_method
                        event['request_payload'] = self.scrub(payload)
                        event['response_headers'] = {key: value for key, value in response.headers.items() if key.lower() in ('content-type', 'request-id', 'x-request-id')}
                    LOG.info(json.dumps(event, ensure_ascii=False))
                    return json.loads(text) if text else {}
            except urllib.error.HTTPError as error:
                text = error.read().decode(errors='replace')
                if self.token:
                    text = text.replace(self.token, '[REDACTED]')
                if request_method == 'GET' and error.code in (429, 500, 502, 503, 504) and attempt + 1 < attempts:
                    time.sleep(min(2 ** attempt, 5))
                    continue
                raise ValueError(f'HTTP {error.code}: {text}') from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                last_transport_error = error
                if request_method == 'GET' and attempt + 1 < attempts:
                    time.sleep(min(2 ** attempt, 5))
                    continue
                break
        raise ConnectionError('API transport interrupted; writes are not automatically repeated') from last_transport_error

    def verify(self):
        if not re.fullmatch(r'(?:ck_|csess_)[A-Za-z0-9_.-]{20,256}', self.token or ''):
            raise ValueError('Provide CET_API_TOKEN or --token-file; tokens are never stored')
        route = '/api/tokens/verify' if self.token.startswith('ck_') else '/api/auth/verify'
        result = self.call(route, {'token': self.token, 'trackUsage': False})
        tenant = result.get('tenantId')
        if result.get('valid') is not True or not isinstance(tenant, str) or not tenant.strip():
            raise ValueError('Token is invalid or has no bound tenant; no data was submitted')
        self.tenant_header = tenant
        return tenant


def check_expected_tenant(args, actual):
    expected = getattr(args, 'tenant_id', None)
    if expected and actual != expected:
        raise ValueError('Token is bound to another tenant; no data was submitted')


def identifier(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value):
        raise ValueError('Expected a SHA-256 model/run ID')
    return value


def token_from(args):
    if getattr(args, 'token_file', None):
        return args.token_file.read_text(encoding='utf-8').strip()
    return os.environ.get('CET_API_TOKEN', '').strip()


def client_for(args):
    return Client(args.base_url, token_from(args), None, args.timeout, getattr(args, 'debug_http', False))


def resolved_child_path(root: Path, child: Path) -> Path:
    root_resolved = root.resolve()
    child_resolved = child.resolve()
    if child_resolved != root_resolved and root_resolved not in child_resolved.parents:
        raise ValueError(f'Batch input path escapes input directory: {child}')
    return child


def client_run_id(operation, payload) -> str:
    return sha256_json({'operation': operation, 'payload': payload})


def await_result(client: Client, job, args):
    if job.get('status') == 'completed':
        return job.get('result', job)
    if job.get('status') in ('failed', 'error', 'cancelled'):
        raise ValueError('Server job ended with status ' + str(job.get('status')) + ': ' + str(job.get('error') or job.get('message') or ''))
    run_id = identifier(job['run_id'])
    deadline = time.monotonic() + args.job_timeout
    while time.monotonic() < deadline:
        status_path = job.get('statusUrl')
        if status_path:
            status_state = client.call(status_path, method='GET')
            if status_state.get('status') in ('failed', 'error', 'cancelled'):
                raise ValueError('Server job ended with status ' + str(status_state.get('status')) + ': ' + str(status_state.get('error') or status_state.get('message') or ''))
        state = client.call(ROOT + '/runs/' + run_id, method='GET')
        if state.get('status') == 'completed':
            return state.get('result', state)
        if state.get('status') in ('failed', 'error', 'cancelled'):
            raise ValueError('Server job ended with status ' + str(state.get('status')) + ': ' + str(state.get('error') or state.get('message') or ''))
        time.sleep(args.poll_interval)
    raise ValueError('Client wait expired; server job was not cancelled. Continue with resume.')


def fresh_out(path: Path, resume=False):
    if resume and path.exists():
        return
    path.mkdir(parents=True, exist_ok=False, mode=0o700)


def write_forecast_csv(path: Path, result):
    rows = result.get('forecast_values') or result.get('forecast') or []
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['timestamp', 'predicted_value'])
        writer.writeheader()
        for row in rows:
            writer.writerow({'timestamp': csv_safe(row.get('timestamp') or row.get('ts')), 'predicted_value': csv_safe(row.get('predicted_value') if 'predicted_value' in row else row.get('value'))})


def write_residuals_csv(path: Path, residuals):
    fieldnames = ['timestamp', 'actual', 'predicted', 'error', 'absolute_error', 'percentage_error']
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in residuals:
            writer.writerow({field: csv_safe(row.get(field)) for field in fieldnames})


def output_formats(args):
    value = getattr(args, 'output_format', 'json') or 'json'
    return {x.strip() for x in value.split(',') if x.strip()}


def pseudonymize_value(value):
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in ('melo_id', 'meloId') and isinstance(v, str):
                out[k + '_hash'] = sha256_bytes(v.encode())
            else:
                out[k] = pseudonymize_value(v)
        return out
    if isinstance(value, list):
        return [pseudonymize_value(v) for v in value]
    return value

def emit_result(args, envelope):
    if getattr(args, 'provenance_level', None) == 'pseudonymized':
        envelope = pseudonymize_value(envelope)
    save_json(args.out / 'result.json', envelope)
    if 'csv' in output_formats(args):
        write_forecast_csv(args.out / 'forecast.csv', envelope.get('result') or {})
    if 'dataset-json' in output_formats(args):
        save_json(args.out / 'forecast.dataset.json', {'result': envelope.get('result'), 'provenance': envelope.get('input_provenance')})
    if getattr(args, 'stdout_json', False):
        print(json.dumps(envelope, ensure_ascii=False, allow_nan=False))


def cmd_day_ahead(args):
    fresh_out(args.out, getattr(args, 'resume_out', False))
    history = load_history_values(args.history)
    payload = {'seriesId': args.series_id, 'forecastDate': str(args.forecast_for), 'granularity': 'PT15M', 'timezone': args.timezone, 'unit': args.unit,
               'historicalValues': history, 'options': {'includeConfidenceBand': args.confidence_band, 'includeQualityHints': True, 'method': 'baseline'}}
    context = apply_location_context(payload, args)
    if context:
        payload['options']['forecastContext'] = context
    idem = client_run_id('day-ahead', payload)
    payload['clientRunId'] = idem
    result = Client(args.base_url, timeout=args.timeout).call(SANDBOX + '/day-ahead', payload, idempotency_key=idem)
    save_json(args.out / 'request.json', payload)
    emit_result(args, {'base_url': args.base_url.rstrip('/'), 'result': result, 'client_run_id': idem})
    print('Completed: ' + str(args.out / 'result.json'))


def state_base(args, operation):
    return {'tenant_id': args.tenant_id, 'base_url': args.base_url.rstrip('/'), 'operation': operation, 'created_at': dt.datetime.now(UTC).isoformat(), 'uploads': []}




def ledger_contains(path: Path, key: str) -> bool:
    if not path or not path.exists():
        return False
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        try:
            if json.loads(line).get('idempotency_key') == key:
                return True
        except json.JSONDecodeError:
            continue
    return False


def ledger_append(path: Path, key: str, payload: dict):
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps({'idempotency_key': key, **payload}, ensure_ascii=False) + '\n')

def cmd_history_like(args, train_after=False):
    fresh_out(args.out, getattr(args, 'resume_out', False))
    dataset, audit = load_dataset(args.input, args.series_id, args.unit, args.timezone, args=args)
    quality = enforce_quality(dataset, args, args.out)
    context = apply_location_context(dataset, args)
    state = state_base(args, 'enroll' if train_after else 'history')
    state['inputs'] = [audit]
    state['quality'] = quality
    dataset_provenance = provenance_from_dataset(dataset)
    input_provenance = [dataset_provenance] if dataset_provenance else []
    if input_provenance:
        state['input_provenance'] = input_provenance
        state['source_provenance'] = source_provenance(input_provenance)
    if context:
        state['forecast_context'] = context
        if context.get('site_context'): state['site_context'] = context['site_context']
        if context.get('weather_region'): state['weather_region'] = context['weather_region']
    if train_after:
        request = {'series_ids': [dataset['series_id']], 'strategy': 'shared_baseline', 'forecast_for': str(args.forecast_for)}
        if context:
            request['forecast_context'] = context
            if context.get('site_context'): request['site_context'] = context['site_context']
            if context.get('weather_region'): request['weather_region'] = context['weather_region']
        if getattr(args, 'import_mode', None):
            request['import_mode'] = args.import_mode
        state['request'] = request
    else:
        request = None
    history_payload = {'dataset': dataset, 'historical_import': args.historical_import or train_after, 'allow_corrections': args.allow_corrections,
                       'import_mode': getattr(args, 'import_mode', 'append-only')}
    history_idem = client_run_id('history', {'audit': audit, 'payload': history_payload}) if getattr(args, 'idempotency_key', None) in (None, 'auto') else args.idempotency_key
    state['client_run_id'] = history_idem
    if getattr(args, 'processed_ledger', None) and getattr(args, 'skip_if_processed', False) and ledger_contains(args.processed_ledger, history_idem):
        state['status'] = 'skipped_already_processed'
        save_json(args.out / 'summary.json', {'status': 'skipped_already_processed', 'idempotency_key': history_idem})
        save_json(args.out / 'run.json', state)
        return 10
    if args.dry_run:
        state['status'] = 'dry_run'
        save_json(args.out / 'run.json', state)
        print('Plan validated without HTTP: ' + str(args.out / 'run.json'))
        return
    client = client_for(args)
    tenant = client.verify(); check_expected_tenant(args, tenant); state['tenant_id'] = tenant
    save_json(args.out / 'run.json', {**state, 'status': 'upload_submission_pending'})
    uploaded = client.call(ROOT + '/history', history_payload, idempotency_key=history_idem)
    state['uploads'].append(uploaded)
    if not train_after:
        state['status'] = 'completed'; save_json(args.out / 'run.json', state)
        result_envelope = {'tenant_id': tenant, 'base_url': client.base, 'result': uploaded, 'client_run_id': history_idem, 'quality': quality}
        if input_provenance:
            result_envelope['input_provenance'] = input_provenance
            result_envelope['source_provenance'] = source_provenance(input_provenance)
        save_json(args.out / 'result.json', result_envelope)
        ledger_append(getattr(args, 'processed_ledger', None), history_idem, {'status': 'completed', 'series_id': dataset['series_id']})
        print('History stored: ' + str(args.out / 'result.json'))
        return
    assert request is not None
    train_idem = client_run_id('train', request)
    request['clientRunId'] = train_idem
    state['status'] = 'job_submission_pending'; state['train_client_run_id'] = train_idem; save_json(args.out / 'run.json', state)
    job = client.call(ROOT + '/train', request, idempotency_key=train_idem)
    state['job'] = job; save_json(args.out / 'run.json', state)
    result = await_result(client, job, args)
    result_envelope = {'tenant_id': tenant, 'base_url': client.base, 'result': result, 'client_run_id': train_idem, 'quality': quality}
    if input_provenance:
        result_envelope['input_provenance'] = input_provenance
        result_envelope['source_provenance'] = source_provenance(input_provenance)
        if isinstance(result_envelope['result'], dict):
            result_envelope['result']['input_provenance'] = input_provenance
            result_envelope['result']['source_provenance'] = source_provenance(input_provenance)
    emit_result(args, result_envelope)
    state['status'] = 'completed'; save_json(args.out / 'run.json', state)
    ledger_append(getattr(args, 'processed_ledger', None), history_idem, {'status': 'completed', 'series_id': dataset['series_id']})
    print('Completed: ' + str(args.out / 'result.json'))


def model_version(args):
    if args.model_version:
        return identifier(args.model_version)
    envelope = read_json(args.model_file)
    if args.tenant_id and envelope.get('tenant_id') != args.tenant_id:
        raise ValueError('Model file belongs to a different tenant')
    return identifier(envelope['result']['model_version'])


def cmd_train(args):
    fresh_out(args.out, getattr(args, 'resume_out', False))
    request = {'series_ids': args.series_ids, 'strategy': getattr(args, 'strategy', 'shared_baseline'), 'forecast_for': str(args.forecast_for)}
    context = apply_location_context(request, args)
    idem = client_run_id('train', request); request['clientRunId'] = idem
    state = {**state_base(args, 'train'), 'request': request, 'client_run_id': idem}
    if context: state['forecast_context'] = context
    if args.dry_run:
        state['status'] = 'dry_run'; save_json(args.out / 'run.json', state); print('Plan validated without HTTP: ' + str(args.out / 'run.json')); return
    client = client_for(args); tenant = client.verify(); check_expected_tenant(args, tenant); state['tenant_id'] = tenant
    job = client.call(ROOT + '/train', request, idempotency_key=idem); state['job'] = job; save_json(args.out / 'run.json', state)
    result = await_result(client, job, args)
    emit_result(args, {'tenant_id': tenant, 'base_url': client.base, 'result': result, 'client_run_id': idem})
    state['status'] = 'completed'; save_json(args.out / 'run.json', state)
    print('Completed: ' + str(args.out / 'result.json'))


def model_provenance(args):
    if not args.model_file:
        return []
    envelope = read_json(args.model_file)
    return envelope.get('input_provenance') or envelope.get('result', {}).get('input_provenance') or []


def cmd_predict(args):
    fresh_out(args.out, getattr(args, 'resume_out', False))
    request = {'series_id': args.series_id, 'model_version': model_version(args), 'forecast_for': str(args.forecast_for), 'allow_stale_model': args.allow_stale_model}
    context = apply_location_context(request, args)
    if args.history_version: request['history_version'] = identifier(args.history_version)
    idem = client_run_id('predict', request); request['clientRunId'] = idem
    state = {**state_base(args, 'predict'), 'request': request, 'client_run_id': idem}
    input_provenance = model_provenance(args)
    if input_provenance:
        state['input_provenance'] = input_provenance
        state['source_provenance'] = source_provenance(input_provenance)
    if context: state['forecast_context'] = context
    if args.dry_run:
        state['status'] = 'dry_run'; save_json(args.out / 'run.json', state); print('Plan validated without HTTP: ' + str(args.out / 'run.json')); return
    client = client_for(args); tenant = client.verify(); check_expected_tenant(args, tenant); state['tenant_id'] = tenant
    job = client.call(ROOT + '/predict', request, idempotency_key=idem); state['job'] = job; save_json(args.out / 'run.json', state)
    result = await_result(client, job, args)
    result_envelope = {'tenant_id': tenant, 'base_url': client.base, 'result': result, 'client_run_id': idem}
    if input_provenance:
        result_envelope['input_provenance'] = input_provenance
        result_envelope['source_provenance'] = source_provenance(input_provenance)
        if isinstance(result_envelope['result'], dict):
            result_envelope['result']['input_provenance'] = input_provenance
            result_envelope['result']['source_provenance'] = source_provenance(input_provenance)
    emit_result(args, result_envelope)
    state['status'] = 'completed'; save_json(args.out / 'run.json', state)
    print('Completed: ' + str(args.out / 'result.json'))


def cmd_resume(args):
    fresh_out(args.out, getattr(args, 'resume_out', False))
    state = read_json(args.run_file)
    client = client_for(args); tenant = client.verify(); check_expected_tenant(args, tenant)
    if state.get('tenant_id') and state['tenant_id'] != tenant:
        raise ValueError('Resume requires the original tenant')
    run_id = identifier(state['job']['run_id'])
    job = client.call(ROOT + '/runs/' + run_id + '/resume', {}, idempotency_key=state.get('client_run_id')) if args.restart else state['job']
    result = await_result(client, job, args)
    emit_result(args, {'tenant_id': tenant, 'base_url': client.base, 'result': result, 'client_run_id': state.get('client_run_id')})
    state['status'] = 'completed'; save_json(args.out / 'run.json', state)
    print('Completed: ' + str(args.out / 'result.json'))


def prediction_rows(result):
    rows = result.get('forecast_values') or result.get('forecast')
    if not isinstance(rows, list):
        raise ValueError('Prediction has no forecast_values/forecast list')
    for row in rows:
        ts = row.get('timestamp') or row.get('ts')
        val = row.get('predicted_value') if 'predicted_value' in row else row.get('value')
        yield parse_stamp(ts), finite_number(val)


def metric_summary(pairs, *, expected_intervals=None):
    if not pairs:
        raise ValueError('Cannot compute forecast quality without overlapping values')
    residuals = []
    for t, actual_v, pred in pairs:
        err = pred - actual_v
        residuals.append({'timestamp': t.isoformat(), 'actual': actual_v, 'predicted': pred, 'error': err, 'absolute_error': abs(err), 'percentage_error': None if actual_v == 0 else 100 * err / actual_v})
    absolute = math.fsum(r['absolute_error'] for r in residuals)
    signed = math.fsum(r['error'] for r in residuals)
    squared = math.fsum(r['error'] * r['error'] for r in residuals)
    actual_total = math.fsum(abs(r['actual']) for r in residuals)
    predicted_total = math.fsum(abs(r['predicted']) for r in residuals)
    expected = expected_intervals or len(residuals)
    return {
        'sample_count': len(residuals),
        'expected_intervals': expected,
        'coverage': len(residuals) / expected if expected else 1.0,
        'rmse': math.sqrt(squared / len(residuals)),
        'mae': absolute / len(residuals),
        'wape_percent': 100 * absolute / actual_total if actual_total else None,
        'bias': signed / len(residuals),
        'bias_percent': 100 * signed / actual_total if actual_total else None,
        'actual_total': actual_total,
        'predicted_total': predicted_total,
    }, residuals


def load_predictions(args):
    predictions = {}; tenant = args.tenant_id
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
    return tenant, predictions


def actual_truth(args):
    actual, audit = load_dataset(args.actuals, args.series_id, args.unit, args.timezone, args=args)
    enforce_quality(actual, args, args.out)
    return actual, audit, {parse_stamp(r['timestamp']): finite_number(r['value']) for r in actual['values']}


def cmd_score(args):
    fresh_out(args.out, getattr(args, 'resume_out', False))
    actual, audit, truth = actual_truth(args)
    tenant, predictions = load_predictions(args)
    matching = sorted(predictions.keys() & truth.keys())
    if not matching or (len(matching) != len(predictions) and not args.allow_partial):
        raise ValueError('Missing actual values; use --allow-partial only for an explicitly partial report')
    metrics, residuals = metric_summary([(t, truth[t], predictions[t]) for t in matching], expected_intervals=len(predictions))
    metrics = {'tenant_id': tenant, 'series_id': args.series_id, 'unit': actual['unit'], **metrics, 'actual_source': audit}
    save_json(args.out / 'metrics.json', metrics)
    save_json(args.out / 'residuals.json', {'series_id': args.series_id, 'rows': residuals})
    write_residuals_csv(args.out / 'residuals.csv', residuals)
    wape = 'undefined' if metrics['wape_percent'] is None else f"{metrics['wape_percent']:.4f} %"
    report = f"# Forecast quality — {args.series_id}\n\nTenant: {tenant or 'n/a'}. Unit: {actual['unit']}.\n\nN: {metrics['sample_count']}\nCoverage: {metrics['coverage']:.2%}\nRMSE: {metrics['rmse']:.6f}\nMAE: {metrics['mae']:.6f}\nWAPE: {wape}\n"
    (args.out / 'report.md').write_text(report, encoding='utf-8')
    print(report)
    limit_wape = args.max_wape if args.max_wape is not None else getattr(args, 'fail_if_wape_above', None)
    if limit_wape is not None and metrics['wape_percent'] is not None and metrics['wape_percent'] > limit_wape:
        return 50
    if args.max_mae is not None and metrics['mae'] > args.max_mae:
        raise ValueError('Forecast quality threshold failed: MAE exceeds --max-mae')
    if args.min_score_coverage is not None and metrics['coverage'] < args.min_score_coverage:
        raise ValueError('Forecast quality threshold failed: coverage below --min-score-coverage')


def normalize_baseline_name(name: str) -> str:
    aliases = {
        'persistence': 'previous_day',
        'previous-day': 'previous_day',
        'previous_day': 'previous_day',
        'weekly_naive': 'previous_week',
        'previous-week': 'previous_week',
        'previous_week': 'previous_week',
        'rolling-mean': 'rolling_mean',
        'rolling_mean': 'rolling_mean',
    }
    key = (name or '').strip()
    if key not in aliases:
        raise ValueError('Unsupported baseline: ' + str(name))
    return aliases[key]


def baseline_prediction(ts: dt.datetime, history: dict, baseline: str, *, rolling_days: int = 7):
    baseline = normalize_baseline_name(baseline)
    if baseline == 'previous_day':
        return history.get(ts - dt.timedelta(days=1))
    if baseline == 'previous_week':
        return history.get(ts - dt.timedelta(days=7))
    if baseline == 'rolling_mean':
        values = []
        for days in range(1, rolling_days + 1):
            value = history.get(ts - dt.timedelta(days=days))
            if value is not None:
                values.append(value)
        return math.fsum(values) / len(values) if values else None
    raise ValueError('Unsupported baseline: ' + baseline)


def benchmark_prediction(ts: dt.datetime, history: dict, benchmark: str):
    return baseline_prediction(ts, history, benchmark)


def acceptance_thresholds(profile: str):
    profiles = {
        'monitoring': {'max_wape': 15.0, 'max_bias': 10.0, 'min_coverage': 1.0},
        'portfolio': {'max_wape': 8.0, 'max_bias': 5.0, 'min_coverage': 1.0},
        'system-load': {'max_wape': 10.0, 'max_bias': 10.0, 'min_coverage': 1.0},
        'household': {'max_wape': 30.0, 'max_bias': 20.0, 'min_coverage': 0.95},
        'industrial': {'max_wape': 20.0, 'max_bias': 15.0, 'min_coverage': 0.98},
        'volatile': {'max_wape': 40.0, 'max_bias': 25.0, 'min_coverage': 0.95},
        'strict': {'max_wape': 5.0, 'max_bias': 2.0, 'min_coverage': 1.0},
    }
    return profiles[profile]


def cmd_acceptance_test(args):
    fresh_out(args.out, getattr(args, 'resume_out', False))
    actual, audit, truth = actual_truth(args)
    tenant, predictions = load_predictions(args)
    matching = sorted(predictions.keys() & truth.keys())
    if not matching or len(matching) != len(predictions):
        raise ValueError('Acceptance test requires complete actuals for every prediction timestamp')
    model_metrics, residuals = metric_summary([(t, truth[t], predictions[t]) for t in matching], expected_intervals=len(predictions))

    history, history_audit = load_dataset(args.history, args.series_id, args.unit, args.timezone, args=args)
    history_by_ts = {parse_stamp(r['timestamp']): finite_number(r['value']) for r in history['values']}
    benchmarks = {}
    benchmark_names = list(dict.fromkeys(list(args.benchmarks or []) + list(args.require_better_than or [])))
    for name in benchmark_names:
        pairs = []
        for t in matching:
            value = benchmark_prediction(t, history_by_ts, name)
            if value is not None:
                pairs.append((t, truth[t], value))
        if len(pairs) != len(matching):
            benchmarks[name] = {'status': 'insufficient_history', 'sample_count': len(pairs), 'expected_intervals': len(matching)}
            continue
        metrics, _ = metric_summary(pairs, expected_intervals=len(matching))
        benchmarks[name] = {'status': 'ok', **metrics}

    thresholds = acceptance_thresholds(args.acceptance_profile)
    max_wape = args.max_wape if args.max_wape is not None else thresholds['max_wape']
    max_bias = args.max_bias if args.max_bias is not None else thresholds['max_bias']
    min_coverage = args.min_score_coverage if args.min_score_coverage is not None else thresholds['min_coverage']
    decision = {
        'within_wape_threshold': model_metrics['wape_percent'] is not None and model_metrics['wape_percent'] <= max_wape,
        'within_bias_threshold': model_metrics['bias_percent'] is not None and abs(model_metrics['bias_percent']) <= max_bias,
        'within_coverage_threshold': model_metrics['coverage'] >= min_coverage,
    }
    required = args.require_better_than or []
    for name in required:
        bm = benchmarks.get(name)
        key = 'better_than_' + name
        if not bm or bm.get('status') != 'ok' or model_metrics['wape_percent'] is None or bm.get('wape_percent') is None:
            decision[key] = False
        else:
            required_wape = bm['wape_percent'] * (1 - args.min_relative_improvement)
            decision[key] = model_metrics['wape_percent'] <= required_wape
    status = 'pass' if all(decision.values()) else 'fail'
    report = {
        'status': status,
        'profile': args.acceptance_profile,
        'tenant_id': tenant,
        'series_id': args.series_id,
        'unit': actual['unit'],
        'model': model_metrics,
        'benchmarks': benchmarks,
        'thresholds': {'max_wape_percent': max_wape, 'max_abs_bias_percent': max_bias, 'min_coverage': min_coverage, 'min_relative_improvement': args.min_relative_improvement},
        'decision': decision,
        'actual_source': audit,
        'history_source': history_audit,
    }
    save_json(args.out / 'acceptance_report.json', report)
    save_json(args.out / 'residuals.json', {'series_id': args.series_id, 'rows': residuals})
    write_residuals_csv(args.out / 'residuals.csv', residuals)
    lines = [f"# Forecast acceptance — {args.series_id}", '', f"Status: {status}", f"Profile: {args.acceptance_profile}", f"Model WAPE: {model_metrics['wape_percent']:.4f}%", f"Model bias: {model_metrics['bias_percent']:.4f}%", '']
    for name, bm in benchmarks.items():
        if bm.get('status') == 'ok':
            lines.append(f"- Benchmark {name}: WAPE {bm['wape_percent']:.4f}%")
        else:
            lines.append(f"- Benchmark {name}: {bm.get('status')} ({bm.get('sample_count')}/{bm.get('expected_intervals')})")
    lines.append('')
    for key, value in decision.items():
        lines.append(f"- {'OK' if value else 'FAIL'} {key}")
    (args.out / 'acceptance_report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines))
    return 0 if status == 'pass' else 50


def e2e_baseline_metrics(history_by_ts, truth, matching, baselines):
    baseline_metrics = {}
    for requested in baselines:
        name = normalize_baseline_name(requested)
        pairs = []
        for t in matching:
            value = baseline_prediction(t, history_by_ts, name)
            if value is not None:
                pairs.append((t, truth[t], value))
        if len(pairs) != len(matching):
            baseline_metrics[name] = {'status': 'insufficient_history', 'sample_count': len(pairs), 'expected_intervals': len(matching)}
            continue
        metrics, _ = metric_summary(pairs, expected_intervals=len(matching))
        baseline_metrics[name] = {'status': 'ok', **metrics}
    return baseline_metrics


def leakage_check(history_by_ts, truth):
    if not history_by_ts or not truth:
        return {'status': 'fail', 'reason': 'history and actuals are required'}
    last_history = max(history_by_ts)
    first_actual = min(truth)
    ok = last_history < first_actual
    return {'status': 'ok' if ok else 'fail', 'last_history_timestamp': last_history.isoformat(), 'first_actual_timestamp': first_actual.isoformat(), 'reason': None if ok else 'actuals overlap with training/history window'}


def history_days_before_d2(history_by_ts, forecast_for: dt.date, timezone: str, min_days: int):
    zone = ZoneInfo(timezone)
    cutoff = forecast_for - dt.timedelta(days=2)
    observed_days = sorted({stamp.astimezone(zone).date() for stamp in history_by_ts if stamp.astimezone(zone).date() <= cutoff})
    ok = len(observed_days) >= min_days
    return {
        'status': 'ok' if ok else 'fail',
        'min_required_days_before_d2': min_days,
        'observed_days_before_d2': len(observed_days),
        'cutoff_date': cutoff.isoformat(),
        'first_observed_date': observed_days[0].isoformat() if observed_days else None,
        'last_observed_date_before_d2': observed_days[-1].isoformat() if observed_days else None,
        'reason': None if ok else f'at least {min_days} observed history days required before D-2; missing history is not zero',
    }


def quality_gate(profile, forecast_metrics, baseline_metrics, *, max_wape=None, min_coverage=None, baseline_tolerance=0.0, require_baseline_delta=True):
    thresholds = acceptance_thresholds(profile)
    wape_limit = thresholds['max_wape'] if max_wape is None else max_wape
    coverage_limit = thresholds['min_coverage'] if min_coverage is None else min_coverage
    checks = {
        'coverage': forecast_metrics.get('coverage', 0) >= coverage_limit,
        'wape': forecast_metrics.get('wape_percent') is not None and forecast_metrics['wape_percent'] <= wape_limit,
    }
    ok_baselines = {k: v for k, v in baseline_metrics.items() if v.get('status') == 'ok' and v.get('wape_percent') is not None}
    best_name = None
    best_wape = None
    if ok_baselines:
        best_name, best = min(ok_baselines.items(), key=lambda item: item[1]['wape_percent'])
        best_wape = best['wape_percent']
        checks['baseline_delta'] = (not require_baseline_delta) or forecast_metrics['wape_percent'] <= best_wape + baseline_tolerance
    else:
        checks['baseline_delta'] = not require_baseline_delta
    status = 'pass' if all(checks.values()) else 'fail'
    return {'status': status, 'profile': profile, 'checks': checks, 'thresholds': {'max_wape_percent': wape_limit, 'min_coverage': coverage_limit, 'baseline_tolerance': baseline_tolerance}, 'best_baseline': {'name': best_name, 'wape_percent': best_wape}}


def cmd_e2e(args):
    fresh_out(args.out, getattr(args, 'resume_out', False))
    history, history_audit = load_dataset(args.history, args.series_id, args.unit, args.timezone, args=args)
    actual, actual_audit = load_dataset(args.actuals, args.series_id, args.unit, args.timezone, args=args)
    history_quality = quality_report(history, min_coverage=args.min_coverage, expected_intervals=args.expected_intervals, allow_gaps=args.allow_gaps, allow_negative=args.allow_negative, policy=args.quality_policy)
    actual_quality = quality_report(actual, min_coverage=args.min_coverage, expected_intervals=args.expected_intervals, allow_gaps=args.allow_gaps, allow_negative=args.allow_negative, policy=args.quality_policy)
    if history_quality['status'] == 'failed' or actual_quality['status'] == 'failed':
        raise ValueError('E2E data quality gate failed before API calls')
    history_by_ts = {parse_stamp(r['timestamp']): finite_number(r['value']) for r in history['values']}
    truth = {parse_stamp(r['timestamp']): finite_number(r['value']) for r in actual['values']}
    leak = leakage_check(history_by_ts, truth)
    if leak['status'] != 'ok':
        raise ValueError('Forecast leakage boundary failed: ' + str(leak.get('reason')))
    history_window = history_days_before_d2(history_by_ts, args.forecast_for, history['timezone'], args.min_history_days_before_d2)
    if history_window['status'] != 'ok':
        raise ValueError('E2E history window failed: ' + str(history_window.get('reason')))
    context = apply_location_context(history, args)
    client = client_for(args)
    tenant = client.verify(); check_expected_tenant(args, tenant)
    history_payload = {'dataset': history, 'historical_import': True, 'allow_corrections': False, 'import_mode': 'append-only'}
    history_idem = client_run_id('e2e-history', {'audit': history_audit, 'payload': history_payload})
    uploaded = client.call(ROOT + '/history', history_payload, idempotency_key=history_idem)
    train_request = {'series_ids': [history['series_id']], 'strategy': args.strategy, 'forecast_for': str(args.forecast_for)}
    if context:
        train_request['forecast_context'] = context
        if context.get('weather_region'):
            train_request['weather_region'] = context['weather_region']
        if context.get('site_context'):
            train_request['site_context'] = context['site_context']
    train_idem = client_run_id('e2e-train', train_request); train_request['clientRunId'] = train_idem
    train_job = client.call(ROOT + '/train', train_request, idempotency_key=train_idem)
    train_result = await_result(client, train_job, args)
    model = train_result.get('model_version') or train_result.get('modelVersion')
    if not model:
        raise ValueError('Train result did not include a model_version')
    predict_request = {'series_id': history['series_id'], 'model_version': identifier(model), 'forecast_for': str(args.forecast_for), 'allow_stale_model': args.allow_stale_model}
    if uploaded.get('history_version'):
        predict_request['history_version'] = uploaded['history_version']
    if context:
        predict_request['forecast_context'] = context
        if context.get('weather_region'):
            predict_request['weather_region'] = context['weather_region']
    predict_idem = client_run_id('e2e-predict', predict_request); predict_request['clientRunId'] = predict_idem
    predict_job = client.call(ROOT + '/predict', predict_request, idempotency_key=predict_idem)
    forecast_result = await_result(client, predict_job, args)
    predictions = {ts: val for ts, val in prediction_rows(forecast_result)}
    matching = sorted(predictions.keys() & truth.keys())
    if not matching or len(matching) != len(predictions):
        raise ValueError('E2E requires complete actuals for every prediction timestamp')
    forecast_metrics, residuals = metric_summary([(t, truth[t], predictions[t]) for t in matching], expected_intervals=len(predictions))
    baseline_metrics = e2e_baseline_metrics(history_by_ts, truth, matching, args.baselines.split(','))
    gate = quality_gate(args.quality_profile, forecast_metrics, baseline_metrics, max_wape=args.max_wape, min_coverage=args.min_score_coverage, baseline_tolerance=args.baseline_tolerance, require_baseline_delta=not args.no_baseline_gate)
    manifest = {
        'tenant_id': tenant,
        'base_url': client.base,
        'series_id': history['series_id'],
        'forecast_for': str(args.forecast_for),
        'history_source': history_audit,
        'actual_source': actual_audit,
        'history_quality': history_quality,
        'actual_quality': actual_quality,
        'leakage_check': leak,
        'history_window_check': history_window,
        'forecast_context': context,
        'history_result': uploaded,
        'train_result': train_result,
        'predict_result': forecast_result,
        'client_run_ids': {'history': history_idem, 'train': train_idem, 'predict': predict_idem},
    }
    summary = {
        'status': gate['status'],
        'tenant_id': tenant,
        'series_id': history['series_id'],
        'forecast_for': str(args.forecast_for),
        'quality_profile': args.quality_profile,
        'forecast_context': context,
        'leakage_check': leak,
        'history_window_check': history_window,
        'forecast_metrics': forecast_metrics,
        'baseline_metrics': baseline_metrics,
        'quality_gate': gate,
    }
    save_json(args.out / 'run_manifest.json', manifest)
    save_json(args.out / 'prediction_result.json', {'tenant_id': tenant, 'base_url': client.base, 'result': forecast_result, 'client_run_id': predict_idem})
    save_json(args.out / 'baseline_metrics.json', baseline_metrics)
    save_json(args.out / 'quality_gate.json', gate)
    save_json(args.out / 'e2e-summary.json', summary)
    save_json(args.out / 'residuals.json', {'series_id': history['series_id'], 'rows': residuals})
    write_residuals_csv(args.out / 'residuals.csv', residuals)
    lines = [f"# Forecast E2E acceptance — {history['series_id']}", '', f"Status: {gate['status']}", f"Profile: {args.quality_profile}", f"Forecast WAPE: {forecast_metrics['wape_percent']:.4f}%", f"Coverage: {forecast_metrics['coverage']:.2%}", f"Leakage check: {leak['status']}", '']
    for name, bm in baseline_metrics.items():
        if bm.get('status') == 'ok':
            lines.append(f"- Baseline {name}: WAPE {bm['wape_percent']:.4f}%")
        else:
            lines.append(f"- Baseline {name}: {bm.get('status')} ({bm.get('sample_count')}/{bm.get('expected_intervals')})")
    lines.append('')
    for key, value in gate['checks'].items():
        lines.append(f"- {'OK' if value else 'FAIL'} {key}")
    (args.out / 'e2e-report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines))
    return 0 if gate['status'] == 'pass' else 50


def cmd_doctor(args):
    fresh_out(args.out, getattr(args, 'resume_out', False))
    client = client_for(args)
    checks = []
    def record(name, ok, detail=None): checks.append({'name': name, 'ok': bool(ok), 'detail': detail})
    try:
        split = urllib.parse.urlsplit(args.base_url)
        record('base_url', split.scheme in ('http', 'https') and bool(split.netloc), args.base_url)
        try:
            openapi = Client(args.base_url, timeout=args.timeout).call('/api/openapi.json', method='GET')
            paths = openapi.get('paths') or {}
            record('openapi', True, {'version': (openapi.get('info') or {}).get('version')})
            for route in (ROOT + '/history', ROOT + '/train', ROOT + '/predict'):
                record('route:' + route, route in paths, None)
        except Exception as error:
            record('openapi', False, str(error))
        if token_from(args):
            tenant = client.verify(); check_expected_tenant(args, tenant); record('token', True, {'tenant_id': tenant})
        else:
            record('token', False, 'No token supplied')
    finally:
        ok = all(c['ok'] for c in checks if not c['name'].startswith('route:'))
        payload = {'status': 'ok' if ok else 'failed', 'checks': checks, 'base_url': args.base_url.rstrip('/')}
        save_json(args.out / 'doctor.json', payload)
        (args.out / 'doctor.md').write_text('# Cernion Forecast CLI Doctor\n\n' + '\n'.join(f"- {'OK' if c['ok'] else 'FAIL'} {c['name']}: {c.get('detail')}" for c in checks) + '\n', encoding='utf-8')
    if not ok:
        raise ValueError('Doctor checks failed')
    print('Doctor OK: ' + str(args.out / 'doctor.json'))




def cmd_batch_history(args):
    fresh_out(args.out, getattr(args, 'resume_out', False))
    input_root = args.input_dir.resolve()
    files = sorted(resolved_child_path(input_root, file) for file in args.input_dir.glob(args.glob))
    if args.log_format == 'json':
        print(json.dumps({'event': 'batch_started', 'files': len(files)}, ensure_ascii=False))
    processed = failed = 0
    items = []
    for file in files:
        try:
            payload = read_json(file) if file.suffix.lower() == '.json' else None
            sid = payload.get(args.series_id_field) if isinstance(payload, dict) else None
            sid = sid or getattr(args, 'series_id', None) or file.stem
            item_out = args.out / file.stem
            child = argparse.Namespace(**vars(args))
            child.input = file
            child.series_id = sid
            child.out = item_out
            child.output_format = 'json'
            child.stdout_json = False
            child.unit = getattr(args, 'unit', None)
            child.timezone = getattr(args, 'timezone', None)
            child.allow_corrections = False
            child.historical_import = False
            child.import_mode = 'append-only'
            child.processed_ledger = None
            child.idempotency_key = None
            child.skip_if_processed = False
            rc = cmd_history_like(child, train_after=False)
            rc = rc if isinstance(rc, int) else 0
            if rc == 0:
                processed += 1; status = 'ok'
            else:
                failed += 1; status = 'failed'
        except Exception as error:
            failed += 1; status = 'failed'; rc = 1
        items.append({'file': str(file), 'status': status, 'exit_code': rc})
    summary = {'status': 'ok' if failed == 0 else 'failed', 'processed': processed, 'failed': failed, 'items': items}
    save_json(args.out / 'summary.json', summary)
    return 0 if failed == 0 else 1

def cmd_batch(args):
    fresh_out(args.out, getattr(args, 'resume_out', False))
    manifest = read_json(args.manifest)
    items = manifest.get('items') or []
    if not items:
        raise ValueError('Batch manifest requires items')
    results = []
    for index, item in enumerate(items):
        item_out = args.out / f"item-{index+1:04d}-{item.get('series_id','series')}"
        argv = ['history', '--tenant-id', manifest.get('tenant_id') or args.tenant_id or '', '--series-id', item['series_id'], '--input', item['input'], '--out', str(item_out)]
        if item.get('weather_region'): argv += ['--weather-region', item['weather_region']]
        if item.get('melo_id'): argv += ['--melo-id', item['melo_id']]
        if item.get('obis'): argv += ['--obis', item['obis']]
        rc = main([x for x in argv if x != ''])
        results.append({'index': index, 'series_id': item.get('series_id'), 'status': 'ok' if rc == 0 else 'failed', 'exit_code': rc, 'out': str(item_out)})
        if rc != 0 and not args.continue_on_error:
            break
    summary = {'status': 'ok' if all(r['exit_code'] == 0 for r in results) else 'failed', 'items': results}
    save_json(args.out / 'batch_summary.json', summary)
    (args.out / 'batch_summary.md').write_text('# Batch summary\n\n' + '\n'.join(f"- {r['status']} {r['series_id']} → {r['out']}" for r in results) + '\n', encoding='utf-8')
    if summary['status'] != 'ok':
        raise ValueError('Batch failed for at least one item')


def cmd_describe(args):
    payload = {'name': 'cernion-forecast-cli', 'version': CLI_VERSION, 'schema_version': ARTIFACT_SCHEMA,
               'commands': ['day-ahead', 'history', 'enroll', 'train', 'predict', 'resume', 'score', 'acceptance-test', 'e2e', 'doctor', 'batch', 'describe'],
               'exit_codes': {'0': 'success', '1': 'validation/runtime error', '2': 'command line usage error', '10': 'idempotent skip', '50': 'quality/acceptance threshold failed'},
               'input_formats': ['json', 'csv', 'mscons', 'edi', 'edifact'], 'output_artifacts': ['run.json', 'result.json', 'quality_report.json', 'metrics.json', 'residuals.csv', 'acceptance_report.json', 'e2e-summary.json', 'quality_gate.json']}
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def add_common(sub, token=True):
    sub.add_argument('--base-url', default=os.environ.get('CET_API_BASE_URL', 'https://api.cernion.de'))
    sub.add_argument('--timeout', type=float, default=120)
    sub.add_argument('--config', type=Path)
    sub.add_argument('--profile')
    sub.add_argument('--log-format', choices=['text', 'json'], default='text')
    sub.add_argument('--log-file', type=Path)
    sub.add_argument('--verbose', action='store_true')
    sub.add_argument('--quiet', action='store_true')
    sub.add_argument('--resume-out', action='store_true')
    sub.add_argument('--debug-http', action='store_true', help='Log sanitized request/response metadata for HTTP diagnostics')
    if token:
        sub.add_argument('--token-file', type=Path)
        sub.add_argument('--poll-interval', type=float, default=5)
        sub.add_argument('--job-timeout', type=float, default=86400)
        sub.add_argument('--dry-run', action='store_true')
        sub.add_argument('--tenant-id')
    sub.add_argument('--out', type=Path, required=True)


def add_output_args(sub):
    sub.add_argument('--output-format', default='json', help='Comma-separated: json,csv')
    sub.add_argument('--stdout-json', action='store_true')


def add_quality_args(sub):
    sub.add_argument('--quality-policy', choices=['strict', 'warn', 'lenient'], default='lenient')
    sub.add_argument('--min-coverage', type=float, default=0.0)
    sub.add_argument('--expected-intervals', default='auto')
    sub.add_argument('--allow-gaps', action='store_true')
    sub.add_argument('--allow-negative', action='store_true')


def add_mscons_select_args(sub):
    sub.add_argument('--melo-id')
    sub.add_argument('--obis')
    sub.add_argument('--cci-code')
    sub.add_argument('--message-ref')
    sub.add_argument('--document-number')
    sub.add_argument('--mscons-timezone')


def add_context_args(sub):
    sub.add_argument('--location')
    sub.add_argument('--weather-region', dest='weather_region')
    sub.add_argument('--weather-dataset-id')
    sub.add_argument('--context-dataset-id')
    sub.add_argument('--postal-code', dest='postal_code')
    sub.add_argument('--municipality')
    sub.add_argument('--country', default=None)
    sub.add_argument('--latitude', type=float)
    sub.add_argument('--longitude', type=float)


def build_parser():
    p = argparse.ArgumentParser(description='CLI for Cernion Energy Tools Lastgang-/load-profile forecasts')
    p.add_argument('--version', action='version', version=f'cernion-forecast {CLI_VERSION}')
    sub = p.add_subparsers(dest='command', required=True)

    day = sub.add_parser('day-ahead')
    add_common(day, token=False); add_output_args(day)
    day.add_argument('--series-id', required=True); day.add_argument('--forecast-for', type=dt.date.fromisoformat, required=True)
    day.add_argument('--history', type=Path, required=True); day.add_argument('--timezone', default='Europe/Berlin'); day.add_argument('--unit', choices=['kWh', 'kW'], default='kWh'); day.add_argument('--confidence-band', action='store_true')
    add_context_args(day); day.set_defaults(func=cmd_day_ahead)

    for name in ('history', 'enroll'):
        sp = sub.add_parser(name); add_common(sp); add_output_args(sp); add_quality_args(sp); add_mscons_select_args(sp); add_context_args(sp)
        sp.add_argument('--input', type=Path, required=True); sp.add_argument('--series-id'); sp.add_argument('--unit', choices=['kWh', 'kW']); sp.add_argument('--timezone')
        sp.add_argument('--allow-corrections', action='store_true'); sp.add_argument('--historical-import', action='store_true'); sp.add_argument('--import-mode', choices=['append-only', 'correction', 'replace-period'], default='append-only')
        sp.add_argument('--processed-ledger', type=Path); sp.add_argument('--idempotency-key'); sp.add_argument('--skip-if-processed', action='store_true')
        if name == 'enroll':
            sp.add_argument('--forecast-for', type=dt.date.fromisoformat, required=True); sp.set_defaults(func=lambda args: cmd_history_like(args, train_after=True))
        else:
            sp.set_defaults(func=lambda args: cmd_history_like(args, train_after=False))

    train = sub.add_parser('train'); add_common(train); add_output_args(train); add_context_args(train)
    train.add_argument('--series-ids', nargs='+', required=True); train.add_argument('--forecast-for', type=dt.date.fromisoformat, required=True); train.add_argument('--strategy', default='shared_baseline'); train.set_defaults(func=cmd_train)

    pred = sub.add_parser('predict'); add_common(pred); add_output_args(pred); add_context_args(pred)
    pred.add_argument('--series-id', required=True); pred.add_argument('--forecast-for', type=dt.date.fromisoformat, required=True)
    g = pred.add_mutually_exclusive_group(required=True); g.add_argument('--model-version'); g.add_argument('--model-file', type=Path)
    pred.add_argument('--history-version'); pred.add_argument('--allow-stale-model', action='store_true'); pred.add_argument('--provenance-level', choices=['full', 'pseudonymized'], default='full'); pred.set_defaults(func=cmd_predict)

    resume = sub.add_parser('resume'); add_common(resume); add_output_args(resume)
    resume.add_argument('--run-file', type=Path, required=True); resume.add_argument('--restart', action='store_true'); resume.set_defaults(func=cmd_resume)

    score = sub.add_parser('score'); add_common(score, token=False); add_quality_args(score); add_mscons_select_args(score)
    score.add_argument('--tenant-id'); score.add_argument('--series-id', required=True); score.add_argument('--predictions', nargs='+', type=Path, required=True); score.add_argument('--actuals', type=Path, required=True)
    score.add_argument('--unit', choices=['kWh', 'kW']); score.add_argument('--timezone'); score.add_argument('--allow-partial', action='store_true')
    score.add_argument('--max-wape', type=float); score.add_argument('--fail-if-wape-above', type=float); score.add_argument('--max-mae', type=float); score.add_argument('--min-score-coverage', type=float); score.set_defaults(func=cmd_score)

    accept = sub.add_parser('acceptance-test'); add_common(accept, token=False); add_quality_args(accept); add_mscons_select_args(accept)
    accept.add_argument('--tenant-id'); accept.add_argument('--series-id', required=True); accept.add_argument('--predictions', nargs='+', type=Path, required=True); accept.add_argument('--actuals', type=Path, required=True); accept.add_argument('--history', type=Path, required=True)
    accept.add_argument('--unit', choices=['kWh', 'kW']); accept.add_argument('--timezone'); accept.add_argument('--acceptance-profile', choices=['monitoring', 'portfolio', 'system-load', 'household', 'industrial', 'volatile', 'strict'], default='portfolio')
    accept.add_argument('--benchmarks', nargs='+', choices=['persistence', 'weekly_naive', 'previous-day', 'previous-week', 'rolling-mean'], default=['persistence', 'weekly_naive'])
    accept.add_argument('--require-better-than', nargs='+', choices=['persistence', 'weekly_naive', 'previous-day', 'previous-week', 'rolling-mean']); accept.add_argument('--min-relative-improvement', type=float, default=0.0)
    accept.add_argument('--max-wape', type=float); accept.add_argument('--max-bias', type=float); accept.add_argument('--min-score-coverage', type=float); accept.set_defaults(func=cmd_acceptance_test)

    e2e = sub.add_parser('e2e'); add_common(e2e); add_quality_args(e2e); add_mscons_select_args(e2e); add_context_args(e2e)
    e2e.add_argument('--series-id', required=True); e2e.add_argument('--history', type=Path, required=True); e2e.add_argument('--actuals', type=Path, required=True)
    e2e.add_argument('--forecast-for', type=dt.date.fromisoformat, required=True); e2e.add_argument('--unit', choices=['kWh', 'kW']); e2e.add_argument('--timezone')
    e2e.add_argument('--min-observed-history-days', '--min-history-days-before-d2', dest='min_history_days_before_d2', type=int, default=28)
    e2e.add_argument('--strategy', default='shared_baseline'); e2e.add_argument('--allow-stale-model', action='store_true')
    e2e.add_argument('--quality-profile', choices=['monitoring', 'portfolio', 'system-load', 'household', 'industrial', 'volatile', 'strict'], default='portfolio')
    e2e.add_argument('--baselines', default='previous-day,previous-week,rolling-mean')
    e2e.add_argument('--max-wape', type=float); e2e.add_argument('--min-score-coverage', type=float); e2e.add_argument('--baseline-tolerance', type=float, default=0.0); e2e.add_argument('--no-baseline-gate', action='store_true')
    e2e.set_defaults(func=cmd_e2e)

    bh = sub.add_parser('batch-history'); add_common(bh); add_quality_args(bh); add_context_args(bh); add_mscons_select_args(bh)
    bh.add_argument('--input-dir', type=Path, required=True); bh.add_argument('--glob', default='*'); bh.add_argument('--series-id-field', default='series_id'); bh.set_defaults(func=cmd_batch_history)
    doctor = sub.add_parser('doctor'); add_common(doctor); doctor.set_defaults(func=cmd_doctor)
    batch = sub.add_parser('batch'); add_common(batch); batch.add_argument('--manifest', type=Path, required=True); batch.add_argument('--continue-on-error', action='store_true'); batch.set_defaults(func=cmd_batch)
    describe = sub.add_parser('describe'); describe.set_defaults(func=cmd_describe)
    return p


def apply_config(args):
    cfg_path = getattr(args, 'config', None)
    if not cfg_path:
        return args
    cfg = read_json(cfg_path)
    if getattr(args, 'profile', None):
        cfg = {**cfg, **((cfg.get('profiles') or {}).get(args.profile) or {})}
    for key, value in cfg.items():
        if key == 'profiles':
            continue
        attr = key.replace('-', '_')
        if hasattr(args, attr):
            current = getattr(args, attr)
            if isinstance(value, bool):
                setattr(args, attr, value)
            elif current in (None, False) or (attr == 'base_url' and current == 'https://api.cernion.de'):
                setattr(args, attr, value)
    return args


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args = apply_config(args)
    configure_logging(args)
    try:
        ret = args.func(args)
        return ret if isinstance(ret, int) else 0
    except (ValueError, KeyError, OSError, ConnectionError, json.JSONDecodeError) as error:
        message = str(error)
        try:
            secret = token_from(args)
            if secret:
                message = message.replace(secret, '[REDACTED]')
        except Exception:
            pass
        print('ERROR: ' + message, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
