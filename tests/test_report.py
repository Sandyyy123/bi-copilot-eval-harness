import json
from pathlib import Path

import pytest

from bi_agent_eval.report import compare, load_cases, load_traces, score_variant, sign_test_p
import main

DATA = Path(__file__).resolve().parents[1] / "data"


def test_sign_test_exact_values():
    assert sign_test_p(0, 0) == 1.0
    assert sign_test_p(6, 1) == pytest.approx(0.125)
    assert sign_test_p(10, 0) == pytest.approx(2 / 1024)


def test_missing_trace_counts_as_failure():
    cases = load_cases(DATA / "cases.json")
    scored = score_variant(cases, {})
    assert scored["cases_passed"] == 0
    assert all(r.get("missing_trace") for r in scored["rows"])


def test_duplicate_trace_rejected(tmp_path):
    line = json.dumps({"case_id": "C01", "steps": [], "final": {}})
    path = tmp_path / "t.jsonl"
    path.write_text(line + "\n" + line + "\n")
    with pytest.raises(ValueError):
        load_traces(path)


def test_compare_requires_same_case_set():
    a = {"rows": [{"case_id": "x", "passed": True}]}
    b = {"rows": [{"case_id": "y", "passed": True}]}
    with pytest.raises(ValueError):
        compare(a, b)


def test_fixture_run_end_to_end(tmp_path):
    out = tmp_path / "results.json"
    assert main.main(["--cases", str(DATA / "cases.json"),
                      "--baseline", str(DATA / "traces_baseline.jsonl"),
                      "--candidate", str(DATA / "traces_candidate.jsonl"),
                      "--out", str(out)]) == 0
    res = json.loads(out.read_text())
    assert res["baseline"]["cases_passed"] == 2
    assert res["candidate"]["cases_passed"] == 7
    assert res["comparison"]["losses"] == ["C08"]
    assert res["comparison"]["sign_test_p"] == pytest.approx(0.125)
    assert res["comparison"]["verdict"].startswith("no reliable difference")
