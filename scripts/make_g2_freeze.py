"""Materialize frozen inputs and job identities without executing test schedules."""
import hashlib
import json
import sys
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sail.data import Corpus,actual_work,bandwidth_for_ccr,failure_node,speed_vector
from sail.development import dump,source_fingerprint
from sail.experiment import METHODS,method_aliases
from sail.frozen import verify_freeze


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_freeze():
    selection=json.loads((ROOT/"reports/p3/parameter_selection.json").read_text())
    profile=json.loads((ROOT/"reports/p3/profiling_summary.json").read_text())
    cfg=json.loads((ROOT/"configs/protocol_v1.json").read_text())
    choice=selection["selected"];n=profile["selected_test_seed_count"]
    if choice is None or n is None:raise ValueError("selection/profiling gate not satisfied")
    if source_fingerprint(ROOT)["sha256"]!=selection["source_fingerprint"]["sha256"]:raise ValueError("selection implementation changed")
    if not any(selection["development_coverage"][m]["effective_protected_nondegenerate"] for m in ("A","B","C")):
        raise ValueError("protection/scope mechanism is not observable in development")
    tests=json.loads((ROOT/"reports/p3/test_summary.json").read_text())
    if tests["failed"] or tests["skipped"]:raise ValueError("correctness gate not passed")
    folder=ROOT/"freeze/g2_v1_20261025"
    if (folder/"freeze.json").exists():
        verify_freeze(ROOT,folder);return json.loads((folder/"freeze.json").read_text())
    corpus=Corpus(ROOT);bases=[];scenarios=[];jobs=[];workloads={}
    for seed in range(60000,60000+n):
        for mix in ("A","B","C"):
            w=corpus.load_mix(mix,seed);wid=f"{seed}-{mix}"
            workload_file=f"public/workloads/{wid}.json";dump(folder/workload_file,w);workloads[seed,mix]=(w,workload_file)
    def base(seed,mix,nodes,ccr,cv):
        w,wfile=workloads[seed,mix]
        bid=f"{seed}-{mix}-n{nodes}-ccr{ccr}-cv{cv}"
        truth_file=f"evaluator/{seed}-{mix}-cv{cv}.json"
        if not (folder/truth_file).exists():dump(folder/truth_file,actual_work(w,seed,mix,cv))
        b={"id":bid,"root_seed":seed,"mix":mix,"nodes":nodes,"ccr":ccr,"runtime_cv":cv,"workload_file":wfile,
           "truth_file":truth_file,"speeds":speed_vector(seed,mix,nodes),"bandwidth":bandwidth_for_ccr(w,ccr)}
        bases.append(b);jobs.append({"id":"ref-"+bid,"kind":"reference","base_id":bid});return bid
    main_bases={}
    for seed in range(60000,60000+n):
        for mix in ("A","B","C"):
            for nodes in (4,8):
                for ccr in (0.5,2):main_bases[seed,mix,nodes,ccr]=base(seed,mix,nodes,ccr,0)
    def scenario(bid,seed,mix,nodes,ccr,fraction,delay,variant,methods):
        sid=f"{seed}-{mix}-n{nodes}-ccr{ccr}-f{fraction}-{variant}"
        scenarios.append({"id":sid,"base_id":bid,"root_seed":seed,"mix":mix,"nodes":nodes,"ccr":ccr,"failure_fraction":fraction,
                          "failed_node":failure_node(seed,mix,nodes),"control_delay_pbar_units":delay,"variant":variant,
                          "fault_time_numeric":None,"fault_time_rule":"failure_fraction * matched actual no-fault makespan, evaluator computed after G2"})
        return [{"id":f"run-{sid}-{method}","kind":"failure","scenario_id":sid,"base_id":bid,"method":method} for method in methods]
    failure_jobs=[]
    for (seed,mix,nodes,ccr),bid in main_bases.items():
        for fraction in (0.3,0.6):failure_jobs.extend(scenario(bid,seed,mix,nodes,ccr,fraction,0,"main",METHODS))
    for seed in range(60000,60010):
        for mix in ("A","B","C"):
            for ccr in (0.5,2):
                for cv in (0.1,0.3):
                    bid=base(seed,mix,4,ccr,cv)
                    failure_jobs.extend(scenario(bid,seed,mix,4,ccr,0.6,0,f"cv{cv}",METHODS[:4]))
                failure_jobs.extend(scenario(main_bases[seed,mix,4,ccr],seed,mix,4,ccr,0.6,0.1,"control_delay",METHODS[:4]))
    jobs.extend(failure_jobs)
    assert len(jobs)==(6960 if n==30 else 2880)
    dump(folder/"scenario_manifest.json",{"bases":bases,"scenarios":scenarios,"jobs":jobs})
    dump(folder/"parameter_selection.json",selection)
    dump(folder/"profiling_summary.json",profile)
    source_paths=sorted(list((ROOT/"sail").glob("*.py"))+list((ROOT/"scripts").glob("*p3*.py"))+
                        [ROOT/"scripts/run_frozen_experiments.py",ROOT/"scripts/analyze_frozen_experiments.py",ROOT/"scripts/make_g2_freeze.py",ROOT/"requirements-p3.txt",ROOT/"configs/p3_execution_spec.json",
                         ROOT/"docs/protocol_v1.md",ROOT/"configs/protocol_v1.json",ROOT/"data/manifest_v1.json",ROOT/"tests/conftest.py",
                         ROOT/"reports/p3/parameter_selection.json",ROOT/"reports/p3/selection_source_manifest.json",ROOT/"reports/p3/profiling_summary.json"]+
                        list((ROOT/"tests").glob("*.py")))
    config={"status":"FROZEN_G2","purpose":"FORMAL_MAIN","version":"g2_v1_20261025","created_at":datetime.now(timezone.utc).isoformat(),
            "selected_lambda":choice["lambda"],"selected_mu":choice["mu"],"root_seeds":list(range(60000,60000+n)),"methods":METHODS,
            "method_aliases":method_aliases(choice["lambda"],choice["mu"]),"nominal_jobs":len(jobs),"reference_jobs":len(bases),"failure_scenarios":len(scenarios),
            "statistical_rule":{"cluster":"root_seed, shared across all mixes and axes","repetitions":5000,"seed":73000,
                                "CI":"percentile two-sided95%; one-sided upper95% for AWCT budget","primary_comparator":"B2",
                                "mechanism_comparators":["NoStability","NoChurn","B0","Fixed_H1","Fixed_H2"],
                                "NA":"undefined if any mix has no applicable cell; no CI unless all draws defined"},
            "candidate_coverage_note":"73.75% single-plan development cases retained; all three mixes include effective protected nondegenerate cases",
            "mu_zero_note":"NoChurn is a configuration alias; no independent churn-effect claim",
            "protocol_sha256":cfg["protocol_sha256"],"manifest_sha256":cfg["data_manifest_sha256"],"formal_runs_completed":0,
            "code_files":[{"path":str(p.relative_to(ROOT)),"sha256":sha(p)} for p in source_paths]}
    dump(folder/"test_summary.json",tests)
    dump(folder/"freeze.json",config)
    paths=sorted(p for p in folder.rglob("*") if p.is_file() and p.name!="inputs_manifest.json")
    dump(folder/"inputs_manifest.json",{"files":[{"path":str(p.relative_to(folder)),"sha256":sha(p)} for p in paths]})
    verify_freeze(ROOT,folder)
    return config


if __name__=="__main__":
    result=build_freeze();print(json.dumps({"status":result["status"],"nominal_jobs":result["nominal_jobs"],"root_seeds":len(result["root_seeds"]),"formal_runs_completed":0}))
