import hashlib
import json
import pytest

from sail.development import dump
from sail.experiment import METHODS,method_aliases
from sail.frozen import execute_frozen,verify_freeze
from .helpers import graph


def toy_freeze(tmp_path):
    workspace=tmp_path/"workspace";workspace.mkdir()
    freeze=workspace/"freeze";freeze.mkdir()
    code=workspace/"fixture_code.txt";code.write_text("unchanged fixture")
    w=graph({"a":2,"b":1},[("a","b",1)])
    dump(freeze/"workload.json",w);dump(freeze/"truth.json",{"a":2,"b":1})
    base={"id":"base","workload_file":"workload.json","truth_file":"truth.json","speeds":[1,1],"bandwidth":1}
    scenario={"id":"s","base_id":"base","root_seed":1,"mix":"A","nodes":2,"ccr":0.5,"failure_fraction":0.3,
              "failed_node":0,"control_delay_pbar_units":0,"variant":"main"}
    jobs=[{"id":"ref-base","kind":"reference","base_id":"base"}]+[
        {"id":f"run-s-{m}","kind":"failure","base_id":"base","scenario_id":"s","method":m} for m in METHODS]
    dump(freeze/"scenario_manifest.json",{"bases":[base],"scenarios":[scenario],"jobs":jobs})
    dump(freeze/"freeze.json",{"status":"FROZEN_G2","purpose":"UNIT_TEST","selected_lambda":3,"selected_mu":0,
         "method_aliases":method_aliases(3,0),"code_files":[{"path":"fixture_code.txt","sha256":hashlib.sha256(code.read_bytes()).hexdigest()}]})
    dump(freeze/"inputs_manifest.json",{"files":[{"path":p.name,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(freeze.glob("*.json")) if p.name!="inputs_manifest.json"]})
    return workspace,freeze


def test_frozen_execution_resume_aliases_and_no_global_state_change(tmp_path):
    workspace,freeze=toy_freeze(tmp_path);output=tmp_path/"output"
    first=execute_frozen(workspace,freeze,output,job_limit=1)
    assert first["completed_labels"]==1 and not first["all_complete"]
    final=execute_frozen(workspace,freeze,output)
    assert final["completed_labels"]==9 and final["actual_executions"]==8 and final["alias_records"]==1 and final["all_complete"]
    assert execute_frozen(workspace,freeze,output)==final
    rows=[json.loads(line) for line in (output/"metrics.jsonl").read_text().splitlines()]
    alias=next(r for r in rows if r.get("method")=="NoChurn")
    assert alias["status"]=="ALIAS" and alias["execution_alias_of"]=="run-s-SAIL"
    assert not (workspace/"project_state.json").exists()


@pytest.mark.parametrize("target",["code","truth","status","checkpoint"])
def test_frozen_runner_rejects_changed_evidence(tmp_path,target):
    workspace,freeze=toy_freeze(tmp_path);output=tmp_path/"output"
    if target=="code":(workspace/"fixture_code.txt").write_text("changed")
    elif target=="truth":dump(freeze/"truth.json",{"a":99,"b":1})
    elif target=="status":
        data=json.loads((freeze/"freeze.json").read_text());data["status"]="DRAFT";dump(freeze/"freeze.json",data)
    else:
        execute_frozen(workspace,freeze,output,job_limit=1)
        event=next((output/"events").glob("*.json"));event.write_text("changed")
    with pytest.raises(ValueError):execute_frozen(workspace,freeze,output)
