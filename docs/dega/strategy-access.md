# Timed strategy access

The backend stores purchase rules in the `strategy-access-policy` database configuration.
Rules specify explicit quantities (for example 5 Silver OR 3 Golden), a duration, and
spending priority. Diamond is an independent global alternative for all strategies.
No local holding threshold grants access.

Select a strategy and choose **Activate access**, or install it. Canon shows affordable
options and asks for explicit confirmation before permanently consuming elements.
The backend selects the cheapest complete alternative and creates a timed grant in
the same transaction. Existing active access is reused without spending or extending it.
Repeat downloads are free during that window. Failed downloads can be retried.

Before starting or relaunching, Canon checks its account-scoped local grant in
`~/.canon/strategy-access.json` (0600). A valid window needs no network request. After
expiry, Canon checks remote access and caches a newer grant if one exists. Otherwise
it blocks the new start and requires explicit activation. Missing/corrupt cache also
requires synchronization. No automatic purchases or renewals occur.

Expiry does not stop existing automations, child processes, orders or positions.
Local checks in an open-source client are not tamper-proof DRM. All backend archive
requests require authentication and a current grant regardless of the client cache.

## Coordinated release

Deploy the matching backend migration and API first, configure exact stored element
classes and enable the approved policy, then install this Canon version. Old clients
cannot perform activation and will be denied archive downloads. Chat registration,
fees and registry contracts are unchanged.

Test policy: strategies cost 1 through 12 Silver OR Golden in catalog order. Durations
are 1, 7, 30 and 365 days in groups of three. One Diamond grants 365 days globally.
All quantities/durations remain editable in DB. Verify actual class names before seeding.

The inventory still contains owned elements after consumption; `consumed_at` and
`consumed_grant_id` distinguish spent inventory. Only unconsumed elements fund access.
Backend tests cover HTTP downloads and concurrent purchases with disposable PostgreSQL.
