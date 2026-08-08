"""CLI to run a Mutagent target through the fallback harness.

    python -m mutagent.run issue_rec               # baseline only
    python -m mutagent.run issue_rec --optimize    # full evolve loop
    python -m mutagent.run issue_rec --dry-run     # validate files, no API calls

Loads mutagent/prompts/<target>.txt, datasets/<target>.json and
rubrics/<target>.json, then reports the severity-gated pass rate — the
'baseline 2/5 -> optimized 5/5' number from design §09, not the weighted mean.

This runs the LOCAL fallback harness. The Mutagent helix skills are the
primary path; this exists so a baseline is reachable without them, and so
the datasets and rubrics can be exercised offline.
"""
from __future__ import annotations

import argparse
import sys

from config import load_prompt, load_dataset, load_rubric, settings
from mutagent.harness import evaluate, optimize


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _print_case(case, criteria_by_name: dict) -> None:
    mark = "PASS" if case.passed else "FAIL"
    print(f"  [{mark}]  {case.case_id}")

    for name, score in case.criterion_scores.items():
        severity = criteria_by_name.get(name, {}).get("severity", "standard")
        tag = "CRITICAL" if severity == "critical" else "standard"
        ok = "ok  " if score >= 0.5 else "FAIL"
        print(f"           {name:<28} {tag:<9} {score:>4.2f}  {ok}")

    # Judge failures first: a 0.00 caused by a broken judge is a different
    # finding from a 0.00 caused by a wrong answer, and must not read as one.
    for name, msg in case.judge_errors.items():
        print(f"           !! JUDGE ERROR [{name}]: {msg}")
    if case.failed_critical:
        print(f"           -> failed critical: {', '.join(case.failed_critical)}")
    if case.error:
        print(f"           -> error: {case.error}")

    excerpt = case.raw_output.strip().replace("\n", " ")[:100]
    print(f"           output: {excerpt!r}")
    print()


def _print_report(label: str, score, rubric: dict) -> None:
    criteria_by_name = {c["name"]: c for c in rubric.get("criteria", [])}

    print(f"\n{'=' * 68}")
    print(f"{label}")
    print("=" * 68)
    for case in score.per_case:
        _print_case(case, criteria_by_name)

    total = len(score.per_case)
    judge_failures = sum(len(c.judge_errors) for c in score.per_case)
    print(f"  cases passed (severity gate) : {score.passed_count}/{total}")
    print(f"  mean weighted score          : {score.mean_score:.4f}")
    if judge_failures:
        print(f"\n  WARNING: {judge_failures} judge call(s) failed. Those criteria "
              f"scored 0.00 because the\n           JUDGE broke, not because the "
              f"output was wrong — this result is not\n           a valid "
              f"measurement until they are fixed.")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

