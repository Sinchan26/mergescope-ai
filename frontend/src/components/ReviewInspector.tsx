import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Bot,
  CheckCircle2,
  Clock3,
  DatabaseZap,
  FileCode2,
  SearchCode,
  ShieldCheck,
} from "lucide-react";
import type { AgentRole, PublicationResult, ReviewRun } from "../types";
import { PublicationPanel } from "./PublicationPanel";
import { StatusBadge, humanize } from "./StatusBadge";

const agentLabels: Record<AgentRole, string> = {
  code_reviewer: "Code",
  security_reviewer: "Security",
  testing_reviewer: "Testing",
  review_synthesizer: "Synthesizer",
};

export function ReviewInspector({
  selected,
  onPublished,
}: {
  selected: ReviewRun | null;
  onPublished: (result: PublicationResult) => void;
}) {
  if (!selected) {
    return (
      <aside className="panel inspector" aria-label="Selected review details">
        <div className="empty-state inspector-empty">
          <SearchCode size={28} />
          <h3>Review inspector</h3>
          <p>Select a review to inspect its agents, sources and line-grounded findings.</p>
        </div>
      </aside>
    );
  }

  return (
    <aside className="panel inspector" aria-label="Selected review details">
      <div className="inspector-header">
        <div className="inspector-kicker"><FileCode2 size={16} /> Selected review</div>
        <a href={selected.pr_url} target="_blank" rel="noreferrer" aria-label="Open pull request on GitHub"><ArrowRight size={17} /></a>
      </div>
      <h2>{selected.title ?? "Review failed before PR metadata loaded"}</h2>
      <p className="repo-line">{selected.repository ?? "Unknown repository"}{selected.pr_number ? ` · PR #${selected.pr_number}` : ""}</p>
      <div className="inspector-meta">
        <StatusBadge status={selected.status} />
        {selected.result && <span className={`verdict verdict-${selected.result.approval}`}>{humanize(selected.result.approval)}</span>}
        {selected.cache_hit && <span className="cache-state"><DatabaseZap size={13} /> Cached</span>}
        {selected.demo_mode && <span className="demo-state">Demo</span>}
      </div>

      {selected.error_message ? (
        <div className="review-error"><AlertTriangle size={18} /><p>{selected.error_message}</p></div>
      ) : selected.result ? (
        <>
          <p className="review-summary">{selected.result.summary}</p>
          <div className="review-facts">
            <div><Clock3 size={15} /><span>Latency</span><strong>{selected.latency_ms ? `${(selected.latency_ms / 1000).toFixed(1)}s` : selected.cache_hit ? "cached" : "—"}</strong></div>
            <div><Activity size={15} /><span>Confidence</span><strong>{Math.round(selected.result.confidence * 100)}%</strong></div>
            <div><FileCode2 size={15} /><span>Files</span><strong>{selected.result.reviewed_files.length}</strong></div>
          </div>

          <PublicationPanel review={selected} onPublished={onPublished} />

          <div className="detail-block">
            <div className="issue-list-heading"><h3>Agents executed</h3><span>{selected.result.agents_run.length}</span></div>
            <div className="agent-list">
              {selected.result.agents_run.map((agent) => (
                <span key={agent}><Bot size={13} /> {agentLabels[agent]}</span>
              ))}
            </div>
          </div>

          <div className="detail-block">
            <div className="issue-list-heading"><h3>Context sources</h3><span>{selected.result.context_sources.length}</span></div>
            {selected.result.context_sources.length ? (
              <div className="source-list">
                {selected.result.context_sources.map((source) => (
                  <details key={source.source_id}>
                    <summary>
                      <span>{source.name}</span>
                      <small>{source.relevance_score ? `${Math.round(source.relevance_score * 100)}%` : source.source_type}</small>
                    </summary>
                    <p>{source.excerpt}</p>
                  </details>
                ))}
              </div>
            ) : <p className="muted-copy">No repository or uploaded context was used.</p>}
          </div>

          <div className="issue-list-heading">
            <h3>Validated findings</h3>
            <span>{selected.result.issues.length}</span>
          </div>
          {selected.result.rejected_issue_count > 0 && (
            <p className="validation-note"><ShieldCheck size={14} /> {selected.result.rejected_issue_count} invalid or duplicate finding{selected.result.rejected_issue_count === 1 ? "" : "s"} removed</p>
          )}
          <div className="issue-list">
            {selected.result.issues.length === 0 ? (
              <div className="clean-review"><CheckCircle2 size={20} /><p>No actionable findings in the supplied diff.</p></div>
            ) : selected.result.issues.map((issue, index) => (
              <article className="issue-card" key={`${issue.file_path}-${issue.line_number}-${index}`}>
                <div className="issue-topline">
                  <span className={`severity severity-${issue.severity}`}>{issue.severity}</span>
                  <span>{agentLabels[issue.agent]} · {humanize(issue.category)}</span>
                </div>
                <h4>{issue.title}</h4>
                <div className="line-reference">
                  <code>{issue.file_path}{issue.line_number ? `:${issue.line_number}` : ""}</code>
                  {issue.line_validated && <span><ShieldCheck size={12} /> line verified</span>}
                </div>
                <p>{issue.message}</p>
                {issue.diff_excerpt && <pre className="diff-excerpt">{issue.diff_excerpt}</pre>}
                <details><summary>Evidence and suggested action</summary><p>{issue.evidence}</p><p>{issue.suggestion}</p></details>
              </article>
            ))}
          </div>
        </>
      ) : (
        <div className="empty-state compact-empty"><h3>Awaiting result</h3></div>
      )}
    </aside>
  );
}
