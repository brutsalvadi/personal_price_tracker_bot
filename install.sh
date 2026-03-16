#!/usr/bin/env bash
#
# First-time installation — run this directly on the server:
#
#   cd ~/src/price_tracking
#   bash install.sh
#
# Requires sudo for: apt packages (Playwright deps) + systemd service.
#
# PREREQUISITE — before running this script, create the sudoers file:
#
#   sudo visudo -f /etc/sudoers.d/price-tracker
#
# Paste this single line (replace USER with your username):
#   USER ALL=(ALL) NOPASSWD: /bin/cp /home/USER/src/price_tracking/deploy/price-tracker.service /etc/systemd/system/, /bin/systemctl daemon-reload, /bin/systemctl enable price-tracker, /bin/systemctl start price-tracker, /bin/systemctl stop price-tracker, /bin/systemctl restart price-tracker, /bin/systemctl status price-tracker *
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="price-tracker"
SERVICE_FILE="${SCRIPT_DIR}/deploy/${SERVICE_NAME}.service"

# Ensure PATH includes ~/.local/bin (uv lives there)
export PATH="$HOME/.local/bin:$PATH"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}==>${NC} $1"; }
warn() { echo -e "${YELLOW}==>${NC} $1"; }

# ─── Checks ──────────────────────────────────────────────────────────────────
if [[ ! -f "${SCRIPT_DIR}/pyproject.toml" ]]; then
    echo "ERROR: run this script from the price_tracking project directory."
    exit 1
fi

# ─── uv ──────────────────────────────────────────────────────────────────────
if ! command -v uv >/dev/null 2>&1; then
    log "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
else
    log "uv already installed ($(uv --version))"
fi

# ─── Python dependencies ─────────────────────────────────────────────────────
log "Installing Python dependencies..."
cd "${SCRIPT_DIR}"
uv sync

# ─── Chromium (system package) ───────────────────────────────────────────────
log "Installing Chromium via apt..."
sudo apt-get install -y chromium-browser

# ─── .env ────────────────────────────────────────────────────────────────────
if [[ ! -f "${SCRIPT_DIR}/.env" ]]; then
    cp "${SCRIPT_DIR}/.env.example" "${SCRIPT_DIR}/.env"
    warn ".env created from .env.example — fill in your credentials before starting the service:"
    warn "  nano ${SCRIPT_DIR}/.env"
else
    log ".env already exists, leaving it untouched"
fi

# ─── systemd service ─────────────────────────────────────────────────────────
log "Installing systemd service..."
sudo cp "${SERVICE_FILE}" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"

# ─── Done ────────────────────────────────────────────────────────────────────
echo ""
log "Installation complete!"
warn "Next steps:"
warn "  1. Fill in credentials:  nano ${SCRIPT_DIR}/.env"
warn "  2. Edit tracked targets: nano ${SCRIPT_DIR}/targets.yaml"
warn "  3. Start the service:    sudo systemctl start ${SERVICE_NAME}"
warn "  4. Follow logs:          sudo journalctl -u ${SERVICE_NAME} -f"
