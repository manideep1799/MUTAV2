"""Governance dashboard packaging (plan §3.5).

No new evaluation logic — observability/metrics.py already computes
everything. This only reshapes and labels it as the artifact a
security/compliance reviewer asks for when approving an AI tool for use
against internal code: per-component score, baseline vs. current, and a
last-evaluated timestamp.

Two things it does NOT fabricate, on principle (plan §6 — verify, don't
assert): dataset_version and rubric_version are reported as null because
mutagent/datasets and mutagent/rubrics don't carry version fields yet, and
generation_model reports what's actually configured rather than the
single model the design doc assumes, since rag_qa.py can diverge from the
rest of the app onto Ollama (see B2B_AUDIT.md).
"""
from __future__ import annotations

from datetime import datetime, timezone

from config import REPORTS_DIR, settings
from observability.metrics import get_metrics


def _generation_model_note() -> str:
    if settings.OLLAMA_BASE_URL:
        return (
            f"Council gate, issue recommendation, PR check, and issue health all use "
            f"{settings.LLM_MODEL} via Groq. RAG Q&A (HyDE + answer synthesis) is "
            f"currently configured to use {settings.OLLAMA_MODEL} via a local Ollama "
            f"endpoint instead, because OLLAMA_BASE_URL is set — this is a real "
            f"divergence from the 'one model' constraint, see B2B_AUDIT.md."
        )
    return f"All generation calls use {settings.LLM_MODEL} via Groq."


def get_governance_report() -> dict:
    metrics = get_metrics()
    components = []

    for t in metrics["targets"]:
        report_path = REPORTS_DIR / f"{t['id']}.delta.json"
        last_evaluated = None
        if report_path.exists():
            last_evaluated = datetime.fromtimestamp(
                report_path.stat().st_mtime, tz=timezone.utc
            ).isoformat()

        components.append({
            "component": t["id"],
            "name": t["name"],
            "priority": t["priority"],
            "evaluated": t["has_report"],
            "last_evaluated": last_evaluated,
            "baseline_score": t.get("baseline_score"),
            "current_score": t.get("optimized_score") if t.get("optimized") else t.get("baseline_score"),
            "delta": t.get("delta"),
            "mean_f1": t.get("mean_f1"),
            "trace_count": t["trace_count"],
            "dataset_version": None,   # not tracked yet — see B2B_AUDIT.md
            "rubric_version": None,    # not tracked yet — see B2B_AUDIT.md
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generation_model_note": _generation_model_note(),
        "components": components,
        "caveats": [
            "dataset_version/rubric_version are not tracked per-report yet — "
            "add a version field to mutagent/datasets and mutagent/rubrics "
            "before presenting this unmodified to a compliance reviewer.",
            "trace_count reflects mutagent/traces/*.jsonl, which is append-only "
            "and never rotated — see B2B_AUDIT.md item 1 before treating volume "
            "as a retention guarantee.",
        ],
    }
