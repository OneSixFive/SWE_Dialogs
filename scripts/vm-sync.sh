#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/vm-sync.sh [options]

Fast-forward pulls origin on the VM and checks backend health.

Options:
  --backend-tests       Run backend pytest on the VM after pulling.
  --restart-backend    Restart svenska-api.service after pulling.
  --no-health          Skip local VM backend health check.
  --host HOST          SSH host or alias. Default: ibtrading-codex.
  --remote-dir DIR     Remote repo path. Default: /home/dima/Svenska_new.
  -h, --help           Show this help.
USAGE
}

host="ibtrading-codex"
remote_dir="/home/dima/Svenska_new"
run_backend_tests=0
restart_backend=0
check_health=1

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --backend-tests)
      run_backend_tests=1
      shift
      ;;
    --restart-backend)
      restart_backend=1
      shift
      ;;
    --no-health)
      check_health=0
      shift
      ;;
    --host)
      host="${2:?--host requires a value}"
      shift 2
      ;;
    --remote-dir)
      remote_dir="${2:?--remote-dir requires a value}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

ssh "$host" \
  "REMOTE_DIR='$remote_dir' RUN_BACKEND_TESTS='$run_backend_tests' RESTART_BACKEND='$restart_backend' CHECK_HEALTH='$check_health' bash -s" <<'REMOTE_SCRIPT'
set -euo pipefail

cd "$REMOTE_DIR"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Remote worktree is dirty; refusing to pull. Resolve or commit remote changes first." >&2
  git status --short
  exit 1
fi

git pull --ff-only

if [[ "$RUN_BACKEND_TESTS" == "1" ]]; then
  (
    cd backend
    PYTHONPATH=. .venv/bin/pytest -q tests
  )
fi

if [[ "$RESTART_BACKEND" == "1" ]]; then
  if sudo -n true 2>/dev/null; then
    sudo -n systemctl restart svenska-api.service
  else
    systemctl restart svenska-api.service
  fi
  sleep 1
fi

if [[ "$CHECK_HEALTH" == "1" ]]; then
  curl -fsS http://127.0.0.1:8100/health
  printf '\n'
fi

git status --short --branch
git rev-parse HEAD
REMOTE_SCRIPT
