import { ChangeEvent, FormEvent, useState } from "react";
import {
  BookOpenCheck,
  CheckCircle2,
  FileText,
  LoaderCircle,
  Trash2,
  UploadCloud,
} from "lucide-react";
import type { KnowledgeDocument, PublicConfig } from "../types";

const formatDate = (value: string) =>
  new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(
    new Date(value),
  );

const formatBytes = (value: number) =>
  value < 1024 ? `${value} B` : `${(value / 1024).toFixed(1)} KB`;

interface KnowledgeBaseProps {
  documents: KnowledgeDocument[];
  config: PublicConfig | null;
  uploading: boolean;
  onUpload: (file: File) => Promise<void>;
  onDelete: (document: KnowledgeDocument) => Promise<void>;
}

export function KnowledgeBase({
  documents,
  config,
  uploading,
  onUpload,
  onDelete,
}: KnowledgeBaseProps) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedFile) return;
    const form = event.currentTarget;
    await onUpload(selectedFile);
    setSelectedFile(null);
    const input = form.elements.namedItem("knowledge-file") as HTMLInputElement;
    input.value = "";
  };

  const chooseFile = (event: ChangeEvent<HTMLInputElement>) => {
    setSelectedFile(event.target.files?.[0] ?? null);
  };

  return (
    <section className="knowledge-page" aria-labelledby="knowledge-title">
      <div className="page-heading">
        <div>
          <p className="eyebrow">Review grounding</p>
          <h1 id="knowledge-title">Knowledge base</h1>
          <p>
            Index architecture notes and coding standards. Relevant sections are retrieved for each
            pull request.
          </p>
        </div>
        <div className="knowledge-summary">
          <BookOpenCheck size={19} />
          <div>
            <strong>{documents.length}</strong>
            <span>indexed documents</span>
          </div>
        </div>
      </div>

      <div className="knowledge-grid">
        <article className="panel upload-panel">
          <div className="section-heading compact-heading">
            <div>
              <p className="eyebrow">Add context</p>
              <h2>Index a document</h2>
            </div>
          </div>
          <form onSubmit={submit}>
            <label className="file-drop" htmlFor="knowledge-file">
              <UploadCloud size={28} />
              <strong>{selectedFile?.name ?? "Choose a Markdown or text file"}</strong>
              <span>
                {selectedFile
                  ? `${formatBytes(selectedFile.size)} selected`
                  : "UTF-8 · .md, .markdown or .txt · maximum 1 MB"}
              </span>
            </label>
            <input
              className="native-file-input"
              id="knowledge-file"
              name="knowledge-file"
              type="file"
              accept=".md,.markdown,.txt,text/plain,text/markdown"
              onChange={chooseFile}
            />
            <button
              className="primary-button full-button"
              type="submit"
              disabled={!selectedFile || uploading || !config?.openai_configured}
            >
              {uploading ? <LoaderCircle className="spin" size={18} /> : <UploadCloud size={18} />}
              {uploading ? "Creating embeddings…" : "Index document"}
            </button>
          </form>
          {!config?.openai_configured && (
            <p className="inline-warning">
              Add <code>OPENAI_API_KEY</code> before indexing documents.
            </p>
          )}
        </article>

        <article className="panel document-panel">
          <div className="section-heading compact-heading document-heading">
            <div>
              <p className="eyebrow">Available context</p>
              <h2>Indexed documents</h2>
            </div>
            <span className="model-label">{config?.embedding_model ?? "embedding model"}</span>
          </div>
          {documents.length === 0 ? (
            <div className="empty-state document-empty">
              <FileText size={28} />
              <h3>No documents indexed</h3>
              <p>Start with your architecture notes, contribution guide, or coding standards.</p>
            </div>
          ) : (
            <div className="document-list">
              {documents.map((document) => (
                <article className="document-row" key={document.id}>
                  <div className="document-icon"><FileText size={19} /></div>
                  <div className="document-info">
                    <strong>{document.name}</strong>
                    <span>
                      {document.chunk_count} chunks · {formatBytes(document.size_bytes)} · indexed {formatDate(document.created_at)}
                    </span>
                  </div>
                  <span className="indexed-state"><CheckCircle2 size={14} /> Ready</span>
                  <button
                    className="icon-button delete-button"
                    type="button"
                    aria-label={`Delete ${document.name}`}
                    onClick={() => void onDelete(document)}
                  >
                    <Trash2 size={17} />
                  </button>
                </article>
              ))}
            </div>
          )}
        </article>
      </div>

      <article className="panel grounding-note">
        <div><BookOpenCheck size={20} /></div>
        <div>
          <h2>How grounding works</h2>
          <p>
            MergeScope embeds each section, compares it with the PR title and changed code, and sends
            only the most relevant excerpts to the reviewer agents. Uploaded text remains in your
            local SQLite database.
          </p>
        </div>
      </article>
    </section>
  );
}
