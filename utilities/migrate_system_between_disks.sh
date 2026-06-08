#!/usr/bin/env bash
set -euo pipefail

BOOT_ORDER_USB_FIRST="0xf2614"
BOOT_SIZE_MIB=512
SOURCE_ROLE=""
TARGET_ROLE=""
ASSUME_YES=0
SKIP_EEPROM=0
SYNC_ONLY=0
SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
WORKSPACE_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

SCRIPT_NAME="$(basename "$0")"
TOTAL_STEPS=13
CURRENT_STEP=0

RED='\033[0;31m'
GRN='\033[0;32m'
YLW='\033[1;33m'
BLU='\033[0;34m'
NC='\033[0m'

info() {
    printf "%b[INFO]%b %s\n" "$BLU" "$NC" "$*"
}

warn() {
    printf "%b[WARN]%b %s\n" "$YLW" "$NC" "$*" >&2
}

ok() {
    printf "%b[ OK ]%b %s\n" "$GRN" "$NC" "$*"
}

die() {
    printf "%b[ERR ]%b %s\n" "$RED" "$NC" "$*" >&2
    exit 1
}

usage() {
    cat <<EOF
Использование:
  sudo ./$SCRIPT_NAME --source-role internal|usb --target-role internal|usb [--yes] [--skip-eeprom] [--sync-only]

Скрипт выполняет файловую миграцию системы между eMMC и USB:
  1. Определяет исходный и целевой диски по ролям.
  2. Перед полным копированием сохраняет изменения проекта в облако.
  3. По умолчанию переразбивает целевой диск.
  4. С флагом --sync-only использует существующие разделы цели без переразметки.
  5. Копирует boot и root через rsync с прогрессом.
  6. Записывает новые PARTUUID в cmdline.txt и fstab на целевом диске.

Примеры:
  sudo ./$SCRIPT_NAME --source-role internal --target-role usb
  sudo ./$SCRIPT_NAME --source-role usb --target-role internal
  sudo ./$SCRIPT_NAME --source-role usb --target-role internal --sync-only
EOF
}

require_root() {
    [[ ${EUID:-$(id -u)} -eq 0 ]] || die "Запустите скрипт через sudo"
}

require_cmds() {
    local missing=()
    local cmd
    for cmd in lsblk findmnt blkid mountpoint rsync sfdisk wipefs partprobe udevadm mkfs.vfat mkfs.ext4 awk sed grep sync sort df numfmt; do
        if ! command -v "$cmd" >/dev/null 2>&1; then
            missing+=("$cmd")
        fi
    done
    if (( ${#missing[@]} > 0 )); then
        die "Не найдены команды: ${missing[*]}"
    fi
}

run_precopy_backup() {
    local backup_script backup_user user_home

    if (( SYNC_ONLY == 1 )); then
        info "Sync-only режим: pre-copy cloud backup не требуется"
        return
    fi

    backup_script="$SCRIPT_DIR/backup_to_cloud.sh"
    [[ -x "$backup_script" ]] || die "Не найден исполняемый backup-скрипт: $backup_script"

    info "Перед полным копированием проверяю и сохраняю изменения проекта в облако"

    backup_user="${SUDO_USER:-}"
    if [[ -z "$backup_user" || "$backup_user" == "root" ]]; then
        backup_user="$(stat -c '%U' "$WORKSPACE_DIR" 2>/dev/null || true)"
    fi
    if [[ -n "$backup_user" && "$backup_user" != "root" ]]; then
        user_home="$(getent passwd "$backup_user" | awk -F: '{print $6}')"
        [[ -n "$user_home" ]] || die "Не удалось определить HOME пользователя $backup_user"
        sudo -u "$backup_user" env \
            HOME="$user_home" \
            CONFIG_FILE="$SCRIPT_DIR/backup_to_cloud.conf" \
            bash "$backup_script" --if-changed
    else
        env CONFIG_FILE="$SCRIPT_DIR/backup_to_cloud.conf" bash "$backup_script" --if-changed
    fi
}

step() {
    CURRENT_STEP=$((CURRENT_STEP + 1))
    printf "\n%b[%d/%d]%b %s\n" "$GRN" "$CURRENT_STEP" "$TOTAL_STEPS" "$NC" "$*"
}

partition_path() {
    local disk="$1"
    local number="$2"

    if [[ "$disk" =~ [0-9]$ ]]; then
        printf "%sp%s\n" "$disk" "$number"
    else
        printf "%s%s\n" "$disk" "$number"
    fi
}

cleanup() {
    set +e
    if mountpoint -q "$TARGET_BOOT_MNT" 2>/dev/null; then
        umount "$TARGET_BOOT_MNT"
    fi
    if mountpoint -q "$TARGET_ROOT_MNT" 2>/dev/null; then
        umount "$TARGET_ROOT_MNT"
    fi
    if mountpoint -q "$SOURCE_BOOT_MNT" 2>/dev/null; then
        umount "$SOURCE_BOOT_MNT"
    fi
    if mountpoint -q "$SOURCE_ROOT_MNT" 2>/dev/null; then
        umount "$SOURCE_ROOT_MNT"
    fi
    rm -rf "$WORKDIR"
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --source-role)
                [[ $# -ge 2 ]] || die "После --source-role нужна роль"
                SOURCE_ROLE="$2"
                shift 2
                ;;
            --target-role)
                [[ $# -ge 2 ]] || die "После --target-role нужна роль"
                TARGET_ROLE="$2"
                shift 2
                ;;
            --yes)
                ASSUME_YES=1
                shift
                ;;
            --skip-eeprom)
                SKIP_EEPROM=1
                shift
                ;;
            --sync-only)
                SYNC_ONLY=1
                shift
                ;;
            --help|-h)
                usage
                exit 0
                ;;
            *)
                die "Неизвестный параметр: $1"
                ;;
        esac
    done

    [[ "$SOURCE_ROLE" == "internal" || "$SOURCE_ROLE" == "usb" ]] || die "Нужен --source-role internal|usb"
    [[ "$TARGET_ROLE" == "internal" || "$TARGET_ROLE" == "usb" ]] || die "Нужен --target-role internal|usb"
    [[ "$SOURCE_ROLE" != "$TARGET_ROLE" ]] || die "Источник и цель должны быть разными ролями"
}

