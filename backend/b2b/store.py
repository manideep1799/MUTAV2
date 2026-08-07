"""Demo-scope persistence for the B2B data model (plan §2).

Plain sqlite3 — no ORM, matching this codebase's existing preference for
the simplest tool that works (Chroma for vectors, JSON files for the graph).
No auth: org_id/member_id are passed as plain request params, the same way
repo_url already is. Real login/session/JWT auth is out of scope for this
pass; see B2B_AUDIT.md for what that would take.

Tables map directly to plan §2's data model, with one addition
(member_roadmap_status) to make "per-member roadmap progress" concrete:
this app's roadmap generation (learning_roadmap.py) is stateless free-text,
not a checklist, so progress is tracked as a status
(not_started/in_progress/completed) per (member, repo) rather than a
percentage — that's the honest granularity available without inventing a
roadmap step format the rest of the app doesn't use.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from config import REPO_ROOT

DB_PATH = REPO_ROOT / "backend" / "data" / "b2b.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS organizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    test_selection_threshold INTEGER NOT NULL DEFAULT 3,
    reviewer_routing_enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL REFERENCES organizations(id),
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    skill_profile TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(org_id, email)
);

CREATE TABLE IF NOT EXISTS org_repos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL REFERENCES organizations(id),
    repo_url TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(org_id, repo_url)
);

CREATE TABLE IF NOT EXISTS tagged_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL REFERENCES organizations(id),
    repo_url TEXT NOT NULL,
    issue_number INTEGER NOT NULL,
    tag TEXT NOT NULL,
    subsystem TEXT NOT NULL DEFAULT '',
    tagged_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(org_id, repo_url, issue_number, tag)
);

CREATE TABLE IF NOT EXISTS assigned_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL REFERENCES members(id),
    repo_url TEXT NOT NULL,
    issue_number INTEGER,
    issue_title TEXT NOT NULL DEFAULT '',
    rationale TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'assigned',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pr_readiness_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL REFERENCES members(id),
    repo_url TEXT NOT NULL DEFAULT '',
    verdict TEXT,
    diff_size_lines INTEGER,
    has_tests INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS member_roadmap_status (
    member_id INTEGER NOT NULL REFERENCES members(id),
    repo_url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'not_started',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (member_id, repo_url)
);
"""

_VALID_ROADMAP_STATUSES = {"not_started", "in_progress", "completed"}


@contextmanager
def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(_SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(r: sqlite3.Row | None) -> dict | None:
    return dict(r) if r is not None else None


def _rows(rs: list[sqlite3.Row]) -> list[dict]:
    return [dict(r) for r in rs]


# ---------------------------------------------------------------------------
# Organizations
# ---------------------------------------------------------------------------

def create_organization(name: str) -> dict:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO organizations (name, created_at) VALUES (?, ?)",
            (name, _now()),
        )
        org_id = cur.lastrowid
    return get_organization(org_id)


def get_organization(org_id: int) -> dict | None:
    with _connect() as conn:
        return _row(conn.execute(
            "SELECT * FROM organizations WHERE id = ?", (org_id,)
        ).fetchone())


def list_organizations() -> list[dict]:
    with _connect() as conn:
        return _rows(conn.execute(
            "SELECT * FROM organizations ORDER BY id"
        ).fetchall())


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------

def create_member(org_id: int, name: str, email: str, skill_profile: str = "") -> dict:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO members (org_id, name, email, skill_profile, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (org_id, name, email, skill_profile, _now()),
        )
        member_id = cur.lastrowid
    return get_member(member_id)


def get_member(member_id: int) -> dict | None:
    with _connect() as conn:
        return _row(conn.execute(
            "SELECT * FROM members WHERE id = ?", (member_id,)
        ).fetchone())


def list_members(org_id: int) -> list[dict]:
    with _connect() as conn:
        return _rows(conn.execute(
            "SELECT * FROM members WHERE org_id = ? ORDER BY id", (org_id,)
        ).fetchall())


# ---------------------------------------------------------------------------
# Org-scoped repos
# ---------------------------------------------------------------------------

def register_repo(org_id: int, repo_url: str) -> dict:
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO org_repos (org_id, repo_url, created_at) VALUES (?, ?, ?)",
            (org_id, repo_url, _now()),
        )
        return _row(conn.execute(
            "SELECT * FROM org_repos WHERE org_id = ? AND repo_url = ?",
            (org_id, repo_url),
        ).fetchone())


