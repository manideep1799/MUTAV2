"""
This is the RAG Q&A box: question -> embed -> vector search -> LLM with context -> answer.
"""
from functools import lru_cache
from typing import Iterator

from openai import OpenAI
from embeddings import embed_texts
from vector_store import query, collection_is_empty
from github_client import parse_repo_url
from config import settings, load_prompt
from reranker import rerank_documents

from hybrid_retriever import hybrid_retrieve

_client = None

def _get_client():
    global _client
    if _client is None:
        if settings.OLLAMA_BASE_URL:
            # Connect to remote Ollama via ngrok using the OpenAI-compatible endpoint.
            # ngrok's free-tier tunnels intercept unheadered requests with an HTML
            # "visit site" warning page instead of proxying through to Ollama — the
            # OpenAI SDK won't send this header on its own, so every chat completion
            # would otherwise get an HTML page back instead of a JSON response.
            _client = OpenAI(
                api_key="ollama", # Ollama doesn't require a real key
                base_url=settings.OLLAMA_BASE_URL,
                default_headers={"ngrok-skip-browser-warning": "true"},
            )
        else:
            # Fallback to Groq
            _client = OpenAI(
                api_key=settings.GROQ_API_KEY,
                base_url="https://api.groq.com/openai/v1"
            )
    return _client

SYSTEM_PROMPT = """You are a helpful assistant answering questions about a specific
GitHub repository. Only use the provided context to answer. If the context doesn't
contain the answer, say so plainly instead of guessing."""


@lru_cache(maxsize=256)
def _generate_hypothetical_document(question: str) -> str:
    """
    HyDE: draft a short hypothetical passage that would answer `question`, so we can
    embed that passage instead of the raw question. A few sentences of plausible
    code/doc-shaped text sits closer in embedding space to the real chunks that would
    answer it than a short, vague user question does.

    Cached by question text: this is a pure function of the question (it doesn't
    touch the repo), and the same question is common across a demo session.
    """
    prompt = load_prompt("hyde").format(question=question)
    model_name = settings.OLLAMA_MODEL if settings.OLLAMA_BASE_URL else settings.LLM_MODEL

    response = _get_client().chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=300,
    )
    return (response.choices[0].message.content or "").strip()


def _retrieve_context(repo_url: str, question: str, route: str) -> tuple[list[str], list[dict]]:
    """HyDE + hybrid retrieval + rerank for a single question. Shared by the
    single-question path and by each sub-query in a multi-intent fan-out."""
    embedding_text = question
    if settings.HYDE_ENABLED:
        try:
            hypothetical_doc = _generate_hypothetical_document(question)
            if hypothetical_doc:
                embedding_text = hypothetical_doc
        except Exception:
            # HyDE is a retrieval-quality boost, not a hard dependency — fall back
            # to embedding the raw question if the LLM call fails.
            pass

    question_embedding = embed_texts([embedding_text])[0]

    # `question` (not the HyDE passage) still drives symbol extraction and reranking.
    documents, metadatas = hybrid_retrieve(
        repo_url, question, question_embedding, top_k=settings.TOP_K, route=route
    )
    return rerank_documents(question, documents, metadatas, top_n=settings.RERANK_TOP_K)


def _distinct_sub_queries(sub_queries: list[dict] | None, question: str, route: str) -> list[dict]:
    """De-dupes the gate's sub_queries by text. Falls back to a single entry
    (the whole question) when the gate found nothing or only one question."""
    candidates = [sq for sq in (sub_queries or []) if sq.get("text")]
    if not candidates:
        return [{"text": question, "route": route}]

    seen: set[str] = set()
    distinct = []
    for sq in candidates:
        key = sq["text"].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        distinct.append(sq)
    return distinct or [{"text": question, "route": route}]


def _build_context(repo_url: str, question: str, route: str, sub_queries: list[dict] | None) -> tuple[str, list[str]]:
    """
    Multi-intent fan-out: when the council gate split the question into more
    than one distinct sub-question, retrieve for each separately (own text,
    own route) and merge the chunk sets before answering once. A single
    retrieval pass over a compound question tends to only surface chunks for
    whichever intent dominates the embedding.
    """
    distinct = _distinct_sub_queries(sub_queries, question, route)

    if len(distinct) > 1:
        documents: list[str] = []
        metadatas: list[dict] = []
        seen_chunks: set[tuple[str, int, int]] = set()
        for sq in distinct:
            docs, metas = _retrieve_context(repo_url, sq["text"], sq.get("route", route))
            for doc, meta in zip(docs, metas):
                key = (meta["path"], meta.get("start_line", 0), meta.get("end_line", 0))
                if key in seen_chunks:
                    continue
                seen_chunks.add(key)
                documents.append(doc)
                metadatas.append(meta)
    else:
        documents, metadatas = _retrieve_context(repo_url, question, route)

    context = "\n\n---\n\n".join(
        f"[{meta['path']}]\n{doc}" for doc, meta in zip(documents, metadatas)
    )
    sources = sorted(set(meta["path"] for meta in metadatas))
    return context, sources


def ensure_indexed(repo_url: str) -> str:
    """Normalizes repo_url and raises ValueError if it hasn't been indexed yet."""
    repo_url = parse_repo_url(repo_url)
    if collection_is_empty(repo_url):
        raise ValueError(f"Repo '{repo_url}' has not been indexed yet. Call /index first.")
    return repo_url


def ask_question(repo_url: str, question: str, route: str = "hybrid", sub_queries: list[dict] | None = None) -> dict:
    """
    Returns: {"answer": "...", "sources": ["src/app.py", "README.md"]}
    Raises a ValueError if the repo hasn't been indexed yet.

    `route` is the council gate's routing decision ("vector" | "graph" |
    "hybrid"); it decides whether graph-aware retrieval runs at all. `sub_queries`
    is the gate's multi-intent split; more than one distinct entry triggers a
    fan-out retrieval (see _build_context). Callers that don't run the gate
    (e.g. tests) get the previous single-question full-hybrid behavior.
    """
    repo_url = ensure_indexed(repo_url)
    context, sources = _build_context(repo_url, question, route, sub_queries)

    model_name = settings.OLLAMA_MODEL if settings.OLLAMA_BASE_URL else settings.LLM_MODEL

    response = _get_client().chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"},
        ],
    )

    answer = response.choices[0].message.content
    return {"answer": answer, "sources": sources}


def ask_question_stream(repo_url: str, question: str, route: str = "hybrid", sub_queries: list[dict] | None = None) -> Iterator[str | list[str]]:
    """
    Streaming twin of ask_question(). Yields answer text chunks as the LLM
    generates them, then a final list[str] of sources as the last item — the
    caller tells the two apart by type. Retrieval (HyDE, hybrid search,
    rerank) happens up front, same as the non-streaming path; only the final
    synthesis call is streamed, since that's the slow, user-visible part.
    Raises a ValueError up front if the repo hasn't been indexed yet.
    """
    repo_url = ensure_indexed(repo_url)
    context, sources = _build_context(repo_url, question, route, sub_queries)

    model_name = settings.OLLAMA_MODEL if settings.OLLAMA_BASE_URL else settings.LLM_MODEL

    stream = _get_client().chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"},
        ],
        stream=True,
    )

    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta

    yield sources
