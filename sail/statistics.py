"""Root-block bootstrap for the predeclared paired main comparisons."""
from __future__ import annotations

import math
import numpy as np


def paired_bootstrap(rows,comparator="B2",*,repetitions=5000,seed=73000):
    selected=[r for r in rows if r.get("variant","main")=="main" and r["method"] in {"SAIL",comparator}]
    indexed={}
    for r in selected:
        if r.get("status","COMPLETE") not in {"COMPLETE","ALIAS"}:raise ValueError("failed or incomplete main run")
        key=(r["root_seed"],r["mix"],r["nodes"],r["ccr"],r["failure_fraction"],r["method"])
        if key in indexed:raise ValueError("duplicate run row")
        indexed[key]=r
    roots=sorted({k[0] for k in indexed});mixes=sorted({k[1] for k in indexed})
    cells=sorted({(k[1],k[2],k[3],k[4]) for k in indexed})
    if not roots or repetitions<1:raise ValueError("empty analysis or invalid bootstrap count")
    differences={"cdi":np.full((len(roots),len(cells)),np.nan),"relative_awct":np.zeros((len(roots),len(cells)))}
    for i,root in enumerate(roots):
        for j,cell in enumerate(cells):
            try:a=indexed[(root,*cell,"SAIL")];b=indexed[(root,*cell,comparator)]
            except KeyError as exc:raise ValueError("main pairing or root/cell grid incomplete") from exc
            if a["protected_count"]!=b["protected_count"]:raise ValueError("protection population differs")
            if not math.isfinite(a["awct"]) or not math.isfinite(b["awct"]) or a["awct"]<=0 or b["awct"]<=0:raise ValueError("invalid AWCT")
            differences["relative_awct"][i,j]=a["awct"]/b["awct"]-1
            if a["protected_count"]:
                if a["cdi"] is None or b["cdi"] is None or not math.isfinite(a["cdi"]) or not math.isfinite(b["cdi"]):raise ValueError("missing applicable CDI")
                differences["cdi"][i,j]=a["cdi"]-b["cdi"]
            elif a["cdi"] is not None or b["cdi"] is not None:raise ValueError("empty P must be NA")
    def estimate(array,indices):
        sample=array[indices]
        count=np.isfinite(sample).sum(axis=0)
        cell_mean=np.divide(np.nansum(sample,axis=0),count,out=np.full(len(cells),np.nan),where=count>0)
        means=[]
        for mix in mixes:
            valid=[cell_mean[j] for j,c in enumerate(cells) if c[0]==mix and np.isfinite(cell_mean[j])]
            if not valid:return float("nan")
            means.append(float(np.mean(valid)))
        return float(np.mean(means))
    rng=np.random.Generator(np.random.PCG64(seed))
    indices=rng.integers(0,len(roots),size=(repetitions,len(roots)))
    output={"comparator":comparator,"cluster_count":len(roots),"root_seeds":roots,"cells":len(cells),"repetitions":repetitions,"seed":seed,
            "weighting":"equal defined axis cells within mix, then equal mixes; same resampled roots across all cells",
            "NA_rule":"if any mix has no applicable cell, statistic undefined; CI requires every bootstrap draw defined"}
    for name,array in differences.items():
        point=estimate(array,np.arange(len(roots)))
        draws=np.array([estimate(array,idx) for idx in indices]);valid=np.isfinite(draws)
        complete=bool(valid.all())
        output[name]={"point":float(point) if np.isfinite(point) else None,"defined_pairs":int(np.isfinite(array).sum()),
                      "undefined_pairs":int(np.isnan(array).sum()),"defined_bootstrap_draws":int(valid.sum()),
                      "ci95":[float(x) for x in np.quantile(draws,[0.025,0.975])] if complete else None,
                      "upper95":float(np.quantile(draws,0.95)) if complete else None}
    return output
