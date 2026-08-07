"""backend.b2b — enterprise data model and features layered on the core engine.

Per the B2B Implementation Plan: everything here reuses the existing
parsing/graph/retrieval engine (indexing.py, graph/, rag_qa.py,
issue_recommendation.py, maintainer_health.py) unmodified. This package only
adds the organization/member layer and the enterprise-framed endpoints that
sit on top of it.

Demo-scope persistence (store.py): sqlite3, no auth. org_id/member_id are
passed as plain request params, the same way repo_url already is elsewhere
in this app. Real login/session auth is out of scope for this pass — see
CHANGES.md and B2B_AUDIT.md.
"""
