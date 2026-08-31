#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this installer as root: sudo sh ./install-hardened.sh" >&2
    exit 1
fi

SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SERVICE_PATH=/etc/systemd/system/ameneko-html.service
BACKUP_PATH=/etc/systemd/system/ameneko-html.service.pre-hardening
INSTALL_DIR=/opt/ameneko-html
HOOK_PATH=/etc/letsencrypt/renewal-hooks/deploy/restart-ameneko-html
DOMAIN=$(sed -n '1p' "$SOURCE_DIR/domain.txt")

if [ "$DOMAIN" != "pba.im" ]; then
    echo "Expected domain.txt to contain pba.im, found: $DOMAIN" >&2
    exit 1
fi

for file in server.py domain.txt index.html a.html ameneko-html.service restart-ameneko-html; do
    if [ ! -f "$SOURCE_DIR/$file" ]; then
        echo "Missing deployment file: $SOURCE_DIR/$file" >&2
        exit 1
    fi
done

for file in fullchain.pem privkey.pem; do
    if [ ! -r "/etc/letsencrypt/live/$DOMAIN/$file" ]; then
        echo "Cannot read certificate file: /etc/letsencrypt/live/$DOMAIN/$file" >&2
        exit 1
    fi
done

/usr/bin/python3 -c \
    'from pathlib import Path; p=Path("'"$SOURCE_DIR"'/server.py"); compile(p.read_bytes(), str(p), "exec")'

if ! getent passwd ameneko >/dev/null 2>&1; then
    useradd --system --user-group --no-create-home \
        --home-dir /nonexistent --shell /usr/sbin/nologin ameneko
fi

install -d -o root -g root -m 0755 "$INSTALL_DIR"
install -o root -g root -m 0644 \
    "$SOURCE_DIR/server.py" \
    "$SOURCE_DIR/domain.txt" \
    "$SOURCE_DIR/index.html" \
    "$SOURCE_DIR/a.html" \
    "$INSTALL_DIR/"

if [ ! -f "$BACKUP_PATH" ]; then
    cp -p "$SERVICE_PATH" "$BACKUP_PATH"
fi

rollback() {
    echo "Hardened service failed; restoring the previous service." >&2
    install -o root -g root -m 0644 "$BACKUP_PATH" "$SERVICE_PATH"
    systemctl daemon-reload
    systemctl restart ameneko-html.service
}

install -o root -g root -m 0644 "$SOURCE_DIR/ameneko-html.service" "$SERVICE_PATH"
install -d -o root -g root -m 0755 "$(dirname "$HOOK_PATH")"
install -o root -g root -m 0755 "$SOURCE_DIR/restart-ameneko-html" "$HOOK_PATH"

if ! systemctl daemon-reload; then
    rollback
    exit 1
fi

if ! systemctl enable ameneko-html.service >/dev/null; then
    rollback
    exit 1
fi

if ! systemctl restart ameneko-html.service; then
    rollback
    exit 1
fi

sleep 1
if ! systemctl is-active --quiet ameneko-html.service; then
    rollback
    exit 1
fi

METRICS=$(curl -kso /dev/null \
    --resolve "$DOMAIN:443:127.0.0.1" \
    -w '%{size_header} %{size_download}' \
    "https://$DOMAIN/200B" || true)

set -- $METRICS
if [ "$#" -ne 2 ]; then
    rollback
    echo "Could not measure the HTTPS response." >&2
    exit 1
fi

TOTAL=$(( $1 + $2 ))
if [ "$TOTAL" -ne 193 ]; then
    rollback
    echo "Response size changed: headers=$1 body=$2 total=$TOTAL" >&2
    exit 1
fi

echo "ameneko-html is active as an unprivileged service."
echo "Response size preserved: headers=$1 body=$2 total=$TOTAL"
