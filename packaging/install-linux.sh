#!/usr/bin/env sh
# NET Sniffer — install as an always-on headless service (Raspberry Pi / Linux home server).
#   curl -fsSL https://raw.githubusercontent.com/crazyramirez/NET-Sniffer/main/packaging/install-linux.sh | sudo sh
# Then open http://<this-device-ip>:8765 from your phone or PC.
set -eu
REPO="${NETSNIFFER_REPO:-crazyramirez/NET-Sniffer}"
DIR=/opt/netsniffer
USER_NAME=netsniffer

case "$(uname -m)" in
  aarch64|arm64) ARCH=arm64 ;;
  x86_64|amd64) ARCH=x64 ;;
  *) echo "Unsupported architecture: $(uname -m) (64-bit Raspberry Pi OS / Linux required)"; exit 1 ;;
esac
[ "$(id -u)" -eq 0 ] || { echo "Run with sudo"; exit 1; }

id "$USER_NAME" >/dev/null 2>&1 || useradd --system --home "$DIR" --shell /usr/sbin/nologin "$USER_NAME"
mkdir -p "$DIR/data"
URL="https://github.com/$REPO/releases/latest/download/NETSniffer-Linux-$ARCH"
echo "Downloading $URL"
curl -fL --progress-bar -o "$DIR/NETSniffer.new" "$URL"
chmod 755 "$DIR/NETSniffer.new"
mv -f "$DIR/NETSniffer.new" "$DIR/NETSniffer"
chown -R "$USER_NAME:$USER_NAME" "$DIR"

cat > /etc/systemd/system/netsniffer.service <<EOF
[Unit]
Description=NET Sniffer network monitor
After=network-online.target
Wants=network-online.target

[Service]
User=$USER_NAME
Environment=NETSNIFFER_DATA=$DIR/data
ExecStart=$DIR/NETSniffer --headless --port 8765
Restart=always
RestartSec=3
# allow binding low ports / ICMP without full root
AmbientCapabilities=CAP_NET_RAW CAP_NET_BIND_SERVICE
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now netsniffer
sleep 3
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
CODE=$(journalctl -u netsniffer -n 50 --no-pager | grep -o 'setup code: [A-Za-z0-9_-]*' | tail -1 | awk '{print $3}')
echo ""
echo "  NET Sniffer is running:  http://${IP:-<this-ip>}:8765"
[ -n "$CODE" ] && echo "  First-time setup code:   $CODE"
echo "  Updates install automatically. Logs: journalctl -u netsniffer -f"
