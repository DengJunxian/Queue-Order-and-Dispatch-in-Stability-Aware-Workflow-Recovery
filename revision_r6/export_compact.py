"""Export replayable inputs, plan/clock outcomes and forecasts without event logs."""
import gzip,hashlib,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'revision_r6'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    out=BASE/'compact';out.mkdir(exist_ok=True);ledger=[]
    for stage in ['holdout','measured/calibration','measured/evaluation']:
        for receipt in sorted((BASE/stage/'cases').glob('*.json')):
            r=json.loads(receipt.read_text());source=ROOT/r['event_file']
            assert digest(source)==r['event_sha256']
            d=json.loads(gzip.decompress(source.read_bytes()))
            for collection in ['references','runs']:
                d[collection]={k:{'clock':{f:v for f,v in b['clock'].items() if f!='events'}} for k,b in d[collection].items()}
            for c in d.get('calibration_candidates',[]):c.pop('continuation')
            d['source_event_sha256']=r['event_sha256'];d['case_id']=r['case_id'];d['stage']=stage
            destination=out/(stage.replace('/','_')+'__'+r['case_id']+'.json.gz')
            destination.write_bytes(gzip.compress(json.dumps(d,separators=(',',':'),allow_nan=False).encode(),mtime=0))
            ledger.append({'case_id':r['case_id'],'stage':stage,'event_path':r['event_file'],'event_sha256':r['event_sha256'],'compact_path':str(destination.relative_to(ROOT)),'compact_sha256':digest(destination)})
    assert len(ledger)==228
    (out/'manifest.json').write_text(json.dumps({'cases':len(ledger),'event_logs_included':False,'source_event_hashes_verified':True,'entries':ledger},indent=2)+'\n')
    print('Exported',len(ledger),'hash-bound replay cases')
if __name__=='__main__':main()
