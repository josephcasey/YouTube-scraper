#!/usr/bin/env bash
#
# Install the YouTube transcript proxy as an always-on launchd service on macOS.
# Idempotent: re-run to update. Reads the repo location from this script's path.
#
# Usage:
#   ./mac_service/install-macos.sh          # install + start
#   ./mac_service/install-macos.sh uninstall
#
set -euo pipefail

LABEL="com.youtube-proxy"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
PYTHON="$(command -v python3)"
LOG_DIR="$HOME/Library/Logs/youtube-proxy"

if [[ "${1:-}" == "uninstall" ]]; then
  launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Uninstalled ${LABEL}."
  exit 0
fi

# Require a token before installing — the service refuses to run without one.
if [[ -z "${YOUTUBE_PROXY_TOKEN:-}" && ! -f "$REPO_DIR/mac_service/.token" ]]; then
  echo "ERROR: no token found."
  echo "  Write one with:  echo 'YOUR_TOKEN' > '$REPO_DIR/mac_service/.token'"
  echo "  (that file is gitignored). Then re-run this installer."
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"

cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON}</string>
    <string>-m</string>
    <string>mac_service.server</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${REPO_DIR}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONPATH</key>
    <string>${REPO_DIR}</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/out.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/err.log</string>
</dict>
</plist>
PLIST_EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo "Installed and started ${LABEL}."
echo "  Logs:   $LOG_DIR/{out,err}.log"
echo "  Verify: curl -s http://127.0.0.1:8787/health"
echo "  Expose: tailscale funnel --bg 8787   (public)  OR  tailscale serve --bg 8787  (tailnet-only)"
