# DEGA / Canon — Backend runbook (Encore, `dega_agents_fe`)

How to run the Encore backend locally, the device-flow auth model, and the cookie policy. This is
the companion to [testing.md](testing.md) for operational concerns.

## Run it

```bash
cd ~/projects/DEGA/dega_agents_fe/backend

# 1) Node 22 is REQUIRED (Node >=23 crashes jsonwebtoken at boot).
#    The Encore daemon must inherit Node 22, not just the CLI.
pkill -f 'encore daemon'; sleep 2
export PATH="$HOME/.nvm/versions/node/v22.15.1/bin:$PATH"

# 2) Start
encore run
```

Healthy output ends with:

```
Encore development server running!
  Your API is running at:     http://127.0.0.1:4000
  Development Dashboard URL:  http://127.0.0.1:9400/ai-agents-4eg2
```

Sanity check:

```bash
curl -s -X POST http://127.0.0.1:4000/device/code
# -> {"user_code":"XXXX-XXXX","device_code":"...","expires_in":600,"interval":5,...}
```

> The `Failed to write to Google Cloud Logging: 16 UNAUTHENTICATED` line on boot is benign — it is
> the remote logger without OAuth credentials in local dev. It does not affect the API.

## Device-flow auth model (A1/A2)

- `/device/code` — issues a code (public).
- `/device/approve` — **auth required**; approves for the signed-in user.
- `/device/approve-encore` — **auth required**; also requires the typed email to match the signed-in
  account. There is **no host-based or email-only shortcut** (the old `localOrDevHost` guard was
  removed; it did not actually validate anything).
- `/device/token` — exchanges a code for a session token, exactly once (single-use).
- `/users/login-encore` — **development/test only**: creates/updates the account for an email through
  `UserOperations.updateOrCreate` (the same path as the real login) and issues a real session. It
  exists so local flows and the HTTP E2E can exercise account creation without a Firebase token; the
  gate is `devRoutesEnabled()` (`core/logic/devRoutes.ts`): allowed when Encore's runtime type is
  `development` or `test`, denied for `production`/`ephemeral`, and fail-closed when the runtime
  metadata is unavailable. It never trusts `Host`/`X-Forwarded-*`.

To approve a device in a browser you must first be logged in on the web app (same-origin
`ai_agent_session` cookie). The page (`GET /device`) calls `/users/me` and compares the typed email
to the logged-in account before approving.

### Local manual flow (no browser login)

`backend/script/e2e_device_auth.py` creates accounts A and B through `POST /users/login-encore`
(real `UserOperations.updateOrCreate` + a real session row), asserts that creating B does not return
A, and then drives the whole device flow over HTTP. psql is used only for read-back checks and
cleanup. Run it after the backend is up:

```bash
npm run test:e2e
```

## Account identity policy (F1)

The `users` table enforces **one account per email** (`unique_email`, migration 019) plus
`unique_provider_user` on `(provider, provider_id)`. `UserOperations.updateOrCreate` therefore
resolves in this order:

1. **Exact provider identity** — `(provider, provider_id)` is the stable key for a login provider.
2. **Same email** — an account already exists for that address, so the call merges into it
   (keeping its `id` and its provider identity) instead of attempting an insert the DB would reject.
   Only profile fields (`email`, `display_name`, `photo_url`) are refreshed; identity is never
   rebound.
3. **Otherwise** a new account is created (`id` defaults to `gen_random_uuid()`).

The email is normalized (`trim().toLowerCase()`) **before the lookup and before every write**, so
`A@x.com` and `a@x.com` resolve to one account — `unique_email` is case-sensitive, so an
un-normalized write could otherwise create a second account for the same address.

The TypeORM schema declares `users.id` as `generated: "uuid"` (`core/models/schemas/user.ts`), so
`save()` returns the DB-generated id; `UserOperations.create` refuses to look up by an undefined id
(which would drop the filter and could return another account).

A missing `provider`/`provider_id` is rejected up front (`logic/identity.ts`), so email is never an
unvalidated lookup key.

Note: the device-approval guard is separate from this — approval always requires an authenticated
session whose email matches the typed email, so a merge can never hand out another account's
session.

## Cookie policy (A3)

Implemented in `core/logic/cookies.ts`. Flags are chosen from an **explicit** deployment choice,
never inferred from proxy headers (Encore's local gateway also sets `x-forwarded-host`, which
previously mislabeled local-dev cookies as `SameSite=None; Secure`).

| Env var | Effect |
|---------|--------|
| `DEGA_COOKIE_CROSS_SITE=true` | `SameSite=None; Secure` |
| (unset) | `SameSite=Lax`; `Secure` only on HTTPS outside a development runtime |

`authCookieClear()` mirrors the same flags so the logout cookie is removed.

## Fee decimals (F3)

`ChainRegistry.token_decimals()` reads `degaToken()` then ERC-20 `decimals()` once and caches it.
Production DEGA reports **18** decimals; the verified production fee of
`6719270000000000000000000` base units renders as **6,719,270 DEGA**. If the contract cannot be read, the UI shows base units with
“token scale unavailable”. Only successful reads are cached, so the next refresh retries.
Read-only check:

```bash
cd ~/projects/DEGA/canon-app && uv run python tools/e2e_fee_decimals_real.py
```

## Local database networking (WSL2 workaround)

The default docker `bridge` on this machine can stop forwarding to newly published ports, which
makes `encore run` fail with `connection reset by peer` / `dial error: timeout`. The workaround is
to run the Encore DB container on a **user-defined** network:

```bash
docker network create encore-db-net 2>/dev/null || true
docker rm -f sqldb-ai-agents-4eg2-default-da2vigibaa0ue4q70uag
docker run -d --name sqldb-ai-agents-4eg2-default-da2vigibaa0ue4q70uag \
  --network encore-db-net -p 32768:5432 --restart unless-stopped \
  -v sqldb-ai-agents-4eg2-da2vigibaa0ue4q70uag-default:/var/lib/postgresql \
  -e PGDATA=/var/lib/postgresql/data \
  -e POSTGRES_PASSWORD=postgres -e POSTGRES_HOST_AUTH_METHOD=trust \
  postgres:18
```

Then start Encore as above. If the bridge breaks again, `sudo systemctl restart docker` (or
`wsl --shutdown`) regenerates the rules.
