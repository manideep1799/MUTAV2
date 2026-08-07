"""
AI Open Source Mentor++ — API server.

    uvicorn main:app --reload
    http://127.0.0.1:8000/docs

Architecture matches TEMPPP design spec.
"""
from __future__ import annotations

import json

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config import settings, repo_id_from_url
from indexing import index_repo
from vector_store import delete_collection
from graph.store import delete_graph
from github_client import parse_repo_url
from rag_qa import ask_question_stream
from pipeline.gate import run_gate
from issue_recommendation import recommend_issue
from learning_roadmap import generate_roadmap
from pr_readiness import check_pr_readiness
from maintainer_health import get_maintainer_health
from observability.metrics import get_metrics
from github_client import get_rate_limit_status

from b2b import store as b2b_store
from b2b.roster import get_roster
from b2b.governance import get_governance_report
from graph.test_selection import select_tests
from graph.reviewer_routing import suggest_reviewers

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

b2b_store.init_db()


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


class TestSelectionRequest(BaseModel):
    repo_url: str
    targets: list[str]
    max_hops: int = 3


class ReviewerRoutingRequest(BaseModel):
    repo_url: str
    targets: list[str]
    pr_author: str | None = None
    top_n: int = 2
    max_hops: int = 3


class OrgCreateRequest(BaseModel):
    name: str


class MemberCreateRequest(BaseModel):
    name: str
    email: str
    skill_profile: str = ""


class RepoRegisterRequest(BaseModel):
    repo_url: str


class IssueTagRequest(BaseModel):
    repo_url: str
    issue_number: int
    tag: str
    subsystem: str = ""
    tagged_by: str = ""


class AssignIssueRequest(BaseModel):
    repo_url: str
    user_profile: str = "general contributor"


class RoadmapStatusRequest(BaseModel):
    repo_url: str
    status: str  # not_started | in_progress | completed


class MemberPRCheckRequest(BaseModel):
    repo_url: str
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


