"""Independently check queue membership and dispatch choices from clock event logs."""
import gzip,hashlib,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'revision_r6'
def audit(doc,rule,switch):
    queues=[list(q) for q in doc['events'][0]['queues']]
    status={v:'PENDING' for q in queues for v in q};ready=set();busy={};starts=0;applications=0
    for e in doc['events']:
        kind=e['kind'];v=e.get('task');j=e.get('node')
        if kind=='input_ready':ready.add(v)
        elif kind=='input_reset':ready.discard(v)
        elif kind=='cpu_start':
            assert j not in busy and v in queues[j]
            pending=[x for x in queues[j] if status[x]=='PENDING']
            permitted=next((x for x in pending if x in ready),None) if rule=='skip-unready' and e['time']>=switch else (pending[0] if pending else None)
            assert v==permitted and v in ready,(rule,e,permitted)
            busy[j]=v;status[v]='RUNNING';ready.remove(v);starts+=1
        elif kind=='cpu_done':
            assert busy.pop(j)==v;status[v]='DONE'
        elif kind=='cpu_abort':
            assert busy.pop(j)==v;status[v]='PENDING'
        elif kind=='plan_applied':
            queues=[list(q) for q in e['queues']]
            for node,task in busy.items():assert queues[node][0]==task
            assert len([x for q in queues for x in q])==len({x for q in queues for x in q})
            applications+=1
    assert all(x=='DONE' for x in status.values()) and not busy
    return {'dispatch_choices':starts,'plan_applications':applications}
def main():
    ledger=json.loads((BASE/'compact/manifest.json').read_text());starts=0;plans=0;runs=0
    for e in ledger['entries']:
        p=ROOT/e['event_path'];assert hashlib.sha256(p.read_bytes()).hexdigest()==e['event_sha256'];d=json.loads(gzip.decompress(p.read_bytes()))
        for collection in ['references','runs']:
            for key,value in d[collection].items():
                r=audit(value['clock'],key.split('/')[1],d['failure']['time']);starts+=r['dispatch_choices'];plans+=r['plan_applications'];runs+=1
    result={'status':'PASS','clock_executions':runs,'dispatch_choices_checked':starts,'plan_applications_checked':plans,'cases':len(ledger['entries']),'source_compact_manifest_sha256':hashlib.sha256((BASE/'compact/manifest.json').read_bytes()).hexdigest()}
    (BASE/'reports/dispatch_order_audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
if __name__=='__main__':main()
