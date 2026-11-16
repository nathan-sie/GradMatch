"""Verify the recommendation pilot; optional two paid synthetic OpenAI requests."""
import argparse
from datetime import date, datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
from gradmatch.catalog import load_seed, read_catalog, coverage_rows
from gradmatch.config import load_settings
from gradmatch.service import start_task, export_session
from gradmatch.session import Session, tiering_profile
from gradmatch.storage import PROJECT_ROOT
from gradmatch.validation import data_hash

def live_check(programs,sources):
    settings=load_settings()
    if not settings.ready:
        return {"status":"not_run","model_calls":0,"reason":"Model not configured or enabled."}
    session=Session(profile=tiering_profile())
    turns=[]
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    path=PROJECT_ROOT/'work'/f'm35_live_synthetic_{stamp}.json'
    before=session.profile.model_dump(mode='json')
    checks={}
    try:
        for message in [None,'Change my tuition budget to 100000']:
            turns.append(start_task(session,request_id=str(uuid4()),programs=programs,sources=sources,
                settings=settings,as_of=date(2026,11,16),message=message))
            if turns[-1].get('model_status')!='completed':break
        first=turns[0]
        second=turns[1] if len(turns)==2 else {}
        checks={
            'real_model_completed_both_turns':len(turns)==2 and all(t.get('model_status')=='completed' for t in turns),
            'one_supported_lottery_recommendation':[(i['program_id'],i['tier']) for i in first.get('recommendations',[])]==[('cmu-msaii-pittsburgh','Lottery')],
            'exact_total_includes_required_summer':bool(first.get('recommendations')) and first['recommendations'][0]['checks']['tuition']['upper_usd']=='137400',
            'budget_removes_msaii':not second.get('recommendations') and any(i['program_id']=='cmu-msaii-pittsburgh' and any('budget' in r for r in i['reasons']) for i in second.get('changes_from_previous',{}).get('removed',[])),
            'background_preserved':session.profile.model_dump(mode='json')=={**before,'tuition_budget_usd':'100000','profile_version':2},
            'no_validation_errors':all(not t.get('validation_errors') for t in turns),
            'bounded_two_requests':len(session.usage)==2,
        }
    finally:
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({'synthetic_only':True,'turns':turns,'session':export_session(session),'checks':checks},indent=2),encoding='utf-8')
    return {'status':'passed' if all(checks.values()) else 'failed','checks':checks,'model_calls':len(session.usage),
            'usage':session.usage,'estimated_cost_usd':str(sum(Decimal(u['estimated_cost_usd']) for u in session.usage)) if all(u['estimated_cost_usd'] is not None for u in session.usage) else None,
            'synthetic_log':str(path)}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-model',action='store_true',help='Allow at most two paid requests, using a fictional profile only.')
    args=parser.parse_args()
    programs,sources=load_seed(); actual,actual_sources=read_catalog()
    if data_hash(programs,sources)!=data_hash(actual,actual_sources):
        raise ValueError('Reimport the current m35 seed before verification; SQLite differs from the snapshots.')
    result=subprocess.run([sys.executable,'-m','pytest','-q'],cwd=PROJECT_ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=120)
    report={'milestone':'M3.5','verified_at':datetime.now(timezone.utc).isoformat(),
        'offline_status':'passed' if result.returncode==0 else 'failed','test_output':result.stdout,
        'programs':len(programs),'sources':len(sources),'data_hash':data_hash(programs,sources),
        'rubric_version':'conservative-v1.1','live_model':{'status':'not_run','model_calls':0},
        'manual_acceptance':'pending','formal_benchmark':'not_run','m4_started':False}
    if result.returncode==0 and args.live_model:report['live_model']=live_check(programs,sources)
    out=PROJECT_ROOT/'work';out.mkdir(exist_ok=True)
    (out/'m35_verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (out/'m35_catalog_coverage.json').write_text(json.dumps(coverage_rows(programs,sources),indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['offline_status','programs','sources','live_model']},indent=2))
    if result.returncode:print(result.stdout)
    return 0 if result.returncode==0 and report['live_model']['status']!='failed' else 1

if __name__=='__main__':raise SystemExit(main())
