"""NetworkX graph construction, persistence (JSON), and loading.

Public API:
    build_graph(files: list[FileNode]) -> nx.DiGraph
    save_graph(graph: nx.DiGraph, repo_id: str) -> Path
    load_graph(repo_id: str) -> nx.DiGraph          # cached, contract signature
"""
from __future__ import annotations

import json
import functools
from pathlib import Path
from typing import Any

import networkx as nx
from networkx.readwrite import json_graph

from config import REPO_ROOT
from graph.extract import FileNode

# ---------------------------------------------------------------------------
# Storage location: {REPO_ROOT}/.graphs/{repo_id}.json
# ---------------------------------------------------------------------------

GRAPHS_DIR = REPO_ROOT / ".graphs"


def _graph_path(repo_id: str) -> Path:
    return GRAPHS_DIR / f"{repo_id}.json"


# ---------------------------------------------------------------------------
# Build a NetworkX DiGraph from extracted file data
# ---------------------------------------------------------------------------

def build_graph(files: list[FileNode]) -> nx.DiGraph:
    """Construct a dependency graph from extracted file nodes.

    Nodes: file paths (repo-relative, POSIX separators).
    Node attributes:
        - tier:   coverage tier ("deep", "occurrence-only", "unparseable")
        - lang:   tree-sitter language name (or None)
        - idents: sorted list of identifiers found in the file
        - defs:   list of {name, kind, line} definition dicts
    Edges: import relationships (A imports B -> edge from A to B).
    Edge attributes:
        - kind: "import"
    """
    g = nx.DiGraph()

    # Index: map file path -> FileNode for import resolution
    path_index: dict[str, FileNode] = {f.path: f for f in files}

    # Add all files as nodes
    for f in files:
        g.add_node(
            f.path,
            tier=f.tier,
            lang=f.lang,
            idents=sorted(f.idents),          # sorted for determinism
            defs=[{"name": d.name, "kind": d.kind, "line": d.line}
                  for d in f.defs],
        )

    # Build import edges — resolve import paths to file paths
    for f in files:
        if f.tier != "deep":
            continue
        for imp in f.import_paths:
            resolved = _resolve_import(imp, f.path, path_index)
            if resolved and resolved in path_index:
                g.add_edge(f.path, resolved, kind="import")

    return g


def _resolve_import(
    import_path: str,
    source_file: str,
    path_index: dict[str, FileNode],
) -> str | None:
    """Best-effort resolution of an import string to a repo-relative file path.

    Tries several strategies:
    1. Direct match (import_path is already a file path in the repo)
    2. Module-to-file mapping (e.g., "foo.bar" -> "foo/bar.py")
    3. Suffix match (e.g., "auth" -> "src/auth.py")

    Returns None if no match found. This is expected — external dependencies
    (stdlib, pip packages) won't resolve, and that's correct.
    """
    # 1. Direct path match
    if import_path in path_index:
        return import_path

    # 2. Dot-notation to path (Python, Java, Kotlin)
    dot_path = import_path.replace(".", "/")

    # Try common extensions for the source file's language
    source_lang = path_index.get(source_file)
    extensions = _lang_extensions(source_lang.lang if source_lang else None)

    for ext in extensions:
        candidate = f"{dot_path}{ext}"
        if candidate in path_index:
            return candidate
        # Also try as package init (Python)
        candidate_init = f"{dot_path}/__init__{ext}"
        if candidate_init in path_index:
            return candidate_init

    # 3. Suffix match — find a file whose path ends with the import
    clean = import_path.lstrip("./").rstrip("/")
    for ext in extensions:
        suffix = f"{clean}{ext}"
        for p in path_index:
            if p.endswith(suffix) or p.endswith(f"/{suffix}"):
                return p

    # 4. Bare name match — "auth" matches "src/auth.py"
    for ext in extensions:
        bare = f"{clean}{ext}"
        for p in path_index:
            parts = p.rsplit("/", 1)
            filename = parts[-1] if len(parts) > 1 else parts[0]
            if filename == bare:
                return p

    return None


def _lang_extensions(lang: str | None) -> list[str]:
    """Return file extensions to try for import resolution."""
    _MAP = {
        "python":      [".py"],
        "javascript":  [".js", ".jsx", ".ts", ".tsx"],
        "typescript":  [".ts", ".tsx", ".js", ".jsx"],
        "tsx":         [".tsx", ".ts", ".js", ".jsx"],
        "java":        [".java"],
        "go":          [".go"],
        "rust":        [".rs"],
        "c":           [".h", ".c"],
        "cpp":         [".hpp", ".h", ".cpp", ".cc"],
        "c_sharp":     [".cs"],
        "ruby":        [".rb"],
        "php":         [".php"],
        "kotlin":      [".kt", ".kts"],
        "html":        [".html", ".htm"],
        "css":         [".css"],
    }
    return _MAP.get(lang, [".py", ".js", ".ts", ".java", ".go", ".rs"])


# ---------------------------------------------------------------------------
# Save / Load — JSON node-link format
# ---------------------------------------------------------------------------

def save_graph(graph: nx.DiGraph, repo_id: str) -> Path:
    """Serialize a NetworkX graph to JSON and write to disk.

    Returns the path the graph was written to.
    """
    GRAPHS_DIR.mkdir(parents=True, exist_ok=True)
    path = _graph_path(repo_id)

    data = json_graph.node_link_data(graph)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # Invalidate the LRU cache for this repo_id
    load_graph.cache_clear()

    return path


def delete_graph(repo_id: str) -> bool:
    """Purge a repo's persisted graph. Returns True if a file was removed.
    Nothing currently calls this automatically — see B2B_AUDIT.md item 2."""
    path = _graph_path(repo_id)
    existed = path.exists()
    if existed:
        path.unlink()
    load_graph.cache_clear()
    return existed


@functools.lru_cache(maxsize=32)
def load_graph(repo_id: str) -> nx.DiGraph:
    """Load the persisted NetworkX graph for a repo. Cached across calls.

    This is the contract signature from GRAPH_QUERY_CONTRACT.md.
    The eval harness treats the return value as opaque — it calls load_graph
    and hands the result straight to execute_query.

    Raises FileNotFoundError if the graph has not been built yet.
    """
    path = _graph_path(repo_id)
    if not path.exists():
        raise FileNotFoundError(
            f"No graph for repo '{repo_id}'. Run /index first. "
            f"Expected at: {path}"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    return json_graph.node_link_graph(data)
