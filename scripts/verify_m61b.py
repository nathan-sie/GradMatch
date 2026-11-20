"""Verify the first M6.1b data batch without any model or network transport."""
import argparse
from dataclasses import replace
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from unittest.mock import patch
from uuid import uuid4

from gradmatch.bootstrap import resolve_app_database
from gradmatch.catalog import DEFAULT_SEED, M35_SEED, M61B_SEED, import_catalog, load_seed, read_catalog
from gradmatch.catalog_audit import markdown_report
from gradmatch.config import load_settings
from gradmatch.providers import OpenAIProvider
from gradmatch.service import start_task
from gradmatch.session import Session, tiering_profile
from gradmatch.storage import DEFAULT_DATABASE, PROJECT_ROOT
from gradmatch.validation import data_hash
from scripts.audit_catalog import build_report, sha256
from scripts.m5_fixtures import FixtureProvider


def verify_receipts(programs, sources):
    manifest = json.loads((PROJECT_ROOT/'data/review/m61b_field_reviews.json').read_text(encoding='utf-8'))
    document = json.loads((PROJECT_ROOT/'data/review/m61b_capture_receipts.json').read_text(encoding='utf-8'))
    old_programs, old_sources = load_seed(M35_SEED)
    assert all(sources[sid] == source for sid, source in old_sources.items())
    assert set(manifest['new_source_ids']) == set(sources) - set(old_sources)
    assert set(manifest['new_programs']) == {p.program_id for p in programs} - {p.program_id for p in old_programs}
    assert len({r['program_id'] for r in manifest['pricing_reviews']}) == 5
    assert all(r['decision']=='retain_unknown' and not r['full_program_tuition_verified'] for r in manifest['pricing_reviews'])
    receipts = document['captures']
    assert document['http_requests'] == sum(1+len(r.get('redirects',[])) for r in receipts)
    rehashed = []
    absent = []
    for sid in manifest['new_source_ids']:
        source = sources[sid]
        matching = [r for r in receipts if r['raw_response_sha256']==source.raw_response_sha256
            and r['url']==str(source.url)]
        assert len(matching)==1 and matching[0]['http_status']==200 and matching[0]['status']=='captured'
        receipt = matching[0]
        assert receipt['retrieved_at']==source.retrieved_at.isoformat()
        suffix = '.pdf' if 'pdf' in receipt['content_type'] else '.html'
        raw = PROJECT_ROOT/'work/m61b_research'/(receipt['key']+suffix)
        if raw.exists():
            assert sha256(raw)==source.raw_response_sha256
            rehashed.append(sid)
        else:
            absent.append(sid)
    return dict(new_sources_checked=len(manifest['new_source_ids']),
        raw_responses_rehashed=len(rehashed), optional_raw_not_supplied=absent,
        historical_source_objects_preserved=len(old_sources),
        preparation_http_requests=document['http_requests'],
        failed_captures_not_imported=sum(r['status']!='captured' for r in receipts),
        pricing_reviewed=5, pricing_newly_computable=0)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path)
    parser.add_argument('--skip-tests',action='store_true',help='Only after this source has passed the suite.')
    args=parser.parse_args()
    directory=args.output_dir or PROJECT_ROOT/'work/m61b'/str(uuid4())
    directory.mkdir(parents=True,exist_ok=False)
    databases=[p for p in [DEFAULT_DATABASE,PROJECT_ROOT/'work/csgrad_candidates.db'] if p.exists()]
    before={p.name:sha256(p) for p in databases}
    tests='not_run'
    if not args.skip_tests:
        checked=subprocess.run([sys.executable,'-m','pytest','-q','--tb=short'],cwd=PROJECT_ROOT,
            capture_output=True,text=True,encoding='utf-8',errors='replace')
        (directory/'offline_tests.txt').write_text(checked.stdout+checked.stderr,encoding='utf-8')
        print(checked.stdout.strip().splitlines()[-1])
        if checked.returncode:
            print('Regression failed; see '+str(directory/'offline_tests.txt'))
            return 1
        tests='passed'
    blocked={'network':0,'paid_model':0}
    loopback_connections=0
    original_connect=socket.socket.connect
    def deny_network(*args,**kwargs):
        blocked['network']+=1
        raise AssertionError('Snapshot data verification attempted network access')
    def deny_model(*args,**kwargs):
        blocked['paid_model']+=1
        raise AssertionError('Snapshot data verification attempted a paid provider')
    def local_page_connect(sock,address):
        nonlocal loopback_connections
        # Windows asyncio uses a loopback socket pair even for an in-process page.
        if isinstance(address,tuple) and address[0] in {'127.0.0.1','::1'}:
            loopback_connections+=1
            return original_connect(sock,address)
        return deny_network(sock,address)
    with (patch.object(socket,'getaddrinfo',deny_network),
          patch.object(socket,'create_connection',deny_network),
          patch.object(socket.socket,'connect',local_page_connect),
          patch.object(OpenAIProvider,'generate',deny_model)):
        programs,sources=load_seed(M61B_SEED)
        provenance=verify_receipts(programs,sources)
        database=directory/'catalog.db'
        import_catalog(M61B_SEED,database)
        restored,restored_sources=read_catalog(database)
        digest=data_hash(programs,sources)
        assert data_hash(restored,restored_sources)==digest
        strategy_checks={}
        for strategy in ['fixed','react','plan']:
            session=Session(profile=tiering_profile())
            result=start_task(session,request_id='m61b-'+strategy,
                programs=restored,sources=restored_sources,
                settings=replace(load_settings(),enabled=False,api_key=''),
                as_of=date(2026,11,20),strategy=strategy,provider=FixtureProvider())
            assert result['data_hash']==digest and not result['validation_errors']
            assert {r['program_id'] for r in result['recommendations']}=={'cmu-msaii-pittsburgh'}
            strategy_checks[strategy]=dict(catalog_hash=result['data_hash'],
                programs=len(session.agent_task.programs),status=result['status'],
                validation_passed=result['validation_passed'],transport='deterministic_fixture_not_real_model')
        from streamlit.testing.v1 import AppTest
        with patch.dict(os.environ,{'GRADMATCH_DB_PATH':str(database),'MODEL_ENABLED':'false'}):
            app=AppTest.from_file(str(PROJECT_ROOT/'app.py'),default_timeout=30).run()
            assert not app.exception
            assert [m.value for m in app.metric]==[str(len(programs)),str(len(sources))]
            app.button(key='m35_load_example').click().run()
            assert not app.exception
            assert not app.session_state['m2_session'].usage
        # Resolve the ordinary local startup path too, preserving older developer databases.
        with patch.dict(os.environ,{'GRADMATCH_PUBLIC_CACHE_DIR':str(directory/'public-cache')}):
            if not os.environ.get('GRADMATCH_DB_PATH'):
                active=resolve_app_database()
                assert data_hash(*read_catalog(active))==data_hash(*load_seed(DEFAULT_SEED))
        audit=build_report(as_of=date(2026,11,20),seed=M61B_SEED,
            review_path=PROJECT_ROOT/'data/review/m61b_review_plan.json')
        assert audit['catalog']['summary']['programs']==12
        assert audit['candidates']['summary']['total']==83
        assert audit['candidates']['summary']['screening_counts']['already_linked_identity']==12
        assert not any(r['recommendation_eligible'] for r in audit['candidates']['inventory'])
    after={p.name:sha256(p) for p in databases}
    assert before==after and blocked=={'network':0,'paid_model':0}
    (directory/'catalog_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (directory/'catalog_audit.md').write_text(markdown_report(audit),encoding='utf-8')
    proof=dict(milestone='M6.1b',status='passed',checkpoint='First official batch; complete eligibility/pricing repair and full M6 remain incomplete',
        tests=tests,programs=len(programs),sources=len(sources),data_hash=digest,
        catalog_database=str(database.resolve()),provenance=provenance,
        old_databases_unchanged=before==after,database_sha256=after,
        page_metrics=[str(len(programs)),str(len(sources))],shared_strategies=strategy_checks,
        external_network_requests_in_verifier=blocked['network'],paid_model_requests=blocked['paid_model'],
        loopback_connections_for_page_test=loopback_connections,
        formal_benchmark_run=False,full_m6_complete=False,
        remaining_task_set='210 main tasks and 50 safety prompts, shared runner and a real pilot are later gates',
        input_code_sha256={p:sha256(PROJECT_ROOT/p) for p in [
            'gradmatch/catalog.py','gradmatch/bootstrap.py','gradmatch/constraints.py','gradmatch/catalog_audit.py',
            'data/catalog/m61b_seed.json','data/review/m61b_review_plan.json',
            'data/review/m61b_field_reviews.json','data/review/m61b_capture_receipts.json',
            'scripts/verify_m61b.py','tests/test_m61b.py']})
    (directory/'verification.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8')
    print(f'M6.1b passed: {len(programs)} programs / {len(sources)} official source records; no paid model or external network calls in verification.')
    print('Evidence directory: '+str(directory.resolve()))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
