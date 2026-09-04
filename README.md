# MergeScope AI

MergeScope AI is a Docker-free pull-request review workspace. It fetches a GitHub PR, asks an OpenAI model for a structured review, stores the result in SQLite, and presents the review in a focused React dashboard.

The first milestone is intentionally safe: reviews run in **dry-run mode** and never post comments back to GitHub.

## What is included

- FastAPI API with health, configuration, manual review, history, and detail endpoints
- React + Vite dashboard served separately in development and by FastAPI after a production build
- GitHub REST integration; a token is optional for public repositories
- OpenAI Responses API with a typed review schema
- SQLite persistence with no Redis, Jira, or Docker requirement
- Optional ticket reference field, ready for a future Jira or local-ticket provider
- Automated backend tests with mocked GitHub and OpenAI clients

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Node.js 20+
- An OpenAI API key
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

On PowerShell, use `Copy-Item .env.example .env` instead of `cp`.

Set `OPENAI_API_KEY` in `.env`, then run the two development servers in separate terminals:

```bash
uv run uvicorn mergescope.main:app --app-dir backend/src --reload --port 8000
```

```bash
cd frontend
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). The Vite server proxies `/api` requests to FastAPI.

## Test without Jira

Jira is not required. Leave **Ticket reference** blank, or enter a label such as `LOCAL-101` to test that optional metadata is preserved. MergeScope does not contact Jira in this milestone.

Use a public pull request URL, keep **Dry run** enabled, and submit the review. A GitHub token is not required for a public repository, although unauthenticated requests have a lower rate limit.

## Validation

```bash
uv run pytest
uv run ruff check backend
cd frontend
npm run build
```

## Single-server production build

```bash
cd frontend
npm run build
cd ..
uv run uvicorn mergescope.main:app --app-dir backend/src --host 0.0.0.0 --port 8000
```

FastAPI detects `frontend/dist` and serves the dashboard at [http://localhost:8000](http://localhost:8000).

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Service and integration readiness |
| `GET` | `/api/config` | Safe client configuration |
| `GET` | `/api/reviews` | Recent review runs |
| `GET` | `/api/reviews/{review_id}` | Complete review result |
| `POST` | `/api/reviews/manual` | Run a dry-run review for a GitHub PR URL |

Interactive API documentation is available at `/docs`.

## Safety boundaries

- Pull-request content is treated as untrusted input; instructions found inside code or comments are ignored.
- Secrets are loaded only from environment variables and are never returned by the API.
- GitHub write operations are not implemented in this milestone.
- Large diffs are truncated deterministically before being sent to the model.
