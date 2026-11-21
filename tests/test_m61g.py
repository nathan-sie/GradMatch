"""Existing-record repairs and score floors that never establish English eligibility."""
from datetime import date
from decimal import Decimal
import hashlib
import json

import pytest

from gradmatch.catalog import M61F_SEED, M61G_SEED, load_seed as current_load_seed
from gradmatch.constraints import check_constraints
from gradmatch.directory import build_directory, comparison_rows
from gradmatch.schemas import EnglishScore
from gradmatch.session import tiering_profile
from gradmatch.storage import PROJECT_ROOT


def load_seed(path=M61G_SEED):
    return current_load_seed(path)


def assess(pid,profile=None,programs=None,sources=None,as_of=date(2026,11,20)):
    if programs is None:
        programs,sources=load_seed()
    report=check_constraints(profile or tiering_profile(),next(p for p in programs if p.program_id==pid),sources,as_of=as_of)
    return report,{c.rule_id:c for c in report.checks}


def test_twelve_repairs_preserve_all_prior_source_objects_and_exact_identities():
    programs,sources=load_seed();prior,old_sources=load_seed(M61F_SEED)
    assert len(programs)==20 and len(sources)==112
    assert {p.program_id for p in programs}=={p.program_id for p in prior}
    assert all(sources[sid]==source for sid,source in old_sources.items())
    reviews=json.loads((PROJECT_ROOT/'data/review/m61g_field_reviews.json').read_text(encoding='utf-8'))
    receipts=json.loads((PROJECT_ROOT/'data/review/m61g_capture_receipts.json').read_text(encoding='utf-8'))
    assert len(reviews['programs_enriched'])==12
    assert set(reviews['new_source_ids'])==set(sources)-set(old_sources)
    for sid in reviews['new_source_ids']:
        source=sources[sid]
        receipt=next(r for r in receipts['captures'] if r.get('raw_response_sha256')==source.raw_response_sha256 and r.get('url')==str(source.url))
        assert receipt['status']=='captured' and receipt['http_status']==200
        suffix='.pdf' if 'pdf' in receipt['content_type'] else '.html'
        raw=PROJECT_ROOT/'work/m61g_research'/(receipt['key']+suffix)
        if raw.exists():
            assert hashlib.sha256(raw.read_bytes()).hexdigest()==source.raw_response_sha256


@pytest.mark.parametrize('pid',[
    'cmu-ms-ece-pittsburgh','ucsd-ms-cs-la-jolla','gatech-mscs-atlanta','cornell-meng-cs-ithaca',
    'wisc-ms-cs-professional-madison','umass-mscs-amherst','uiuc-mcs-urbana','uiuc-meng-ece-urbana',
])
def test_known_english_floor_flags_low_scores_but_high_scores_stay_unknown(pid):
    profile=tiering_profile()
    profile.english=EnglishScore(version='ielts_9',total='9',test_date=date(2026,10,1),
        subscores=dict.fromkeys(['reading','listening','speaking','writing'],'9'))
    report,high=assess(pid,profile)
    assert high['english'].status=='unknown' and high['english'].reason_code=='ENGLISH_MINIMUM_ONLY'
    assert high['english'].source_ids and not report.recommendation_ready
    profile.english.total=Decimal('5')
    _,low=assess(pid,profile)
    assert low['english'].status=='fail' and low['english'].reason_code=='ENGLISH_TOTAL_BELOW_MINIMUM'
    assert low['english'].source_ids==high['english'].source_ids


def test_gatech_subscores_and_source_pair_cannot_be_bypassed():
    programs,sources=load_seed();p=next(p for p in programs if p.program_id=='gatech-mscs-atlanta')
    profile=tiering_profile()
    profile.english.subscores={'reading':'30','listening':'30','speaking':'18','writing':'30'}
    _,checks=assess(p.program_id,profile,programs,sources)
    assert checks['english'].reason_code=='ENGLISH_SUBSCORE_BELOW_MINIMUM'
    sources.pop(p.field_sources['english_minimum'][-1])
    _,checks=assess(p.program_id,profile,programs,sources)
    assert checks['english'].status=='unknown' and not checks['english'].source_ids


