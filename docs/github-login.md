# GitHub sign-in and manual PR publishing (v0.5)

## One-time GitHub App setup

Create or update a **GitHub App**, not a classic OAuth App, under GitHub Settings → Developer settings.

1. Homepage: `http://localhost:5173`.
2. User authorization callback: `http://localhost:5173/api/auth/callback`.
3. Keep expiring user access tokens enabled. MergeScope refreshes them on the server.
4. Disable **Active** under Webhooks. No webhook URL, tunnel, or delivery subscriptions are needed.
5. Repository permissions: **Contents: read**, **Pull requests: read and write**, **Metadata: read**.
6. Install the App on selected repositories. Organization repositories may require owner approval.
7. Copy the App's **Client ID** (not App ID), generate a **Client secret**, and note its URL slug.

GitHub sign-in alone does not grant access to every public repository. Available repositories are
those explicitly accessible through both the user's App installations and account permissions,
intersected with `ALLOWED_REPOSITORIES` if set. Owned, collaborator, and permitted organization
repositories qualify. If an organization uses SAML SSO, establish its SSO session before sign-in.

## Environment

Put these in the root `.env`; never commit actual secrets:

```dotenv
GITHUB_CLIENT_ID=your-github-app-client-id
GITHUB_CLIENT_SECRET=your-github-app-client-secret
GITHUB_APP_SLUG=your-github-app-slug
AUTH_ENCRYPTION_KEY=generated-fernet-key
APP_ORIGIN=http://localhost:5173
GITHUB_CALLBACK_URL=http://localhost:5173/api/auth/callback
AUTH_COOKIE_SECURE=false
SESSION_TTL_SECONDS=604800
ALLOWED_GITHUB_USER_IDS=your-numeric-github-user-id
ALLOWED_REPOSITORIES=Sinchan26/mergescope-ai
GITHUB_PUBLISHING_ENABLED=false
WORKER_ENABLED=false
OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL=gpt-4o-mini
```

Generate the encryption key locally after `uv sync`:

```bash
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Keep this key stable across restarts and back it up securely, separately from the databases.
Find your public numeric GitHub ID from `https://api.github.com/users/YOUR_USERNAME` (the `id`
field, not `node_id`). `ALLOWED_GITHUB_USER_IDS` accepts comma-separated IDs; empty denies all users.
This prevents arbitrary sign-ins from using your server's OpenAI key. Adding another ID deliberately
authorizes that person to incur review/indexing costs. Evaluations also require `EVALUATION_RUN_TOKEN`.

`GITHUB_TOKEN`, App private keys, `PUBLISH_CONFIRMATION_TOKEN`, webhook secrets, and worker settings
are not used by this runtime. They may remain in an older `.env` but provide no authentication bypass.
`DRY_RUN_ONLY=true` means analysis itself never posts; it does not disable separately confirmed publication.

## Run and publish

Run the usual two development servers from the README. Use **localhost** consistently, not a mix
of localhost and 127.0.0.1. The browser must use the configured origin. Vite proxies `/api` including
the callback to port 8000. Register the callback exactly; do not point it to the backend port while
using the frontend on 5173. No public callback tunnel is needed for this browser redirect.

1. Click **Continue with GitHub**, authorize the App, and choose/install repository access if needed.
2. Select a repository or paste its PR URL. An installation change requires a page reload to update
   the selector; backend permissions are checked afresh regardless of the displayed list.
3. Run the deterministic demo first. It is private to your account and cannot be published.
4. Run a small live PR review. It uses the configured OpenAI API key; Jira is optional and no Jira
   connection is required. Ticket references can be arbitrary local labels.
5. To publish, set `GITHUB_PUBLISHING_ENABLED=true`, copy `config/review-policies.example.json` to
   `config/review-policies.json`, and set `publish_comments: true` for your intended repository.
   Restart the backend. Example policy:

```json
{
  "default": { "publish_comments": false },
  "repositories": { "Sinchan26/mergescope-ai": { "publish_comments": true } }
}
```

