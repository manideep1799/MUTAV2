# Changes since cloning `Saradwanth-116/git-quest`

This branch (`claude/git-quest-clone-z0qti3`) started as a full clone of
[`Saradwanth-116/git-quest`](https://github.com/Saradwanth-116/git-quest),
history and all (`e6f1a5b` Initial MVP Commit, `a2bd3ac` Refactor backend to
align with TEMPPP architecture). Everything below was added on top of that,
in `backend/` and the `/ask` chat panel in `src/routes/index.tsx`. Nothing
else in the original repo was touched.

## 1. HyDE for retrieval (`backend/rag_qa.py`, `backend/mutagent/prompts/hyde.txt`)

Before embedding a question for vector search, an LLM call first drafts a
short hypothetical passage that *would* answer it — that passage gets
embedded instead of the raw question. A few sentences of plausible
code/doc-shaped text lands closer in embedding space to the real chunks
that answer a question than a short, vague user question does.

- `mutagent/prompts/hyde.txt` — new prompt, loaded via the existing
  `load_prompt()` convention (prompts never get inlined in `.py` files).
- `rag_qa._generate_hypothetical_document(question)` — calls the prompt,
  falls back silently to embedding the raw question if the call fails.
- Toggle: `HYDE_ENABLED` in `.env` (defaults to `true`).

## 2. AI-Council gate (`backend/pipeline/gate.py`)

The repo's own design doc (Mutagent target #2/#4) specified a query-gating
stage in front of retrieval, using the existing `mutagent/prompts/council.txt`
prompt — but only the prompt existed, nothing called it. Built the missing
piece:

- `pipeline/gate.run_gate(query)` — classifies the question on four gate
  criteria (clarity, scope, answerability, specificity), picks a retrieval
  route (`vector` / `graph` / `hybrid`), and splits multi-intent questions
  into sub-questions. Follows the same `complete()` / `extract_json()` /
  `trace()` pattern already used by `issue_recommendation.py` and
  `maintainer_health.py`.
- Wired into `POST /ask` as the first stage: a question failing any gate
  criterion is rejected with a reason before retrieval ever runs.
- `route` is threaded through to `hybrid_retriever.hybrid_retrieve()`,
  which now skips graph-symbol search and structural-facts injection
  entirely when the gate says `route="vector"` — matching the retrieval
  flow the design doc describes ("graph search, if route includes graph").
- Router (target #4) needed no separate code — it grades the same `route`
  field the gate already produces.

## 3. Multi-intent fan-out (`backend/rag_qa.py`)

The gate splits a compound question ("how does auth work *and* where's
rate limiting?") into sub-questions, but nothing used the split — a single
retrieval pass over a compound question tends to only surface chunks for
whichever intent dominates the embedding.

- `rag_qa._build_context()` now retrieves separately for each distinct
  sub-question (its own text, its own route), dedupes the resulting chunks
  by `(path, start_line, end_line)`, and merges them into one context.
  One synthesis call still produces the final answer, against the
  original full question.
- A single-intent question (the common case) takes exactly the same path
  as before — one retrieval pass, no behavior change.

## 4. Response caching (`backend/pipeline/gate.py`, `backend/rag_qa.py`)

Both the gate classification and the HyDE passage are pure functions of
the question text alone (neither depends on the repo). Added
`functools.lru_cache(maxsize=256)` to `run_gate()` and
`_generate_hypothetical_document()` — a repeated question in the same
session skips its LLM round-trip entirely (no duplicate trace line
written either, since the trace call is inside the cached function).

## 5. Streaming answers (`backend/main.py`, `backend/rag_qa.py`, `src/routes/index.tsx`)

`POST /ask` used to block until the entire answer was generated
(gate → HyDE → retrieve → rerank → one full LLM completion, all before any
bytes went to the client). The synthesis call is now streamed:

- `rag_qa.ask_question_stream()` — same retrieval pipeline as
  `ask_question()`, but the final LLM call uses `stream=True` and the
  function yields text chunks as they arrive, then the `sources` list as
  its last item (callers tell the two apart by type — `str` vs `list`).
- `POST /ask` response contract, by `Content-Type`:
  - **Gate rejects the question** → `application/json`, shape unchanged
    from before (`{answer, sources, passed, reason, classification,
    route, sub_queries}` — `answer` carries the rejection reason so the
    existing chat UI doesn't break on a missing field).
  - **Gate passes** → `text/plain`, streamed: answer text chunks, then a
    `"\n\n<<<META>>>{json}"` trailer with `{sources, route, sub_queries,
    passed}`.
  - `ensure_indexed()` still runs before the stream opens, so "repo not
    indexed" is still a clean `400`, not a broken stream.
- `src/routes/index.tsx` (`AskPanel.send`) — switched from a single
  `await res.json()` to reading `res.body.getReader()` and growing one
  assistant message bubble as text arrives, splitting off the `<<<META>>>`
  trailer for sources at the end. Falls back to the old plain-JSON path
  automatically when `Content-Type` is `application/json` (the
  gate-rejection case).

## Net effect on `POST /ask`

```
question
  → council gate (cached)         reject → {answer: <reason>, sources: [], passed: false, ...}
  → route decision                              ↓
  → HyDE per (sub-)question (cached)     pass → stream:
  → hybrid retrieve (respects route)              text chunks...
  → merge + dedupe if multi-intent                <<<META>>>{sources, route, sub_queries}
  → rerank
  → stream final answer
```

## Config additions (`backend/.env.example`)

```
HYDE_ENABLED=true   # set false to embed the raw question instead of a HyDE passage
```

## Verifying it

No network access to Groq/Ollama was available in the environment these
changes were made in, so the retrieval/caching/streaming logic was
smoke-tested with the LLM and vector-store calls mocked out (see the
commit history for what was checked): single-question streaming yields
text-then-sources in order, multi-intent fan-out merges and dedupes chunks
across sub-queries, repeated questions hit the gate/HyDE cache (no
duplicate LLM call, no duplicate trace line), and the `<<<META>>>` framing
round-trips through JSON correctly. Worth a real end-to-end pass once a
`GROQ_API_KEY` is available: `POST /index` a small repo, then a few
`POST /ask` calls through `/docs` or the chat UI — one normal question,
one deliberately vague one (checks the gate rejects it), and one compound
one (checks the fan-out).
