# B2B Data-Handling Audit (plan §6)

Per the plan: "None of these are hard to satisfy given the architecture,
but they need to be demonstrated with an actual audit, not asserted from
the pitch deck." This is that audit — every claim below is traced to a
specific file and line, not asserted. One finding directly contradicts the
plan document itself (item 4).

Status: **not yet sellable to a security-conscious buyer.** Three of four
items have real, code-verified gaps. One fix shipped in this pass (item 2's
purge mechanism); the rest need infrastructure this pass explicitly didn't
build (real auth, a secrets manager, log redaction policy).

---

## 1. Trace logging — retains raw private-repo content indefinitely

`observability/tracer.py`'s `trace()` appends one JSON line per call to
`mutagent/traces/{component}.jsonl` — the file is append-only, never
rotated, never expired, and not scoped by organization (all orgs hitting
the same server interleave into the same file, keyed only by component
name).

What actually gets written, by caller:

| Caller | Content logged verbatim |
|---|---|
| `pipeline/gate.py` (council) | The full user question, twice (once in `prompt`, once in `extra.query`) |
| `pr_readiness.py` | Up to **4,000 characters of the actual diff text** — real source code from a private repo |
| `maintainer_health.py` | Full issue body text (up to 800 chars per issue, from `GitHubClient.list_issues`) |
| `issue_recommendation.py` | Issue titles + labels (not full bodies) |
| `rag_qa.py` (RAG Q&A, HyDE, answer synthesis) | **Nothing** — this path never calls `trace()` at all |

The `rag_qa.py` gap cuts both ways: it's the path that injects the most
actual source code into a prompt (retrieved chunks as `context`), and it's
the one path with zero audit trail. Less exposure, but also less evidence
for a judge/compliance reviewer, and an inconsistent story across targets.

**Not fixed this pass** — redaction and retention policy are product
decisions, not something to unilaterally bake in. Concrete next step:
add `org_id` to every `trace()` call's `extra`, add file rotation/TTL, and
decide whether diff/issue-body content should be truncated or scrubbed
before being written at all.

## 2. Vector store + graph lifecycle — fixed the mechanism, not the policy

Before this pass: **no deletion path existed anywhere in the codebase.**
`vector_store.py`'s `chromadb.PersistentClient` collections (keyed by
`md5(repo_url)`) and `graph/store.py`'s `.graphs/{repo_id}.json` files
both accumulated forever — the only way to remove one was to manually
delete files on disk.

**Fixed in this pass:** `vector_store.delete_collection()`,
`graph/store.delete_graph()`, and a `DELETE /index?repo_url=...` endpoint
now actually purge both. Verified end-to-end (graph file confirmed removed
from disk after the call).

**Still open:** nothing calls this automatically. There's no session
boundary, no org-deletion hook, no TTL — purging is manual until a real
auth/session layer exists to hang an automatic trigger on. Today, any
indexed repo is also globally queryable by anyone who knows or guesses its
`repo_url`, since `/ask` and `/index` carry no org scoping — the B2B org
model added in this pass doesn't yet gate repo access, it only tracks
which org registered which repo for tagging/roster purposes.

## 3. Token handling — single global token, not scoped per org

`config.py` reads `GITHUB_TOKEN` once at process startup into the
module-level `settings` singleton. Confirmed by reading every call site:
it's never written back to disk, never logged (no `trace()` call includes
it), never cached in the new `b2b/store.py` sqlite tables.

**The real gap:** it's one token for the entire server process, shared by
every organization's requests. The plan's own data model (§2) says each
`Organization` "has many Repos (private, GitHub org-token auth)" — implying
per-org credentials — but the code has exactly one credential, server-wide.
Two organizations onboarded to the same running instance share identical
GitHub access; scope is enforced by the token's own permissions, not by
which org is asking.

**Deliberately not fixed this pass:** adding a `github_token` column to
`organizations` would just move the problem — a plaintext token in a
sqlite file is not meaningfully safer than one in `.env`, arguably worse
since it's now sitting on disk per-org. Real per-org tokens need a secrets
manager (Vault, AWS Secrets Manager, or at minimum encryption-at-rest with
a KMS-managed key), which is infrastructure, not a code change, and stays
out of scope for the "demo scope, no auth" posture this pass was scoped to.

## 4. Network boundary — contradicts the plan's own self-hosted claim

Every outbound call in the codebase, traced to its file:

| Destination | From | When |
|---|---|---|
| `api.github.com` | `clients/github_client.py`, `backend/github_client.py` | every repo/issue/commit lookup |
| `api.groq.com` | `clients/llm_client.py` (gate, issue_rec, pr_check, issue_health) | every one of those calls |
| `generativelanguage.googleapis.com` (Gemini) | `embeddings.py` | every indexed chunk, every HyDE passage |
| Ollama via ngrok (`OLLAMA_BASE_URL`, optional) | `rag_qa.py` only | only if configured, replaces Groq for that file only |
| `huggingface.co` | `reranker.py`'s `CrossEncoder("BAAI/bge-reranker-base")` | **first use only**, then fully local |
| `openaipublic.blob.core.windows.net` | `tiktoken.get_encoding("cl100k_base")` in `embeddings.py` | **first use only**, then fully local (hit this exact wall while testing this pass — see below) |

**Direct contradiction with the plan document:** §4's "Self-hosted" row
claims *"Embeddings (local BGE) ... all run on customer infrastructure;
only the generation call leaves the environment."* That is not what the
code does. `embeddings.py` calls Gemini's hosted embeddings REST API for
every chunk — there is no local BGE embedding path in this codebase today,
despite `sentence-transformers` and `huggingface-hub` already being
dependencies (currently used only for the reranker). This is exactly the
kind of gap §6 warns about: a claim in the pitch document that the running
code does not back up. Swapping in a local `BAAI/bge-base-en-v1.5`
embedding model is plausible future work — the dependencies are already
there — but it's a real feature build, not a config flag, and out of scope
for this pass.

**Also worth stating precisely for a self-hosted claim:** the reranker and
tokenizer both make one outbound call on first use to fetch weights/data,
then run fully offline. A genuinely air-gapped deployment needs those
pre-cached into the image ahead of time, not just "self-hosted" asserted.

---

## Summary

| Item | Status |
|---|---|
| 1. Trace logging | Documented, not fixed — needs a redaction/retention policy decision |
| 2. Vector store / graph lifecycle | **Purge mechanism shipped this pass**; auto-trigger still needs real auth |
| 3. Token handling | Documented — real fix needs a secrets manager, not a code change |
| 4. Network boundary | Documented — found a real contradiction between the plan's §4 claim and the shipped embeddings code |

None of this blocks the demo. All of it blocks presenting §4's
"self-hosted" row or the governance dashboard (`/b2b/governance-report`)
as compliance-ready without the caveats above — which is why both surfaces
now report `dataset_version`/`rubric_version` as `null` and include a
`generation_model_note` that reflects what's actually configured, rather
than asserting the one-model constraint unconditionally.
