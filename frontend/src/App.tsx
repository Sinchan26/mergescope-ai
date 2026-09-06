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
  DatabaseZap,
  GitPullRequest,
  History,
  LayoutDashboard,
  LoaderCircle,
  Menu,
  RefreshCw,
  SearchCode,
  ShieldCheck,
  Sparkles,
  Webhook,
  X,
  XCircle,
} from "lucide-react";
import { api } from "./api";
import { KnowledgeBase } from "./components/KnowledgeBase";
import { ReviewInspector } from "./components/ReviewInspector";
import { StatusBadge, humanize } from "./components/StatusBadge";
import { WorkflowCenter } from "./components/WorkflowCenter";
import type {
  Health,
  KnowledgeDocument,
  PublicationResult,
  PublicConfig,
  ReviewJob,
  ReviewRun,
} from "./types";

type View = "overview" | "knowledge" | "automation";

const formatDate = (value: string) =>
  new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));

function App() {
  const [view, setView] = useState<View>("overview");
  const [health, setHealth] = useState<Health | null>(null);
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [reviews, setReviews] = useState<ReviewRun[]>([]);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [jobs, setJobs] = useState<ReviewJob[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [prUrl, setPrUrl] = useState("");
  const [ticketReference, setTicketReference] = useState("");
  const [forceRereview, setForceRereview] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  const selected = useMemo(
    () => reviews.find((review) => review.id === selectedId) ?? reviews[0] ?? null,
    [reviews, selectedId],
  );
  const completed = reviews.filter((review) => review.status === "completed").length;
  const blocking = reviews.filter((review) => review.result?.approval === "request_changes").length;
  const issueTotal = reviews.reduce((sum, review) => sum + review.issue_count, 0);

  const loadDashboard = async () => {
    setLoading(true);
    try {
      const [nextHealth, nextConfig, nextReviews, nextDocuments, nextJobs] = await Promise.all([
        api.health(), api.config(), api.reviews(), api.documents(), api.jobs(),
      ]);
      setHealth(nextHealth);
      setConfig(nextConfig);
      setReviews(nextReviews.items);
      setDocuments(nextDocuments.items);
      setJobs(nextJobs.items);
      setSelectedId((current) => current ?? nextReviews.items[0]?.id ?? null);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Could not load MergeScope.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void loadDashboard(); }, []);

  useEffect(() => {
    if (view !== "automation") return;
    const interval = window.setInterval(() => {
      void Promise.all([api.health(), api.jobs()]).then(([nextHealth, nextJobs]) => {
        setHealth(nextHealth);
        setJobs(nextJobs.items);
      }).catch(() => undefined);
    }, 5_000);
    return () => window.clearInterval(interval);
  }, [view]);

  const executeReview = async (demoMode: boolean) => {
    setSubmitting(true);
    setError(null);
    setNotice(null);
    try {
      const created = await api.createReview({ prUrl, ticketReference, forceRereview, demoMode });
      setReviews((current) => [created, ...current]);
      setSelectedId(created.id);
      setPrUrl("");
      setTicketReference("");
      setForceRereview(false);
      setNotice(created.cache_hit ? "An unchanged review was loaded from cache." : demoMode ? "Demo review completed without external API calls." : "Grounded agent review completed.");
    } catch (reviewError) {
      setError(reviewError instanceof Error ? reviewError.message : "The review could not run.");
      await loadDashboard();
    } finally {
      setSubmitting(false);
    }
  };

  const submitReview = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void executeReview(false);
  };

  const uploadDocument = async (file: File) => {
    setUploading(true);
    setError(null);
    try {
      const document = await api.uploadDocument(file);
      const nextDocuments = (await api.documents()).items;
      setDocuments(nextDocuments);
      setNotice(`${document.name} is indexed and ready for retrieval.`);
      setHealth((current) => current ? { ...current, knowledge_documents: nextDocuments.length } : current);
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : "Document indexing failed.");
    } finally {
      setUploading(false);
    }
  };

  const deleteDocument = async (document: KnowledgeDocument) => {
    if (!window.confirm(`Delete ${document.name} and all of its indexed chunks?`)) return;
    try {
      await api.deleteDocument(document.id);
      const nextDocuments = documents.filter((item) => item.id !== document.id);
      setDocuments(nextDocuments);
      setHealth((current) => current ? { ...current, knowledge_documents: nextDocuments.length } : current);
      setNotice(`${document.name} was removed from the knowledge base.`);
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "Document deletion failed.");
    }
  };

  const navigate = (nextView: View) => {
    setView(nextView);
    setMobileNavOpen(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const openJobReview = (reviewId: string) => {
    setSelectedId(reviewId);
    navigate("overview");
    requestAnimationFrame(() => document.getElementById("history")?.scrollIntoView());
  };

  const publicationCompleted = (result: PublicationResult) => {
    setReviews((current) => current.map((review) => review.id === result.review_id ? {
      ...review,
      publication_status: result.status,
      github_review_id: result.github_review_id,
      published_at: result.published_at,
    } : review));
    setNotice(result.message);
  };

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <aside className={`sidebar ${mobileNavOpen ? "sidebar-open" : ""}`}>
        <div className="brand">
          <div className="brand-mark" aria-hidden="true"><SearchCode size={22} /></div>
          <div><strong>MergeScope</strong><span>AI review console</span></div>
          <button className="icon-button nav-close" aria-label="Close navigation" onClick={() => setMobileNavOpen(false)}><X size={20} /></button>
        </div>
        <nav aria-label="Primary navigation">
          <button className={`nav-item ${view === "overview" ? "active" : ""}`} onClick={() => navigate("overview")}><LayoutDashboard size={18} />Overview</button>
          <button className="nav-item" onClick={() => { navigate("overview"); requestAnimationFrame(() => document.getElementById("new-review")?.scrollIntoView()); }}><GitPullRequest size={18} />New review</button>
          <button className={`nav-item ${view === "knowledge" ? "active" : ""}`} onClick={() => navigate("knowledge")}><BookOpen size={18} />Knowledge base<span className="nav-count">{documents.length}</span></button>
          <button className={`nav-item ${view === "automation" ? "active" : ""}`} onClick={() => navigate("automation")}><Webhook size={18} />Workflow center<span className="nav-count">{health?.pending_jobs ?? 0}</span></button>
          <button className="nav-item" onClick={() => { navigate("overview"); requestAnimationFrame(() => document.getElementById("history")?.scrollIntoView()); }}><History size={18} />Review history</button>
        </nav>
        <div className="sidebar-section">
          <p>Phase 3</p>
          <div className="phase-progress"><span aria-hidden="true" /><small>3 of 4 · GitHub workflow</small></div>
        </div>
        <div className="sidebar-status">
          <div className="status-line"><span className={`health-dot ${health?.status === "ready" ? "online" : ""}`} /><span>{health?.status === "ready" ? "API operational" : "API unavailable"}</span></div>
          <span>{config?.environment ?? "development"} · {config?.prompt_version ?? "phase2"}</span>
        </div>
      </aside>
      {mobileNavOpen && <button className="nav-backdrop" aria-label="Close navigation" onClick={() => setMobileNavOpen(false)} />}

      <main className="main-content" id="main-content" tabIndex={-1}>
        <header className="topbar">
          <button className="icon-button menu-button" aria-label="Open navigation" onClick={() => setMobileNavOpen(true)}><Menu size={20} /></button>
          <div><p className="eyebrow">{view === "overview" ? "Review workspace" : view === "knowledge" ? "Grounding workspace" : "Automation workspace"}</p><h1>{view === "overview" ? "Pull request overview" : view === "knowledge" ? "Knowledge management" : "GitHub workflow operations"}</h1></div>
          <div className="topbar-actions">
            <div className="model-chip"><Bot size={16} /><span>{config?.openai_model ?? "Loading model"}</span></div>
            <button className="icon-button" onClick={() => void loadDashboard()} aria-label="Refresh dashboard"><RefreshCw size={18} className={loading ? "spin" : ""} /></button>
          </div>
        </header>

        {error && <div className="error-banner" role="alert"><XCircle size={18} /><span>{error}</span><button aria-label="Dismiss error" onClick={() => setError(null)}><X size={17} /></button></div>}
        {notice && <div className="success-banner" role="status"><CheckCircle2 size={18} /><span>{notice}</span><button aria-label="Dismiss message" onClick={() => setNotice(null)}><X size={17} /></button></div>}

        {view === "knowledge" ? (
          <KnowledgeBase documents={documents} config={config} uploading={uploading} onUpload={uploadDocument} onDelete={deleteDocument} />
        ) : view === "automation" ? (
          <WorkflowCenter config={config} health={health} jobs={jobs} loading={loading} onRefresh={() => void loadDashboard()} onOpenReview={openJobReview} />
        ) : (
          <>
            {!config?.openai_configured && !loading && (
              <section className="setup-notice" role="status">
                <AlertTriangle size={20} />
                <div><strong>OpenAI is not configured</strong><p>Add <code>OPENAI_API_KEY</code> for live reviews, or use the deterministic demo below.</p></div>
                <button className="text-button" onClick={() => void executeReview(true)}>Run demo <ArrowRight size={15} /></button>
              </section>
            )}

            <section className="review-launcher panel" id="new-review">
              <div className="section-heading">
                <div><p className="eyebrow">Grounded trigger</p><h2>Analyze a pull request</h2><p>Reviewer agents use exact diff lines, repository rules and relevant indexed context.</p></div>
                <span className="dry-run-badge"><ShieldCheck size={15} /> Dry run enforced</span>
              </div>
              <form onSubmit={submitReview}>
                <label className="field field-wide"><span>GitHub pull request URL</span><div className="input-wrap"><GitPullRequest size={18} /><input type="url" required value={prUrl} onChange={(event) => setPrUrl(event.target.value)} placeholder="https://github.com/owner/repository/pull/123" autoComplete="url" /></div></label>
                <label className="field"><span>Ticket reference <small>Optional</small></span><div className="input-wrap"><CircleDot size={18} /><input type="text" maxLength={100} value={ticketReference} onChange={(event) => setTicketReference(event.target.value)} placeholder="LOCAL-101" /></div></label>
                <button className="primary-button" type="submit" disabled={submitting || !config?.openai_configured}>{submitting ? <LoaderCircle size={18} className="spin" /> : <Sparkles size={18} />}{submitting ? "Agents reviewing…" : "Run agent review"}</button>
              </form>
              <div className="review-options">
                <label className="checkbox-option"><input type="checkbox" checked={forceRereview} onChange={(event) => setForceRereview(event.target.checked)} /><span>Force re-review and ignore cache</span></label>
                {config?.demo_mode_allowed && <button type="button" className="secondary-button" disabled={submitting} onClick={() => void executeReview(true)}><Activity size={16} />Run deterministic demo</button>}
              </div>
              <p className="form-note">No GitHub comments are created. Cache identity uses repository, PR number, head SHA and prompt version.</p>
            </section>

            <section className="metrics-grid" aria-label="Review summary">
              <article className="metric-card"><div className="metric-icon blue"><GitPullRequest size={19} /></div><div><span>Total reviews</span><strong>{reviews.length}</strong><small>Stored locally</small></div></article>
              <article className="metric-card"><div className="metric-icon green"><CheckCircle2 size={19} /></div><div><span>Completed</span><strong>{completed}</strong><small>{reviews.length ? `${Math.round((completed / reviews.length) * 100)}% success rate` : "No runs yet"}</small></div></article>
              <article className="metric-card"><div className="metric-icon amber"><AlertTriangle size={19} /></div><div><span>Validated issues</span><strong>{issueTotal}</strong><small>Changed-line grounded</small></div></article>
              <article className="metric-card"><div className="metric-icon red"><ShieldCheck size={19} /></div><div><span>Blocking reviews</span><strong>{blocking}</strong><small>Request changes</small></div></article>
            </section>

            <section className="workspace-grid" id="history">
              <article className="panel history-panel">
                <div className="section-heading compact"><div><p className="eyebrow">Latest activity</p><h2>Review history</h2></div><span className="record-count">{reviews.length} records</span></div>
                {loading ? <div className="empty-state"><LoaderCircle size={26} className="spin" /><h3>Loading workspace</h3></div> : reviews.length === 0 ? (
                  <div className="empty-state"><div className="empty-icon"><SearchCode size={25} /></div><h3>No reviews yet</h3><p>Run the deterministic demo to explore the complete Phase 2 workflow without credentials.</p><button className="text-button" onClick={() => void executeReview(true)}>Run demo <ArrowRight size={15} /></button></div>
                ) : (
                  <div className="table-wrap"><table><thead><tr><th>Pull request</th><th>Status</th><th>Source</th><th>Verdict</th><th>Issues</th><th>Run at</th><th><span className="sr-only">Open</span></th></tr></thead><tbody>
                    {reviews.map((review) => <tr key={review.id} className={selected?.id === review.id ? "selected-row" : ""}>
                      <td><button className="review-title" onClick={() => setSelectedId(review.id)}><strong>{review.title ?? "Review did not start"}</strong><span>{review.repository ?? "Unknown repository"} {review.pr_number ? `#${review.pr_number}` : ""}</span></button></td>
                      <td><StatusBadge status={review.status} /></td>
                      <td>{review.demo_mode ? <span className="demo-state">Demo</span> : review.trigger_source === "webhook" ? <span className="webhook-state"><Webhook size={12} /> Webhook</span> : review.cache_hit ? <span className="cache-state"><DatabaseZap size={12} /> Cache</span> : <span className="fresh-state">Manual</span>}</td>
                      <td><span className={`verdict verdict-${review.result?.approval ?? "pending"}`}>{review.result ? humanize(review.result.approval) : "—"}</span></td>
                      <td><span className="issue-count">{review.issue_count}</span></td>
                      <td><time dateTime={review.created_at}>{formatDate(review.created_at)}</time></td>
                      <td><button className="row-action" onClick={() => setSelectedId(review.id)} aria-label={`Open review ${review.title ?? review.id}`}><ChevronRight size={18} /></button></td>
                    </tr>)}
                  </tbody></table></div>
                )}
              </article>
              <ReviewInspector selected={selected} onPublished={publicationCompleted} />
            </section>
          </>
        )}
      </main>
    </div>
  );
}

export default App;
