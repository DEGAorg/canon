#!/usr/bin/env python3
"""E2E del device flow usando el approve HTTP REAL (autenticado con cookie).

A diferencia de e2e_device_flow.py (que saltaba el approve actualizando la fila
device_codes en la DB), este ejerce `POST /device/approve` de verdad:

1. POST /device/code            -> device_code + user_code (real).
2. Poll /device/token           -> pending (real).
3. Mint una sesión legítima     -> usuario en users + JWT firmado con el mismo
   jwtsecret que el backend (en el almacén local de Encore) + fila en sessions.
4. POST /device/approve         -> con cookie ai_agent_session del usuario (REAL,
   válida por auth handler + validateSession en DB).
5. Poll /device/token           -> approved + session_token (real).
6. Re-poll                       -> consumido (404).

Con eso SOLO el paso de "identidad del usuario que aprueba" se siembra (lo que
Firebase daría); el approve HTTP y la validación de sesión son 100% reales.
"""
import asyncio
import json
import os
import subprocess
import time

from toad.extensions.dega_panel.device_client import DeviceClient

API = os.environ.get("DEGA_API_URL", "http://127.0.0.1:4000")
TEST_USER_ID = "e2e00000-0000-0000-0000-00000000e2e3"
TEST_EMAIL = "e2e-approve@dega.org"

# ruta al almacén de secretos de Encore para este proyecto app id "ai-agents-4eg2"
SECRETS = os.path.expanduser("~/.cache/encore/secrets/ai-agents-4eg2.json")
BACKEND = os.path.expanduser("~/projects/DEGA/dega_agents_fe/backend")


def find_pg_container():
    out = subprocess.run(["docker", "ps", "--format", "{{.Names}}"],
                         capture_output=True, text=True).stdout
    for name in out.splitlines():
        if name.startswith("sqldb-ai-agents-4eg2"):
            return name
    raise SystemExit("no Encore postgres container found")


def psql(container, sql):
    subprocess.run(["docker", "exec", container, "psql", "-U", "postgres",
                    "-d", "agents_core", "-c", sql], check=True,
                   capture_output=True, text=True)


def get_jwt_secret():
    d = json.load(open(SECRETS))
    jwt_sec = d["Values"].get("jwtsecret")
    if not jwt_sec:
        raise SystemExit(f"jwtsecret no está en {SECRETS}")
    return jwt_sec


def mint_session_token(user_id, secret):
    """Firma un JWT igual que createSessionToken (claim userId, HS256, 24h)."""
    import hmac, hashlib, base64
    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).rstrip(b"=")
    payload = base64.urlsafe_b64encode(json.dumps({"userId": user_id,
                                                   "iat": int(time.time()),
                                                   "exp": int(time.time()) + 86400}).encode()).rstrip(b"=")
    signing = header + b"." + payload
    sig = base64.urlsafe_b64encode(hmac.new(secret.encode(), signing, hashlib.sha256).digest()).rstrip(b"=")
    return (signing + b"." + sig).decode()


async def request_device_code(client):
    code = await client.request_code()
    return code


def approve_via_http(user_code, cookie):
    """POST /device/approve real con cookie."""
    import urllib.request
    import urllib.error
    req = urllib.request.Request(
        f"{API}/device/approve",
        data=json.dumps({"user_code": user_code}).encode(),
        headers={"Content-Type": "application/json",
                 "Cookie": f"ai_agent_session={cookie}"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


async def token_status(device_code):
    """POST /device/token directo para inspeccionar el estado (no espera)."""
    import httpx
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{API}/device/token", json={"device_code": device_code})
        return r.status_code, (r.json() if r.content else {})


async def main():
    container = find_pg_container()
    secret = get_jwt_secret()
    # limpiar previos
    for table, col in (("sessions", "user_id"), ("device_codes", "user_id"), ("users", "id")):
        psql(container, f"DELETE FROM {table} WHERE {col}='{TEST_USER_ID}';")
    # 1. usuario de prueba
    psql(container, f"INSERT INTO users (id, provider, provider_id, email, display_name) "
                    f"VALUES ('{TEST_USER_ID}','firebase','e2e-uid','{TEST_EMAIL}','E2E') "
                    f"ON CONFLICT (id) DO NOTHING;")
    # 2. sesión legítima: JWT + fila en sessions
    tok = mint_session_token(TEST_USER_ID, secret)
    psql(container, f"INSERT INTO sessions (user_id, token, is_valid, expires_at) "
                    f"VALUES ('{TEST_USER_ID}','{tok}', true, now() + interval '24 hours');")
    cookie = tok

    client = DeviceClient(base_url=API)
    print(f"1. POST /device/code via DeviceClient ({API})")
    code = await client.request_code()
    device_code = code["device_code"]; user_code = code["user_code"]
    print(f"   user_code={user_code} device_code={device_code[:8]}...")

    print("2. POST /device/token antes de aprobar (espera pending)")
    sc, st = await token_status(device_code)
    print(f"   -> HTTP {sc} status={st.get('status')}")
    if st.get("status") != "pending":
        raise SystemExit(f"esperaba pending, obtuve {st.get('status')}")

    print("3. POST /device/approve REAL con cookie de sesión del usuario")
    asc, body = approve_via_http(user_code, cookie)
    print(f"   -> HTTP {asc} body={body[:120]}")
    if asc != 200:
        raise SystemExit(f"approve falló: {asc}")

    print("4. POST /device/token tras aprobar (espera approved + session)")
    sc2, st2 = await token_status(device_code)
    print(f"   -> HTTP {sc2} status={st2.get('status')} has_token={'session_token' in st2}")

    print("5. Re-poll: el code debe estar consumido (404)")
    sc3, _ = await token_status(device_code)
    print(f"   -> HTTP {sc3}")
    if sc3 != 404:
        raise SystemExit(f"esperaba 404 (consumido), obtuve {sc3}")

    # limpiar
    for table, col in (("sessions", "user_id"), ("device_codes", "user_id"), ("users", "id")):
        psql(container, f"DELETE FROM {table} WHERE {col}='{TEST_USER_ID}';")
    print("\nE2E-DEVICE-APPROVE-REAL PASS")


if __name__ == "__main__":
    asyncio.run(main())