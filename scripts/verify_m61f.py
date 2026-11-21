"""Verify the twenty-record focus catalog and minimum-only budget handling offline."""

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
from gradmatch.catalog import M61E_SEED, load_seed, read_catalog
from gradmatch.config import load_settings
from gradmatch.constraints import check_constraints
from gradmatch.directory import bootstrap_directory, read_directory
from gradmatch.providers import OpenAIProvider
from gradmatch.service import start_task
from gradmatch.session import Session, tiering_profile
from gradmatch.storage import DEFAULT_DATABASE, PROJECT_ROOT
from gradmatch.validation import data_hash
from scripts.audit_catalog import build_report
from scripts.m5_fixtures import FixtureProvider


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path)
    args=parser.parse_args()
    output=args.output_dir or PROJECT_ROOT/'work/m61f'/str(uuid4())
    output.mkdir(parents=True,exist_ok=False)
    originals=[p for p in [DEFAULT_DATABASE,PROJECT_ROOT/'work/csgrad_candidates.db'] if p.exists()]
    before={p.name:sha256(p) for p in originals}
    def deny(*args,**kwargs):
        raise AssertionError('No external or paid requests in snapshot verification')
    with (patch.object(socket,'getaddrinfo',deny),patch.object(socket,'create_connection',deny),
          patch.object(socket.socket,'connect',deny),patch.object(OpenAIProvider,'generate',deny)):
        programs,sources=load_seed()
        _,prior=load_seed(M61E_SEED)
        review=json.loads((PROJECT_ROOT/'data/review/m61f_field_reviews.json').read_text(encoding='utf-8'))
        receipts=json.loads((PROJECT_ROOT/'data/review/m61f_capture_receipts.json').read_text(encoding='utf-8'))
        assert len(programs)==20 and len(sources)==94 and len(review['new_source_ids'])==12
        assert all(sources[sid]==source for sid,source in prior.items())
        checked=0
        for sid in review['new_source_ids']:
            source=sources[sid]
            receipt=next(r for r in receipts['captures'] if r.get('url')==str(source.url)
                         and r.get('raw_response_sha256')==source.raw_response_sha256)
            assert receipt['status']=='captured' and receipt['http_status']==200
            raw=PROJECT_ROOT/'work/m61f_research'/(receipt['key']+'.html')
            if raw.exists():
                assert sha256(raw)==source.raw_response_sha256
                checked+=1
        database=bootstrap_public_catalog(output/'public')
        assert data_hash(*read_catalog(database))==data_hash(programs,sources)
        directory=read_directory(bootstrap_directory(database,output/'public'))
        assert directory['total']==83 and directory['official_records']==20
        assert all(not r['recommendation_eligible'] for r in directory['records'])
        old=build_report(seed=M61E_SEED,as_of=date(2026,11,20))['catalog']['summary']
        audit=build_report(as_of=date(2026,11,20))
        new=audit['catalog']['summary']
        assert new['computable_verified_tuition']==7 and new['minimum_only_tuition']==1
        assert old['full_eligibility_reviews']==1 and new['full_eligibility_reviews']==2
        assert new['reference_formal_evidence_ready']==1
        duke=next(p for p in programs if p.program_id=='duke-ms-ece-durham')
        floor_checks=[]
        for budget in ['100000','104820','140000']:
            profile=tiering_profile();profile.tuition_budget_usd=Decimal(budget)
            report=check_constraints(profile,duke,sources,as_of=date(2026,11,20))
            check=next(c for c in report.checks if c.rule_id=='tuition')
            assert report.tuition.upper_usd is None and str(report.tuition.lower_usd)=='104820'
            assert check.status==('fail' if budget=='100000' else 'unknown')
            floor_checks.append(dict(budget_usd=budget,status=check.status,source_ids=check.source_ids))
        strategies={}
        for strategy in ['fixed','react','plan']:
            session=Session(profile=tiering_profile())
            result=start_task(session,request_id='m61f-'+strategy,programs=programs,sources=sources,
                settings=replace(load_settings(),enabled=False,api_key=''),as_of=date(2026,11,20),
                strategy=strategy,provider=FixtureProvider())
            assert result['data_hash']==data_hash(programs,sources) and not result['validation_errors']
            assert {r['program_id'] for r in result['recommendations']}=={'cmu-msaii-pittsburgh'}
            strategies[strategy]={'data_hash':result['data_hash'],'transport':'deterministic_fixture_not_real_model'}
    after={p.name:sha256(p) for p in originals}
    assert before==after
    proof=dict(milestone='M6.1f',status='passed',programs=20,sources=94,directory_programs=83,
        new_programs=review['new_programs'],repaired_programs=review['repaired_programs'],new_sources=12,
        prior_sources_preserved=82,optional_raw_responses_rehashed=checked,
        request_attempts_in_preparation=receipts['request_attempts'],
        unused_empty_capture='duke_rates; HTTP 200 with empty extracted body; not imported',
        before=old,after=new,minimum_only_budget_checks=floor_checks,shared_strategies=strategies,
        data_hash=data_hash(programs,sources),database_hashes_before=before,database_hashes_after=after,
        external_requests_in_verifier=0,paid_model_requests=0,formal_benchmark_run=False)
    for filename,document in [('verification.json',proof),('catalog_audit.json',audit)]:
        (output/filename).write_text(json.dumps(document,indent=2)+'\n',encoding='utf-8')
    from gradmatch.catalog_audit import markdown_report
    (output/'catalog_audit.md').write_text(markdown_report(audit),encoding='utf-8')
    print(f'M6.1f passed: 20 programs / 94 sources / 83 directory leads; proof: {output}')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
