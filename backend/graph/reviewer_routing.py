"""Reviewer routing — git authorship over the blast radius.

Item B / 6b from docs/handoff/2026-08-07.md:
    git blame over the blast-radius file set → "these 2 people own the affected code"

Uses the GitHub client already built. No model call at all — which is the
point: it is a deterministic answer to a question people ask daily.

Weight recent commits above old ones; exclude the PR author from their
own reviewer list.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from config import repo_id_from_url
from graph.blast_radius import _blast_radius_core


def suggest_reviewers(
    changed_files: list[str],
    repo_url: str,
    top_n: int = 2,
    pr_author: Optional[str] = None,
    max_hops: int = 3,
) -> dict:
    """Who owns the code in the blast radius, by recent authorship.

    Args:
        changed_files: list of repo-relative paths that changed
        repo_url:      GitHub repo URL
        top_n:         number of reviewers to suggest (default 2)
        pr_author:     login to exclude from suggestions (the PR author)
        max_hops:      max traversal depth for blast radius

    Returns:
        {
            "reviewers": [
                {"login": ..., "files_touched": n, "score": float,
                 "last_touched": iso_date},
                ...
            ],
            "blast_radius_size": int,
            "error": null | str,
        }

    No model call — fully deterministic.
    """
    from graph.store import load_graph
    from clients.github_client import GitHubClient
    from config import settings

    repo_id = repo_id_from_url(repo_url)

    try:
        graph = load_graph(repo_id)
    except FileNotFoundError as e:
        return {"reviewers": [], "blast_radius_size": 0, "error": str(e)}

    # Get blast radius
    result = _blast_radius_core(changed_files, graph, max_hops=max_hops)
    if result.get("error"):
        return {"reviewers": [], "blast_radius_size": 0,
                "error": result["error"]}

    affected_paths = [n["path"] for n in result["nodes"]]
    if not affected_paths:
        return {"reviewers": [], "blast_radius_size": 0, "error": None}

    # Get commit authors for affected files via GitHub API
    gh = GitHubClient(settings.GITHUB_TOKEN)
    try:
        repo = gh.get_repo(repo_url)
    except Exception as e:
        return {"reviewers": [], "blast_radius_size": len(affected_paths),
                "error": f"GitHub API error: {e}"}

    # Aggregate author scores across affected files
    author_scores: dict[str, float] = defaultdict(float)
    author_files: dict[str, int] = defaultdict(int)
    author_last: dict[str, datetime] = {}

    now = datetime.now(timezone.utc)

    for file_path in affected_paths[:50]:  # Cap API calls at 50 files
        try:
            commits = repo.get_commits(path=file_path)
            for i, commit in enumerate(commits):
                if i >= 10:  # Max 10 commits per file
                    break
                author_login = (
                    commit.author.login if commit.author else None
                )
                if not author_login:
                    continue
                if pr_author and author_login == pr_author:
                    continue

                # Recency weight: recent commits score higher
                commit_date = commit.commit.author.date
                if commit_date.tzinfo is None:
                    commit_date = commit_date.replace(tzinfo=timezone.utc)
                days_ago = max((now - commit_date).days, 1)
                weight = 1.0 / days_ago  # inverse recency

                author_scores[author_login] += weight
                author_files[author_login] += 1

                if (author_login not in author_last
                        or commit_date > author_last[author_login]):
                    author_last[author_login] = commit_date
        except Exception:
            continue  # Skip files with API errors

    # Rank by score, take top_n
    ranked = sorted(
        author_scores.keys(),
        key=lambda login: author_scores[login],
        reverse=True,
    )[:top_n]

    reviewers = [
        {
            "login": login,
            "files_touched": author_files[login],
            "score": round(author_scores[login], 4),
            "last_touched": (
                author_last[login].isoformat() if login in author_last else None
            ),
        }
        for login in ranked
    ]

    return {
        "reviewers": reviewers,
        "blast_radius_size": len(affected_paths),
        "error": None,
    }
