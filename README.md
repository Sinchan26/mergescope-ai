# MergeScope AI

MergeScope AI is a Docker-free, grounded pull-request review workspace. It fetches a GitHub PR,
runs specialized reviewers through a LangGraph workflow, validates every finding against the exact
added lines, stores the result in SQLite, and presents the evidence in a React dashboard.

Reviews remain in **dry-run mode**: the application never writes comments to GitHub.

## Phase 2 capabilities

- Code and testing reviewers, with a security reviewer routed only for sensitive changes
- OpenAI Responses API with strict Pydantic structured outputs
- Deterministic synthesis guardrail: invalid paths, missing lines, non-added lines, and duplicates
  are rejected before the verdict is calculated
- Repository guidance from `AGENTS.md`, `CONTRIBUTING.md`, and the pull-request template
- Local Markdown/text knowledge base using OpenAI embeddings and SQLite retrieval
- Review cache keyed by repository, PR number, head SHA, and prompt version
- Deterministic demo mode requiring neither GitHub nor OpenAI credentials
- Dashboard views for review agents, context sources, cache state, and validated diff excerpts
- No Docker, Redis, vector database, or Jira dependency

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Node.js 20+
- An OpenAI API key for live reviews and document indexing
- Optional: a GitHub token for private repositories or higher rate limits

## Local setup

```bash
git clone https://github.com/Sinchan26/mergescope-ai.git
cd mergescope-ai
git switch dev
cp .env.example .env
uv sync --dev
cd frontend
npm install
```

On PowerShell, use `Copy-Item .env.example .env` instead of `cp`. Set `OPENAI_API_KEY` in `.env`
for live reviews. Then run these commands in separate terminals:

```bash
uv run uvicorn mergescope.main:app --app-dir backend/src --reload --port 8000
```

```bash
cd frontend
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). Vite proxies `/api` to FastAPI.

## Test without Jira or API keys

Jira is not required. Leave **Ticket reference** blank or use a local label such as `LOCAL-101`.

To test without any credentials, click **Run deterministic demo**. It exercises the same diff
validator, storage, history, and dashboard result views using a fixed synthetic PR. For a live run,
set `OPENAI_API_KEY`, submit a public PR URL, and optionally set `GITHUB_TOKEN`.

Use **Knowledge base** to index `.md`, `.markdown`, or `.txt` guidance files up to 1 MB. Indexing
uses `text-embedding-3-small`; the text and vectors remain in the local SQLite database.

## Validation

```bash
uv run ruff format --check backend
uv run ruff check backend
uv run pytest
cd frontend
npm run build
npm audit --audit-level=high
```

## Single-server production build

```bash
cd frontend
npm run build
cd ..
uv run uvicorn mergescope.main:app --app-dir backend/src --host 0.0.0.0 --port 8000
```

FastAPI detects `frontend/dist` and serves the dashboard at
[http://localhost:8000](http://localhost:8000).

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Service, integration, and document readiness |
| `GET` | `/api/config` | Safe client configuration |
| `GET` | `/api/reviews` | Recent review runs |
| `GET` | `/api/reviews/{review_id}` | Complete grounded review result |
| `POST` | `/api/reviews/manual` | Run a live or deterministic demo review |
| `GET` | `/api/knowledge/documents` | List indexed guidance documents |
| `POST` | `/api/knowledge/documents` | Index a Markdown or text document |
| `DELETE` | `/api/knowledge/documents/{document_id}` | Delete a document and its chunks |

Interactive API documentation is available at `/docs`.

## Safety boundaries

- PRs and uploaded guidance are treated as untrusted data; embedded instructions are ignored.
- Findings without a valid added-line anchor are excluded from the result.
- The deterministic validator, not the model synthesizer, calculates the final verdict.
- Secrets are loaded only from environment variables and are never returned by the API.
- GitHub write operations do not exist in Phase 2.
- Diffs are truncated deterministically before model submission.