6. Expand the comment preview and confirm publication. One GitHub `COMMENT` review is created
   as the signed-in user through the App, with validated inline comments. No shared token prompt.
   MergeScope rechecks repository access and the PR head; changed commits require a fresh review.

## Storage and upgrade

For `DATABASE_PATH=data/mergescope.db`, the new layout is:

| File | Contents |
|---|---|
| `data/mergescope.db` | Existing legacy data, left untouched and not exposed by the signed-in API |
| `data/mergescope.auth.db` | Hashed session identifiers and encrypted OAuth/token records |
| `data/mergescope-users/<numeric-id>.db` | That user's reviews, caches, documents/chunks, and evaluations |

Separate user databases avoid shared-table authorization mistakes and global document-hash
collisions. They are created lazily after sign-in. Review access also binds to numeric repository
IDs so a different repository reusing an old name does not expose earlier review content. Renamed
repositories' old reviews are hidden until a deliberate migration; there is no automatic reassignment.
Do **not** delete or copy the legacy DB into a user's workspace: its ownership is unknown.

Back up each user DB with `scripts/backup_sqlite.py --database <path>` (see `--help`), rather than
backing up only the old `DATABASE_PATH`. Stop the app before taking a full-directory snapshot;
include SQLite WAL files if not using SQLite's backup API. Protect backups and the parent data
directory: review/document content is not encrypted at rest. Session token payloads are encrypted;
DB files are chmod 0600 on POSIX. Use disk encryption/OS ACLs as appropriate.

Rotating `AUTH_ENCRYPTION_KEY` invalidates stored sessions; users sign in again. Logout deletes
the current server-side session, not GitHub's App grant or other devices' sessions. Revoke the App
in GitHub account settings to remove the grant. Revocation is detected by a failed GitHub check
on the next protected request, without needing a webhook. Existing stored data is not deleted.

## Deployment boundaries

- Supported: local or small trusted-user deployment with **one Uvicorn process**, SQLite, and a
  same-origin frontend/API. Do not enable multiple workers: token-refresh locks and workspace
  initialization are process-local. Multi-instance hosting needs coordinated sessions/jobs/storage.
- Remote deployment must use HTTPS and `AUTH_COOKIE_SECURE=true`. Set both auth URLs to the
  public HTTPS origin and register the callback. HTTP is accepted only for localhost development.
- Disable query-string access logging in the reverse proxy. OAuth callback codes/state are secrets.
  The application logs paths only and disables Uvicorn's default access logger. Never enable
  request-body, Authorization-header, Cookie-header, or token debug logging.
- Sessions have a fixed maximum age; cookies are HttpOnly/SameSite=Lax. Unsafe endpoints require
  an exact Origin plus session-bound CSRF. OAuth uses browser-bound, expiring, single-use state
  and PKCE S256. Tokens are never returned to the frontend or put in localStorage.
- API responses are `Cache-Control: no-store`; sign-out/session failure unmounts the private UI.
- This is not a public SaaS billing/security boundary: add reverse-proxy rate limits, per-user spend
  quotas, storage quotas, auditing, and coordinated concurrency before inviting untrusted users.
  GitHub API outages/rate limits intentionally fail closed, including access to saved live reviews.

## Testing checklist

Automated tests use fake GitHub/OpenAI responses, never live comments or paid model calls:

```bash
uv run ruff check backend
uv run ruff format --check backend
uv run pytest
cd frontend
npm test
npm run build
```

Live acceptance requires your App credentials: login → selected repository → small PR review →
preview → publish → verify GitHub author and inline locations. Then sign out, use a second enabled
account, and verify empty independent history/documents. Remove repository installation access
and confirm history/preview/publish no longer reveal that repository. Advance the PR head after
review and verify publication is blocked. A second publish of the same completed review must not
create another GitHub review. These live actions are intentionally not part of automated tests.

## References

- [GitHub App user access tokens and PKCE](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app)
- [User-accessible App installations and repositories](https://docs.github.com/en/rest/apps/installations)
- [Creating a PR review](https://docs.github.com/en/rest/pulls/reviews#create-a-review-for-a-pull-request)