@app.delete("/index")
def delete_index_endpoint(repo_url: str):
    """Purge a repo's indexed chunks + graph. A fix for the vector-store/
    graph lifecycle gap flagged in B2B_AUDIT.md item 2 — nothing calls this
    automatically yet (no session/org-boundary auto-wipe), but the mechanism
    to actually delete data now exists, which it didn't before."""
    try:
        normalized = parse_repo_url(repo_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    vector_deleted = delete_collection(normalized)
    graph_deleted = delete_graph(repo_id_from_url(normalized))
    return {"repo_url": normalized, "vector_collection_deleted": vector_deleted, "graph_deleted": graph_deleted}


_META_MARKER = "\n\n<<<META>>>"


@app.post("/ask")
def ask_endpoint(req: AskRequest):
    """Council-gated, streamed hybrid RAG Q&A — repo must already be indexed.

    The council gate (Mutagent target #2/#4) classifies the question first.
    A question that fails clarity/scope/answerability/specificity is
    rejected as plain JSON ({answer, sources: [], passed: false, reason,
    classification}) with no retrieval or LLM call. A passing question
    streams the answer as plain text as the LLM generates it, followed by
    a "\\n\\n<<<META>>>{json}" trailer carrying sources/route/sub_queries —
    the frontend tells the two response shapes apart by Content-Type
    (application/json vs text/plain).
    """
    gate = run_gate(req.question)
    if not gate["passed"]:
        return {
            "answer": f"I can't answer that as asked — {gate['reason']}",
            "sources": [],
            "passed": False,
            "reason": gate["reason"],
            "classification": {field: gate[field] for field in
                                ("clarity", "scope", "answerability", "specificity")},
            "route": gate["route"],
            "sub_queries": gate["sub_queries"],
        }

    stream = ask_question_stream(req.repo_url, req.question,
                                  route=gate["route"], sub_queries=gate["sub_queries"])
    try:
        # Retrieval + the first streamed token happen here, up front — this is what
        # surfaces "repo not indexed" as a real 400 instead of a broken stream.
        first_piece = next(stream)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    def generate():
        piece = first_piece
        while not isinstance(piece, list):
            yield piece
            piece = next(stream)
        meta = {"passed": True, "route": gate["route"], "sub_queries": gate["sub_queries"], "sources": piece}
        yield _META_MARKER + json.dumps(meta)

    return StreamingResponse(generate(), media_type="text/plain")


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


# ---------------------------------------------------------------------------
# B2B — per B2B_Implementation_Plan.md. Same engine as above; these routes
# add the enterprise data model (org/member/repo) and enterprise framing on
# top of it. Demo-scope: no auth, org_id/member_id are plain request params.
# ---------------------------------------------------------------------------

@app.post("/b2b/test-selection")
def test_selection_endpoint(req: TestSelectionRequest):
    """§3.2 — blast radius of the changed files, filtered to test files.

    "Run these first, full suite on merge" — not a replacement for the full
    suite. Reflection/dynamic dispatch can create edges the static parser
    can't see, so this is test *selection*, not test *proving*.
    """
    from config import repo_id_from_url
    try:
        result = select_tests(req.targets, repo_id_from_url(req.repo_url), req.max_hops)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    result["disclaimer"] = (
        "Run these first, then the full suite on merge — this is test "
        "selection based on static import/identifier analysis, not proof "
        "that untouched tests can't also break."
    )
    return result


@app.post("/b2b/reviewer-routing")
def reviewer_routing_endpoint(req: ReviewerRoutingRequest):
    """§3.4 — route a PR to whoever owns the files/functions actually in the
    blast radius, by recent commit authorship. No model call — deterministic."""
    try:
        result = suggest_reviewers(
            req.targets, req.repo_url,
            top_n=req.top_n, pr_author=req.pr_author, max_hops=req.max_hops,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/b2b/orgs")
def create_org_endpoint(req: OrgCreateRequest):
    try:
        return b2b_store.create_organization(req.name)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/b2b/orgs")
def list_orgs_endpoint():
    return b2b_store.list_organizations()


@app.post("/b2b/orgs/{org_id}/members")
def create_member_endpoint(org_id: int, req: MemberCreateRequest):
    try:
        return b2b_store.create_member(org_id, req.name, req.email, req.skill_profile)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/b2b/orgs/{org_id}/members")
def list_members_endpoint(org_id: int):
    return b2b_store.list_members(org_id)


@app.post("/b2b/orgs/{org_id}/repos")
def register_repo_endpoint(org_id: int, req: RepoRegisterRequest):
    try:
        return b2b_store.register_repo(org_id, req.repo_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/b2b/orgs/{org_id}/repos")
def list_repos_endpoint(org_id: int):
    return b2b_store.list_repos(org_id)


@app.post("/b2b/orgs/{org_id}/issues/tag")
def tag_issue_endpoint(org_id: int, req: IssueTagRequest):
    """Team-lead-facing tagging (§3.3): mark an issue once ('good-first-task',
    subsystem) instead of re-explaining it per assignment."""
    try:
        return b2b_store.tag_issue(
            org_id, req.repo_url, req.issue_number, req.tag, req.subsystem, req.tagged_by,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/b2b/orgs/{org_id}/issues/tags")
def list_tagged_issues_endpoint(org_id: int, repo_url: str):
    return b2b_store.list_tagged_issues(org_id, repo_url)


@app.post("/b2b/members/{member_id}/assign")
def assign_issue_endpoint(member_id: int, req: AssignIssueRequest):
    """§3.3 ticket routing: reuses the unchanged issue-recommendation engine
    (and its safe-refusal behavior — issue_id null on no match), then
    records the assignment against this member for the manager view."""
    try:
        recommendation = recommend_issue(req.repo_url, req.user_profile)
        assignment = b2b_store.assign_issue(
            member_id, req.repo_url,
            recommendation.get("issue_id"), recommendation.get("title") or "",
            recommendation.get("rationale", ""),
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"recommendation": recommendation, "assignment": assignment}


@app.get("/b2b/members/{member_id}/assignments")
def list_assignments_endpoint(member_id: int):
    return b2b_store.list_assigned_issues(member_id)


@app.post("/b2b/members/{member_id}/roadmap-status")
def set_roadmap_status_endpoint(member_id: int, req: RoadmapStatusRequest):
    try:
        return b2b_store.set_roadmap_status(member_id, req.repo_url, req.status)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/b2b/members/{member_id}/pr-check")
def member_pr_check_endpoint(member_id: int, req: MemberPRCheckRequest):
    """Reuses the unchanged PR-readiness check, then logs the verdict against
    this member so the manager view can show a PR-readiness trend."""
    try:
        result = check_pr_readiness(req.diff_text)
        b2b_store.record_pr_readiness(
            member_id, req.repo_url, result.get("verdict"),
            result["checklist"]["diff_size_lines"], result["checklist"]["has_tests"],
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@app.get("/b2b/orgs/{org_id}/roster")
def roster_endpoint(org_id: int):
    """§3.3 manager view: roster + per-member roadmap progress + PR-readiness
    history, replacing manual status-chasing."""
    return get_roster(org_id)


@app.get("/b2b/team-health")
def team_health_endpoint(repo_url: str):
    """§3.6 — the maintainer-health target, repointed. Same function as
    GET /maintainer-health; this alias exists because at the enterprise buyer
    it's framed as internal ticket-queue/process health, not OSS triage, and
    a distinct route keeps that framing legible in the API surface itself."""
    try:
        return get_maintainer_health(repo_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/b2b/governance-report")
def governance_report_endpoint():
    """§3.5 — /metrics reframed as the artifact a security/compliance
    reviewer asks for: per-component score, baseline vs. current, last
    evaluated. No new evaluation logic; see governance.py for what's
    honestly not tracked yet (dataset/rubric versioning)."""
    return get_governance_report()
