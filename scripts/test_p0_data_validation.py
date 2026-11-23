"""Adversarial checks for the P0 input auditor, not scheduling experiments."""
from copy import deepcopy
import pytest
from validate_p0_data import validate_document


@pytest.fixture
def valid():
    return {"workflow": {"specification": {
        "tasks": [
            {"id": "a", "parents": [], "children": ["b"], "inputFiles": [], "outputFiles": ["f"]},
            {"id": "b", "parents": ["a"], "children": [], "inputFiles": ["f"], "outputFiles": []}],
        "files": [{"id": "f", "sizeInBytes": 100}]},
        "execution": {"tasks": [{"id": "a", "runtimeInSeconds": 1}, {"id": "b", "runtimeInSeconds": 2}]}}}


def codes(doc):
    return {x["code"] for x in validate_document(doc)[1]}


def test_valid_document(valid):
    p, issues, graph, parsed = validate_document(valid)
    assert p["error_count"] == 0 and not issues
    assert p["critical_path_runtime_s"] == 3
    assert parsed["edges"][0]["bytes"] == 100


def test_duplicate_id(valid):
    valid["workflow"]["specification"]["tasks"].append(deepcopy(valid["workflow"]["specification"]["tasks"][0]))
    assert "DUPLICATE_ID" in codes(valid)


@pytest.mark.parametrize("value", [None, 0, -1, float("nan"), True])
def test_invalid_runtime(valid, value):
    valid["workflow"]["execution"]["tasks"][0]["runtimeInSeconds"] = value
    assert "INVALID_RUNTIME" in codes(valid)


def test_cycle(valid):
    a, b = valid["workflow"]["specification"]["tasks"]
    a["parents"] = ["b"]
    b["children"] = ["a"]
    assert "CYCLE" in codes(valid)


def test_asymmetric_edge(valid):
    valid["workflow"]["specification"]["tasks"][0]["children"] = []
    assert "ASYMMETRIC_EDGE" in codes(valid)


def test_negative_file_size(valid):
    valid["workflow"]["specification"]["files"][0]["sizeInBytes"] = -1
    assert "INVALID_FILE_SIZE" in codes(valid)


def test_missing_file_reference(valid):
    valid["workflow"]["specification"]["files"] = []
    assert "MISSING_FILE_REFERENCE" in codes(valid)


def test_unordered_file_dependency(valid):
    a, b = valid["workflow"]["specification"]["tasks"]
    a["children"] = []
    b["parents"] = []
    assert "FILE_DEPENDENCY_MISSING" in codes(valid)


def test_ambiguous_producer(valid):
    valid["workflow"]["specification"]["tasks"][1]["outputFiles"] = ["f"]
    assert "AMBIGUOUS_PRODUCER" in codes(valid)


def test_execution_id_mismatch(valid):
    valid["workflow"]["execution"]["tasks"].pop()
    assert "EXECUTION_ID_MISMATCH" in codes(valid)


def test_timestamp_warning_only(valid):
    valid["createdAt"] = "2021-03-23T06:25:32"
    p, issues, *_ = validate_document(valid)
    assert p["error_count"] == 0
    assert "NONCANONICAL_TIMESTAMP" in {i["code"] for i in issues}


def test_external_input_is_valid(valid):
    spec = valid["workflow"]["specification"]
    spec["files"].append({"id": "external", "sizeInBytes": 20})
    spec["tasks"][0]["inputFiles"] = ["external"]
    p, *_ = validate_document(valid)
    assert p["error_count"] == 0 and p["external_input_files"] == 1


def test_indirect_data_edge_is_explicit(valid):
    spec = valid["workflow"]["specification"]
    spec["tasks"][1]["children"] = ["c"]
    spec["tasks"].append({"id": "c", "parents": ["b"], "children": [], "inputFiles": ["f"], "outputFiles": []})
    valid["workflow"]["execution"]["tasks"].append({"id": "c", "runtimeInSeconds": 1})
    p, issues, _, parsed = validate_document(valid)
    assert p["error_count"] == 0 and p["data_edges_added"] == 1
    assert any(e["source"] == "a" and e["target"] == "c" and not e["original_dependency"] for e in parsed["edges"])
