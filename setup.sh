#!/usr/bin/env bash
# ─────────────────────────────────────────────
#  Nimbus — One-command setup
#  Usage: chmod +x setup.sh && ./setup.sh
# ─────────────────────────────────────────────

set -e

GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${CYAN}[NIMBUS]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC}     $1"; }

NIMBUS_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$NIMBUS_DIR/.venv"
SERVICE_NAME="nimbus"

info "Setting up Nimbus from $NIMBUS_DIR"

# 1. Python venv
if [[ ! -d "$VENV_DIR" ]]; then
    python3 -m venv "$VENV_DIR"
    success "Virtual environment created"
else
    success "Virtual environment exists"
fi

"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -r "$NIMBUS_DIR/requirements.txt"
success "Dependencies installed"

# 2. Check config
if [[ ! -f "$NIMBUS_DIR/config.yaml" ]]; then
    echo ""
    info "No config.yaml found. Copy config.example.yaml and fill in your values:"
    info "  cp config.example.yaml config.yaml"
    exit 1
fi
success "Config found"

# 3. Create data directories
mkdir -p ~/.nimbus
mkdir -p ~/automation/.nimbus-uploads
success "Data directories ready"

# 4. Stop old dispatch bot if running
if systemctl --user is-active dispatch-bot &>/dev/null; then
    systemctl --user stop dispatch-bot
    systemctl --user disable dispatch-bot
    success "Old dispatch-bot stopped and disabled"
fi

# 5. Create systemd service
mkdir -p "$HOME/.config/systemd/user"

cat > "$HOME/.config/systemd/user/${SERVICE_NAME}.service" << EOF
[Unit]
Description=Nimbus — Mobile AI Agent Command Center
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=${VENV_DIR}/bin/python3 -m nimbus --config ${NIMBUS_DIR}/config.yaml
Restart=always
RestartSec=10
WorkingDirectory=${NIMBUS_DIR}
Environment=PYTHONPATH=${NIMBUS_DIR}

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable "$SERVICE_NAME"
systemctl --user start "$SERVICE_NAME"
success "Systemd service created and started"

# 6. Enable linger for reboot survival
loginctl enable-linger "$(whoami)" 2>/dev/null || true
success "Linger enabled — survives reboot"

echo ""
echo -e "${BOLD}${GREEN}Nimbus is live!${NC}"
echo ""
echo -e "  Status:  ${CYAN}systemctl --user status nimbus${NC}"
echo -e "  Logs:    ${CYAN}journalctl --user -u nimbus -f${NC}"
echo -e "  Restart: ${CYAN}systemctl --user restart nimbus${NC}"
echo ""
echo -e "  Open Telegram and message your bot!"
echo ""
