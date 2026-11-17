"""Per-run trace/span recorder; stores observable decisions, never hidden reasoning."""
from copy import deepcopy
from datetime import datetime, timezone
from time import monotonic
from uuid import uuid4


def timestamp():return datetime.now(timezone.utc).isoformat()


class Trace:
    def __init__(self):
        self.trace_id=str(uuid4())
        self.spans=[]

    def start(self,kind,name,parent_id=None,inputs=None,selected_by=None):
        span={"span_id":str(uuid4()),"parent_id":parent_id,"kind":kind,"name":name,
            "started_at":timestamp(),"finished_at":None,"duration_ms":None,
            "inputs":deepcopy(inputs),"outputs":None,"status":"running","error":None,
            "selected_by":selected_by,"_started":monotonic()}
        self.spans.append(span)
        return span

    def finish(self,span,outputs=None,error=None,status=None):
        span.update(outputs=deepcopy(outputs),error=deepcopy(error),
            status=status or ("error" if error else "completed"),finished_at=timestamp(),
            duration_ms=round((monotonic()-span["_started"])*1000,3))

    def export(self):
        return {"trace_id":self.trace_id,"spans":[{k:deepcopy(v) for k,v in s.items() if not k.startswith('_')} for s in self.spans]}