def list_repos(org_id: int) -> list[dict]:
    with _connect() as conn:
        return _rows(conn.execute(
            "SELECT * FROM org_repos WHERE org_id = ? ORDER BY id", (org_id,)
        ).fetchall())


# ---------------------------------------------------------------------------
# Tagged issues (team-lead-facing tagging, plan §3.3)
# ---------------------------------------------------------------------------

def tag_issue(org_id: int, repo_url: str, issue_number: int, tag: str,
              subsystem: str = "", tagged_by: str = "") -> dict:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO tagged_issues
                   (org_id, repo_url, issue_number, tag, subsystem, tagged_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(org_id, repo_url, issue_number, tag)
               DO UPDATE SET subsystem = excluded.subsystem, tagged_by = excluded.tagged_by""",
            (org_id, repo_url, issue_number, tag, subsystem, tagged_by, _now()),
        )
        return _row(conn.execute(
            "SELECT * FROM tagged_issues WHERE org_id = ? AND repo_url = ? "
            "AND issue_number = ? AND tag = ?",
            (org_id, repo_url, issue_number, tag),
        ).fetchone())


def list_tagged_issues(org_id: int, repo_url: str) -> list[dict]:
    with _connect() as conn:
        return _rows(conn.execute(
            "SELECT * FROM tagged_issues WHERE org_id = ? AND repo_url = ? "
            "ORDER BY issue_number",
            (org_id, repo_url),
        ).fetchall())


# ---------------------------------------------------------------------------
# Assigned issues
# ---------------------------------------------------------------------------

def assign_issue(member_id: int, repo_url: str, issue_number: int | None,
                  issue_title: str, rationale: str) -> dict:
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO assigned_issues
                   (member_id, repo_url, issue_number, issue_title, rationale, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (member_id, repo_url, issue_number, issue_title, rationale, _now()),
        )
        assigned_id = cur.lastrowid
        return _row(conn.execute(
            "SELECT * FROM assigned_issues WHERE id = ?", (assigned_id,)
        ).fetchone())


def list_assigned_issues(member_id: int) -> list[dict]:
    with _connect() as conn:
        return _rows(conn.execute(
            "SELECT * FROM assigned_issues WHERE member_id = ? ORDER BY created_at DESC",
            (member_id,),
        ).fetchall())


# ---------------------------------------------------------------------------
# PR readiness history
# ---------------------------------------------------------------------------

def record_pr_readiness(member_id: int, repo_url: str, verdict: str | None,
                         diff_size_lines: int, has_tests: bool) -> dict:
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO pr_readiness_history
                   (member_id, repo_url, verdict, diff_size_lines, has_tests, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (member_id, repo_url, verdict, diff_size_lines, int(has_tests), _now()),
        )
        row_id = cur.lastrowid
        return _row(conn.execute(
            "SELECT * FROM pr_readiness_history WHERE id = ?", (row_id,)
        ).fetchone())


def list_pr_readiness_history(member_id: int, limit: int = 20) -> list[dict]:
    with _connect() as conn:
        return _rows(conn.execute(
            "SELECT * FROM pr_readiness_history WHERE member_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (member_id, limit),
        ).fetchall())


# ---------------------------------------------------------------------------
# Per-member roadmap status
# ---------------------------------------------------------------------------

def set_roadmap_status(member_id: int, repo_url: str, status: str) -> dict:
    if status not in _VALID_ROADMAP_STATUSES:
        raise ValueError(f"status must be one of {sorted(_VALID_ROADMAP_STATUSES)}, got {status!r}")
    with _connect() as conn:
        conn.execute(
            """INSERT INTO member_roadmap_status (member_id, repo_url, status, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(member_id, repo_url) DO UPDATE SET
                   status = excluded.status, updated_at = excluded.updated_at""",
            (member_id, repo_url, status, _now()),
        )
        return _row(conn.execute(
            "SELECT * FROM member_roadmap_status WHERE member_id = ? AND repo_url = ?",
            (member_id, repo_url),
        ).fetchone())


def get_roadmap_statuses(member_id: int) -> list[dict]:
    with _connect() as conn:
        return _rows(conn.execute(
            "SELECT * FROM member_roadmap_status WHERE member_id = ? ORDER BY updated_at DESC",
            (member_id,),
        ).fetchall())
