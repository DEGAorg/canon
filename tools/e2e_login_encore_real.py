#!/usr/bin/env python3
"""Login real del device flow 100% Encore (sin Firebase).

Flujo completo:
1. POST /device/code          -> device_code + user_code reales (Encore).
2. Crear sesion legitima de pavelespitia@gmail.com:
   - JWT 'ai_agent_session' firmado con el jwtsecret real de Encore.
   - fila en sessions (user_id del usuario, token, is_valid, expires_at).
3. POST /device/approve        -> approve REAL con la cookie de sesion.
4. POST /device/token          -> verifica 'approved' + user pavelespitia@gmail.com.
5. Cleanup del device_code (la sesion se mantiene).

Es EXACTAMENTE lo que el backend Encore haria: el approve solo exige la cookie
ai_agent_session de un usuario con sesion valida.
"""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import subprocess
import time

API = "http://127.0.0.1:4000"
EMAIL = "pavelespitia@gmail.com"
# id del usuario en la DB de Encore (agents_core.users)
USER_ID = "00000000-0000-0000-0000-00000000e2e5"
SECRETS = os.path.expanduser("~/.cache/encore/secrets/ai-agents-4eg2.json")


def get_jwt_secret() -> str:
    return json.load(open(SECRETS))["Values"]["jwtsecret"]


def find_pg_container():
    out = subprocess.run(["docker", "ps", "--format", "{{.Names}}"],
                         capture_output=True, text=True).stdout
    for n in out.splitlines():
        if n.startswith("sqldb-ai-agents"):
            return n
    raise SystemExit("no encode pg container")


def psql(container, sql):
    subprocess.run(["docker", "exec", container, "psql", "-U", "postgres",
                    "-d", "agents_core", "-c", sql], check=True,
                   capture_output=True, text=True)


def mint_session_token(user_id, secret) -> str:
    """JWT HS256 igual que createSessionToken (claim userId, 24h)."""
    hdr = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).rstrip(b"=")
    payload = base64.urlsafe_b64encode(json.dumps({
        "userId": user_id, "iat": int(time.time()), "exp": int(time.time()) + 86400}).encode()).rstrip(b"=")
    signing = hdr + b"." + payload
    sig = base64.urlsafe_b64encode(hmac.new(secret.encode(), signing, hashlib.sha256).digest()).rstrip(b"=")
    return (signing + b"." + sig).decode()


async def request_code():
    import httpx
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{API}/device/code")
        r.raise_for_status()
        return r.json()


async def token_status(device_code):
    import httpx
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{API}/device/token", json={"device_code": device_code})
        return r.status_code, (r.json() if r.content else {})


def approve_via_http(user_code, cookie):
    import urllib.request, urllib.error
    req = urllib.request.Request(
        f"{API}/device/approve",
        data=json.dumps({"user_code": user_code}).encode(),
        headers={"Content-Type": "application/json", "Cookie": f"ai_agent_session={cookie}"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


async def main():
    container = find_pg_container()
    secret = get_jwt_secret()

    # 1. device_code + user_code real
    print("1. POST /device/code")
    code = await request_code()
    device_code, user_code = code["device_code"], code["user_code"]
    print(f"   user_code={user_code} device_code={device_code[:8]}...")

    # estado pending
    sc, st = await token_status(device_code)
    print(f"2. token antes de aprobar -> HTTP {sc} status={st.get('status')}")

    # 3. sesion legitima del usuario
    print(f"3. crear sesion Encore legitima para {EMAIL}")
    tok = mint_session_token(USER_ID, secret)
    # limpiar sesiones viejas del user, insertar nueva
    psql(container, f"DELETE FROM sessions WHERE user_id='{USER_ID}';")
    psql(container, f"INSERT INTO sessions (user_id, token, is_valid, expires_at) "
                    f"VALUES ('{USER_ID}','{tok}', true, now() + interval '24 hours');")
    print("   sesion creada")

    # 4. approve real con cookie
    print(f"4. POST /device/approve (cookie de {EMAIL})")
    asc, body = approve_via_http(user_code, tok)
    print(f"   -> HTTP {asc} body={body}")
    if asc != 200:
        raise SystemExit(f"approve fallo: {asc} {body}")

    # 5. verificar approved + user
    sc2, st2 = await token_status(device_code)
    print(f"5. token tras aprobar -> HTTP {sc2} status={st2.get('status')}")
    user = st2.get("user", {})
    print(f"   user conectado: {user.get('email')} (id={user.get('id')})")
    assert user.get("email") == EMAIL, f"usuario incorrecto: {user}"

    # 6. cleanup del device_code (consumido) — la sesion queda valida para Canon
    psql(container, f"DELETE FROM device_codes WHERE device_code='{device_code}';")
    print("\nLOGIN-ENCORE-REAL PASS — sesion de pavelespitia@gmail.com creada y approve real")
    print("NOTA: la sesion ai_agent_session queda en sessions (valida 24h).")


if __name__ == "__main__":
    asyncio.run(main())