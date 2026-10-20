#!/usr/bin/env bash
# Reusable developer worktrees: scripts/pool.sh acquire <1|2|3> <branch> | release <1|2|3> | status
# Pool lives next to the repo: ../smc-scanner-pool/developerN, parked on pool/developerN.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
POOL="$ROOT/../smc-scanner-pool"
BASE="${POOL_BASE:-main}"

slot() { echo "$POOL/developer$1"; }

case "${1:-}" in
status)
  for n in 1 2 3; do
    d="$(slot "$n")"
    echo "developer$n: $(git -C "$d" branch --show-current) dirty=$(git -C "$d" status --porcelain | wc -l)"
  done ;;
acquire)
  n="${2:?slot}"; branch="${3:?branch}"; d="$(slot "$n")"
  [ "$(git -C "$d" branch --show-current)" = "pool/developer$n" ] || { echo "developer$n is in use"; exit 1; }
  [ -z "$(git -C "$d" status --porcelain)" ] || { echo "developer$n is dirty"; exit 1; }
  git -C "$d" switch -q -c "$branch" "$BASE"
  (cd "$d" && uv sync --locked -q)
  echo "developer$n ready on $branch: $d" ;;
release)
  n="${2:?slot}"; d="$(slot "$n")"; cur="$(git -C "$d" branch --show-current)"
  [ "$cur" != "pool/developer$n" ] || { echo "developer$n is already free"; exit 0; }
  git -C "$ROOT" branch --merged "$BASE" | grep -qx "[ *+]*$cur" || { echo "$cur is not merged into $BASE"; exit 1; }
  git -C "$d" switch -q -C "pool/developer$n" "$BASE"
  git -C "$d" branch -d "$cur"
  git -C "$d" clean -fdxq -e .venv -e .env
  echo "developer$n released" ;;
*) echo "usage: $0 status | acquire <1|2|3> <branch> | release <1|2|3>"; exit 2 ;;
esac
