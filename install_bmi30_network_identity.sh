#!/usr/bin/env bash

set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
MANUFACTURER="Vineta BMI s.r.o."
MODEL="BMI30"
WORKGROUP_DEFAULT="WORKGROUP"
NETWORK_NAME_PREFIX="BMI30-"
NETWORK_SERIAL_SUFFIX_LEN=9
WIFI_HOSTAPD_UPDATED=0
WIFI_NM_AP_UPDATED=0

# Headless display preset when no physical monitor is connected.
# Recommended presets:
# - FHD_60: 1920x1080@60 (best default for normal RDP work)
# - HD_60: 1280x720@60 (lower CPU/network load)
# - XGA_60: 1024x768@60 (maximum compatibility on weak links)
HEADLESS_DISPLAY_PRESET="${HEADLESS_DISPLAY_PRESET:-FHD_60}"

log() {
    local level="$1"
    shift
    printf '[%s] %s\n' "$level" "$*"
}

require_root() {
    if [[ "${EUID}" -eq 0 ]]; then
        return
    fi
    if command -v sudo >/dev/null 2>&1; then
        log INFO "Перезапуск через sudo..."
        exec sudo -E bash "$0" "$@"
    fi
    log ERROR "Нужны права root. Запустите: sudo ./$SCRIPT_NAME"
    exit 1
}

backup_file() {
    local path="$1"
    if [[ -f "$path" ]]; then
        local stamp
        stamp="$(date +%Y%m%d_%H%M%S)"
        cp -a "$path" "${path}.bmi30bak.${stamp}"
    fi
}

