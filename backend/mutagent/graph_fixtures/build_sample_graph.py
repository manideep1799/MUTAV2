"""Builds a small, realistic repo graph and saves it via the real store.py path.

This stands in for a live indexed repo so target #3 (graph query generation)
can be built and dry-run validated before anyone has run POST /index against
a real GitHub URL. Uses backend.graph.store.save_graph() directly rather
than hand-writing JSON, so the fixture is guaranteed to match the exact
on-disk schema query_dsl.py actually consumes — no format drift possible
between the fixture and the real thing.

Run once: python -m mutagent.graph_fixtures.build_sample_graph
Produces: .graphs/sample_repo.json
"""
from __future__ import annotations

import networkx as nx

from graph.store import save_graph


def _node(tier: str, lang: str | None, idents: list[str], defs: list[dict]) -> dict:
    return {"tier": tier, "lang": lang, "idents": sorted(idents), "defs": defs}


def _def(name: str, kind: str, line: int) -> dict:
    return {"name": name, "kind": kind, "line": line}


def build() -> nx.DiGraph:
    g = nx.DiGraph()

    # --- deep-tier Python files, a plausible small web app -----------------
    g.add_node("src/auth.py", **_node(
        "deep", "python", ["authenticate", "User", "Session"],
        [_def("authenticate", "function", 12), _def("User", "class", 40)],
    ))
    g.add_node("src/session.py", **_node(
        "deep", "python", ["create_session", "Session", "User"],
        [_def("create_session", "function", 8)],
    ))
    g.add_node("src/api/login.py", **_node(
        "deep", "python", ["login_handler", "Session"],
        [_def("login_handler", "function", 5)],
    ))
    g.add_node("src/api/logout.py", **_node(
        "deep", "python", ["logout_handler", "Session"],
        [_def("logout_handler", "function", 5)],
    ))
    g.add_node("src/api/admin.py", **_node(
        "deep", "python", ["delete_user", "promote_admin", "User"],
        [_def("delete_user", "function", 20), _def("promote_admin", "function", 34)],
    ))
    g.add_node("src/db/models.py", **_node(
        "deep", "python", ["User", "Session"],
        [_def("User", "class", 3), _def("Session", "class", 22)],
    ))
    g.add_node("src/db/queries.py", **_node(
        "deep", "python", ["find_user", "save_session", "User", "Session"],
        [_def("find_user", "function", 9), _def("save_session", "function", 18)],
    ))
    g.add_node("src/billing/charge.py", **_node(
        "deep", "python", ["charge_card", "User"],
        [_def("charge_card", "function", 14)],
    ))
    g.add_node("src/billing/webhook.py", **_node(
        "deep", "python", ["handle_webhook", "charge_card"],
        [_def("handle_webhook", "function", 6)],
    ))
    g.add_node("src/utils/format.py", **_node(
        "deep", "python", ["format_currency"],
        [_def("format_currency", "function", 2)],
    ))
    g.add_node("src/reports/summary.py", **_node(
        "deep", "python", ["build_summary", "find_user", "charge_card", "format_currency"],
        [_def("build_summary", "function", 11)],
    ))
    g.add_node("tests/test_auth.py", **_node(
        "deep", "python", ["test_authenticate", "authenticate"],
        [_def("test_authenticate", "function", 4)],
    ))
    g.add_node("tests/test_session.py", **_node(
        "deep", "python", ["test_create_session", "create_session"],
        [_def("test_create_session", "function", 4)],
    ))

    # --- occurrence-only tier: PHP has no import query, per GRAPH_EXTRACTION.md,
    # so these carry identifiers but zero defs/import edges -----------------
    g.add_node("legacy/parser.php", **_node(
        "occurrence-only", "php", ["parse_config", "load_settings"], [],
    ))
    g.add_node("legacy/helpers.php", **_node(
        "occurrence-only", "php", ["parse_config", "format_output"], [],
    ))

    # --- unparseable: no grammar match, no lang -----------------------------
    g.add_node("docs/README.md", **_node("unparseable", None, [], []))

    # --- import edges --------------------------------------------------------
    g.add_edge("src/session.py", "src/auth.py", kind="import")
    g.add_edge("src/api/login.py", "src/session.py", kind="import")
    g.add_edge("src/api/logout.py", "src/session.py", kind="import")
    g.add_edge("src/api/admin.py", "src/auth.py", kind="import")
    g.add_edge("src/db/queries.py", "src/db/models.py", kind="import")
    g.add_edge("src/auth.py", "src/db/models.py", kind="import")
    g.add_edge("src/session.py", "src/db/models.py", kind="import")
    g.add_edge("src/billing/charge.py", "src/db/models.py", kind="import")
    g.add_edge("src/billing/webhook.py", "src/billing/charge.py", kind="import")
    g.add_edge("src/reports/summary.py", "src/db/queries.py", kind="import")
    g.add_edge("src/reports/summary.py", "src/billing/charge.py", kind="import")
    g.add_edge("src/reports/summary.py", "src/utils/format.py", kind="import")
    g.add_edge("tests/test_auth.py", "src/auth.py", kind="import")
    g.add_edge("tests/test_session.py", "src/session.py", kind="import")

    return g


if __name__ == "__main__":
    graph = build()
    path = save_graph(graph, "sample_repo")
    print(f"built {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges")
    print(f"saved to {path}")
