#!/usr/bin/env bash
set -euo pipefail

TAG="bmi30-rdp-autofix"
log() {
    logger -t "$TAG" "$*"
    printf '[%s] %s\n' "$TAG" "$*"
}

is_listening_3389() {
    ss -ltn 2>/dev/null | grep -q ':3389'
}

has_active_rdp_clients() {
    ss -tn state established 2>/dev/null | awk 'NR>1 && $4 ~ /:3389$/ {found=1} END {exit found?0:1}'
}

stop_timer_if_running() {
    systemctl stop bmi30-rdp-autofix.timer >/dev/null 2>&1 || true
}

ensure_unit() {
    local unit="$1"
    systemctl reset-failed "$unit" >/dev/null 2>&1 || true
}

# Do not touch services while someone is already connected via RDP.
if has_active_rdp_clients; then
    log "Active RDP session detected; stopping watchdog timer"
    stop_timer_if_running
    exit 0
fi

# Startup-focused behavior: once healthy, stop timer and leave system as-is.
if systemctl is-active --quiet xrdp && is_listening_3389; then
    log "RDP is healthy; stopping watchdog timer"
    stop_timer_if_running
    exit 0
fi

log "Detected unhealthy RDP state, starting recovery"

ensure_unit bmi30-x11vnc.service
ensure_unit bmi30-shared-desktop-ready.service
ensure_unit xrdp.service

if ! systemctl is-active --quiet bmi30-x11vnc.service; then
    systemctl start bmi30-x11vnc.service || true
fi

ok=0
for _ in 1 2 3; do
    if systemctl start bmi30-shared-desktop-ready.service; then
        ok=1
        break
    fi
    sleep 2
done

if [[ "$ok" -ne 1 ]]; then
    log "Prerequisite service is still not ready; watchdog timer will retry"
    exit 0
fi

if systemctl is-active --quiet xrdp; then
    systemctl restart xrdp || true
else
    systemctl start xrdp || true
fi

sleep 1
if systemctl is-active --quiet xrdp && is_listening_3389; then
    log "Recovery successful: xrdp active and listening on 3389"
else
    log "Recovery attempted but xrdp still unhealthy; timer will retry"
fi