detect_current_devices() {
    CURRENT_ROOT_DEV="$(findmnt -no SOURCE /)"
    [[ -b "$CURRENT_ROOT_DEV" ]] || die "Не удалось определить устройство для /"
    CURRENT_ROOT_DISK="/dev/$(lsblk -no PKNAME "$CURRENT_ROOT_DEV")"

    CURRENT_BOOT_DEV="$(findmnt -no SOURCE /boot/firmware 2>/dev/null || true)"
    if [[ -n "$CURRENT_BOOT_DEV" && -b "$CURRENT_BOOT_DEV" ]]; then
        CURRENT_BOOT_DISK="/dev/$(lsblk -no PKNAME "$CURRENT_BOOT_DEV")"
    else
        CURRENT_BOOT_DISK=""
    fi
}

get_current_boot_order() {
    local order=""

    if command -v vcgencmd >/dev/null 2>&1; then
        order="$(vcgencmd bootloader_config 2>/dev/null | awk -F= '/^BOOT_ORDER=/{print $2; exit}')"
    fi

    if [[ -z "$order" ]] && command -v rpi-eeprom-config >/dev/null 2>&1; then
        order="$(rpi-eeprom-config 2>/dev/null | awk -F= '/^BOOT_ORDER=/{print $2; exit}')"
    fi

    printf "%s\n" "$order"
}

list_candidates() {
    local role="$1"
    local exclude_disk="${2:-}"
    local name transport size_bytes

    while read -r name; do
        [[ -n "$name" ]] || continue
        [[ -n "$exclude_disk" && "$name" == "$exclude_disk" ]] && continue

        case "$name" in
            /dev/mmcblk*boot*|/dev/mmcblk*rpmb)
                continue
                ;;
        esac

        transport="$(lsblk -dnro TRAN "$name" 2>/dev/null | awk 'NR==1 {print $1}')"
        size_bytes="$(lsblk -dnbro SIZE "$name" 2>/dev/null | awk 'NR==1 {print $1}')"
        [[ -n "$size_bytes" && "$size_bytes" -gt 0 ]] || continue

        if [[ "$role" == "usb" ]]; then
            [[ "$transport" == "usb" ]] || continue
        else
            [[ "$transport" != "usb" ]] || continue
        fi

        printf "%s\n" "$name"
    done < <(lsblk -dpno NAME,TYPE | awk '$2 == "disk" {print $1}')
}