detect_serial() {
    local serial=""

    if [[ -r /proc/device-tree/serial-number ]]; then
        serial="$(tr -d '\000\r\n ' < /proc/device-tree/serial-number || true)"
    fi

    if [[ -z "$serial" && -r /sys/firmware/devicetree/base/serial-number ]]; then
        serial="$(tr -d '\000\r\n ' < /sys/firmware/devicetree/base/serial-number || true)"
    fi

    if [[ -z "$serial" && -r /proc/cpuinfo ]]; then
        serial="$(awk -F: '/^Serial/ {gsub(/^[ \t]+/, "", $2); print $2; exit}' /proc/cpuinfo || true)"
    fi

    serial="$(printf '%s' "$serial" | tr -cd '0-9A-Fa-f')"
    if [[ -z "$serial" || ${#serial} -lt 12 ]]; then
        log ERROR "Не удалось определить серийный номер Raspberry Pi"
        exit 1
    fi

    printf '%s' "${serial^^}"
}

build_common_name() {
    local serial_full="$1"
    local serial_suffix

    serial_suffix="${serial_full: -$NETWORK_SERIAL_SUFFIX_LEN}"
    printf '%s%s' "$NETWORK_NAME_PREFIX" "$serial_suffix"
}

install_packages() {
    log INFO "Устанавливаю сетевые пакеты (avahi, samba, wsdd, snmpd, lldpd)..."
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq avahi-daemon avahi-utils samba snmpd >/dev/null
    if ! apt-get install -y -qq lldpd >/dev/null 2>&1; then
        log WARN "Пакет lldpd не установлен автоматически. LLDP-настройка будет пропущена, если службы нет."
    fi
    if ! apt-get install -y -qq wsdd >/dev/null 2>&1; then
        log WARN "Пакет wsdd не установлен автоматически. WSD-настройка будет пропущена, если службы нет."
    fi

    log INFO "Проверяю пакеты для удаленного рабочего стола и индикатора раскладки..."
    if ! apt-get install -y -qq xrdp xorgxrdp dbus-x11 x11-xkb-utils >/dev/null 2>&1; then
        log WARN "Часть пакетов XRDP/X11 не установлена автоматически. Будут применены только доступные настройки."
    fi
    if ! apt-get install -y -qq x11vnc >/dev/null 2>&1; then
        log WARN "Пакет x11vnc не установлен автоматически. Режим общего рабочего стола для RDP может быть недоступен."
    fi
    if ! apt-get install -y -qq xxkb >/dev/null 2>&1; then
        log WARN "Пакет xxkb не установлен автоматически. Останется индикация раскладки через LED Scroll Lock."
    fi
    if ! apt-get install -y -qq wmctrl xdotool >/dev/null 2>&1; then
        log WARN "Пакеты wmctrl/xdotool не установлены автоматически. Восстановление размеров и позиций окон будет ограничено."
    fi
}

configure_rdp_session() {
    if ! systemctl list-unit-files xrdp.service >/dev/null 2>&1 && ! command -v xrdp >/dev/null 2>&1; then
        log INFO "XRDP не найден, настройка удаленного рабочего стола пропущена"
        return
    fi

    log INFO "Настраиваю XRDP-сессию (безопасный режим)"

    # Allow XRDP to read default TLS private key when distro uses ssl-cert group.
    if id -u xrdp >/dev/null 2>&1 && getent group ssl-cert >/dev/null 2>&1; then
        usermod -a -G ssl-cert xrdp >/dev/null 2>&1 || true
    fi

    if [[ -f /etc/xrdp/startwm.sh ]]; then
        backup_file /etc/xrdp/startwm.sh
        python3 - <<'PY'
from pathlib import Path

path = Path('/etc/xrdp/startwm.sh')
text = path.read_text(encoding='utf-8')
lines = text.splitlines()

start_marker = '# BMI30_HEADLESS_DISPLAY_BEGIN'
end_marker = '# BMI30_HEADLESS_DISPLAY_END'
begin_idx = next((i for i, line in enumerate(lines) if line.strip() == start_marker), None)
end_idx = next((i for i, line in enumerate(lines) if line.strip() == end_marker), None)
if begin_idx is not None and end_idx is not None and end_idx >= begin_idx:
    lines = lines[:begin_idx] + lines[end_idx + 1:]

start_marker = '# BMI30_RDP_FIX_BEGIN'
end_marker = '# BMI30_RDP_FIX_END'

begin_idx = next((i for i, line in enumerate(lines) if line.strip() == start_marker), None)
end_idx = next((i for i, line in enumerate(lines) if line.strip() == end_marker), None)

if begin_idx is not None and end_idx is not None and end_idx >= begin_idx:
    lines = lines[:begin_idx] + lines[end_idx + 1:]

fix_block = [
    '# BMI30_RDP_FIX_BEGIN',
    '# Ensure EN/RU XKB is initialized early for XRDP sessions.',
    'if [ -x /usr/local/bin/bmi30-rdp-xkb.sh ]; then',
    '        (',
    '                for i in 1 2 3 4 5; do',
    '                        /usr/local/bin/bmi30-rdp-xkb.sh && exit 0',
    '                        sleep 1',
    '                done',
    '        ) >/dev/null 2>&1 &',
    'fi',
    '# BMI30_RDP_FIX_END',
]

insert_idx = next((
    i for i, line in enumerate(lines)
    if line.strip() == 'test -x /etc/X11/Xsession && exec /etc/X11/Xsession'
), None)
if insert_idx is None:
    insert_idx = next((
        i for i, line in enumerate(lines)
        if line.strip() == 'exec /bin/sh /etc/X11/Xsession'
    ), len(lines))

if insert_idx > 0 and lines[insert_idx - 1].strip() != '':
    fix_block = [''] + fix_block

lines[insert_idx:insert_idx] = fix_block

path.write_text('\n'.join(lines).rstrip() + '\n', encoding='utf-8')
PY
    else
        log WARN "Файл /etc/xrdp/startwm.sh не найден, пропускаю XRDP cleanup"
    fi

    mkdir -p /usr/local/bin
    cat > /usr/local/bin/bmi30-rdp-xkb.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

# Переключение EN/RU по Ctrl+Shift; Scroll Lock может показывать активную группу.
if command -v setxkbmap >/dev/null 2>&1; then
    setxkbmap -model 'pc105' -layout 'us,ru' -variant ',' -option '' -option 'grp:ctrl_shift_toggle,grp_led:scroll' >/dev/null 2>&1 || true
fi

# Запуск xxkb с повторами: панель/трей в XRDP может появиться позже.
if command -v xxkb >/dev/null 2>&1; then
    (
        for i in $(seq 1 20); do
            if pgrep -u "$USER" -x xxkb >/dev/null 2>&1; then
                exit 0
            fi
            xxkb >/dev/null 2>&1 &
            sleep 2
        done
    ) >/dev/null 2>&1 &
fi
EOF
    chmod 755 /usr/local/bin/bmi30-rdp-xkb.sh

    mkdir -p /etc/xdg/autostart
    cat > /etc/xdg/autostart/bmi30-rdp-xkb.desktop <<'EOF'
[Desktop Entry]
Type=Application
Name=BMI30 RDP Keyboard Layout
Comment=Set EN/RU layout and start layout indicator
Exec=/usr/local/bin/bmi30-rdp-xkb.sh
Terminal=false
X-GNOME-Autostart-enabled=true
EOF

    # На части LXDE-сессий xxkb без явного конфига не стартует в трее.
    # Создаём пользовательский конфиг и иконки 32x32.
    if [[ -d /home/techaid ]]; then
        install -d -m 755 /home/techaid/.local/share/xxkb
        if command -v convert >/dev/null 2>&1; then
            convert /usr/share/xxkb/en48.xpm -resize 32x32\! /home/techaid/.local/share/xxkb/en32.xpm >/dev/null 2>&1 || cp -f /usr/share/xxkb/en48.xpm /home/techaid/.local/share/xxkb/en32.xpm
            convert /usr/share/xxkb/ru48.xpm -resize 32x32\! /home/techaid/.local/share/xxkb/ru32.xpm >/dev/null 2>&1 || cp -f /usr/share/xxkb/ru48.xpm /home/techaid/.local/share/xxkb/ru32.xpm
            convert /usr/share/xxkb/su48.xpm -resize 32x32\! /home/techaid/.local/share/xxkb/su32.xpm >/dev/null 2>&1 || cp -f /usr/share/xxkb/su48.xpm /home/techaid/.local/share/xxkb/su32.xpm
        else
            cp -f /usr/share/xxkb/en48.xpm /home/techaid/.local/share/xxkb/en32.xpm
            cp -f /usr/share/xxkb/ru48.xpm /home/techaid/.local/share/xxkb/ru32.xpm
            cp -f /usr/share/xxkb/su48.xpm /home/techaid/.local/share/xxkb/su32.xpm
        fi
        cat > /home/techaid/.xxkbrc <<'EOF'
XXkb.image.path: /home/techaid/.local/share/xxkb
XXkb.group.base: 1
XXkb.group.alt: 2
XXkb.mainwindow.enable: yes
XXkb.mainwindow.type: tray
XXkb.mainwindow.in_tray: true
XXkb.mainwindow.geometry: 32x32+0+0
XXkb.mainwindow.image.1: en32.xpm
XXkb.mainwindow.image.2: ru32.xpm
XXkb.mainwindow.image.3: su32.xpm
XXkb.controls.add_when_start: yes
XXkb.controls.add_when_create: yes
XXkb.controls.two_state: yes
XXkb.button.enable: no
EOF
        chown techaid:techaid /home/techaid/.local/share/xxkb/en32.xpm /home/techaid/.local/share/xxkb/ru32.xpm /home/techaid/.local/share/xxkb/su32.xpm || true
        chown techaid:techaid /home/techaid/.xxkbrc || true

        # Единый пользовательский init клавиатуры в LXDE (:0 и XRDP).
        install -d -m 755 /home/techaid/.local/bin
        cat > /home/techaid/.local/bin/session-keyboard-init <<'EOF'
#!/bin/sh

# Небольшая задержка, чтобы лоток панели успел инициализироваться.
sleep 2

setxkbmap -option '' >/dev/null 2>&1
setxkbmap -model pc105 -layout us,ru -variant , -option '' -option grp:ctrl_shift_toggle,grp_led:scroll >/dev/null 2>&1

if command -v xxkb >/dev/null 2>&1; then
    (
        for i in $(seq 1 20); do
            if pgrep -u "${USER:-techaid}" -x xxkb >/dev/null 2>&1; then
                exit 0
            fi
            xxkb >/dev/null 2>&1 &
            sleep 2
        done
    ) >/dev/null 2>&1 &
fi
EOF
        chmod 755 /home/techaid/.local/bin/session-keyboard-init
        chown techaid:techaid /home/techaid/.local/bin/session-keyboard-init || true

        install -d -m 755 /home/techaid/.config/lxsession/LXDE-pi
        if [[ ! -f /home/techaid/.config/lxsession/LXDE-pi/autostart ]]; then
            cat > /home/techaid/.config/lxsession/LXDE-pi/autostart <<'EOF'
@lxpanel --profile LXDE-pi
@pcmanfm --desktop --profile LXDE-pi
@xscreensaver -no-splash
@/home/techaid/.local/bin/session-keyboard-init
EOF
        elif ! grep -qF '@/home/techaid/.local/bin/session-keyboard-init' /home/techaid/.config/lxsession/LXDE-pi/autostart; then
            printf '\n@/home/techaid/.local/bin/session-keyboard-init\n' >> /home/techaid/.config/lxsession/LXDE-pi/autostart
        fi
        chown techaid:techaid /home/techaid/.config/lxsession/LXDE-pi/autostart || true
    fi

    if [[ -f /etc/xrdp/xrdp.ini ]]; then
        backup_file /etc/xrdp/xrdp.ini
        python3 - <<'PY'
from pathlib import Path

path = Path('/etc/xrdp/xrdp.ini')
text = path.read_text(encoding='utf-8')
lines = text.splitlines()

start_marker = '# BMI30_SHARED_DESKTOP_BEGIN'
end_marker = '# BMI30_SHARED_DESKTOP_END'

begin_idx = next((i for i, line in enumerate(lines) if line.strip() == start_marker), None)
end_idx = next((i for i, line in enumerate(lines) if line.strip() == end_marker), None)

if begin_idx is not None and end_idx is not None and end_idx >= begin_idx:
    lines = lines[:begin_idx] + lines[end_idx + 1:]

# Добавляем профиль общего рабочего стола и делаем его первым в списке,
# чтобы XRDP по умолчанию подключался к существующему экрану :0.
if lines and lines[-1].strip() != '':
    lines.append('')
new_section = [
    start_marker,
    '[BMI30_SHARED_DESKTOP]',
    'name=BMI30 Shared Desktop (:0)',
    'lib=libvnc.so',
    'ip=127.0.0.1',
    'port=5900',
    'username=na',
    'password=ask',
    end_marker,
]
# Вставка профиля BMI30 перед [Xorg] (первый профиль).
xorg_idx = next((i for i, line in enumerate(lines) if line.strip() == '[Xorg]'), None)
if xorg_idx is not None:
    lines[xorg_idx:xorg_idx] = new_section + ['']
else:
    lines.append('')
    lines.extend(new_section)

# Включаем autorun=BMI30_SHARED_DESKTOP в [Globals], чтобы при подключении
# открывался общий рабочий стол с приложениями, запущенными на :0.
globals_found = False
autorun_set = False
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped == '[Globals]':
        globals_found = True
        continue
    if globals_found and stripped.startswith('['):
        if not autorun_set:
            lines.insert(i, 'autorun=BMI30_SHARED_DESKTOP')
            autorun_set = True
        break
    if globals_found and stripped.startswith('autorun='):
        lines[i] = 'autorun=BMI30_SHARED_DESKTOP'
        autorun_set = True

if globals_found and not autorun_set:
    lines.append('autorun=BMI30_SHARED_DESKTOP')

path.write_text('\n'.join(lines).rstrip() + '\n', encoding='utf-8')
PY
    else
        log WARN "Файл /etc/xrdp/xrdp.ini не найден, пропускаю добавление shared desktop-профиля"
    fi

    # InputClass для Xorg: единая раскладка us,ru для всех клавиатур.
    install -d -m 755 /etc/X11/xorg.conf.d
    cat > /etc/X11/xorg.conf.d/10-bmi30-keyboard.conf <<'XORGEOF'
Section "InputClass"
    Identifier "bmi30-keyboard-all"
    MatchIsKeyboard "on"
    Option "XkbRules"   "evdev"
    Option "XkbModel"   "pc105"
    Option "XkbLayout"  "us,ru"
    Option "XkbOptions" "grp:ctrl_shift_toggle,grp_led:scroll"
EndSection
XORGEOF
    log INFO "Создан /etc/X11/xorg.conf.d/10-bmi30-keyboard.conf"

    # Дорабатываем display-setup-script: принудительно задаём XKB на :0 сразу после
    # старта X. Это ключевой фикс headless-режима для корректного ввода через x11vnc.
    local dispsetup_path='/usr/share/dispsetup.sh'
    if [[ -f "$dispsetup_path" ]] && ! grep -qF '# BMI30_XKB_BEGIN' "$dispsetup_path"; then
        backup_file "$dispsetup_path"
        python3 - "$dispsetup_path" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
text = path.read_text(encoding='utf-8')
if 'BMI30_XKB_BEGIN' not in text:
    inject = (
        '\n# BMI30_XKB_BEGIN\n'
        '# Принудительная XKB-конфигурация для headless-режима и XTEST-ввода.\n'
        '/usr/bin/setxkbmap -model "pc105" -layout "us,ru" -variant "," -option "" -option "grp:ctrl_shift_toggle,grp_led:scroll" 2>/dev/null || true\n'
        '# BMI30_XKB_END\n'
    )
    text = text.replace('\nexit 0', inject + 'exit 0', 1)
    path.write_text(text, encoding='utf-8')
PY
        log INFO "Обновлён $dispsetup_path: добавлена инициализация XKB раскладки"
    fi
}

configure_shared_desktop_bridge() {
    if ! command -v x11vnc >/dev/null 2>&1; then
        log WARN "x11vnc не найден, режим общего рабочего стола пропущен"
        return
    fi

    log INFO "Настраиваю bridge локального экрана (:0) для общего доступа через XRDP"

    cat > /usr/local/bin/bmi30-force-display-mode.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

export DISPLAY=:0
export XAUTHORITY=/home/techaid/.Xauthority

if ! command -v xrandr >/dev/null 2>&1; then
    exit 0
fi

# В headless-режиме могут оставаться «залипшие» параметры viewport/panning.
# Фиксируем стабильную геометрию 1920x1080 для моста x11vnc/XRDP.
xrandr --output HDMI-1 --mode 1920x1080 --rate 60 --primary --pos 0x0 --panning 0x0 >/dev/null 2>&1 || true
xrandr --fb 1920x1080 >/dev/null 2>&1 || true
EOF
    chmod 755 /usr/local/bin/bmi30-force-display-mode.sh

    mkdir -p /etc/systemd/system
    cat > /etc/systemd/system/bmi30-x11vnc.service <<'EOF'
[Unit]
Description=BMI30 shared desktop bridge for XRDP
After=display-manager.service graphical.target
Wants=display-manager.service

[Service]
Type=simple
ExecStartPre=/bin/sh -c 'for i in $(seq 1 30); do [ -e /tmp/.X11-unix/X0 ] && exit 0; sleep 1; done; exit 1'
ExecStartPre=/usr/local/bin/bmi30-force-display-mode.sh
ExecStartPre=/bin/sh -c 'DISPLAY=:0 XAUTHORITY=/var/run/lightdm/root/:0 /usr/bin/setxkbmap -model pc105 -layout us,ru -variant , -option "" -option grp:ctrl_shift_toggle,grp_led:scroll 2>/dev/null || true'
ExecStart=/usr/bin/x11vnc -display :0 -auth guess -forever -loop -shared -rfbport 5900 -localhost -noxdamage -norepeat -xkb -nomodtweak -clear_keys -clear_all -skip_keycodes 64,108,205 -o /var/log/bmi30-x11vnc.log
Restart=always
RestartSec=2

[Install]
WantedBy=graphical.target
EOF
}

configure_headless_display() {
    local config_path="/boot/firmware/config.txt"
    local cmdline_path="/boot/firmware/cmdline.txt"
    local headless_hdmi_group="2"
    local headless_hdmi_mode="82"
    local headless_video_token="video=HDMI-A-1:1920x1080@60D"

    case "${HEADLESS_DISPLAY_PRESET^^}" in
        FHD_60)
            headless_hdmi_group="2"
            headless_hdmi_mode="82"
            headless_video_token="video=HDMI-A-1:1920x1080@60D"
            ;;
        HD_60)
            headless_hdmi_group="1"
            headless_hdmi_mode="4"
            headless_video_token="video=HDMI-A-1:1280x720@60D"
            ;;
        XGA_60)
            headless_hdmi_group="2"
            headless_hdmi_mode="16"
            headless_video_token="video=HDMI-A-1:1024x768@60D"
            ;;
        *)
            log WARN "Неизвестный HEADLESS_DISPLAY_PRESET='${HEADLESS_DISPLAY_PRESET}', использую FHD_60"
            ;;
    esac

    if [[ ! -f "$config_path" || ! -f "$cmdline_path" ]]; then
        log WARN "Файлы boot-конфигурации не найдены, настройка headless display пропущена"
        return
    fi

    log INFO "Настраиваю headless HDMI: preset=${HEADLESS_DISPLAY_PRESET^^}, token=${headless_video_token#video=}"

    backup_file "$config_path"
    python3 - "$headless_hdmi_group" "$headless_hdmi_mode" <<'PY'
