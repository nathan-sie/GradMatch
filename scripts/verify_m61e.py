"""Verify the twelve-program repair batch, provenance and offline strategy parity."""

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
from gradmatch.catalog import M61C_SEED, M61E_SEED, import_catalog, load_seed as latest_load_seed, read_catalog
from gradmatch.config import load_settings
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


def load_seed(path=M61E_SEED):
    return latest_load_seed(path)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path)
    args=parser.parse_args()
    output=args.output_dir or PROJECT_ROOT/'work/m61e'/str(uuid4())
    output.mkdir(parents=True,exist_ok=False)
    originals=[p for p in [DEFAULT_DATABASE,PROJECT_ROOT/'work/csgrad_candidates.db'] if p.exists()]
    before={p.name:sha256(p) for p in originals}
    def deny(*args,**kwargs):
        raise AssertionError('No external or paid requests in snapshot verification')
    with (patch.object(socket,'getaddrinfo',deny),patch.object(socket,'create_connection',deny),
          patch.object(socket.socket,'connect',deny),patch.object(OpenAIProvider,'generate',deny)):
        programs,sources=load_seed()
        prior_programs,prior_sources=load_seed(M61C_SEED)
        review=json.loads((PROJECT_ROOT/'data/review/m61e_field_reviews.json').read_text(encoding='utf-8'))
        receipts=json.loads((PROJECT_ROOT/'data/review/m61e_capture_receipts.json').read_text(encoding='utf-8'))
        assert len(programs)==16 and len(sources)==82
        assert all(sources[sid]==s for sid,s in prior_sources.items())
        assert len(review['programs_enriched'])==12 and len(review['new_source_ids'])==20
        hashes_checked=0
        for sid in review['new_source_ids']:
            s=sources[sid]
            r=next(r for r in receipts['captures'] if r.get('url')==str(s.url) and r.get('raw_response_sha256')==s.raw_response_sha256)
            assert r['status']=='captured' and r['http_status']==200
            raw=PROJECT_ROOT/'work/m61e_research'/(r['key']+'.html')
            if raw.exists():
                assert sha256(raw)==s.raw_response_sha256
                hashes_checked+=1
        database=output/'catalog.db'
        import_catalog(M61E_SEED,database)
        assert data_hash(*read_catalog(database))==data_hash(programs,sources)
        directory_path=bootstrap_directory(database,output/'public')
        directory=read_directory(directory_path)
        assert directory['total']==83 and directory['official_records']==16
        assert all(not r['recommendation_eligible'] for r in directory['records'])
        baseline=build_report(seed=M61C_SEED,as_of=date(2026,11,20))
        updated=build_report(seed=M61E_SEED,as_of=date(2026,11,20))
        old=baseline['catalog']['summary'];new=updated['catalog']['summary']
        assert old['fields']['gre']['usable']==8 and new['fields']['gre']['usable']==15
        assert old['fields']['degree']['usable']==8 and new['fields']['degree']['usable']==12
        assert new['computable_verified_tuition']==7 and new['reference_formal_evidence_ready']==1
        strategies={}
        for strategy in ['fixed','react','plan']:
            session=Session(profile=tiering_profile())
            result=start_task(session,request_id='m61e-'+strategy,programs=programs,sources=sources,
                settings=replace(load_settings(),enabled=False,api_key=''),as_of=date(2026,11,20),
                strategy=strategy,provider=FixtureProvider())
            assert result['data_hash']==data_hash(programs,sources) and not result['validation_errors']
            assert {r['program_id'] for r in result['recommendations']}=={'cmu-msaii-pittsburgh'}
            strategies[strategy]={'data_hash':result['data_hash'],'transport':'deterministic_fixture_not_real_model'}
    after={p.name:sha256(p) for p in originals}
    assert before==after
    proof=dict(milestone='M6.1e',status='passed',programs=16,sources=82,directory_programs=83,
        programs_enriched=12,new_sources=20,prior_sources_preserved=62,
        policy_notes_added=sum(len(v) for v in review['programs_enriched'].values()),
        optional_raw_responses_rehashed=hashes_checked,request_attempts_in_preparation=receipts['request_attempts'],
        failed_captures_not_imported=sum(r['status']!='captured' for r in receipts['captures']),
        before=old,after=new,shared_strategies=strategies,data_hash=data_hash(programs,sources),
        database_hashes_before=before,database_hashes_after=after,external_requests_in_verifier=0,
        paid_model_requests=0,formal_benchmark_run=False,complete_eligibility_not_claimed_for_batch=True)
    (output/'verification.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8')
    (output/'catalog_audit.json').write_text(json.dumps(updated,indent=2)+'\n',encoding='utf-8')
    from gradmatch.catalog_audit import markdown_report
    (output/'catalog_audit.md').write_text(markdown_report(updated),encoding='utf-8')
    print(f'M6.1e passed: 12 programs enriched / 82 sources / GRE 8 -> 15 / degree 8 -> 12; proof: {output}')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
