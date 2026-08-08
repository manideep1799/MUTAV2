"""
This is diagram box #1: GitHub repo -> Indexing pipeline -> Knowledge base.

index_repo() is the one function everything else depends on. Run it once per
repo before using any other module.
"""
from github_client import fetch_repo_files, parse_repo_url
from embeddings import chunk_text, embed_texts
from vector_store import add_chunks


def index_repo(repo_url: str) -> dict:
    """
    Fetches every indexable file in the repo, chunks it, embeds the chunks,
    and stores them in the vector store under this repo's collection.

    Returns a small summary dict so the caller (e.g. an API endpoint) can
    show progress: {"files_indexed": 42, "chunks_created": 310}
    """
    repo_url = parse_repo_url(repo_url)
    files, total_files = fetch_repo_files(repo_url)

    # 1. Build the structural Graph database (Tree-Sitter + NetworkX)
    graph_nodes_count = 0
    graph_edges_count = 0
    try:
        from graph.extract import extract_file
        from graph.store import build_graph, save_graph

        slug = repo_url.rstrip("/").split("github.com/")[-1].removesuffix(".git")
        repo_id = slug.replace("/", "__")

        file_nodes = []
        for f in files:
            source_bytes = f["content"].encode('utf-8')
            file_nodes.append(extract_file(source_bytes, f["path"]))

        g = build_graph(file_nodes)
        save_graph(g, repo_id)
        graph_nodes_count = len(g.nodes)
        graph_edges_count = len(g.edges)
    except Exception as e:
        print(f"Warning: Failed to build structural graph: {e}")

    # 2. Build the semantic Vector database (ChromaDB)
    all_chunks: list[str] = []
    all_metadatas: list[dict] = []
    all_ids: list[str] = []

    for file in files:
        chunks = chunk_text(file["content"])
        for i, chunk in enumerate(chunks):
            all_chunks.append(chunk)
            all_metadatas.append({
                "path": file["path"],
                "type": file["type"],
                "chunk_index": i,
            })
            all_ids.append(f"{file['path']}::{i}")

    if not all_chunks:
        return {
            "files_indexed": 0,
            "chunks_created": 0,
            "total_repo_files": total_files,
            "graph_nodes": graph_nodes_count,
            "graph_edges": graph_edges_count,
        }

    # Encode in batches so one huge repo doesn't build a single oversized
    # tensor for the local embedding model.
    batch_size = 100
    for start in range(0, len(all_chunks), batch_size):
        end = start + batch_size
        batch_embeddings = embed_texts(all_chunks[start:end])
        add_chunks(
            repo_url=repo_url,
            ids=all_ids[start:end],
            embeddings=batch_embeddings,
            documents=all_chunks[start:end],
            metadatas=all_metadatas[start:end],
        )

    return {
        "files_indexed": len(files),
        "chunks_created": len(all_chunks),
        "total_repo_files": total_files,
        "graph_nodes": graph_nodes_count,
        "graph_edges": graph_edges_count,
    }
