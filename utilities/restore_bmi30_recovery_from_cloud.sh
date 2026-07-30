#!/usr/bin/env bash
# Download, verify and optionally apply the latest BMI30 project recovery.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
WORKSPACE_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
CONFIG_FILE="$SCRIPT_DIR/backup_to_cloud.conf"
BACKUP_ROOT="$WORKSPACE_DIR/backups"
DOWNLOAD_DIR=""
REMOTE_TARGET=""
REMOTE_FOLDER_ID=""
RECOVERY_REMOTE_SUBDIR="recovery"
VERIFY_ONLY=0
APPLY=0
ASSUME_YES=0
VERIFIED_ARCHIVE=""

usage() {
    cat <<'EOF'
Использование:
  ./utilities/restore_bmi30_recovery_from_cloud.sh
  ./utilities/restore_bmi30_recovery_from_cloud.sh --verify-only
  ./utilities/restore_bmi30_recovery_from_cloud.sh --apply [--yes]

Сценарий читает облачный recovery/latest, загружает архив и SHA sidecar,
проверяет весь архив и только после подтверждения восстанавливает проект.

Опции:
  --verify-only          Скачать и проверить без восстановления.
  --apply                После проверки перейти к восстановлению.
  --yes                  Подтвердить восстановление без вопроса.
  --config PATH          Файл cloud-конфигурации.
  --remote TARGET        rclone remote, например gdrive:.
  --remote-folder-id ID  Google Drive root folder ID.
  --remote-subdir NAME   Подкаталог recovery.
  --download-dir PATH    Куда сохранить загруженный архив.
EOF
}

die() {
    printf '[ERR] %s\n' "$*" >&2
    exit 1
}

info() {
    printf '[INFO] %s\n' "$*"
}

