import hashlib
import json
from pathlib import Path
import pytest

_cases = []
_source_hashes = {}


def pytest_addoption(parser):
    parser.addoption("--acceptance-stage",choices=("P1","P2","P3"),default="P3")


def input_hashes():
    root = Path(__file__).resolve().parents[1]
    paths = sorted(list((root/"sail").glob("*.py"))+list((root/"tests").glob("*.py"))+
                   [root/"pytest.ini",root/"requirements-p1.txt",root/"requirements-p2.txt",root/"requirements-p3.txt",root/"docs/protocol_v1.md",root/"docs/P2_共同内核与基线说明.md",root/"docs/P3_实现参数选择与冻结说明.md",root/"configs/protocol_v1.json",root/"configs/p3_execution_spec.json",root/"data/manifest_v1.json",
                    root/"scripts/run_frozen_experiments.py",root/"scripts/analyze_frozen_experiments.py",root/"scripts/make_g2_freeze.py",
                    root/"scripts/test_p0_data_validation.py",root/"scripts/validate_p0_data.py"]+
                   list((root/"scripts").glob("*p1*.py"))+list((root/"scripts").glob("*p2*.py"))+list((root/"scripts").glob("*p3*.py")))
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def pytest_sessionstart(session):
    _cases.clear()
    _source_hashes.clear()
    _source_hashes.update(input_hashes())


@pytest.fixture
def record_case():
    return _cases.append


def pytest_sessionfinish(session,exitstatus):
    if _cases:
        from collections import Counter
        stage = session.config.getoption("--acceptance-stage").lower()
        path = Path(__file__).resolve().parents[1]/f"reports/{stage}/systematic_results.json"
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps({"purpose":"execution correctness, not algorithm performance experiments",
                                    "session_exit_code":int(exitstatus),"pytest_collected":session.testscollected,
                                    "source_hashes":_source_hashes,"inputs_unchanged_during_tests":_source_hashes==input_hashes(),
                                    "completed_cases":len(_cases),"counts":dict(Counter(c["kind"] for c in _cases)),
                                    "cases":_cases},ensure_ascii=False,indent=2)+"\n")
