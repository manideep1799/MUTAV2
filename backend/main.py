"""
AI Open Source Mentor++ — API server.

    uvicorn main:app --reload
    http://127.0.0.1:8000/docs

Architecture matches TEMPPP design spec.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import settings
from indexing import index_repo
from rag_qa import ask_question
from pipeline.gate import run_gate
from issue_recommendation import recommend_issue
from learning_roadmap import generate_roadmap
from pr_readiness import check_pr_readiness
from maintainer_health import get_maintainer_health
from observability.metrics import get_metrics
from github_client import get_rate_limit_status

app = FastAPI(
    title="AI Open Source Mentor++",
    description="Deterministic change-impact analysis and repo onboarding.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # demo posture
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class IndexRequest(BaseModel):
    repo_url: str


class AskRequest(BaseModel):
    repo_url: str
    question: str


class BlastRadiusRequest(BaseModel):
    repo_url: str
    targets: list[str]
    max_hops: int = 3


class RecommendRequest(BaseModel):
    repo_url: str
    user_profile: str = "general contributor"


class RoadmapRequest(BaseModel):
    repo_url: str


class PRCheckRequest(BaseModel):
    diff_text: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
def root() -> dict:
    """Health check."""
    return {"status": "ok", "message": "AI Open Source Mentor++ is running"}


@app.get("/health")
def health_endpoint() -> dict:
    """GET /health -> {ok, indexed_repos}."""
    return {"ok": True}


@app.get("/metrics")
def metrics_endpoint() -> dict:
    """Self-improvement dashboard: per-target Mutagent eval scores.

    Reads what the offline optimize runs wrote to mutagent/reports/.
    There is deliberately no POST /optimize — the ADLC loop is CLI-only.
    """
    return get_metrics()


@app.post("/index")
def index_endpoint(req: IndexRequest):
    """Step 1: always call this first for a new repo."""
    try:
        return index_repo(req.repo_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/ask")
def ask_endpoint(req: AskRequest):
    """Council-gated hybrid RAG Q&A — repo must already be indexed.

    The council gate (Mutagent target #2/#4) classifies the question first.
    A question that fails clarity/scope/answerability/specificity is
    rejected with a reason before retrieval ever runs.
    """
    gate = run_gate(req.question)
    if not gate["passed"]:
        return {
            "passed": False,
            "reason": gate["reason"],
            "classification": {field: gate[field] for field in
                                ("clarity", "scope", "answerability", "specificity")},
        }

    try:
        result = ask_question(req.repo_url, req.question, route=gate["route"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"passed": True, "route": gate["route"], "sub_queries": gate["sub_queries"], **result}


@app.post("/recommend-issue")
def recommend_endpoint(req: RecommendRequest):
    """Returns issue_id null when nothing matches — a designed state, not an error."""
    try:
        return recommend_issue(req.repo_url, req.user_profile)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/recommend-issue")
def recommend_issue_get(repo_url: str):
    """GET convenience alias — for direct browser/curl access."""
    try:
        return recommend_issue(repo_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/roadmap")
def roadmap_endpoint(req: RoadmapRequest):
    """Graph-informed learning roadmap. Returns {roadmap, central_files}."""
    try:
        return generate_roadmap(req.repo_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/pr-check")
def pr_check_endpoint(req: PRCheckRequest):
    """PR readiness — paste a unified diff, get a readiness report + verdict."""
    try:
        return check_pr_readiness(req.diff_text)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/blast-radius")
def blast_radius_endpoint(req: BlastRadiusRequest):
    """The hero feature: what breaks if these files change."""
    from graph.blast_radius import blast_radius
    try:
        return blast_radius(req.repo_url, req.targets, req.max_hops)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/maintainer-health")
def maintainer_health_endpoint(repo_url: str):
    """GET /maintainer-health -> {score, mislabelled[], latency_days, scanned}."""
    try:
        return get_maintainer_health(repo_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/rate-limit")
def rate_limit_endpoint():
    """Current GitHub API rate limit status."""
    try:
        return get_rate_limit_status()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
