"""Verify the second catalog batch and its scope without paid model requests."""
import argparse
from dataclasses import replace
from datetime import date
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from unittest.mock import patch
from uuid import uuid4

from gradmatch.bootstrap import resolve_app_database
from gradmatch.catalog import M61C_SEED as DEFAULT_SEED, M61B_SEED, import_catalog, load_seed as latest_load_seed, read_catalog
from gradmatch.catalog_audit import markdown_report
from gradmatch.config import load_settings
from gradmatch.providers import OpenAIProvider
from gradmatch.service import start_task
from gradmatch.session import Session, tiering_profile
from gradmatch.storage import DEFAULT_DATABASE, PROJECT_ROOT
from gradmatch.validation import data_hash
from scripts.audit_catalog import build_report, sha256
from scripts.m5_fixtures import FixtureProvider

MANIFEST=PROJECT_ROOT/'data/review/m61c_field_reviews.json'
RECEIPTS=PROJECT_ROOT/'data/review/m61c_capture_receipts.json'
REVIEW=PROJECT_ROOT/'data/review/m61c_review_plan.json'


def load_seed(path=DEFAULT_SEED):
    """Historical verification explicitly uses the immutable M6.1c seed."""
    return latest_load_seed(path)


def verify_receipts(programs,sources):
    manifest=json.loads(MANIFEST.read_text(encoding='utf-8'))
    captured=json.loads(RECEIPTS.read_text(encoding='utf-8'))
    prior_programs,prior_sources=load_seed(M61B_SEED)
    assert len(programs)==manifest['expected_programs']==16
    assert len(sources)==manifest['expected_sources']==62
    assert all(sources[sid]==source for sid,source in prior_sources.items())
    assert set(manifest['new_source_ids'])==set(sources)-set(prior_sources)
    assert set(manifest['new_programs'])=={p.program_id for p in programs}-{p.program_id for p in prior_programs}
    assert len(manifest['new_programs'])==4 and len(manifest['new_source_ids'])==19
    receipts=captured['captures']
    assert captured['http_requests']==sum(1+len(r.get('redirects',[])) for r in receipts)
    rehashed=[]
    unavailable=[]
    for sid in manifest['new_source_ids']:
        source=sources[sid]
        matching=[r for r in receipts if r.get('url')==str(source.url)
            and r.get('raw_response_sha256')==source.raw_response_sha256]
        assert len(matching)==1
        receipt=matching[0]
        assert receipt['status']=='captured' and receipt['http_status']==200
        assert receipt['retrieved_at']==source.retrieved_at.isoformat()
        suffix='.pdf' if 'pdf' in receipt['content_type'] else '.html'
        raw=PROJECT_ROOT/'work/m61c_research'/(receipt['key']+suffix)
        if raw.exists():
            assert sha256(raw)==source.raw_response_sha256
            if suffix=='.pdf':
                assert raw.read_bytes().startswith(b'%PDF')
            rehashed.append(sid)
        else:
            unavailable.append(sid)
    return dict(new_sources_checked=len(manifest['new_source_ids']),raw_responses_rehashed=len(rehashed),
        optional_raw_not_supplied=unavailable,historical_source_objects_preserved=len(prior_sources),
        preparation_http_requests=captured['http_requests'],
        failed_captures_not_imported=sum(r['status']!='captured' for r in receipts),
        new_computable_tuition=manifest['new_computable_tuition'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path)
    parser.add_argument('--skip-tests',action='store_true',help='Only after this revision has passed regression.')
    args=parser.parse_args()
    directory=args.output_dir or PROJECT_ROOT/'work/m61c'/str(uuid4())
    directory.mkdir(parents=True,exist_ok=False)
    databases=[p for p in [DEFAULT_DATABASE,PROJECT_ROOT/'work/csgrad_candidates.db'] if p.exists()]
    before={p.name:sha256(p) for p in databases}
    test_summary='not_run'
    if not args.skip_tests:
        result=subprocess.run([sys.executable,'-m','pytest','-q','--tb=short'],cwd=PROJECT_ROOT,
            capture_output=True,text=True,encoding='utf-8',errors='replace')
        (directory/'offline_tests.txt').write_text(result.stdout+result.stderr,encoding='utf-8',newline='\n')
        test_summary=result.stdout.strip().splitlines()[-1]
        print(test_summary)
        if result.returncode:
            print('Regression failed; see '+str(directory/'offline_tests.txt'))
            return 1
    blocked={'external_network':0,'paid_model':0}
    loopback=0
    original_connect=socket.socket.connect
    def deny_network(*args,**kwargs):
        blocked['external_network']+=1
        raise AssertionError('External network access during snapshot verification')
    def local_connect(sock,address):
        nonlocal loopback
        if isinstance(address,tuple) and address[0] in {'127.0.0.1','::1'}:
            loopback+=1
            return original_connect(sock,address)
        return deny_network(sock,address)
    def deny_model(*args,**kwargs):
        blocked['paid_model']+=1
        raise AssertionError('Paid model request during snapshot verification')
    with (patch.object(socket,'getaddrinfo',deny_network),patch.object(socket,'create_connection',deny_network),
          patch.object(socket.socket,'connect',local_connect),patch.object(OpenAIProvider,'generate',deny_model)):
        programs,sources=load_seed()
        provenance=verify_receipts(programs,sources)
        digest=data_hash(programs,sources)
        database=directory/'catalog.db'
        import_catalog(DEFAULT_SEED,database)
        restored,restored_sources=read_catalog(database)
        assert data_hash(restored,restored_sources)==digest
        strategies={}
        for strategy in ['fixed','react','plan']:
            session=Session(profile=tiering_profile())
            result=start_task(session,request_id='m61c-'+strategy,programs=restored,sources=restored_sources,
                settings=replace(load_settings(),enabled=False,api_key=''),as_of=date(2026,11,20),
                strategy=strategy,provider=FixtureProvider())
            assert result['data_hash']==digest and not result['validation_errors']
            assert {r['program_id'] for r in result['recommendations']}=={'cmu-msaii-pittsburgh'}
            strategies[strategy]=dict(catalog_hash=result['data_hash'],programs=len(session.agent_task.programs),
                validation_passed=result['validation_passed'],transport='deterministic_fixture_not_real_model')
        from streamlit.testing.v1 import AppTest
        with patch.dict(os.environ,{'GRADMATCH_DB_PATH':str(database),'MODEL_ENABLED':'false'}):
            app=AppTest.from_file(str(PROJECT_ROOT/'app.py'),default_timeout=30).run()
            assert not app.exception
            assert [m.value for m in app.metric]==['16','62']
            app.button(key='m35_load_example').click().run()
            assert not app.exception and not app.session_state['m2_session'].usage
        with patch.dict(os.environ,{'GRADMATCH_PUBLIC_CACHE_DIR':str(directory/'public-cache')}):
            if not os.environ.get('GRADMATCH_DB_PATH'):
                assert data_hash(*read_catalog(resolve_app_database()))==data_hash(*latest_load_seed())
        audit=build_report(seed=DEFAULT_SEED,as_of=date(2026,11,20))
        summary=audit['catalog']['summary']
        assert summary['programs']==16 and summary['sources']==62
        assert summary['computable_verified_tuition']==7
        assert summary['reference_formal_evidence_ready']==1
        assert audit['candidates']['summary']['screening_counts']['already_linked_identity']==16
        assert not any(r['recommendation_eligible'] for r in audit['candidates']['inventory'])
    after={p.name:sha256(p) for p in databases}
    assert before==after and blocked=={'external_network':0,'paid_model':0}
    (directory/'catalog_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    (directory/'catalog_audit.md').write_text(markdown_report(audit),encoding='utf-8',newline='\n')
    proof=dict(milestone='M6.1c',status='passed',tests=test_summary,programs=16,sources=62,data_hash=digest,
        catalog_database=str(database.resolve()),provenance=provenance,database_sha256=after,
        old_databases_unchanged=before==after,page_metrics=['16','62'],shared_strategies=strategies,
        external_network_requests_in_verifier=0,loopback_connections_for_page_test=loopback,paid_model_requests=0,
        computable_tuition_estimates=7,reference_formal_evidence_ready=1,formal_benchmark_run=False,full_m6_complete=False,
        remaining_expansion_queue=4,input_code_sha256={p:sha256(PROJECT_ROOT/p) for p in [
            'gradmatch/catalog.py','gradmatch/bootstrap.py','gradmatch/constraints.py','gradmatch/catalog_audit.py',
            'data/catalog/m61c_seed.json','data/review/m61c_review_plan.json',
            'data/review/m61c_field_reviews.json','data/review/m61c_capture_receipts.json',
            'scripts/verify_m61c.py','tests/test_m61c.py']})
    (directory/'verification.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8',newline='\n')
    print('M6.1c passed: 16 programs / 62 sources; 7 computable published-rate estimates; no paid model or external network calls.')
    print('Evidence directory: '+str(directory.resolve()))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
