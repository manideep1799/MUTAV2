"""Fallback local optimizer — same shape as Mutagent's ADLC loop.

Use this if the Mutagent gate fails at hour 1:00. Datasets, rubrics,
traces and delta tables are unchanged; only the optimizer is substituted.
Disclose the substitution in the submission README rather than hiding it.

Public API (matches the gate spec in docs/GATE.md):
    evaluate(prompt, dataset, rubric) -> Score
    optimize(baseline, dataset, rubric, ...) -> tuple[str, DeltaTable]
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from config import REPORTS_DIR
from observability.tracer import trace
from clients.llm_client import complete, json_complete, extract_json  # json_complete: variant generation


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class CaseResult:
    case_id: str
    score: float                        # weighted mean across criteria, 0–1
    criterion_scores: dict[str, float]
    raw_output: str                     # preserved verbatim, never parsed away
    latency_ms: float
    passed: bool = False                # severity gate verdict, not the mean
    failed_critical: list[str] = field(default_factory=list)
    judge_errors: dict[str, str] = field(default_factory=dict)
    error: str | None = None


@dataclass
class Score:
    mean_score: float
    per_case: list[CaseResult] = field(default_factory=list)

    def failed_cases(self, threshold: float = 0.7) -> list[CaseResult]:
        return [c for c in self.per_case if c.score < threshold]

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.per_case if c.passed)

    @property
    def pass_rate(self) -> float:
        """Fraction of cases clearing the severity gate — the headline metric.

        This, not mean_score, is what the design doc reports as
        'baseline 2/5 -> optimized 5/5'.
        """
        return self.passed_count / len(self.per_case) if self.per_case else 0.0


# A criterion scored at or above this counts as satisfied. The rubrics define
# their criteria as binary (1.0 / 0.0); the margin tolerates a judge that
# returns 0.8 where it means 1.0.
CRITERION_PASS = 0.5


DeltaTable = list[dict]  # rows: generation, variant_id, score, prompt_excerpt


# ---------------------------------------------------------------------------
# evaluate
# ---------------------------------------------------------------------------

def evaluate(prompt: str, dataset: list[dict], rubric: dict,
             progress: bool = False) -> Score:
    """Score a prompt against the dataset using the rubric.

    dataset item shape:
      id       -- unique case identifier
      inputs   -- dict of str values substituted into the prompt via .format()
      expected -- dict of assertions passed to the rubric judge

    rubric shape:
      criteria -- list of: name, weight (float), description (str)
    """
    criteria = rubric.get("criteria", [])
    total_weight = sum(c["weight"] for c in criteria) or 1.0
    results: list[CaseResult] = []

    for idx, case in enumerate(dataset, 1):
        case_id = case.get("name") or case.get("id", "unknown")
        if progress:
            print(f"    [{idx:>2}/{len(dataset)}] {case_id}", flush=True)
        inputs   = case.get("inputs", {})
        expected = case.get("expected", {})

        try:
            instantiated = prompt.format(**inputs)
        except KeyError as exc:
            results.append(CaseResult(
                case_id=case_id, score=0.0, criterion_scores={},
                raw_output="", latency_ms=0.0,
                error=f"Missing input key: {exc}",
            ))
            continue

        raw_output, latency_ms = complete(instantiated, temperature=0.1)

        # Trace before scoring. The instantiated prompt and the raw pre-parse
        # output are the evidence a diagnosis runs on; capturing them after
        # judging would lose exactly the malformed responses worth studying.
        trace(
            component=rubric.get("target_id", "unknown"),
            prompt=instantiated,
            raw_output=raw_output,
            latency_ms=latency_ms,
            extra={"case_id": case_id, "expected": expected},
        )

        criterion_scores: dict[str, float] = {}
        judge_errors: dict[str, str] = {}
        for crit in criteria:
            score, judge_error = _score_criterion(crit, raw_output, expected, inputs)
            criterion_scores[crit["name"]] = score
            if judge_error:
                judge_errors[crit["name"]] = judge_error

        case_score = sum(
            criterion_scores.get(c["name"], 0.0) * c["weight"]
            for c in criteria
        ) / total_weight

        # Severity gate: any single critical criterion failing fails the case,
        # regardless of the weighted mean. Standard criteria inform the score
        # but never gate. Rubrics declare this with "gate": "critical".
        failed_critical = [
            c["name"] for c in criteria
            if c.get("severity") == "critical"
            and criterion_scores.get(c["name"], 0.0) < CRITERION_PASS
        ]
        gated = rubric.get("gate") == "critical"
        passed = (
            not failed_critical if gated
            else case_score >= rubric.get("pass_threshold", 0.7)
        )

        results.append(CaseResult(
            case_id=case_id,
            score=round(case_score, 4),
            criterion_scores=criterion_scores,
            raw_output=raw_output,
            latency_ms=round(latency_ms, 2),
            passed=passed,
            failed_critical=failed_critical,
            judge_errors=judge_errors,
        ))

    mean = sum(r.score for r in results) / len(results) if results else 0.0
    return Score(mean_score=round(mean, 4), per_case=results)


def _score_criterion(
    crit: dict, output: str, expected: dict, inputs: dict | None = None
) -> tuple[float, str | None]:
    """Score one criterion. Returns (score, judge_error).

    A judge failure returns 0.0 *and* the reason. Never swallow the reason:
    a 0.0 that means "the output was wrong" and a 0.0 that means "the judge
    broke" are different findings, and conflating them makes an eval
    unreadable — see design §09 on raw output surviving as evidence.

    `inputs` is load-bearing: a groundedness criterion ("is this id one that
    actually appeared in the list?") is unanswerable without the material the
    system was given. Without it the judge cannot do anything but guess, and
    guessing reads as a uniform zero.
    """
    given = (
        "\n".join(f"{k}:\n{v}" for k, v in inputs.items())
        if inputs else "(not provided)"
    )
    judge_prompt = (
        f"You are a strict evaluator scoring an AI system output.\n\n"
        f"CRITERION NAME: {crit['name']}\n"
        f"CRITERION DESCRIPTION: {crit['description']}\n\n"
        f"INPUT THE SYSTEM WAS GIVEN (the only source of truth for what "
        f"exists):\n{given[:2500]}\n\n"
        f"AI OUTPUT (evaluate this):\n{output[:1500]}\n\n"
        f"EXPECTED PROPERTIES:\n{json.dumps(expected, indent=2)}\n\n"
        f"Score ONLY the criterion named above. The expected properties may "
        f"describe things other criteria check — ignore those and judge this "
        f"criterion alone.\n\n"
        f"Respond with a JSON object containing exactly one field named score. "
        f"The score must be a number from 0.0 to 1.0: "
        f"1.0 means the output fully satisfies the criterion, "
        f"0.0 means it completely fails. "
        f"Reply with the JSON object only — no explanation before or after it."
    )
    try:
        raw, _ = complete(judge_prompt, temperature=0.0, max_tokens=256)
    except Exception as exc:                      # noqa: BLE001
        return 0.0, f"judge call failed: {type(exc).__name__}: {exc}"

    parsed = extract_json(raw)
    if parsed is None:
        return 0.0, f"judge output not parseable as JSON: {raw[:160]!r}"
    if "score" not in parsed:
        return 0.0, f"judge output has no 'score' field: {raw[:160]!r}"
    try:
        return max(0.0, min(1.0, float(parsed["score"]))), None
    except (TypeError, ValueError):
        return 0.0, f"judge 'score' is not numeric: {parsed['score']!r}"


# ---------------------------------------------------------------------------
# optimize
# ---------------------------------------------------------------------------

def optimize(
    baseline: str,
    dataset: list[dict],
    rubric: dict,
    generations: int = 4,
    variants: int = 8,
    target_id: str = "unknown",
    failure_threshold: float = 0.7,
) -> tuple[str, DeltaTable]:
    """Genetic-algorithm-flavoured prompt evolution.

    Evaluates baseline, then iteratively mutates the best prompt and keeps
    the highest scorer each generation. Same external shape as Mutagent's
    optimize command so datasets and rubrics transfer unchanged.
    """
    delta: DeltaTable = []
    baseline_result = evaluate(baseline, dataset, rubric)
    _record(delta, 0, 0, baseline_result.mean_score, baseline, label="baseline")

    current_prompt = baseline
    current_score  = baseline_result.mean_score
    current_result = baseline_result

    for gen in range(1, generations + 1):
        failure_summary = _summarize_failures(current_result.failed_cases(failure_threshold))
        variant_prompts, mutation_error = _generate_variants(current_prompt, failure_summary, variants)

        if mutation_error:
            # The fallback is [current_prompt] unchanged — evaluating it again
            # only measures sampling noise, not an improvement. Record that
            # plainly rather than let a noise-driven score sit next to real
            # rows indistinguishably, which is what silently happened before
            # this was fixed: two generations of "no change" logged as if
            # they were optimization attempts.
            _record(delta, gen, 0, current_score, current_prompt,
                    label=f"mutation_failed: {mutation_error}")
            continue

        for vid, variant in enumerate(variant_prompts):
            result = evaluate(variant, dataset, rubric)
            _record(delta, gen, vid, result.mean_score, variant)

            if result.mean_score > current_score:
                current_score  = result.mean_score
                current_prompt = variant
                current_result = result

    _save_report(target_id, baseline_result.mean_score, current_score, generations, delta)
    return current_prompt, delta


def _request_variants(prompt: str, failure_summary: str, n: int) -> tuple[list[str], str | None]:
    """One mutation call, asking for exactly n variants. Returns (variants, error)."""
    mutation_prompt = (
        f"You are a prompt engineer improving a prompt template that uses "
        f"{{variable_name}} placeholders for runtime substitution.\n\n"
        f"RULES:\n"
        f"- Keep every {{variable_name}} placeholder exactly as-is\n"
        f"- Describe any output format in prose — do not use literal braces\n"
        f"- Focus improvements on the failure patterns below\n"
        f"- Each variant must be a complete, standalone prompt\n\n"
        f"FAILURES TO FIX:\n{failure_summary}\n\n"
        f"CURRENT PROMPT:\n{prompt}\n\n"
        f"Respond with a JSON object containing one field named variants: "
        f"a list of {n} strings, each a complete improved prompt.\n\n"
        f"YOU MUST OUTPUT ONLY RAW JSON. DO NOT WRAP IN MARKDOWN (NO ```json). "
        f"DO NOT INCLUDE ANY EXPLANATORY TEXT BEFORE OR AFTER THE JSON."
    )
    try:
        raw, _ = complete(mutation_prompt, temperature=0.8, max_tokens=4096)
    except Exception as exc:                      # noqa: BLE001
        return [], f"mutation call failed: {type(exc).__name__}: {exc}"

    # Asking an 8B model to emit JSON containing several full paragraphs of
    # prompt text is a hard generation task — quotes and newlines inside
    # those strings are easy to mis-escape. Use the same tolerant extractor
    # the judge uses (fence-stripping + outermost-brace fallback) rather
    # than the narrower fence-only path json_complete takes, since a single
    # malformed variant should not discard the whole generation.
    parsed = extract_json(raw)
    if parsed is None:
        return [], f"mutation output not parseable as JSON: {raw[:200]!r}"

    variants = [str(v) for v in parsed.get("variants", [])[:n]]
    if not variants:
        return [], f"mutation output had no 'variants' field: {raw[:200]!r}"
    return variants, None


def _generate_variants(
    prompt: str, failure_summary: str, n: int
) -> tuple[list[str], str | None]:
    """Ask the model for n mutated prompts. Returns (variants, error).

    On any failure, falls back to [prompt] (the unchanged input) so the
    generation loop still has something to evaluate — but returns the
    reason too, so that fallback is never silently mistaken for a real
    mutation. Re-evaluating an unchanged prompt against a nonzero
    temperature produces score noise that looks exactly like a small
    optimization win if nothing flags what actually happened.

    A real (non-error) response with FEWER than n variants is not that
    failure mode — an 8B model asked for 3 full paragraph-length prompts in
    one JSON response sometimes only writes 1 before closing the object.
    One top-up call asks for exactly the shortfall and merges the results
    (deduped), capping total mutation calls at 2 per generation rather than
    silently accepting an under-sized batch or retrying unboundedly.
    """
    variants, error = _request_variants(prompt, failure_summary, n)
    if error:
        return [prompt], error

    if len(variants) < n:
        shortfall = n - len(variants)
        more, _ = _request_variants(prompt, failure_summary, shortfall)
        for v in more:
            if v not in variants:
                variants.append(v)

    return variants, None


def _summarize_failures(failures: list[CaseResult]) -> str:
    if not failures:
        return "No failures — prompt is performing well on all cases."
    lines = []
    for f in failures[:5]:
        lines.append(
            f"case={f.case_id}  score={f.score:.2f}  "
            f"criteria={json.dumps(f.criterion_scores)}  "
            f"output={f.raw_output[:200]!r}"
        )
    return "\n".join(lines)


def _record(
    delta: DeltaTable,
    generation: int,
    variant_id: int,
    score: float,
    prompt: str,
    label: str = "",
) -> None:
    """Records one row. prompt_hash is a cheap way to confirm whether two
    rows are the SAME prompt without eyeballing full text — this is what
    would have caught the bug where mutation silently fell back to
    re-evaluating an unchanged prompt: every row's hash was identical, and
    nothing in the report surfaced that fact. The full prompt is kept too,
    not just an excerpt — these reports are meant to be human-audited
    (design's self-improving-thesis panel), and a 120-char excerpt cannot
    show what a mutation actually changed.
    """
    delta.append({
        "generation": generation,
        "variant_id": variant_id,
        "label": label,
        "score": round(score, 4),
        "prompt_hash": hashlib.sha256(prompt.encode()).hexdigest()[:12],
        "prompt_excerpt": prompt[:120].replace("\n", " "),
        "prompt": prompt,
    })


def _save_report(
    target_id: str,
    baseline_score: float,
    optimized_score: float,
    generations: int,
    delta: DeltaTable,
) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "target_id": target_id,
        "baseline_score": round(baseline_score, 4),
        "optimized_score": round(optimized_score, 4),
        "delta": round(optimized_score - baseline_score, 4),
        "generations": generations,
        "rows": delta,
    }
    dest = REPORTS_DIR / f"{target_id}.delta.json"
    dest.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
