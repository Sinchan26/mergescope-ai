import { useRef, useState } from "react";
import {
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  FlaskConical,
  Gauge,
  LoaderCircle,
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
  TerminalSquare,
  X,
  XCircle,
} from "lucide-react";
import type {
  EvaluationDatasetSummary,
  EvaluationRun,
  PublicConfig,
} from "../types";
import { humanize } from "./StatusBadge";

interface EvaluationCenterProps {
  config: PublicConfig | null;
  dataset: EvaluationDatasetSummary | null;
  runs: EvaluationRun[];
  running: boolean;
  onRun: (operatorToken: string) => void;
  onRefresh: () => void;
}

const percent = (value: number) => `${Math.round(value * 100)}%`;
const formatDate = (value: string) =>
  new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));

function ScoreCard({
  label,
  value,
  target,
  lowerIsBetter = false,
}: {
  label: string;
  value: number;
  target: number;
  lowerIsBetter?: boolean;
}) {
  const passing = lowerIsBetter ? value <= target : value >= target;
  return (
    <article className="score-card">
      <div className="score-heading">
        <span>{label}</span>
        <strong>{percent(value)}</strong>
      </div>
      <div
        className="score-track"
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(value * 100)}
      >
        <span className={passing ? "passing" : "attention"} style={{ width: percent(value) }} />
        <i style={{ left: percent(target) }} aria-hidden="true" />
      </div>
      <small className={passing ? "target-met" : "target-missed"}>
        {passing ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}
        Target {lowerIsBetter ? "≤" : "≥"} {percent(target)}
      </small>
    </article>
  );
}

