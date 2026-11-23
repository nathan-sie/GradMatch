"""Verify the 83-program preliminary layer without model or network requests."""
import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import socket
from unittest.mock import patch
from uuid import uuid4

from gradmatch.bootstrap import bootstrap_public_catalog
from gradmatch.catalog import load_seed, read_catalog
from gradmatch.community import exploration_rows
from gradmatch.directory import bootstrap_directory, read_directory
from gradmatch.providers import OpenAIProvider
from gradmatch.session import tiering_profile
from gradmatch.storage import PROJECT_ROOT, DEFAULT_DATABASE
from gradmatch.validation import data_hash


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path)
    args=parser.parse_args()
    output=args.output_dir or PROJECT_ROOT/'work/m62'/str(uuid4())
    output.mkdir(parents=True,exist_ok=False)
    originals=[p for p in [DEFAULT_DATABASE,PROJECT_ROOT/'work/csgrad_candidates.db'] if p.exists()]
    hashes=lambda:{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in originals}
    before=hashes()
    def deny(*args,**kwargs):raise AssertionError('No external or paid request in preliminary verification')
    with (patch.object(socket,'getaddrinfo',deny),patch.object(socket,'create_connection',deny),
          patch.object(socket.socket,'connect',deny),patch.object(OpenAIProvider,'generate',deny)):
        official=bootstrap_public_catalog(output/'public')
        database=bootstrap_directory(official,output/'public')
        d=read_directory(database);rows=d['records'];p,s=load_seed()
        assert data_hash(*read_catalog(official))==data_hash(p,s)
        assert d['total']==d['community_records']==83 and d['official_records']==len(p)
        assert all(not r['recommendation_eligible'] for r in rows)
        expected=d;database.unlink()
        assert read_directory(bootstrap_directory(official,output/'public'))==expected
        profile=tiering_profile()
        candidates=exploration_rows(d,profile,p,s,as_of=date(2026,11,21))
        assert len(candidates)==83 and all(r['personalized_tier'] is None for r in candidates)
        coverage=dict(maintained_programs=83,with_language_fields=sum(len(r['community_facts']['language'])==4 for r in rows),
            known_gre_markers=sum(r['community_facts']['reported_gre']!='unknown' for r in rows),
            with_listed_rounds=sum(bool(r['community_facts']['rounds']) for r in rows),
            with_application_fee=sum(r['community_facts']['application_fee'] is not None for r in rows),
            with_application_portal=sum(bool(r['community_facts']['application_url']) for r in rows))
        assert list(coverage.values())==[83,83,82,80,82,83]
    assert hashes()==before
    proof=dict(milestone='M6.2',status='passed',coverage=coverage,official_programs=len(p),official_sources=len(s),
        official_data_hash=data_hash(p,s),source_sha256=d['source_sha256'],source_url=d['source_url'],
        snapshot_date=d['upstream_generated'],source_intake=d['source_intake'],
        reference_exploration_statuses={status:sum(r['status']==status for r in candidates) for status in sorted({r['status'] for r in candidates})},
        original_databases_before=before,original_databases_after=hashes(),cache_loss_rebuild='passed',
        paid_model_requests=0,external_requests=0,benchmark_scores='not_measured')
    (output/'verification.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(proof,indent=2))


if __name__=='__main__':
    main()
