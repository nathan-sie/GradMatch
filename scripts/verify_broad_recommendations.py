"""Verify all three shared strategies can recommend outside the 20 official records."""
import argparse
from dataclasses import replace
from datetime import date
import hashlib
import json
from pathlib import Path
import socket
from unittest.mock import patch
from uuid import uuid4

from gradmatch.catalog import DEFAULT_SEED, load_seed
from gradmatch.config import load_settings
from gradmatch.providers import OpenAIProvider
from gradmatch.ranking import PreliminaryRecommendationDraft
from gradmatch.service import start_task
from gradmatch.session import Session,tiering_profile
from gradmatch.storage import DEFAULT_DATABASE,PROJECT_ROOT
from gradmatch.validation import data_hash
from scripts.m5_fixtures import FixtureProvider


class BroadFixture(FixtureProvider):
    def generate(self,kind,purpose,payload,session):
        result=super().generate(kind,purpose,payload,session)
        if purpose=='rank' and payload.get('recommendation_scope')=='broad':
            ids=[pid for pid in payload['allowed_preliminary_program_ids'] if pid.startswith('community-')]
            ids.sort(key=lambda pid:(pid!='community-sss-stanford-mscs',pid))
            result.suggestions=[PreliminaryRecommendationDraft(program_id=pid,reason_check_ids=['english','deadline','gre']) for pid in ids[:8]]
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path)
    args=parser.parse_args()
    output=args.output_dir or PROJECT_ROOT/'work/m63'/str(uuid4());output.mkdir(parents=True,exist_ok=False)
    originals=[p for p in [DEFAULT_DATABASE,PROJECT_ROOT/'work/csgrad_candidates.db'] if p.exists()]
    hashes=lambda:{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in originals}
    before=hashes();p,s=load_seed(DEFAULT_SEED);official_hash=data_hash(p,s)
    def deny(*args,**kwargs):raise AssertionError('No paid or external request in broad verification')
    strategies={}
    with (patch.object(socket,'getaddrinfo',deny),patch.object(socket,'create_connection',deny),
          patch.object(socket.socket,'connect',deny),patch.object(OpenAIProvider,'generate',deny)):
        for strategy in ['fixed','react','plan']:
            session=Session(profile=tiering_profile());provider=BroadFixture()
            r=start_task(session,request_id=str(uuid4()),programs=p,sources=s,
                settings=replace(load_settings(),enabled=False,api_key=''),as_of=date(2026,11,21),
                strategy=strategy,provider=provider,recommendation_scope='broad')
            assert r['validation_passed'] and len(r['retrieved_program_ids'])==r['catalog_program_count']==83
            assert 'community-sss-stanford-mscs' in {i['program_id'] for i in r['preliminary_recommendations']}
            payload=next(v for purpose,v in provider.calls if purpose=='rank')
            screen=next(i for i in payload['preliminary_reports'] if i['program_id']=='community-sss-stanford-mscs')
            assert screen['next_listed_round']['date']=='2026-12-08'
            strategies[strategy]=dict(status='passed',catalog_programs=83,retrieved_programs=83,
                preliminary_recommendations=len(r['preliminary_recommendations']),
                community_only_recommended_ids=[i['program_id'] for i in r['preliminary_recommendations'] if i['program_id'].startswith('community-')],
                stanford_next_listed_round=screen['next_listed_round'],fixture_calls=len(provider.calls),
                community_data_hash=r['community_data_hash'],recommendation_data_hash=r['recommendation_data_hash'],
                raw_model_transport_requests=0,ranking_payload_characters=len(json.dumps(payload)))
    assert hashes()==before and data_hash(p,s)==official_hash
    report=dict(milestone='M6.3',status='passed',strategies=strategies,official_programs=20,official_sources=145,
        official_data_hash=official_hash,databases_before=before,databases_after=hashes(),
        paid_model_requests=0,external_requests=0,real_model_acceptance='not_run',benchmark_scores='not_measured')
    (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
