# IgorAgent

IgorAgent is a policy-bounded Telegram AI userbot with a local control plane. It separates **who may request an action** from **what the connected Telegram account may do**. The initial release intentionally contains no cryptocurrency tools and starts with dangerous account actions disabled.

## What is implemented now

- Telegram user-account worker boundary built on Telethon; it does not connect until explicit environment variables are provided.
- Dashboard for initial policy, LLM budget and heartbeat configuration.
- Direct-message, group and channel access policies; group mention/reply gating.
- Administrator recognition by Telegram numeric ID.
- Permission for posting a photo with caption to an allowed chat/channel: disabled, allowed users, or administrators only.
- Fixed-interval heartbeat or a bounded number of randomly selected unique runs each hour.
- Typed policy decisions, action approval requirements, tool idempotency primitive, audit-chain primitive and test coverage for the core rules.

## Prerequisites

- Linux/macOS, Python 3.12+, Node.js 22+ and npm 10+.
- A separate Telegram test account. Do **not** begin with a personal or production account.
- Telegram application credentials (`api_id`, `api_hash`) created in Telegram's official developer portal.
- An LLM provider key only after the local dashboard has been tested.
- Docker is optional. The supplied Compose file is for local Postgres/Redis/API/Web startup when Docker is available.

## Install and run

### Recommended local start

Install Docker Engine with Docker Compose v2, then clone or unpack the project and run one command:

```bash
cd /root/igoragent
./scripts/start.sh
```

The launcher generates protected local runtime values in `.env`, starts the stack, and prints `http://localhost:3000`. The dashboard is bound to `127.0.0.1` only. Create the dashboard password and complete onboarding in the browser; no `.env` editing is needed for this first run.

### Development without Docker

```bash
cd /root/igoragent
cp .env.example .env
python3 -m venv .venv
. .venv/bin/activate
pip install -e 'packages/core[api,telegram,test]'
uvicorn --app-dir apps/api main:app --reload
```

In a second terminal:

```bash
cd /root/igoragent/apps/web
npm install
npm run dev
```

Open `http://localhost:3000`. Run core tests after dependencies are installed:

```bash
cd /root/igoragent
. .venv/bin/activate
pytest packages/core/tests apps/api/test_auth.py
```

## First-run onboarding

On the first dashboard visit, the onboarding flow must be completed before the normal control panel is shown:

1. **AI settings** — choose provider, model and token budgets. API keys are configured in the server secret store and never returned to the browser.
2. **Telegram login** — enter Telegram `api_id`, `api_hash` and the test-account phone number. IgorAgent requests a Telegram code, then presents a separate code/optional-2FA step. Login codes, API hash and 2FA password are never persisted in dashboard configuration or returned by API responses. The resulting session is stored with owner-only filesystem permissions.
3. **Administrator** — the connected Telegram numeric ID is automatically made the owner; it can be reviewed before completion.
4. **Conversation policy** — choose DM access and group activation. The safe default is group `mention_or_reply` and allowlisted group/channel access.
5. **Captioned photos** — choose disabled, allowed users, or administrators only. Keep it admin-only until testing is complete.
6. **Heartbeat** — leave disabled initially. If enabled, choose either a fixed interval or a maximum run count per hour; random scheduling picks unique execution times within each hour.
7. **Review** — confirm all settings. Completing onboarding saves public configuration and the local Telegram session; it does not send messages or enable dangerous account actions.

## Telegram credentials and sessions

Do not commit Telegram credentials, sessions or keys. `.env` and `*.session` are ignored by Git.

1. Put `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` in the local `.env` file.
2. Set `TELEGRAM_SESSION_PATH` to a protected filesystem location such as `/run/secrets/igoragent.session` in deployment or a permission-restricted local path during development.
3. Start the worker only after policy and dashboard checks are complete:

```bash
. .venv/bin/activate
python apps/worker/telegram_gateway.py
```

The first Telethon login requires interactive phone-code/2FA completion. Run it only on a trusted host. Never paste session strings, codes, 2FA passwords, API keys or wallet credentials into chat, Git, logs or a dashboard field.

## LLM configuration

The dashboard stores provider/model/budget configuration. Secrets should be injected by the deployment environment, e.g. `ANTHROPIC_API_KEY` from a secret manager. The current scaffold does **not** yet invoke an LLM: this prevents accidental spending and Telegram activity until the provider adapter, encrypted secret vault and audit persistence are completed.

Recommended efficiency settings:

- keep `max_output_tokens` low for routine chat replies;
- set a monthly token budget before enabling the worker;
- rely on summaries and scoped memory rather than submitting full chat history;
- keep update deduplication enabled so retries cannot post duplicate messages.

## Bounded memory

Memory is **disabled by default**. When enabled, it never copies an unlimited chat transcript. It holds only three compact types of information: short recent context in RAM, concise conversation summaries, and useful durable facts/preferences.

Safe defaults per user/chat scope are 100 records, 256 KiB total storage, 30-day expiration, at most 8 records and 1,500 estimated tokens injected into an LLM request, plus a 20,000-token monthly memory-write budget. Repeated text is deduplicated. Expired records are removed first; if a scope remains full, the oldest/least-confident/least-accessed non-pinned record is evicted.

