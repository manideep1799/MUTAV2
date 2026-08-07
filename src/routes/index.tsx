import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useRef, useState, type FormEvent } from "react";
import ReactMarkdown from "react-markdown";

export const Route = createFileRoute("/")({
  component: App,
});

const API = "http://127.0.0.1:8000";

type Section = "ask" | "issues" | "roadmap" | "pr" | "blast" | "health" | "metrics" | "b2b";

type IndexResp = { files_indexed: number; chunks_created: number; total_repo_files: number };
type AskResp = { answer: string; sources: string[] };
type IssueResp = { issue_id: number | null; title: string | null; rationale: string };
type RoadmapResp = { roadmap: string; central_files: string[] };
type PRResp = {
  checklist: {
    has_tests: boolean;
    touches_docs: boolean;
    diff_size_lines: number;
    is_large_diff: boolean;
    touches_security_sensitive_path?: boolean;
  };
  verdict: "ready" | "needs_changes" | "blocked" | null;
  report: string;
  rationale: string;
};
type BlastResp = {
  nodes: {
    path: string;
    kind: "import" | "occurrence";
    hops: number;
    reason: string;
  }[];
  coverage_tier: string;
  truncated: boolean;
  error: string | null;
};
type HealthResp = {
  score: number | null;
  mislabelled: { number: number; title: string; rationale: string }[];
  latency_days: number | null;
  scanned: number;
};
type MetricsResp = {
  targets: {
    id: string;
    name: string;
    priority: string;
    trace_count: number;
    has_report: boolean;
    metric?: string;
    baseline_score?: number;
    optimized_score?: number;
    delta?: number;
    generations?: number;
    optimized?: boolean;
    mean_f1?: number;
  }[];
};

/* ---- B2B types ---- */
type B2BOrg = {
  id: number;
  name: string;
  test_selection_threshold: number;
  reviewer_routing_enabled: number;
  created_at: string;
};
type B2BMember = {
  id: number;
  org_id: number;
  name: string;
  email: string;
  skill_profile: string;
  created_at: string;
};
type B2BTaggedIssue = {
  id: number;
  org_id: number;
  repo_url: string;
  issue_number: number;
  tag: string;
  subsystem: string;
  tagged_by: string;
  created_at: string;
};
type B2BAssignedIssue = {
  id: number;
  member_id: number;
  repo_url: string;
  issue_number: number | null;
  issue_title: string;
  rationale: string;
  status: string;
  created_at: string;
};
type B2BRoadmapStatus = { member_id: number; repo_url: string; status: string; updated_at: string };
type B2BRosterEntry = {
  member: B2BMember;
  assigned_issues: B2BAssignedIssue[];
  open_assignment_count: number;
  roadmap_status: B2BRoadmapStatus[];
  pr_readiness_history: {
    verdict: string | null;
    diff_size_lines: number;
    has_tests: number;
    created_at: string;
  }[];
  pr_ready_rate: number | null;
};
type B2BTestSelectionResp = {
  tests: { path: string; hops: number; reason: string }[];
  total_tests: number;
  selected: number;
  ratio: string;
  error?: string | null;
  disclaimer: string;
};
type B2BReviewerResp = {
  reviewers: { login: string; files_touched: number; score: number; last_touched: string | null }[];
  blast_radius_size: number;
  error: string | null;
};
type B2BGovernanceResp = {
  generated_at: string;
  generation_model_note: string;
  components: {
    component: string;
    name: string;
    priority: string;
    evaluated: boolean;
    last_evaluated: string | null;
    baseline_score?: number;
    current_score?: number;
    delta?: number;
    mean_f1?: number;
    trace_count: number;
    dataset_version: string | null;
    rubric_version: string | null;
  }[];
  caveats: string[];
};

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    });
  } catch {
    throw new Error("Could not reach backend at http://127.0.0.1:8000");
  }
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      msg = body.detail || body.error || body.message || msg;
    } catch {
      // ignore
    }
    throw new Error(msg);
  }
  return (await res.json()) as T;
}

function App() {
  const [repoUrl, setRepoUrl] = useState("");
  const [indexed, setIndexed] = useState<{ url: string; stats: IndexResp } | null>(null);

  if (!indexed) {
    return <IndexScreen repoUrl={repoUrl} setRepoUrl={setRepoUrl} onIndexed={setIndexed} />;
  }

  return (
    <Workspace
      repoUrl={indexed.url}
      stats={indexed.stats}
      onChangeRepo={() => {
        setIndexed(null);
        setRepoUrl("");
      }}
    />
  );
}

/* ---------------- Landing / Index screen ---------------- */

function IndexScreen({
  repoUrl,
  setRepoUrl,
  onIndexed,
}: {
  repoUrl: string;
  setRepoUrl: (v: string) => void;
  onIndexed: (v: { url: string; stats: IndexResp }) => void;
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!repoUrl.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const stats = await apiFetch<IndexResp>("/index", {
        method: "POST",
        body: JSON.stringify({ repo_url: repoUrl.trim() }),
      });
      onIndexed({ url: repoUrl.trim(), stats });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col">
      <TopBar />
      <main className="flex-1 flex items-center justify-center px-6 py-16">
        <div className="w-full max-w-2xl">
          <div className="mb-10">
            <div className="mono text-xs text-muted-foreground mb-3 tracking-widest uppercase">
              Open Source Mentor++
            </div>
            <h1 className="text-4xl md:text-5xl font-semibold tracking-tight leading-tight">
              Onboard to any repository,
              <br />
              <span className="text-muted-foreground">in minutes.</span>
            </h1>
            <p className="mt-4 text-muted-foreground max-w-lg">
              Index a GitHub repo, then ask questions, get issue recommendations, generate a
              learning roadmap, and check PR readiness.
            </p>
          </div>

          <form onSubmit={submit} className="space-y-3">
            <label className="mono text-xs text-muted-foreground block">
              GITHUB REPOSITORY URL
            </label>
            <div className="flex flex-col sm:flex-row gap-2">
              <input
                type="url"
                required
                placeholder="https://github.com/owner/repo"
                value={repoUrl}
                onChange={(e) => setRepoUrl(e.target.value)}
                className="mono flex-1 px-4 py-3 rounded-md bg-input border border-border text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent transition"
                disabled={loading}
              />
              <button
                type="submit"
                disabled={loading}
                className="px-5 py-3 rounded-md bg-accent text-accent-foreground text-sm font-medium hover:opacity-90 disabled:opacity-50 transition inline-flex items-center justify-center gap-2 min-w-[160px]"
              >
                {loading ? (
                  <>
                    <Spinner /> Indexing…
                  </>
                ) : (
                  "Index repository"
                )}
              </button>
            </div>
            {error && <ErrorBox message={error} />}
          </form>

          <div className="mt-10 grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              { k: "Ask", d: "RAG Q&A over the codebase" },
              { k: "Issues", d: "Good-first-issue picks" },
              { k: "Roadmap", d: "Personalized learning path" },
              { k: "PR Check", d: "Diff readiness report" },
              { k: "Blast", d: "Structural impact analysis" },
            ].map((x) => (
              <div key={x.k} className="p-4 rounded-md border border-border bg-card">
                <div className="mono text-xs text-accent">{x.k}</div>
                <div className="text-xs text-muted-foreground mt-1">{x.d}</div>
              </div>
            ))}
          </div>
        </div>
      </main>
    </div>
  );
}

/* ---------------- Workspace ---------------- */

