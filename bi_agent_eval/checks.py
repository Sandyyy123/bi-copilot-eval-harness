"""Per-case checks for one recorded agent investigation (a "trace").

A trace is what a business-intelligence agent did for one account question:
the tool calls it made (warehouse SQL, knowledge-base search), what each call
returned, and its final answer (a recommendation with citations, or an
abstention). Every check returns True (pass), False (fail) or None (not
applicable to this case), so a report can count only the checks that apply.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

WRITE_SQL = re.compile(
    r"\b(insert|update|delete|merge|drop|truncate|alter|create|grant|revoke)\b", re.I
)
DATE_BOUND = re.compile(r"\b\w*date\w*\b\s*(>=|>|between)", re.I)
ACCOUNT_LITERAL = re.compile(r"account_id\s*=\s*'([^']+)'", re.I)
TABLE_REF = re.compile(r"\b(?:from|join)\s+`?([\w.\-]+)`?", re.I)
NUMBER = re.compile(r"(?<![\w.])-?\d+(?:,\d{3})*(?:\.\d+)?")


def sql_steps(trace: dict) -> list[dict]:
    return [s for s in trace.get("steps", []) if s.get("tool") == "warehouse.query"]


def search_steps(trace: dict) -> list[dict]:
    return [s for s in trace.get("steps", []) if s.get("tool") == "knowledge.search"]


# ---------------------------------------------------------------- tool use
def tables_touched(trace: dict) -> set[str]:
    found: set[str] = set()
    for step in sql_steps(trace):
        for name in TABLE_REF.findall(step["args"].get("sql", "")):
            found.add(name.split(".")[-1].lower())
    return found


def check_required_tables(case: dict, trace: dict) -> bool | None:
    """Did the agent pull every data source the question needs?"""
    required = {t.lower() for t in case.get("required_tables", [])}
    if not required or case.get("should_abstain"):
        return None
    return required <= tables_touched(trace)


def check_tool_budget(case: dict, trace: dict) -> bool | None:
    """Stayed within the agreed number of tool calls (cost and loop guard)."""
    budget = case.get("max_tool_calls")
    if budget is None:
        return None
    return len(trace.get("steps", [])) <= budget


# ------------------------------------------------------------ SQL safety
def check_read_only(case: dict, trace: dict) -> bool | None:
    steps = sql_steps(trace)
    if not steps:
        return None
    return not any(WRITE_SQL.search(s["args"].get("sql", "")) for s in steps)


def check_account_isolation(case: dict, trace: dict) -> bool | None:
    """Every query filters on this case's account and on no other account."""
    steps = sql_steps(trace)
    if not steps:
        return None
    for step in steps:
        literals = {a for a in ACCOUNT_LITERAL.findall(step["args"].get("sql", ""))}
        if literals != {case["account_id"]}:
            return False
    return True


def check_date_bounded(case: dict, trace: dict) -> bool | None:
    """Every query has a date lower bound (controls scanned bytes and period)."""
    steps = sql_steps(trace)
    if not steps:
        return None
    return all(DATE_BOUND.search(s["args"].get("sql", "")) for s in steps)


# --------------------------------------------------------------- retrieval
def retrieval_rank(case: dict, trace: dict, k: int = 5) -> int | None:
    """1-based rank of the first expected knowledge doc in the first search, else 0."""
    expected = set(case.get("expected_doc_ids", []))
    if not expected:
        return None
    for step in search_steps(trace):
        for rank, doc_id in enumerate(step.get("result", {}).get("doc_ids", [])[:k], 1):
            if doc_id in expected:
                return rank
        return 0
    return 0


def check_retrieval_hit(case: dict, trace: dict, k: int = 5) -> bool | None:
    rank = retrieval_rank(case, trace, k)
    return None if rank is None else rank > 0


# --------------------------------------------------------------- grounding
def _numbers_in(value: Any) -> Iterable[float]:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        yield float(value)
    elif isinstance(value, str):
        for token in NUMBER.findall(value):
            yield float(token.replace(",", ""))
    elif isinstance(value, dict):
        for v in value.values():
            yield from _numbers_in(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _numbers_in(v)


def _decimals(token: str) -> int:
    return len(token.split(".")[1]) if "." in token else 0


def ungrounded_numbers(case: dict, trace: dict) -> list[str]:
    """Numbers in the recommendation that no cited tool result supports.

    A number is supported when a cited result contains a value that rounds to
    it at the precision written (as a raw value or as a percentage of a
    fraction). Numbers already in the question, or listed in the case's
    allowed_numbers (e.g. "30 days"), are exempt.
    """
    final = trace.get("final", {})
    cited = set(final.get("citations", []))
    pool = [
        v
        for s in trace.get("steps", [])
        if s.get("result_id") in cited
        for v in _numbers_in(s.get("result", {}))
    ]
    exempt = {float(x) for x in case.get("allowed_numbers", [])}
    exempt |= set(_numbers_in(case.get("question", "")))
    missing = []
    for token in NUMBER.findall(final.get("recommendation", "")):
        n = float(token.replace(",", ""))
        if n in exempt:
            continue
        d = _decimals(token)
        if not any(round(v, d) == n or round(v * 100, d) == n for v in pool):
            missing.append(token)
    return missing


def check_citations_exist(case: dict, trace: dict) -> bool | None:
    """Every citation points at a tool result the agent actually received."""
    final = trace.get("final", {})
    if final.get("abstained"):
        return None
    received = {s.get("result_id") for s in trace.get("steps", [])}
    cites = final.get("citations", [])
    return bool(cites) and set(cites) <= received


def check_numbers_grounded(case: dict, trace: dict) -> bool | None:
    if trace.get("final", {}).get("abstained"):
        return None
    return not ungrounded_numbers(case, trace)


# -------------------------------------------------------------- abstention
def check_abstention(case: dict, trace: dict) -> bool:
    """Recommends only when the evidence supports it; abstains otherwise."""
    return bool(trace.get("final", {}).get("abstained")) == bool(case.get("should_abstain"))


CHECKS = {
    "required_tables": check_required_tables,
    "tool_budget": check_tool_budget,
    "read_only_sql": check_read_only,
    "account_isolation": check_account_isolation,
    "date_bounded_sql": check_date_bounded,
    "retrieval_hit@5": check_retrieval_hit,
    "citations_exist": check_citations_exist,
    "numbers_grounded": check_numbers_grounded,
    "abstention_correct": check_abstention,
}


def evaluate_case(case: dict, trace: dict) -> dict:
    results = {name: fn(case, trace) for name, fn in CHECKS.items()}
    applicable = [v for v in results.values() if v is not None]
    return {
        "case_id": case["case_id"],
        "checks": results,
        "passed": all(applicable),
        "ungrounded_numbers": ungrounded_numbers(case, trace),
        "retrieval_rank": retrieval_rank(case, trace),
        "tool_calls": len(trace.get("steps", [])),
    }
