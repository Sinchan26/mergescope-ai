import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ExternalLink,
  LoaderCircle,
  LockKeyhole,
  MessageSquareText,
  Send,
  ShieldCheck,
  X,
} from "lucide-react";
import { api } from "../api";
import type { PublicationResult, PublicationPreview, ReviewRun } from "../types";
import { humanize } from "./StatusBadge";

interface PublicationPanelProps {
  review: ReviewRun;
  onPublished: (result: PublicationResult) => void;
}

export function PublicationPanel({ review, onPublished }: PublicationPanelProps) {
  const [preview, setPreview] = useState<PublicationPreview | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(true);
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    void api.publicationPreview(review.id)
      .then((value) => { if (active) setPreview(value); })
      .catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : "Preview unavailable."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [review.id, review.publication_status]);

  const openConfirmation = () => dialogRef.current?.showModal();
  const closeConfirmation = () => dialogRef.current?.close();

  const publish = async () => {
    setPublishing(true);
    setError(null);
    try {
      const result = await api.publishReview(review.id);
      onPublished(result);
      closeConfirmation();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "GitHub publication failed.");
      closeConfirmation();
    } finally {
      setPublishing(false);
    }
  };

  return (
    <div className="detail-block publication-panel">
      <div className="issue-list-heading">
        <h3>GitHub publication</h3>
        <span className={`publication-chip publication-${review.publication_status}`}>
          {humanize(review.publication_status)}
        </span>
      </div>

      {loading ? (
        <p className="muted-copy publication-loading"><LoaderCircle className="spin" size={14} /> Preparing preview…</p>
      ) : error ? (
        <p className="publication-error"><AlertTriangle size={14} /> {error}</p>
      ) : preview ? (
        <>
          {preview.already_published ? (
            <div className="published-state"><CheckCircle2 size={17} /><span>Published as GitHub review #{review.github_review_id}</span></div>
          ) : (
            <>
              <button className="preview-toggle" type="button" onClick={() => setExpanded((value) => !value)} aria-expanded={expanded}>
                <span><MessageSquareText size={16} /> Preview {preview.comments.length} inline comment{preview.comments.length === 1 ? "" : "s"}</span>
                <ChevronDown className={expanded ? "rotate" : ""} size={16} />
              </button>
              {expanded && (
                <div className="comment-preview">
                  <pre>{preview.body}</pre>
                  {preview.comments.map((comment) => (
                    <article key={`${comment.path}-${comment.line}`}>
                      <strong>{comment.path}:{comment.line}</strong>
                      <p>{comment.body}</p>
                    </article>
                  ))}
                </div>
              )}
              {preview.blocking_reasons.length > 0 && (
                <div className="publish-blockers"><LockKeyhole size={15} /><ul>{preview.blocking_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></div>
              )}
              <button className="publish-button" type="button" disabled={!preview.can_publish} onClick={openConfirmation}>
                <Send size={16} /> Publish reviewed comments <ExternalLink size={14} />
              </button>
            </>
          )}
        </>
      ) : null}

      <dialog className="publish-dialog" ref={dialogRef} onCancel={closeConfirmation}>
        <div className="dialog-header"><div><p className="eyebrow">External write confirmation</p><h2>Publish to GitHub?</h2></div><button className="icon-button" type="button" aria-label="Close confirmation" onClick={closeConfirmation}><X size={18} /></button></div>
        <div className="dialog-warning"><ShieldCheck size={21} /><p>This creates one GitHub review on commit <code>{preview?.commit_sha?.slice(0, 12)}</code> with {preview?.comments.length ?? 0} inline comments. MergeScope will recheck the PR head first.</p></div>
        <p className="muted-copy">This review will be posted as your signed-in GitHub account. Your session authorizes it—no publication token is needed.</p>
        <div className="dialog-actions"><button className="secondary-button" type="button" onClick={closeConfirmation}>Cancel</button><button className="primary-button danger-confirm" type="button" disabled={publishing} onClick={() => void publish()}>{publishing ? <LoaderCircle className="spin" size={17} /> : <Send size={17} />}{publishing ? "Publishing…" : "Confirm publication"}</button></div>
      </dialog>
    </div>
  );
}