def test_changed_score_floor_or_future_cycle_loses_support():
    programs,sources=load_seed();p=next(p for p in programs if p.program_id=='cmu-ms-ece-pittsburgh')
    profile=tiering_profile();profile.english.total=Decimal('50')
    p.english[0].minimum_total=Decimal('60')
    _,checks=assess(p.program_id,profile,programs,sources)
    assert checks['english'].status=='unknown' and not checks['english'].source_ids
    profile.intake.year=2028
    _,future=assess('gatech-mscs-atlanta',profile)
    assert future['english'].status=='unknown'


def test_cornell_professional_subscores_do_not_borrow_research_ta_thresholds():
    profile=tiering_profile()
    profile.english=EnglishScore(version='toefl_120',total='100',test_date=date(2025,11,1),
        subscores={'reading':'25','listening':'25','speaking':'22','writing':'28'})
    _,checks=assess('cornell-meng-cs-ithaca',profile)
    assert checks['english'].reason_code=='ENGLISH_MINIMUM_ONLY'
    profile.english.subscores['speaking']=Decimal('21')
    _,checks=assess('cornell-meng-cs-ithaca',profile)
    assert checks['english'].reason_code=='ENGLISH_SUBSCORE_BELOW_MINIMUM'


@pytest.mark.parametrize('budget,status',[(60000,'fail'),(63500,'pass'),(70000,'pass')])
def test_uci_uses_five_quarter_instructional_fee_not_annual_or_all_fees(budget,status):
    profile=tiering_profile();profile.tuition_budget_usd=Decimal(budget)
    report,checks=assess('uci-mcs-irvine',profile)
    assert report.tuition.upper_usd==Decimal('63500') and report.tuition.mandatory_fees_usd is None
    assert checks['tuition'].status==status and not report.recommendation_ready
    profile.budget_basis='guaranteed_final'
    _,checks=assess('uci-mcs-irvine',profile)
    assert checks['tuition'].status=='unknown'


def test_no_cutoff_gpa_and_new_degrees_do_not_create_admission_tiers():
    for pid in ['duke-ms-ece-durham','cmu-ms-ece-pittsburgh']:
        _,checks=assess(pid)
        assert checks['gpa'].status=='not_applicable' and checks['gre'].status=='not_applicable'
    for pid in ['ucsd-ms-cs-la-jolla','umass-mscs-amherst']:
        report,checks=assess(pid)
        assert checks['degree'].status=='pass' and not report.recommendation_ready
    _,duke=assess('duke-ms-ece-durham',as_of=date(2027,2,1))
    assert duke['deadline'].status=='pass' and 'places' in duke['deadline'].explanation


def test_directory_exposes_partial_english_and_keeps_unverified_costs_unknown():
    document=build_directory(*load_seed());rows={r['linked_program_id']:r for r in document['records'] if r['linked_program_id']}
    assert document['total']==83 and document['official_records']==20
    assert sum(r['tuition_upper_usd'] is not None for r in rows.values())==8
    assert sum(r['field_coverage']['english_minimum']['rule_usable'] for r in rows.values())==8
    assert sum(r['field_coverage']['english']['rule_usable'] for r in rows.values())==5
    assert rows['rice-mcs-houston']['tuition_upper_usd'] is None
    assert all('English score floor only' not in row['missing_fields'] for row in document['records'])
    assert 'The GPA exception-policy page could not be retrieved' not in ' '.join(rows['uci-mcs-irvine']['notes'])
    assert '30,720' in rows['rice-mcs-houston']['requirements']['Cost context']
    assert 'generally' in rows['duke-ms-ece-durham']['requirements']['English policy'].lower()
    comparison=comparison_rows([rows['gatech-mscs-atlanta'],rows['uci-mcs-irvine']])
    assert any(r['Field']=='English score floor only' for r in comparison)
    assert 'confir' in rows['cmu-mcds-pittsburgh']['requirements']['English validity']
    assert all(not r['recommendation_eligible'] for r in document['records'])
