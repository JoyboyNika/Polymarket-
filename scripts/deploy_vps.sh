#!/usr/bin/env bash
# ============================================================
# Carmin — Full VPS Deployment Script
# Target: OVH VPS (Ubuntu, 6 vCore, 12 Go RAM)
#
# Run as root (or via sudo) on the VPS:
#   sudo bash deploy_vps.sh
#
# This script does EVERYTHING:
#   1. Installs system packages
#   2. Creates carmin user
#   3. Clones code from GitHub
#   4. Creates .env with production values
#   5. Sets up Python venv + installs deps
#   6. Runs --dry-run test
#   7. Installs systemd service
# ============================================================

set -euo pipefail

REPO_URL="https://github.com/JoyboyNika/Polymarket-.git"
BRANCH="claude/create-trades-database-OF7mH"
DEPLOY_DIR="/home/carmin"
VENV="$DEPLOY_DIR/venv"

echo "========================================"
echo "  Carmin — VPS Deployment"
echo "========================================"
echo

# ── 1. System packages ────────────────────────────────────────
echo "[1/7] Installing system packages..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv git > /dev/null 2>&1
echo "  Python: $(python3 --version)"
echo "  Git:    $(git --version)"

# ── 2. Create carmin user ────────────────────────────────────
echo "[2/7] Creating carmin user..."
if id "carmin" &>/dev/null; then
    echo "  User carmin already exists"
else
    useradd -m -s /bin/bash carmin
    echo "  User carmin created"
fi

# ── 3. Clone / update code ────────────────────────────────────
echo "[3/7] Deploying code from GitHub..."
if [ -d "$DEPLOY_DIR/.git" ]; then
    echo "  Repo exists — pulling latest..."
    su - carmin -c "cd $DEPLOY_DIR && git fetch origin $BRANCH && git checkout $BRANCH && git pull origin $BRANCH"
else
    # Clone into a temp dir then move contents (user home already exists)
    TMPDIR=$(mktemp -d)
    git clone --branch "$BRANCH" --single-branch "$REPO_URL" "$TMPDIR"
    # Move everything including .git
    cp -a "$TMPDIR/." "$DEPLOY_DIR/"
    rm -rf "$TMPDIR"
    chown -R carmin:carmin "$DEPLOY_DIR"
    echo "  Code cloned to $DEPLOY_DIR"
fi

echo "  Files:"
ls -la "$DEPLOY_DIR/run.py" "$DEPLOY_DIR/ingestor/" "$DEPLOY_DIR/scorer/" 2>/dev/null | head -5

# ── 4. Create .env ────────────────────────────────────────────
echo "[4/7] Creating production .env..."
cat > "$DEPLOY_DIR/.env" << 'ENVEOF'
# ── Bloc 1 — Ingesteur ────────────────────────────────────────
POLL_INTERVAL_SECONDS=300
FILTER_AMOUNT_USDC=1000
DEDUP_WINDOW_HOURS=24
API_BASE_URL=https://data-api.polymarket.com
GAMMA_API_URL=https://gamma-api.polymarket.com

# ── Bloc 2 — Scoreur ──────────────────────────────────────────
PASS1_THRESHOLD=5
PASS2_THRESHOLD=10
MARKET_VOLUME_LOW_THRESHOLD=50000
TRADE_SIZE_RATIO_THRESHOLD=0.02
IMPROBABLE_PROBABILITY_THRESHOLD=0.10
WALLET_AGE_NEW_DAYS=7
TIMING_CLOSE_DAYS=7

# ── Bloc 2 → Bloc 3 (webhook Make) ────────────────────────────
MAKE_WEBHOOK_URL=https://hook.eu2.make.com/5l6dkp6l0le8leoo9ke3kf6owc9dt6ng

# ── Alchemy (on-chain profiling — optional) ────────────────────
# Leave empty to run in degraded mode (no on-chain wallet data)
ALCHEMY_API_KEY=
ENVEOF

chown carmin:carmin "$DEPLOY_DIR/.env"
chmod 600 "$DEPLOY_DIR/.env"
echo "  .env created (MAKE_WEBHOOK_URL set, ALCHEMY_API_KEY empty)"

# ── 5. Python venv + dependencies ─────────────────────────────
echo "[5/7] Setting up Python environment..."
su - carmin -c "
    cd $DEPLOY_DIR
    python3 -m venv venv 2>/dev/null || true
    $VENV/bin/pip install --quiet --upgrade pip
    $VENV/bin/pip install --quiet -r requirements.txt
"
echo "  Dependencies installed:"
su - carmin -c "$VENV/bin/pip list --format=columns 2>/dev/null" | grep -E "requests|dotenv|notion" || true

# ── 6. Dry-run test ───────────────────────────────────────────
echo "[6/7] Running --dry-run test..."
echo
su - carmin -c "cd $DEPLOY_DIR && $VENV/bin/python run.py --dry-run" 2>&1 || {
    echo
    echo "WARNING: --dry-run failed (might be a transient API issue)"
    echo "You can retry manually: su - carmin -c 'cd /home/carmin && venv/bin/python run.py --dry-run'"
}
echo

# ── 7. systemd service ────────────────────────────────────────
echo "[7/7] Installing systemd service..."

# Create data directory for webhook fallback
mkdir -p "$DEPLOY_DIR/data"
chown carmin:carmin "$DEPLOY_DIR/data"

# Install service file
cp "$DEPLOY_DIR/carmin.service" /etc/systemd/system/carmin.service
systemctl daemon-reload
echo "  Service installed (not started yet)"

# ── Summary ───────────────────────────────────────────────────
echo
echo "========================================"
echo "  DEPLOYMENT COMPLETE"
echo "========================================"
echo
echo "File structure:"
echo "  $DEPLOY_DIR/"
su - carmin -c "cd $DEPLOY_DIR && find . -maxdepth 2 -name '*.py' -o -name '.env' -o -name 'requirements.txt' -o -name '*.service' | sort" 2>/dev/null
echo
echo "Next steps:"
echo "  1. --dry-run should have succeeded above"
echo "  2. WAIT — tell the Interrogateur that --test-webhook is ready"
echo "     (they need to activate Make scenario ID 8668473)"
echo "  3. Then run:"
echo "     su - carmin -c 'cd /home/carmin && venv/bin/python run.py --test-webhook'"
echo "  4. After webhook test succeeds, start the service:"
echo "     systemctl enable --now carmin"
echo "  5. Monitor logs:"
echo "     journalctl -u carmin -f"
