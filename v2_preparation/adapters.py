"""v2 manifest adapter, using the frozen per-workflow normalization unchanged."""
import json
from pathlib import Path

from sail.data import Corpus
from sail.model import ModelError,Workload


class CorpusV2(Corpus):
    def __init__(self,root):
        self.root=Path(root);self.manifest=json.loads((self.root/'v2_preparation/data/manifest_v2.json').read_text())
        self.records={r['id']:r for r in self.manifest['records']}
        if len(self.records)!=len(self.manifest['records']):raise ModelError('duplicate v2 corpus id')

    def mix_ids(self,mix,root_seed):
        if root_seed not in range(81000,81060):raise ModelError('v2 test seed outside proposed namespace')
        families={'A':['Montage','Epigenomics','SRA Search'],'B':['Montage','Montage','Epigenomics'],'C':['Epigenomics','SRA Search','SRA Search']}[mix]
        seen={};selected=[];i=root_seed-81000
        for family in families:
            q=seen.get(family,0);seen[family]=q+1
            pool=sorted((r for r in self.records.values() if r['family']==family and r['eligible']),key=lambda r:r['id'])
            if len(pool)!=2:raise ModelError('v2 requires two verified unseen topology groups per family')
            stride={'Montage':1,'Epigenomics':2,'SRA Search':4}[family]
            selected.append(pool[(i//stride+q)%2]['id'])
        return tuple(selected)

    def load_mix(self,mix,root_seed):
        pieces=[self.load(identity,f'w{j:02d}') for j,identity in enumerate(self.mix_ids(mix,root_seed))]
        return Workload(tuple(t for w in pieces for t in w.tasks),tuple(f for w in pieces for f in w.files))
