"""Pinned community facts for broad exploration, separate from reviewed rules."""

from datetime import date
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from gradmatch.storage import PROJECT_ROOT


COMMUNITY_FILE = PROJECT_ROOT / 'data/community/csgrad_tracker_v1.json'
TESTS = {'toefl_old': ('toefl_120', 'TOEFL /120'), 'toefl_new': ('toefl_6', 'TOEFL /6'),
         'ielts': ('ielts_9', 'IELTS'), 'duolingo': ('det_160', 'DET')}
KINDS = {'hard_min': 'Reported minimum', 'recommended': 'Recommended',
         'typical_range': 'Typical score', 'subscores_only': 'Subscores only',
         'not_accepted': 'Not accepted', 'not_stated': 'Not stated', 'none': 'No requirement reported'}


def public_url(value):
    parsed = urlsplit(value)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Invalid public URL in community input.')
    return value


def english_cell(value):
    """Translate short score-cell notation; retain the original separately."""
    for old, new in [('另有小分', 'additional subscores'), ('小分', 'subscores'),
                     ('口语', 'speaking'), ('听力', 'listening'), ('写作', 'writing'),
                     ('阅读', 'reading'), ('读写', 'literacy'), ('理解', 'comprehension'), ('产出', 'production'),
                     ('会话', 'conversation'), ('各项', 'each subscore'), ('每项', 'each subscore'),
                     ('其余', 'other subscores'), ('不接受', 'Not accepted'), ('无', 'None reported')]:
        value = value.replace(old, new)
    if re.search(r'[\u3400-\u9fff]', value):
        raise ValueError('A new score-cell translation needs review.')
    return value


def compile_community(raw, index):
    """Batch import already-downloaded public tracker facts from the pinned file."""
    if hashlib.sha256(raw).hexdigest() != index['source_sha256']:
        raise ValueError('The tracker file does not match the pinned source hash.')
    source = json.loads(raw)
    if source['cycle'] != index['intake'] or source['generated'] != index['upstream_generated']:
        raise ValueError('Community source period differs from the identity index.')
    identities = {r['source_id']: r for r in index['rows']}
    if len(source['rows']) != len(identities) or len({r['id'] for r in source['rows']}) != len(identities):
        raise ValueError('Community source identity count differs from the index.')
    rows = []
    for item in source['rows']:
        identity = identities[item['id']]
        if item['site'] != identity['program_url'] or item['official'] != identity['reported_program_name']:
            raise ValueError('Community identity scope differs from the pinned index.')
        language = []
        for test, (version, label) in TESTS.items():
            cell = item['lang'][test]
            kind, raw_cell = cell['kind'], cell['cell']
            summary = english_cell(source['en'].get(raw_cell, raw_cell))
            match = re.fullmatch(r'(\d+(?:\.\d+)?)(?:\((.*)\))?', summary)
            language.append(dict(test=version, test_label=label, kind=kind,
                summary=f'{KINDS[kind]}: {summary}', original_value=raw_cell,
                reported_total=match[1] if match and kind == 'hard_min' else None,
                conditions_pending=bool(match and match[2])))
        rounds = []
        for entry in item['rounds']:
            label = source['en'].get(entry['label'], entry['label'])
            if re.search(r'[\u3400-\u9fff]', label):
                raise ValueError('An application-round label needs an English translation.')
            date.fromisoformat(entry['date'])
            rounds.append(dict(date=entry['date'], label=label))
        fee = item.get('fee')
        if fee is not None and (not isinstance(fee, (int, float)) or fee < 0):
            raise ValueError('Unexpected application fee value.')
        rows.append(dict(source_id=item['id'], program_url=public_url(item['site']),
            application_url=public_url(item['apply']), reported_gre=item['gre'],
            language=language, rounds=rounds, application_fee=fee, fee_currency=None,
            verification_status='community_unverified'))
    return dict(schema_version='community-tracker-v1', source_url=index['source_url'],
        source_commit=index['source_commit'], source_sha256=index['source_sha256'],
        upstream_generated=source['generated'], intake=source['cycle'],
        attribution={**index['attribution'], 'changes': 'Identity leads plus reported language, GRE, application rounds, application fees and public application URLs. English score notation and round labels normalized; no admission datapoints or source ranking labels included.'},
        rows=rows)


