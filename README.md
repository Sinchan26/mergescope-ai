# MergeScope AI

MergeScope AI is a Docker-free pull-request review workspace. It retrieves GitHub changes and local
guidance, runs specialized OpenAI reviewers through LangGraph, validates every finding against the
exact added lines, and stores durable review workflows in SQLite.

Phase 4 adds measurable quality and operational boundaries. A versioned labeled suite tracks
precision, recall, invalid-line rate, latency, token use, and configured cost estimates. Repository
allowlists, per-repository policies, structured logs, and verified SQLite backups prepare the local
service for controlled use.

## Capabilities

- Code and testing reviewers with conditional security review and synthesis
- OpenAI Responses structured outputs and `text-embedding-3-small` knowledge retrieval
- Deterministic validation of changed paths, added lines, duplicates, and final verdicts
- Repository guidance from `AGENTS.md`, `CONTRIBUTING.md`, and PR templates
- SQLite review cache, local knowledge vectors, webhook deliveries, and durable jobs
- GitHub App RS256 authentication with cached installation tokens
- HMAC-SHA256 webhook verification before payload parsing
- Delivery-ID and PR-head idempotency, retry backoff, worker leases, and stale-head supersession
- Comment preview with a second head-SHA check and explicit publish confirmation
- Six labeled good, bad, and adversarial evaluation cases with persisted case-level metrics
- Repository allowlists and policy-controlled agent routing, confidence, blocking, and publishing
- Correlation IDs across HTTP requests and durable webhook jobs with structured JSON logs
- Online SQLite backup CLI with integrity checking, SHA-256 manifests, and retention
- Deterministic demo mode requiring no GitHub, Jira, or OpenAI credentials
- No Docker, Redis, external queue, vector database, or Jira dependency

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Node.js 20+
- An OpenAI API key for live reviews and document indexing
- Optional GitHub App for webhooks, private repositories, and comment publishing
- Optional GitHub token for manual private-repository reviews

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
for live reviews, then run these commands in separate terminals:

```bash
uv run uvicorn mergescope.main:app --app-dir backend/src --reload --port 8000
```

```bash
cd frontend
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). Vite proxies `/api` to FastAPI. The application
starts its SQLite-backed worker in the FastAPI process, so no additional server is required.

For Phase 4 controls, copy `config/review-policies.example.json` to
`config/review-policies.json`, set `ALLOWED_REPOSITORIES`, and configure a separate
`EVALUATION_RUN_TOKEN`. See [Operations and deployment](docs/OPERATIONS.md).

## Test without Jira or API keys

Jira is not required. Leave **Ticket reference** blank or enter a local label such as `LOCAL-101`.
Click **Run deterministic demo** to exercise validation, storage, history, and review inspection
without credentials. Demo reviews cannot be published.

For live review automation, follow [GitHub App setup](docs/GITHUB_APP_SETUP.md). Keep
`GITHUB_PUBLISHING_ENABLED=false` while testing webhooks and the job queue.

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

FastAPI serves `frontend/dist` at [http://localhost:8000](http://localhost:8000).

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Integration, worker, queue, and storage readiness |
| `GET` | `/api/config` | Safe client configuration without secrets |
| `GET` | `/api/reviews` | Recent review runs |
| `POST` | `/api/reviews/manual` | Run a manual live or deterministic demo review |
| `GET` | `/api/reviews/{id}/publication-preview` | Preview the exact GitHub review payload |
| `POST` | `/api/reviews/{id}/publish` | Publish after literal `confirm: true` validation |
| `GET` | `/api/jobs` | Inspect durable webhook review jobs |
| `POST` | `/api/webhooks/github` | Receive signed GitHub App deliveries |
| `GET` | `/api/policies` | Inspect non-secret policy readiness and defaults |
| `GET` | `/api/evaluations/dataset` | Inspect the labeled evaluation-set summary |
| `GET/POST` | `/api/evaluations/runs` | List or explicitly run measured evaluations |
| `GET/POST` | `/api/knowledge/documents` | List or index local guidance |
| `DELETE` | `/api/knowledge/documents/{id}` | Delete a document and its chunks |

Interactive API documentation is available at `/docs`.

## Safety boundaries

- Webhook signatures are verified with a constant-time comparison before JSON parsing.
- Duplicate delivery IDs and duplicate repository/PR/head/prompt combinations reuse one job.
- Worker jobs are leased, retried with backoff, and recover after process restarts.
- Stale webhook heads are superseded; stale reviewed heads cannot be published.
- Only deterministic, line-validated findings become inline comments.
- GitHub publishing defaults to disabled and requires an explicit preview confirmation.
- The write endpoint additionally requires a server-side operator token entered at confirmation.
- Paid evaluation runs require a separate server-side evaluation token and literal confirmation.
- An optional repository allowlist is enforced before manual review or webhook enqueue.
- The resolved review policy is part of cache and webhook-job identity.
- Repository policy defaults keep comment publishing disabled until explicitly enabled per repo.
- Logs never include request bodies, credentials, webhook payloads, or operator tokens.
- Publication uses a hidden idempotency marker to recover from ambiguous network failures.
- Published reviews use GitHub's non-approving `COMMENT` event.
- Secrets and private keys are never returned by the API; `.env` and `*.pem` are ignored by Git.

## Operational guides

- [GitHub App setup](docs/GITHUB_APP_SETUP.md)
- [Evaluation, policies, deployment, and backup](docs/OPERATIONS.md)
- [Four-weekend implementation plan](docs/PROJECT_PLAN.md)