from pathlib import Path
import sys

hdmi_group = sys.argv[1]
hdmi_mode = sys.argv[2]

path = Path('/boot/firmware/config.txt')
text = path.read_text(encoding='utf-8')
lines = text.splitlines()

start_marker = '# BMI30_HEADLESS_DISPLAY_BEGIN'
end_marker = '# BMI30_HEADLESS_DISPLAY_END'
begin_idx = next((i for i, line in enumerate(lines) if line.strip() == start_marker), None)
end_idx = next((i for i, line in enumerate(lines) if line.strip() == end_marker), None)
if begin_idx is not None and end_idx is not None and end_idx >= begin_idx:
    lines = lines[:begin_idx] + lines[end_idx + 1:]

desired = {
    'hdmi_force_hotplug:0': '1',
    'hdmi_group:0': hdmi_group,
    'hdmi_mode:0': hdmi_mode,
}

seen = {k: False for k in desired}
out = []
for line in lines:
    stripped = line.strip()
    replaced = False
    for key, value in desired.items():
        if stripped.startswith(f'{key}='):
            out.append(f'{key}={value}')
            seen[key] = True
            replaced = True
            break
    if not replaced:
        out.append(line)

if out and out[-1].strip() != '':
    out.append('')

if not all(seen.values()):
    out.append(start_marker)
    for key, value in desired.items():
        if not seen[key]:
            out.append(f'{key}={value}')
    out.append(end_marker)

