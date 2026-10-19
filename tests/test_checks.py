from bi_agent_eval.checks import (
    check_abstention, check_account_isolation, check_citations_exist, check_date_bounded,
    check_read_only, check_required_tables, check_retrieval_hit, check_tool_budget,
    evaluate_case, retrieval_rank, ungrounded_numbers,
)

CASE = {"case_id": "T1", "account_id": "a1", "question": "What changed in the last 30 days?",
        "required_tables": ["orders_daily", "sessions_daily"], "max_tool_calls": 2,
        "should_abstain": False}


def sql(text, rid="r1", rows=None):
    return {"tool": "warehouse.query", "args": {"sql": text}, "result_id": rid, "result": {"rows": rows or []}}


GOOD = "SELECT * FROM ds.orders_daily o JOIN ds.sessions_daily s USING (d) WHERE account_id = 'a1' AND order_date >= '2026-01-01'"


def test_required_tables_from_and_join():
    assert check_required_tables(CASE, {"steps": [sql(GOOD)]}) is True
    only_orders = GOOD.split(" o JOIN")[0] + " WHERE account_id = 'a1'"
    assert check_required_tables(CASE, {"steps": [sql(only_orders)]}) is False


def test_required_tables_not_applicable_when_case_expects_abstention():
    assert check_required_tables({**CASE, "should_abstain": True}, {"steps": []}) is None


def test_tool_budget():
    assert check_tool_budget(CASE, {"steps": [sql(GOOD)] * 2}) is True
    assert check_tool_budget(CASE, {"steps": [sql(GOOD)] * 3}) is False


def test_read_only_blocks_writes_but_not_column_names():
    assert check_read_only(CASE, {"steps": [sql("SELECT updated_at FROM t WHERE account_id = 'a1'")]}) is True
    assert check_read_only(CASE, {"steps": [sql("DELETE FROM t WHERE account_id = 'a1'")]}) is False
    assert check_read_only(CASE, {"steps": []}) is None


def test_account_isolation_rejects_other_or_missing_account():
    assert check_account_isolation(CASE, {"steps": [sql(GOOD)]}) is True
    leak = GOOD.replace("account_id = 'a1'", "account_id = 'a1' OR account_id = 'a2'")
    assert check_account_isolation(CASE, {"steps": [sql(leak)]}) is False
    assert check_account_isolation(CASE, {"steps": [sql("SELECT 1 FROM t")]}) is False


def test_date_bounded():
    assert check_date_bounded(CASE, {"steps": [sql(GOOD)]}) is True
    assert check_date_bounded(CASE, {"steps": [sql("SELECT 1 FROM t WHERE account_id = 'a1'")]}) is False
    between = "SELECT 1 FROM t WHERE account_id = 'a1' AND event_date BETWEEN '2026-01-01' AND '2026-02-01'"
    assert check_date_bounded(CASE, {"steps": [sql(between)]}) is True


def test_retrieval_rank_uses_first_search_only():
    case = {"case_id": "K", "expected_doc_ids": ["kb-x"]}
    first_miss = {"steps": [
        {"tool": "knowledge.search", "result_id": "r1", "result": {"doc_ids": ["kb-a", "kb-b"]}},
        {"tool": "knowledge.search", "result_id": "r2", "result": {"doc_ids": ["kb-x"]}},
    ]}
    assert retrieval_rank(case, first_miss) == 0
    hit3 = {"steps": [{"tool": "knowledge.search", "result_id": "r1", "result": {"doc_ids": ["a", "b", "kb-x"]}}]}
    assert retrieval_rank(case, hit3) == 3
    assert check_retrieval_hit(case, hit3) is True
    assert check_retrieval_hit({"case_id": "N"}, hit3) is None


def test_numbers_grounded_handles_percent_rounding_and_thousands():
    rows = [{"cr": 0.0213, "revenue": 18400.0}]
    trace = {"steps": [sql(GOOD, "r1", rows)],
             "final": {"abstained": False, "citations": ["r1"],
                       "recommendation": "Conversion is 2.1% and revenue 18,400 over 30 days."}}
    assert ungrounded_numbers(CASE, trace) == []
    trace["final"]["recommendation"] = "Expect 15% uplift."
    assert ungrounded_numbers(CASE, trace) == ["15"]


def test_numbers_only_count_from_cited_results():
    trace = {"steps": [sql(GOOD, "r1", [{"x": 7}]), sql(GOOD, "r2", [{"y": 9}])],
             "final": {"abstained": False, "citations": ["r1"], "recommendation": "Value 9."}}
    assert ungrounded_numbers(CASE, trace) == ["9"]


def test_citations_must_point_at_received_results():
    trace = {"steps": [sql(GOOD, "r1")], "final": {"abstained": False, "citations": ["r1"], "recommendation": "x"}}
    assert check_citations_exist(CASE, trace) is True
    trace["final"]["citations"] = ["r9"]
    assert check_citations_exist(CASE, trace) is False
    trace["final"]["citations"] = []
    assert check_citations_exist(CASE, trace) is False


def test_abstention_both_directions():
    assert check_abstention({"should_abstain": True}, {"final": {"abstained": True}}) is True
    assert check_abstention({"should_abstain": True}, {"final": {"abstained": False}}) is False
    assert check_abstention({"should_abstain": False}, {"final": {"abstained": True}}) is False


def test_evaluate_case_ignores_not_applicable_checks():
    case = {"case_id": "A", "account_id": "a1", "should_abstain": True}
    row = evaluate_case(case, {"steps": [], "final": {"abstained": True, "citations": []}})
    assert row["passed"] is True
    assert row["checks"]["read_only_sql"] is None
