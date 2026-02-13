#!/usr/bin/env bash
# Carmin VPS Setup Script
# Target: OVH Starter (Ubuntu 22.04+, 1 vCPU, 2 Go RAM)
#
# Usage:
#   ssh root@your-vps 'bash -s' < scripts/setup_vps.sh
#
# Or copy to VPS and run:
#   chmod +x setup_vps.sh && sudo ./setup_vps.sh

set -euo pipefail

echo "========================================"
echo "Carmin — VPS Setup"
echo "========================================"
echo

# ── 1. System packages ────────────────────────────────────────
echo "[1/6] Installing system packages..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv git > /dev/null
echo "  Python: $(python3 --version)"

# ── 2. Create user ────────────────────────────────────────────
echo "[2/6] Creating carmin user..."
if id "carmin" &>/dev/null; then
    echo "  User carmin already exists"
else
    useradd -m -s /bin/bash carmin
    echo "  User carmin created"
fi

# ── 3. Clone / update code ────────────────────────────────────
echo "[3/6] Deploying code..."
DEPLOY_DIR="/home/carmin"

# Copy project files (run from repo root or adjust paths)
for dir in ingestor scorer notion_db; do
    if [ -d "$dir" ]; then
        cp -r "$dir" "$DEPLOY_DIR/"
    fi
done

for file in run.py requirements.txt .env.example; do
    if [ -f "$file" ]; then
        cp "$file" "$DEPLOY_DIR/"
    fi
done

chown -R carmin:carmin "$DEPLOY_DIR"
echo "  Code deployed to $DEPLOY_DIR"

# ── 4. Python venv + dependencies ─────────────────────────────
echo "[4/6] Setting up Python virtual environment..."
su - carmin -c "
    cd /home/carmin
    python3 -m venv venv
    source venv/bin/activate
    pip install --quiet --upgrade pip
    pip install --quiet -r requirements.txt
"
echo "  Dependencies installed"

# ── 5. .env file ──────────────────────────────────────────────
echo "[5/6] Checking .env..."
if [ -f "$DEPLOY_DIR/.env" ]; then
    echo "  .env already exists — not overwriting"
else
    cp "$DEPLOY_DIR/.env.example" "$DEPLOY_DIR/.env"
    chown carmin:carmin "$DEPLOY_DIR/.env"
    chmod 600 "$DEPLOY_DIR/.env"
    echo "  .env created from .env.example — EDIT IT with your keys!"
fi

# ── 6. systemd service ────────────────────────────────────────
echo "[6/6] Installing systemd service..."
if [ -f "carmin.service" ]; then
    cp carmin.service /etc/systemd/system/carmin.service
elif [ -f "$DEPLOY_DIR/carmin.service" ]; then
    cp "$DEPLOY_DIR/carmin.service" /etc/systemd/system/carmin.service
fi

# Create data directory for webhook fallback
mkdir -p "$DEPLOY_DIR/data"
chown carmin:carmin "$DEPLOY_DIR/data"

systemctl daemon-reload
echo "  Service installed (not started)"

echo
echo "========================================"
echo "Setup complete!"
echo "========================================"
echo
echo "Next steps:"
echo "  1. Edit /home/carmin/.env with your API keys"
echo "  2. Test:  su - carmin -c 'cd /home/carmin && venv/bin/python run.py --dry-run'"
echo "  3. Test:  su - carmin -c 'cd /home/carmin && venv/bin/python run.py --test-webhook'"
echo "  4. Start: systemctl enable --now carmin"
echo "  5. Logs:  journalctl -u carmin -f"
