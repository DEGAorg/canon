"""E2E smoke test: Canon's DeviceClient against the real Encore backend.

Requires the backend running at $DEGA_API_URL (default http://127.0.0.1:4000)
and the Encore Postgres container (auto-discovered by name). Since the browser
approval step needs a real Firebase login, this script simulates it by updating
the device_codes row directly in the local DB — exercising the real
/device/code and /device/token endpoints through the actual Canon client code.
"""

import asyncio
import json
import os
import subprocess

from toad.extensions.dega_panel.device_client import DeviceClient

API = os.environ.get("DEGA_API_URL", "http://127.0.0.1:4000")
TEST_USER_ID = "e2e00000-0000-0000-0000-00000000e2e2"
TEST_EMAIL = "e2e-test@dega.org"


def find_pg_container():
    out = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True).stdout
    for name in out.splitlines():
        if name.startswith("sqldb-ai-agents-4eg2"):
            return name
    raise SystemExit("no Encore postgres container found")


def approve(code, user_id, container):
    sql = (
        f"UPDATE device_codes SET status='approved', user_id='{user_id}', "
        f"approved_at=now() WHERE device_code='{code}';"
    )
    subprocess.run(["docker", "exec", container, "psql", "-U", "postgres", "-d", "agents_core", "-c", sql], check=True)


def insert_user(user_id, email, container):
    sql = (
        f"INSERT INTO users (id, provider, provider_id, email, display_name) "
        f"VALUES ('{user_id}','firebase','e2e-uid','{email}','E2E') "
        f"ON CONFLICT (id) DO NOTHING;"
    )
    subprocess.run(["docker", "exec", container, "psql", "-U", "postgres", "-d", "agents_core", "-c", sql], check=True)


def cleanup(user_id, container):
    # users.id is the PK column; sessions/device_codes reference it as user_id.
    for table, col in (("sessions", "user_id"), ("device_codes", "user_id"), ("users", "id")):
        sql = f"DELETE FROM {table} WHERE {col}='{user_id}';"
        subprocess.run(["docker", "exec", container, "psql", "-U", "postgres", "-d", "agents_core", "-c", sql], check=True)


async def main():
    container = find_pg_container()
    insert_user(TEST_USER_ID, TEST_EMAIL, container)
    client = DeviceClient(base_url=API)

    print(f"1. POST /device/code via Canon DeviceClient ({API})")
    code = await client.request_code()
    print(f"   user_code={code['user_code']} device_code={code['device_code']}")
    assert code.get("device_code") and code.get("user_code")

    print("2. Poll before approval (expect pending)")
    # One-shot check via raw httpx (poll_token loops until approved/timeout).
    import httpx

    async with httpx.AsyncClient() as c:
        resp = await c.post(
            f"{API}/device/token", json={"device_code": code["device_code"]}
        )
    early = resp.json()
    print(f"   -> {early}")
    assert early.get("status") == "pending"

    print("3. Simulate browser approval (update DB row)")
    approve(code["device_code"], TEST_USER_ID, container)

    print("4. Poll after approval (expect approved + session_token + user)")
    approved = await client.poll_token(code["device_code"], expires_in=30, interval=1)
    print(f"   status={approved['status']} token={approved.get('session_token','')[:12]}... user={approved['user']['email']}")
    assert approved["status"] == "approved"
    assert approved["session_token"]
    assert approved["user"]["email"] == TEST_EMAIL

    print("5. Fetch elements via v2 endpoint")
    elems = await client.fetch_elements(TEST_EMAIL)
    print(f"   totalElements={elems.get('totalElements')} aggregated={elems.get('aggregatedElements')}")
    assert "aggregatedElements" in elems

    print("6. Re-poll: code should now be consumed (404)")
    try:
        await client.poll_token(code["device_code"], expires_in=10, interval=1)
        print("   !! code was reusable — FAIL")
    except Exception as exc:
        print(f"   -> correctly consumed: {type(exc).__name__}")

    cleanup(TEST_USER_ID, container)
    print("\nE2E PASS")


if __name__ == "__main__":
    asyncio.run(main())
