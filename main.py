"""Score two agent variants on the same cases and compare them.

Usage: python main.py [--cases data/cases.json] [--baseline data/traces_baseline.jsonl]
                      [--candidate data/traces_candidate.jsonl] [--out results.json]
"""
import argparse
import json
import sys

from bi_agent_eval import compare, load_cases, load_traces, score_variant


def show(name, scored):
    print(f"\n{name}: {scored['cases_passed']}/{scored['cases']} cases pass every applicable check")
    for check, s in scored["by_check"].items():
        rate = "n/a" if s["pass_rate"] is None else f"{s['passed']}/{s['applicable']}"
        print(f"  {check:<20} {rate}")
    print(f"  retrieval MRR        {scored['retrieval_mrr']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", default="data/cases.json")
    ap.add_argument("--baseline", default="data/traces_baseline.jsonl")
    ap.add_argument("--candidate", default="data/traces_candidate.jsonl")
    ap.add_argument("--out", default="results.json")
    args = ap.parse_args(argv)
    cases = load_cases(args.cases)
    base = score_variant(cases, load_traces(args.baseline))
    cand = score_variant(cases, load_traces(args.candidate))
    cmp = compare(base, cand)
    show("baseline", base)
    show("candidate", cand)
    print(f"\npaired: wins {cmp['wins']} losses {cmp['losses']} ties {cmp['ties']} "
          f"sign-test p={cmp['sign_test_p']}\nverdict: {cmp['verdict']}")
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"baseline": base, "candidate": cand, "comparison": cmp}, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
