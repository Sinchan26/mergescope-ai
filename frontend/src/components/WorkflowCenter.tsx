import { CheckCircle2, GitPullRequest, KeyRound, LockKeyhole, RefreshCw, Send } from "lucide-react";
import type { Health, PublicConfig, ReviewJob } from "../types";

interface WorkflowCenterProps {
  config: PublicConfig | null;
  health: Health | null;
  jobs: ReviewJob[];
  loading: boolean;
  onRefresh: () => void;
  onOpenReview: (reviewId: string) => void;
}

export function WorkflowCenter({ config, loading, onRefresh }: WorkflowCenterProps) {
  return <section className="workflow-page" aria-labelledby="workflow-title">
    <div className="page-heading"><div><p className="eyebrow">Signed-in GitHub workflow</p><h2 id="workflow-title">Manual reviews, explicit publication</h2><p>You choose the pull request. Your agents review it. You decide when to post.</p></div><button className="secondary-button" type="button" onClick={onRefresh} disabled={loading}><RefreshCw className={loading ? "spin" : ""} size={17} aria-hidden="true" /> Refresh status</button></div>
    <div className="readiness-grid">
      <article className="readiness-card ready"><div className="readiness-icon"><KeyRound size={20} aria-hidden="true" /></div><div><span>Signed in</span><strong>GitHub user authentication</strong><p>Session-based access. No shared PAT or publish token.</p></div><CheckCircle2 size={17} aria-hidden="true" /></article>
      <article className="readiness-card ready"><div className="readiness-icon"><GitPullRequest size={20} aria-hidden="true" /></div><div><span>Always enforced</span><strong>Repository access boundary</strong><p>Your account permissions intersected with App installations and server restrictions.</p></div><CheckCircle2 size={17} aria-hidden="true" /></article>
      <article className={`readiness-card ${config?.publishing_enabled ? "ready" : "locked"}`}><div className="readiness-icon"><Send size={20} aria-hidden="true" /></div><div><span>{config?.publishing_enabled ? "Enabled" : "Disabled"}</span><strong>Comment publishing</strong><p>Requires a completed review, repository policy permission, a current PR head, and your confirmation.</p></div></article>
      <article className="readiness-card"><div className="readiness-icon"><LockKeyhole size={20} aria-hidden="true" /></div><div><span>Intentionally inactive</span><strong>Webhooks and background worker</strong><p>Not needed for this flow. Pasting a PR link is the only live review trigger.</p></div></article>
    </div>
    <article className="panel webhook-panel"><div className="webhook-copy"><div><p className="eyebrow">Before your first publication</p><h3>Connect a test repository</h3><p>Install the App on selected repositories, enable publishing on the server and in the repository policy, then run a small PR review from Overview. Expand its comment preview and confirm to post as your GitHub account.</p><p className="muted-copy">Setup guide: <code>docs/github-login.md</code>. No webhook URL, tunnel, Jira account, or Docker service is required.</p></div></div></article>
  </section>;
}
