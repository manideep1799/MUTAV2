"""
This is the RAG Q&A box: question -> embed -> vector search -> LLM with context -> answer.
"""
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
            # Connect to remote Ollama (Qwen) via ngrok using OpenAI compatible endpoint
            _client = OpenAI(
                api_key="ollama", # Ollama doesn't require a real key
                base_url=settings.OLLAMA_BASE_URL
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


def _generate_hypothetical_document(question: str) -> str:
    """
    HyDE: draft a short hypothetical passage that would answer `question`, so we can
    embed that passage instead of the raw question. A few sentences of plausible
    code/doc-shaped text sits closer in embedding space to the real chunks that would
    answer it than a short, vague user question does.
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


def ask_question(repo_url: str, question: str) -> dict:
    repo_url = parse_repo_url(repo_url)
    """
    Returns: {"answer": "...", "sources": ["src/app.py", "README.md"]}
    Raises a ValueError if the repo hasn't been indexed yet.
    """
    if collection_is_empty(repo_url):
        raise ValueError(f"Repo '{repo_url}' has not been indexed yet. Call /index first.")

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

    # Use Hybrid Retrieval (Vector + Graph Symbols). `question` (not the HyDE
    # passage) still drives symbol extraction and reranking below.
    documents, metadatas = hybrid_retrieve(
        repo_url, question, question_embedding, top_k=settings.TOP_K
    )

    documents, metadatas = rerank_documents(question, documents, metadatas, top_n=settings.RERANK_TOP_K)

    context = "\n\n---\n\n".join(
        f"[{meta['path']}]\n{doc}" for doc, meta in zip(documents, metadatas)
    )

    model_name = settings.OLLAMA_MODEL if settings.OLLAMA_BASE_URL else settings.LLM_MODEL
    
    response = _get_client().chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"},
        ],
    )

    answer = response.choices[0].message.content
    sources = sorted(set(meta["path"] for meta in metadatas))

    return {"answer": answer, "sources": sources}