Before a write, IgorAgent rejects API/session keys, passwords, OTP/2FA codes, high-entropy tokens, wallet secrets and prompt-injection-like instructions. Memory is scoped to an owner/user/chat and is inserted into the model only as explicitly untrusted reference context. The dashboard can enable/pause writes and tune record, KiB, retention and prompt-context limits. The API supports scoped statistics and deletion through `GET`/`DELETE /api/memory`.

Use the smallest practical limits. For ordinary personal use, the defaults are deliberately conservative and should not consume large storage or prompt budgets.

## Permission model

Every inbound event must pass chat access and activation checks. Every action then passes a separate tool permission check.

| Action | Default |
| --- | --- |
| Text response | allowed for permitted conversations |
| Captioned photo to chat/channel | administrator only |
| Reactions | allowed for permitted conversations |
| Edit/delete, inline buttons, deep links, avatar changes | administrator and explicit approval |
| Crypto/wallet/exchange actions | not implemented |

A permitted user can request an operation, but cannot broaden access or enable an action. The dashboard owner controls policies.

## Heartbeat behavior

- **Disabled:** no autonomous runs.
- **Fixed interval:** runs at the configured interval.
- **Random runs each hour:** at the beginning of an hour IgorAgent deterministically selects up to the configured number of different second-level times for that hour. It records this plan and never exceeds the configured maximum.

Heartbeat never receives more permissions than interactive messages. It should initially be limited to harmless, observable routines.

## Security checklist before connecting an account

- Use a dedicated Telegram account and a test chat/channel.
- Configure an owner Telegram ID and allowlists before enabling all-message behavior.
- Leave captioned-media permission admin-only until verified.
- Keep heartbeat disabled during initial testing.
- Use a secret manager or protected runtime files, not repository config, for API keys and Telegram sessions.
- Verify audit persistence, encrypted credential storage, URL/image validation and approval handling before enabling deep links, inline buttons, profile changes or outbound media at scale.
- Review Telegram's current Terms of Service and rate limits for user-account automation.

## Remote dashboard deployment

Do **not** expose the development server, FastAPI port, Redis or PostgreSQL directly to the internet. The no-domain IP mode below uses plain HTTP because it is designed for the requested simple setup; use it only from a trusted network. For public internet access, use the domain deployment with TLS.

### External access without a domain

On the server, run:

```bash
cd /root/igoragent
./scripts/start-ip.sh
```

The launcher automatically detects the server public IPv4 address, creates or updates protected `.env` values, starts Caddy, and prints a one-time setup link of the form `http://<server-ip>/#setup-token=...` followed by **“Continue setup in the dashboard.”** Open that exact link once. The token is in the URL fragment, so it is not sent to Caddy or the API; the dashboard removes it from the address bar and uses it only in the first password-setup request. Treat the link as a password and do not share it.

If public-IP detection is unavailable because the server is behind NAT or outbound HTTPS is restricted, provide the externally reachable IPv4 explicitly:

```bash
IGORAGENT_PUBLIC_IP=<server-ip> ./scripts/start-ip.sh
```

The IP launcher exposes only port **80**; API, Redis and PostgreSQL remain on a Docker-internal network. HTTP does not encrypt the dashboard password, setup traffic, session cookie, or configuration while in transit. Run this mode only on a network you trust. For an internet-facing dashboard, configure the optional domain deployment below so Caddy provides public TLS.

### Optional domain with public TLS

If a public domain is available, point its A/AAAA record to the server, set `IGORAGENT_DOMAIN` plus strong `POSTGRES_PASSWORD` and `IGORAGENT_SETUP_TOKEN` values in `.env`, then run:

```bash
docker compose -f infra/docker-compose.prod.yml up -d --build
```

Open `https://<your-domain>`. Caddy obtains and renews a public TLS certificate automatically. After the first password is created, remove `IGORAGENT_SETUP_TOKEN` from the deployment environment and restart the API.

Both external modes use same-origin `/api` routing, secure HttpOnly session cookies, CSRF tokens, an eight-hour session limit and a five-attempt/15-minute login rate limit.

## Install from GitHub on a server

Install Docker Engine with Docker Compose v2 and Git, then run:

```bash
git clone https://github.com/<account>/<repository>.git igoragent
cd igoragent
chmod +x scripts/start-ip.sh
./scripts/start-ip.sh
```

After the containers start, the script prints a public HTTP dashboard address and a one-time setup link. Open the setup link in a browser, create a dashboard password, and continue onboarding. Use this HTTP mode only from a trusted network; use the optional domain deployment for public TLS.

The one-time link contains a token after `#`. It is used only to create the first password, is removed from the browser address bar immediately, and must not be shared.

### Update an existing installation

```bash
cd igoragent
git pull --ff-only
docker compose -f infra/docker-compose.ip.yml up --build -d
```

For a local-only installation instead of a public server, run `./scripts/start.sh` and open `http://localhost:3000`.

## Current limitations

The project is an initial secure foundation, not a finished autonomous production agent. Persistent database repositories, encrypted credential vault, live LLM tool loop, safe web/image worker, full Telethon event handling, approvals, audit storage, migrations and browser tests remain the next implementation milestones.