export function EvaluationCenter({
  config,
  dataset,
  runs,
  running,
  onRun,
  onRefresh,
}: EvaluationCenterProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [operatorToken, setOperatorToken] = useState("");
  const latest = runs[0] ?? null;

  const confirmRun = () => {
    dialogRef.current?.close();
    onRun(operatorToken);
    setOperatorToken("");
  };

  return (
    <section className="evaluation-page" aria-labelledby="evaluation-title">
      <div className="page-heading">
        <div>
          <p className="eyebrow">Quality gate</p>
          <h1 id="evaluation-title">Evaluation & operations</h1>
          <p>
            Measure grounded review quality against labeled diffs and verify the controls required
            before expanding repository access.
          </p>
        </div>
        <div className="page-actions">
          <button className="secondary-button" type="button" onClick={onRefresh} disabled={running}>
            <RefreshCw size={17} /> Refresh
          </button>
          <button
            className="primary-button evaluation-run-button"
            type="button"
            disabled={running || !config?.evaluation_enabled || !dataset}
            onClick={() => dialogRef.current?.showModal()}
          >
            {running ? <LoaderCircle className="spin" size={17} /> : <FlaskConical size={17} />}
            {running ? "Evaluation running…" : "Run evaluation"}
          </button>
        </div>
      </div>

      {!config?.evaluation_enabled && (
        <div className="evaluation-setup-note" role="status">
          <LockKeyhole size={17} />
          <span>Set both <code>OPENAI_API_KEY</code> and <code>EVALUATION_RUN_TOKEN</code> to unlock paid evaluation runs.</span>
        </div>
      )}

      {running && (
        <div className="evaluation-running" role="status" aria-live="polite">
          <LoaderCircle className="spin" size={18} />
          <div><strong>Running the labeled suite</strong><span>The API will return after every case has been measured and persisted.</span></div>
        </div>
      )}

      <div className="operations-grid" aria-label="Operational readiness">
        <article className={config?.allowlist_enabled ? "operation-ready" : "operation-warning"}>
          <LockKeyhole size={19} /><div><span>Repository boundary</span><strong>{config?.allowlist_enabled ? `${config.allowed_repository_count} allowlisted` : "Allowlist open"}</strong></div>
        </article>
        <article className={config?.policy_file_configured ? "operation-ready" : "operation-warning"}>
          <ShieldCheck size={19} /><div><span>Review policies</span><strong>{config?.policy_file_configured ? `${config.repository_policy_count} overrides` : "Default policy only"}</strong></div>
        </article>
        <article className={config?.structured_logging ? "operation-ready" : "operation-warning"}>
          <TerminalSquare size={19} /><div><span>Structured logs</span><strong>{config?.structured_logging ? "JSON enabled" : "Plain text"}</strong></div>
        </article>
        <article className={config?.cost_estimation_configured ? "operation-ready" : "operation-warning"}>
          <Gauge size={19} /><div><span>Cost estimation</span><strong>{config?.cost_estimation_configured ? "Rates configured" : "Set model rates"}</strong></div>
        </article>
      </div>

      <div className="evaluation-grid">
        <article className="panel dataset-panel">
          <div className="section-heading compact">
            <div><p className="eyebrow">Versioned benchmark</p><h2>Labeled dataset</h2></div>
            <span className="record-count">{dataset?.version ?? "Unavailable"}</span>
          </div>
          {dataset ? (
            <>
              <div className="dataset-stats">
                <div><strong>{dataset.good_cases}</strong><span>Good diffs</span></div>
                <div><strong>{dataset.bad_cases}</strong><span>Bad diffs</span></div>
                <div><strong>{dataset.adversarial_cases}</strong><span>Adversarial</span></div>
                <div><strong>{dataset.expected_finding_count}</strong><span>Expected findings</span></div>
              </div>
              <div className="case-list">
                {dataset.cases.map((item) => (
                  <article key={item.id}>
                    <span className={`case-type case-${item.case_type}`}>{humanize(item.case_type)}</span>
                    <div><strong>{item.name}</strong><p>{item.description}</p></div>
                    <small>{item.expected_finding_count} expected</small>
                  </article>
                ))}
              </div>
            </>
          ) : (
            <div className="empty-state compact-empty"><XCircle size={25} /><h3>Dataset unavailable</h3><p>Check EVALUATION_DATASET_PATH and restart the API.</p></div>
          )}
        </article>

        <article className="panel results-panel">
          <div className="section-heading compact">
            <div><p className="eyebrow">Latest quality result</p><h2>Measured performance</h2></div>
            {latest && <span className={`evaluation-status evaluation-state-${latest.status}`}>{humanize(latest.status)}</span>}
          </div>
          {latest ? (
            <>
              <div className="score-grid">
                <ScoreCard label="Precision" value={latest.precision} target={0.8} />
                <ScoreCard label="Recall" value={latest.recall} target={0.8} />
                <ScoreCard label="Invalid-line rate" value={latest.invalid_line_rate} target={0.02} lowerIsBetter />
              </div>
              <dl className="evaluation-facts">
                <div><dt>Cases</dt><dd>{latest.completed_cases} / {latest.case_count}</dd></div>
                <div><dt>Latency</dt><dd>{(latest.latency_ms / 1000).toFixed(1)}s</dd></div>
                <div><dt>Tokens</dt><dd>{(latest.input_tokens + latest.output_tokens).toLocaleString()}</dd></div>
                <div><dt>Estimated cost</dt><dd>{config?.cost_estimation_configured ? `$${latest.estimated_cost_usd.toFixed(6)}` : "Rates not set"}</dd></div>
              </dl>
              <div className="evaluation-meta"><span>{latest.model}</span><span>{latest.dataset_version}</span><time dateTime={latest.created_at}>{formatDate(latest.created_at)}</time></div>
              <div className="case-results">
                {latest.results.map((result) => (
                  <details key={result.case_id}>
                    <summary><span className={`case-dot case-${result.case_type}`} /><strong>{result.case_name}</strong><span>{result.error_message ? "Failed" : `${result.true_positives} TP · ${result.false_positives} FP · ${result.false_negatives} FN`}</span></summary>
                    <p>{result.error_message ?? `${result.accepted_findings} accepted, ${result.invalid_findings} rejected for invalid grounding, ${result.latency_ms} ms.`}</p>
                  </details>
                ))}
              </div>
            </>
          ) : (
            <div className="empty-state"><BarChart3 size={28} /><h3>No evaluation runs yet</h3><p>Run the suite when an OpenAI key is configured. Each run is saved in SQLite for comparison.</p></div>
          )}
        </article>
      </div>

      <dialog className="publish-dialog" ref={dialogRef} onCancel={() => dialogRef.current?.close()}>
        <div className="dialog-header"><div><p className="eyebrow">OpenAI usage confirmation</p><h2>Run all {dataset?.case_count ?? 0} cases?</h2></div><button className="icon-button" type="button" aria-label="Close evaluation confirmation" onClick={() => dialogRef.current?.close()}><X size={18} /></button></div>
        <div className="dialog-warning"><FlaskConical size={21} /><p>This invokes the configured reviewer agents for every labeled case and consumes OpenAI tokens. Results and estimated cost are stored locally.</p></div>
        {!config?.cost_estimation_configured && <p className="dialog-inline-note"><AlertTriangle size={15} />Token usage will be measured, but cost remains zero until current per-million-token rates are configured.</p>}
        <label className="dialog-token-field" htmlFor="evaluation-operator-token"><span>Evaluation operator token</span><input id="evaluation-operator-token" type="password" value={operatorToken} onChange={(event) => setOperatorToken(event.target.value)} autoComplete="off" aria-describedby="evaluation-token-help" required /><small id="evaluation-token-help">Enter the EVALUATION_RUN_TOKEN configured on the server. It is not stored.</small></label>
        <div className="dialog-actions"><button className="secondary-button" type="button" onClick={() => dialogRef.current?.close()}>Cancel</button><button className="primary-button danger-confirm" type="button" disabled={!operatorToken} onClick={confirmRun}><FlaskConical size={17} />Confirm evaluation run</button></div>
      </dialog>
    </section>
  );
}