path.write_text('\n'.join(out).rstrip() + '\n', encoding='utf-8')
PY

    backup_file "$cmdline_path"
    python3 - "$headless_video_token" <<'PY'
from pathlib import Path
import sys

video_token = sys.argv[1]

path = Path('/boot/firmware/cmdline.txt')
line = path.read_text(encoding='utf-8').strip()
tokens = line.split()

tokens = [t for t in tokens if not t.startswith('video=HDMI-A-1:')]
tokens.append(video_token)

path.write_text(' '.join(tokens) + '\n', encoding='utf-8')
PY
}

configure_workspace_restore() {
    log INFO "Настраиваю автозапуск Psensor/VS Code с восстановлением расположения окон"

    mkdir -p /usr/local/bin

    cat > /usr/local/bin/bmi30-capture-window-layout.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

layout_file="${HOME}/.config/bmi30/window-layout.env"
mkdir -p "$(dirname "$layout_file")"

if ! command -v wmctrl >/dev/null 2>&1; then
    echo "wmctrl не найден. Установите пакет wmctrl." >&2
    exit 1
fi

get_geom_by_wmclass() {
    local wmclass="$1"
    wmctrl -lGx | awk -v wmclass="$wmclass" '$7 == wmclass {print $3 "," $4 "," $5 "," $6; exit}'
}

get_geom_by_title_regex() {
    local regex="$1"
    wmctrl -lGx | awk -v rx="$regex" 'BEGIN{IGNORECASE=1} $0 ~ rx {print $3 "," $4 "," $5 "," $6; exit}'
}

psensor_geom="$(get_geom_by_wmclass "psensor.Psensor")"
vscode_geom="$(get_geom_by_wmclass "code.Code")"

if [[ -z "$vscode_geom" ]]; then
    vscode_geom="$(get_geom_by_title_regex "Visual Studio Code|Code - OSS|VSCodium")"
fi

base_display="1920,1080"
if command -v xdotool >/dev/null 2>&1; then
    if geom="$(xdotool getdisplaygeometry 2>/dev/null)"; then
        base_display="${geom%% *},${geom##* }"
    fi
fi

cat > "$layout_file" <<LAYOUT
# BMI30 window layout (x,y,width,height)
# Saved by bmi30-capture-window-layout.sh
BASE_DISPLAY=${base_display}
PSENSOR_GEOM=${psensor_geom:-0,0,640,1080}
VSCODE_GEOM=${vscode_geom:-640,0,1280,1080}
LAYOUT

echo "Сохранено: $layout_file"
echo "BASE_DISPLAY=${base_display}"
echo "PSENSOR_GEOM=${psensor_geom:-0,0,640,1080}"
echo "VSCODE_GEOM=${vscode_geom:-640,0,1280,1080}"
EOF
    chmod 755 /usr/local/bin/bmi30-capture-window-layout.sh

    cat > /usr/local/bin/bmi30-restore-window-layout.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

layout_file="${HOME}/.config/bmi30/window-layout.env"

if ! command -v xdotool >/dev/null 2>&1 || ! command -v wmctrl >/dev/null 2>&1; then
    exit 0
fi

display_w="1920"
display_h="1080"
if geom="$(xdotool getdisplaygeometry 2>/dev/null)"; then
    display_w="${geom%% *}"
    display_h="${geom##* }"
fi

default_psensor_w=$((display_w / 3))
default_vscode_x="$default_psensor_w"
default_vscode_w=$((display_w - default_psensor_w))

PSENSOR_GEOM="0,0,${default_psensor_w},${display_h}"
VSCODE_GEOM="${default_vscode_x},0,${default_vscode_w},${display_h}"
BASE_DISPLAY="${display_w},${display_h}"

if [[ -f "$layout_file" ]]; then
    # shellcheck disable=SC1090
    source "$layout_file"
fi

scale_geom_to_current_display() {
    local geom="$1"
    local base_w base_h x y w h

    IFS=',' read -r base_w base_h <<< "${BASE_DISPLAY:-${display_w},${display_h}}"
    IFS=',' read -r x y w h <<< "$geom"

    if [[ -z "${base_w:-}" || -z "${base_h:-}" || "$base_w" -le 0 || "$base_h" -le 0 ]]; then
        echo "$geom"
        return 0
    fi

    x=$(( x * display_w / base_w ))
    y=$(( y * display_h / base_h ))
    w=$(( w * display_w / base_w ))
    h=$(( h * display_h / base_h ))

    if [[ "$w" -lt 320 ]]; then w=320; fi
    if [[ "$h" -lt 200 ]]; then h=200; fi
    if [[ "$x" -lt 0 ]]; then x=0; fi
    if [[ "$y" -lt 0 ]]; then y=0; fi
    if [[ $((x + w)) -gt "$display_w" ]]; then x=$(( display_w - w )); fi
    if [[ $((y + h)) -gt "$display_h" ]]; then y=$(( display_h - h )); fi
    if [[ "$x" -lt 0 ]]; then x=0; fi
    if [[ "$y" -lt 0 ]]; then y=0; fi

    echo "${x},${y},${w},${h}"
}

PSENSOR_GEOM="$(scale_geom_to_current_display "$PSENSOR_GEOM")"
VSCODE_GEOM="$(scale_geom_to_current_display "$VSCODE_GEOM")"

configure_psensor_geometry() {
    local geom="$1"
    local x y w h

    command -v gsettings >/dev/null 2>&1 || return 0
    gsettings list-schemas | grep -qx 'psensor' || return 0

    IFS=',' read -r x y w h <<< "$geom"
    gsettings set psensor interface-window-restore-enabled true >/dev/null 2>&1 || true
    gsettings set psensor interface-window-x "$x" >/dev/null 2>&1 || true
    gsettings set psensor interface-window-y "$y" >/dev/null 2>&1 || true
    gsettings set psensor interface-window-w "$w" >/dev/null 2>&1 || true
    gsettings set psensor interface-window-h "$h" >/dev/null 2>&1 || true
}

launch_vscode() {
    if pgrep -u "$USER" -f 'code|code-oss|codium' >/dev/null 2>&1; then
        return
    fi
    if command -v code >/dev/null 2>&1; then
        nohup code >/dev/null 2>&1 &
        return
    fi
    if command -v code-oss >/dev/null 2>&1; then
        nohup code-oss >/dev/null 2>&1 &
        return
    fi
    if command -v codium >/dev/null 2>&1; then
        nohup codium >/dev/null 2>&1 &
    fi
}

configure_psensor_geometry "$PSENSOR_GEOM"

if command -v psensor >/dev/null 2>&1 && ! pgrep -u "$USER" -x psensor >/dev/null 2>&1; then
    nohup psensor >/dev/null 2>&1 &
fi

launch_vscode

apply_geom() {
    local regex="$1"
    local geom="$2"
    local id=""
    local x y w h

    IFS=',' read -r x y w h <<< "$geom"

    for _ in $(seq 1 30); do
        id="$(xdotool search --name "$regex" 2>/dev/null | head -n 1 || true)"
        if [[ -n "$id" ]]; then
            wmctrl -ir "$id" -b remove,maximized_vert,maximized_horz >/dev/null 2>&1 || true
            wmctrl -ir "$id" -e "0,${x},${y},${w},${h}" >/dev/null 2>&1 || true
            return 0
        fi
        sleep 1
    done
    return 1
}

apply_geom "psensor" "$PSENSOR_GEOM" || true
apply_geom "Visual Studio Code|Code - OSS|VSCodium" "$VSCODE_GEOM" || true
EOF
    chmod 755 /usr/local/bin/bmi30-restore-window-layout.sh

    mkdir -p /etc/xdg/autostart
    cat > /etc/xdg/autostart/bmi30-restore-window-layout.desktop <<'EOF'
[Desktop Entry]
Type=Application
Name=BMI30 Restore Window Layout
Comment=Autostart Psensor and VS Code, then restore their window geometry
Exec=/usr/local/bin/bmi30-restore-window-layout.sh
Terminal=false
X-GNOME-Autostart-enabled=true
OnlyShowIn=LXDE;XFCE;MATE;GNOME;
EOF
}

