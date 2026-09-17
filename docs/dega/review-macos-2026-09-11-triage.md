# DEGA Canon macOS Review — Triage Matrix

> Source review: `docs/dega/review-macos-2026-09-11.md` — never committed to this repository, so the
> matrix below is the record of it.
>
> The original F5 note ("`canon-strategies` is public, so keep the public download path") is now
> **obsolete**: strategy archives are delivered by the authenticated backend
> (`GET /strategies/archive`), gated by the user's element grant, and the public GitHub/codeload
> path was removed. F5 was correct at the time; the delivery model has since changed. See
> [strategy-access.md](strategy-access.md) and [sandbox-live.md](sandbox-live.md).

| ID | Finding | Classification | Proposed fix |
|---|---|---:|---|
| F1 | Email approval can connect the wrong existing account | correct | Fix the user creation / lookup path so the inserted ID is always returned, reject undefined-ID lookups, and add a two-account regression test for token/session binding. |
| F2 | A long log line breaks runner reading and leaves the runner marked active | correct | Drain stdout in bounded chunks, split oversized lines safely, and always finalize task state in `finally` even on stream errors. |
| F3 | The fee display uses the wrong precision | correct | Read `decimals()` from the active token, use decimal-safe formatting, cache decimals, and update docs/examples. |
| F4 | The generic command runner does not execute several catalog packages correctly | correct | Add explicit package metadata for build/dry-run/live commands and stop assuming `start` or the first script is the right entrypoint. |
| F5 | The installer cannot download private catalog files | incorrect | The repo is public, so no private-repo auth is needed; if a package is missing, surface it as a missing artifact, not an auth issue. **Superseded:** archives are now delivered by the authenticated backend (element-gated), not from a public repo. |
| F6 | Nostr identity ignores the documented config-file key | correct | Resolve one persisted key source once and pass it consistently to both registry and chat identity; add restart/config precedence tests. |
| F7 | The approval transition is not atomic | correct | Update the approval write so it only succeeds while the row is still pending and verify the affected row count; add approve-vs-consume race tests. |
| A1 | Email approval and Host-based guard are unsafe | partial | Keep the local/dev shortcut only for isolated development; require authenticated identity and stop trusting Host in shared/remote releases. |
| A2 | The approval page only implements the local/dev route | partial | Wire the page to the authenticated approval route for shared releases and keep the local route isolated for dev. |
| A3 | The cookie change affects the existing web login behavior | partial | Preserve Secure, set SameSite to match the deployment topology, and avoid letting local-only cookie settings bleed into production. |

## Summary

- Correct: F1, F2, F3, F4, F6, F7
- Incorrect as written: F5
- Partial / release-model dependent: A1, A2, A3

## Follow-up order

1. Fix F1 identity binding.
2. Fix F2 runner draining/state cleanup.
3. Fix F3 fee formatting.
4. Fix F4 package command selection.
5. Keep F5 on the public-download path; update docs only if needed.
6. Fix F6 key resolution.
7. Fix F7 atomic approval transitions.
8. Decide shared-vs-local auth behavior for A1–A3 and document it.

## Status (verified 2026-09-11)

| ID | Status | Evidence |
|----|--------|----------|
| F1 | ✅ Fixed & verified | identity rule unit tests + E2E: session A/email B → 403; session B → user B |
| F2 | ✅ Fixed & verified | bounded `read()` drain; 200 KB chunk test passes |
| F3 | ✅ Fixed & verified | `token_decimals()` reads real Sepolia token (18); `e2e_fee_decimals_real.py` PASS |
| F4 | ✅ Fixed & verified | explicit build/dry-run/live metadata; selection test passes |
| F5 | ✅ Closed (not a bug) | repo is public; docs updated. Delivery has since moved to backend-gated archives (`strategy-access.md`) |
| F6 | ✅ Fixed & verified | `resolve_identity_secret_key()` precedence; 4 tests pass |
| F7 | ✅ Fixed & verified | atomic approve + consume; E2E single-use + `device.atomic.test.ts` |
| A1 | ✅ Resolved | dead Host guard removed; published flow requires authenticated session |
| A2 | ✅ Decided | published flow requires login (session + email match); verified by E2E |
| A3 | ✅ Fixed & verified | explicit cookie policy (`DEGA_COOKIE_CROSS_SITE`); unit + E2E cookie checks pass |

See [testing.md](testing.md) for how each result was produced and how to re-run it.

## Follow-up (2026-09-12)

A second macOS pass reported six remaining items. All six are resolved at the current state, each
verified by execution (no mocks): contract reads against the live Sepolia registry, a real
PostgreSQL, and the real `market-forecast` package.

| # | Reported item | Status | Evidence |
|---|---------------|--------|----------|
| 1 | Creating account B after A returned A | Fixed, and the test discriminates | `users.id` is `generated: "uuid"`; reverting it makes `encore test` fail with `user insert did not return an id`. `updateOrCreate` also normalizes the email (`trim().toLowerCase()`) before the lookup and every write, so a case-variant address cannot create a second account |
| 2 | Runner did not build before `start` (`market-forecast` missed `dist/index.js`) | Fixed | Real run: `building first: npm run build` → `tsc` → `npm run start` (`node dist/index.js`); `dist/index.js` exists only after the pre-step |
| 3 | Token read 18 decimals but the UI showed `0.5` | Fixed | `0.00000000005 $DEGA` from the live contract; a forced real read failure falls back to the ERC-20 standard **18** (flagged as assumed), so the figure stays correct instead of `0.5` |
| 4 | `ChatView` ignored `dega-chat.env` | Not reproducible (claim was incorrect) | With a private temp HOME, the derived Nostr pubkey matches the `DEGA_CHAT_PK` in that file |
| 5 | A single newline-less line accumulated until EOF | Fixed | Real 400 MB single-line child: parent peak-RSS delta stayed ~0.9 MB (bounded 16 KB flushes) |
| 6 | `encore test` 25/1 due to duplicate-email policy | Fixed | `encore test` now passes 32/32, including the merge policy tests |

Additional fixes made while closing the follow-up:

- Runner command selection (`F4`): `build`/`compile` is only a pre-step, checkers are never the
  entrypoint, and a package with no execution script is reported as not runnable.
- Dev/test-gated `POST /users/login-encore` route so the HTTP E2E exercises account creation
  through the real login path (fails closed outside `development`/`test`).
- The two DB suites are split into a loader plus body, so they run under `encore test` and skip
  (rather than fail) on an offline unit run.

> The follow-up document referenced by the reviewer
> (`docs/dega/review-macos-2026-09-12-follow-up.md`) was never committed to this repository; this
> section records that follow-up state instead.

