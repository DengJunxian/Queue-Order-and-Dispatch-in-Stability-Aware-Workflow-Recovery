"""Pinned data adaptation and protocol v1 random fields, without execution."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np

from .model import DataFile, ModelError, Platform, Task, Workload, positive


def random_stream(root_seed, mix, stream, stable_id):
    if stream not in {"platform", "failure", "runtime", "synthetic"}:
        raise ModelError("unknown protocol random stream")
    key = f"protocol_v1|{root_seed}|{mix}|{stream}|{stable_id}"
    seed = int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:16], "little")
    return np.random.Generator(np.random.PCG64(seed))


def speed_vector(root_seed, mix, nodes):
    if nodes not in (4, 8):
        raise ModelError("protocol scenario platform requires 4 or 8 nodes")
    speed = random_stream(root_seed, mix, "platform", "speeds").uniform(0.5, 1.5, 8)[:nodes]
    return tuple(float(x) for x in speed / speed.mean())


def failure_node(root_seed, mix, nodes):
    if nodes not in (4, 8):
        raise ModelError("protocol scenario platform requires 4 or 8 nodes")
    return int(random_stream(root_seed, mix, "failure", "node").integers(0, nodes))


def actual_work(workload, root_seed, mix, cv):
    if not math.isfinite(cv) or cv < 0:
        raise ModelError("CV must be finite and nonnegative")
    sigma = math.sqrt(math.log1p(cv * cv))
    return {t.id: t.work * math.exp(sigma * float(random_stream(root_seed, mix, "runtime", t.id).normal()) - sigma*sigma/2)
            for t in workload.tasks}


def bandwidth_for_ccr(workload, ccr):
    positive(ccr, "CCR")
    files = workload.file_map
    edge_bytes = [sum(files[f].size for f in t.inputs if files[f].producer == p)
                  for t in workload.tasks for p in t.parents]
    if not edge_bytes or sum(edge_bytes) == 0:
        raise ModelError("positive CCR undefined for graph with no positive communication; set fixture bandwidth explicitly")
    return (sum(edge_bytes) / len(edge_bytes)) / (ccr * workload.pbar)


class Corpus:
    def __init__(self, root):
        self.root = Path(root)
        self.manifest = json.loads((self.root / "data/manifest_v1.json").read_text())
        self.records = {r["id"]: r for r in self.manifest["records"]}
        if len(self.records) != len(self.manifest["records"]):
            raise ModelError("duplicate corpus ID")

    def load(self, record_id, workflow_id, *, normalize=True):
        record = self.records[record_id]
        if not record["eligible"]:
            raise ModelError("ineligible input")
        for path_key, hash_key in [("raw_path", "raw_sha256"), ("parsed_path", "parsed_sha256")]:
            if hashlib.sha256((self.root / record[path_key]).read_bytes()).hexdigest() != record[hash_key]:
                raise ModelError(f"corpus hash mismatch: {record_id}/{path_key}")
        doc = json.loads((self.root / record["parsed_path"]).read_text())
        if doc["source_sha256"] != record["raw_sha256"] or doc["source_revision"] != self.manifest["source_revision"]:
            raise ModelError("parsed provenance mismatch")
        prefix = workflow_id + "::"
        parents = {t["id"]: [] for t in doc["tasks"]}
        inputs = {tid: [] for tid in parents}
        for e in doc["edges"]:
            parents[e["target"]].append(prefix + e["source"])
        files = []
        for f in doc["files"]:
            if len(f["producers"]) > 1:
                raise ModelError("ambiguous producer")
            files.append(DataFile(prefix+f["id"], f["bytes"], prefix+f["producers"][0] if f["producers"] else None))
            for consumer in f["consumers"]:
                inputs[consumer].append(prefix+f["id"])
        scale = sum(t["runtime_seconds"] for t in doc["tasks"]) / len(doc["tasks"]) if normalize else 1.0
        tasks = tuple(Task(prefix+t["id"], workflow_id, t["runtime_seconds"]/scale,
                           tuple(sorted(parents[t["id"]])), tuple(sorted(inputs[t["id"]]))) for t in doc["tasks"])
        return Workload(tasks, tuple(files))

    def mix_ids(self, mix, root_seed):
        families = {"A": ["Montage", "Epigenomics", "SRA Search"],
                    "B": ["Montage", "Montage", "Epigenomics"],
                    "C": ["Epigenomics", "SRA Search", "SRA Search"]}[mix]
        if root_seed not in range(60000, 60030):
            raise ModelError("real test mix identity requires a planned test root seed")
        i, count, selected = root_seed-60000, {}, []
        for family in families:
            q = count.get(family, 0)
            count[family] = q+1
            pool = sorted((r for r in self.records.values() if r["family"] == family and r["split"] == "test_core"), key=lambda r:r["id"])
            if family == "SRA Search":
                size = (42, 64, 84)[(i+q) % 3]
                pool = [r for r in pool if r["tasks"] == size]
                chosen = pool[(i//3+q) % 5]
            else:
                chosen = pool[(i+q) % 2]
            selected.append(chosen["id"])
        return tuple(selected)

    def load_mix(self, mix, root_seed):
        pieces = [self.load(record, f"w{j:02d}") for j, record in enumerate(self.mix_ids(mix, root_seed))]
        return Workload(tuple(t for w in pieces for t in w.tasks), tuple(f for w in pieces for f in w.files))


def synthetic_workload(root_seed, mix):
    if root_seed in range(10000,10020):
        i = root_seed-10000
    elif root_seed in range(20000,20010):
        i = root_seed-20000
    else:
        raise ModelError("synthetic generator accepts only protocol development/validation seeds")
    kinds = {"A": "LRF", "B": "LLR", "C": "RFF"}[mix]
    tasks, files = [], []
    for q, kind in enumerate(kinds):
        n, wid = (48,64,80)[(i+q) % 3], f"w{q:02d}"
        rng = random_stream(root_seed, mix, "synthetic", wid)
        if kind == "L":
            edges = {(j,j+1) for j in range(n-1)}
        elif kind == "F":
            edges = {(0,j) for j in range(1,n-1)} | {(j,n-1) for j in range(1,n-1)}
        else:
            layers = [list(range(layer,n,8)) for layer in range(8)]
            edges = {(u,v) for a,b in zip(layers,layers[1:]) for u in a for v in b if rng.random()<0.25}
            for v in range(n):
                layer = v % 8
                if layer>0 and not any(b==v for a,b in edges):
                    edges.add((int(rng.choice(layers[layer-1])),v))
                if layer<7 and not any(a==v for a,b in edges):
                    edges.add((v,int(rng.choice(layers[layer+1]))))
        work = rng.lognormal(0,0.8,n)
        work /= work.mean()
        parents, inputs = {j:[] for j in range(n)}, {j:[] for j in range(n)}
        ids = [f"{wid}::t{j:04d}" for j in range(n)]
        for u,v in sorted(edges):
            fid = f"{wid}::f{u:04d}_{v:04d}"
            files.append(DataFile(fid,float(rng.lognormal(0,1)),ids[u]))
            parents[v].append(ids[u]); inputs[v].append(fid)
        tasks.extend(Task(ids[j],wid,float(work[j]),tuple(sorted(parents[j])),tuple(sorted(inputs[j]))) for j in range(n))
    return Workload(tuple(tasks),tuple(files))
