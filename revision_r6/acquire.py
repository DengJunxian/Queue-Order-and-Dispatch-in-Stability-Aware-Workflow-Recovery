"""Select new source graphs using only preregistered structural criteria."""
import hashlib,json,sys,urllib.request
from pathlib import Path
import networkx as nx
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.validate_p0_data import validate_document,git_blob
OUT=ROOT/'revision_r6'
def dump(p,d):
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d,indent=2)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def graph(parsed):
    g=nx.DiGraph();g.add_nodes_from(t['id'] for t in parsed['tasks']);g.add_edges_from((e['source'],e['target']) for e in parsed['edges']);return g
def same(a,b):
    return len(a)==len(b) and a.number_of_edges()==b.number_of_edges() and nx.is_isomorphic(a,b)
def main():
    config=json.loads((OUT/'data/selection_protocol.json').read_text());receipt=json.loads((OUT/'reports/before_selection.json').read_text())
    assert sha(OUT/'data/selection_protocol.json')==receipt['selection_protocol_sha256']
    catalog=json.loads((OUT/'data/catalog.json').read_text());schema=json.loads((ROOT/'data/schema/wfcommons-schema.json').read_text())
    old=[]
    for path in ['data/manifest_v1.json','v2_preparation/data/manifest_v2.json']:
        for r in json.loads((ROOT/path).read_text())['records']:old.append(graph(json.loads((ROOT/r['parsed_path']).read_text())))
    records=[];profiles=[];audit=[];graphs=[]
    for family in catalog['families']:
        chosen=0
        for f in sorted((x for x in family['entries'] if x['name'].endswith('.json') and x['size']<=config['raw_size_limit_bytes']),key=lambda x:(x['size'],x['path'])):
            p=OUT/'data/raw'/f['path'];p.parent.mkdir(parents=True,exist_ok=True)
            if not p.exists():
                with urllib.request.urlopen(urllib.request.Request(f['download_url'],headers={'User-Agent':'CSCWD-research-reproducibility'}),timeout=90) as response:p.write_bytes(response.read())
            raw=p.read_bytes();assert git_blob(raw)==f['sha'] and len(raw)==f['size'],f['path']
            profile,issues,control,parsed=validate_document(json.loads(raw),schema);g=graph(parsed)
            reasons=[x['code'] for x in issues if x['severity']=='error']
            if not 20<=len(g)<=400:reasons.append('SIZE_OUTSIDE_20_400')
            if not profile['edge_bytes_sum']>0:reasons.append('NO_POSITIVE_COMMUNICATION')
            if any(same(g,x) for x in old):reasons.append('SEEN_OLD_TOPOLOGY')
            if any(same(g,x) for x in graphs):reasons.append('DUPLICATE_R6_TOPOLOGY')
            audit.append({'path':f['path'],'sha256':sha(p),'profile':profile,'issues':issues,'exclusion_reasons':reasons,'selected':not reasons})
            print(family['family'],f['name'],len(g),'selected' if not reasons else reasons,flush=True)
            if reasons:continue
            graphs.append(g);chosen+=1;gid=f'r6-{family["family"]}-{chosen:02d}'
            parsed.update({'source_sha256':sha(p),'source_revision':config['source_revision'],'topology_group':gid})
            dest=OUT/'data/processed'/f['name'];dump(dest,parsed)
            records.append({'id':p.stem,'family':family['family'],'source_url':f['html_url'],'git_blob_sha':f['sha'],'raw_path':str(p.relative_to(ROOT)),'parsed_path':str(dest.relative_to(ROOT)),'raw_sha256':sha(p),'parsed_sha256':sha(dest),'topology_group':gid,'tasks':len(g),'eligible':True,'split':'R6_STRUCTURAL_HOLDOUT'})
            profiles.append({'id':p.stem,'family':family['family'],'topology_group':gid,**profile})
            if chosen==3:break
        if chosen!=3:
            dump(OUT/'reports/acquisition_audit.json',audit);raise RuntimeError(f'Only {chosen} eligible topologies in {family["family"]}; protocol not changed')
    dump(OUT/'data/manifest.json',{'source_revision':config['source_revision'],'status':'VALIDATED_NOT_SCHEDULED','selection_protocol_sha256':receipt['selection_protocol_sha256'],'records':records})
    dump(OUT/'reports/data_profiles.json',profiles);dump(OUT/'reports/acquisition_audit.json',audit)
    dump(OUT/'reports/data_acceptance.json',{'status':'PASS','selected_graphs':len(records),'new_families':4,'all_nonisomorphic_to_prior_and_each_other':True,'fetched_and_validated_files':len(audit),'new_scheduling_runs':0,'manifest_sha256':sha(OUT/'data/manifest.json')})
if __name__=='__main__':main()
