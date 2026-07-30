#!/usr/bin/env bash
# Build and upload a project-level BMI30 disaster-recovery archive.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
WORKSPACE_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
SOURCE_DIR="$WORKSPACE_DIR"
BACKUP_ROOT="$WORKSPACE_DIR/backups"
REMOTE_TARGET=""
REMOTE_FOLDER_ID=""
RECOVERY_REMOTE_SUBDIR="recovery"
CONFIG_FILE="$SCRIPT_DIR/backup_to_cloud.conf"
LOCAL_ONLY=0
BUILT_ARCHIVE=""

usage() {
    cat <<'EOF'
Использование:
  ./utilities/backup_bmi30_recovery_to_cloud.sh [опции]

Опции:
  --source PATH             Каталог проекта Documents.
  --output-dir PATH         Локальный каталог архивов.
  --config PATH             backup_to_cloud.conf.
  --remote TARGET           rclone remote, например gdrive:.
  --remote-folder-id ID     Google Drive root folder ID.
  --remote-subdir NAME      Подкаталог recovery (по умолчанию recovery).
  --local-only              Создать и проверить без загрузки.

Recovery содержит проект, оба полных version bundle и их настройки. Не входят:
.git, venv, active runtime, cloud cache, логи, backups и secrets.
EOF
}

die() {
    printf '[ERR] %s\n' "$*" >&2
    exit 1
}

