"""Offline evaluation harness for business-intelligence agent investigation traces."""
from .checks import CHECKS, evaluate_case
from .report import compare, load_cases, load_traces, score_variant, sign_test_p

__all__ = ["CHECKS", "evaluate_case", "compare", "load_cases", "load_traces", "score_variant", "sign_test_p"]
