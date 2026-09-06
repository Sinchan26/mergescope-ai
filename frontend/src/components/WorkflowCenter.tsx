import {
  CheckCircle2,
  Clock3,
  GitBranch,
  KeyRound,
  LockKeyhole,
  Radio,
  RefreshCw,
  Send,
  Webhook,
  XCircle,
} from "lucide-react";
import type { Health, PublicConfig, ReviewJob } from "../types";
import { humanize } from "./StatusBadge";

const formatDate = (value: string) =>
  new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));

interface WorkflowCenterProps {
  config: PublicConfig | null;
  health: Health | null;
  jobs: ReviewJob[];
  loading: boolean;
  onRefresh: () => void;
  onOpenReview: (reviewId: string) => void;
}

function ReadinessCard({
  ready,
  icon,
  title,
  detail,
}: {
  ready: boolean;
  icon: React.ReactNode;
  title: string;
  detail: string;
}) {
  return (
    <article className={`readiness-card ${ready ? "ready" : "locked"}`}>
      <div className="readiness-icon">{icon}</div>
      <div>
        <span>{ready ? "Ready" : "Setup required"}</span>
        <strong>{title}</strong>
        <p>{detail}</p>
      </div>
      {ready ? <CheckCircle2 size={17} /> : <XCircle size={17} />}
    </article>
  );
}

export function WorkflowCenter({
  config,
  health,
  jobs,
  loading,
  onRefresh,
  onOpenReview,
}: WorkflowCenterProps) {
  return (
    <section className="workflow-page" aria-labelledby="workflow-title">
      <div className="page-heading">
        <div>
          <p className="eyebrow">GitHub automation</p>
          <h1 id="workflow-title">Workflow control center</h1>
          <p>
            Inspect signed webhook ingestion, durable jobs, retries, and the publication safety
            boundary.
          </p>
        </div>
        <button className="secondary-button" type="button" onClick={onRefresh} disabled={loading}>
          <RefreshCw className={loading ? "spin" : ""} size={17} /> Refresh jobs
        </button>
      </div>

      <div className="readiness-grid">
        <ReadinessCard
          ready={Boolean(config?.github_app_configured)}
          icon={<KeyRound size={20} />}
          title="GitHub App authentication"
          detail="RS256 app identity and installation tokens"
        />
        <ReadinessCard
          ready={Boolean(config?.webhook_configured)}
          icon={<Webhook size={20} />}
          title="Signed webhooks"
          detail="SHA-256 delivery verification before parsing"
        />
        <ReadinessCard
          ready={Boolean(config?.worker_enabled)}
          icon={<Radio size={20} />}
          title="Durable review worker"
          detail={`${health?.pending_jobs ?? 0} active or queued jobs`}
        />
        <ReadinessCard
          ready={Boolean(config?.publishing_enabled)}
          icon={config?.publishing_enabled ? <Send size={20} /> : <LockKeyhole size={20} />}
          title="Comment publishing"
          detail={config?.publishing_enabled ? "Preview and confirmation required" : "Server locked by default"}
        />
      </div>

      <article className="panel webhook-panel">
        <div className="webhook-copy">
          <div className="workflow-callout-icon"><Webhook size={20} /></div>
          <div>
            <p className="eyebrow">Webhook endpoint</p>
            <h2><code>/api/webhooks/github</code></h2>
            <p>Subscribe the GitHub App to pull request events and send JSON payloads here.</p>
          </div>
        </div>
        <div className="webhook-tags">
          <span>opened</span><span>reopened</span><span>ready for review</span><span>synchronize</span>
        </div>
      </article>

      <article className="panel jobs-panel">
        <div className="section-heading compact">
          <div><p className="eyebrow">Persistent queue</p><h2>Webhook jobs</h2></div>
          <span className="record-count">{jobs.length} records</span>
        </div>
        {jobs.length === 0 ? (
          <div className="empty-state">
            <GitBranch size={28} />
            <h3>No webhook jobs yet</h3>
            <p>Signed pull-request events will appear here after your GitHub App is connected.</p>
          </div>
        ) : (
          <div className="table-wrap"><table><thead><tr><th>Pull request</th><th>Head</th><th>Status</th><th>Attempts</th><th>Received</th><th>Result</th></tr></thead><tbody>
            {jobs.map((job) => (
              <tr key={job.id}>
                <td><a className="job-link" href={job.pr_url} target="_blank" rel="noreferrer"><strong>{job.repository} #{job.pr_number}</strong><span>{job.delivery_id}</span></a></td>
                <td><code>{job.head_sha.slice(0, 9)}</code></td>
                <td><span className={`job-status job-${job.status}`}>{job.status === "running" && <Clock3 size={12} />}{humanize(job.status)}</span></td>
                <td>{job.attempts} / {job.max_attempts}</td>
                <td><time dateTime={job.created_at}>{formatDate(job.created_at)}</time></td>
                <td>{job.review_id ? <button className="text-button table-action" type="button" onClick={() => onOpenReview(job.review_id!)}>Open review</button> : <span className="muted-copy">—</span>}</td>
              </tr>
            ))}
          </tbody></table></div>
        )}
      </article>
    </section>
  );
}