set_hostname_files() {
    local safe_hostname="$1"
    local pretty_name="$2"

    log INFO "Настраиваю системное имя: $safe_hostname"

    backup_file /etc/hostname
    printf '%s\n' "$safe_hostname" > /etc/hostname

    if command -v hostnamectl >/dev/null 2>&1; then
        hostnamectl set-hostname "$safe_hostname" || true
        hostnamectl set-hostname "$pretty_name" --pretty || true
    else
        hostname "$safe_hostname" || true
    fi

    backup_file /etc/machine-info
    cat > /etc/machine-info <<EOF
PRETTY_HOSTNAME=$pretty_name
EOF

    backup_file /etc/hosts
    python3 - "$safe_hostname" <<'PY'
from pathlib import Path
import sys

hostname = sys.argv[1]
path = Path('/etc/hosts')
lines = path.read_text(encoding='utf-8').splitlines()
out = []
replaced = False

for line in lines:
    if line.strip().startswith('127.0.1.1'):
        out.append(f'127.0.1.1\t{hostname}')
        replaced = True
    else:
        out.append(line)

if not replaced:
    out.append(f'127.0.1.1\t{hostname}')

path.write_text('\n'.join(out) + '\n', encoding='utf-8')
PY
}

configure_avahi() {
    local safe_hostname="$1"
    local display_name="$2"
    local manufacturer="$3"
    local serial_tail="$4"

    log INFO "Настраиваю Avahi/mDNS"

    mkdir -p /etc/avahi/services
    backup_file /etc/avahi/avahi-daemon.conf

    python3 - "$safe_hostname" <<'PY'
from pathlib import Path
import sys

hostname = sys.argv[1]
path = Path('/etc/avahi/avahi-daemon.conf')
text = path.read_text(encoding='utf-8') if path.exists() else '[server]\n'
lines = text.splitlines()

section = None
server_found = False
host_written = False
out = []

for line in lines:
    stripped = line.strip()
    if stripped.startswith('[') and stripped.endswith(']'):
        if section == 'server' and not host_written:
            out.append(f'host-name={hostname}')
            host_written = True
        section = stripped.strip('[]').strip().lower()
        if section == 'server':
            server_found = True
        out.append(line)
        continue
    if section == 'server' and stripped.startswith('host-name='):
        out.append(f'host-name={hostname}')
        host_written = True
        continue
    out.append(line)

if not server_found:
    if out and out[-1] != '':
        out.append('')
    out.append('[server]')
    out.append(f'host-name={hostname}')
elif section == 'server' and not host_written:
    out.append(f'host-name={hostname}')

path.write_text('\n'.join(out).rstrip() + '\n', encoding='utf-8')
PY

    cat > /etc/avahi/services/bmi30-device.service <<EOF
<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name replace-wildcards="no">${display_name}</name>

  <service>
    <type>_workstation._tcp</type>
    <port>9</port>
  </service>

  <service>
    <type>_device-info._tcp</type>
    <port>9</port>
    <txt-record>model=${MODEL}</txt-record>
    <txt-record>manufacturer=${manufacturer}</txt-record>
    <txt-record>serial=${serial_tail}</txt-record>
    <txt-record>friendly-name=${display_name}</txt-record>
  </service>

  <service>
    <type>_smb._tcp</type>
    <port>445</port>
    <txt-record>friendly-name=${display_name}</txt-record>
    <txt-record>manufacturer=${manufacturer}</txt-record>
  </service>
</service-group>
EOF
}

configure_samba() {
    local display_name="$1"
    local manufacturer="$2"
    local netbios_name="$3"
    local workgroup="$4"

    log INFO "Настраиваю Samba/NetBIOS"

    backup_file /etc/samba/smb.conf
    python3 - "$display_name" "$manufacturer" "$netbios_name" "$workgroup" <<'PY'
from pathlib import Path
import sys

display_name, manufacturer, netbios_name, workgroup = sys.argv[1:5]
path = Path('/etc/samba/smb.conf')
text = path.read_text(encoding='utf-8') if path.exists() else '[global]\n'
lines = text.splitlines()

updates = {
    'workgroup': workgroup,
    'netbios name': netbios_name,
    'server string': f'{display_name} | {manufacturer}',
    'mdns name': 'mdns',
    'name resolve order': 'bcast host lmhosts wins',
}

section = None
global_found = False
seen = set()
out = []

for line in lines:
    stripped = line.strip()
    if stripped.startswith('[') and stripped.endswith(']'):
        if section == 'global':
            for key, value in updates.items():
                if key not in seen:
                    out.append(f'   {key} = {value}')
            seen.clear()
        section = stripped.strip('[]').strip().lower()
        if section == 'global':
            global_found = True
        out.append(line)
        continue

    if section == 'global' and '=' in line and not stripped.startswith(('#', ';')):
        key = line.split('=', 1)[0].strip().lower()
        if key in updates:
            out.append(f'   {key} = {updates[key]}')
            seen.add(key)
            continue

    out.append(line)

if not global_found:
    if out and out[-1] != '':
        out.append('')
    out.append('[global]')
    for key, value in updates.items():
        out.append(f'   {key} = {value}')
else:
    if section == 'global':
        for key, value in updates.items():
            if key not in seen:
                out.append(f'   {key} = {value}')

path.write_text('\n'.join(out).rstrip() + '\n', encoding='utf-8')
PY
}

