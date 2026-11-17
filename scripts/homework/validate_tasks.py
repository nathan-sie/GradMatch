"""Validate H1 artifacts offline; this does not run or grade any model."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from gradmatch.homework.validation import validate_bundle
from gradmatch.storage import PROJECT_ROOT


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,default=PROJECT_ROOT/'work/h1_verification.json')
    args=parser.parse_args()
    try:
        report=validate_bundle()
    except (ValueError,KeyError,IndexError,TypeError,OSError) as error:
        report={'status':'failed','checkpoint':'H1','error':str(error),'model_api_calls':0,'formal_evaluation':'not_run'}
    report['verified_at']=datetime.now(timezone.utc).isoformat()
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