def load_community(index, path=COMMUNITY_FILE):
    document = json.loads(Path(path).read_text(encoding='utf-8'))
    for key in ['source_url', 'source_commit', 'source_sha256', 'upstream_generated', 'intake']:
        if document[key] != index[key]:
            raise ValueError('Community facts and identity index have different provenance.')
    rows = document['rows']
    if document['schema_version'] != 'community-tracker-v1' or len(rows) != index['expected_rows']:
        raise ValueError('Unexpected community facts version or count.')
    by_id = {r['source_id']: r for r in rows}
    if len(by_id) != len(rows) or set(by_id) != {r['source_id'] for r in index['rows']}:
        raise ValueError('Community facts contain a missing, duplicate or unknown identity.')
    for row in rows:
        public_url(row['application_url'])
        if row['verification_status'] != 'community_unverified':
            raise ValueError('Reported facts must retain their community status.')
    return document


def reported_language_label(facts):
    return '; '.join(f"{r['test_label']} {r['summary']}" for r in facts['language'])


def reported_rounds_label(facts):
    return '; '.join(f"{r['date']}: {r['label']}" for r in facts['rounds']) or 'No round listed; verify availability'


def application_fee_label(facts):
    fee = facts['application_fee']
    return f'{fee:g} (currency unverified; application fee only)' if fee is not None else 'Not stated'


def exploration_rows(document, profile, programs, sources, *, as_of):
    """Annotate a broad candidate pool; never emit formal recommendations or tiers."""
    from gradmatch.constraints import check_constraints
    from gradmatch.directory import tuition_label

    by_program = {p.program_id: p for p in programs}
    result = []
    for row in document['records']:
        facts = row['community_facts']
        cycle_matches = bool(profile.intake and f'{profile.intake.term.title()} {profile.intake.year}' == document['source_intake'])
        english_note = 'English comparison pending'
        concern = False
        program = by_program.get(row['linked_program_id'])
        reviewed = None
        if program:
            reviewed = check_constraints(profile, program, sources, as_of=as_of)
            check = next(c for c in reviewed.checks if c.rule_id == 'english')
            english_note = f'Reviewed English check: {check.status.value}; {check.reason_code}'
            concern = any(c.status.value == 'fail' for c in reviewed.checks)
        elif cycle_matches and profile.english:
            rule = next(r for r in facts['language'] if r['test'] == profile.english.version)
            if rule['kind'] == 'not_accepted':
                english_note = 'Tracker reports this test is not accepted; confirm alternatives'
                concern = True
            elif rule['reported_total'] is not None:
                below = profile.english.total < Decimal(rule['reported_total'])
                english_note = ('Below reported overall minimum' if below else 'At/above reported overall minimum') + '; subscores, test age and conditions still need review'
                concern = below
            else:
                english_note = rule['summary'] + '; no overall-minimum decision'
        if not cycle_matches and not program:
            english_note = 'Tracker is for Fall 2027; selected intake needs review'
        scope = row['source_reports_halted'] or 'source_mentions_doctoral_admission' in row['review_flags']
        status = 'Availability / degree-route review' if scope else 'Review reported concerns' if concern else 'Explore'
        result.append(dict(source_id=row['source_id'], university=row['university'], program=row['program_name'],
            status=status, english_note=english_note,
            gre_note=(row['requirements']['GRE policy'] if row['field_coverage'].get('gre', {}).get('rule_usable') else facts['reported_gre'].replace('_', ' ') + ' (community)'),
            tuition=tuition_label(row), listed_rounds=reported_rounds_label(facts),
            application_url=facts['application_url'], verification_status='preliminary_exploration',
            personalized_tier=None, recommendation_eligible=False))
    return result
