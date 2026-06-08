#!/usr/bin/env bash
set -euo pipefail

WLAN_STA="wlan0"
WLAN_AP="wlan0ap"
PASS="${BMI30_HOTSPOT_PASSWORD:-12345678}"
NETWORK_NAME_PREFIX="BMI30-"
NETWORK_SERIAL_SUFFIX_LEN=9
CONFIG_JSON="${BMI30_CONFIG_JSON:-}"

detect_serial() {
    local serial=""

    if [[ -r /proc/device-tree/serial-number ]]; then
        serial="$(tr -d '\000\r\n ' < /proc/device-tree/serial-number || true)"
    fi

    if [[ -z "$serial" && -r /sys/firmware/devicetree/base/serial-number ]]; then
        serial="$(tr -d '\000\r\n ' < /sys/firmware/devicetree/base/serial-number || true)"
    fi

    if [[ -z "$serial" && -r /proc/cpuinfo ]]; then
        serial="$(awk -F': ' '/^Serial/ {print $2; exit}' /proc/cpuinfo | tr -d ' \t\n' || true)"
    fi

    serial="$(printf '%s' "$serial" | tr -cd '0-9A-Fa-f')"
    if [[ -z "$serial" || ${#serial} -lt 12 ]]; then
        echo "Unable to determine Raspberry Pi hardware serial" >&2
        exit 1
    fi

    printf '%s' "${serial^^}"
}

read_saved_hotspot_ssid() {
    local config_path="$1"

    [[ -n "$config_path" && -r "$config_path" ]] || return 0
    python3 - "$config_path" <<'PY' 2>/dev/null || true
import json
import sys

try:
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        payload = json.load(f) or {}
except Exception:
    payload = {}

hotspot = payload.get("hotspot_access")
if isinstance(hotspot, dict):
    ssid = str(hotspot.get("ssid") or "").strip()
    if ssid:
        print(ssid)
PY
}

resolve_config_json() {
    if [[ -n "$CONFIG_JSON" ]]; then
        printf '%s\n' "$CONFIG_JSON"
        return
    fi

    local candidate
    for candidate in \
        /etc/bmi30/portal_config.json \
        /usr/local/bin/host/bmi30_config.json \
        /home/techaid/Documents/host/bmi30_config.json; do
        if [[ -r "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return
        fi
    done
}

preserve_existing_password() {
    local target="$1"
    local existing_pass=""

    [[ -z "${BMI30_HOTSPOT_PASSWORD:-}" ]] || return 0
    [[ -n "$target" ]] || return 0

    existing_pass="$(nmcli -s -g 802-11-wireless-security.psk connection show "$target" 2>/dev/null || true)"
    if [[ -n "$existing_pass" ]]; then
        PASS="$existing_pass"
    fi
}

detect_ap_band_and_channel() {
    local sta_chan=""

    AP_BAND="bg"
    AP_CHAN="6"

    if ! nmcli -t -f DEVICE,STATE dev status | grep -q "^${WLAN_STA}:connected"; then
        return
    fi

    sta_chan="$(nmcli -t -f ACTIVE,CHAN dev wifi | awk -F: '$1=="yes" && $2 ~ /^[0-9]+$/ {print $2; exit}')"
    if [[ -z "$sta_chan" ]]; then
        return
    fi

    if (( sta_chan >= 1 && sta_chan <= 14 )); then
        AP_BAND="bg"
        AP_CHAN="$sta_chan"
        return
    fi

    if (( sta_chan >= 32 && sta_chan <= 196 )); then
        AP_BAND="a"
        AP_CHAN="$sta_chan"
    fi
}

apply_connection_settings() {
    local target="$1"

    nmcli con modify "$target" \
        connection.id "$CON" \
        connection.interface-name "$WLAN_AP" \
        802-11-wireless.ssid "$SSID" \
        802-11-wireless.mode ap \
        802-11-wireless.band "$AP_BAND" \
        802-11-wireless.channel "$AP_CHAN" \
        ipv4.method shared \
        ipv6.method ignore \
        wifi-sec.key-mgmt wpa-psk \
        wifi-sec.proto rsn \
        wifi-sec.pairwise ccmp \
        wifi-sec.group ccmp \
        wifi-sec.pmf 1 \
        wifi-sec.psk "$PASS" \
        connection.autoconnect yes
}

bring_connection_up() {
    if nmcli con up "$CON" >/dev/null 2>&1; then
        return 0
    fi

    if [[ "$AP_BAND" == "bg" && "$AP_CHAN" == "6" ]]; then
        return 1
    fi

    echo "Primary AP config ${AP_BAND}/${AP_CHAN} failed, retrying with bg/6" >&2
    AP_BAND="bg"
    AP_CHAN="6"
    apply_connection_settings "$1"
    nmcli con up "$CON" >/dev/null
}

serial="$(detect_serial)"
suffix="${serial: -$NETWORK_SERIAL_SUFFIX_LEN}"
saved_ssid="$(read_saved_hotspot_ssid "$(resolve_config_json)")"
SSID="${BMI30_HOTSPOT_SSID:-${saved_ssid:-${NETWORK_NAME_PREFIX}${suffix}}}"
CON="${BMI30_HOTSPOT_CONN:-$SSID}"

if ! ip link show "$WLAN_AP" >/dev/null 2>&1; then
    iw dev "$WLAN_STA" interface add "$WLAN_AP" type __ap
fi

nmcli dev set "$WLAN_AP" managed yes

detect_ap_band_and_channel

target_uuid=""
declare -a candidate_uuids=()

while IFS=: read -r connection_name connection_uuid connection_type; do
    [[ "$connection_type" == "802-11-wireless" || "$connection_type" == "wifi" ]] || continue

    current_if="$(nmcli -g connection.interface-name connection show "$connection_uuid" 2>/dev/null | tr '[:upper:]' '[:lower:]' || true)"
    current_mode="$(nmcli -g 802-11-wireless.mode connection show "$connection_uuid" 2>/dev/null | tr '[:upper:]' '[:lower:]' || true)"
    current_ssid="$(nmcli -g 802-11-wireless.ssid connection show "$connection_uuid" 2>/dev/null || true)"
    lowered_name="$(printf '%s' "$connection_name" | tr '[:upper:]' '[:lower:]')"

    if [[ "$connection_name" == "$CON" ]]; then
        target_uuid="$connection_uuid"
        candidate_uuids+=("$connection_uuid")
        continue
    fi

    if [[ "$current_if" == "$WLAN_AP" || "$current_mode" == "ap" || "$lowered_name" == hotspot-bmi30.* || "$current_ssid" == BMI30.* || "$current_ssid" == BMI30-* ]]; then
        candidate_uuids+=("$connection_uuid")
    fi
done < <(nmcli -t -f NAME,UUID,TYPE connection show 2>/dev/null || true)

if [[ -z "$target_uuid" && ${#candidate_uuids[@]} -gt 0 ]]; then
    target_uuid="${candidate_uuids[0]}"
fi

if [[ -n "$target_uuid" ]]; then
    preserve_existing_password "$target_uuid"
    apply_connection_settings "$target_uuid"
else
    nmcli con add type wifi ifname "$WLAN_AP" con-name "$CON" ssid "$SSID"
    preserve_existing_password "$CON"
    apply_connection_settings "$CON"
fi

for connection_uuid in "${candidate_uuids[@]}"; do
    [[ "$connection_uuid" == "$target_uuid" ]] && continue
    nmcli con delete "$connection_uuid" >/dev/null 2>&1 || true
done

bring_connection_up "${target_uuid:-$CON}"
