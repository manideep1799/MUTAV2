"""Production home of Mutagent target #2 & #4's prompt (mutagent/prompts/council.txt).

Runs as the first stage of POST /ask: classifies the query on four gate
criteria (clarity, scope, answerability, specificity), picks a retrieval
route (vector/graph/hybrid), and splits multi-intent queries into
sub-questions. A query that fails any gate criterion is rejected before it
ever reaches retrieval — Target #4 (Router) grades the same `route` field
against its own dataset, so there's nothing extra to build for it here.
"""
from __future__ import annotations

from functools import lru_cache

from config import load_prompt
from clients.llm_client import extract_json, complete
from observability.tracer import trace

_VALID_ROUTES = {"vector", "graph", "hybrid"}
_GATE_FIELDS = ("clarity", "scope", "answerability", "specificity")


@lru_cache(maxsize=256)
def run_gate(query: str) -> dict:
    """Returns:
        {passed, clarity, scope, answerability, specificity,
         route, sub_queries: [{text, route}, ...], reason}

    `reason` is only meaningful when passed is False. A response that can't
    be parsed at all fails closed rather than defaulting to passed.

    Cached by exact query text: classification is a pure function of the
    question at temperature=0.1, and repeat questions are common in a demo
    session. A cache hit also means no duplicate trace line is written.
    """
    prompt = load_prompt("council").format(query=query)
    raw_output, latency_ms = complete(prompt, temperature=0.1, json_mode=True)

    trace(component="council", prompt=prompt, raw_output=raw_output,
          latency_ms=latency_ms, extra={"query": query})

    parsed = extract_json(raw_output)
    if parsed is None:
        return {
            "passed": False,
            "clarity": False, "scope": False, "answerability": False, "specificity": False,
            "route": "hybrid",
            "sub_queries": [{"text": query, "route": "hybrid"}],
            "reason": f"Could not parse gate classification: {raw_output[:200]!r}",
        }

    flags = {field: bool(parsed.get(field, False)) for field in _GATE_FIELDS}
    passed = all(flags.values())

    route = parsed.get("route")
    if route not in _VALID_ROUTES:
        route = "hybrid"

    raw_sub_queries = parsed.get("sub_queries") or [{"text": query, "route": route}]
    sub_queries = []
    for sq in raw_sub_queries:
        text = sq.get("text") if isinstance(sq, dict) else None
        sq_route = sq.get("route") if isinstance(sq, dict) else None
        if sq_route not in _VALID_ROUTES:
            sq_route = route
        sub_queries.append({"text": text or query, "route": sq_route})

    reason = ""
    if not passed:
        failed = [field for field, ok in flags.items() if not ok]
        reason = f"Query failed the gate on: {', '.join(failed)}."

    return {"passed": passed, **flags, "route": route,
            "sub_queries": sub_queries, "reason": reason}
