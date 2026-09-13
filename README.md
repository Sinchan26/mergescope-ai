# MergeScope AI

MergeScope AI is a Docker-free pull-request review workspace. It retrieves GitHub changes and local
guidance, runs specialized OpenAI reviewers through LangGraph, validates every finding against the
exact added lines, and stores durable review workflows in SQLite.

Version 0.5 adds GitHub sign-in and private user workspaces. Paste a PR link, inspect the findings,
then confirm publication as your GitHub account—no shared publication token. Webhooks and the
background worker are disabled in this manual-only runtime.

**Start with [GitHub login setup](docs/github-login.md)**. This supersedes the earlier webhook setup.

## Capabilities

- Code and testing reviewers with conditional security review and synthesis
- OpenAI Responses structured outputs and `text-embedding-3-small` knowledge retrieval
- Deterministic validation of changed paths, added lines, duplicates, and final verdicts
- Repository guidance from `AGENTS.md`, `CONTRIBUTING.md`, and PR templates
- Per-user SQLite review cache, knowledge vectors, history, and evaluation results
- GitHub App OAuth with PKCE, encrypted tokens, expiring sessions, refresh, logout, and CSRF checks
- Repository access restricted to the signed-in user ∩ installed App ∩ optional server allowlist
- Comment preview with a second head-SHA check and explicit publish confirmation
- Six labeled good, bad, and adversarial evaluation cases with persisted case-level metrics
- Repository allowlists and policy-controlled agent routing, confidence, blocking, and publishing
- Correlation IDs across HTTP requests and durable webhook jobs with structured JSON logs
- Online SQLite backup CLI with integrity checking, SHA-256 manifests, and retention
- Deterministic demo mode requiring no OpenAI key or Jira (GitHub sign-in still required)
- No Docker, Redis, external queue, vector database, or Jira dependency

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Node.js 20+
- An OpenAI API key for live reviews and document indexing
- A GitHub App client ID/secret and installation on selected repositories

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

On PowerShell, use `Copy-Item .env.example .env` instead of `cp`. Complete
[the one-time auth configuration](docs/github-login.md), and set `OPENAI_API_KEY` for live reviews.
Run these commands in separate terminals:

```bash
uv run uvicorn mergescope.main:app --app-dir backend/src --reload --port 8000 --no-access-log
```

```bash
cd frontend
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). Vite proxies `/api` to FastAPI. The application
uses two development servers; SQLite is embedded. No worker, webhook tunnel, or Jira server is needed.

For Phase 4 controls, copy `config/review-policies.example.json` to
`config/review-policies.json`, set `ALLOWED_REPOSITORIES`, and configure a separate
`EVALUATION_RUN_TOKEN`. See [Operations and deployment](docs/OPERATIONS.md).

## Test without Jira or API keys

Jira is not required. Leave **Ticket reference** blank or enter a local label such as `LOCAL-101`.
Click **Run deterministic demo** to exercise validation, storage, history, and review inspection
without OpenAI charges after signing in. Demo reviews cannot be published.

For publication, enable `GITHUB_PUBLISHING_ENABLED=true` and the repository's
`publish_comments` policy. Keep it disabled until ready to post real comments.

## Validation

```bash
uv run ruff format --check backend
uv run ruff check backend
uv run pytest
cd frontend
npm test
npm run build
npm audit --audit-level=high
```

## Single-server production build

```bash
cd frontend
npm run build
cd ..
uv run uvicorn mergescope.main:app --app-dir backend/src --host 127.0.0.1 --port 8000 --no-access-log
```

FastAPI serves `frontend/dist` at [http://localhost:8000](http://localhost:8000). Set
`APP_ORIGIN=http://localhost:8000` and `GITHUB_CALLBACK_URL=http://localhost:8000/api/auth/callback`,
and register that callback in GitHub. For remote deployment use HTTPS, secure cookies, a same-origin
reverse proxy, and **one application process**. See the auth guide before exposing the service.

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Public minimal liveness check |
| `GET` | `/api/readiness` | Signed-in integration and user-storage readiness |
| `GET` | `/api/auth/login`, `/api/auth/callback` | OAuth redirect and callback |
| `GET` | `/api/auth/me`, `/api/auth/repositories` | Current identity/CSRF and accessible repositories |
| `POST` | `/api/auth/logout` | Invalidate this local session |
| `GET` | `/api/config` | Safe client configuration without secrets |
| `GET` | `/api/reviews` | Recent review runs |
| `POST` | `/api/reviews/manual` | Run a manual live or deterministic demo review |
| `GET` | `/api/reviews/{id}/publication-preview` | Preview the exact GitHub review payload |
| `POST` | `/api/reviews/{id}/publish` | Publish after literal `confirm: true` validation |
| `GET` | `/api/jobs` | Inspect durable webhook review jobs |
| `POST` | `/api/webhooks/github` | Disabled in the manual-only runtime |
| `GET` | `/api/policies` | Inspect non-secret policy readiness and defaults |
| `GET` | `/api/evaluations/dataset` | Inspect the labeled evaluation-set summary |
| `GET/POST` | `/api/evaluations/runs` | List or explicitly run measured evaluations |
| `GET/POST` | `/api/knowledge/documents` | List or index local guidance |
| `DELETE` | `/api/knowledge/documents/{id}` | Delete a document and its chunks |

Interactive API documentation is available at `/docs`. Private endpoints require the session
cookie. Unsafe requests additionally require the exact `Origin` and `X-MergeScope-CSRF` from
`/api/auth/me`; the UI handles these automatically. Shared PATs and publish tokens grant no access.

## Safety boundaries

- The manual runtime never starts the legacy webhook worker or uses bot/PAT credentials.
- GitHub access is checked on protected requests and again immediately before publication.
- User workspaces are keyed by immutable numeric GitHub ID, not username.
- Legacy data is preserved, never automatically assigned to the first person who signs in.
- Stale reviewed heads cannot be published.
- Only deterministic, line-validated findings become inline comments.
- GitHub publishing defaults to disabled and requires an explicit preview confirmation.
- Publication requires the user's session, CSRF check, and literal confirmation, not a shared token.
- Paid evaluation runs require a separate server-side evaluation token and literal confirmation.
- An explicit GitHub-user allowlist limits who can use the server's OpenAI key.
- An optional repository allowlist further restricts GitHub-authorized repositories.
- Cache identity includes policy, knowledge document IDs, ticket reference, model, prompt, and PR head.
- Repository policy defaults keep comment publishing disabled until explicitly enabled per repo.
- Logs never include request bodies, credentials, webhook payloads, or operator tokens.
- Publication uses a hidden idempotency marker to recover from ambiguous network failures.
- Published reviews use GitHub's non-approving `COMMENT` event.
- Secrets and private keys are never returned by the API; `.env` and `*.pem` are ignored by Git.

## Operational guides

- [GitHub sign-in and manual publication setup](docs/github-login.md)
- [Previous webhook design (inactive)](docs/GITHUB_APP_SETUP.md)
- [Evaluation, policies, deployment, and backup](docs/OPERATIONS.md)
- [Four-weekend implementation plan](docs/PROJECT_PLAN.md)
