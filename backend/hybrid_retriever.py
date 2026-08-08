import re
from typing import Any

from vector_store import query as vector_query
from graph.store import load_graph
from graph.query_dsl import execute_query
from github_client import parse_repo_url

from config import load_prompt
from clients.llm_client import json_complete
from observability.tracer import trace

IDENT_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")

def _extract_identifiers(text: str) -> list[str]:
    common_words = {
        "how", "what", "where", "why", "when", "who", "which", "the", "a",
        "an", "and", "or", "not", "is", "are", "was", "were", "be", "been",
        "to", "of", "in", "for", "on", "with", "by", "at", "from", "auth",
        "login", "deploy", "code", "file", "function", "class", "method",
        "change", "break", "import", "package", "module"
    }
    candidates = IDENT_RE.findall(text)
    return [c for c in candidates if c.lower() not in common_words and len(c) > 2]

def _get_graph_paths_for_symbols(repo_id: str, symbols: list[str]) -> list[str]:
    try:
        graph = load_graph(repo_id)
    except Exception:
        return []

    paths = set()
    for sym in symbols:
        def_res = execute_query({"op": "definition_of", "symbol": sym}, graph)
        for n in def_res.get("nodes", []):
            paths.add(n["path"])
        occ_res = execute_query({"op": "occurrences_of", "symbol": sym}, graph)
        for n in occ_res.get("nodes", []):
            paths.add(n["path"])

    return list(paths)

def _rrf_fuse(dense: list[dict[str, Any]], sparse: list[dict[str, Any]], k: int = 60) -> list[dict[str, Any]]:
    scores: dict[tuple[str, int, int], float] = {}
    chunk_map: dict[tuple[str, int, int], dict[str, Any]] = {}

    def get_key(c: dict[str, Any]) -> tuple[str, int, int]:
        return (c["path"], c.get("start_line", 0), c.get("end_line", 0))

    for rank, chunk in enumerate(dense, 1):
        key = get_key(chunk)
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
        chunk_map[key] = chunk

    for rank, chunk in enumerate(sparse, 1):
        key = get_key(chunk)
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
        chunk_map[key] = chunk

    sorted_keys = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)
    return [chunk_map[key] for key in sorted_keys]

def hybrid_retrieve(repo_url: str, question: str, question_embedding: list[float], top_k: int = 20, route: str = "hybrid") -> tuple[list[str], list[dict[str, Any]]]:
    """
    Returns (documents, metadatas) using Hybrid Search (Dense + Graph-aware Sparse).

    `route` comes from the council gate (Target #2/#4): "vector" skips the
    graph-aware sparse search and structural-facts injection entirely, since
    the gate already decided this question doesn't need graph structure.
    "graph" and "hybrid" both run the full pipeline below — "graph" without a
    dedicated graph-only path isn't a documented gate outcome, so treat it
    the same as "hybrid" rather than under-serving it.
    """
    repo_url = parse_repo_url(repo_url)
    slug = repo_url.rstrip("/").split("github.com/")[-1].removesuffix(".git")
    repo_id = slug.replace("/", "__")
    use_graph = route != "vector"

    # 1. Dense vector search
    dense_results_raw = vector_query(repo_url, question_embedding, top_k=top_k)
    dense_chunks = []
    if dense_results_raw["documents"] and dense_results_raw["documents"][0]:
        for doc, meta in zip(dense_results_raw["documents"][0], dense_results_raw["metadatas"][0]):
            dense_chunks.append({"text": doc, **meta})

    # 2. Sparse Identifier-Index search (skipped when the gate routed pure "vector")
    sparse_chunks = []
    if use_graph:
        symbols = _extract_identifiers(question)
        graph_paths = _get_graph_paths_for_symbols(repo_id, symbols) if symbols else []

        if graph_paths:
            sparse_results_raw = vector_query(repo_url, question_embedding, top_k=top_k, paths=graph_paths)
            if sparse_results_raw["documents"] and sparse_results_raw["documents"][0]:
                for doc, meta in zip(sparse_results_raw["documents"][0], sparse_results_raw["metadatas"][0]):
                    sparse_chunks.append({"text": doc, **meta})

    # 3. Graph structural facts injection
    # Execute an AI-generated structural AST query if the Gate permitted graph traversal
    graph_facts_chunk = None
    if use_graph:
        try:
            graph = load_graph(repo_id)
            prompt = load_prompt("graph_query").format(question=question)
            parsed_json, raw_text, latency_ms = json_complete(prompt, temperature=0.1, max_tokens=1024)

            trace(component="graph_query", prompt=prompt, raw_output=raw_text, latency_ms=latency_ms, extra={"question": question})

            result = execute_query(parsed_json, graph)
            nodes = result.get("nodes", [])
            if nodes:
                op = parsed_json.get("op", "unknown")
                target = parsed_json.get("targets", [""])[0] if "targets" in parsed_json else parsed_json.get("symbol", "")
                lines = [f"- {n['path']} ({n.get('hops', 1)} hop(s), {n.get('reason', '')})" for n in nodes[:20]]
                fact_text = f"Graph results for {op} on {target}:\n" + "\n".join(lines)
                graph_facts_chunk = {"text": fact_text, "path": nodes[0]['path'], "start_line": -1, "end_line": -1}
        except Exception:
            pass
            
    # Fuse dense and sparse
    fused_chunks = _rrf_fuse(dense_chunks, sparse_chunks, k=60)
    
    # Prepend graph facts if available
    if graph_facts_chunk:
        fused_chunks.insert(0, graph_facts_chunk)
        
    docs = [c["text"] for c in fused_chunks]
    metas = [{"path": c["path"], "start_line": c.get("start_line", 0), "end_line": c.get("end_line", 0)} for c in fused_chunks]
    
    return docs[:top_k], metas[:top_k]