pick_disk_for_role() {
    local role="$1"
    local exclude_disk="${2:-}"
    local candidates=()
    local disk

    while read -r disk; do
        [[ -n "$disk" ]] || continue
        candidates+=("$disk")
    done < <(list_candidates "$role" "$exclude_disk")

    if (( ${#candidates[@]} == 0 )); then
        die "Не найден диск для роли '$role'"
    fi

    if [[ "$role" == "internal" ]]; then
        for disk in "${candidates[@]}"; do
            if [[ "$disk" =~ ^/dev/mmcblk[0-9]+$ ]]; then
                printf "%s\n" "$disk"
                return
            fi
        done
    fi

    if (( ${#candidates[@]} == 1 )); then
        printf "%s\n" "${candidates[0]}"
        return
    fi

    printf "Найдено несколько дисков для роли '%s':\n" "$role" >&2
    printf "  %s\n" "${candidates[@]}" >&2
    die "Оставьте только один диск роли '$role' или упростите конфигурацию"
}

detect_source_and_target() {
    SOURCE_DISK="$(pick_disk_for_role "$SOURCE_ROLE")"
    TARGET_DISK="$(pick_disk_for_role "$TARGET_ROLE" "$SOURCE_DISK")"

    [[ "$SOURCE_DISK" != "$TARGET_DISK" ]] || die "Источник и цель совпали"

    SOURCE_BOOT_DEV="$(partition_path "$SOURCE_DISK" 1)"
    SOURCE_ROOT_DEV="$(partition_path "$SOURCE_DISK" 2)"
    [[ -b "$SOURCE_BOOT_DEV" && -b "$SOURCE_ROOT_DEV" ]] || die "На исходном диске не найдены разделы 1 и 2"

    SOURCE_BOOT_TYPE="$(blkid -s TYPE -o value "$SOURCE_BOOT_DEV" 2>/dev/null || true)"
    SOURCE_ROOT_TYPE="$(blkid -s TYPE -o value "$SOURCE_ROOT_DEV" 2>/dev/null || true)"
    [[ "$SOURCE_BOOT_TYPE" == "vfat" ]] || die "Исходный boot-раздел должен быть vfat: $SOURCE_BOOT_DEV"
    [[ "$SOURCE_ROOT_TYPE" == "ext4" ]] || die "Исходный root-раздел должен быть ext4: $SOURCE_ROOT_DEV"

    if [[ "$TARGET_DISK" == "$CURRENT_ROOT_DISK" ]]; then
        die "Целевой диск сейчас является текущим root. Загрузитесь с другого носителя и повторите"
    fi

    if [[ -n "$CURRENT_BOOT_DISK" && "$TARGET_DISK" == "$CURRENT_BOOT_DISK" ]]; then
        warn "Целевой диск сейчас смонтирован как /boot/firmware. Перед переразметкой он будет отмонтирован"
    fi
}

confirm_plan() {
    local source_size target_size
    source_size="$(lsblk -dnro SIZE "$SOURCE_DISK")"
    target_size="$(lsblk -dnro SIZE "$TARGET_DISK")"

    info "Источник ($SOURCE_ROLE): $SOURCE_DISK ($source_size)"
    info "  boot: $SOURCE_BOOT_DEV"
    info "  root: $SOURCE_ROOT_DEV"
    info "Цель ($TARGET_ROLE):     $TARGET_DISK ($target_size)"
    if (( SYNC_ONLY == 1 )); then
        warn "Режим sync-only: переразметка не будет выполнена, данные на цели будут синхронизированы через rsync --delete"
    else
        warn "Все данные на $TARGET_DISK будут уничтожены"
    fi

    if (( ASSUME_YES == 1 )); then
        return
    fi

    read -r -p "Продолжить? [y/N] " answer
    [[ "$answer" =~ ^[Yy]$ ]] || die "Операция отменена"
}

configure_bootloader() {
    local current_order tmp_cfg

    if [[ "$TARGET_ROLE" != "usb" ]]; then
        info "EEPROM не меняю: целевой диск не USB"
        return
    fi

    if (( SKIP_EEPROM == 1 )); then
        warn "Изменение EEPROM пропущено по флагу --skip-eeprom"
        return
    fi

    if [[ -n "$CURRENT_BOOT_DISK" && "$CURRENT_BOOT_DISK" == "$TARGET_DISK" ]]; then
        warn "Изменение EEPROM отложено: текущий /boot/firmware находится на целевом USB-диске"
        return
    fi

    if ! command -v rpi-eeprom-config >/dev/null 2>&1; then
        warn "rpi-eeprom-config не найден, BOOT_ORDER не изменён"
        return
    fi

    current_order="$({ vcgencmd bootloader_config 2>/dev/null || rpi-eeprom-config; } | awk -F= '/^BOOT_ORDER=/{print $2; exit}')"
    if [[ "$current_order" == "$BOOT_ORDER_USB_FIRST" ]]; then
        ok "BOOT_ORDER уже настроен: $BOOT_ORDER_USB_FIRST"
        return
    fi

    tmp_cfg="$WORKDIR/boot.conf"
    rpi-eeprom-config > "$tmp_cfg"
    if grep -q '^BOOT_ORDER=' "$tmp_cfg"; then
        sed -i "s/^BOOT_ORDER=.*/BOOT_ORDER=$BOOT_ORDER_USB_FIRST/" "$tmp_cfg"
    else
        printf "\nBOOT_ORDER=%s\n" "$BOOT_ORDER_USB_FIRST" >> "$tmp_cfg"
    fi

    info "Применяю BOOT_ORDER=$BOOT_ORDER_USB_FIRST через EEPROM"
    rpi-eeprom-config --apply "$tmp_cfg"
    ok "EEPROM обновлён. Новый BOOT_ORDER вступит в силу после reboot"
}

unmount_target_partitions() {
    local part mountpoint

    while read -r part; do
        [[ -n "$part" ]] || continue
        while read -r mountpoint; do
            [[ -n "$mountpoint" ]] || continue
            info "Отмонтирую $mountpoint"
            umount "$mountpoint"
        done < <(findmnt -rn -S "$part" -o TARGET | sort -r)
    done < <(lsblk -lnpo NAME,TYPE "$TARGET_DISK" | awk '$2 == "part" {print $1}')
}

partition_and_format_target() {
    local sfdisk_script
    local root_start_mib

    sfdisk_script="$WORKDIR/target.sfdisk"
    root_start_mib=$((4 + BOOT_SIZE_MIB))
    cat > "$sfdisk_script" <<EOF
label: dos

${TARGET_DISK}1 : start=4MiB, size=${BOOT_SIZE_MIB}MiB, type=c, bootable
${TARGET_DISK}2 : start=${root_start_mib}MiB, type=83
EOF

    unmount_target_partitions
    wipefs -af "$TARGET_DISK"
    sfdisk --wipe always "$TARGET_DISK" < "$sfdisk_script"
    partprobe "$TARGET_DISK"
    udevadm settle

    TARGET_BOOT_DEV="$(partition_path "$TARGET_DISK" 1)"
    TARGET_ROOT_DEV="$(partition_path "$TARGET_DISK" 2)"
    [[ -b "$TARGET_BOOT_DEV" && -b "$TARGET_ROOT_DEV" ]] || die "После разметки не найдены целевые разделы"

    mkfs.vfat -F 32 -n BOOTFS "$TARGET_BOOT_DEV"
    mkfs.ext4 -F -L rootfs -m 0 -E lazy_itable_init=0,lazy_journal_init=0 "$TARGET_ROOT_DEV"
    partprobe "$TARGET_DISK"
    udevadm settle

    TARGET_BOOT_PARTUUID="$(blkid -s PARTUUID -o value "$TARGET_BOOT_DEV")"
    TARGET_ROOT_PARTUUID="$(blkid -s PARTUUID -o value "$TARGET_ROOT_DEV")"
    [[ -n "$TARGET_BOOT_PARTUUID" && -n "$TARGET_ROOT_PARTUUID" ]] || die "Не удалось определить PARTUUID целевых разделов"

    ok "Цель подготовлена: boot=$TARGET_BOOT_PARTUUID root=$TARGET_ROOT_PARTUUID"
}

prepare_existing_target_partitions() {
    TARGET_BOOT_DEV="$(partition_path "$TARGET_DISK" 1)"
    TARGET_ROOT_DEV="$(partition_path "$TARGET_DISK" 2)"
    [[ -b "$TARGET_BOOT_DEV" && -b "$TARGET_ROOT_DEV" ]] || die "На целевом диске не найдены разделы 1 и 2"

    TARGET_BOOT_TYPE="$(blkid -s TYPE -o value "$TARGET_BOOT_DEV" 2>/dev/null || true)"
    TARGET_ROOT_TYPE="$(blkid -s TYPE -o value "$TARGET_ROOT_DEV" 2>/dev/null || true)"
    [[ "$TARGET_BOOT_TYPE" == "vfat" ]] || die "Целевой boot-раздел должен быть vfat: $TARGET_BOOT_DEV"
    [[ "$TARGET_ROOT_TYPE" == "ext4" ]] || die "Целевой root-раздел должен быть ext4: $TARGET_ROOT_DEV"

    unmount_target_partitions

    TARGET_BOOT_PARTUUID="$(blkid -s PARTUUID -o value "$TARGET_BOOT_DEV")"
    TARGET_ROOT_PARTUUID="$(blkid -s PARTUUID -o value "$TARGET_ROOT_DEV")"
    [[ -n "$TARGET_BOOT_PARTUUID" && -n "$TARGET_ROOT_PARTUUID" ]] || die "Не удалось определить PARTUUID целевых разделов"

    ok "Найдена существующая цель: boot=$TARGET_BOOT_PARTUUID root=$TARGET_ROOT_PARTUUID"
}

mount_filesystems() {
    if [[ "$SOURCE_BOOT_DEV" == "$CURRENT_BOOT_DEV" ]]; then
        SOURCE_BOOT_COPY_MNT="/boot/firmware"
    else
        mount -o ro "$SOURCE_BOOT_DEV" "$SOURCE_BOOT_MNT"
        SOURCE_BOOT_COPY_MNT="$SOURCE_BOOT_MNT"
    fi

    if [[ "$SOURCE_ROOT_DEV" == "$CURRENT_ROOT_DEV" ]]; then
        SOURCE_ROOT_COPY_MNT="/"
    else
        mount -o ro "$SOURCE_ROOT_DEV" "$SOURCE_ROOT_MNT"
        SOURCE_ROOT_COPY_MNT="$SOURCE_ROOT_MNT"
    fi

    mount "$TARGET_ROOT_DEV" "$TARGET_ROOT_MNT"
    mkdir -p "$TARGET_ROOT_MNT/boot/firmware"
    mount "$TARGET_BOOT_DEV" "$TARGET_BOOT_MNT"
}

detach_source_virtual_mounts() {
    local source_root path
    source_root="${SOURCE_ROOT_COPY_MNT%/}"
    if [[ "$source_root" == "/" ]]; then
        source_root=""
    fi

    shopt -s nullglob
    for path in \
        "$source_root"/home/*/.cache/gvfs \
        "$source_root"/home/*/.cache/doc \
        "$source_root"/home/*/.gvfs
    do
        if mountpoint -q "$path"; then
            warn "Отключаю виртуальный mountpoint перед rsync: $path"
            umount -l "$path" || warn "Не удалось отключить $path"
        fi
    done
    shopt -u nullglob
}

copy_boot_files() {
    info "Копирую boot-файлы"
    rsync -aHAX --delete --human-readable --info=progress2 "$SOURCE_BOOT_COPY_MNT/" "$TARGET_BOOT_MNT/"
}

copy_root_files() {
    local rsync_status

    info "Копирую rootfs. Это самая долгая часть"
    detach_source_virtual_mounts
    rsync_status=0
    rsync -aHAXx --numeric-ids --delete --human-readable --info=progress2 \
        --exclude=/boot/firmware/* \
        --exclude=/dev/* \
        --exclude=/proc/* \
        --exclude=/sys/* \
        --exclude=/tmp/* \
        --exclude=/run/* \
        --exclude=/mnt/* \
        --exclude=/media/* \
        --exclude=/home/*/.cache/gvfs \
        --exclude=/home/*/.cache/gvfs/ \
        --exclude=/home/*/.cache/gvfs/*** \
        --exclude=/home/*/.cache/doc \
        --exclude=/home/*/.cache/doc/ \
        --exclude=/home/*/.cache/doc/*** \
        --exclude=/home/*/.gvfs \
        --exclude=/home/*/.gvfs/ \
        --exclude=/home/*/.gvfs/*** \
        --exclude=home/*/.cache/gvfs \
        --exclude=home/*/.cache/gvfs/ \
        --exclude=home/*/.cache/gvfs/*** \
        --exclude=home/*/.cache/doc \
        --exclude=home/*/.cache/doc/ \
        --exclude=home/*/.cache/doc/*** \
        --exclude=home/*/.gvfs \
        --exclude=home/*/.gvfs/ \
        --exclude=home/*/.gvfs/*** \
        --exclude=/lost+found \
        --exclude=/swapfile \
        "$SOURCE_ROOT_COPY_MNT"/ "$TARGET_ROOT_MNT/" || rsync_status=$?

    if (( rsync_status == 24 )); then
        warn "rsync code 24: часть файлов исчезла во время копирования; продолжаю, это нормально для живой системы"
    elif (( rsync_status != 0 )); then
        return "$rsync_status"
    fi
}

verify_target_capacity() {
    local src_boot_used src_root_used
    local dst_boot_size dst_root_size
    local boot_reserve root_reserve

    # Небольшой запас на служебные накладные расходы ФС.
    boot_reserve=$((32 * 1024 * 1024))
    root_reserve=$((256 * 1024 * 1024))

    src_boot_used="$(df -B1 --output=used "$SOURCE_BOOT_COPY_MNT" | awk 'NR==2 {print $1}')"
    src_root_used="$(df -B1 --output=used "$SOURCE_ROOT_COPY_MNT" | awk 'NR==2 {print $1}')"
    dst_boot_size="$(df -B1 --output=size "$TARGET_BOOT_MNT" | awk 'NR==2 {print $1}')"
    dst_root_size="$(df -B1 --output=size "$TARGET_ROOT_MNT" | awk 'NR==2 {print $1}')"

    [[ -n "$src_boot_used" && -n "$src_root_used" && -n "$dst_boot_size" && -n "$dst_root_size" ]] || \
        die "Не удалось вычислить размеры файловых систем для проверки вместимости"

    info "Проверка вместимости: source boot used=$(numfmt --to=iec "$src_boot_used"), target boot size=$(numfmt --to=iec "$dst_boot_size")"
    info "Проверка вместимости: source root used=$(numfmt --to=iec "$src_root_used"), target root size=$(numfmt --to=iec "$dst_root_size")"

    if (( src_boot_used + boot_reserve > dst_boot_size )); then
        die "Целевой boot-раздел слишком мал. Нужно минимум $(numfmt --to=iec $((src_boot_used + boot_reserve))), доступно $(numfmt --to=iec "$dst_boot_size")"
    fi

    if (( src_root_used + root_reserve > dst_root_size )); then
        die "Целевой root-раздел слишком мал. Нужно минимум $(numfmt --to=iec $((src_root_used + root_reserve))), доступно $(numfmt --to=iec "$dst_root_size")"
    fi

    ok "Вместимость цели достаточна для копирования по файлам"
}

rewrite_target_config() {
    local target_cmdline target_fstab tmp_fstab

    target_cmdline="$TARGET_BOOT_MNT/cmdline.txt"
    target_fstab="$TARGET_ROOT_MNT/etc/fstab"
    tmp_fstab="$WORKDIR/fstab.new"

    [[ -f "$target_cmdline" ]] || die "На цели не найден cmdline.txt"
    [[ -f "$target_fstab" ]] || die "На цели не найден /etc/fstab"

    sed -Ei "s#root=[^ ]+#root=PARTUUID=$TARGET_ROOT_PARTUUID#" "$target_cmdline"

    awk -v boot_puuid="$TARGET_BOOT_PARTUUID" -v root_puuid="$TARGET_ROOT_PARTUUID" '
        BEGIN {
            boot_done = 0
            root_done = 0
        }
        $2 == "/boot/firmware" {
            print "PARTUUID=" boot_puuid "  /boot/firmware  vfat    defaults          0       2"
            boot_done = 1
            next
        }
        $2 == "/" {
            print "PARTUUID=" root_puuid "  /               ext4    defaults,noatime  0       1"
            root_done = 1
            next
        }
        {
            print
        }
        END {
            if (!boot_done) {
                print "PARTUUID=" boot_puuid "  /boot/firmware  vfat    defaults          0       2"
            }
            if (!root_done) {
                print "PARTUUID=" root_puuid "  /               ext4    defaults,noatime  0       1"
            }
        }
    ' "$target_fstab" > "$tmp_fstab"

    mv "$tmp_fstab" "$target_fstab"
}

install_boot_network_identity_refresh() {
    local refresh_src refresh_dst service_path wants_dir

    refresh_src="$SCRIPT_DIR/refresh_network_identity.sh"
    refresh_dst="$TARGET_ROOT_MNT/usr/local/sbin/bmi30-refresh-network-identity.sh"
    service_path="$TARGET_ROOT_MNT/etc/systemd/system/bmi30-refresh-network-identity.service"
    wants_dir="$TARGET_ROOT_MNT/etc/systemd/system/multi-user.target.wants"

    if [[ ! -f "$refresh_src" ]]; then
        warn "Не найден $refresh_src, автообновление сетевой идентичности после миграции пропущено"
        return
    fi

    info "Устанавливаю постоянное обновление hostname и сетевых имен на каждом старте цели"
    mkdir -p "$(dirname "$refresh_dst")" "$(dirname "$service_path")" "$wants_dir"
    install -m 755 "$refresh_src" "$refresh_dst"

    cat > "$service_path" <<'EOF'
[Unit]
Description=Refresh BMI30 network identity on every boot
After=local-fs.target NetworkManager.service
Wants=NetworkManager.service
ConditionPathExists=/usr/local/sbin/bmi30-refresh-network-identity.sh

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/bmi30-refresh-network-identity.sh

[Install]
WantedBy=multi-user.target
EOF

    ln -sf ../bmi30-refresh-network-identity.service "$wants_dir/bmi30-refresh-network-identity.service"
}

install_boot_ethernet_portal_enable() {
    local portal_src portal_dst portal_server_src portal_server_dst service_path wants_dir

    portal_src="$SCRIPT_DIR/setup_ethernet_portal.sh"
    portal_dst="$TARGET_ROOT_MNT/usr/local/sbin/bmi30-setup-ethernet-portal.sh"
    portal_server_src="$WORKSPACE_DIR/hotspot_info_server.py"
    portal_server_dst="$TARGET_ROOT_MNT/usr/local/hotspot_info_server.py"
    service_path="$TARGET_ROOT_MNT/etc/systemd/system/bmi30-enable-ethernet-portal.service"
    wants_dir="$TARGET_ROOT_MNT/etc/systemd/system/multi-user.target.wants"

    if [[ ! -f "$portal_src" ]]; then
        warn "Не найден $portal_src, автоподнятие Ethernet portal на целевой системе пропущено"
        return
    fi

    if [[ ! -f "$portal_server_src" ]]; then
        warn "Не найден $portal_server_src, автоподнятие Ethernet portal на целевой системе пропущено"
        return
    fi

    info "Устанавливаю автоподнятие Ethernet portal на каждом старте цели"
    mkdir -p "$(dirname "$portal_dst")" "$(dirname "$portal_server_dst")" "$(dirname "$service_path")" "$wants_dir"
    install -m 755 "$portal_src" "$portal_dst"
    install -m 755 "$portal_server_src" "$portal_server_dst"

    cat > "$service_path" <<'EOF'
[Unit]
Description=Ensure BMI30 Ethernet portal is enabled on every boot
After=local-fs.target NetworkManager.service
Wants=NetworkManager.service
ConditionPathExists=/usr/local/sbin/bmi30-setup-ethernet-portal.sh

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/bmi30-setup-ethernet-portal.sh install
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

    ln -sf ../bmi30-enable-ethernet-portal.service "$wants_dir/bmi30-enable-ethernet-portal.service"
}

configure_target_shared_desktop() {
    local xrdp_ini tmp_xrdp x11vnc_unit x11vnc_wants installer_script

    xrdp_ini="$TARGET_ROOT_MNT/etc/xrdp/xrdp.ini"
    tmp_xrdp="$WORKDIR/xrdp.ini.new"
    x11vnc_unit="$TARGET_ROOT_MNT/etc/systemd/system/bmi30-x11vnc.service"
    x11vnc_wants="$TARGET_ROOT_MNT/etc/systemd/system/graphical.target.wants/bmi30-x11vnc.service"
    installer_script="$TARGET_ROOT_MNT/home/techaid/Documents/install_bmi30_network_identity.sh"

    if [[ ! -f "$xrdp_ini" ]]; then
        info "XRDP не найден на целевой системе, настройку общего рабочего стола пропускаю"
        return
    fi

    info "Настраиваю XRDP на общий рабочий стол :0"

    awk '
        function emit_shared_desktop_section() {
            print ""
            print "[BMI30_SHARED_DESKTOP]"
            print "name=BMI30 Shared Desktop (:0)"
            print "lib=libvnc.so"
            print "ip=127.0.0.1"
            print "port=5901"
            print "username=na"
            print "password=ask"
            shared_section_done = 1
        }

        /^\[Globals\][[:space:]]*$/ {
            if (in_globals && !autorun_done) {
                print "autorun=BMI30_SHARED_DESKTOP"
                autorun_done = 1
            }
            in_globals = 1
            print
            next
        }

        /^\[BMI30_SHARED_DESKTOP\][[:space:]]*$/ {
            if (in_globals && !autorun_done) {
                print "autorun=BMI30_SHARED_DESKTOP"
                autorun_done = 1
            }
            in_globals = 0
            if (!shared_section_done) {
                emit_shared_desktop_section()
            }
            skip_section = 1
            next
        }

        /^\[[^]]+\][[:space:]]*$/ {
            if (in_globals && !autorun_done) {
                print "autorun=BMI30_SHARED_DESKTOP"
                autorun_done = 1
            }
            in_globals = 0
            if (!shared_section_done) {
                emit_shared_desktop_section()
            }
            skip_section = 0
        }

        skip_section {
            next
        }

        in_globals && /^[[:space:]]*autorun=/ {
            print "autorun=BMI30_SHARED_DESKTOP"
            autorun_done = 1
            next
        }

        {
            print
        }

        END {
            if (in_globals && !autorun_done) {
                print "autorun=BMI30_SHARED_DESKTOP"
            }
            if (!shared_section_done) {
                emit_shared_desktop_section()
            }
        }
    ' "$xrdp_ini" > "$tmp_xrdp"

    mv "$tmp_xrdp" "$xrdp_ini"

    if [[ -f "$x11vnc_unit" ]]; then
        sed -i 's/-rfbport 5900/-rfbport 5901/g' "$x11vnc_unit"
        mkdir -p "$(dirname "$x11vnc_wants")"
        ln -sf ../bmi30-x11vnc.service "$x11vnc_wants"
        ok "BMI30 shared desktop bridge включён на целевой системе (порт 5901)"
    else
        warn "Не найден $x11vnc_unit, общий рабочий стол XRDP не будет автоматически включён"
    fi

    if [[ -f "$installer_script" ]]; then
        sed -i \
            -e "s/'port=5900'/'port=5901'/g" \
            -e 's/-rfbport 5900/-rfbport 5901/g' \
            "$installer_script"
        ok "Инсталлятор на цели обновлён под порт 5901"
    fi
}

show_summary() {
    local boot_order_now=""

    boot_order_now="$(get_current_boot_order)"

    printf "\nГотово. Итоговая конфигурация цели:\n"
    if (( SYNC_ONLY == 1 )); then
        printf "  Режим:       %s -> %s (sync-only)\n" "$SOURCE_ROLE" "$TARGET_ROLE"
    else
        printf "  Режим:       %s -> %s (full copy)\n" "$SOURCE_ROLE" "$TARGET_ROLE"
    fi
    printf "  Диск:        %s\n" "$TARGET_DISK"
    printf "  Boot раздел: %s (PARTUUID=%s)\n" "$TARGET_BOOT_DEV" "$TARGET_BOOT_PARTUUID"
    printf "  Root раздел: %s (PARTUUID=%s)\n" "$TARGET_ROOT_DEV" "$TARGET_ROOT_PARTUUID"

    if [[ "$TARGET_ROLE" == "usb" ]]; then
        printf "  BOOT_ORDER:  USB-first (%s), если EEPROM шаг не был пропущен\n" "$BOOT_ORDER_USB_FIRST"
    else
        printf "  BOOT_ORDER:  не изменялся"
        if [[ -n "$boot_order_now" ]]; then
            printf " (сейчас %s)" "$boot_order_now"
        fi
        printf "\n"
    fi

    printf "\nПосле reboot проверьте:\n"
    printf "  findmnt -no SOURCE /\n"
    printf "  findmnt -no SOURCE /boot/firmware\n"

    if [[ "$TARGET_ROLE" == "internal" && "$boot_order_now" == "$BOOT_ORDER_USB_FIRST" ]]; then
        printf "\n%b[INFO]%b EEPROM сейчас в режиме USB-first (%s).\n" "$BLU" "$NC" "$BOOT_ORDER_USB_FIRST"
        printf "Это подходит для сценария \"USB подключен -> грузимся с USB, USB отсутствует -> грузимся с eMMC\".\n"
        printf "Если нужно именно проверить запуск с eMMC, временно отключите USB-накопитель перед reboot.\n"
    fi
}

main() {
    parse_args "$@"
    require_root
    require_cmds
    detect_current_devices
    detect_source_and_target

    WORKDIR="$(mktemp -d /tmp/bmi30-disk-migrate.XXXXXX)"
    SOURCE_BOOT_MNT="$WORKDIR/source-boot"
    SOURCE_ROOT_MNT="$WORKDIR/source-root"
    TARGET_ROOT_MNT="$WORKDIR/target-root"
    TARGET_BOOT_MNT="$TARGET_ROOT_MNT/boot/firmware"
    mkdir -p "$SOURCE_BOOT_MNT" "$SOURCE_ROOT_MNT" "$TARGET_ROOT_MNT"
    trap cleanup EXIT INT TERM

    step "Проверка исходного и целевого диска"
    confirm_plan

    step "Cloud backup перед полным копированием"
    run_precopy_backup

    step "Настройка BOOT_ORDER при необходимости"
    configure_bootloader

    if (( SYNC_ONLY == 1 )); then
        step "Проверка существующих разделов на целевом диске"
        prepare_existing_target_partitions
    else
        step "Разметка и форматирование целевого диска"
        partition_and_format_target
    fi

    step "Монтирование исходной и целевой систем"
    mount_filesystems

    step "Проверка вместимости целевой файловой системы"
    verify_target_capacity

    step "Копирование boot-раздела"
    copy_boot_files

    step "Копирование rootfs с прогрессом"
    copy_root_files

    step "Обновление cmdline.txt и fstab на цели"
    rewrite_target_config

    step "Подготовка автокоррекции сетевой идентичности на целевой системе"
    install_boot_network_identity_refresh

    step "Подготовка автоподнятия Ethernet portal на целевой системе"
    install_boot_ethernet_portal_enable

    step "Настройка одного общего рабочего стола XRDP на цели"
    configure_target_shared_desktop

    step "Синхронизация и отчёт"
    sync
    ok "Миграция завершена"
    show_summary
}

main "$@"
