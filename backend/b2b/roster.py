"""Manager view (plan §3.3): team roster, per-member roadmap progress, and
PR-readiness history in one payload — replaces manually chasing status
across three separate queries.
"""
from __future__ import annotations

from b2b import store


def get_roster(org_id: int) -> list[dict]:
    roster = []
    for member in store.list_members(org_id):
        member_id = member["id"]
        assigned = store.list_assigned_issues(member_id)
        pr_history = store.list_pr_readiness_history(member_id)
        roadmap_status = store.get_roadmap_statuses(member_id)

        open_count = sum(1 for a in assigned if a["status"] not in ("done", "closed"))
        ready_count = sum(1 for h in pr_history if h["verdict"] == "ready")

        roster.append({
            "member": member,
            "assigned_issues": assigned,
            "open_assignment_count": open_count,
            "roadmap_status": roadmap_status,
            "pr_readiness_history": pr_history,
            "pr_ready_rate": round(ready_count / len(pr_history), 4) if pr_history else None,
        })
    return roster
