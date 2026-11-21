"""Verify conservative pricing ceilings and all retained source objects offline."""
import argparse
from dataclasses import replace
from datetime import date
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import socket
from unittest.mock import patch
from uuid import uuid4

from gradmatch.bootstrap import bootstrap_public_catalog
from gradmatch.catalog import M61H_SEED, load_seed, read_catalog
from gradmatch.catalog_audit import markdown_report
from gradmatch.config import load_settings
from gradmatch.constraints import check_constraints
from gradmatch.directory import bootstrap_directory, read_directory, tuition_label
from gradmatch.providers import OpenAIProvider
from gradmatch.service import start_task
from gradmatch.session import Session, tiering_profile
from gradmatch.storage import DEFAULT_DATABASE, PROJECT_ROOT
from gradmatch.validation import data_hash
from scripts.audit_catalog import build_report
from scripts.m5_fixtures import FixtureProvider

CEILINGS={'wisc-ms-cs-professional-madison':'45102.00','uiuc-meng-ece-urbana':'60666',
          'cmu-ms-ece-pittsburgh':'92265','ncsu-mcs-raleigh':'67983'}

def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path)
    args=parser.parse_args()
    output=args.output_dir or PROJECT_ROOT/'work/m61i'/str(uuid4())
    output.mkdir(parents=True,exist_ok=False)
    originals=[p for p in [DEFAULT_DATABASE,PROJECT_ROOT/'work/csgrad_candidates.db'] if p.exists()]
    before={p.name:sha256(p) for p in originals}
    def deny(*args,**kwargs):raise AssertionError('No external or paid request in snapshot verification')
    with (patch.object(socket,'getaddrinfo',deny),patch.object(socket,'create_connection',deny),
          patch.object(socket.socket,'connect',deny),patch.object(OpenAIProvider,'generate',deny)):
        programs,sources=load_seed();_,prior=load_seed(M61H_SEED)
        review=json.loads((PROJECT_ROOT/'data/review/m61i_field_reviews.json').read_text(encoding='utf-8'))
        receipts=json.loads((PROJECT_ROOT/'data/review/m61i_capture_receipts.json').read_text(encoding='utf-8'))
        assert len(programs)==20 and len(sources)==138 and len(review['programs_enriched'])==7
        assert all(sources[k]==v for k,v in prior.items())
        used=set();checked=0
        for sid in review['new_source_ids']:
            source=sources[sid]
            receipt=next(r for r in receipts['captures'] if r.get('url')==str(source.url) and r.get('raw_response_sha256')==source.raw_response_sha256)
            assert receipt['status']=='captured' and receipt['http_status']==200
            used.add(receipt['key'])
            for extension in ['.html','.pdf']:
                raw=PROJECT_ROOT/'work/m61i_research'/(receipt['key']+extension)
                if raw.exists():assert sha256(raw)==source.raw_response_sha256;checked+=1;break
        database=bootstrap_public_catalog(output/'public')
        assert data_hash(*read_catalog(database))==data_hash(programs,sources)
        directory=read_directory(bootstrap_directory(database,output/'public'))
        assert directory['total']==83 and directory['official_records']==20
        assert sum(r['source_reports_halted'] for r in directory['records'])==4
        price_checks={}
        for pid,amount in CEILINGS.items():
            program=next(p for p in programs if p.program_id==pid)
            row=next(r for r in directory['records'] if r['linked_program_id']==pid)
            assert 'ceiling' in tuition_label(row) and row['tuition_lower_usd'] is None
            outcomes=[]
            for budget in [Decimal(amount),Decimal(amount)-Decimal('.01')]:
                profile=tiering_profile();profile.tuition_budget_usd=budget
                report=check_constraints(profile,program,sources,as_of=date(2026,11,21))
                result=next(c for c in report.checks if c.rule_id=='tuition')
                assert report.tuition.lower_usd is None and report.tuition.upper_usd==Decimal(amount)
                assert result.status==('pass' if budget==Decimal(amount) else 'unknown')
                outcomes.append(dict(budget_usd=str(budget),status=result.status,reason_code=result.reason_code))
            price_checks[pid]=dict(published_rate_ceiling_usd=amount,boundary_checks=outcomes)
        audit=build_report(as_of=date(2026,11,21));summary=audit['catalog']['summary']
        assert summary['computable_verified_tuition']==12
        assert summary['two_sided_tuition_estimates']==8 and summary['maximum_only_tuition']==4
        assert summary['minimum_only_tuition']==1 and summary['full_eligibility_reviews']==5
        assert summary['reference_hard_checks_ready']==2 and summary['reference_formal_evidence_ready']==1
        assert summary['fields']['prerequisites']['usable']==9 and summary['fields']['degree']['usable']==16
        strategies={}
        for strategy in ['fixed','react','plan']:
            session=Session(profile=tiering_profile())
            result=start_task(session,request_id='m61i-'+strategy,programs=programs,sources=sources,
                settings=replace(load_settings(),enabled=False,api_key=''),as_of=date(2026,11,21),
                strategy=strategy,provider=FixtureProvider())
            assert result['data_hash']==data_hash(programs,sources) and not result['validation_errors']
            assert {r['program_id'] for r in result['recommendations']}=={'cmu-msaii-pittsburgh'}
            strategies[strategy]={'data_hash':result['data_hash'],'transport':'deterministic_fixture_not_real_model'}
    after={p.name:sha256(p) for p in originals};assert before==after
    proof=dict(milestone='M6.1i',status='passed',programs=20,sources=138,directory_programs=83,
        programs_enriched=7,new_sources=13,prior_sources_preserved=125,optional_raw_responses_rehashed=checked,
        scripted_capture_attempts=receipts['request_attempts'],used_capture_keys=sorted(used),
        excluded_or_unused_captures=[dict(key=r['key'],status=r['status'],http_status=r.get('http_status')) for r in receipts['captures'] if r['key'] not in used],
        admission_research_not_imported=review['admission_research_not_imported'],tuition_ceiling_checks=price_checks,
        summary=summary,shared_strategies=strategies,data_hash=data_hash(programs,sources),
        database_hashes_before=before,database_hashes_after=after,external_requests_in_verifier=0,
        paid_model_requests=0,formal_benchmark_run=False)
    for filename,document in [('verification.json',proof),('catalog_audit.json',audit)]:
        (output/filename).write_text(json.dumps(document,indent=2)+'\n',encoding='utf-8')
    (output/'catalog_audit.md').write_text(markdown_report(audit),encoding='utf-8')
    print(f'M6.1i passed: 20 programs / 138 sources / 8 two-sided estimates / 4 ceiling-only bounds; proof: {output}')
    return 0

if __name__=='__main__':raise SystemExit(main())
