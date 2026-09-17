"""Verify the RFC 8628 single-use fix: concurrent /device/token polls.

Approves one device code, then fires two concurrent POST /device/token calls.
Exactly one must mint a session; the loser must get a 404 ("already used").
Requires the Encore backend at $DEGA_API_URL and its local Postgres container.
"""

import asyncio
import os
import subprocess

import httpx

API = os.environ.get("DEGA_API_URL", "http://127.0.0.1:4000")
TEST_USER_ID = "e2e00000-0000-0000-0000-00000000ca1e"
TEST_EMAIL = "race-test@dega.org"


def find_pg():
    out = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True).stdout
    for name in out.splitlines():
        if name.startswith("sqldb-ai-agents-4eg2"):
            return name
    raise SystemExit("no Encore postgres container")


def psql(container, sql):
    subprocess.run(
        ["docker", "exec", container, "psql", "-U", "postgres", "-d", "agents_core", "-c", sql],
        check=True, capture_output=True,
    )


async def main():
    container = find_pg()
    psql(container, f"INSERT INTO users (id, provider, provider_id, email) VALUES ('{TEST_USER_ID}','firebase','race','{TEST_EMAIL}') ON CONFLICT (id) DO NOTHING;")
    try:
        async with httpx.AsyncClient() as c:
            r = await c.post(f"{API}/device/code")
            code = r.json()
            dc = code["device_code"]
            psql(container, f"UPDATE device_codes SET status='approved', user_id='{TEST_USER_ID}', approved_at=now() WHERE device_code='{dc}';")

            # Fire two concurrent token exchanges.
            r1, r2 = await asyncio.gather(
                c.post(f"{API}/device/token", json={"device_code": dc}),
                c.post(f"{API}/device/token", json={"device_code": dc}),
            )
            print("resp1:", r1.status_code, r1.text[:60])
            print("resp2:", r2.status_code, r2.text[:60])
            ok = [r for r in (r1, r2) if r.status_code == 200]
            reused = [r for r in (r1, r2) if r.status_code == 404]
            assert len(ok) == 1, f"expected exactly 1 minted session, got {len(ok)}"
            assert len(reused) == 1, f"expected 1 rejected (404), got {len(reused)}"
            print("RACE-CONCURRENCY FIX: PASS (1 session minted, 1 rejected)")
    finally:
        for table, col in (("sessions", "user_id"), ("device_codes", "user_id"), ("users", "id")):
            psql(container, f"DELETE FROM {table} WHERE {col}::text LIKE '%{TEST_USER_ID}%';")


if __name__ == "__main__":
    asyncio.run(main())
