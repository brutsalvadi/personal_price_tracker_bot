#!/usr/bin/env bash
#
# Deploy the price-tracker daemon to your server.
# Edit REMOTE and REMOTE_DIR below before first use.
#
# Usage:
#   ./deploy.sh             # Pull remote targets.yaml, sync code, restart service
#   ./deploy.sh --overwrite # Push local targets.yaml as-is (skip remote pull)
#   ./deploy.sh --setup     # First-time setup (push code, then run install.sh on server)
#

set -euo pipefail

REMOTE="user@yourserver.example.com"
REMOTE_DIR="/home/user/src/price_tracking"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="price-tracker"
OVERWRITE=false

# Prefix PATH for non-interactive SSH (uv installs to ~/.local/bin)
REMOTE_PATH="export PATH=\$HOME/.local/bin:\$PATH"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}==>${NC} $1"; }
warn() { echo -e "${YELLOW}==>${NC} $1"; }

# ─── First-time setup (code push only) ──────────────────────────────────────
setup() {
    log "Pushing code to ${REMOTE}..."
    ssh "$REMOTE" "mkdir -p ${REMOTE_DIR}"
    do_sync

    log "Code pushed!"
    warn "Now SSH in and run install.sh to complete the setup:"
    warn "  ssh ${REMOTE}"
    warn "  bash ${REMOTE_DIR}/install.sh"
}

# ─── File sync ───────────────────────────────────────────────────────────────
do_sync() {
    if [[ "${OVERWRITE}" == true ]]; then
        warn "Overwrite mode: pushing local targets.yaml without pulling remote"
    elif ssh "$REMOTE" "test -f ${REMOTE_DIR}/targets.yaml"; then
        log "Pulling targets.yaml from remote..."
        scp -q "${REMOTE}:${REMOTE_DIR}/targets.yaml" "${LOCAL_DIR}/targets.yaml"
    fi

    log "Syncing code..."
    rsync -avz --delete \
        --exclude '.venv/' \
        --exclude 'venv/' \
        --exclude '__pycache__/' \
        --exclude '.env' \
        --exclude 'data/' \
        --exclude '.git/' \
        --exclude '*.pyc' \
        --exclude '*.egg-info/' \
        --exclude '.claude/' \
        "${LOCAL_DIR}/" "${REMOTE}:${REMOTE_DIR}/"
}

# ─── Standard deploy ─────────────────────────────────────────────────────────
deploy() {
    do_sync

    log "Restarting service..."
    ssh "$REMOTE" "${REMOTE_PATH} && cd ${REMOTE_DIR} && uv sync --quiet && sudo systemctl restart ${SERVICE_NAME}"

    sleep 2
    log "Service status:"
    ssh "$REMOTE" "sudo systemctl status ${SERVICE_NAME} --no-pager -l" || true

    log "Deploy complete!"
}

# ─── Main ────────────────────────────────────────────────────────────────────
case "${1:-}" in
    --setup)
        setup
        ;;
    --overwrite)
        OVERWRITE=true
        deploy
        ;;
    *)
        deploy
        ;;
esac
