"""Recompute reports from saved H4 records offline, without credentials or model calls."""
import argparse
import json
from pathlib import Path
from uuid import uuid4
from gradmatch.homework.experiment import ExperimentStore
from gradmatch.homework.metrics import summarize,write_reports


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path)
    args=parser.parse_args()
    try:
        store=ExperimentStore(args.experiment_dir)
        result=summarize(store)
        output=write_reports(result,args.output_dir or store.path/'reports'/str(uuid4()))
    except (ValueError,KeyError,TypeError,OSError):
        print('Saved experiment or report path is invalid. No model request was made and no prior result was replaced.')
        return 2
    print(json.dumps({'status':result['status'],'report_dir':str(output),
        'scheduled_executions':result['scheduled_executions'],'terminal_records':result['terminal_records'],
        'model_requests_made_by_summary':0},indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
