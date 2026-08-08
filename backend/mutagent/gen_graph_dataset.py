"""Generates target #3's eval dataset by RUNNING the real graph, not by
hand-labelling.

Design §09's claim for this target is that ground truth is machine-generated
at scale — "you already know auth.py has exactly three importers because you
parsed it." This script is that claim made real: for each case it calls
backend.graph.query_dsl.execute_query() against a real graph and records
whatever comes back as the expected node set. It never asserts an answer a
human decided was right; the graph decides.

Usage:
    python -m mutagent.gen_graph_dataset                    # sample_repo fixture
    python -m mutagent.gen_graph_dataset --repo-id <id>      # a real indexed repo

Produces: mutagent/datasets/graph_query.json
"""
from __future__ import annotations

import argparse
import json
import random

from config import DATASETS_DIR
from graph.store import load_graph
from graph.query_dsl import execute_query

DATASET_PATH = DATASETS_DIR / "graph_query.json"

# One or more natural-language phrasings per op, so the generated set doesn't
# train the model on a single fixed sentence shape per op.
_QUESTION_TEMPLATES = {
    "blast_radius": [
        "What breaks if I change {target}?",
        "What is the blast radius of {target}?",
        "If I modify {target}, what else could be affected?",
    ],
    "importers_of": [
        "Which files import {target}?",
        "What depends on {target}?",
        "Who imports {target}?",
    ],
    "imports_of": [
        "What does {target} import?",
        "What does {target} depend on?",
    ],
    "definition_of": [
        "Where is {symbol} defined?",
        "Which file defines {symbol}?",
    ],
    "occurrences_of": [
        "Where does {symbol} appear in the codebase?",
        "Which files reference {symbol}?",
    ],
    "neighbors": [
        "What files are directly connected to {target}?",
        "Show me everything one hop from {target}.",
    ],
}


def _case(name: str, question: str, ground_truth_query: dict, graph) -> dict | None:
    """Run ground_truth_query for real and package it as a dataset case.

    Returns None if the query yields zero nodes AND no error — an empty
    case teaches the model nothing about what a right answer looks like,
    so it is skipped rather than padding the dataset with no-ops.
    """
    result = execute_query(ground_truth_query, graph)
    if result.get("error"):
        return None
    paths = sorted(n["path"] for n in result["nodes"])
    if not paths:
        return None
    return {
        "name": name,
        "failure_mode": f"Generated node set for a {ground_truth_query['op']} query does not match a correctly executed one.",
        "inputs": {"question": question},
        "expected": {
            "expected_paths": paths,
            "expected_coverage_tier": result["coverage_tier"],
            # Kept for diagnostics only — scoring compares node SETS from
            # whatever query the model emits, not whether it picked this
            # exact op. A different op that returns the same correct set
            # is not a failure.
            "reference_op": ground_truth_query,
        },
    }


def generate(repo_id: str, seed: int = 7) -> list[dict]:
    graph = load_graph(repo_id)
    rng = random.Random(seed)
    cases: list[dict] = []

    deep_paths = sorted(p for p in graph.nodes if graph.nodes[p].get("tier") == "deep")
    all_symbols = sorted({
        d["name"] for p in graph.nodes for d in graph.nodes[p].get("defs", [])
    })
    # A symbol shared across >=2 files stresses occurrences_of beyond the
    # trivial one-file case, and is exactly where a naive implementation
    # (stop at first match) would silently under-report.
    ident_counts: dict[str, int] = {}
    for p in graph.nodes:
        for ident in graph.nodes[p].get("idents", []):
            ident_counts[ident] = ident_counts.get(ident, 0) + 1
    shared_idents = sorted(k for k, v in ident_counts.items() if v >= 2)

    def add(op_key: str, target_or_symbol: str, query: dict) -> None:
        template = rng.choice(_QUESTION_TEMPLATES[op_key])
        question = template.format(target=target_or_symbol, symbol=target_or_symbol)
        name = f"{op_key}__{target_or_symbol.replace('/', '_').replace('.', '_')}"
        case = _case(name, question, query, graph)
        if case and case["name"] not in {c["name"] for c in cases}:
            cases.append(case)

    for path in deep_paths:
        add("blast_radius", path, {"op": "blast_radius", "targets": [path], "max_hops": 3})
        add("importers_of", path, {"op": "importers_of", "targets": [path], "max_hops": 3})
        add("imports_of", path, {"op": "imports_of", "targets": [path]})
        add("neighbors", path, {"op": "neighbors", "targets": [path]})

    for symbol in all_symbols:
        add("definition_of", symbol, {"op": "definition_of", "symbol": symbol})

    for symbol in shared_idents:
        add("occurrences_of", symbol, {"op": "occurrences_of", "symbol": symbol})
    # A couple of single-occurrence identifiers too, so the case set isn't
    # exclusively the "shared across files" shape.
    single_idents = sorted(k for k, v in ident_counts.items() if v == 1)
    for symbol in rng.sample(single_idents, min(3, len(single_idents))):
        add("occurrences_of", symbol, {"op": "occurrences_of", "symbol": symbol})

    rng.shuffle(cases)
    return cases


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-id", default="sample_repo",
                        help="graph to generate from; default is the built-in fixture")
    parser.add_argument("--limit", type=int, default=None,
                        help="cap the number of generated cases")
    args = parser.parse_args()

    cases = generate(args.repo_id)
    if args.limit:
        cases = cases[:args.limit]

    from collections import Counter
    op_counts = Counter(c["expected"]["reference_op"]["op"] for c in cases)

    print(f"generated {len(cases)} cases from repo_id={args.repo_id!r}")
    for op, n in sorted(op_counts.items()):
        print(f"  {op:<16} {n}")

    DATASET_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATASET_PATH.write_text(json.dumps(cases, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {DATASET_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
