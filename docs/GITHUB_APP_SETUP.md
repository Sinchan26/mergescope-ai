# GitHub App setup

Use a test repository for the first end-to-end run. GitHub publication is disabled by default.

## 1. Create the app

In GitHub, open **Settings → Developer settings → GitHub Apps → New GitHub App**.

- GitHub App name: any unique name, for example `MergeScope AI Local`
- Homepage URL: your repository or local project page
- Webhook URL: `https://YOUR_PUBLIC_HOST/api/webhooks/github`
- Webhook secret: generate a long random value and retain it for `.env`
- Repository permissions:
  - **Contents:** Read-only
  - **Pull requests:** Read and write
- Subscribe to events: **Pull request**

For local testing, expose port `8000` through an HTTPS tunnel and use its temporary public URL.
MergeScope itself still runs locally and needs no Docker.

Prefer a tunnel or reverse-proxy rule that exposes only `/api/webhooks/github`. If your tunnel
publishes the whole local server, use only a temporary URL and a non-sensitive test repository;
dashboard authentication and repository allowlists are Phase 4 work.

## 2. Generate and store the private key

Generate a private key from the app settings and save the downloaded PEM outside version control.
The repository ignores `*.pem`, but a separate secrets directory is still recommended.

## 3. Configure `.env`

```dotenv
OPENAI_API_KEY=your-openai-key
GITHUB_APP_ID=123456
GITHUB_APP_PRIVATE_KEY_PATH=C:/absolute/path/to/mergescope.private-key.pem
GITHUB_WEBHOOK_SECRET=the-same-secret-entered-in-github
GITHUB_PUBLISHING_ENABLED=false
PUBLISH_CONFIRMATION_TOKEN=generate-a-separate-long-random-value
ALLOWED_REPOSITORIES=your-org/test-repository
REVIEW_POLICIES_PATH=config/review-policies.json
WORKER_ENABLED=true
```

Linux/macOS paths work normally. On Windows, either use forward slashes or a plain absolute path.
Restart FastAPI after changing `.env`.

Copy `config/review-policies.example.json` to `config/review-policies.json`, replace the example
repository name, and set `publish_comments` to `true` only for the test repository you intend to
write to. Phase 4 requires this repository policy in addition to the global publishing flag.

## 4. Install and verify

Install the GitHub App on only the test repository first. Open MergeScope's **Workflow center** and
confirm app authentication, signed webhooks, and the worker show ready. GitHub's app settings can
send a `ping`; opening or synchronizing a non-draft PR should create one durable job.

The supported PR actions are `opened`, `reopened`, `ready_for_review`, and `synchronize`.

## 5. Test publication safely

Keep publishing disabled while validating review quality. When ready:

1. Set `GITHUB_PUBLISHING_ENABLED=true`, set a separate `PUBLISH_CONFIRMATION_TOKEN`, enable
   `publish_comments` in that repository's policy, and restart FastAPI.
2. Select a completed, non-demo review.
3. Expand **Preview comments** and inspect every path, line, and message.
4. Choose **Publish reviewed comments**, enter the publication token, and confirm the native dialog.

Immediately before writing, MergeScope fetches the PR again and requires the reviewed head SHA to
still be current. It creates a GitHub `COMMENT` review, not an approval or request-changes review.

## Troubleshooting

- **Signature validation failed:** the GitHub App webhook secret and `.env` value differ.
- **App not installed:** install the app on the target repository and retry with a new delivery.
- **Permission failure:** verify Pull requests is read/write and Contents is read-only.
- **Job superseded:** the PR received a newer commit; wait for the new head's job.
- **Publishing disabled:** this is the safe default; enable it only for the intended environment.

## GitHub references

- [Generate a JWT for a GitHub App](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-json-web-token-jwt-for-a-github-app)
- [Authenticate as an installation](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation)
- [Validate webhook deliveries](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries)
- [Create a pull-request review](https://docs.github.com/en/rest/pulls/reviews#create-a-review-for-a-pull-request)