function Workspace({
  repoUrl,
  stats,
  onChangeRepo,
}: {
  repoUrl: string;
  stats: IndexResp;
  onChangeRepo: () => void;
}) {
  const [section, setSection] = useState<Section>("ask");
  const repoName = repoUrl.replace(/^https?:\/\/(www\.)?github\.com\//, "").replace(/\/$/, "");

  const tabs: { key: Section; label: string }[] = [
    { key: "ask", label: "Ask" },
    { key: "issues", label: "Issues" },
    { key: "roadmap", label: "Roadmap" },
    { key: "pr", label: "PR Check" },
    { key: "blast", label: "Blast Radius" },
    { key: "health", label: "Maintainer Health" },
    { key: "metrics", label: "Metrics" },
    { key: "b2b", label: "B2B" },
  ];

  return (
    <div className="min-h-screen flex flex-col">
      <TopBar />
      <div className="border-b border-border">
        <div className="max-w-6xl mx-auto px-6 py-4 flex flex-wrap items-center gap-4 justify-between">
          <div className="min-w-0">
            <div className="mono text-xs text-muted-foreground">INDEXED REPOSITORY</div>
            <div className="mono text-sm text-foreground truncate mt-0.5">{repoName}</div>
            <div className="mono text-xs text-muted-foreground mt-1">
              {stats.files_indexed} / {stats.total_repo_files} files indexed ·{" "}
              {stats.chunks_created} chunks
            </div>
          </div>
          <button
            onClick={onChangeRepo}
            className="px-3 py-1.5 rounded-md border border-border bg-card text-xs hover:bg-muted transition mono"
          >
            ← Change repo
          </button>
        </div>
        <div className="max-w-6xl mx-auto px-6 flex gap-1">
          {tabs.map((t) => (
            <button
              key={t.key}
              onClick={() => setSection(t.key)}
              className={`px-4 py-2.5 text-sm border-b-2 -mb-px transition ${
                section === t.key
                  ? "border-accent text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <main className="flex-1">
        <div className="max-w-6xl mx-auto px-6 py-8">
          {section === "ask" && <AskPanel repoUrl={repoUrl} />}
          {section === "issues" && <IssuesPanel repoUrl={repoUrl} />}
          {section === "roadmap" && <RoadmapPanel repoUrl={repoUrl} />}
          {section === "pr" && <PRPanel />}
          {section === "blast" && <BlastPanel repoUrl={repoUrl} />}
          {section === "health" && <HealthPanel repoUrl={repoUrl} />}
          {section === "metrics" && <MetricsPanel />}
          {section === "b2b" && <B2BPanel repoUrl={repoUrl} />}
        </div>
      </main>
    </div>
  );
}

/* ---------------- Ask ---------------- */

type ChatMessage =
  | { role: "user"; content: string }
  | { role: "assistant"; content: string; sources: string[] }
  | { role: "error"; content: string };

function AskPanel({ repoUrl }: { repoUrl: string }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, loading]);

  const send = async (e: FormEvent) => {
    e.preventDefault();
    const q = input.trim();
    if (!q || loading) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", content: q }]);
    setLoading(true);

    try {
      let res: Response;
      try {
        res = await fetch(`${API}/ask`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ repo_url: repoUrl, question: q }),
        });
      } catch {
        throw new Error("Could not reach backend at http://127.0.0.1:8000");
      }
      if (!res.ok) {
        let msg = `Request failed (${res.status})`;
        try {
          const body = await res.json();
          msg = body.detail || body.error || body.message || msg;
        } catch {
          // ignore
        }
        throw new Error(msg);
      }

      // The council gate rejects a question as plain JSON (no stream, no LLM
      // call). A passing question streams back as text/plain instead.
      const isJson = (res.headers.get("content-type") || "").includes("application/json");
      if (isJson) {
        const body: AskResp = await res.json();
        setMessages((m) => [
          ...m,
          { role: "assistant", content: body.answer, sources: body.sources || [] },
        ]);
        return;
      }

      // Streamed answer: grow one assistant bubble as tokens arrive, then peel
      // the "\n\n<<<META>>>{json}" trailer off the end for sources.
      setMessages((m) => [...m, { role: "assistant", content: "", sources: [] }]);
      const marker = "\n\n<<<META>>>";
      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const markerIdx = buffer.indexOf(marker);
        const visible = markerIdx === -1 ? buffer : buffer.slice(0, markerIdx);
        setMessages((m) => {
          const next = [...m];
          next[next.length - 1] = { role: "assistant", content: visible, sources: [] };
          return next;
        });
      }

      const markerIdx = buffer.indexOf(marker);
      const finalText = markerIdx === -1 ? buffer : buffer.slice(0, markerIdx);
      let sources: string[] = [];
      if (markerIdx !== -1) {
        try {
          sources = JSON.parse(buffer.slice(markerIdx + marker.length)).sources || [];
        } catch {
          // malformed trailer — keep the text we already streamed, just skip sources
        }
      }
      setMessages((m) => {
        const next = [...m];
        next[next.length - 1] = { role: "assistant", content: finalText, sources };
        return next;
      });
    } catch (err) {
      setMessages((m) => [...m, { role: "error", content: (err as Error).message }]);
    } finally {
      setLoading(false);
    }
  };

  // Hide the "thinking" spinner once the streamed answer bubble has visible text.
  let showThinking = loading;
  if (loading && messages.length > 0) {
    const last = messages[messages.length - 1];
    if (last.role === "assistant" && last.content !== "") {
      showThinking = false;
    }
  }

  return (
    <div className="flex flex-col h-[calc(100vh-260px)] min-h-[500px]">
      <div ref={scrollRef} className="flex-1 overflow-y-auto pr-2 space-y-6">
        {messages.length === 0 && (
          <div className="text-center py-16 text-muted-foreground text-sm">
            Ask anything about this repository — architecture, files, how to run it, where a feature
            lives…
          </div>
        )}
        {messages.map((m, i) => (
          <MessageBubble key={i} message={m} />
        ))}
        {showThinking && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Spinner /> <span className="mono text-xs">thinking…</span>
          </div>
        )}
      </div>

      <form onSubmit={send} className="mt-4 flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about this repository…"
          disabled={loading}
          className="flex-1 px-4 py-3 rounded-md bg-input border border-border text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring transition"
        />
        <button
          type="submit"
          disabled={loading || !input.trim()}
          className="px-5 py-3 rounded-md bg-accent text-accent-foreground text-sm font-medium hover:opacity-90 disabled:opacity-50 transition"
        >
          Send
        </button>
      </form>
    </div>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] px-4 py-2.5 rounded-md bg-secondary text-secondary-foreground text-sm">
          {message.content}
        </div>
      </div>
    );
  }
  if (message.role === "error") {
    return <ErrorBox message={message.content} />;
  }
  return (
    <div>
      <div className="mono text-xs text-muted-foreground mb-2">ASSISTANT</div>
      <div className="prose-md text-sm">
        <ReactMarkdown>{message.content}</ReactMarkdown>
      </div>
      {message.sources.length > 0 && (
        <div className="mt-3">
          <div className="mono text-[10px] text-muted-foreground mb-1.5 tracking-widest">
            SOURCES
          </div>
          <div className="flex flex-wrap gap-1.5">
            {message.sources.map((s, i) => (
              <span
                key={i}
                className="mono text-xs px-2 py-1 rounded border border-border bg-card text-muted-foreground"
              >
                {s}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------------- Issues ---------------- */

function IssuesPanel({ repoUrl }: { repoUrl: string }) {
  const [issue, setIssue] = useState<IssueResp | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [profile, setProfile] = useState("general contributor");

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await apiFetch<IssueResp>("/recommend-issue", {
        method: "POST",
        body: JSON.stringify({ repo_url: repoUrl, user_profile: profile }),
      });
      setIssue(r);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-3xl">
      <SectionHeader
        title="Recommend an issue"
        description="Get a suggested good-first-issue matched to your profile."
      />

      <div className="space-y-3 mb-6">
        <label className="mono text-xs text-muted-foreground block">YOUR PROFILE</label>
        <input
          type="text"
          value={profile}
          onChange={(e) => setProfile(e.target.value)}
          placeholder="e.g. Python developer new to open source, interested in testing"
          className="mono w-full px-4 py-3 rounded-md bg-input border border-border text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring transition"
          disabled={loading}
        />
        <button
          onClick={run}
          disabled={loading}
          className="px-5 py-3 rounded-md bg-accent text-accent-foreground text-sm font-medium hover:opacity-90 disabled:opacity-50 transition inline-flex items-center gap-2"
        >
          {loading ? (
            <>
              <Spinner /> Matching…
            </>
          ) : (
            "Recommend an issue"
          )}
        </button>
      </div>

      {error && !loading && <ErrorBox message={error} />}

      {issue && !loading && (
        <div className="space-y-4">
          {issue.issue_id === null ? (
            <div className="p-6 rounded-md border border-border bg-card text-sm text-muted-foreground">
              {issue.rationale}
            </div>
          ) : (
            <div className="p-6 rounded-md border border-border bg-card">
              <div className="flex items-baseline gap-3 mb-3">
                <span className="mono text-sm text-accent">#{issue.issue_id}</span>
                <h3 className="text-lg font-semibold leading-tight">{issue.title}</h3>
              </div>
              <div className="mono text-[10px] text-muted-foreground mb-2 tracking-widest">
                RATIONALE
              </div>
              <div className="prose-md text-sm">
                <ReactMarkdown>{issue.rationale}</ReactMarkdown>
              </div>
            </div>
          )}
          <button
            onClick={run}
            className="px-4 py-2 rounded-md border border-border bg-card text-sm hover:bg-muted transition"
          >
            Get another recommendation
          </button>
        </div>
      )}
    </div>
  );
}

/* ---------------- Roadmap ---------------- */

function RoadmapPanel({ repoUrl }: { repoUrl: string }) {
  const [roadmap, setRoadmap] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await apiFetch<RoadmapResp>("/roadmap", {
        method: "POST",
        body: JSON.stringify({ repo_url: repoUrl }),
      });
      setRoadmap(r.roadmap || (r as any).markdown || "");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-3xl">
      <SectionHeader
        title="Learning roadmap"
        description="Generate a personalized path for exploring this codebase."
      />

      <div className="flex items-center gap-3 mb-6">
        <button
          onClick={run}
          disabled={loading}
          className="px-5 py-3 rounded-md bg-accent text-accent-foreground text-sm font-medium hover:opacity-90 disabled:opacity-50 transition inline-flex items-center gap-2"
        >
          {loading ? (
            <>
              <Spinner /> Generating…
            </>
          ) : roadmap ? (
            "Regenerate roadmap"
          ) : (
            "Generate roadmap"
          )}
        </button>
      </div>

      {error && <ErrorBox message={error} />}

      {roadmap && !loading && (
        <div className="space-y-4">
          <div className="p-6 rounded-md border border-border bg-card prose-md text-sm">
            <ReactMarkdown>{roadmap}</ReactMarkdown>
          </div>
        </div>
      )}

      {loading && !roadmap && (
        <div className="space-y-2">
          <Skeleton className="h-5 w-1/3" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-11/12" />
          <Skeleton className="h-3 w-10/12" />
          <Skeleton className="h-5 w-1/4 mt-4" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-9/12" />
        </div>
      )}
    </div>
  );
}

/* ---------------- PR Check ---------------- */

function PRPanel() {
  const [diff, setDiff] = useState("");
  const [result, setResult] = useState<PRResp | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (e: FormEvent) => {
    e.preventDefault();
    if (!diff.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const r = await apiFetch<PRResp>("/pr-check", {
        method: "POST",
        body: JSON.stringify({ diff_text: diff }),
      });
      setResult(r);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-4xl">
      <SectionHeader
        title="PR readiness check"
        description="Paste a git diff to get a readiness report and rule checklist."
      />

      <form onSubmit={run} className="space-y-3">
        <label className="mono text-xs text-muted-foreground block">GIT DIFF</label>
        <textarea
          value={diff}
          onChange={(e) => setDiff(e.target.value)}
          placeholder="diff --git a/src/index.ts b/src/index.ts&#10;@@ -1,5 +1,7 @@..."
          rows={12}
          className="mono w-full px-4 py-3 rounded-md bg-input border border-border text-xs placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring transition resize-y"
          disabled={loading}
        />
        <button
          type="submit"
          disabled={loading || !diff.trim()}
          className="px-5 py-3 rounded-md bg-accent text-accent-foreground text-sm font-medium hover:opacity-90 disabled:opacity-50 transition inline-flex items-center gap-2"
        >
          {loading ? (
            <>
              <Spinner /> Checking…
            </>
          ) : (
            "Check readiness"
          )}
        </button>
      </form>

      {error && (
        <div className="mt-4">
          <ErrorBox message={error} />
        </div>
      )}

      {result && !loading && (
        <div className="mt-8 space-y-6">
          {result.verdict && (
            <div
              className={`px-4 py-3 rounded-md text-sm font-medium mono border ${
                result.verdict === "ready"
                  ? "bg-green-500/10 text-green-500 border-green-500/20"
                  : result.verdict === "blocked"
                    ? "bg-red-500/10 text-red-500 border-red-500/20"
                    : "bg-yellow-500/10 text-yellow-500 border-yellow-500/20"
              }`}
            >
              VERDICT: {result.verdict.toUpperCase().replace("_", " ")}
            </div>
          )}
          <div>
            <div className="mono text-xs text-muted-foreground mb-3 tracking-widest">CHECKLIST</div>
            <div className="grid sm:grid-cols-2 gap-2">
              <CheckRow label="Has tests" pass={result.checklist.has_tests} />
              <CheckRow label="Touches docs" pass={result.checklist.touches_docs} />
              <CheckRow
                label="Diff size"
                neutral
                value={`${result.checklist.diff_size_lines} lines`}
              />
              <CheckRow label="Diff size acceptable" pass={!result.checklist.is_large_diff} />
              {result.checklist.touches_security_sensitive_path !== undefined && (
                <CheckRow
                  label="Security sensitive path"
                  pass={!result.checklist.touches_security_sensitive_path}
                />
              )}
            </div>
          </div>

          <div>
            <div className="mono text-xs text-muted-foreground mb-3 tracking-widest">
              READINESS REPORT
            </div>
            <div className="p-6 rounded-md border border-border bg-card prose-md text-sm">
              <ReactMarkdown>{result.report}</ReactMarkdown>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function CheckRow({
  label,
  pass,
  neutral,
  value,
}: {
  label: string;
  pass?: boolean;
  neutral?: boolean;
  value?: string;
}) {
  return (
    <div className="flex items-center justify-between px-4 py-3 rounded-md border border-border bg-card">
      <div className="text-sm">{label}</div>
      {neutral ? (
        <span className="mono text-xs text-muted-foreground">{value}</span>
      ) : (
        <span
          className={`mono text-xs px-2 py-1 rounded inline-flex items-center gap-1.5 ${
            pass ? "bg-success/15 text-success" : "bg-destructive/15 text-destructive"
          }`}
          style={{
            color: pass ? "var(--color-success)" : "var(--color-destructive)",
            backgroundColor: pass
              ? "color-mix(in oklab, var(--color-success) 15%, transparent)"
              : "color-mix(in oklab, var(--color-destructive) 15%, transparent)",
          }}
        >
          <span
            className="w-1.5 h-1.5 rounded-full"
            style={{
              backgroundColor: pass ? "var(--color-success)" : "var(--color-destructive)",
            }}
          />
          {pass ? "PASS" : "FAIL"}
        </span>
      )}
    </div>
  );
}

function BlastPanel({ repoUrl }: { repoUrl: string }) {
  const [targets, setTargets] = useState("");
  const [maxHops, setMaxHops] = useState(3);
  const [result, setResult] = useState<BlastResp | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (e: FormEvent) => {
    e.preventDefault();
    if (!targets.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const targetList = targets
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);
      const r = await apiFetch<BlastResp>("/blast-radius", {
        method: "POST",
        body: JSON.stringify({ repo_url: repoUrl, targets: targetList, max_hops: maxHops }),
      });
      if (r.error) {
        setError(r.error);
      } else {
        setResult(r);
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-4xl">
      <SectionHeader
        title="Blast Radius Analysis"
        description="Deterministic, multi-hop dependency and occurrence tracking using the deep graph."
      />

      <form onSubmit={run} className="space-y-4">
        <div>
          <label className="mono text-xs text-muted-foreground block mb-1">TARGET FILES</label>
          <div className="flex flex-col sm:flex-row gap-2">
            <input
              type="text"
              value={targets}
              onChange={(e) => setTargets(e.target.value)}
              placeholder="e.g. src/auth.py, src/utils.py"
              className="mono flex-1 px-4 py-3 rounded-md bg-input border border-border text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring transition"
              disabled={loading}
            />
            <button
              type="submit"
              disabled={loading || !targets.trim()}
              className="px-5 py-3 rounded-md bg-accent text-accent-foreground text-sm font-medium hover:opacity-90 disabled:opacity-50 transition inline-flex items-center gap-2 min-w-[160px] justify-center"
            >
              {loading ? (
                <>
                  <Spinner /> Querying Graph…
                </>
              ) : (
                "Analyze Impact"
              )}
            </button>
          </div>
        </div>
        <div>
          <label className="mono text-xs text-muted-foreground flex items-center justify-between">
            <span>MAX HOPS: {maxHops}</span>
            <span className="text-muted-foreground/50">Limits dependency recursion depth</span>
          </label>
          <input
            type="range"
            min="1"
            max="10"
            value={maxHops}
            onChange={(e) => setMaxHops(parseInt(e.target.value))}
            className="w-full mt-2 accent-accent"
            disabled={loading}
          />
        </div>
      </form>

      {error && (
        <div className="mt-4">
          <ErrorBox message={error} />
        </div>
      )}

      {result && !loading && (
        <div className="mt-8">
          <div className="flex items-center justify-between mb-4">
            <div className="mono text-xs text-muted-foreground tracking-widest">
              IMPACTED FILES ({result.nodes.length}
              {result.truncated ? "+" : ""})
            </div>
            <div
              className={`mono text-xs px-2 py-1 rounded border ${
                result.coverage_tier === "deep"
                  ? "bg-success/15 text-success border-success/20"
                  : result.coverage_tier === "occurrence-only"
                    ? "bg-yellow-500/15 text-yellow-500 border-yellow-500/20"
                    : "bg-destructive/15 text-destructive border-destructive/20"
              }`}
            >
              Tier: {result.coverage_tier}
            </div>
          </div>

          <div className="border border-border rounded-md overflow-hidden bg-card">
            {result.nodes.length === 0 ? (
              <div className="p-8 text-center text-sm text-muted-foreground">
                No impacted files found within {maxHops} hop{maxHops > 1 ? "s" : ""}.
              </div>
            ) : (
              <div className="divide-y divide-border max-h-[500px] overflow-y-auto">
                {result.nodes.map((node, idx) => (
                  <div
                    key={idx}
                    className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3 hover:bg-muted/50 transition"
                  >
                    <div className="min-w-0">
                      <div className="mono text-sm text-foreground truncate">{node.path}</div>
                      <div className="text-xs text-muted-foreground mt-1 truncate">
                        {node.reason}
                      </div>
                    </div>
                    <div className="flex items-center gap-3 shrink-0">
                      <span
                        className={`mono text-xs px-2 py-1 rounded ${
                          node.kind === "import"
                            ? "bg-accent/10 text-accent"
                            : "bg-primary/10 text-primary"
                        }`}
                      >
                        {node.kind}
                      </span>
                      <span className="mono text-xs text-muted-foreground w-16 text-right">
                        Hop {node.hops}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
            {result.truncated && (
              <div className="p-3 text-center text-xs text-muted-foreground bg-muted/30 border-t border-border">
                Results truncated to {result.nodes.length} nodes to protect performance.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------------- Health Panel ---------------- */

function HealthPanel({ repoUrl }: { repoUrl: string }) {
  const [result, setResult] = useState<HealthResp | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await apiFetch<HealthResp>(
        `/maintainer-health?repo_url=${encodeURIComponent(repoUrl)}`,
      );
      setResult(r);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const scoreColor =
    result === null
      ? "text-muted-foreground"
      : result.score === null
        ? "text-muted-foreground"
        : result.score >= 0.7
          ? "text-green-500"
          : result.score >= 0.4
            ? "text-yellow-500"
            : "text-red-500";

  return (
    <div className="max-w-4xl">
      <SectionHeader
        title="Maintainer Health"
        description="LLM-scored analysis of open issues: health, mislabelling, and response latency."
      />

      <button
        onClick={run}
        disabled={loading}
        className="px-5 py-3 rounded-md bg-accent text-accent-foreground text-sm font-medium hover:opacity-90 disabled:opacity-50 transition inline-flex items-center gap-2 mb-6"
      >
        {loading ? (
          <>
            <Spinner /> Scanning issues…
          </>
        ) : result ? (
          "Re-scan"
        ) : (
          "Scan repository"
        )}
      </button>

      {error && <ErrorBox message={error} />}

      {result && !loading && (
        <div className="space-y-6">
          <div className="grid sm:grid-cols-3 gap-4">
            <div className="p-5 rounded-md border border-border bg-card">
              <div className="mono text-[10px] text-muted-foreground mb-2 tracking-widest">
                HEALTH SCORE
              </div>
              <div className={`text-3xl font-bold mono ${scoreColor}`}>
                {result.score === null ? "—" : `${(result.score * 100).toFixed(0)}%`}
              </div>
              <div className="text-xs text-muted-foreground mt-1">of issues classified healthy</div>
            </div>
            <div className="p-5 rounded-md border border-border bg-card">
              <div className="mono text-[10px] text-muted-foreground mb-2 tracking-widest">
                MEDIAN LATENCY
              </div>
              <div className="text-3xl font-bold mono">
                {result.latency_days === null ? "—" : `${result.latency_days}d`}
              </div>
              <div className="text-xs text-muted-foreground mt-1">creation → last update</div>
            </div>
            <div className="p-5 rounded-md border border-border bg-card">
              <div className="mono text-[10px] text-muted-foreground mb-2 tracking-widest">
                ISSUES SCANNED
              </div>
              <div className="text-3xl font-bold mono">{result.scanned}</div>
              <div className="text-xs text-muted-foreground mt-1">open issues analyzed</div>
            </div>
          </div>

          {result.mislabelled.length > 0 && (
            <div>
              <div className="mono text-xs text-muted-foreground mb-3 tracking-widest">
                MISLABELLED ISSUES ({result.mislabelled.length})
              </div>
              <div className="border border-border rounded-md overflow-hidden bg-card divide-y divide-border">
                {result.mislabelled.map((issue) => (
                  <div key={issue.number} className="p-4">
                    <div className="flex items-baseline gap-2 mb-1">
                      <span className="mono text-xs text-accent">#{issue.number}</span>
                      <span className="text-sm font-medium">{issue.title}</span>
                    </div>
                    <div className="text-xs text-muted-foreground">{issue.rationale}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {result.mislabelled.length === 0 && result.scanned > 0 && (
            <div className="p-4 rounded-md border border-border bg-card text-sm text-muted-foreground">
              ✓ No mislabelled issues found in the scanned set.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ---------------- Metrics Panel ---------------- */

function MetricsPanel() {
  const [result, setResult] = useState<MetricsResp | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await apiFetch<MetricsResp>("/metrics");
      setResult(r);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  // Load on mount via useEffect — calling load() directly during render causes
  // a React crash because setting state triggers re-renders before the first
  // render is even committed.
  useEffect(() => {
    load();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const priorityColor = (p: string) =>
    p === "critical"
      ? "text-red-500 bg-red-500/10 border-red-500/20"
      : p === "high"
        ? "text-orange-500 bg-orange-500/10 border-orange-500/20"
        : p === "medium"
          ? "text-yellow-500 bg-yellow-500/10 border-yellow-500/20"
          : "text-muted-foreground bg-muted border-border";

  return (
    <div className="max-w-5xl">
      <SectionHeader
        title="Mutagent Reliability Dashboard"
        description="Per-target Mutagent evaluation scores. Baseline vs. optimized prompt performance."
      />

      <button
        onClick={load}
        disabled={loading}
        className="px-4 py-2 rounded-md border border-border bg-card text-xs hover:bg-muted transition mono mb-6"
      >
        {loading ? "Refreshing…" : "↻ Refresh"}
      </button>

      {error && <ErrorBox message={error} />}

      {loading && !result && (
        <div className="space-y-2">
          {[...Array(6)].map((_, i) => (
            <Skeleton key={i} className="h-14 w-full" />
          ))}
        </div>
      )}

      {result && (
        <div className="border border-border rounded-md overflow-hidden bg-card">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="px-4 py-3 text-left mono text-[10px] text-muted-foreground tracking-widest font-normal">
                  TARGET
                </th>
                <th className="px-4 py-3 text-left mono text-[10px] text-muted-foreground tracking-widest font-normal">
                  PRIORITY
                </th>
                <th className="px-4 py-3 text-right mono text-[10px] text-muted-foreground tracking-widest font-normal">
                  TRACES
                </th>
                <th className="px-4 py-3 text-right mono text-[10px] text-muted-foreground tracking-widest font-normal">
                  BASELINE
                </th>
                <th className="px-4 py-3 text-right mono text-[10px] text-muted-foreground tracking-widest font-normal">
                  OPTIMIZED
                </th>
                <th className="px-4 py-3 text-right mono text-[10px] text-muted-foreground tracking-widest font-normal">
                  DELTA
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {result.targets.map((t) => (
                <tr key={t.id} className="hover:bg-muted/30 transition">
                  <td className="px-4 py-3">
                    <div className="mono text-xs font-medium">{t.name}</div>
                    <div className="mono text-[10px] text-muted-foreground">{t.id}</div>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`mono text-[10px] px-2 py-0.5 rounded border ${priorityColor(t.priority)}`}
                    >
                      {t.priority}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right mono text-xs text-muted-foreground">
                    {t.trace_count}
                  </td>
                  <td className="px-4 py-3 text-right mono text-xs">
                    {t.baseline_score !== undefined
                      ? `${(t.baseline_score * 100).toFixed(0)}%`
                      : t.mean_f1 !== undefined
                        ? `F1 ${t.mean_f1.toFixed(2)}`
                        : "—"}
                  </td>
                  <td className="px-4 py-3 text-right mono text-xs">
                    {t.optimized_score !== undefined
                      ? `${(t.optimized_score * 100).toFixed(0)}%`
                      : "—"}
                  </td>
                  <td className="px-4 py-3 text-right mono text-xs">
                    {t.delta !== undefined && t.delta !== null ? (
                      <span className={t.delta >= 0 ? "text-green-500" : "text-red-500"}>
                        {t.delta >= 0 ? "+" : ""}
                        {(t.delta * 100).toFixed(0)}%
                      </span>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-xs text-muted-foreground mt-4 mono">
        Scores read from <code>backend/mutagent/reports/*.delta.json</code> — run Mutagent optimize
        to populate.
      </p>
    </div>
  );
}

/* ---------------- B2B ---------------- */

type B2BSubSection =
  "team" | "roster" | "tags" | "test-selection" | "reviewer-routing" | "governance";

function B2BPanel({ repoUrl }: { repoUrl: string }) {
  const [orgId, setOrgId] = useState<number | null>(null);
  const [orgName, setOrgName] = useState<string | null>(null);
  const [sub, setSub] = useState<B2BSubSection>("team");

  const subTabs: { key: B2BSubSection; label: string }[] = [
    { key: "team", label: "Team Setup" },
    { key: "roster", label: "Roster" },
    { key: "tags", label: "Tag Issues" },
    { key: "test-selection", label: "Test Selection" },
    { key: "reviewer-routing", label: "Reviewer Routing" },
    { key: "governance", label: "Governance" },
  ];

  return (
    <div>
      <SectionHeader
        title="B2B / Enterprise"
        description="Same engine as above — organization/team roster, change-impact tooling, and governance evidence, framed for engineering leadership instead of an individual contributor."
      />

      <div className="flex flex-wrap gap-2 mb-4">
        {subTabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setSub(t.key)}
            className={`px-3 py-1.5 rounded-md text-xs mono border transition ${
              sub === t.key
                ? "bg-accent text-accent-foreground border-accent"
                : "border-border bg-card text-muted-foreground hover:text-foreground"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {orgId !== null && (
        <div className="mb-6 px-3 py-2 rounded-md border border-border bg-card inline-flex items-center gap-3">
          <span className="mono text-[10px] text-muted-foreground tracking-widest">ORG</span>
          <span className="mono text-xs">
            {orgName} (#{orgId})
          </span>
          <button
            onClick={() => {
              setOrgId(null);
              setOrgName(null);
            }}
            className="mono text-xs text-muted-foreground hover:text-foreground"
          >
            change
          </button>
        </div>
      )}

      {sub === "team" && (
        <B2BTeamPanel
          repoUrl={repoUrl}
          orgId={orgId}
          orgName={orgName}
          onOrgSelected={(id, name) => {
            setOrgId(id);
            setOrgName(name);
          }}
        />
      )}
      {sub === "roster" && <B2BRosterPanel orgId={orgId} />}
      {sub === "tags" && <B2BTagPanel repoUrl={repoUrl} orgId={orgId} />}
      {sub === "test-selection" && <B2BTestSelectionPanel repoUrl={repoUrl} />}
      {sub === "reviewer-routing" && <B2BReviewerRoutingPanel repoUrl={repoUrl} />}
      {sub === "governance" && <B2BGovernancePanel />}
    </div>
  );
}

function B2BTeamPanel({
  repoUrl,
  orgId,
  orgName,
  onOrgSelected,
}: {
  repoUrl: string;
  orgId: number | null;
  orgName: string | null;
  onOrgSelected: (id: number, name: string) => void;
}) {
  const [orgs, setOrgs] = useState<B2BOrg[]>([]);
  const [loadingOrgs, setLoadingOrgs] = useState(false);
  const [newOrgName, setNewOrgName] = useState("");
  const [creatingOrg, setCreatingOrg] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [members, setMembers] = useState<B2BMember[]>([]);
  const [loadingMembers, setLoadingMembers] = useState(false);
  const [memberName, setMemberName] = useState("");
  const [memberEmail, setMemberEmail] = useState("");
  const [memberSkills, setMemberSkills] = useState("");
  const [creatingMember, setCreatingMember] = useState(false);

  const [repoRegistered, setRepoRegistered] = useState(false);
  const [registeringRepo, setRegisteringRepo] = useState(false);

  const loadOrgs = async () => {
    setLoadingOrgs(true);
    setError(null);
    try {
      setOrgs(await apiFetch<B2BOrg[]>("/b2b/orgs"));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoadingOrgs(false);
    }
  };

  useEffect(() => {
    loadOrgs();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const createOrg = async (e: FormEvent) => {
    e.preventDefault();
    if (!newOrgName.trim()) return;
    setCreatingOrg(true);
    setError(null);
    try {
      const r = await apiFetch<B2BOrg>("/b2b/orgs", {
        method: "POST",
        body: JSON.stringify({ name: newOrgName.trim() }),
      });
      setNewOrgName("");
      await loadOrgs();
      onOrgSelected(r.id, r.name);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setCreatingOrg(false);
    }
  };

  const loadMembers = async (id: number) => {
    setLoadingMembers(true);
    try {
      setMembers(await apiFetch<B2BMember[]>(`/b2b/orgs/${id}/members`));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoadingMembers(false);
    }
  };

  useEffect(() => {
    if (orgId !== null) loadMembers(orgId);
  }, [orgId]); // eslint-disable-line react-hooks/exhaustive-deps

  const createMember = async (e: FormEvent) => {
    e.preventDefault();
    if (orgId === null || !memberName.trim() || !memberEmail.trim()) return;
    setCreatingMember(true);
    setError(null);
    try {
      await apiFetch<B2BMember>(`/b2b/orgs/${orgId}/members`, {
        method: "POST",
        body: JSON.stringify({
          name: memberName.trim(),
          email: memberEmail.trim(),
          skill_profile: memberSkills.trim(),
        }),
      });
      setMemberName("");
      setMemberEmail("");
      setMemberSkills("");
      await loadMembers(orgId);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setCreatingMember(false);
    }
  };

  const registerRepo = async () => {
    if (orgId === null) return;
    setRegisteringRepo(true);
    setError(null);
    try {
      await apiFetch(`/b2b/orgs/${orgId}/repos`, {
        method: "POST",
        body: JSON.stringify({ repo_url: repoUrl }),
      });
      setRepoRegistered(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setRegisteringRepo(false);
    }
  };

  return (
    <div className="max-w-3xl space-y-8">
      {error && <ErrorBox message={error} />}

      <div>
        <div className="mono text-xs text-muted-foreground mb-3 tracking-widest">ORGANIZATION</div>
        {orgId === null ? (
          <div className="space-y-4">
            {loadingOrgs ? (
              <Skeleton className="h-10 w-full" />
            ) : orgs.length > 0 ? (
              <div className="grid sm:grid-cols-2 gap-2">
                {orgs.map((o) => (
                  <button
                    key={o.id}
                    onClick={() => onOrgSelected(o.id, o.name)}
                    className="text-left px-4 py-3 rounded-md border border-border bg-card hover:bg-muted transition"
                  >
                    <div className="text-sm font-medium">{o.name}</div>
                    <div className="mono text-xs text-muted-foreground">#{o.id}</div>
                  </button>
                ))}
              </div>
            ) : (
              <div className="text-sm text-muted-foreground">
                No organizations yet — create one below.
              </div>
            )}

            <form onSubmit={createOrg} className="flex gap-2">
              <input
                type="text"
                value={newOrgName}
                onChange={(e) => setNewOrgName(e.target.value)}
                placeholder="New organization name"
                className="flex-1 px-4 py-2.5 rounded-md bg-input border border-border text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring transition"
                disabled={creatingOrg}
              />
              <button
                type="submit"
                disabled={creatingOrg || !newOrgName.trim()}
                className="px-4 py-2.5 rounded-md bg-accent text-accent-foreground text-sm font-medium hover:opacity-90 disabled:opacity-50 transition"
              >
                {creatingOrg ? <Spinner /> : "Create"}
              </button>
            </form>
          </div>
        ) : (
          <div className="text-sm text-muted-foreground">
            Working in <span className="text-foreground font-medium">{orgName}</span>.
          </div>
        )}
      </div>

      {orgId !== null && (
        <>
          <div>
            <div className="mono text-xs text-muted-foreground mb-3 tracking-widest">
              REGISTER THIS REPO
            </div>
            <div className="flex items-center gap-3 flex-wrap">
              <span className="mono text-xs text-muted-foreground truncate">{repoUrl}</span>
              <button
                onClick={registerRepo}
                disabled={registeringRepo}
                className="px-3 py-1.5 rounded-md border border-border bg-card text-xs hover:bg-muted transition mono"
              >
                {registeringRepo
                  ? "Registering…"
                  : repoRegistered
                    ? "Registered ✓"
                    : "Register repo"}
              </button>
            </div>
          </div>

          <div>
            <div className="mono text-xs text-muted-foreground mb-3 tracking-widest">MEMBERS</div>
            {loadingMembers ? (
              <Skeleton className="h-16 w-full mb-4" />
            ) : members.length > 0 ? (
              <div className="border border-border rounded-md overflow-hidden bg-card divide-y divide-border mb-4">
                {members.map((m) => (
                  <div key={m.id} className="p-3 flex items-center justify-between">
                    <div>
                      <div className="text-sm font-medium">{m.name}</div>
                      <div className="mono text-xs text-muted-foreground">
                        {m.email}
                        {m.skill_profile ? ` · ${m.skill_profile}` : ""}
                      </div>
                    </div>
                    <span className="mono text-xs text-muted-foreground">#{m.id}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-sm text-muted-foreground mb-4">No members yet.</div>
            )}

            <form onSubmit={createMember} className="grid sm:grid-cols-3 gap-2">
              <input
                type="text"
                value={memberName}
                onChange={(e) => setMemberName(e.target.value)}
                placeholder="Name"
                className="px-3 py-2 rounded-md bg-input border border-border text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring transition"
                disabled={creatingMember}
              />
              <input
                type="email"
                value={memberEmail}
                onChange={(e) => setMemberEmail(e.target.value)}
                placeholder="Email"
                className="px-3 py-2 rounded-md bg-input border border-border text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring transition"
                disabled={creatingMember}
              />
              <input
                type="text"
                value={memberSkills}
                onChange={(e) => setMemberSkills(e.target.value)}
                placeholder="Skills (e.g. python, react)"
                className="px-3 py-2 rounded-md bg-input border border-border text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring transition"
                disabled={creatingMember}
              />
              <button
                type="submit"
                disabled={creatingMember || !memberName.trim() || !memberEmail.trim()}
                className="sm:col-span-3 px-4 py-2 rounded-md bg-accent text-accent-foreground text-sm font-medium hover:opacity-90 disabled:opacity-50 transition"
              >
                {creatingMember ? <Spinner /> : "Add member"}
              </button>
            </form>
          </div>
        </>
      )}
    </div>
  );
}

function B2BRosterPanel({ orgId }: { orgId: number | null }) {
  const [roster, setRoster] = useState<B2BRosterEntry[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [assigning, setAssigning] = useState<number | null>(null);
  const [assignRepo, setAssignRepo] = useState("");

  const load = async () => {
    if (orgId === null) return;
    setLoading(true);
    setError(null);
    try {
      setRoster(await apiFetch<B2BRosterEntry[]>(`/b2b/orgs/${orgId}/roster`));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [orgId]); // eslint-disable-line react-hooks/exhaustive-deps

  const assign = async (memberId: number) => {
    if (!assignRepo.trim()) return;
    setAssigning(memberId);
    setError(null);
    try {
      await apiFetch(`/b2b/members/${memberId}/assign`, {
        method: "POST",
        body: JSON.stringify({ repo_url: assignRepo.trim() }),
      });
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setAssigning(null);
    }
  };

  if (orgId === null) {
    return (
      <div className="text-sm text-muted-foreground">
        Select or create an organization in Team Setup first.
      </div>
    );
  }

  return (
    <div>
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}

      <div className="flex flex-col sm:flex-row gap-2 mb-6 items-start sm:items-center">
        <input
          type="text"
          value={assignRepo}
          onChange={(e) => setAssignRepo(e.target.value)}
          placeholder="repo_url for issue assignment (e.g. https://github.com/owner/repo)"
          className="flex-1 px-3 py-2 rounded-md bg-input border border-border text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring transition"
        />
        <button
          onClick={load}
          className="px-3 py-2 rounded-md border border-border bg-card text-xs hover:bg-muted transition mono"
        >
          ↻ Refresh
        </button>
      </div>

      {loading && !roster && (
        <div className="space-y-2">
          {[...Array(3)].map((_, i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </div>
      )}

      {roster && roster.length === 0 && (
        <div className="text-sm text-muted-foreground">No members in this organization yet.</div>
      )}

      {roster && roster.length > 0 && (
        <div className="space-y-4">
          {roster.map((entry) => (
            <div key={entry.member.id} className="p-5 rounded-md border border-border bg-card">
              <div className="flex items-start justify-between mb-3 gap-3">
                <div>
                  <div className="text-sm font-semibold">{entry.member.name}</div>
                  <div className="mono text-xs text-muted-foreground">{entry.member.email}</div>
                  {entry.member.skill_profile && (
                    <div className="mono text-xs text-muted-foreground mt-1">
                      {entry.member.skill_profile}
                    </div>
                  )}
                </div>
                <button
                  onClick={() => assign(entry.member.id)}
                  disabled={assigning === entry.member.id || !assignRepo.trim()}
                  className="px-3 py-1.5 rounded-md bg-accent text-accent-foreground text-xs font-medium hover:opacity-90 disabled:opacity-50 transition shrink-0"
                >
                  {assigning === entry.member.id ? <Spinner /> : "Assign issue"}
                </button>
              </div>

              <div className="grid sm:grid-cols-3 gap-3 text-xs">
                <div>
                  <div className="mono text-muted-foreground tracking-widest mb-1">
                    OPEN ASSIGNMENTS
                  </div>
                  <div className="mono text-sm">{entry.open_assignment_count}</div>
                </div>
                <div>
                  <div className="mono text-muted-foreground tracking-widest mb-1">
                    PR READY RATE
                  </div>
                  <div className="mono text-sm">
                    {entry.pr_ready_rate === null
                      ? "—"
                      : `${(entry.pr_ready_rate * 100).toFixed(0)}%`}
                  </div>
                </div>
                <div>
                  <div className="mono text-muted-foreground tracking-widest mb-1">
                    ROADMAP STATUS
                  </div>
                  <div className="mono text-sm">
                    {entry.roadmap_status.length === 0
                      ? "—"
                      : entry.roadmap_status.map((s) => s.status).join(", ")}
                  </div>
                </div>
              </div>

              {entry.assigned_issues.length > 0 && (
                <div className="mt-4 pt-4 border-t border-border space-y-2">
                  {entry.assigned_issues.map((a) => (
                    <div key={a.id} className="text-xs flex items-baseline gap-2">
                      <span className="mono text-accent">
                        {a.issue_number !== null ? `#${a.issue_number}` : "—"}
                      </span>
                      <span>{a.issue_title || "(no match found)"}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function B2BTagPanel({ repoUrl, orgId }: { repoUrl: string; orgId: number | null }) {
  const [tags, setTags] = useState<B2BTaggedIssue[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [issueNumber, setIssueNumber] = useState("");
  const [tag, setTag] = useState("good-first-task");
  const [subsystem, setSubsystem] = useState("");
  const [taggedBy, setTaggedBy] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const load = async () => {
    if (orgId === null) return;
    setLoading(true);
    setError(null);
    try {
      const r = await apiFetch<B2BTaggedIssue[]>(
        `/b2b/orgs/${orgId}/issues/tags?repo_url=${encodeURIComponent(repoUrl)}`,
      );
      setTags(r);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [orgId]); // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (orgId === null || !issueNumber.trim() || !tag.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await apiFetch(`/b2b/orgs/${orgId}/issues/tag`, {
        method: "POST",
        body: JSON.stringify({
          repo_url: repoUrl,
          issue_number: parseInt(issueNumber, 10),
          tag: tag.trim(),
          subsystem: subsystem.trim(),
          tagged_by: taggedBy.trim(),
        }),
      });
      setIssueNumber("");
      setSubsystem("");
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  if (orgId === null) {
    return (
      <div className="text-sm text-muted-foreground">
        Select or create an organization in Team Setup first.
      </div>
    );
  }

  return (
    <div className="max-w-3xl">
      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}

      <form onSubmit={submit} className="grid sm:grid-cols-4 gap-2 mb-6">
        <input
          type="number"
          value={issueNumber}
          onChange={(e) => setIssueNumber(e.target.value)}
          placeholder="Issue #"
          className="px-3 py-2 rounded-md bg-input border border-border text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring transition"
          disabled={submitting}
        />
        <input
          type="text"
          value={tag}
          onChange={(e) => setTag(e.target.value)}
          placeholder="Tag (e.g. good-first-task)"
          className="px-3 py-2 rounded-md bg-input border border-border text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring transition"
          disabled={submitting}
        />
        <input
          type="text"
          value={subsystem}
          onChange={(e) => setSubsystem(e.target.value)}
          placeholder="Subsystem (optional)"
          className="px-3 py-2 rounded-md bg-input border border-border text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring transition"
          disabled={submitting}
        />
        <input
          type="text"
          value={taggedBy}
          onChange={(e) => setTaggedBy(e.target.value)}
          placeholder="Tagged by (optional)"
          className="px-3 py-2 rounded-md bg-input border border-border text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring transition"
          disabled={submitting}
        />
        <button
          type="submit"
          disabled={submitting || !issueNumber.trim() || !tag.trim()}
          className="sm:col-span-4 px-4 py-2 rounded-md bg-accent text-accent-foreground text-sm font-medium hover:opacity-90 disabled:opacity-50 transition"
        >
          {submitting ? <Spinner /> : "Tag issue"}
        </button>
      </form>

      {loading ? (
        <Skeleton className="h-24 w-full" />
      ) : tags.length > 0 ? (
        <div className="border border-border rounded-md overflow-hidden bg-card divide-y divide-border">
          {tags.map((t) => (
            <div key={t.id} className="p-3 flex items-center justify-between text-sm">
              <div className="flex items-baseline gap-2">
                <span className="mono text-accent text-xs">#{t.issue_number}</span>
                <span className="mono text-xs px-2 py-0.5 rounded border border-border bg-muted">
                  {t.tag}
                </span>
                {t.subsystem && (
                  <span className="text-xs text-muted-foreground">{t.subsystem}</span>
                )}
              </div>
              {t.tagged_by && (
                <span className="text-xs text-muted-foreground">by {t.tagged_by}</span>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className="text-sm text-muted-foreground">No tagged issues yet for this repo.</div>
      )}
    </div>
  );
}

function B2BTestSelectionPanel({ repoUrl }: { repoUrl: string }) {
  const [targets, setTargets] = useState("");
  const [maxHops, setMaxHops] = useState(3);
  const [result, setResult] = useState<B2BTestSelectionResp | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (e: FormEvent) => {
    e.preventDefault();
    if (!targets.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const targetList = targets
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);
      const r = await apiFetch<B2BTestSelectionResp>("/b2b/test-selection", {
        method: "POST",
        body: JSON.stringify({ repo_url: repoUrl, targets: targetList, max_hops: maxHops }),
      });
      setResult(r);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-3xl">
      <p className="text-sm text-muted-foreground mb-4">
        Blast radius of the changed files, filtered to test files — "run these first, full suite on
        merge," not a replacement for the full suite.
      </p>

      <form onSubmit={run} className="space-y-3 mb-6">
        <input
          type="text"
          value={targets}
          onChange={(e) => setTargets(e.target.value)}
          placeholder="Changed files, comma-separated (e.g. src/auth.py, src/utils.py)"
          className="mono w-full px-4 py-3 rounded-md bg-input border border-border text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring transition"
          disabled={loading}
        />
        <div>
          <label className="mono text-xs text-muted-foreground">MAX HOPS: {maxHops}</label>
          <input
            type="range"
            min="1"
            max="10"
            value={maxHops}
            onChange={(e) => setMaxHops(parseInt(e.target.value, 10))}
            className="w-full mt-2 accent-accent"
            disabled={loading}
          />
        </div>
        <button
          type="submit"
          disabled={loading || !targets.trim()}
          className="px-5 py-3 rounded-md bg-accent text-accent-foreground text-sm font-medium hover:opacity-90 disabled:opacity-50 transition inline-flex items-center gap-2"
        >
          {loading ? (
            <>
              <Spinner /> Selecting…
            </>
          ) : (
            "Select tests"
          )}
        </button>
      </form>

      {error && <ErrorBox message={error} />}

      {result && !loading && (
        <div className="space-y-4">
          <div className="mono text-sm">{result.ratio}</div>
          <div className="p-3 rounded-md border border-border bg-card text-xs text-muted-foreground">
            {result.disclaimer}
          </div>
          {result.tests.length > 0 ? (
            <div className="border border-border rounded-md overflow-hidden bg-card divide-y divide-border">
              {result.tests.map((t, i) => (
                <div key={i} className="p-3 text-sm">
                  <div className="mono text-xs">{t.path}</div>
                  <div className="text-xs text-muted-foreground mt-1">
                    {t.reason} · hop {t.hops}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-sm text-muted-foreground">
              No tests fall within the blast radius of these files.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function B2BReviewerRoutingPanel({ repoUrl }: { repoUrl: string }) {
  const [targets, setTargets] = useState("");
  const [prAuthor, setPrAuthor] = useState("");
  const [topN, setTopN] = useState(2);
  const [result, setResult] = useState<B2BReviewerResp | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (e: FormEvent) => {
    e.preventDefault();
    if (!targets.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const targetList = targets
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);
      const r = await apiFetch<B2BReviewerResp>("/b2b/reviewer-routing", {
        method: "POST",
        body: JSON.stringify({
          repo_url: repoUrl,
          targets: targetList,
          pr_author: prAuthor.trim() || null,
          top_n: topN,
        }),
      });
      setResult(r);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-3xl">
      <p className="text-sm text-muted-foreground mb-4">
        Who owns the code in the blast radius, by recent commit authorship — no model call, fully
        deterministic.
      </p>

      <form onSubmit={run} className="space-y-3 mb-6">
        <input
          type="text"
          value={targets}
          onChange={(e) => setTargets(e.target.value)}
          placeholder="Changed files, comma-separated"
          className="mono w-full px-4 py-3 rounded-md bg-input border border-border text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring transition"
          disabled={loading}
        />
        <div className="flex gap-2">
          <input
            type="text"
            value={prAuthor}
            onChange={(e) => setPrAuthor(e.target.value)}
            placeholder="PR author to exclude (optional)"
            className="flex-1 px-3 py-2 rounded-md bg-input border border-border text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring transition"
            disabled={loading}
          />
          <input
            type="number"
            min={1}
            value={topN}
            onChange={(e) => setTopN(parseInt(e.target.value, 10) || 1)}
            className="w-24 px-3 py-2 rounded-md bg-input border border-border text-sm focus:outline-none focus:ring-2 focus:ring-ring transition"
            disabled={loading}
          />
        </div>
        <button
          type="submit"
          disabled={loading || !targets.trim()}
          className="px-5 py-3 rounded-md bg-accent text-accent-foreground text-sm font-medium hover:opacity-90 disabled:opacity-50 transition inline-flex items-center gap-2"
        >
          {loading ? (
            <>
              <Spinner /> Routing…
            </>
          ) : (
            "Suggest reviewers"
          )}
        </button>
      </form>

      {error && <ErrorBox message={error} />}

      {result && !loading && (
        <div className="space-y-4">
          <div className="mono text-xs text-muted-foreground">
            Blast radius: {result.blast_radius_size} file{result.blast_radius_size === 1 ? "" : "s"}
          </div>
          {result.reviewers.length > 0 ? (
            <div className="border border-border rounded-md overflow-hidden bg-card divide-y divide-border">
              {result.reviewers.map((r, i) => (
                <div key={i} className="p-4 flex items-center justify-between">
                  <div>
                    <div className="text-sm font-medium">{r.login}</div>
                    <div className="text-xs text-muted-foreground">
                      {r.files_touched} file{r.files_touched === 1 ? "" : "s"} touched
                      {r.last_touched
                        ? ` · last ${new Date(r.last_touched).toLocaleDateString()}`
                        : ""}
                    </div>
                  </div>
                  <span className="mono text-xs text-muted-foreground">
                    score {r.score.toFixed(3)}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-sm text-muted-foreground">
              No reviewers found in commit history for these files.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function B2BGovernancePanel() {
  const [result, setResult] = useState<B2BGovernanceResp | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setResult(await apiFetch<B2BGovernanceResp>("/b2b/governance-report"));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const priorityColor = (p: string) =>
    p === "critical"
      ? "text-red-500 bg-red-500/10 border-red-500/20"
      : p === "high"
        ? "text-orange-500 bg-orange-500/10 border-orange-500/20"
        : p === "medium"
          ? "text-yellow-500 bg-yellow-500/10 border-yellow-500/20"
          : "text-muted-foreground bg-muted border-border";

  return (
    <div className="max-w-5xl">
      <button
        onClick={load}
        disabled={loading}
        className="px-4 py-2 rounded-md border border-border bg-card text-xs hover:bg-muted transition mono mb-6"
      >
        {loading ? "Refreshing…" : "↻ Refresh"}
      </button>

      {error && <ErrorBox message={error} />}

      {result && (
        <div className="space-y-6">
          <div className="p-4 rounded-md border border-border bg-card text-xs text-muted-foreground">
            {result.generation_model_note}
          </div>

          <div className="border border-border rounded-md overflow-hidden bg-card overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border">
                  <th className="px-4 py-3 text-left mono text-[10px] text-muted-foreground tracking-widest font-normal">
                    COMPONENT
                  </th>
                  <th className="px-4 py-3 text-left mono text-[10px] text-muted-foreground tracking-widest font-normal">
                    PRIORITY
                  </th>
                  <th className="px-4 py-3 text-left mono text-[10px] text-muted-foreground tracking-widest font-normal">
                    EVALUATED
                  </th>
                  <th className="px-4 py-3 text-left mono text-[10px] text-muted-foreground tracking-widest font-normal">
                    LAST EVALUATED
                  </th>
                  <th className="px-4 py-3 text-right mono text-[10px] text-muted-foreground tracking-widest font-normal">
                    BASELINE
                  </th>
                  <th className="px-4 py-3 text-right mono text-[10px] text-muted-foreground tracking-widest font-normal">
                    CURRENT
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {result.components.map((c) => (
                  <tr key={c.component} className="hover:bg-muted/30 transition">
                    <td className="px-4 py-3">
                      <div className="mono text-xs font-medium">{c.name}</div>
                      <div className="mono text-[10px] text-muted-foreground">{c.component}</div>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`mono text-[10px] px-2 py-0.5 rounded border ${priorityColor(c.priority)}`}
                      >
                        {c.priority}
                      </span>
                    </td>
                    <td className="px-4 py-3 mono text-xs">{c.evaluated ? "yes" : "no"}</td>
                    <td className="px-4 py-3 mono text-xs text-muted-foreground">
                      {c.last_evaluated ? new Date(c.last_evaluated).toLocaleDateString() : "—"}
                    </td>
                    <td className="px-4 py-3 text-right mono text-xs">
                      {c.baseline_score !== undefined
                        ? `${(c.baseline_score * 100).toFixed(0)}%`
                        : c.mean_f1 !== undefined
                          ? `F1 ${c.mean_f1.toFixed(2)}`
                          : "—"}
                    </td>
                    <td className="px-4 py-3 text-right mono text-xs">
                      {c.current_score !== undefined
                        ? `${(c.current_score * 100).toFixed(0)}%`
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {result.caveats.length > 0 && (
            <div>
              <div className="mono text-xs text-muted-foreground mb-2 tracking-widest">CAVEATS</div>
              <ul className="space-y-1.5">
                {result.caveats.map((c, i) => (
                  <li key={i} className="text-xs text-muted-foreground">
                    · {c}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ---------------- Shared UI ---------------- */

function TopBar() {
  const [rateLimit, setRateLimit] = useState<{
    limit: number;
    remaining: number;
    reset: string;
  } | null>(null);
  const [loading, setLoading] = useState(false);

  const checkRateLimit = async () => {
    setLoading(true);
    try {
      const data = await apiFetch<{ limit: number; remaining: number; reset: string }>(
        "/rate-limit",
      );
      setRateLimit(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <header className="border-b border-border bg-card/50">
      <div className="max-w-6xl mx-auto px-6 h-14 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="flex items-center justify-center w-6 h-6 rounded bg-primary/10">
            <div className="w-2 h-2 rounded-sm bg-accent" />
          </div>
          <span className="mono text-sm font-medium">mentor++</span>
        </div>

        <div className="flex items-center gap-4">
          {rateLimit && (
            <div
              className={`mono text-xs px-2 py-1 rounded border ${rateLimit.remaining > 0 ? "bg-green-500/10 text-green-500 border-green-500/20" : "bg-red-500/10 text-red-500 border-red-500/20"}`}
            >
              {rateLimit.remaining > 0
                ? `API Usable: ${rateLimit.remaining}/${rateLimit.limit}`
                : `Exhausted (Resets at ${new Date(rateLimit.reset).toLocaleTimeString()})`}
            </div>
          )}
          <button
            onClick={checkRateLimit}
            disabled={loading}
            className="mono text-xs text-muted-foreground hover:text-foreground transition flex items-center gap-1"
          >
            {loading ? "Checking..." : "Check Rate Limit"}
          </button>
          <span className="mono text-xs text-muted-foreground ml-2 border-l border-border pl-4">
            v0.1 · local
          </span>
        </div>
      </div>
    </header>
  );
}

function SectionHeader({ title, description }: { title: string; description: string }) {
  return (
    <div className="mb-6">
      <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
      <p className="text-sm text-muted-foreground mt-1">{description}</p>
    </div>
  );
}

function Spinner() {
  return (
    <span
      className="inline-block w-3.5 h-3.5 rounded-full border-2 border-current border-t-transparent animate-spin"
      aria-label="loading"
    />
  );
}

function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`rounded bg-muted animate-pulse ${className}`} />;
}

function ErrorBox({ message }: { message: string }) {
  return (
    <div
      className="p-3 rounded-md text-sm border"
      style={{
        borderColor: "color-mix(in oklab, var(--color-destructive) 40%, transparent)",
        backgroundColor: "color-mix(in oklab, var(--color-destructive) 12%, transparent)",
        color: "var(--color-destructive)",
      }}
    >
      <span className="mono text-[10px] tracking-widest mr-2">ERROR</span>
      {message}
    </div>
  );
}
