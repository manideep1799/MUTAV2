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

## Verifying it (parts 1-5)

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

---

## 6. B2B build-out, per `B2B_Implementation_Plan.md`

Demo scope throughout: no auth/login, `org_id`/`member_id` passed as plain
request params the same way `repo_url` already is. See `B2B_AUDIT.md` for
what real multi-tenant auth would take.

### 6.1 Fixed and wired two already-built, never-connected modules

`graph/test_selection.py` (§3.2) and `graph/reviewer_routing.py` (§3.4)
already implemented most of the plan — blast-radius-filtered test
selection and commit-authorship-based reviewer suggestion — but both had
`from backend.graph...`/`from backend.config...`-style imports that don't
match how this app actually runs (no `backend.` package prefix anywhere
else in the codebase), plus `reviewer_routing.py` called
`settings.github_token` (lowercase; the real attribute is `GITHUB_TOKEN`).
Neither was imported from `main.py` despite `graph/__init__.py`'s own
docstring saying they should be. Fixed both bugs, wired them in as
`POST /b2b/test-selection` and `POST /b2b/reviewer-routing`.

### 6.2 Organization/Member data model (`backend/b2b/store.py`)

Plain `sqlite3` (no ORM, matching the codebase's existing preference for
the simplest tool that works — Chroma for vectors, JSON for the graph).
Tables: `organizations`, `members`, `org_repos`, `tagged_issues`,
`assigned_issues`, `pr_readiness_history`, `member_roadmap_status`. The
last one is an addition beyond plan §2: `learning_roadmap.py`'s roadmap is
stateless free text, not a checklist, so "per-member roadmap progress" is
tracked as a status (`not_started`/`in_progress`/`completed`) per
(member, repo) rather than an invented percentage.

### 6.3 Ticket routing, tagging, manager view (§3.3) — `backend/b2b/`

- `POST /b2b/orgs`, `/members`, `/repos` — plain CRUD over the tables above.
- `POST /b2b/orgs/{id}/issues/tag` — team-lead tagging, once per issue
  instead of re-explained per assignment.
- `POST /b2b/members/{id}/assign` — reuses `recommend_issue()` **unchanged**
  (including its issue_id-null safe-refusal behavior), then records the
  result against the member.
- `POST /b2b/members/{id}/pr-check` — reuses `check_pr_readiness()`
  **unchanged**, then logs the verdict to `pr_readiness_history`.
- `GET /b2b/orgs/{id}/roster` (`b2b/roster.py`) — composes member profile +
  assignments + roadmap status + PR-readiness history into one payload,
  replacing manual status-chasing across three separate queries.

### 6.4 Governance dashboard + team health repoint (§3.5, §3.6)

