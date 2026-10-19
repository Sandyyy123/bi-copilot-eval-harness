"""Load cases and traces, score a system variant, and compare two variants."""
from __future__ import annotations

import json
from math import comb
from pathlib import Path

from .checks import CHECKS, evaluate_case


def load_cases(path: str | Path) -> dict[str, dict]:
    cases = json.loads(Path(path).read_text(encoding="utf-8"))
    ids = [c["case_id"] for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case_id in cases file")
    return {c["case_id"]: c for c in cases}


def load_traces(path: str | Path) -> dict[str, dict]:
    traces = {}
    for line_no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        trace = json.loads(line)
        if trace["case_id"] in traces:
            raise ValueError(f"line {line_no}: second trace for {trace['case_id']}")
        traces[trace["case_id"]] = trace
    return traces


def score_variant(cases: dict[str, dict], traces: dict[str, dict]) -> dict:
    """Score every case. A case with no trace counts as a failed case."""
    rows = []
    for case_id, case in cases.items():
        trace = traces.get(case_id)
        if trace is None:
            rows.append({"case_id": case_id, "checks": {}, "passed": False, "missing_trace": True})
        else:
            rows.append(evaluate_case(case, trace))
    by_check = {}
    for name in CHECKS:
        values = [r["checks"].get(name) for r in rows if r["checks"].get(name) is not None]
        by_check[name] = {
            "applicable": len(values),
            "passed": sum(values),
            "pass_rate": round(sum(values) / len(values), 3) if values else None,
        }
    ranks = [r.get("retrieval_rank") for r in rows if r.get("retrieval_rank") is not None]
    return {
        "cases": len(rows),
        "cases_passed": sum(r["passed"] for r in rows),
        "by_check": by_check,
        "retrieval_mrr": round(sum(1 / r for r in ranks if r) / len(ranks), 3) if ranks else None,
        "rows": rows,
    }


def sign_test_p(wins: int, losses: int) -> float:
    """Exact two-sided sign test on discordant pairs (ties are dropped)."""
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    tail = sum(comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def compare(baseline: dict, candidate: dict) -> dict:
    """Paired case-level comparison of two variants scored on the same cases."""
    base = {r["case_id"]: r["passed"] for r in baseline["rows"]}
    cand = {r["case_id"]: r["passed"] for r in candidate["rows"]}
    if base.keys() != cand.keys():
        raise ValueError("variants were scored on different case sets")
    wins = sorted(c for c in base if cand[c] and not base[c])
    losses = sorted(c for c in base if base[c] and not cand[c])
    p = sign_test_p(len(wins), len(losses))
    return {
        "wins": wins,
        "losses": losses,
        "ties": len(base) - len(wins) - len(losses),
        "sign_test_p": round(p, 4),
        "verdict": (
            "candidate better" if p < 0.05 and len(wins) > len(losses)
            else "baseline better" if p < 0.05 else
            "no reliable difference on this case set; add representative cases before deciding"
        ),
    }
