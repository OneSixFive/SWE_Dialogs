#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/git-commit-push.sh "Commit message"

Commits currently staged changes, runs git diff --check on the staged patch,
and pushes the current branch to origin. It does not stage files for you.
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ "$#" -lt 1 ]]; then
  usage >&2
  exit 2
fi

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

branch="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$branch" == "HEAD" ]]; then
  echo "Refusing to push from a detached HEAD." >&2
  exit 1
fi

if git diff --cached --quiet; then
  echo "No staged changes to commit." >&2
  exit 1
fi

git diff --check --cached
git status --short
git commit -m "$*"
git push origin "$branch"
git status --short --branch
