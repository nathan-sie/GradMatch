"""Four read-only snapshot tools; no arbitrary file paths, SQL writes or network."""
from copy import deepcopy
import hashlib
import json
from pydantic import ValidationError
from gradmatch.constraints import check_constraints
from gradmatch.homework.contracts import TOOL_ARGUMENTS
from gradmatch.storage import PROJECT_ROOT


def source_metadata(source):
    value=source.model_dump(mode='json')
    return {k:value[k] for k in ['source_id','program_id','url','title','applicable_intake','effective_period',
        'verification_status','field_groups','locator','retrieved_at','source_excerpt','fact_summary','content_hash']}


class SnapshotTools:
    def __init__(self,programs,sources,as_of):
        self.programs={p.program_id:p.model_copy(deep=True) for p in programs}
        self.sources={k:s.model_copy(deep=True) for k,s in sources.items()}
        self.as_of=as_of

    def catalog_index(self):
        return [{k:p.model_dump(mode='json')[k] for k in ['program_id','university','program_name','degree','campus','discipline']}
            for p in sorted(self.programs.values(),key=lambda p:p.program_id)]

    def dispatch(self,name,arguments,profile):
        if name not in TOOL_ARGUMENTS:return {'ok':False,'error':{'code':'unknown_tool','message':'Tool name is not allowlisted.'}}
        try:args=TOOL_ARGUMENTS[name].model_validate(arguments)
        except ValidationError:return {'ok':False,'error':{'code':'invalid_arguments','message':'Arguments do not match the declared tool schema.'}}
        if name=='search_programs':
            filters=args.model_dump()
            return {'ok':True,'programs':[row for row in self.catalog_index() if all(v is None or row[k]==v for k,v in filters.items())]}
        if name=='get_evidence':
            source=self.sources.get(args.source_id)
            if source is None:return {'ok':False,'error':{'code':'not_found','message':'No such source ID exists in the frozen catalog.'}}
            path=(PROJECT_ROOT/source.snapshot_path).resolve()
            if not path.is_relative_to((PROJECT_ROOT/'data/snapshots').resolve()):
                return {'ok':False,'error':{'code':'invalid_snapshot_path','message':'Snapshot path is outside the public snapshot directory.'}}
            try:
                raw=path.read_bytes()
                if hashlib.sha256(raw).hexdigest()!=source.content_hash:
                    return {'ok':False,'error':{'code':'snapshot_hash_mismatch','message':'The snapshot no longer matches the pinned source.'}}
                snapshot=json.loads(raw)
            except (OSError,ValueError):return {'ok':False,'error':{'code':'snapshot_read_error','message':'The verified snapshot could not be read.'}}
            return {'ok':True,'source':source.model_dump(mode='json'),'snapshot':snapshot}
        program=self.programs.get(args.program_id)
        if program is None:return {'ok':False,'error':{'code':'not_found','message':'No such program ID exists in the frozen catalog.'}}
        if name=='get_program':
            return {'ok':True,'program':program.model_dump(mode='json'),
                'sources':[source_metadata(s) for s in self.sources.values() if s.program_id==program.program_id]}
        if args.profile_version!=profile.profile_version:
            return {'ok':False,'error':{'code':'stale_profile','message':'Check request does not use the current profile version.'}}
        report=check_constraints(profile,program,self.sources,as_of=self.as_of)
        ids=sorted({sid for c in report.checks for sid in c.source_ids})
        return {'ok':True,'report':report.model_dump(mode='json'),'sources':[source_metadata(self.sources[s]) for s in ids]}
