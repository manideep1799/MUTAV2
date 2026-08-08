"""Runner for Target #3 (graph query generation) — Node-F1, not an LLM judge.

    python -m mutagent.run_graph_query                  # baseline, sample_repo fixture
    python -m mutagent.run_graph_query --repo-id <id>    # against a real indexed repo
    python -m mutagent.run_graph_query --dry-run         # regenerate ground truth, no API calls

This does not use mutagent.harness.evaluate() — that harness assumes an
LLM-judge-per-criterion shape (see mutagent/rubrics/issue_rec.json and
similar). This target has no judge to calibrate: the model's query is
EXECUTED against the real graph and the returned node set is compared
against ground truth produced the same way. See
mutagent/rubrics/graph_query.json for the full method.

Optimize is not implemented for this target yet — baseline measurement
only. A genetic-search loop over graph_query.txt is future work, not built
here; disclosing that honestly rather than pretending it exists.
"""
from __future__ import annotations

import argparse
import json
import sys

from config import load_prompt, load_dataset, settings, REPORTS_DIR
from graph.store import load_graph
from graph.query_dsl import execute_query
from clients.llm_client import complete
from clients.llm_client import extract_json


def _prf1(predicted: set[str], expected: set[str]) -> tuple[float, float, float]:
    if not predicted and not expected:
        return 1.0, 1.0, 1.0
    if not predicted:
        return 1.0, 0.0, 0.0            # nothing predicted, precision is vacuous-true, recall 0
    if not expected:
        return 0.0, 1.0, 0.0            # nothing expected, anything predicted is a false positive
    tp = len(predicted & expected)
    precision = tp / len(predicted)
    recall = tp / len(expected)
    f1 = 0.0 if (precision + recall) == 0 else 2 * precision * recall / (precision + recall)
    return round(precision, 4), round(recall, 4), round(f1, 4)


def _score_case(prompt_template: str, case: dict, graph) -> dict:
    question = case["inputs"]["question"]
    expected_paths = set(case["expected"]["expected_paths"])
    prompt = prompt_template.format(question=question)

    try:
        raw, latency_ms = complete(prompt, temperature=0.0, max_tokens=256)
    except Exception as exc:                      # noqa: BLE001
        return {"name": case["name"], "precision": 0.0, "recall": 0.0, "f1": 0.0,
                "error": f"LLM call failed: {type(exc).__name__}: {exc}",
                "predicted_paths": [], "raw_output": ""}

    parsed = _extract_json(raw)
    if parsed is None:
        return {"name": case["name"], "precision": 0.0, "recall": 0.0, "f1": 0.0,
                "error": f"model output not parseable as a query: {raw[:160]!r}",
                "predicted_paths": [], "raw_output": raw}

    result = execute_query(parsed, graph)
    if result.get("error"):
        return {"name": case["name"], "precision": 0.0, "recall": 0.0, "f1": 0.0,
                "error": f"query failed to execute: {result['error']}",
                "predicted_paths": [], "raw_output": raw, "generated_query": parsed}

    predicted_paths = {n["path"] for n in result["nodes"]}
    p, r, f1 = _prf1(predicted_paths, expected_paths)
    return {
        "name": case["name"], "precision": p, "recall": r, "f1": f1, "error": None,
        "predicted_paths": sorted(predicted_paths), "raw_output": raw,
        "generated_query": parsed,
    }


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m mutagent.run_graph_query")
    ap.add_argument("--repo-id", default="sample_repo")
    ap.add_argument("--dry-run", action="store_true",
                    help="re-verify the dataset's ground truth against the graph; no API calls")
    args = ap.parse_args()

    try:
        graph = load_graph(args.repo_id)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print("       run: python -m mutagent.graph_fixtures.build_sample_graph", file=sys.stderr)
        return 1

    prompt_template = load_prompt("graph_query")
    dataset = load_dataset("graph_query")
    print(f"repo_id  : {args.repo_id}  ({graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges)")
    print(f"cases    : {len(dataset)}")
    print(f"model    : {settings.groq_model}")

    if args.dry_run:
        # This target's ground truth is executable, so dry-run can do
        # something the other targets can't: re-run every reference query
        # and confirm the dataset still matches the graph. If someone
        # edits query_dsl.py and breaks something, this catches it with
        # zero API calls.
        mismatches = []
        for case in dataset:
            ref = case["expected"]["reference_op"]
            result = execute_query(ref, graph)
            actual = sorted(n["path"] for n in result.get("nodes", []))
            expected = case["expected"]["expected_paths"]
            if actual != expected:
                mismatches.append((case["name"], expected, actual))
        print(f"\nre-verified {len(dataset)} cases' ground truth against the graph")
        if mismatches:
            print(f"MISMATCH: {len(mismatches)} case(s) no longer match — "
                  f"the dataset is stale relative to query_dsl.py or the graph.")
            for name, exp, act in mismatches[:5]:
                print(f"  {name}: expected {exp} got {act}")
            return 1
        print("all ground truth still consistent — dataset is valid. No API calls made.")
        return 0

    if not settings.groq_api_key.strip().startswith("gsk_"):
        print("\nerror: GROQ_API_KEY missing or invalid in backend/.env", file=sys.stderr)
        return 1

    results = []
    for idx, case in enumerate(dataset, 1):
        print(f"    [{idx:>2}/{len(dataset)}] {case['name']}", flush=True)
        results.append(_score_case(prompt_template, case, graph))

    print(f"\n{'=' * 68}\nRESULTS\n{'=' * 68}")
    op_scores: dict[str, list[float]] = {}
    for r, case in zip(results, dataset):
        op = case["expected"]["reference_op"]["op"]
        op_scores.setdefault(op, []).append(r["f1"])
        mark = "OK  " if r["f1"] >= 0.99 else ("~~  " if r["f1"] > 0 else "FAIL")
        print(f"  [{mark}] {r['name']:<32} P={r['precision']:.2f} R={r['recall']:.2f} F1={r['f1']:.2f}")
        if r["error"]:
            print(f"           !! {r['error']}")

    mean_f1 = sum(r["f1"] for r in results) / len(results) if results else 0.0
    print(f"\n  mean F1 : {mean_f1:.4f}")
    print("  by op:")
    for op, scores in sorted(op_scores.items()):
        print(f"    {op:<16} mean F1 = {sum(scores)/len(scores):.4f}  (n={len(scores)})")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "target_id": "graph_query",
        "repo_id": args.repo_id,
        "mean_f1": round(mean_f1, 4),
        "by_op": {op: round(sum(s) / len(s), 4) for op, s in op_scores.items()},
        "rows": results,
    }
    dest = REPORTS_DIR / "graph_query.delta.json"
    dest.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  report: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
