"""Verify preparation, term-specific English validity and immutable rule history offline."""
import argparse
from dataclasses import replace
from datetime import date
import hashlib
import json
from pathlib import Path
import socket
from unittest.mock import patch
from uuid import uuid4

from gradmatch.bootstrap import bootstrap_public_catalog
from gradmatch.catalog import M61G_SEED, load_seed, read_catalog
from gradmatch.catalog_audit import markdown_report
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
    output=args.output_dir or PROJECT_ROOT/'work/m61h'/str(uuid4())
    output.mkdir(parents=True,exist_ok=False)
    originals=[p for p in [DEFAULT_DATABASE,PROJECT_ROOT/'work/csgrad_candidates.db'] if p.exists()]
    before={p.name:sha256(p) for p in originals}
    def deny(*args,**kwargs):raise AssertionError('No external or paid requests in snapshot verification')
    with (patch.object(socket,'getaddrinfo',deny),patch.object(socket,'create_connection',deny),
          patch.object(socket.socket,'connect',deny),patch.object(OpenAIProvider,'generate',deny)):
        programs,sources=load_seed();_,prior=load_seed(M61G_SEED)
        review=json.loads((PROJECT_ROOT/'data/review/m61h_field_reviews.json').read_text(encoding='utf-8'))
        receipts=json.loads((PROJECT_ROOT/'data/review/m61h_capture_receipts.json').read_text(encoding='utf-8'))
        assert len(programs)==20 and len(sources)==125 and len(review['programs_enriched'])==7
        assert all(sources[sid]==s for sid,s in prior.items())
        checked=0;used=set()
        for sid in review['new_source_ids']:
            s=sources[sid]
            r=next(r for r in receipts['captures'] if r.get('url')==str(s.url) and r.get('raw_response_sha256')==s.raw_response_sha256)
            assert r['status']=='captured' and r['http_status']==200;used.add(r['key'])
            raw=PROJECT_ROOT/'work/m61h_research'/(r['key']+'.html')
            if raw.exists():assert sha256(raw)==s.raw_response_sha256;checked+=1
        database=bootstrap_public_catalog(output/'public')
        assert data_hash(*read_catalog(database))==data_hash(programs,sources)
        directory=read_directory(bootstrap_directory(database,output/'public'))
        assert directory['total']==83 and directory['official_records']==20
        old=build_report(seed=M61G_SEED,as_of=date(2026,11,20))['catalog']['summary']
        audit=build_report(as_of=date(2026,11,21));new=audit['catalog']['summary']
        assert new['computable_verified_tuition']==8 and new['full_eligibility_reviews']==4
        assert new['fields']['english']['usable']==8 and new['fields']['prerequisites']['usable']==8
        assert new['reference_hard_checks_ready']==2 and new['reference_formal_evidence_ready']==1
        strategies={}
        for strategy in ['fixed','react','plan']:
            session=Session(profile=tiering_profile())
            result=start_task(session,request_id='m61h-'+strategy,programs=programs,sources=sources,
                settings=replace(load_settings(),enabled=False,api_key=''),as_of=date(2026,11,21),
                strategy=strategy,provider=FixtureProvider())
            assert result['data_hash']==data_hash(programs,sources) and not result['validation_errors']
            assert {r['program_id'] for r in result['recommendations']}=={'cmu-msaii-pittsburgh'}
            strategies[strategy]={'data_hash':result['data_hash'],'transport':'deterministic_fixture_not_real_model'}
    after={p.name:sha256(p) for p in originals};assert before==after
    proof=dict(milestone='M6.1h',status='passed',programs=20,sources=125,directory_programs=83,
        programs_enriched=7,new_sources=13,prior_sources_preserved=112,optional_raw_responses_rehashed=checked,
        superseded_field_bindings=review['superseded_field_bindings'],request_attempts_in_preparation=receipts['request_attempts'],
        used_capture_keys=sorted(used),unused_captures=[dict(key=r['key'],status=r['status'],http_status=r.get('http_status')) for r in receipts['captures'] if r['key'] not in used],
        before=old,after=new,shared_strategies=strategies,data_hash=data_hash(programs,sources),
        database_hashes_before=before,database_hashes_after=after,external_requests_in_verifier=0,
        paid_model_requests=0,formal_benchmark_run=False)
    for filename,document in [('verification.json',proof),('catalog_audit.json',audit)]:
        (output/filename).write_text(json.dumps(document,indent=2)+'\n',encoding='utf-8')
    (output/'catalog_audit.md').write_text(markdown_report(audit),encoding='utf-8')
    print(f'M6.1h passed: 20 programs / 125 sources / 8 preparation policies / 8 English policies / 4 reviewed eligibility checklists; proof: {output}')
    return 0


if __name__=='__main__':raise SystemExit(main())
