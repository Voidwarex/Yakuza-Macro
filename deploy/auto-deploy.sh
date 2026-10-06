#!/usr/bin/env bash
#
# Checks GitHub for new commits on the deploy branch and, if there are any,
# pulls them and runs deploy.sh. Safe to run on a timer — it does nothing
# when already up to date. Run as root (deploy.sh needs it).
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BRANCH="${BRANCH:-main}"

cd "$REPO_DIR"
git fetch --quiet origin "$BRANCH"

LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse "origin/$BRANCH")"

if [ "$LOCAL" = "$REMOTE" ]; then
    exit 0   # nothing new — stay quiet
fi

echo "$(date -u '+%Y-%m-%d %H:%M:%SZ')  New commit $(git rev-parse --short "$REMOTE") on $BRANCH — deploying."
# Match the remote exactly (the server isn't edited by hand).
git reset --hard "origin/$BRANCH"
bash "$REPO_DIR/deploy/deploy.sh"
echo "$(date -u '+%Y-%m-%d %H:%M:%SZ')  Deploy complete."
