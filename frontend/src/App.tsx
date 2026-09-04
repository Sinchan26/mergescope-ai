import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BookOpen,
  Bot,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  Clock3,
  Code2,
  FileCode2,
  GitPullRequest,
  History,
  LayoutDashboard,
  LoaderCircle,
  Menu,
  RefreshCw,
  SearchCode,
  Settings2,
  ShieldCheck,
  Sparkles,
  X,
  XCircle,
} from "lucide-react";
import { api } from "./api";
import type { Health, PublicConfig, ReviewRun, ReviewStatus } from "./types";

const formatDate = (value: string) =>
  new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));

const humanize = (value: string) => value.replaceAll("_", " ");

function StatusBadge({ status }: { status: ReviewStatus }) {
  const icon =
    status === "completed" ? (
      <CheckCircle2 size={14} />
    ) : status === "failed" ? (
      <XCircle size={14} />
    ) : (
      <LoaderCircle size={14} className={status === "running" ? "spin" : ""} />
    );
  return (
    <span className={`status-badge status-${status}`}>
      {icon}
      {humanize(status)}
    </span>
  );
}

function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [reviews, setReviews] = useState<ReviewRun[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [prUrl, setPrUrl] = useState("");
  const [ticketReference, setTicketReference] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  const selected = useMemo(
    () => reviews.find((review) => review.id === selectedId) ?? reviews[0] ?? null,
    [reviews, selectedId],
  );

  const completed = reviews.filter((review) => review.status === "completed").length;
  const blocking = reviews.filter(
    (review) => review.result?.approval === "request_changes",
  ).length;
  const issueTotal = reviews.reduce((sum, review) => sum + review.issue_count, 0);

  const loadDashboard = async () => {
    setLoading(true);
    try {
      const [nextHealth, nextConfig, nextReviews] = await Promise.all([
        api.health(),
        api.config(),
        api.reviews(),
      ]);
      setHealth(nextHealth);
      setConfig(nextConfig);
      setReviews(nextReviews.items);
      setSelectedId((current) => current ?? nextReviews.items[0]?.id ?? null);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Could not load MergeScope.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadDashboard();
  }, []);

  const submitReview = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const created = await api.createReview(prUrl, ticketReference);
      setReviews((current) => [created, ...current]);
      setSelectedId(created.id);
      setPrUrl("");
      setTicketReference("");
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "The review could not run.");
      await loadDashboard();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileNavOpen ? "sidebar-open" : ""}`}>
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">
            <SearchCode size={22} />
          </div>
          <div>
            <strong>MergeScope</strong>
            <span>AI review console</span>
          </div>
          <button
            className="icon-button nav-close"
            aria-label="Close navigation"
            onClick={() => setMobileNavOpen(false)}
          >
            <X size={20} />
          </button>
        </div>

        <nav aria-label="Primary navigation">
          <a className="nav-item active" href="#overview" onClick={() => setMobileNavOpen(false)}>
            <LayoutDashboard size={18} />
            Overview
          </a>
          <a className="nav-item" href="#new-review" onClick={() => setMobileNavOpen(false)}>
            <GitPullRequest size={18} />
            New review
          </a>
          <a className="nav-item" href="#history" onClick={() => setMobileNavOpen(false)}>
            <History size={18} />
            Review history
          </a>
        </nav>

        <div className="sidebar-section">
          <p>Workspace</p>
          <a className="nav-item" href="/docs">
            <BookOpen size={18} />
            API docs
          </a>
          <button className="nav-item disabled" type="button" disabled>
            <Settings2 size={18} />
            Settings
            <span className="soon-label">Soon</span>
          </button>
        </div>

        <div className="sidebar-status">
          <div className="status-line">
            <span className={`health-dot ${health?.status === "ready" ? "online" : ""}`} />
            <span>{health?.status === "ready" ? "API operational" : "API unavailable"}</span>
          </div>
          <span>{config?.environment ?? "development"} environment</span>
        </div>
      </aside>

      {mobileNavOpen && (
        <button
          className="nav-backdrop"
          aria-label="Close navigation"
          onClick={() => setMobileNavOpen(false)}
        />
      )}

      <main className="main-content" id="overview">
        <header className="topbar">
          <button
            className="icon-button menu-button"
            aria-label="Open navigation"
            onClick={() => setMobileNavOpen(true)}
          >
            <Menu size={20} />
          </button>
          <div>
            <p className="eyebrow">Review workspace</p>
            <h1>Pull request overview</h1>
          </div>
          <div className="topbar-actions">
            <div className="model-chip">
              <Bot size={16} />
              <span>{config?.openai_model ?? "Loading model"}</span>
            </div>
            <button className="icon-button" onClick={() => void loadDashboard()} aria-label="Refresh dashboard">
              <RefreshCw size={18} className={loading ? "spin" : ""} />
            </button>
          </div>
        </header>

        {!config?.openai_configured && !loading && (
          <section className="setup-notice" role="status">
            <AlertTriangle size={20} />
            <div>
              <strong>OpenAI is not configured</strong>
              <p>Add <code>OPENAI_API_KEY</code> to your <code>.env</code> file before running a review.</p>
            </div>
            <a href="/docs">Open API docs <ArrowRight size={15} /></a>
          </section>
        )}

        {error && (
          <div className="error-banner" role="alert">
            <XCircle size={18} />
            <span>{error}</span>
            <button aria-label="Dismiss error" onClick={() => setError(null)}><X size={17} /></button>
          </div>
        )}

        <section className="review-launcher panel" id="new-review">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Manual trigger</p>
              <h2>Analyze a pull request</h2>
              <p>Paste a GitHub PR URL. Ticket context is optional—Jira is not required.</p>
            </div>
            <span className="dry-run-badge"><ShieldCheck size={15} /> Dry run enforced</span>
          </div>
          <form onSubmit={submitReview}>
            <label className="field field-wide">
              <span>GitHub pull request URL</span>
              <div className="input-wrap">
                <GitPullRequest size={18} />
                <input
                  type="url"
                  required
                  value={prUrl}
                  onChange={(event) => setPrUrl(event.target.value)}
                  placeholder="https://github.com/owner/repository/pull/123"
                  autoComplete="url"
                />
              </div>
            </label>
            <label className="field">
              <span>Ticket reference <small>Optional</small></span>
              <div className="input-wrap">
                <CircleDot size={18} />
                <input
                  type="text"
                  maxLength={100}
                  value={ticketReference}
                  onChange={(event) => setTicketReference(event.target.value)}
                  placeholder="LOCAL-101"
                />
              </div>
            </label>
            <button className="primary-button" type="submit" disabled={submitting || !config?.openai_configured}>
              {submitting ? <LoaderCircle size={18} className="spin" /> : <Sparkles size={18} />}
              {submitting ? "Reviewing changes…" : "Run AI review"}
            </button>
          </form>
          <p className="form-note">No GitHub comments will be created. Results stay in your local SQLite database.</p>
        </section>

        <section className="metrics-grid" aria-label="Review summary">
          <article className="metric-card">
            <div className="metric-icon blue"><GitPullRequest size={19} /></div>
            <div><span>Total reviews</span><strong>{reviews.length}</strong><small>Stored locally</small></div>
          </article>
          <article className="metric-card">
            <div className="metric-icon green"><CheckCircle2 size={19} /></div>
            <div><span>Completed</span><strong>{completed}</strong><small>{reviews.length ? `${Math.round((completed / reviews.length) * 100)}% success rate` : "No runs yet"}</small></div>
          </article>
          <article className="metric-card">
            <div className="metric-icon amber"><AlertTriangle size={19} /></div>
            <div><span>Issues found</span><strong>{issueTotal}</strong><small>Across all reviews</small></div>
          </article>
          <article className="metric-card">
            <div className="metric-icon red"><ShieldCheck size={19} /></div>
            <div><span>Blocking reviews</span><strong>{blocking}</strong><small>Request changes</small></div>
          </article>
        </section>

        <section className="workspace-grid" id="history">
          <article className="panel history-panel">
            <div className="section-heading compact">
              <div><p className="eyebrow">Latest activity</p><h2>Review history</h2></div>
              <span className="record-count">{reviews.length} records</span>
            </div>
            {loading ? (
              <div className="empty-state"><LoaderCircle size={26} className="spin" /><h3>Loading workspace</h3></div>
            ) : reviews.length === 0 ? (
              <div className="empty-state">
                <div className="empty-icon"><Code2 size={25} /></div>
                <h3>No reviews yet</h3>
                <p>Your first dry-run analysis will appear here with its verdict and issue count.</p>
                <a href="#new-review">Start a review <ArrowRight size={15} /></a>
              </div>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Pull request</th><th>Status</th><th>Verdict</th><th>Issues</th><th>Run at</th><th><span className="sr-only">Open</span></th></tr></thead>
                  <tbody>
                    {reviews.map((review) => (
                      <tr key={review.id} className={selected?.id === review.id ? "selected-row" : ""}>
                        <td>
                          <button className="review-title" onClick={() => setSelectedId(review.id)}>
                            <strong>{review.title ?? "Review did not start"}</strong>
                            <span>{review.repository ?? new URL(review.pr_url).pathname.split("/").slice(1, 3).join("/")} {review.pr_number ? `#${review.pr_number}` : ""}</span>
                          </button>
                        </td>
                        <td><StatusBadge status={review.status} /></td>
                        <td><span className={`verdict verdict-${review.result?.approval ?? "pending"}`}>{review.result ? humanize(review.result.approval) : "—"}</span></td>
                        <td><span className="issue-count">{review.issue_count}</span></td>
                        <td><time dateTime={review.created_at}>{formatDate(review.created_at)}</time></td>
                        <td><button className="row-action" onClick={() => setSelectedId(review.id)} aria-label={`Open review ${review.title ?? review.id}`}><ChevronRight size={18} /></button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </article>

          <aside className="panel inspector" aria-label="Selected review details">
            {selected ? (
              <>
                <div className="inspector-header">
                  <div className="inspector-kicker"><FileCode2 size={16} /> Selected review</div>
                  <a href={selected.pr_url} target="_blank" rel="noreferrer" aria-label="Open pull request on GitHub"><ArrowRight size={17} /></a>
                </div>
                <h2>{selected.title ?? "Review failed before PR metadata loaded"}</h2>
                <p className="repo-line">{selected.repository ?? "Unknown repository"}{selected.pr_number ? ` · PR #${selected.pr_number}` : ""}</p>
                <div className="inspector-meta">
                  <StatusBadge status={selected.status} />
                  {selected.result && <span className={`verdict verdict-${selected.result.approval}`}>{humanize(selected.result.approval)}</span>}
                </div>

                {selected.error_message ? (
                  <div className="review-error"><AlertTriangle size={18} /><p>{selected.error_message}</p></div>
                ) : selected.result ? (
                  <>
                    <p className="review-summary">{selected.result.summary}</p>
                    <div className="review-facts">
                      <div><Clock3 size={15} /><span>Latency</span><strong>{selected.latency_ms ? `${(selected.latency_ms / 1000).toFixed(1)}s` : "—"}</strong></div>
                      <div><Activity size={15} /><span>Confidence</span><strong>{Math.round(selected.result.confidence * 100)}%</strong></div>
                      <div><FileCode2 size={15} /><span>Files</span><strong>{selected.result.reviewed_files.length}</strong></div>
                    </div>
                    <div className="issue-list-heading"><h3>Findings</h3><span>{selected.result.issues.length}</span></div>
                    <div className="issue-list">
                      {selected.result.issues.length === 0 ? (
                        <div className="clean-review"><CheckCircle2 size={20} /><p>No actionable findings in the supplied diff.</p></div>
                      ) : selected.result.issues.map((issue, index) => (
                        <article className="issue-card" key={`${issue.file_path}-${issue.line_number}-${index}`}>
                          <div className="issue-topline"><span className={`severity severity-${issue.severity}`}>{issue.severity}</span><span>{humanize(issue.category)}</span></div>
                          <h4>{issue.title}</h4>
                          <code>{issue.file_path}{issue.line_number ? `:${issue.line_number}` : ""}</code>
                          <p>{issue.message}</p>
                          <details><summary>Suggested action</summary><p>{issue.suggestion}</p></details>
                        </article>
                      ))}
                    </div>
                  </>
                ) : (
                  <div className="empty-state compact-empty"><LoaderCircle size={23} className={selected.status === "running" ? "spin" : ""} /><h3>{selected.status === "failed" ? "Review failed" : "Awaiting result"}</h3></div>
                )}
              </>
            ) : (
              <div className="empty-state inspector-empty"><SearchCode size={28} /><h3>Review inspector</h3><p>Select a review to inspect its summary and findings.</p></div>
            )}
          </aside>
        </section>
      </main>
    </div>
  );
}

export default App;