configure_wsdd() {
    local display_name="$1"
    local manufacturer="$2"
    local model="$3"
    local workgroup="$4"
    local serial_tail="$5"
    local wsdd_name="$6"

    if ! systemctl list-unit-files wsdd.service >/dev/null 2>&1 && ! command -v wsdd >/dev/null 2>&1; then
        log WARN "wsdd не найден, WSD-объявление пропущено"
        return
    fi

    local wsdd_bin
    wsdd_bin="$(command -v wsdd || true)"
    if [[ -z "$wsdd_bin" ]]; then
        log WARN "Бинарник wsdd не найден, пропускаю WSD-настройку"
        return
    fi

    local help_text wsdd_args
    help_text="$(wsdd --help 2>&1 || true)"
    wsdd_args=()

    if grep -q -- '--hostname' <<<"$help_text"; then
        wsdd_args+=(--hostname "$wsdd_name")
    elif grep -q -- '-n' <<<"$help_text"; then
        wsdd_args+=(-n "$wsdd_name")
    fi

    if grep -q -- '--preserve-case' <<<"$help_text"; then
        wsdd_args+=(--preserve-case)
    elif grep -q -- '-p' <<<"$help_text"; then
        wsdd_args+=(-p)
    fi

    if grep -q -- '--workgroup' <<<"$help_text"; then
        wsdd_args+=(--workgroup "$workgroup")
    elif grep -q -- '-w' <<<"$help_text"; then
        wsdd_args+=(-w "$workgroup")
    fi

    if grep -q -- '--manufacturer' <<<"$help_text"; then
        wsdd_args+=(--manufacturer "$manufacturer")
    elif grep -q -- '--vendor' <<<"$help_text"; then
        wsdd_args+=(--vendor "$manufacturer")
    fi

    if grep -q -- '--model' <<<"$help_text"; then
        wsdd_args+=(--model "$model")
    fi

    if grep -q -- '--serial' <<<"$help_text"; then
        wsdd_args+=(--serial "$serial_tail")
    fi

    if [[ ${#wsdd_args[@]} -eq 0 ]]; then
        log WARN "У wsdd не распознаны параметры имени/метаданных, пропускаю override"
        return
    fi

    local wsdd_exec
    wsdd_exec="$(python3 - "$wsdd_bin" "${wsdd_args[@]}" <<'PY'
import shlex
import sys

print(' '.join(shlex.quote(arg) for arg in sys.argv[1:]))
PY
)"

    log INFO "Настраиваю WSDD"

    mkdir -p /etc/systemd/system/wsdd.service.d
    cat > /etc/systemd/system/wsdd.service.d/override.conf <<EOF
[Service]
ExecStart=
ExecStart=${wsdd_exec}
EOF
}

configure_snmp() {
    local display_name="$1"
    local manufacturer="$2"
    local model="$3"
    local safe_hostname="$4"
    local serial_tail="$5"
    local snmp_contact snmp_location snmp_community snmp_description

    snmp_contact="${SNMP_CONTACT:-${manufacturer}}"
    snmp_location="${SNMP_LOCATION:-BMI30 device}"
    snmp_community="${SNMP_COMMUNITY:-public}"
    snmp_description="${manufacturer} ${model} ${display_name} serial ${serial_tail}"

    if [[ "$snmp_community" == "public" ]]; then
        log WARN "SNMP community оставлен по умолчанию: public"
    fi

    log INFO "Настраиваю SNMP"

    mkdir -p /etc/snmp
    backup_file /etc/snmp/snmpd.conf
    cat > /etc/snmp/snmpd.conf <<EOF
agentaddress udp:161,udp6:[::]:161
sysName ${display_name}
sysDescr ${snmp_description}
sysContact ${snmp_contact}
sysLocation ${snmp_location}
rocommunity ${snmp_community} default -V systemonly
rocommunity6 ${snmp_community} default -V systemonly
view systemonly included .1.3.6.1.2.1.1
EOF

    if [[ -f /etc/default/snmpd ]]; then
        backup_file /etc/default/snmpd
        python3 - <<'PY'
from pathlib import Path

path = Path('/etc/default/snmpd')
lines = path.read_text(encoding='utf-8').splitlines()
out = []
found = False

for line in lines:
    stripped = line.strip()
    if stripped.startswith('SNMPDOPTS='):
        out.append('SNMPDOPTS="-LSwd -Lf /dev/null -u Debian-snmp -g Debian-snmp -I -smux -p /run/snmpd.pid"')
        found = True
    else:
        out.append(line)

if not found:
    out.append('SNMPDOPTS="-LSwd -Lf /dev/null -u Debian-snmp -g Debian-snmp -I -smux -p /run/snmpd.pid"')

path.write_text('\n'.join(out).rstrip() + '\n', encoding='utf-8')
PY
    fi
}

configure_lldp() {
    local display_name="$1"
    local manufacturer="$2"
    local model="$3"
    local serial_tail="$4"
    local lldp_description lldp_platform

    if ! systemctl list-unit-files lldpd.service >/dev/null 2>&1 && ! command -v lldpd >/dev/null 2>&1; then
        log WARN "lldpd не найден, LLDP-объявление пропущено"
        return
    fi

    lldp_description="${manufacturer} ${model} ${display_name} serial ${serial_tail}"
    lldp_platform="${manufacturer} ${model}"

    log INFO "Настраиваю LLDP"

    backup_file /etc/lldpd.conf
    cat > /etc/lldpd.conf <<EOF
configure system hostname ${display_name}
configure system description ${lldp_description}
configure system platform ${lldp_platform}
EOF
}

configure_wifi_name() {
    local wifi_name="$1"
    local updated=0
    local profile_updated=0

    if [[ -f /etc/hostapd/hostapd.conf ]]; then
        log INFO "Настраиваю Wi-Fi SSID в hostapd: $wifi_name"
        backup_file /etc/hostapd/hostapd.conf
        python3 - "$wifi_name" <<'PY'
from pathlib import Path
import sys

ssid = sys.argv[1]
path = Path('/etc/hostapd/hostapd.conf')
lines = path.read_text(encoding='utf-8').splitlines()
out = []
found = False

for line in lines:
    stripped = line.strip()
    if stripped.startswith('ssid='):
        out.append(f'ssid={ssid}')
        found = True
    else:
        out.append(line)

if not found:
    out.append(f'ssid={ssid}')

path.write_text('\n'.join(out).rstrip() + '\n', encoding='utf-8')
PY
        WIFI_HOSTAPD_UPDATED=1
        updated=1
    fi

    if command -v nmcli >/dev/null 2>&1; then
        log INFO "Настраиваю Wi-Fi SSID в hotspot-профилях NetworkManager: $wifi_name"
        local hotspot_uuids=()
        local hotspot_active=()
        local hotspot_ids=()
        local hotspot_ssids=()

        while IFS=: read -r connection_name connection_uuid connection_type connection_active; do
            [[ "$connection_type" == "802-11-wireless" || "$connection_type" == "wifi" ]] || continue

            local mode ipv4_method current_ssid current_id interface_name changed lowered_name lowered_id lowered_ssid is_hotspot
            mode="$(nmcli -g 802-11-wireless.mode connection show "$connection_uuid" 2>/dev/null | tr '[:upper:]' '[:lower:]' || true)"
            ipv4_method="$(nmcli -g ipv4.method connection show "$connection_uuid" 2>/dev/null | tr '[:upper:]' '[:lower:]' || true)"
            interface_name="$(nmcli -g connection.interface-name connection show "$connection_uuid" 2>/dev/null | tr '[:upper:]' '[:lower:]' || true)"
            lowered_name="$(printf '%s' "$connection_name" | tr '[:upper:]' '[:lower:]')"
            current_ssid="$(nmcli -g 802-11-wireless.ssid connection show "$connection_uuid" 2>/dev/null || true)"
            current_id="$(nmcli -g connection.id connection show "$connection_uuid" 2>/dev/null || true)"
            lowered_id="$(printf '%s' "$current_id" | tr '[:upper:]' '[:lower:]')"
            lowered_ssid="$(printf '%s' "$current_ssid" | tr '[:upper:]' '[:lower:]')"

            is_hotspot=0
            if [[ "$mode" == "ap" || "$ipv4_method" == "shared" || "$lowered_name" == hotspot* || "$lowered_name" == "wifi hotspot" || "$lowered_id" == hotspot* || "$lowered_ssid" == bmi30* || "$interface_name" == "wlan0ap" ]]; then
                is_hotspot=1
            fi

            if [[ "$is_hotspot" -eq 0 ]]; then
                continue
            fi

            changed=0

            if [[ "$current_ssid" != "$wifi_name" ]]; then
                changed=1
            fi

            if [[ "$current_id" != "$wifi_name" ]]; then
                changed=1
            fi

            if [[ "$changed" -eq 1 ]]; then
                log INFO "Обновляю hotspot-профиль NetworkManager: ${connection_name:-$connection_uuid}"
                if nmcli connection modify "$connection_uuid" 802-11-wireless.ssid "$wifi_name" connection.id "$wifi_name" >/dev/null 2>&1; then
                    current_ssid="$wifi_name"
                    current_id="$wifi_name"
                    WIFI_NM_AP_UPDATED=1
                    updated=1
                else
                    log WARN "Не удалось обновить hotspot-профиль NetworkManager: ${connection_name:-$connection_uuid}"
                fi
            fi

            hotspot_uuids+=("$connection_uuid")
            hotspot_active+=("$connection_active")
            hotspot_ids+=("$current_id")
            hotspot_ssids+=("$current_ssid")

        done < <(nmcli -t -f NAME,UUID,TYPE,ACTIVE connection show 2>/dev/null || true)

        if [[ ${#hotspot_uuids[@]} -gt 1 ]]; then
            local keep_uuid=""
            local active_uuid=""

            for i in "${!hotspot_uuids[@]}"; do
                if [[ "${hotspot_active[$i]}" == "yes" ]]; then
                    active_uuid="${hotspot_uuids[$i]}"
                fi

                if [[ "${hotspot_ids[$i]}" == "$wifi_name" || "${hotspot_ssids[$i]}" == "$wifi_name" ]]; then
                    if [[ "${hotspot_active[$i]}" == "yes" ]]; then
                        keep_uuid="${hotspot_uuids[$i]}"
                        break
                    fi
                    if [[ -z "$keep_uuid" ]]; then
                        keep_uuid="${hotspot_uuids[$i]}"
                    fi
                fi
            done

            if [[ -z "$keep_uuid" && -n "$active_uuid" ]]; then
                keep_uuid="$active_uuid"
            fi

            if [[ -z "$keep_uuid" ]]; then
                keep_uuid="${hotspot_uuids[0]}"
            fi

            if [[ -n "$active_uuid" && "$keep_uuid" != "$active_uuid" ]]; then
                log INFO "Переключаю активный hotspot на профиль: $keep_uuid"
                nmcli connection down "$active_uuid" >/dev/null 2>&1 || true
                if nmcli connection up "$keep_uuid" >/dev/null 2>&1; then
                    WIFI_NM_AP_UPDATED=1
                    updated=1
                else
                    log WARN "Не удалось активировать hotspot-профиль: $keep_uuid"
                fi
            fi

            for i in "${!hotspot_uuids[@]}"; do
                local uuid_to_delete
                uuid_to_delete="${hotspot_uuids[$i]}"

                if [[ "${hotspot_active[$i]}" == "yes" ]]; then
                    if [[ "$uuid_to_delete" == "$keep_uuid" ]]; then
                        continue
                    fi

                    log INFO "Отключаю лишний активный hotspot-профиль: $uuid_to_delete"
                    nmcli connection down "$uuid_to_delete" >/dev/null 2>&1 || true
                fi

                if [[ "$uuid_to_delete" == "$keep_uuid" ]]; then
                    continue
                fi

                log INFO "Удаляю лишний hotspot-профиль NetworkManager: $uuid_to_delete"
                if nmcli connection delete "$uuid_to_delete" >/dev/null 2>&1; then
                    WIFI_NM_AP_UPDATED=1
                    updated=1
                else
                    log WARN "Не удалось удалить hotspot-профиль NetworkManager: $uuid_to_delete"
                fi
            done
        fi
    fi

    if compgen -G '/etc/NetworkManager/system-connections/*.nmconnection' >/dev/null; then
        log INFO "Проверяю keyfile-профили NetworkManager: $wifi_name"
        while IFS= read -r -d '' connection_file; do
            backup_file "$connection_file"
            if python3 - "$connection_file" "$wifi_name" <<'PY'
from configparser import ConfigParser
from pathlib import Path
import sys

path = Path(sys.argv[1])
ssid = sys.argv[2]
parser = ConfigParser(interpolation=None)
parser.optionxform = str
parser.read(path, encoding='utf-8')

if not parser.has_section('wifi'):
    raise SystemExit(10)

connection_type = parser.get('connection', 'type', fallback='').strip().lower()
if connection_type != 'wifi':
    raise SystemExit(10)

wifi_mode = parser.get('wifi', 'mode', fallback='').strip().lower()
ipv4_method = parser.get('ipv4', 'method', fallback='').strip().lower()
connection_id = parser.get('connection', 'id', fallback='').strip().lower()
interface_name = parser.get('connection', 'interface-name', fallback='').strip().lower()
file_name = path.name.strip().lower()

is_hotspot = (
    wifi_mode == 'ap'
    or ipv4_method == 'shared'
    or connection_id in {'hotspot', 'wifi hotspot'}
    or connection_id.startswith('hotspot-')
    or file_name.startswith('hotspot-')
    or interface_name == 'wlan0ap'
)

if not is_hotspot:
    raise SystemExit(10)

changed = False

if parser.get('wifi', 'ssid', fallback='') != ssid:
    parser.set('wifi', 'ssid', ssid)
    changed = True

if parser.has_section('connection'):
    if parser.get('connection', 'id', fallback='') != ssid:
        parser.set('connection', 'id', ssid)
        changed = True

if not changed:
    raise SystemExit(10)

with path.open('w', encoding='utf-8') as fh:
    parser.write(fh, space_around_delimiters=False)
PY
            then
                chmod 600 "$connection_file" || true
                profile_updated=1
            fi
        done < <(find /etc/NetworkManager/system-connections -maxdepth 1 -type f -name '*.nmconnection' -print0)
        if [[ "$profile_updated" -eq 1 ]]; then
            WIFI_NM_AP_UPDATED=1
            updated=1
        fi
    fi

    if [[ "$updated" -eq 0 ]]; then
        log INFO "Конфиг hotspot Wi-Fi не найден, имя Wi-Fi не меняю"
    fi
}

configure_bmi30_hotspot_service() {
        if [[ ! -f /usr/local/bin/bmi30-hotspot.sh ]] && ! systemctl list-unit-files bmi30-hotspot.service >/dev/null 2>&1; then
                return
        fi

        log INFO "Синхронизирую startup-скрипт bmi30-hotspot с общим именем устройства"

        if [[ -f /usr/local/bin/bmi30-hotspot.sh ]]; then
                backup_file /usr/local/bin/bmi30-hotspot.sh
        fi

        cat > /usr/local/bin/bmi30-hotspot.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

WLAN_STA="wlan0"
WLAN_AP="wlan0ap"
PASS="12345678"
NETWORK_NAME_PREFIX="BMI30-"
NETWORK_SERIAL_SUFFIX_LEN=9

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

    if [[ -z "$serial" && -r /etc/machine-id ]]; then
        serial="$(tr -d ' \t\n' < /etc/machine-id || true)"
    fi

    serial="$(printf '%s' "$serial" | tr -cd '0-9A-Fa-f')"
    if [[ -z "$serial" ]]; then
        echo "Unable to determine serial" >&2
        exit 1
    fi

    printf '%s' "${serial^^}"
}

serial="$(detect_serial)"
suffix="${serial: -$NETWORK_SERIAL_SUFFIX_LEN}"
SSID="${NETWORK_NAME_PREFIX}${suffix}"
CON="$SSID"

if ! ip link show "$WLAN_AP" >/dev/null 2>&1; then
    iw dev "$WLAN_STA" interface add "$WLAN_AP" type __ap
fi

nmcli dev set "$WLAN_AP" managed yes

chan="6"
if nmcli -t -f DEVICE,STATE dev status | grep -q "^${WLAN_STA}:connected"; then
    sta_chan="$(nmcli -t -f ACTIVE,CHAN dev wifi | awk -F: '$1=="yes"{print $2; exit}')"
    if [[ -n "$sta_chan" ]]; then
        chan="$sta_chan"
    fi
fi

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
    nmcli con modify "$target_uuid" \
        connection.id "$CON" \
        connection.interface-name "$WLAN_AP" \
        802-11-wireless.ssid "$SSID" \
        802-11-wireless.mode ap \
        802-11-wireless.band bg \
        802-11-wireless.channel "$chan" \
        ipv4.method shared \
        ipv6.method ignore \
        wifi-sec.key-mgmt wpa-psk \
        wifi-sec.psk "$PASS" \
        connection.autoconnect yes
else
    nmcli con add type wifi ifname "$WLAN_AP" con-name "$CON" ssid "$SSID"
    nmcli con modify "$CON" \
        connection.interface-name "$WLAN_AP" \
        802-11-wireless.mode ap \
        802-11-wireless.band bg \
        802-11-wireless.channel "$chan" \
        ipv4.method shared \
        ipv6.method ignore \
        wifi-sec.key-mgmt wpa-psk \
        wifi-sec.psk "$PASS" \
        connection.autoconnect yes
fi

for connection_uuid in "${candidate_uuids[@]}"; do
    [[ "$connection_uuid" == "$target_uuid" ]] && continue
    nmcli con delete "$connection_uuid" >/dev/null 2>&1 || true
done

nmcli con up "$CON" >/dev/null
EOF

        chmod 755 /usr/local/bin/bmi30-hotspot.sh
}

configure_firewall() {
    if ! command -v ufw >/dev/null 2>&1; then
        return
    fi

    if ! ufw status 2>/dev/null | grep -qi '^status: active'; then
        log INFO "UFW не активен, firewall-настройка не требуется"
        return
    fi

    log INFO "Открываю правила UFW для SMB/WSD обнаружения"
    ufw allow Samba >/dev/null 2>&1 || true
    ufw allow 3702/udp >/dev/null 2>&1 || true
    ufw allow 5357/tcp >/dev/null 2>&1 || true
    ufw allow 161/udp >/dev/null 2>&1 || true
}

restart_services() {
    log INFO "Перезапускаю сетевые службы"
    systemctl daemon-reload || true

    for service in avahi-daemon smbd nmbd wsdd snmpd lldpd xrdp bmi30-x11vnc; do
        if systemctl list-unit-files "${service}.service" >/dev/null 2>&1; then
            systemctl enable "$service" >/dev/null 2>&1 || true
            systemctl restart "$service" || true
        fi
    done

    if [[ "$WIFI_HOSTAPD_UPDATED" -eq 1 ]] && systemctl list-unit-files hostapd.service >/dev/null 2>&1; then
        systemctl enable hostapd >/dev/null 2>&1 || true
        systemctl restart hostapd || true
    fi

    if command -v nmcli >/dev/null 2>&1; then
        nmcli connection reload >/dev/null 2>&1 || true

        if [[ "$WIFI_NM_AP_UPDATED" -eq 1 ]]; then
            while IFS=: read -r connection_uuid connection_type connection_name; do
                [[ "$connection_type" == "wifi" || "$connection_type" == "802-11-wireless" ]] || continue

                local mode ipv4_method
                mode="$(nmcli -g 802-11-wireless.mode connection show "$connection_uuid" 2>/dev/null | tr '[:upper:]' '[:lower:]' || true)"
                ipv4_method="$(nmcli -g ipv4.method connection show "$connection_uuid" 2>/dev/null | tr '[:upper:]' '[:lower:]' || true)"
                [[ "$mode" == "ap" || "$ipv4_method" == "shared" ]] || continue

                log INFO "Переактивирую hotspot NetworkManager: ${connection_name:-$connection_uuid}"
                nmcli connection down "$connection_uuid" >/dev/null 2>&1 || true
                nmcli connection up "$connection_uuid" >/dev/null 2>&1 || true
            done < <(nmcli -t -f UUID,TYPE,NAME connection show --active 2>/dev/null || true)
        fi
    fi
}

main() {
    require_root "$@"

    local serial_full serial_tail common_name display_name safe_hostname netbios_name wsdd_name workgroup
    serial_full="$(detect_serial)"
    serial_tail="${serial_full: -12}"
    common_name="$(build_common_name "$serial_full")"
    display_name="$common_name"
    safe_hostname="$common_name"
    netbios_name="$common_name"
    wsdd_name="$common_name"
    workgroup="${WORKGROUP:-$WORKGROUP_DEFAULT}"

    log INFO "Серийный номер Raspberry: $serial_full"
    log INFO "Отображаемое имя устройства: $display_name"
    log INFO "Системное hostname: $safe_hostname"
    log INFO "NetBIOS fallback: $netbios_name"
    log INFO "Windows Explorer имя: $wsdd_name"

    install_packages
    set_hostname_files "$safe_hostname" "$display_name"
    configure_avahi "$safe_hostname" "$display_name" "$MANUFACTURER" "$serial_tail"
    configure_samba "$display_name" "$MANUFACTURER" "$netbios_name" "$workgroup"
    configure_wsdd "$display_name" "$MANUFACTURER" "$MODEL" "$workgroup" "$serial_tail" "$wsdd_name"
    configure_snmp "$display_name" "$MANUFACTURER" "$MODEL" "$safe_hostname" "$serial_tail"
    configure_lldp "$display_name" "$MANUFACTURER" "$MODEL" "$serial_tail"
    configure_wifi_name "$display_name"
    configure_bmi30_hotspot_service
    configure_headless_display
    configure_workspace_restore
    configure_rdp_session
    configure_shared_desktop_bridge
    configure_firewall
    restart_services

    log OK "Готово"
    log OK "Имя в сети: $display_name"
    log OK "Производитель: $MANUFACTURER"
    log INFO "Если имя не обновилось у клиентов сразу, переподключите сеть или перезапустите Raspberry Pi"
}

main "$@"