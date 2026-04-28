#!/usr/bin/env bash
set -euo pipefail

IFACE="${1:-}"
ACTION="${2:-}"

case "$ACTION" in
  up|connectivity-change|dhcp4-change|dhcp6-change) ;;
  *) exit 0 ;;
esac

current_ssid="$(nmcli -t -f ACTIVE,SSID dev wifi 2>/dev/null | awk -F: '$1=="yes" {print $2; exit}')"

if [[ "$current_ssid" == "VinetaBMI 2,4GHz" ]]; then
  logger -t bmi30-wifi-policy "2.4GHz SSID detected on ${IFACE}; switching to VinetaBMI 5GHz"
  nmcli connection down id "VinetaBMI 2,4GHz" >/dev/null 2>&1 || true
  nmcli connection up id "VinetaBMI 5GHz" >/dev/null 2>&1 || nmcli device wifi connect "VinetaBMI 5GHz" ifname "$IFACE" >/dev/null 2>&1 || true
fi