def _explain_api_error(exc: Exception) -> int:
    """Turn an SDK exception into one actionable line instead of a traceback.

    Matches on class name rather than importing openai's exception types, so
    this keeps working if the SDK reorganises them.
    """
    name = type(exc).__name__

    if name == "AuthenticationError":
        print("\nerror: Groq rejected the API key (401).\n"
              "       The key in backend/.env is invalid, revoked, or still a "
              "placeholder.\n"
              "       Create a new one at https://console.groq.com/keys",
              file=sys.stderr)
    elif name == "RateLimitError":
        print("\nerror: Groq rate limit hit (429).\n"
              "       Wait a minute, or lower the load with "
              "--generations 2 --variants 2.", file=sys.stderr)
    elif name in ("APIConnectionError", "APITimeoutError"):
        print(f"\nerror: could not reach Groq ({name}). Check your network "
              f"and retry.", file=sys.stderr)
    elif name == "NotFoundError":
        print(f"\nerror: model {settings.groq_model!r} was not found (404).\n"
              f"       It may have been retired — check "
              f"https://console.groq.com/docs/models and update groq_model "
              f"in backend/config.py.", file=sys.stderr)
    else:
        print(f"\nerror: {name}: {exc}", file=sys.stderr)
    return 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mutagent.run",
        description="Run a Mutagent target through the local fallback harness.",
    )
    parser.add_argument("target", help="target id, e.g. issue_rec")
    parser.add_argument("--optimize", action="store_true",
                        help="run the evolve loop after the baseline")
    parser.add_argument("--generations", type=int, default=3)
    parser.add_argument("--variants", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true",
                        help="validate the three files and exit; makes no API calls")
    args = parser.parse_args()

    # --- load ------------------------------------------------------------
    try:
        rubric = load_rubric(args.target)
        # A target may evaluate a prompt owned by a different target id —
        # e.g. router.json scores mutagent/prompts/council.txt, since the
        # design merged Council and Router into one call (design §11) and
        # there is no separate router prompt. The rubric declares this
        # explicitly via prompt_ref rather than the file being duplicated,
        # which is the exact "prompts in two places" bug CLAUDE.md forbids.
        prompt_name = rubric.get("prompt_ref", args.target)
        prompt = load_prompt(prompt_name)
        dataset = load_dataset(args.target)
    except FileNotFoundError as exc:
        print(f"error: missing file for target '{args.target}': {exc}", file=sys.stderr)
        return 1

    print(f"target   : {args.target}"
          + (f"  (evaluates prompt: {prompt_name})" if prompt_name != args.target else ""))
    print(f"cases    : {len(dataset)}")
    print(f"criteria : {len(rubric.get('criteria', []))} "
          f"({sum(1 for c in rubric.get('criteria', []) if c.get('severity') == 'critical')} critical)")
    print(f"gate     : {rubric.get('gate', 'weighted-mean')}")
    print(f"model    : {settings.groq_model}")

    # --- validate --------------------------------------------------------
    problems = []
    for case in dataset:
        try:
            prompt.format(**case.get("inputs", {}))
        except KeyError as exc:
            problems.append(f"case '{case.get('name')}' missing input {exc}")
    if problems:
        print("\nvalidation failed:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print("validation: all cases substitute into the prompt cleanly")

    if args.dry_run:
        print("\ndry run — no API calls made.")
        return 0

    key = settings.groq_api_key.strip()
    if not key:
        print("\nerror: GROQ_API_KEY is empty. Add it to backend/.env "
              "(never commit that file).", file=sys.stderr)
        return 1
    if not key.startswith("gsk_"):
        # Catches the placeholder-pasted-literally case before spending a
        # round trip on a request that cannot succeed.
        print(f"\nerror: GROQ_API_KEY does not look like a Groq key — it should "
              f"start with 'gsk_' (got {key[:4]!r}...).\n"
              f"       Get one at https://console.groq.com/keys, then:\n"
              f'       [IO.File]::WriteAllText("$PWD\\backend\\.env", '
              f'"GROQ_API_KEY=gsk_...`n")', file=sys.stderr)
        return 1

    # --- baseline --------------------------------------------------------
    try:
        print("\nevaluating baseline ...")
        baseline = evaluate(prompt, dataset, rubric, progress=True)
    except Exception as exc:                      # noqa: BLE001 — see below
        return _explain_api_error(exc)
    _print_report("BASELINE", baseline, rubric)

    if not args.optimize:
        print("\nRun again with --optimize to evolve the prompt.")
        return 0

    # --- optimize --------------------------------------------------------
    print(f"\noptimizing: {args.generations} generations x {args.variants} variants ...")
    try:
        best_prompt, delta = optimize(
            prompt, dataset, rubric,
            generations=args.generations,
            variants=args.variants,
            target_id=rubric.get("target_id", args.target),
        )
        print("\nevaluating optimized prompt ...")
        optimized = evaluate(best_prompt, dataset, rubric, progress=True)
    except Exception as exc:                      # noqa: BLE001
        print("\n(baseline above is still valid — only the optimize run failed)",
              file=sys.stderr)
        return _explain_api_error(exc)
    _print_report("OPTIMIZED", optimized, rubric)

    print(f"\n{'=' * 68}")
    print("DELTA")
    print("=" * 68)
    print(f"  cases passed : {baseline.passed_count}/{len(dataset)}"
          f"  ->  {optimized.passed_count}/{len(dataset)}")
    print(f"  mean score   : {baseline.mean_score:.4f}  ->  {optimized.mean_score:.4f}"
          f"   ({optimized.mean_score - baseline.mean_score:+.4f})")
    print(f"  variants evaluated : {len(delta)}")

    failed_gens = [row for row in delta if row.get("label", "").startswith("mutation_failed")]
    if failed_gens:
        print(f"\n  WARNING: {len(failed_gens)} of {len(delta)} row(s) are mutation_failed —")
        print(f"           the model could not be prompted for real variants that generation,")
        print(f"           so the prompt was re-evaluated UNCHANGED. Any score movement on")
        print(f"           those rows is sampling noise, not improvement:")
        for row in failed_gens:
            print(f"             gen {row['generation']}: {row['label']}")

    # Answers the exact question a delta report alone could not: did the
    # optimize loop actually produce different prompt TEXT, or is a score
    # increase from re-sampling the same prompt at nonzero temperature?
    # prompt_hash makes this a hash comparison instead of eyeballing a
    # 120-char excerpt.
    baseline_hash = delta[0].get("prompt_hash") if delta else None
    non_baseline = [r for r in delta if r.get("generation", 0) > 0 and not r["label"].startswith("mutation_failed")]
    distinct_hashes = {r.get("prompt_hash") for r in non_baseline}
    if non_baseline:
        if distinct_hashes == {baseline_hash}:
            print(f"\n  NOTE: every evaluated variant has the SAME prompt_hash as the baseline —")
            print(f"        the text never changed. The score delta above is sampling noise, not")
            print(f"        a real optimization result, even though no mutation_failed row exists.")
        else:
            print(f"\n  prompt text changed across the run: {len(distinct_hashes)} distinct "
                  f"prompt_hash value(s) among {len(non_baseline)} evaluated variant(s).")

    print(f"\n  report  : mutagent/reports/{rubric.get('target_id', args.target)}.delta.json")
    print(f"  prompt  : optimized prompt below — review before replacing the baseline\n")
    print(best_prompt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
