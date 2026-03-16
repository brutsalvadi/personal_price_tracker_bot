#!/usr/bin/env bash
#
# Publish a sanitized snapshot to the public GitHub repo.
# Squashes all history into a single commit on a fresh orphan branch.
#
# Usage:  ./publish.sh
#

set -euo pipefail

REMOTE="github-public"
BRANCH="main"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"
PUBLISH_DIR="${LOCAL_DIR}/publish"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'
log()  { echo -e "${GREEN}==>${NC} $1"; }
warn() { echo -e "${YELLOW}==>${NC} $1"; }

# ─── Sanity checks ───────────────────────────────────────────────────────────
if ! git -C "$LOCAL_DIR" remote get-url "$REMOTE" &>/dev/null; then
    echo "ERROR: remote '${REMOTE}' not found."
    echo "Add it with:"
    echo "  git remote add ${REMOTE} git@github.com:brutsalvadi/personal_price_tracker_bot.git"
    exit 1
fi

if [[ -n "$(git -C "$LOCAL_DIR" status --porcelain)" ]]; then
    echo "ERROR: uncommitted changes in working tree. Commit or stash first."
    exit 1
fi

log "Creating orphan branch..."
git checkout --orphan _public_tmp

# ─── Sanitize ────────────────────────────────────────────────────────────────
log "Applying sanitized overrides..."

# Remove files that should not be public
rm -f CLAUDE.md

# Replace with sanitized templates
cp "${PUBLISH_DIR}/targets.yaml" targets.yaml
cp "${PUBLISH_DIR}/deploy.sh"   deploy.sh
cp "${PUBLISH_DIR}/install.sh"  install.sh

# Make sure data/ and publish internals are not committed
grep -qxF 'data/'       .gitignore || echo 'data/'       >> .gitignore
grep -qxF 'publish/'    .gitignore || echo 'publish/'    >> .gitignore
grep -qxF 'publish.sh'  .gitignore || echo 'publish.sh'  >> .gitignore

# ─── Commit & push ───────────────────────────────────────────────────────────
log "Staging files..."
git add -A

log "Committing..."
git commit -m "Initial release"

log "Force-pushing to ${REMOTE}/${BRANCH}..."
git push --force "$REMOTE" "HEAD:${BRANCH}"

# ─── Cleanup ─────────────────────────────────────────────────────────────────
log "Cleaning up..."
git checkout main
git branch -D _public_tmp

log "Done! Published to https://github.com/brutsalvadi/personal_price_tracker_bot"
