"""Validate source bytes and unseen topology groups without running schedules."""
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import networkx as nx

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sail.development import dump
from scripts.validate_p0_data import validate_document,git_blob
from v2_preparation.adapters import CorpusV2


def main():
    folder=ROOT/'v2_preparation';data=folder/'data';reports=folder/'reports'
    selected=json.loads((data/'selection_before_outcomes.json').read_text())['files']
    old=json.loads((ROOT/'data/manifest_v1.json').read_text());schema=json.loads((ROOT/'data/schema/wfcommons-schema.json').read_text())
    revision=old['source_revision'];old_graphs=[]
    for r in old['records']:
        parsed=json.loads((ROOT/r['parsed_path']).read_text());g=nx.DiGraph();g.add_nodes_from(t['id'] for t in parsed['tasks']);g.add_edges_from((e['source'],e['target']) for e in parsed['edges']);old_graphs.append(g)
    records=[];profiles=[];allissues=[];graphs=[]
    for f in selected:
        path=data/'raw'/f['path'];raw=path.read_bytes();assert git_blob(raw)==f['sha'] and len(raw)==f['size']
        profile,issues,control,parsed=validate_document(json.loads(raw),schema)
        executed=nx.DiGraph();executed.add_nodes_from(t['id'] for t in parsed['tasks']);executed.add_edges_from((e['source'],e['target']) for e in parsed['edges'])
        overlaps=[i for i,g in enumerate(old_graphs) if nx.is_isomorphic(g,executed) or nx.is_isomorphic(g,control)]
        if overlaps:issues.append({'severity':'error','code':'SEEN_TOPOLOGY','detail':str(overlaps)})
        if any(nx.is_isomorphic(g,executed) for g in graphs):issues.append({'severity':'error','code':'DUPLICATE_NEW_TOPOLOGY','detail':f['path']})
        graphs.append(executed);gid=f'v2-unseen-{len(graphs):02d}';sha=hashlib.sha256(raw).hexdigest()
        parsed.update({'source_sha256':sha,'source_revision':revision,'topology_group':gid,'schema_version':json.loads(raw).get('schemaVersion')})
        parsed_path=data/'processed'/f['name'];dump(parsed_path,parsed)
        error_count=sum(x['severity']=='error' for x in issues)
        records.append({'id':Path(f['name']).stem,'family':f['family'],'source_url':f['html_url'],'git_blob_sha':f['sha'],
                        'raw_path':str(path.relative_to(ROOT)),'parsed_path':str(parsed_path.relative_to(ROOT)),
                        'raw_sha256':sha,'parsed_sha256':hashlib.sha256(parsed_path.read_bytes()).hexdigest(),
                        'topology_group':gid,'tasks':profile['tasks'],'split':'v2_test_unseen','eligible':error_count==0})
        profiles.append({'id':Path(f['name']).stem,'family':f['family'],'topology_group':gid,**profile,'new_error_count':error_count,'seen_topology_matches':overlaps})
        allissues.extend({'file':f['name'],**x} for x in issues)
    manifest={'version':'v2_unseen_inputs_20261025','source_revision':revision,'schema_revision':old['schema_revision'],
              'status':'INPUTS_VALIDATED_NOT_RUN','split_policy':'all six unseen topology groups are test-only; no scheduling outcomes used in acquisition or eligibility',
              'records':records,'independent_population_claim':'fixed unseen benchmark; environment roots do not create independent topologies'}
    dump(data/'manifest_v2.json',manifest)
    corpus=CorpusV2(ROOT)
    for r in records:
        if r['eligible']:
            w=corpus.load(r['id'],'check');assert len(w.tasks)==r['tasks'] and abs(w.pbar-1)<1e-12
    sizes={}
    for mix in 'ABC':
        for seed in range(81000,81008):sizes[f'{mix}-{seed}']=sum(corpus.records[i]['tasks'] for i in corpus.mix_ids(mix,seed))
    summary={'status':'PASS' if all(r['eligible'] for r in records) else 'FAIL','raw_files':len(records),'eligible':sum(r['eligible'] for r in records),
             'unseen_topology_groups':len(graphs),'families':dict(Counter(r['family'] for r in records)),
             'total_tasks':sum(r['tasks'] for r in records),'task_counts':{r['id']:r['tasks'] for r in records},'possible_mix_sizes':sizes,
             'max_new_mix_tasks':max(sizes.values()),'errors':sum(x['severity']=='error' for x in allissues),'warnings':sum(x['severity']=='warning' for x in allissues),
             'issue_codes':dict(Counter(x['code'] for x in allissues)),'new_test_scheduling_runs':0,'original_scale_holdout_used':False}
    dump(reports/'new_data_summary.json',summary);dump(reports/'new_data_profiles.json',profiles);dump(reports/'new_data_issues.json',allissues)
    print(json.dumps(summary,ensure_ascii=False))
    if summary['status']!='PASS':raise ValueError('new inputs failed validation; preserve originals and inspect before freezing')


if __name__=='__main__':main()
