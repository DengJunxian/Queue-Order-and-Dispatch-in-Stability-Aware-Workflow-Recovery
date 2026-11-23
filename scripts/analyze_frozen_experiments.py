"""Analyze a completed frozen run without changing methods, weights, or seeds."""
import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sail.development import dump
from sail.frozen import verify_freeze
from sail.statistics import paired_bootstrap


def analyze(freeze,output):
    config,manifest=verify_freeze(ROOT,freeze)
    output=Path(output)
    summary=json.loads((output/"execution_summary.json").read_text())
    rows=[json.loads(line) for line in (output/"metrics.jsonl").read_text().splitlines()]
    if not summary["all_complete"] or {r["job_id"] for r in rows}!={j["id"] for j in manifest["jobs"]}:raise ValueError("experiment incomplete")
    if len(rows)!=len(manifest["jobs"]):raise ValueError("duplicated or missing job records")
    main=[r for r in rows if r["kind"]=="failure" and r["variant"]=="main"]
    rule=config["statistical_rule"]
    kwargs={"repetitions":rule["repetitions"],"seed":rule["seed"]}
    primary=paired_bootstrap(main,"B2",**kwargs)
    mix_results={m:paired_bootstrap([r for r in main if r["mix"]==m],"B2",**kwargs) for m in ("A","B","C")}
    mechanisms={name:paired_bootstrap(main,name,**kwargs) for name in rule["mechanism_comparators"]}
    cdi=primary["cdi"];awct=primary["relative_awct"]
    result={"purpose":"confirmatory statistics on frozen main results","primary":primary,"mixes":mix_results,"mechanisms":mechanisms,
            "CDI_interval_supports_improvement":cdi["ci95"] is not None and cdi["ci95"][1]<0,
            "AWCT_budget_supported":awct["upper95"] is not None and awct["upper95"]<=0.05,
            "at_least_two_mix_directions":sum(r["cdi"]["point"] is not None and r["cdi"]["point"]<0 for r in mix_results.values())>=2,
            "mechanism_interpretation_required":True,"p_values_reported":False,"protocol_changed":False}
    dump(output/"statistics.json",result)
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--freeze",required=True);parser.add_argument("--output",required=True)
    args=parser.parse_args();result=analyze(Path(args.freeze),Path(args.output))
    print(json.dumps({k:v for k,v in result.items() if isinstance(v,bool)},ensure_ascii=False))
