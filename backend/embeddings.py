"""
Two jobs:
1. chunk_text() — splits long text into overlapping token-sized pieces
2. embed_texts() — turns a list of text chunks into vectors using a local
   BGE model (sentence-transformers) — no API key, no quota, no rate limit
"""
import tiktoken
from config import settings

_encoding = tiktoken.get_encoding("cl100k_base")

_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        print(f"Loading local embedding model {settings.EMBEDDING_MODEL} (this may take a moment on first boot)...")
        _model = SentenceTransformer(settings.EMBEDDING_MODEL)
    return _model


def chunk_text(text: str, chunk_size: int = None, overlap: int = None) -> list[str]:
    """
    Splits text into overlapping chunks measured in tokens (not characters),
    so chunk size stays consistent regardless of language or formatting.
    """
    chunk_size = chunk_size or settings.CHUNK_SIZE
    overlap = overlap or settings.CHUNK_OVERLAP

    text = text.strip()
    if not text:
        return []

    tokens = _encoding.encode(text)
    if len(tokens) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(tokens):
        end = start + chunk_size
        chunk_tokens = tokens[start:end]
        chunks.append(_encoding.decode(chunk_tokens))
        start += chunk_size - overlap  # step forward, leaving "overlap" tokens repeated

    return chunks


def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Embeds a list of texts locally via a BGE sentence-transformers model.
    Returns one vector per input text, in the same order.
    """
    if not texts:
        return []

    model = _get_model()
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return vectors.tolist()
