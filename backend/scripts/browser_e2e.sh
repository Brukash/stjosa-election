#!/usr/bin/env bash
# Boots a throwaway API and frontend, then runs the voter-flow browser test
# (accredit → mark and submit the ballot → open the receipt).
#
#   backend/scripts/browser_e2e.sh
#
# It uses its own SQLite database and key directory, so the development
# database and keys are untouched, and deletes everything it created on exit.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
PORT_API="${PORT_API:-8010}"
PORT_WEB="${PORT_WEB:-3010}"
DB="$BACKEND/browser_e2e.db"
KEYS="$BACKEND/keys_browser_e2e"
LOG_API="$BACKEND/browser_e2e_api.log"
LOG_WEB="$BACKEND/browser_e2e_web.log"
PY="$BACKEND/.venv/Scripts/python.exe"
[ -x "$PY" ] || PY="python3"

PID_API=""
PID_WEB=""

# The PID of the process actually listening on a port. The subshell that
# launches `next dev` is not the listener, so killing it leaves the server up.
listener_pid() {
  netstat -ano 2> /dev/null | grep -E ":$1[[:space:]]" | grep LISTENING | awk '{print $NF}' | head -1
}

kill_tree() {
  local pid="$1"
  [ -z "$pid" ] && return 0
  case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) taskkill //F //T //PID "$pid" > /dev/null 2>&1 ;;
    *)
      pkill -P "$pid" > /dev/null 2>&1
      kill -TERM "$pid" > /dev/null 2>&1
      sleep 1
      kill -KILL "$pid" > /dev/null 2>&1
      ;;
  esac
}

kill_port() {
  local port="$1" pid
  pid="$(listener_pid "$port")"
  [ -z "$pid" ] && return 0
  kill_tree "$pid"
  for _ in $(seq 1 15); do
    [ -z "$(listener_pid "$port")" ] && return 0
    sleep 1
  done
  echo "warning: port $port is still listening after kill"
}

cleanup() {
  kill_port "$PORT_WEB"
  kill_port "$PORT_API"
  # The API releases the SQLite file a moment after the process is killed.
  for _ in 1 2 3 4 5; do
    rm -f "$DB" "$DB-journal" "$DB-wal" "$DB-shm" 2> /dev/null && break
    sleep 1
  done
  rm -rf "$KEYS"
}
trap cleanup EXIT

wait_for() {
  local url="$1" label="$2" log="$3"
  for _ in $(seq 1 90); do
    if curl -fsS -o /dev/null --max-time 5 "$url" 2> /dev/null; then return 0; fi
    sleep 1
  done
  echo "timed out waiting for $label ($url)"
  tail -20 "$log" 2> /dev/null
  exit 1
}

for port in "$PORT_API" "$PORT_WEB"; do
  occupant="$(listener_pid "$port")"
  if [ -n "$occupant" ]; then
    echo "port $port is already in use (PID $occupant); stop it or set PORT_API/PORT_WEB"
    exit 1
  fi
done

rm -f "$DB" "$DB-journal" "$DB-wal" "$DB-shm"
rm -rf "$KEYS"

echo "starting throwaway API on :$PORT_API"
(
  cd "$BACKEND" || exit 1
  DATABASE_URL="sqlite:///./browser_e2e.db" \
  KEYS_DIR="./keys_browser_e2e" \
  DEMO_SEED=true \
  ENVIRONMENT=development \
  APP_ORIGIN="http://localhost:$PORT_WEB" \
  exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT_API" > "$LOG_API" 2>&1
) &
PID_API=$!
wait_for "http://127.0.0.1:$PORT_API/api/health" "API" "$LOG_API"

echo "starting frontend on :$PORT_WEB"
(
  cd "$FRONTEND" || exit 1
  NEXT_PUBLIC_API_URL="http://127.0.0.1:$PORT_API" exec npx next dev -p "$PORT_WEB" > "$LOG_WEB" 2>&1
) &
PID_WEB=$!
wait_for "http://localhost:$PORT_WEB/" "frontend" "$LOG_WEB"

echo "running voter flow"
FRONTEND_URL="http://localhost:$PORT_WEB" \
VOTER_ID="${VOTER_ID:-SJC/AL/2004/001}" \
SHOTS_DIR="${SHOTS_DIR:-$ROOT/screenshots/browser-e2e}" \
node "$FRONTEND/scripts/browser-voter-flow.mjs"
status=$?

exit $status