info() {
    printf '[INFO] %s\n' "$*"
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
            --source)
                [[ $# -ge 2 ]] || die "После --source нужен путь"
                SOURCE_DIR="$2"
                shift 2
                ;;
            --output-dir)
                [[ $# -ge 2 ]] || die "После --output-dir нужен путь"
                BACKUP_ROOT="$2"
                shift 2
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
                [[ $# -ge 2 ]] || die "После --remote-folder-id нужен ID"
                REMOTE_FOLDER_ID="$2"
                shift 2
                ;;
            --remote-subdir)
                [[ $# -ge 2 ]] || die "После --remote-subdir нужно имя"
                RECOVERY_REMOTE_SUBDIR="$2"
                shift 2
                ;;
            --local-only)
                LOCAL_ONLY=1
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

write_recovery_metadata() {
    local root="$1"
    local active_id bundle_ids created_at
    active_id="$(sed -n 's/^BMI30_SPLIT_BUNDLE_ID=//p' "$SOURCE_DIR/host/bmi30_split_active_version.env" | sed -n '1p')"
    bundle_ids="$(find "$SOURCE_DIR/host/bmi30_split_bundles" -mindepth 2 -maxdepth 2 -type f -name manifest.env -printf '%h\n' | xargs -r -n1 basename | sort -V | paste -sd, -)"
    created_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

    {
        printf '# BMI30 project recovery metadata\n'
        printf 'BMI30_RECOVERY_FORMAT=1\n'
        printf 'BMI30_RECOVERY_CREATED_AT=%q\n' "$created_at"
        printf 'BMI30_RECOVERY_SOURCE_HOST=%q\n' "$(hostname)"
        printf 'BMI30_RECOVERY_ACTIVE_BUNDLE=%q\n' "$active_id"
        printf 'BMI30_RECOVERY_BUNDLE_IDS=%q\n' "$bundle_ids"
    } > "$root/RECOVERY.env"

    {
        printf 'BMI30 project recovery archive\n\n'
        printf 'This archive contains the project and complete BMI30 websplit bundles.\n'
        printf 'It intentionally excludes .git, virtual environments, logs, caches and secrets.\n\n'
        printf 'Verify only:\n'
        printf '  ./Documents/utilities/restore_bmi30_recovery_archive.sh ARCHIVE --verify-only\n\n'
        printf 'Restore and activate the bundle saved as active:\n'
        printf '  sudo ./Documents/utilities/restore_bmi30_recovery_archive.sh ARCHIVE --apply --activate saved --yes\n\n'
        printf 'System packages, rclone credentials and device identity must already exist on the target Raspberry Pi.\n'
    } > "$root/RESTORE.txt"
}

build_archive() {
    [[ -d "$SOURCE_DIR/host/bmi30_split_bundles" ]] || die "Нет host/bmi30_split_bundles"
    "$SOURCE_DIR/switch_bmi30_split_versions.sh" --validate

    mkdir -p "$BACKUP_ROOT"
    local workdir root timestamp archive archive_name source_abs
    workdir="$(mktemp -d /tmp/bmi30-recovery-build.XXXXXX)"
    root="$workdir/BMI30-project-recovery"
    mkdir -p "$root/Documents"
    trap 'rm -rf -- "${workdir:-}"' RETURN
    source_abs="$(cd -- "$SOURCE_DIR" && pwd)"

    rsync -a --no-owner --no-group \
        --exclude='/.git/' \
        --exclude='/.venv/' \
        --exclude='/.usbvenv/' \
        --exclude='/.codex/' \
        --exclude='/.agents/' \
        --exclude='/backups/' \
        --exclude='/.bmi30_cloud_sync/' \
        --exclude='/secrets/' \
        --exclude='/History/' \
        --exclude='/test_logs/' \
        --exclude='/host/bmi30_active_runtime/' \
        --exclude='/host/player_recordings/' \
        --exclude='/host/bmi30_faults.log*' \
        --exclude='__pycache__/' \
        --exclude='*.pyc' \
        --exclude='*.pyo' \
        --exclude='*.log' \
        --exclude='*.tmp' \
        "$source_abs/" "$root/Documents/"

    write_recovery_metadata "$root"
    (
        cd "$root"
        find RECOVERY.env RESTORE.txt Documents -type f -print0 \
            | sort -z \
            | xargs -0 sha256sum > RECOVERY_SHA256SUMS
        sha256sum -c RECOVERY_SHA256SUMS >/dev/null
    )

    timestamp="$(date +%Y%m%d_%H%M%S)"
    archive_name="bmi30_project_recovery_${timestamp}.tar.gz"
    archive="${BACKUP_ROOT%/}/$archive_name"
    tar -czf "$archive" -C "$workdir" BMI30-project-recovery
    sha256sum "$archive" > "${archive}.sha256"

    local required
    for required in \
        BMI30-project-recovery/RECOVERY.env \
        BMI30-project-recovery/RECOVERY_SHA256SUMS \
        BMI30-project-recovery/Documents/switch_bmi30_split_versions.sh \
        BMI30-project-recovery/Documents/utilities/restore_bmi30_recovery_archive.sh
    do
        tar -tzf "$archive" "$required" >/dev/null || die "Нет обязательного файла в архиве: $required"
    done
    info "Recovery-архив создан: $archive"
    info "Размер: $(du -h "$archive" | awk '{print $1}')"

    "$SOURCE_DIR/utilities/restore_bmi30_recovery_archive.sh" "$archive" --verify-only
    BUILT_ARCHIVE="$archive"
}

upload_archive() {
    local archive="$1"
    (( LOCAL_ONLY == 0 )) || {
        info "Local-only: облачная загрузка пропущена"
        return 0
    }
    [[ -n "$REMOTE_TARGET" ]] || die "REMOTE_TARGET не задан"
    command -v rclone >/dev/null || die "rclone не установлен"

    local archive_name sidecar_name remote_dir remote_archive remote_sidecar
    local marker marker_name remote_marker local_md5 remote_md5 expected_sha remote_sha
    archive_name="$(basename -- "$archive")"
    sidecar_name="${archive_name}.sha256"
    remote_dir="$(remote_join "$REMOTE_TARGET" "$RECOVERY_REMOTE_SUBDIR")"
    remote_archive="$(remote_join "$remote_dir" "$archive_name")"
    remote_sidecar="$(remote_join "$remote_dir" "$sidecar_name")"
    marker_name="bmi30_project_recovery_latest.env"
    remote_marker="$(remote_join "$remote_dir" "$marker_name")"
    marker="${BACKUP_ROOT%/}/$marker_name"

    info "Загружаю recovery-архив: $remote_archive"
    rclone_with_root rclone copyto "$archive" "$remote_archive"
    rclone_with_root rclone copyto "${archive}.sha256" "$remote_sidecar"

    expected_sha="$(awk 'NR == 1 {print $1}' "${archive}.sha256")"
    {
        printf 'RECOVERY_KIND=project-bundles\n'
        printf 'ARCHIVE_NAME=%q\n' "$archive_name"
        printf 'ARCHIVE_SHA256=%q\n' "$expected_sha"
        printf 'ARCHIVE_SIZE=%q\n' "$(stat -c %s "$archive")"
        printf 'CREATED_AT=%q\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    } > "$marker"
    rclone_with_root rclone copyto "$marker" "$remote_marker"

    remote_sha="$(rclone_with_root rclone cat "$remote_sidecar" | awk 'NR == 1 {print $1}')"
    [[ "${remote_sha,,}" == "${expected_sha,,}" ]] || die "Remote SHA sidecar не совпадает"
    local_md5="$(md5sum "$archive" | awk '{print $1}')"
    remote_md5="$(rclone_with_root rclone md5sum "$remote_archive" | awk 'NR == 1 {print $1}')"
    [[ -n "$remote_md5" && "${remote_md5,,}" == "${local_md5,,}" ]] || die "Remote MD5 архива не совпадает"

    info "Cloud verification: SHA-256 sidecar PASS, remote MD5 PASS"
    info "Latest marker: $remote_marker"
}

main() {
    local args=("$@")
    # Load the default config before parsing, then allow CLI to override it.
    load_config
    parse_args "${args[@]}"
    [[ -d "$SOURCE_DIR" ]] || die "SOURCE_DIR не найден: $SOURCE_DIR"
    [[ "$RECOVERY_REMOTE_SUBDIR" =~ ^[A-Za-z0-9._/-]+$ ]] || die "Некорректный remote subdir"

    local archive
    build_archive
    archive="$BUILT_ARCHIVE"
    [[ -f "$archive" ]] || die "Не удалось определить созданный recovery-архив"
    upload_archive "$archive"
    info "Recovery backup завершён: $archive"
}

main "$@"