find_config_argument() {
    local -a args=("$@")
    local i
    for ((i = 0; i < ${#args[@]}; i++)); do
        if [[ "${args[$i]}" == "--config" ]]; then
            (( i + 1 < ${#args[@]} )) || die "После --config нужен путь"
            CONFIG_FILE="${args[$((i + 1))]}"
            return 0
        fi
    done
}

load_config() {
    if [[ -f "$CONFIG_FILE" ]]; then
        # shellcheck source=/dev/null
        source "$CONFIG_FILE"
    fi
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --verify-only)
                VERIFY_ONLY=1
                shift
                ;;
            --apply)
                APPLY=1
                shift
                ;;
            --yes)
                ASSUME_YES=1
                APPLY=1
                shift
                ;;
            --config)
                [[ $# -ge 2 ]] || die "После --config нужен путь"
                CONFIG_FILE="$2"
                shift 2
                ;;
            --remote)
                [[ $# -ge 2 ]] || die "После --remote нужен target"
                REMOTE_TARGET="$2"
                shift 2
                ;;
            --remote-folder-id)
                [[ $# -ge 2 ]] || die "После --remote-folder-id нужен ID или пустая строка"
                REMOTE_FOLDER_ID="$2"
                shift 2
                ;;
            --remote-subdir)
                [[ $# -ge 2 ]] || die "После --remote-subdir нужно имя"
                RECOVERY_REMOTE_SUBDIR="$2"
                shift 2
                ;;
            --download-dir)
                [[ $# -ge 2 ]] || die "После --download-dir нужен путь"
                DOWNLOAD_DIR="$2"
                shift 2
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
}

remote_join() {
    local base="$1"
    local name="$2"
    if [[ "$base" == *: ]]; then
        printf '%s%s\n' "$base" "$name"
    else
        printf '%s/%s\n' "${base%/}" "$name"
    fi
}

rclone_with_root() {
    local -a cmd=("$@" --contimeout 15s --timeout 5m --retries 3 --low-level-retries 5)
    if [[ -n "$REMOTE_FOLDER_ID" ]]; then
        cmd+=(--drive-root-folder-id "$REMOTE_FOLDER_ID")
    fi
    "${cmd[@]}"
}

marker_value() {
    local key="$1"
    local marker="$2"
    sed -n "s/^${key}=//p" "$marker" | sed -n '1p'
}

download_and_verify() {
    command -v rclone >/dev/null || die "rclone не установлен"
    [[ -x "$SCRIPT_DIR/restore_bmi30_recovery_archive.sh" ]] || \
        die "Не найден restore_bmi30_recovery_archive.sh"
    [[ -n "$REMOTE_TARGET" ]] || die "REMOTE_TARGET не задан в $CONFIG_FILE"
    [[ "$RECOVERY_REMOTE_SUBDIR" =~ ^[A-Za-z0-9._/-]+$ ]] || \
        die "Некорректный remote subdir"

    DOWNLOAD_DIR="${DOWNLOAD_DIR:-$BACKUP_ROOT}"
    mkdir -p "$DOWNLOAD_DIR"

    local remote_dir remote_marker marker_tmp marker_local
    local archive_name expected_sha expected_size remote_archive remote_sidecar
    local archive sidecar archive_tmp sidecar_tmp sidecar_sha actual_sha actual_size
    remote_dir="$(remote_join "$REMOTE_TARGET" "$RECOVERY_REMOTE_SUBDIR")"
    remote_marker="$(remote_join "$remote_dir" "bmi30_project_recovery_latest.env")"
    marker_local="$DOWNLOAD_DIR/bmi30_project_recovery_latest.env"
    marker_tmp="${marker_local}.part.$$"

    trap 'rm -f -- "${marker_tmp:-}" "${archive_tmp:-}" "${sidecar_tmp:-}"' EXIT
    info "Читаю указатель: $remote_marker"
    rclone_with_root rclone copyto "$remote_marker" "$marker_tmp"

    archive_name="$(marker_value ARCHIVE_NAME "$marker_tmp")"
    expected_sha="$(marker_value ARCHIVE_SHA256 "$marker_tmp")"
    expected_size="$(marker_value ARCHIVE_SIZE "$marker_tmp")"
    [[ "$archive_name" =~ ^bmi30_project_recovery_[0-9]{8}_[0-9]{6}\.tar\.gz$ ]] || \
        die "Некорректное имя recovery-архива в latest marker"
    [[ "$expected_sha" =~ ^[0-9a-fA-F]{64}$ ]] || \
        die "Некорректный SHA-256 в latest marker"
    [[ "$expected_size" =~ ^[0-9]+$ ]] || die "Некорректный размер в latest marker"

    archive="$DOWNLOAD_DIR/$archive_name"
    sidecar="${archive}.sha256"
    archive_tmp="${archive}.part.$$"
    sidecar_tmp="${sidecar}.part.$$"
    remote_archive="$(remote_join "$remote_dir" "$archive_name")"
    remote_sidecar="$(remote_join "$remote_dir" "${archive_name}.sha256")"

    info "Recovery latest: $archive_name"
    info "Загружаю SHA sidecar"
    rclone_with_root rclone copyto "$remote_sidecar" "$sidecar_tmp"
    sidecar_sha="$(awk 'NR == 1 {print $1}' "$sidecar_tmp")"
    [[ "${sidecar_sha,,}" == "${expected_sha,,}" ]] || \
        die "SHA-256 sidecar не совпадает с latest marker"

    actual_sha=""
    if [[ -f "$archive" ]]; then
        actual_sha="$(sha256sum "$archive" | awk '{print $1}')"
    fi
    if [[ "${actual_sha,,}" == "${expected_sha,,}" ]]; then
        info "Локальный архив уже совпадает; повторная загрузка не нужна"
    else
        info "Загружаю recovery-архив: $remote_archive"
        rclone_with_root rclone copyto "$remote_archive" "$archive_tmp"
        actual_sha="$(sha256sum "$archive_tmp" | awk '{print $1}')"
        [[ "${actual_sha,,}" == "${expected_sha,,}" ]] || \
            die "SHA-256 загруженного recovery-архива не совпадает"
        mv -f -- "$archive_tmp" "$archive"
    fi

    actual_size="$(stat -c %s "$archive")"
    [[ "$actual_size" == "$expected_size" ]] || die "Размер recovery-архива не совпадает"
    mv -f -- "$sidecar_tmp" "$sidecar"
    mv -f -- "$marker_tmp" "$marker_local"

    "$SCRIPT_DIR/restore_bmi30_recovery_archive.sh" "$archive" --verify-only
    VERIFIED_ARCHIVE="$archive"
}

main() {
    local -a args=("$@")
    find_config_argument "${args[@]}"
    load_config
    parse_args "${args[@]}"

    local archive saved_id answer
    download_and_verify
    archive="$VERIFIED_ARCHIVE"
    [[ -f "$archive" ]] || die "Не удалось определить проверенный recovery-архив"
    saved_id="$(tar -xOzf "$archive" BMI30-project-recovery/RECOVERY.env 2>/dev/null \
        | sed -n 's/^BMI30_RECOVERY_ACTIVE_BUNDLE=//p' | sed -n '1p')"

    info "Проверка облачной recovery-копии завершена"
    info "Сохранённый активный комплект: ${saved_id:-не указан}"
    if (( VERIFY_ONLY == 1 )); then
        info "Восстановление не выполнялось"
        return 0
    fi

    if (( ASSUME_YES == 0 )); then
        if [[ ! -t 0 ]]; then
            info "Нет интерактивного терминала; для применения используйте --apply --yes"
            return 0
        fi
        printf '\nВосстановить проект из этой копии и активировать сохранённый комплект? [y/N] '
        read -r answer
        [[ "$answer" =~ ^[YyДд]$ ]] || {
            info "Восстановление отменено; проверенный архив оставлен в $archive"
            return 0
        }
    elif (( APPLY == 0 )); then
        return 0
    fi

    sudo "$SCRIPT_DIR/restore_bmi30_recovery_archive.sh" \
        "$archive" --target "$WORKSPACE_DIR" --apply --activate saved --yes
}

main "$@"
