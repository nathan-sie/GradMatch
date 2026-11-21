"""Twenty-record coverage, minimum-only costs and official policy boundaries."""

from datetime import date
from dataclasses import asdict
from decimal import Decimal
import json

import pytest

from gradmatch.catalog import M61E_SEED, M61F_SEED, load_seed as current_load_seed
from gradmatch.constraints import check_constraints
from gradmatch.directory import build_directory, comparison_rows, tuition_label
from gradmatch.schemas import GPA
from gradmatch.session import Session, tiering_profile
from gradmatch.storage import PROJECT_ROOT


def load_seed(path=M61F_SEED):
    return current_load_seed(path)


def assess(pid, profile=None, programs=None, sources=None):
    if programs is None:
        programs, sources = load_seed()
    program = next(p for p in programs if p.program_id == pid)
    report = check_constraints(profile or tiering_profile(), program, sources, as_of=date(2026,11,20))
    return report, {c.rule_id:c for c in report.checks}


def test_twenty_identities_preserve_every_prior_source_and_all_83_leads():
    programs, sources = load_seed()
    _, prior = load_seed(M61E_SEED)
    assert len(programs) == 20 and len(sources) == 94
    assert all(sources[sid] == source for sid,source in prior.items())
    review = json.loads((PROJECT_ROOT/'data/review/m61f_field_reviews.json').read_text(encoding='utf-8'))
    assert len(review['new_programs']) == 4 and len(review['repaired_programs']) == 2
    assert set(review['new_source_ids']) == set(sources)-set(prior)
    directory = build_directory(programs,sources)
    assert directory['total'] == 83 and directory['official_records'] == 20
    assert sum(bool(r['source_reports_halted']) for r in directory['records']) == 4
    assert all(not r['recommendation_eligible'] for r in directory['records'])


@pytest.mark.parametrize('budget,status', [(100000,'fail'),(104820,'unknown'),(140000,'unknown')])
def test_duke_minimum_can_exclude_but_cannot_establish_affordability(budget,status):
    profile = tiering_profile()
    profile.tuition_budget_usd = Decimal(budget)
    report, checks = assess('duke-ms-ece-durham',profile)
    assert report.tuition.lower_usd == Decimal('104820') and report.tuition.upper_usd is None
    assert checks['tuition'].status == status and len(checks['tuition'].source_ids) == 2
    assert not report.recommendation_ready
    profile.budget_basis = 'guaranteed_final'
    _, guaranteed = assess('duke-ms-ece-durham',profile)
    assert guaranteed['tuition'].status == 'unknown'


@pytest.mark.parametrize('tamper', ['missing_source','changed_rate','wrong_program','missing_numeric_binding'])
def test_minimum_requires_matching_official_numeric_evidence(tamper):
    programs,sources = load_seed()
    duke = next(p for p in programs if p.program_id == 'duke-ms-ece-durham')
    sid = duke.field_sources['tuition_minimum'][-1]
    if tamper == 'missing_source':
        sources.pop(sid)
    elif tamper == 'changed_rate':
        duke.tuition.unit_rate_lower = Decimal('1')
    elif tamper == 'wrong_program':
        sources[sid].program_id = 'cmu-ms-ece-pittsburgh'
    else:
        sources[sid].verified_values['tuition_minimum'].pop('tuition.unit_rate_lower')
    report,checks = assess(duke.program_id,programs=programs,sources=sources)
    assert report.tuition.lower_usd is None and checks['tuition'].status == 'unknown'


def test_credit_systems_and_ongoing_program_gpa_are_not_admission_rules():
    directory = build_directory(*load_seed())
    rows = {r['linked_program_id']:r for r in directory['records'] if r['linked_program_id']}
    compared = comparison_rows([rows[pid] for pid in ['cmu-ms-ece-pittsburgh','ucsd-ms-cs-la-jolla','gatech-mscs-atlanta']])
    credits = next(r for r in compared if r['Field'] == 'Credits')
    assert any('97' in str(v) and 'CMU' in str(v) for v in credits.values())
    assert any('40' in str(v) and 'quarter' in str(v) for v in credits.values())
    assert any('30' in str(v) and 'semester' in str(v) for v in credits.values())
    duke = rows['duke-ms-ece-durham']
    assert '104,820' in tuition_label(duke) and 'upper bound unverified' in tuition_label(duke)
    assert duke['tuition_upper_usd'] is None
    _, checks = assess('duke-ms-ece-durham')
    assert checks['gpa'].status == 'unknown'


def test_gatech_recommended_gpa_stays_unknown_and_ucsd_cycle_is_bounded():
    profile=tiering_profile()
    profile.gpa=GPA(value='2.9',scale='4')
    _,gt=assess('gatech-mscs-atlanta',profile)
    assert gt['gpa'].status == 'unknown' and gt['gpa'].reason_code == 'RECOMMENDATION_NOT_HARD_MINIMUM'
    assert gt['gre'].status == 'not_applicable'
    _,ucsd=assess('ucsd-ms-cs-la-jolla',profile)
    assert ucsd['deadline'].status == 'pass' and ucsd['gre'].status == 'not_applicable'
    profile.intake.year=2028
    _,future=assess('ucsd-ms-cs-la-jolla',profile)
    assert future['deadline'].status == future['gre'].status == 'unknown'


def test_uw_completed_review_still_requires_matching_gpa_scope_and_budget():
    profile=tiering_profile()
    _,old=assess('uw-ece-msece-pmp-seattle',profile)
    assert old['gpa'].status == 'unknown'
    profile.gpa=GPA(value='3.5',scale='4',scope='last_60_semester')
    report,checks=assess('uw-ece-msece-pmp-seattle',profile)
    assert report.recommendation_ready and checks['remaining_eligibility'].status == 'pass'
    profile.tuition_budget_usd=Decimal('50000')
    report,checks=assess('uw-ece-msece-pmp-seattle',profile)
    assert checks['tuition'].status == 'fail' and not report.recommendation_ready


@pytest.mark.parametrize('gpa,scale,status', [('3','4','pass'),('2.9','4','fail'),('85','100','unknown')])
def test_uci_cumulative_undergraduate_gpa_is_comparable_without_conversion(gpa,scale,status):
    profile=tiering_profile()
    profile.gpa=GPA(value=gpa,scale=scale,scope='overall')
    report,checks=assess('uci-mcs-irvine',profile)
    assert checks['gpa'].status == status and checks['gpa'].source_ids
    assert checks['remaining_eligibility'].status == 'unknown' and not report.recommendation_ready


def test_hot_refresh_rebinds_cached_constraint_helpers_without_resetting_sessions(monkeypatch):
    import gradmatch.constraints as constraints
    import gradmatch.service as service
    import gradmatch.agent as agent
    import gradmatch.validation as validation
    import gradmatch.release as release
    session=Session(profile=tiering_profile())
    session.messages.append({'role':'user','content':'Keep my profile'})
    original=asdict(session)
    previous=constraints.check_constraints
    monkeypatch.setattr(release,'_signature',None)
    release.refresh_catalog_modules()
    assert constraints.check_constraints is not previous
    for module in [service,agent,validation]:
        if hasattr(module,'check_constraints'):
            assert module.check_constraints is constraints.check_constraints
    assert asdict(session) == original
