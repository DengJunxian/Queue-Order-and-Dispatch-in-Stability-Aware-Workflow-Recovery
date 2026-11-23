"""Measure end-to-end validation execution cost on 20 declared development cases."""
import json
import shutil
import sys
from pathlib import Path
from time import perf_counter
import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sail.audit import audit_result
from sail.data import actual_work,bandwidth_for_ccr,failure_node,speed_vector,synthetic_workload
from sail.development import dump
from sail.experiment import METHODS,run_methods
from sail.model import Failure,Platform
from sail.scheduling import initial_heft
from sail.simulator import Simulator


def main():
    chosen=json.loads((ROOT/"reports/p3/parameter_selection.json").read_text())["selected"]
    if chosen is None:raise ValueError("no selected parameter; profiling cannot supply a freeze decision")
    measurements=[]
    for i,seed in enumerate(range(10000,10020)):
        mix=("A","B","C")[i%3];nodes=8 if i%2==0 else 4;cv=(0,0.1,0.3)[i%3];fraction=(0.3,0.6)[i%2]
        w=synthetic_workload(seed,mix);p=Platform(speed_vector(seed,mix,nodes),bandwidth_for_ccr(w,2))
        truth=actual_work(w,seed,mix,cv)
        out=ROOT/f"reports/p3/profiling/events/{seed}-{mix}-{nodes}"
        begin=perf_counter();initial=initial_heft(w,p)
        reference=Simulator(w,p,initial.plan,realized_work=truth).run();audit_result(reference,w,p,realized_work=truth)
        dump(out/"reference.json",reference)
        reference_seconds=perf_counter()-begin
        fault=Failure(reference.makespan*fraction,failure_node(seed,mix,nodes),0.1*w.pbar if i%4==3 else 0)
        rows,_=run_methods(w,p,initial,reference,truth,fault,chosen["lambda"],chosen["mu"],output=out,reuse_aliases=False)
        measurements.append({"seed":seed,"mix":mix,"nodes":nodes,"ccr":2,"cv":cv,"failure_fraction":fraction,
                             "control_delay":fault.control_delay,"reference_seconds":reference_seconds,"methods":rows})
        print(f"profiling {i+1}/20 complete",flush=True)
    p95={name:float(np.quantile([m["methods"][name]["total_seconds"] for m in measurements],0.95)) for name in METHODS}
    reference_p95=float(np.quantile([m["reference_seconds"] for m in measurements],0.95))
    # P0 structural counts only: no scheduling/test outcome is evaluated here.
    maximum_real_tasks=73+84+84
    scale=max(1,maximum_real_tasks/192)**2
    estimates=[]
    for seeds in (30,10):
        main=3*2*2*2*seeds
        counts={method:main for method in METHODS}
        for name in ("B0","B1","B2","SAIL"):counts[name]+=180
        refs=3*2*2*seeds+120
        seconds=2*scale*(sum(counts[n]*p95[n] for n in METHODS)+refs*reference_p95)+600
        estimates.append({"seeds":seeds,"nominal_jobs":main*8+refs+720,"estimated_seconds":seconds,"estimated_hours":seconds/3600})
    selected=next((r["seeds"] for r in estimates if r["estimated_hours"]<=12),None)
    files=list((ROOT/"reports/p3/profiling/events").rglob("*.json"))
    size_p95=float(np.quantile([f.stat().st_size for f in files],0.95))
    result={"scenarios":20,"method_configurations_per_scenario":8,"measurements":measurements,"p95_end_to_end_seconds":p95,
            "p95_reference_seconds":reference_p95,"task_count_safety_scale":scale,"estimates":estimates,"selected_test_seed_count":selected,
            "formula":"2*(241/192)^2*sum(n_j*p95_j)+600s","timing_includes":"policy, event execution, independent audit, metrics, JSON event write",
            "p95_json_bytes":size_p95,"conservative_nominal_storage_bytes":size_p95*6960*2,"workspace_free_bytes":shutil.disk_usage(ROOT).free,
            "formal_runs_completed":0}
    dump(ROOT/"reports/p3/profiling_summary.json",result)
    print(json.dumps({"selected_test_seed_count":selected,"estimates":estimates},ensure_ascii=False),flush=True)


if __name__=="__main__":main()
