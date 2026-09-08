# Evaluation and operations

Phase 4 keeps MergeScope Docker-free and single-server. FastAPI, the background worker, the built
React application, and SQLite run as one process. Use a test repository until its evaluation results
are acceptable.

## Repository boundary

Set a comma-separated allowlist. Matching is case-insensitive and exact.

```dotenv
ALLOWED_REPOSITORIES=your-org/test-repository,your-org/another-repository
```

An empty value preserves local Phase 1–3 behavior and allows all repositories, but the Evaluation
page reports that boundary as open. Disallowed manual reviews fail before GitHub or OpenAI access;
valid signed webhooks return an ignored receipt without creating a job.

## Review policies

Copy the versioned example, then edit the copy. The active file is intentionally untracked so local
operational decisions do not leak into the repository.

```bash
cp config/review-policies.example.json config/review-policies.json
```

```dotenv
REVIEW_POLICIES_PATH=config/review-policies.json
```

Repository overrides merge over `default`. Available controls are:

| Control | Effect |
|---|---|
| `require_ticket_reference` | Reject reviews without a local/Jira/ADO reference |
| `security_review` | `disabled`, `conditional`, or `always` |
| `testing_review` | Run or skip the testing specialist |
| `blocking_severities` | Severities eligible to request changes |
| `blocking_categories` | Categories eligible to request changes |
| `minimum_confidence` | Prevent low-confidence clean reviews from approving |
| `max_inline_comments` | Cap GitHub inline comments from 0–100 |
| `publish_comments` | Allow publishing for this repository |

The selected model and resolved policy fingerprint are part of review-cache and webhook-job
identity. After a model or policy change and API restart, the same pull-request head is reviewed
under a new identity rather than reusing results produced by the previous controls.

Comment publication requires all three locks: the global publishing flag, the publication operator
token, and `publish_comments: true` in the resolved repository policy.

## Labeled evaluation

`evaluations/cases.json` contains six synthetic cases: two good, two defective, and two adversarial.
Expected findings use exact path, added-line number, and category labels. A run records:

- true positives, false positives, and false negatives;
- precision and recall;
- rejected/invalid-line rate after deterministic grounding;
- summed model latency and input/output tokens;
- cost estimated from explicitly configured current model rates.

The dashboard shows reference targets of at least 80% precision, at least 80% recall, and at most a
2% invalid-line rate. These are visible comparison markers, not an automatic deployment decision;
adjust the dataset and acceptance criteria for your repositories before broader use.

Configure rates for the model you actually select. Rates default to zero because provider pricing
changes and a stale hard-coded value is worse than a visible "not configured" state.

```dotenv
EVALUATION_RUN_TOKEN=generate-a-long-random-operator-token
OPENAI_INPUT_COST_PER_MILLION=0
OPENAI_OUTPUT_COST_PER_MILLION=0
```

The UI requires the evaluation token immediately before the paid run. It is sent once in the
`X-MergeScope-Evaluation-Token` header and is not stored. The endpoint also requires literal
`confirm_cost: true`.

## Structured logs and correlation

```dotenv
LOG_LEVEL=INFO
LOG_JSON=true
```

Each HTTP response includes `X-Request-ID`. A safe caller-supplied ID is preserved; otherwise a UUID
is generated. Signed webhook jobs persist that correlation ID, and the worker restores it while
processing. JSON events contain request method/path/status/duration and safe job or evaluation IDs.
Request bodies, diffs, prompts, webhook payloads, credentials, and operator-token headers are not
logged.

## Online SQLite backups

The backup command uses SQLite's online backup API, so the API can remain running:

```bash
uv run python scripts/backup_sqlite.py --retain 7
```

Optional paths:

```bash
uv run python scripts/backup_sqlite.py \
  --database data/mergescope.db \
  --destination backups \
  --retain 14
```

Each `.db` file has a sibling JSON manifest containing its UTC creation time, byte size, and SHA-256
digest. The new copy must pass `PRAGMA integrity_check` before older copies are pruned.

Restore drill:

1. Stop FastAPI.
2. Preserve the current `data/mergescope.db` instead of overwriting it blindly.
3. Copy one backup to a temporary path and run `PRAGMA integrity_check`.
4. Set `DATABASE_PATH` to the verified copy and start FastAPI.
5. Confirm `/api/health`, review history, jobs, and evaluation runs before replacing the primary.

## Non-Docker deployment

Build and validate on the target machine:

```bash
uv sync --frozen --no-dev
cd frontend
npm ci
npm run build
cd ..
uv run uvicorn mergescope.main:app --app-dir backend/src --host 127.0.0.1 --port 8000
```

`deploy/mergescope.service.example` is a hardened systemd starting point. Copy it to
`/etc/systemd/system/mergescope.service`, adjust the user and paths, then enable it. Keep Uvicorn on
loopback behind an HTTPS reverse proxy. The only endpoint that normally needs public ingress is
`/api/webhooks/github`; keep the dashboard and all other API routes on a private network, VPN, or SSH
tunnel because MergeScope is an operator console, not a public multi-tenant service.

Schedule the backup CLI using a systemd timer, cron, or Windows Task Scheduler and copy retained
backups to storage outside the application host. Test a restore periodically; an untested backup is
only an assumption.
