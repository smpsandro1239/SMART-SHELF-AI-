#!/usr/bin/env bash
set -Eeuo pipefail

# Read-only preflight for the local SMART SHELF AI 10-minute demo.
# It does not start, stop, reset, seed, or modify any service or data.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

API_URL="${API_URL:-http://127.0.0.1:8000/health/ready}"
WEB_URL="${WEB_URL:-http://127.0.0.1:5173/}"

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

pass() {
  printf 'PASS: %s\n' "$*"
}

command -v docker >/dev/null 2>&1 || fail "Docker CLI não encontrado."
command -v curl >/dev/null 2>&1 || fail "curl não encontrado."
command -v grep >/dev/null 2>&1 || fail "grep não encontrado."
command -v python3 >/dev/null 2>&1 || fail "Python 3 não encontrado."

docker compose version >/dev/null 2>&1 || fail "Docker Compose plugin não está disponível."
pass "Docker Compose disponível."

docker compose config --quiet || fail "docker-compose.yml não é válido."
pass "Configuração Docker Compose válida."

running_services="$(docker compose ps --services --filter status=running)"
for service in db api vision-worker; do
  grep -Fxq "$service" <<<"$running_services" || fail "Serviço '$service' não está em execução. Consulta: docker compose ps"
  pass "Serviço '$service' em execução."
done

api_ready=false
api_payload=""
for attempt in {1..15}; do
  if api_payload="$(curl --silent --show-error --fail --max-time 3 "$API_URL" 2>/dev/null)"; then
    if python3 -c '
import json
import sys

try:
    payload = json.load(sys.stdin)
except (json.JSONDecodeError, UnicodeDecodeError):
    raise SystemExit(1)

expected = {
    "status": "ready",
    "database": "connected",
    "migrations": "current",
}
raise SystemExit(0 if all(payload.get(key) == value for key, value in expected.items()) else 1)
' <<<"$api_payload"; then
      api_ready=true
      break
    fi
  fi
  sleep 2
done
"$api_ready" || fail "API não confirmou status=ready, database=connected e migrations=current em $API_URL (limite de 30 segundos)."
pass "API pronta: PostgreSQL ligado e migrações atualizadas."

curl --silent --show-error --fail --max-time 5 "$WEB_URL" >/dev/null 2>&1 \
  || fail "Frontend não respondeu em $WEB_URL. Inicia-o em apps/web com npm run dev."
pass "Frontend responde."

if [[ ! -s "apps/api/demo/assets/synthetic-shelf.png" ]]; then
  fail "Imagem sintética não encontrada. Executa: docker compose exec api python -m app.demo.seed"
fi

docker compose exec -T api python -c '
from pathlib import Path
from PIL import Image

path = Path("/app/demo/assets/synthetic-shelf.png")
if path.is_symlink() or not path.is_file():
    raise SystemExit("Synthetic image is not a regular file")
try:
    with Image.open(path) as image:
        if image.format != "PNG" or image.size != (1200, 700):
            raise SystemExit("Synthetic image has an unexpected format or dimensions")
        image.verify()
except (OSError, ValueError) as exc:
    raise SystemExit(f"Synthetic image is corrupt: {exc}")
'
pass "Imagem sintética validada: PNG íntegro de 1200x700."

printf '\nPré-validação concluída. Isto não substitui o percurso manual com ADMIN, SUPERVISOR e EMPLOYEE.\n'
