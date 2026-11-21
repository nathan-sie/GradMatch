"""Verify priority eligibility repairs and non-personal cohort context offline."""
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
from gradmatch.catalog import M61I_SEED, load_seed, read_catalog
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
    output=args.output_dir or PROJECT_ROOT/'work/m61j'/str(uuid4())
    output.mkdir(parents=True,exist_ok=False)
    originals=[p for p in [DEFAULT_DATABASE,PROJECT_ROOT/'work/csgrad_candidates.db'] if p.exists()]
    before={p.name:sha256(p) for p in originals}
    def deny(*args,**kwargs):raise AssertionError('No external or paid request in snapshot verification')
    with (patch.object(socket,'getaddrinfo',deny),patch.object(socket,'create_connection',deny),
          patch.object(socket.socket,'connect',deny),patch.object(OpenAIProvider,'generate',deny)):
        programs,sources=load_seed();old_programs,prior=load_seed(M61I_SEED)
        review=json.loads((PROJECT_ROOT/'data/review/m61j_field_reviews.json').read_text(encoding='utf-8'))
        receipts=json.loads((PROJECT_ROOT/'data/review/m61j_capture_receipts.json').read_text(encoding='utf-8'))
        assert len(programs)==20 and len(sources)==145 and len(review['programs_enriched'])==2
        assert all(sources[k]==v for k,v in prior.items())
        assert {p.program_id:p.tuition for p in programs}=={p.program_id:p.tuition for p in old_programs}
        used=set();checked=0
        for sid in review['new_source_ids']:
            source=sources[sid]
            receipt=next(r for r in receipts['captures'] if r.get('url')==str(source.url) and r.get('raw_response_sha256')==source.raw_response_sha256)
            assert receipt['status']=='captured' and receipt['http_status']==200
            used.add(receipt['key'])
            for ext in ['.html','.pdf']:
                raw=PROJECT_ROOT/'work/m61j_research'/(receipt['key']+ext)
                if raw.exists():assert sha256(raw)==source.raw_response_sha256;checked+=1;break
        database=bootstrap_public_catalog(output/'public')
        assert data_hash(*read_catalog(database))==data_hash(programs,sources)
        directory=read_directory(bootstrap_directory(database,output/'public'))
        assert directory['total']==83 and directory['official_records']==20
        assert sum(r['source_reports_halted'] for r in directory['records'])==4
        context_rows=[r for r in directory['records'] if r['cohort_context']]
        assert len(context_rows)==2 and all(not r['recommendation_eligible'] for r in context_rows)
        gaps={}
        for pid,expected in [('cmu-mcds-pittsburgh',['english']),('nyu-mscs-tandon-brooklyn',['gpa'])]:
            program=next(p for p in programs if p.program_id==pid)
            report=check_constraints(tiering_profile(),program,sources,as_of=date(2026,11,21))
            unknown=[c for c in report.checks if c.status=='unknown']
            assert sorted(c.rule_id for c in unknown)==expected and not report.recommendation_ready
            gaps[pid]=dict(unknown_checks=[c.model_dump(mode='json') for c in unknown],
                           hard_checks_status=report.hard_checks_status.value,recommendation_ready=False)
        audit=build_report(as_of=date(2026,11,21));summary=audit['catalog']['summary']
        assert summary['computable_verified_tuition']==12 and summary['maximum_only_tuition']==4
        assert summary['full_eligibility_reviews']==7 and summary['fields']['prerequisites']['usable']==10
        assert summary['fields']['intake']['usable']==14 and summary['fields']['deadline']['usable']==12
        assert summary['reference_hard_checks_ready']==2 and summary['reference_formal_evidence_ready']==1
        strategies={}
        for strategy in ['fixed','react','plan']:
            session=Session(profile=tiering_profile())
            result=start_task(session,request_id='m61j-'+strategy,programs=programs,sources=sources,
                settings=replace(load_settings(),enabled=False,api_key=''),as_of=date(2026,11,21),
                strategy=strategy,provider=FixtureProvider())
            assert result['data_hash']==data_hash(programs,sources) and not result['validation_errors']
            assert {r['program_id'] for r in result['recommendations']}=={'cmu-msaii-pittsburgh'}
            strategies[strategy]={'data_hash':result['data_hash'],'transport':'deterministic_fixture_not_real_model'}
    after={p.name:sha256(p) for p in originals};assert before==after
    proof=dict(milestone='M6.1j',status='passed',programs=20,sources=145,directory_programs=83,
        programs_enriched=2,new_sources=7,prior_sources_preserved=138,optional_raw_responses_rehashed=checked,
        scripted_capture_attempts=receipts['request_attempts'],used_capture_keys=sorted(used),
        excluded_captures=[dict(key=r['key'],status=r['status'],http_status=r.get('http_status')) for r in receipts['captures'] if r['key'] not in used],
        remaining_reference_gaps=gaps,cohort_context_programs=[r['linked_program_id'] for r in context_rows],
        summary=summary,shared_strategies=strategies,data_hash=data_hash(programs,sources),
        database_hashes_before=before,database_hashes_after=after,external_requests_in_verifier=0,
        paid_model_requests=0,formal_benchmark_run=False)
    for filename,document in [('verification.json',proof),('catalog_audit.json',audit)]:
        (output/filename).write_text(json.dumps(document,indent=2)+'\n',encoding='utf-8')
    (output/'catalog_audit.md').write_text(markdown_report(audit),encoding='utf-8')
    print(f'M6.1j passed: 20 programs / 145 sources / MCDS English gap retained / NYU GPA scope retained; proof: {output}')
    return 0

if __name__=='__main__':raise SystemExit(main())
