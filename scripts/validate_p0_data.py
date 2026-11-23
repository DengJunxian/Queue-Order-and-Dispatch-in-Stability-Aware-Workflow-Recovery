"""Read-only validation and deterministic extraction of the pinned WfInstances corpus.

Run from the repository root: python scripts/validate_p0_data.py
No scheduler, failure injection, parameter search, or performance experiment runs here.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import platform
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import networkx as nx

ROOT = Path(__file__).resolve().parents[1]


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def git_blob(data):
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def validate_document(doc, schema=None):
    issues = []

    def add(severity, code, detail):
        issues.append({"severity": severity, "code": code, "detail": detail})

    if schema is not None:
        validator = jsonschema.validators.validator_for(schema)(schema)
        for error in validator.iter_errors(doc):
            add("error", "SCHEMA", f"{list(error.path)}: {error.message}")
    workflow = doc.get("workflow", {})
    spec = workflow.get("specification", {})
    execution = workflow.get("execution", {})
    tasks, files, runs = spec.get("tasks", []), spec.get("files", []), execution.get("tasks", [])
    for kind, rows in [("task", tasks), ("file", files), ("execution", runs)]:
        ids = [x.get("id") for x in rows]
        if len(ids) != len(set(ids)):
            add("error", "DUPLICATE_ID", kind)
    task_map = {t.get("id"): t for t in tasks}
    file_map = {f.get("id"): f for f in files}
    run_map = {t.get("id"): t for t in runs}
    if not task_map:
        add("error", "EMPTY_DAG", "no tasks")
    if set(task_map) != set(run_map):
        add("error", "EXECUTION_ID_MISMATCH", str(sorted(set(task_map) ^ set(run_map))))
    graph = nx.DiGraph()
    graph.add_nodes_from(task_map)
    producer, consumer = defaultdict(list), defaultdict(list)
    runtimes = []
    machine_ids = {m.get("nodeName") for m in execution.get("machines", [])}
    for tid, task in task_map.items():
        for field in ["parents", "children", "inputFiles", "outputFiles"]:
            values = task.get(field, [])
            if len(values) != len(set(values)):
                add("error", "DUPLICATE_REFERENCE", f"{tid}/{field}")
        for parent in task.get("parents", []):
            if parent not in task_map:
                add("error", "MISSING_TASK_REFERENCE", f"{parent}->{tid}")
            else:
                graph.add_edge(parent, tid)
                if tid not in task_map[parent].get("children", []):
                    add("error", "ASYMMETRIC_EDGE", f"{parent}->{tid}")
        for child in task.get("children", []):
            if child not in task_map:
                add("error", "MISSING_TASK_REFERENCE", f"{tid}->{child}")
            elif tid not in task_map[child].get("parents", []):
                add("error", "ASYMMETRIC_EDGE", f"{tid}->{child}")
        for field, relation in [("inputFiles", consumer), ("outputFiles", producer)]:
            for fid in task.get(field, []):
                relation[fid].append(tid)
                if fid not in file_map:
                    add("error", "MISSING_FILE_REFERENCE", f"{tid}/{fid}")
        runtime = run_map.get(tid, {}).get("runtimeInSeconds")
        if isinstance(runtime, bool) or not isinstance(runtime, (int, float)) or not math.isfinite(runtime) or runtime <= 0:
            add("error", "INVALID_RUNTIME", f"{tid}: {runtime}")
        else:
            runtimes.append(float(runtime))
        for machine in run_map.get(tid, {}).get("machines", []):
            if machine not in machine_ids:
                add("error", "MISSING_MACHINE_REFERENCE", f"{tid}/{machine}")
    is_dag = nx.is_directed_acyclic_graph(graph)
    if not is_dag:
        add("error", "CYCLE", str(nx.find_cycle(graph)))
    for fid, file in file_map.items():
        size = file.get("sizeInBytes")
        if isinstance(size, bool) or not isinstance(size, (int, float)) or not math.isfinite(size) or size < 0 or size != int(size):
            add("error", "INVALID_FILE_SIZE", f"{fid}: {size}")
        if len(producer[fid]) > 1:
            add("error", "AMBIGUOUS_PRODUCER", f"{fid}: {producer[fid]}")
    indirect_dependencies = []
    if is_dag:
        for fid, producers in producer.items():
            for u in producers:
                for v in consumer[fid]:
                    if u == v or not nx.has_path(graph, u, v):
                        add("error", "FILE_DEPENDENCY_MISSING", f"{u}->{v}/{fid}")
                    elif not graph.has_edge(u, v):
                        indirect_dependencies.append({"source": u, "target": v, "file": fid})
    if indirect_dependencies:
        add("warning", "INDIRECT_FILE_DEPENDENCY", f"{len(indirect_dependencies)} producer-consumer pairs require explicit data edges")
    canonical_date = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
    for field, value in [("createdAt", doc.get("createdAt")), ("executedAt", execution.get("executedAt"))]:
        if value and not canonical_date.fullmatch(str(value)):
            add("warning", "NONCANONICAL_TIMESTAMP", f"{field}: {value}")
    # Enrich dependencies with all producer-consumer edges, retaining original control edges.
    data_graph = graph.copy()
    for item in indirect_dependencies:
        data_graph.add_edge(item["source"], item["target"])
    edges = []
    for u, v in sorted(data_graph.edges):
        shared = sorted(set(task_map[u].get("outputFiles", [])) & set(task_map[v].get("inputFiles", [])))
        edges.append({"source": u, "target": v, "file_ids": shared,
                      "bytes": sum(file_map.get(f, {}).get("sizeInBytes", 0) or 0 for f in shared),
                      "original_dependency": graph.has_edge(u, v)})
    levels = list(nx.topological_generations(graph)) if is_dag else []
    cp = {}
    if is_dag and len(runtimes) == len(task_map):
        for v in nx.topological_sort(graph):
            cp[v] = run_map[v]["runtimeInSeconds"] + max((cp[u] for u in graph.predecessors(v)), default=0)
    profile = {
        "tasks": len(tasks), "edges": graph.number_of_edges(), "files": len(files),
        "execution_rows": len(runs), "is_dag": is_dag,
        "roots": sum(graph.in_degree(v) == 0 for v in graph),
        "sinks": sum(graph.out_degree(v) == 0 for v in graph),
        "levels": len(levels), "max_level_width": max(map(len, levels), default=0),
        "runtime_min_s": min(runtimes, default=None),
        "runtime_median_s": statistics.median(runtimes) if runtimes else None,
        "runtime_max_s": max(runtimes, default=None),
        "runtime_sum_s": sum(runtimes),
        "runtime_cv": statistics.pstdev(runtimes) / statistics.mean(runtimes) if runtimes else None,
        "critical_path_runtime_s": max(cp.values(), default=None),
        "external_input_files": sum(bool(consumer[f]) and not producer[f] for f in file_map),
        "terminal_output_files": sum(bool(producer[f]) and not consumer[f] for f in file_map),
        "unreferenced_files": sum(not producer[f] and not consumer[f] for f in file_map),
        "zero_byte_files": sum(f.get("sizeInBytes") == 0 for f in files),
        "control_only_edges": sum(not e["file_ids"] for e in edges),
        "data_edges_added": len(indirect_dependencies),
        "edge_bytes_sum": sum(e["bytes"] for e in edges),
        "file_bytes_sum": sum(f.get("sizeInBytes", 0) or 0 for f in files),
        "error_count": sum(i["severity"] == "error" for i in issues),
        "warning_count": sum(i["severity"] == "warning" for i in issues),
    }
    parsed = {"tasks": [{"id": tid, "name": task_map[tid].get("name"),
                         "runtime_seconds": run_map.get(tid, {}).get("runtimeInSeconds")}
                        for tid in sorted(task_map)], "edges": edges,
              "files": [{"id": fid, "bytes": file_map[fid].get("sizeInBytes"),
                         "producers": producer[fid], "consumers": consumer[fid]}
                        for fid in sorted(file_map)]}
    return profile, issues, graph, parsed


def main():
    acquisition = json.loads((ROOT / "data/acquisition_manifest.json").read_text())
    schema = json.loads((ROOT / "data/schema/wfcommons-schema.json").read_text())
    reports = ROOT / "reports/p0"
    reports.mkdir(parents=True, exist_ok=True)
    profiles, all_issues, records, groups, seen_hashes = [], [], [], [], defaultdict(list)
    for record in sorted(acquisition["records"], key=lambda x: x["path"]):
        path = ROOT / "data/raw/wfinstances" / record["path"]
        raw = path.read_bytes()
        assert git_blob(raw) == record["git_blob_sha"], f"source byte mismatch: {path}"
        assert sha256(raw) == record["sha256"], f"source hash mismatch: {path}"
        doc = json.loads(raw)
        profile, issues, graph, parsed = validate_document(doc, schema)
        # Exact directed isomorphism ignores names/weights; hash alone is not used as proof.
        group_id = None
        for gid, family, representative in groups:
            if family == record["family"] and nx.is_isomorphic(graph, representative):
                group_id = gid
                break
        if group_id is None:
            group_id = f"topology-{len(groups) + 1:02d}"
            groups.append((group_id, record["family"], graph))
        profile = {"file": path.name, "family": record["family"], "topology_group": group_id, **profile}
        profiles.append(profile)
        all_issues.extend({"file": path.name, **i} for i in issues)
        parsed.update({"source_sha256": sha256(raw), "source_revision": acquisition["revision"],
                       "topology_group": group_id, "schema_version": doc.get("schemaVersion")})
        parsed_rel = "data/processed/" + path.name
        write_json(ROOT / parsed_rel, parsed)
        split = "test_core" if 40 <= profile["tasks"] <= 90 else "test_scale_holdout"
        records.append({"id": path.stem, "family": record["family"], "raw_path": str(path.relative_to(ROOT)),
                        "parsed_path": parsed_rel, "source_url": record["url"],
                        "raw_sha256": sha256(raw), "parsed_sha256": sha256((ROOT / parsed_rel).read_bytes()),
                        "git_blob_sha": record["git_blob_sha"], "topology_group": group_id,
                        "tasks": profile["tasks"], "split": split, "eligible": profile["error_count"] == 0})
        seen_hashes[sha256(raw)].append(path.name)
    with (reports / "data_profiles.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(profiles[0]))
        writer.writeheader()
        writer.writerows(profiles)
    summary = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(), "networkx": nx.__version__, "jsonschema": __import__('importlib.metadata', fromlist=['version']).version('jsonschema'),
        "source_revision": acquisition["revision"], "files": len(profiles),
        "valid_files": sum(p["error_count"] == 0 for p in profiles),
        "total_tasks": sum(p["tasks"] for p in profiles), "total_edges": sum(p["edges"] for p in profiles),
        "total_files": sum(p["files"] for p in profiles),
        "distinct_family_topologies": len(groups),
        "exact_duplicate_groups": [v for v in seen_hashes.values() if len(v) > 1],
        "errors": sum(p["error_count"] for p in profiles), "warnings": sum(p["warning_count"] for p in profiles),
        "issue_code_counts": dict(Counter(i["code"] for i in all_issues)),
        "split_counts": dict(Counter(r["split"] for r in records)),
        "family_counts": dict(Counter(r["family"] for r in records)),
        "zero_byte_files": sum(p["zero_byte_files"] for p in profiles),
        "control_only_edges": sum(p["control_only_edges"] for p in profiles),
        "data_edges_added": sum(p["data_edges_added"] for p in profiles),
        "runtime_min_s": min(p["runtime_min_s"] for p in profiles),
        "runtime_max_s": max(p["runtime_max_s"] for p in profiles),
        "audit_script_sha256": sha256(Path(__file__).read_bytes()),
    }
    write_json(reports / "data_summary.json", summary)
    write_json(reports / "data_issues.json", all_issues)
    write_json(ROOT / "data/manifest_v1.json", {
        "version": 1, "status": "DATA_VALIDATED_DESIGN_SPLIT_FINAL",
        "source_revision": acquisition["revision"], "schema_revision": acquisition["schema_revision"],
        "split_policy": "All real instances are test-only. Independent synthetic development and validation graphs; no real test outcomes used for tuning.",
        "independent_population_claim": "Fixed benchmark corpus; repeated execution logs are not independent workflow topologies.",
        "records": records,
    })
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return int(summary["errors"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
