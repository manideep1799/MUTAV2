"""
Wraps Chroma so the rest of the app never has to think about the database directly.
Each repo gets its own "collection" so multiple repos can be indexed without mixing data.
"""
import chromadb
from config import settings

_client = chromadb.PersistentClient(
    path=settings.CHROMA_PERSIST_DIR,
    settings=chromadb.Settings(anonymized_telemetry=False)
)


import hashlib

def _collection_name(repo_url: str) -> str:
    # Chroma collection names must be 3-63 chars. We hash the URL to guarantee a safe, unique name.
    url_hash = hashlib.md5(repo_url.encode('utf-8')).hexdigest()
    return f"repo_{url_hash}"


def get_or_create_collection(repo_url: str):
    return _client.get_or_create_collection(name=_collection_name(repo_url))


def add_chunks(repo_url: str, ids: list[str], embeddings: list[list[float]],
               documents: list[str], metadatas: list[dict]) -> None:
    collection = get_or_create_collection(repo_url)
    collection.add(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)


def query(repo_url: str, query_embedding: list[float], top_k: int = None, paths: list[str] = None) -> dict:
    top_k = top_k or settings.TOP_K
    collection = get_or_create_collection(repo_url)
    
    where = None
    if paths:
        if len(paths) == 1:
            where = {"path": paths[0]}
        elif len(paths) > 1:
            where = {"path": {"$in": paths}}
            
    return collection.query(
        query_embeddings=[query_embedding], 
        n_results=top_k,
        where=where
    )


def collection_is_empty(repo_url: str) -> bool:
    collection = get_or_create_collection(repo_url)
    return collection.count() == 0


def delete_collection(repo_url: str) -> bool:
    """Purge a repo's indexed chunks. Nothing currently calls this
    automatically — see B2B_AUDIT.md item 2 (vector store lifecycle)."""
    try:
        _client.delete_collection(name=_collection_name(repo_url))
        return True
    except Exception:
        return False
