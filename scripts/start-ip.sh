#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$PROJECT_DIR/.env"

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  printf 'Docker Engine with Docker Compose v2 is required.\n' >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  printf 'Python 3 is required to generate protected runtime values.\n' >&2
  exit 1
fi

public_ip="${IGORAGENT_PUBLIC_IP:-}"
if [[ -z "$public_ip" ]] && command -v curl >/dev/null 2>&1; then
  public_ip="$(curl -4fsS --connect-timeout 5 --max-time 10 https://api.ipify.org || true)"
fi

if [[ -z "$public_ip" ]]; then
  printf 'Could not determine a public IPv4 address automatically. Run: IGORAGENT_PUBLIC_IP=<server-ip> ./scripts/start-ip.sh\n' >&2
  exit 1
fi

if ! python3 - "$public_ip" <<'PY'
import ipaddress
import sys

try:
    address = ipaddress.ip_address(sys.argv[1])
except ValueError:
    raise SystemExit(1)
raise SystemExit(0 if address.version == 4 and address.is_global else 1)
PY
then
  printf 'Detected address is not a public IPv4 address: %s\n' "$public_ip" >&2
  printf 'Run with the server public address: IGORAGENT_PUBLIC_IP=<server-ip> ./scripts/start-ip.sh\n' >&2
  exit 1
fi

printf 'Public dashboard address: http://%s\n' "$public_ip"

setup_token="$(python3 - "$ENV_FILE" "$public_ip" <<'PY'
from pathlib import Path
import re
import secrets
import sys

path = Path(sys.argv[1])
public_ip = sys.argv[2]
values = {}
if path.exists():
    for line in path.read_text().splitlines():
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)", line)
        if match:
            values[match.group(1)] = match.group(2)

db_password = values.get("POSTGRES_PASSWORD") or secrets.token_urlsafe(32)
setup_token = values.get("IGORAGENT_SETUP_TOKEN") or secrets.token_urlsafe(32)
values.update({
    "POSTGRES_PASSWORD": db_password,
    "DATABASE_URL": f"postgresql+psycopg://igoragent:{db_password}@postgres:5432/igoragent",
    "REDIS_URL": "redis://redis:6379/0",
    "IGORAGENT_LOCAL_MODE": "false",
    "IGORAGENT_COOKIE_SECURE": "false",
    "IGORAGENT_SETUP_TOKEN": setup_token,
    "IGORAGENT_PUBLIC_IP": public_ip,
    "NEXT_PUBLIC_API_URL": "/api",
})
order = [
    "POSTGRES_PASSWORD",
    "DATABASE_URL",
    "REDIS_URL",
    "IGORAGENT_LOCAL_MODE",
    "IGORAGENT_COOKIE_SECURE",
    "IGORAGENT_SETUP_TOKEN",
    "IGORAGENT_PUBLIC_IP",
    "NEXT_PUBLIC_API_URL",
]
remaining = sorted(key for key in values if key not in order)
path.write_text("\n".join(f"{key}={values[key]}" for key in [*order, *remaining]) + "\n")
path.chmod(0o600)
print(setup_token)
PY
)"

cd "$PROJECT_DIR"
docker compose --env-file "$ENV_FILE" -f infra/docker-compose.ip.yml up --build -d
printf '\nOpen this one-time setup link and continue setup in the dashboard:\nhttp://%s/#setup-token=%s\n' "$public_ip" "$setup_token"
printf 'The token stays after #, so the browser does not send it to Caddy or the API. Treat this link like a password.\n'
printf 'This IP mode uses plain HTTP. Use it only from a trusted network; use the domain deployment for public TLS.\n'
printf 'Later visits use http://%s without the token.\n' "$public_ip"
