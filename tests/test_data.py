import json
import math
from pathlib import Path
import pytest

from sail.data import Corpus, actual_work, bandwidth_for_ccr, failure_node, speed_vector, synthetic_workload
from sail.model import ModelError
from .helpers import graph

ROOT = Path(__file__).resolve().parents[1]
RECORDS = json.loads((ROOT/"data/manifest_v1.json").read_text())["records"]


@pytest.mark.parametrize("record",RECORDS,ids=[r["id"] for r in RECORDS])
def test_each_pinned_real_instance_adapts_without_execution(record):
    w = Corpus(ROOT).load(record["id"],"adapter_check")
    assert len(w.tasks)==record["tasks"] and w.pbar==pytest.approx(1)
    assert all(t.id.startswith("adapter_check::") and t.workflow=="adapter_check" for t in w.tasks)
    assert bandwidth_for_ccr(w,2)>0


def test_raw_runtime_scale_and_mean_normalization():
    corpus = Corpus(ROOT)
    raw = corpus.load(RECORDS[0]["id"],"w",normalize=False)
    normalized = corpus.load(RECORDS[0]["id"],"w")
    assert normalized.pbar==pytest.approx(1)
    assert all(a.work/b.work==pytest.approx(raw.pbar) for a,b in zip(raw.tasks,normalized.tasks))


def test_shared_corpus_namespaces_and_reserved_scale_holdout():
    corpus = Corpus(ROOT)
    for mix in ("A","B","C"):
        w = corpus.load_mix(mix,60000)
        assert len({t.id for t in w.tasks})==len(w.tasks)
        assert len({t.workflow for t in w.tasks})==3
        assert all(corpus.records[x]["split"]=="test_core" for x in corpus.mix_ids(mix,60000))
    used = {r for seed in range(60000,60030) for r in corpus.mix_ids("A",seed) if corpus.records[r]["family"]=="SRA Search"}
    assert len(used)==15


def test_corrupted_raw_file_rejected(tmp_path):
    manifest = json.loads((ROOT/"data/manifest_v1.json").read_text())
    manifest["records"] = [manifest["records"][0]]
    (tmp_path/"data").mkdir()
    (tmp_path/"data/manifest_v1.json").write_text(json.dumps(manifest))
    path = tmp_path/manifest["records"][0]["raw_path"]
    path.parent.mkdir(parents=True)
    path.write_text('{"corrupted":true}')
    with pytest.raises(ModelError,match="hash mismatch"):
        Corpus(tmp_path).load(manifest["records"][0]["id"],"w")


@pytest.mark.parametrize("mix",["A","B","C"])
def test_synthetic_generation_reproducible_and_independent(mix):
    w = synthetic_workload(10000,mix)
    assert w==synthetic_workload(10000,mix)
    assert w!=synthetic_workload(20000,mix)
    assert len(w.tasks)==192
    assert w.pbar==pytest.approx(1)


def test_synthetic_generator_rejects_real_test_seed_space():
    with pytest.raises(ModelError): synthetic_workload(60000,"A")


def test_random_fields_do_not_depend_on_call_order():
    before = speed_vector(10000,"A",8)
    w = synthetic_workload(10000,"A")
    actual_work(w,10000,"A",0.3)
    failure_node(10000,"A",4)
    assert before==speed_vector(10000,"A",8)
    small = speed_vector(10000,"A",4)
    assert all(small[i]/small[0]==pytest.approx(before[i]/before[0]) for i in range(4))
    assert sum(small)/4==pytest.approx(1)


def test_runtime_errors_share_Z_and_use_CV_zero_exactly():
    w = graph({"a":1,"b":2})
    a,b = actual_work(w,10000,"A",0.1),actual_work(w,10000,"A",0.3)
    for t in w.tasks:
        s1,s2 = math.sqrt(math.log1p(0.1**2)),math.sqrt(math.log1p(0.3**2))
        z1 = (math.log(a[t.id]/t.work)+s1*s1/2)/s1
        z2 = (math.log(b[t.id]/t.work)+s2*s2/2)/s2
        assert z1==pytest.approx(z2)
    assert actual_work(w,10000,"A",0)=={t.id:t.work for t in w.tasks}


def test_ccr_formula_with_hand_weights():
    w = graph({"a":1,"b":3},[("a","b",8)])
    assert bandwidth_for_ccr(w,2)==2
    with pytest.raises(ModelError): bandwidth_for_ccr(graph({"a":1}),0.5)
