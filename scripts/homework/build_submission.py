"""Build a credential-free, self-contained ZIP from the frozen source and actual evidence."""
import argparse
import json
from pathlib import Path
from uuid import uuid4
import zipfile
from gradmatch.homework.submission import PACKAGE_NAME,package_payloads,sha,verify_payloads
from gradmatch.storage import PROJECT_ROOT


def build(output_dir,root=PROJECT_ROOT):
    output_dir=Path(output_dir);output_dir.mkdir(parents=True,exist_ok=False)
    payloads=package_payloads(root)
    checks=verify_payloads(payloads)
    archive=output_dir/(PACKAGE_NAME+'.zip')
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as stream:
        for name,data in sorted(payloads.items()):
            info=zipfile.ZipInfo(PACKAGE_NAME+'/'+name,date_time=(2026,11,17,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o100644<<16
            stream.writestr(info,data,compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
    report={**checks,'archive_name':archive.name,'archive_bytes':archive.stat().st_size,
        'archive_sha256':sha(archive.read_bytes()),'uncompressed_bytes':sum(map(len,payloads.values())),
        'actual_candidate_requests':0,'actual_judge_requests':0}
    with (output_dir/'build.json').open('x',encoding='utf-8',newline='\n') as stream:
        stream.write(json.dumps(report,indent=2)+'\n')
    return archive,report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path)
    args=parser.parse_args()
    archive,report=build(args.output_dir or PROJECT_ROOT/'work/h6'/('package-'+str(uuid4())))
    print(json.dumps(report,indent=2))
    print('Archive:',archive)


if __name__=='__main__':main()