- `GET /b2b/governance-report` (`b2b/governance.py`) — reshapes the
  existing `/metrics` payload for a compliance reviewer: per-component
  score, baseline vs. current, last-evaluated timestamp (from the report
  file's mtime). No new eval logic. Honestly reports `dataset_version`/
  `rubric_version` as `null` (not tracked anywhere yet) instead of
  fabricating them, and states the *actual* configured generation model
  rather than assuming the single-model constraint always holds — see
  `B2B_AUDIT.md` item 4 for why that distinction matters.
- `GET /b2b/team-health` — thin alias over `get_maintainer_health()`
  (zero new logic; it already works against any repo the token can reach,
  public or private). The separate route exists so the internal-process-
  health framing is legible in the API surface itself.

### 6.5 Data-handling audit (§6) → `B2B_AUDIT.md`

Read `tracer.py`, `vector_store.py`, `graph/store.py`, `config.py`,
`embeddings.py`, and every `trace()` call site to answer the plan's four
audit questions with citations, not assertions. Headline finding: **the
plan's own §4 "self-hosted" row claims local BGE embeddings; the actual
code (`embeddings.py`) calls Gemini's hosted embeddings API for every
chunk.** Also shipped one concrete fix rather than only documenting the
gap: `vector_store.delete_collection()` + `graph/store.delete_graph()` +
`DELETE /index?repo_url=...`, since previously there was no way to purge
an indexed repo's data at all. Verified end-to-end — the graph file is
actually gone from disk after the call. The other three findings (trace
retention, single global GitHub token, first-run network fetches for the
reranker/tokenizer) are documented with the exact files/gaps but
deliberately not "fixed" with something that would just be security
theater (e.g. a plaintext per-org token column) — see the doc for why.

### On the "Helix engine"

Was asked to wire this build up to a Helix instance reachable via an
ngrok URL (`spearmint-factoid-brewery.ngrok-free.dev`). That host is
categorically unreachable from this sandbox — the egress proxy explicitly
refuses ngrok tunnels (certificate-pinned clients), independent of which
URL — confirmed via the proxy's own status endpoint before giving up on
it, not assumed. Re-reading the plan: none of the four build-first items
actually call into Helix at runtime; it's referenced only as how the core
engine's *prompts* were tuned (§1) and as a future "Managed/hosted"
deployment option (§4), not a runtime dependency of test selection,
governance packaging, the roster view, or the audit. No stub/config slot
was added for it — an unused `HELIX_BASE_URL` would be exactly the kind
of dead configuration this codebase avoids elsewhere.

### Verifying it (part 6)

All new endpoints were exercised end-to-end with FastAPI's `TestClient`
(external deps stubbed — no live GROQ/GEMINI/GITHUB credentials in this
sandbox): full org → member → repo → tag → assign → pr-check → roster
lifecycle, the `not_a_real_status` validation path (`400`), the
not-yet-indexed path for test-selection/reviewer-routing (`400` with the
real "Run /index first" message from `graph/store.py`), the governance
report's shape, and the `DELETE /index` purge actually removing a graph
file from disk. Not exercised against real Groq/GitHub APIs — do that
before treating this as demo-ready.

---

## 7. "Helix engine" turned out to be plain Ollama — fixed a real bug in that path

Follow-up on part 6's Helix question. Had the requester curl the ngrok URL
from a machine that could actually reach it (this sandbox still can't):
`GET /` returned `Ollama is running` — Ollama's literal default root
response — and `/openapi.json`/`/health` both 404'd, which rules out a
custom API server. It's the existing `OLLAMA_BASE_URL` path in
`rag_qa.py`, reached over a tunnel, running `llama3.1:8b`.

That surfaced a real bug rather than just a config question: the OpenAI
SDK client `rag_qa._get_client()` builds for the Ollama path doesn't send
any custom headers, but ngrok's free-tier interstitial intercepts
unheadered requests with an HTML "visit site" warning page instead of
proxying through — exactly what curl hit before the
`ngrok-skip-browser-warning` header was added to the request. Every real
chat completion through that path would have silently gotten HTML back
where JSON was expected. Fixed by passing
`default_headers={"ngrok-skip-browser-warning": "true"}` to the `OpenAI()`
client constructor when `OLLAMA_BASE_URL` is set — verified by
constructing the real client (openai==1.51.0, the pinned version) against
the actual ngrok URL and confirming the header lands on the client.

Also documented `OLLAMA_BASE_URL`/`OLLAMA_MODEL` in `.env.example` — both
were live `config.py` settings with zero mention in the example file
before this.

To actually use it: set in your local `.env` (not committed) —
```
OLLAMA_BASE_URL=https://spearmint-factoid-brewery.ngrok-free.dev/v1
OLLAMA_MODEL=llama3.1:8b
```
Note the `/v1` suffix — Ollama's OpenAI-compatible routes live there, and
the OpenAI SDK appends `/chat/completions` etc. to whatever `base_url` is.

---

## 8. Embeddings moved from Gemini to local BGE — fixes B2B_AUDIT.md item 4, drops a required key

While walking through local setup, `embeddings.py` turned out to be
asking for a `GEMINI_API_KEY` that the app's own `B2B_AUDIT.md` (item 4,
written a few commits earlier in this same session) had already flagged
as a contradiction: the B2B plan's §4 "self-hosted" deployment claim
explicitly says embeddings should be local BGE, not a hosted API.

- `embeddings.py` — `embed_texts()` no longer calls Gemini's REST API.
  It now lazy-loads a local `sentence-transformers` model
  (`SentenceTransformer(settings.EMBEDDING_MODEL)`, default
  `BAAI/bge-base-en-v1.5`) and encodes locally with
  `normalize_embeddings=True`, the same lazy-singleton pattern
  `reranker.py` already used for its cross-encoder. No more manual
  429-retry loop either — there's no remote quota to hit.
- `config.py` — `EMBEDDING_MODEL` default changed to
  `BAAI/bge-base-en-v1.5`; the `GEMINI_API_KEY` setting is removed
  entirely (confirmed by grep it was read nowhere else).
- `.env.example`, `README.md` — updated to match: only `GROQ_API_KEY`
  and `GITHUB_TOKEN` are needed now, embeddings need no key at all.
- `requirements.txt` — dropped `google-genai`, which turned out to be
  dead weight even before this change (the old Gemini code called the
  REST API directly with `requests`, never through that SDK — grepped
  to confirm zero imports of it anywhere).
- `B2B_AUDIT.md` — item 4 updated from "contradiction found" to "fixed,"
  with the network-boundary table and the doc's own status line updated
  to match reality rather than left stale the moment it was fixed.

Verified end-to-end with the real `sentence-transformers` types stubbed
out (no GPU/network in this sandbox for an actual model download):
`embed_texts([])` still short-circuits to `[]`, a batch of real texts
returns one normalized vector per input with no key set anywhere, the
model loads lazily and is reused across calls, and `main.py` imports
cleanly with `GEMINI_API_KEY` absent from `settings` altogether. Indexing
a real repo will now download `BAAI/bge-base-en-v1.5` on first use (a few
hundred MB, one-time, then fully offline) instead of calling out to
Gemini per chunk.

---

## 9. B2B frontend panels (`src/routes/index.tsx`)

Everything in §6's B2B build-out only existed as backend endpoints,
exercised via raw API calls — the actual chat UI never had a B2B surface.
Added a new "B2B" tab alongside the existing seven (Ask, Issues, Roadmap,
PR Check, Blast Radius, Maintainer Health, Metrics), with its own
sub-navigation:

- **Team Setup** — list/create organizations, register the currently
  indexed repo under one, create/list members.
- **Roster** (`GET /b2b/orgs/{id}/roster`) — the manager view: one card
  per member with open-assignment count, PR-ready rate, roadmap status,
  and an inline "Assign issue" button that calls
  `POST /b2b/members/{id}/assign` and refreshes.
- **Tag Issues** — team-lead tagging UI against
  `POST /b2b/orgs/{id}/issues/tag`, with the existing tag list shown
  below the form.
- **Test Selection** / **Reviewer Routing** — same input pattern as the
  existing Blast Radius panel (comma-separated target files, max-hops
  slider), calling the two endpoints fixed in §6.1.
- **Governance** — `GET /b2b/governance-report` rendered in the same
  table style as the existing Metrics panel, including the caveats list
  (dataset/rubric version nulls, the generation-model note) rather than
  hiding them.

No new UI library — matches the existing file's conventions exactly:
raw Tailwind classes (not the shadcn/ui components sitting unused in
`src/components/ui/`, since the existing panels don't use them either),
the same `apiFetch` helper, and the same `SectionHeader`/`ErrorBox`/
`Spinner`/`Skeleton` primitives. `GET /b2b/team-health` got no dedicated
panel — it's a zero-logic alias of `GET /maintainer-health`, and the
existing Maintainer Health tab already demonstrates that exact response
shape, so a second identical-looking panel would add nothing.

**Verified for real, not just by inspection:** this sandbox has no
persistent frontend toolchain, so `npm install react-markdown --no-save`
was used one-time purely to unblock a type-check (the project's
`node_modules` was otherwise already present but missing that one
package — an artifact of this sandbox, not the real repo). With that in
place: `npx tsc --noEmit -p tsconfig.json` passes with **zero errors**
against the whole file in strict mode, and `npx eslint` reports zero
new issues (the one pre-existing `no-explicit-any` warning is in
`RoadmapPanel`, code this change never touched). Ran `npx prettier
--write` to match the file's existing formatting exactly. That
`react-markdown` install was `--no-save` and touched nothing in
`package.json`/`package-lock.json` — confirmed via `git status` showing
only `index.tsx` changed.

## 10. Synced against upstream `Saradwanth-116/git-quest`, which had moved on without us

This fork branched from `git-quest` early and diverged (HyDE, the
council gate, B2B, local embeddings — none of that exists upstream).
Upstream, meanwhile, kept moving independently and built the piece our
own docs kept flagging as absent: a real Mutagent evaluate/optimize
harness with real datasets. Diffed both trees file-by-file and pulled
across what was real, fixed two regressions the diff exposed, and left
out one file that fabricates results. Nothing here was guessed —
every claim below is a diffed file.

**Regressions fixed** (this fork had these, upstream had already fixed them):
- `clients/llm_client.py` — `complete()` had silently lost its
  `json_mode` parameter (`response_format: json_object`) and `_get()`
  had lost `OLLAMA_BASE_URL` routing entirely, so every caller through
  the shared client (gate, issue_rec, pr_check, issue_health) was stuck
  on Groq with no JSON-mode enforcement, relying purely on prompt text
  to produce parseable JSON. Restored both, and `json_complete()` now
  actually passes `json_mode=True` again. `MAX_RETRIES` restored to 10.
- `pipeline/gate.py` — wasn't passing `json_mode=True` even though the
  gate's entire output is JSON the caller depends on parsing correctly.
- `mutagent/prompts/council.txt` — this fork's rewritten version (part
  2) was stricter than upstream's tuned one: it could reject harmless
  greetings and general-overview questions, and it never told the model
  not to wrap output in a markdown fence. Reverted to upstream's
  version, which is the one that's actually been run through the
  harness (see `mutagent/reports/council.delta.json`, now included).
- `indexing.py` — had a duplicate `from vector_store import add_chunks`
  import, and a comment claiming the embedding batch loop exists
  because of "OpenAI's embeddings endpoint" request-size limits — stale
  from before part 8 moved embeddings local. Fixed both, and added
  `graph_nodes`/`graph_edges` counts to the `/index` response (upstream
  had this; we didn't).

**Real upgrade ported:**
- `hybrid_retriever.py`'s graph-facts injection used to trigger only on
  three hardcoded keywords (`"break"`, `"impact"`, `"rely"`) and find
  target files by literal substring match against the question text —
  brittle, and blind to anything phrased differently. Replaced with
  upstream's approach: every graph/hybrid question now goes through a
  new prompt (`mutagent/prompts/graph_query.txt`) that asks the model to
  translate the question into one of six structured graph operations
  (`blast_radius`, `importers_of`, `imports_of`, `definition_of`,
  `occurrences_of`, `neighbors`), which then actually executes against
  `graph/query_dsl.execute_query()` — the DSL executor was already
  identical in both trees, only the query-construction step was
  outdated here.

**The actual gap this closes — a real self-evolving loop:**
Every previous document in this repo (`CHANGES.md` parts 1-9, the PDC,
`B2B_AUDIT.md`) said the same honest thing: Mutagent's optimize/evaluate
harness doesn't exist in this fork, only the receiving-side prompts and
traces do. That was true when written and is no longer true — upstream
built it. Pulled across wholesale:
- `mutagent/harness.py` — `evaluate()` scores a prompt against a
  dataset+rubric with an LLM judge per criterion, severity-gated
  (a `critical` criterion failing fails the case regardless of weighted
  mean); `optimize()` is a genetic-mutation loop over generations x
  variants that keeps the highest scorer, and is honest when a mutation
  call comes back unparseable (`mutation_failed`, re-evaluates the
  unchanged prompt rather than pretending it improved).
- `mutagent/run.py` — the CLI (`python -m mutagent.run <target>
  [--optimize]`), `mutagent/run_graph_query.py` — a separate runner for
  the graph-query target since it's scored by node-set F1 against the
  real executed graph, not an LLM judge.
- `mutagent/datasets/*.json` + `mutagent/rubrics/*.json` — six real
  targets (`council`, `router`, `issue_rec`, `pr_check`, `issue_health`,
  `graph_query`), 22-70 cases each, none synthetic filler.
- `mutagent/gen_graph_dataset.py` — generates the graph_query dataset by
  actually running the DSL against a real graph rather than
  hand-labelling expected answers. Fixed a real path bug while porting
  it: it wrote to `<repo_root>/mutagent/datasets/graph_query.json`
  instead of `<repo_root>/backend/mutagent/datasets/graph_query.json`
  (used the wrong `REPO_ROOT`-relative path; switched it to
  `config.DATASETS_DIR`, the same single source of truth every other
  loader in this repo already uses).
- `mutagent/reports/council.delta.json` and `issue_rec.delta.json` —
  real prior runs, kept as-is including the unflattering parts: the
  council run's optimize loop failed to mutate for 3 straight
  generations (`mutation_failed`, score never moved off baseline) and
  the report shows that plainly rather than hiding it.
- `.agents/skills/ship/SKILL.md`, `scripts/ship.py`,
  `Dockerfile.backend`, `Dockerfile.frontend`, `docker-compose.yml`,
  `run_mutagent.bat` — a `*ship` ADL stage that packages the app for
  `docker-compose up --build`. Checked what `ship.py` actually does
  before including it: it writes three static files and nothing else —
  no fake gate, no claim of checking a scorecard that doesn't exist.

**Verified before committing:** `python -m mutagent.run <target>
--dry-run` run against all five LLM-judged targets
(council/router/issue_rec/pr_check/issue_health) — all validate cleanly,
every dataset case substitutes into its prompt without a missing key.
Every touched/added `.py` file compiles (`py_compile`); the modules that
don't depend on `tree_sitter_language_pack` (not installed in this
sandbox, unrelated to this change) import cleanly too.

**Deliberately left out — upstream has a file that fabricates results:**
`backend/test_architecture_flow.py` is a manual smoke-test script whose
step 5 ("Simulating Mutagent Optimization Cycle") writes a **hardcoded**
`{"baseline_score": 0.45, "optimized_score": 0.88, ...}` straight into
`mutagent/reports/issue_rec.delta.json` — overwriting the real report
from an actual harness run with invented numbers, labeled only
`"notes": "Simulated mutagent optimization run"` in a field nobody
reads before the governance dashboard displays the score. Not pulled
in. If evidence of the optimize loop is wanted beyond the dry-run above,
the honest path is running `python -m mutagent.run issue_rec
--optimize` for real against a live `GROQ_API_KEY`, not running this
script. `backend/run_stages.py` was also left out — a second smoke-test
script that calls `POST /ask` expecting a JSON body, which no longer
matches this fork's streaming `/ask` contract (part 5); it would need
rewriting to consume the `<<<META>>>` trailer, not a straight copy.
