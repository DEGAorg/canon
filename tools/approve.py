"""Approve a Canon device-code row by the visible USER_CODE (XXXX-XXXX), simulating the /device approve step without Firebase.

Usage: python tools/approve_code.py <USER_CODE>
"""
import subprocess
import sys

def find_pg_container():
    out = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True).stdout
    for name in out.splitlines():
        if name.startswith("sqldb-ai-agents-4eg2"):
            return name
    raise SystemExit("no Encore postgres container found")

def main():
    user_code = (sys.argv[1] if len(sys.argv) > 1 else "").strip().upper().replace("-", "")
    if not user_code:
        raise SystemExit("usage: python3 approve.py <USER_CODE>")
    container = find_pg_container()
    # ensure the e2e user exists (mirrors e2e_device_flow.py insert_user)
    subprocess.run(
        ["docker", "exec", container, "psql", "-U", "postgres", "-d", "agents_core", "-c",
         "INSERT INTO users (id, provider, provider_id, email, display_name) "
         "VALUES ('e2e00000-0000-0000-0000-00000000e2e2','firebase','e2e-uid','e2e-test@dega.org','E2E') "
         "ON CONFLICT (id) DO NOTHING;"],
        check=True)
    # find+update in one shot: normalize stored user_code (no dash) and match.
    sql = (
        "UPDATE device_codes SET status='approved', user_id='e2e00000-0000-0000-0000-00000000e2e2', "
        f"approved_at=now() WHERE replace(user_code,'-','')='{user_code}' AND status='pending' RETURNING device_code, user_code;"
    )
    r = subprocess.run(["docker", "exec", container, "psql", "-U", "postgres", "-d", "agents_core", "-c", sql], capture_output=True, text=True)
    print(r.stdout)
    if r.returncode or "approved" not in r.stdout:
        print("No pending code matched. Is the TUI showing a fresh code (l/log in -> device) and unpolled?")
        sys.exit(1)
    print(f"Approved {user_code}")

if __name__ == "__main__":
    main()