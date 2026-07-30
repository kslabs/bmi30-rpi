#!/usr/bin/env bash

# Shared rules for BMI30 cloud sync.
# "Project content" means files that should make a device publish a new build.
# Runtime state, local device settings, logs, caches, captures, and learned data
# are intentionally ignored so running devices do not become false leaders.

BMI30_PROJECT_SIGNATURE_VERSION="8"

bmi30_copy_format_duration() {
    local total_s="${1:-0}"
    [[ "$total_s" =~ ^[0-9]+$ ]] || total_s=0

    local hours minutes seconds
    hours=$((total_s / 3600))
    minutes=$(((total_s % 3600) / 60))
    seconds=$((total_s % 60))

    if (( hours > 0 )); then
        printf '%dч %02dм %02dс' "$hours" "$minutes" "$seconds"
    elif (( minutes > 0 )); then
        printf '%dм %02dс' "$minutes" "$seconds"
    else
        printf '%dс' "$seconds"
    fi
}

bmi30_copy_format_bytes() {
    local bytes="${1:-0}"
    [[ "$bytes" =~ ^[0-9]+$ ]] || bytes=0
    numfmt --to=iec --suffix=B "$bytes" 2>/dev/null || printf '%sB' "$bytes"
}

bmi30_copy_format_rate() {
    local bytes="${1:-0}"
    local elapsed_s="${2:-0}"
    [[ "$bytes" =~ ^[0-9]+$ ]] || bytes=0
    [[ "$elapsed_s" =~ ^[0-9]+$ ]] || elapsed_s=0

    if (( bytes <= 0 )); then
        printf 'н/д'
        return
    fi
    if (( elapsed_s <= 0 )); then
        elapsed_s=1
    fi

    numfmt --to=iec --suffix=B/s "$((bytes / elapsed_s))" 2>/dev/null || printf '%sB/s' "$((bytes / elapsed_s))"
}

bmi30_file_size_bytes() {
    local path="$1"
    if [[ -f "$path" ]]; then
        stat -c '%s' "$path" 2>/dev/null || printf '0'
    else
        printf '0'
    fi
}

bmi30_dir_size_bytes() {
    local path="$1"
    local bytes
    bytes="$(du -sb "$path" 2>/dev/null | awk 'NR == 1 {print $1}' || true)"
    [[ "$bytes" =~ ^[0-9]+$ ]] || bytes=0
    printf '%s' "$bytes"
}

bmi30_copy_summary_message() {
    local label="$1"
    local bytes="${2:-0}"
    local elapsed_s="${3:-0}"

    printf '%s: длительность %s, средняя скорость %s' \
        "$label" \
        "$(bmi30_copy_format_duration "$elapsed_s")" \
        "$(bmi30_copy_format_rate "$bytes" "$elapsed_s")"
    if [[ "$bytes" =~ ^[0-9]+$ ]] && (( bytes > 0 )); then
        printf ', объем %s' "$(bmi30_copy_format_bytes "$bytes")"
    fi
}

bmi30_copy_log_info() {
    if declare -F log >/dev/null 2>&1; then
        log "$*"
    else
        printf '[INFO] %s\n' "$*" >&2
    fi
}

bmi30_copy_log_warn() {
    if declare -F warn >/dev/null 2>&1; then
        warn "$*"
    else
        printf '[WARN] %s\n' "$*" >&2
    fi
}

bmi30_log_copy_result() {
    local label="$1"
    local bytes="${2:-0}"
    local elapsed_s="${3:-0}"
    local level="${4:-info}"
    local message

    message="$(bmi30_copy_summary_message "$label" "$bytes" "$elapsed_s")"
    if [[ "$level" == "warn" ]]; then
        bmi30_copy_log_warn "$message"
    else
        bmi30_copy_log_info "$message"
    fi
}

bmi30_run_timed_copy() {
    local label="$1"
    local bytes="${2:-0}"
    shift 2

    local start_ts end_ts elapsed_s rc
    start_ts="$(date +%s)"
    rc=0
    "$@" || rc=$?
    end_ts="$(date +%s)"
    elapsed_s=$((end_ts - start_ts))

    if (( rc == 0 )); then
        bmi30_log_copy_result "$label" "$bytes" "$elapsed_s"
    else
        bmi30_log_copy_result "$label завершилось с кодом $rc" "$bytes" "$elapsed_s" warn
    fi
    return "$rc"
}

bmi30_project_find_files0() {
    local source_abs="$1"
    shift || true

    find "$source_abs" \
        \( -path "$source_abs/.git" \
        -o -path "$source_abs/.venv" \
        -o -path "$source_abs/.usbvenv" \
        -o -path "$source_abs/.codex" \
        -o -path "$source_abs/.agents" \
        -o -path "$source_abs/.vscode" \
        -o -path "$source_abs/.pytest_cache" \
        -o -path "$source_abs/.mypy_cache" \
        -o -path "$source_abs/backups" \
        -o -path "$source_abs/.bmi30_cloud_sync" \
        -o -path "$source_abs/secrets" \
        -o -path "$source_abs/History" \
        -o -path "$source_abs/host/player_recordings" \
        -o -path "$source_abs/host/bmi30_active_runtime" \
        -o -path "$source_abs/host/.bmi30_active_runtime.stage.*" \
        -o -path "$source_abs/host/.bmi30_active_runtime.rollback.*" \
        -o -path "$source_abs/host/bmi30_split_bundles" \
        -o -path "$source_abs/captures" \
        -o -path "$source_abs/noise_calibration_data" \
        -o -path "$source_abs/adaptive_data" \
        -o -path "$source_abs/adaptive_data_real" \
        -o -path "$source_abs/adaptive_data_test" \
        -o -path "$source_abs/adaptive_data_test_30min" \
        -o -path "$source_abs/learn_test" \
        -o -path "$source_abs/learn_test_final" \
        -o -path "$source_abs/test5min" \
        -o -path "$source_abs/test_5min_data" \
        -o -path "$source_abs/test_adaptive_data" \
        -o -path "$source_abs/test_persistent_data" \
        -o -name "__pycache__" \) -prune \
        -o -type f \
        ! -path "$source_abs/utilities/backup_to_cloud.conf" \
        ! -path "$source_abs/host/bmi30_firmware_release.env" \
        ! -path "$source_abs/host/bmi30_config.json" \
        ! -path "$source_abs/host/bmi30_sel.json" \
        ! -path "$source_abs/host/plot_config.json" \
        ! -path "$source_abs/host/dc_offset_samples.npz" \
        ! -path "$source_abs/host/dc_offset_samples.npz.bak" \
        ! -path "$source_abs/host/usb_vendor/usb_stream_demo" \
        ! -name "backup_output.txt" \
        ! -name "status.json" \
        ! -name "*.log" \
        ! -name "*.log.*" \
        ! -name "*.pyc" \
        ! -name "*.pyo" \
        ! -name "*.npz" \
        ! -name "*.npy" \
        ! -name "*.bak" \
        ! -name "*.old" \
        ! -name "*.broken" \
        ! -name "*.tmp" \
        ! -name "*.swp" \
        ! -name "*.swo" \
        ! -name "*.o" \
        ! -name "test_*.py" \
        ! -name "*_test.py" \
        ! -name "*codex-broken-backup*" \
        ! -name "*restore-backup*" \
        ! -name ".DS_Store" \
        ! -name "full_mismatch_*" \
        ! -name "udo netstat*" \
        "$@" \
        -print0
}

bmi30_active_bundle_id() {
    local source_abs="$1"
    local active_env="$source_abs/host/bmi30_split_active_version.env"

    [[ -f "$active_env" ]] || return 1
    (
        unset BMI30_SPLIT_BUNDLE_ID
        # shellcheck source=/dev/null
        source "$active_env"
        [[ "${BMI30_SPLIT_BUNDLE_ID:-}" =~ ^[A-Za-z0-9._-]+$ ]] || exit 1
        printf '%s' "$BMI30_SPLIT_BUNDLE_ID"
    )
}

bmi30_firmware_project_find_files0() {
    local source_abs="$1"
    shift || true

    # The switcher rewrites this generated file during every successful
    # activation (selected_at/selected_by).  The selected bundle still affects
    # the signature through its path and contents below, so excluding the env
    # prevents endless reinstall loops without hiding firmware changes.
    bmi30_project_find_files0 "$source_abs" \
        ! -path "$source_abs/host/bmi30_split_active_version.env" \
        "$@"

    local bundle_id bundle_dir
    bundle_id="$(bmi30_active_bundle_id "$source_abs" || true)"
    [[ -n "$bundle_id" ]] || return 0
    bundle_dir="$source_abs/host/bmi30_split_bundles/$bundle_id"
    [[ -d "$bundle_dir" ]] || return 0
    find "$bundle_dir" -type f "$@" -print0
}

bmi30_legacy_project_find_files0() {
    local source_abs="$1"
    shift || true

    find "$source_abs" \
        \( -path "$source_abs/.git" \
        -o -path "$source_abs/.venv" \
        -o -path "$source_abs/.usbvenv" \
        -o -path "$source_abs/.codex" \
        -o -path "$source_abs/.pytest_cache" \
        -o -path "$source_abs/.mypy_cache" \
        -o -path "$source_abs/backups" \
        -o -path "$source_abs/.bmi30_cloud_sync" \
        -o -path "$source_abs/host/bmi30_active_runtime" \
        -o -path "$source_abs/host/.bmi30_active_runtime.stage.*" \
        -o -path "$source_abs/host/.bmi30_active_runtime.rollback.*" \
        -o -path "$source_abs/host/bmi30_split_bundles" \
        -o -name "__pycache__" \) -prune \
        -o -type f \
        ! -path "$source_abs/utilities/backup_to_cloud.conf" \
        ! -path "$source_abs/host/bmi30_firmware_release.env" \
        ! -name "backup_output.txt" \
        ! -name "status.json" \
        ! -name "*.log" \
        ! -name "*.log.*" \
        ! -name "full_mismatch_*" \
        "$@" \
        -print0
}

bmi30_signature_from_find0() {
    local source_abs="$1"
    shift

    "$@" "$source_abs" \
        | LC_ALL=C sort -z \
        | while IFS= read -r -d '' file; do
            local rel file_hash
            rel="${file#$source_abs/}"
            file_hash="$(sha256sum "$file" | awk '{print $1}')"
            printf '%s  %s\n' "$file_hash" "$rel"
        done \
        | sha256sum \
        | awk '{print $1}'
}

bmi30_project_signature() {
    local source_dir="$1"
    local source_abs
    source_abs="$(cd -- "$source_dir" && pwd)"
    bmi30_signature_from_find0 "$source_abs" bmi30_firmware_project_find_files0
}

bmi30_legacy_project_signature() {
    local source_dir="$1"
    local source_abs
    source_abs="$(cd -- "$source_dir" && pwd)"
    bmi30_signature_from_find0 "$source_abs" bmi30_legacy_project_find_files0
}

bmi30_project_changed_today() {
    local source_dir="$1"
    local source_abs today_start first_file
    source_abs="$(cd -- "$source_dir" && pwd)"
    today_start="$(date +%Y-%m-%d) 00:00:00"

    if IFS= read -r -d '' first_file < <(bmi30_firmware_project_find_files0 "$source_abs" -newermt "$today_start"); then
        [[ -n "$first_file" ]]
        return
    fi

    return 1
}

bmi30_signature_is_valid() {
    local value="${1:-}"
    [[ "$value" =~ ^[0-9a-fA-F]{64}$ ]]
}

bmi30_add_project_tar_excludes() {
    local array_name="$1"
    local source_name="$2"
    local -n _tar_args="$array_name"

    _tar_args+=(
        --exclude="$source_name/.git"
        --exclude="$source_name/.venv"
        --exclude="$source_name/.usbvenv"
        --exclude="$source_name/.codex"
        --exclude="$source_name/.agents"
        --exclude="$source_name/.vscode"
        --exclude="$source_name/.pytest_cache"
        --exclude="$source_name/.mypy_cache"
        --exclude="$source_name/__pycache__"
        --exclude="$source_name/backups"
        --exclude="$source_name/.bmi30_cloud_sync"
        --exclude="$source_name/secrets"
        --exclude="$source_name/History"
        --exclude="$source_name/host/player_recordings"
        --exclude="$source_name/host/bmi30_active_runtime"
        --exclude="$source_name/host/.bmi30_active_runtime.stage.*"
        --exclude="$source_name/host/.bmi30_active_runtime.rollback.*"
        --exclude="$source_name/host/bmi30_split_bundles"
        --exclude="$source_name/captures"
        --exclude="$source_name/noise_calibration_data"
        --exclude="$source_name/adaptive_data"
        --exclude="$source_name/adaptive_data_real"
        --exclude="$source_name/adaptive_data_test"
        --exclude="$source_name/adaptive_data_test_30min"
        --exclude="$source_name/learn_test"
        --exclude="$source_name/learn_test_final"
        --exclude="$source_name/test5min"
        --exclude="$source_name/test_5min_data"
        --exclude="$source_name/test_adaptive_data"
        --exclude="$source_name/test_persistent_data"
        --exclude="$source_name/utilities/backup_to_cloud.conf"
        --exclude="$source_name/host/bmi30_config.json"
        --exclude="$source_name/host/bmi30_sel.json"
        --exclude="$source_name/host/plot_config.json"
        --exclude="$source_name/host/dc_offset_samples.npz"
        --exclude="$source_name/host/dc_offset_samples.npz.bak"
        --exclude="$source_name/host/usb_vendor/usb_stream_demo"
        --exclude="backup_output.txt"
        --exclude="status.json"
        --exclude="*.log"
        --exclude="*.log.*"
        --exclude="*.pyc"
        --exclude="*.pyo"
        --exclude="*.npz"
        --exclude="*.npy"
        --exclude="*.bak"
        --exclude="*.old"
        --exclude="*.broken"
        --exclude="*.tmp"
        --exclude="*.swp"
        --exclude="*.swo"
        --exclude="*.o"
        --exclude="test_*.py"
        --exclude="*_test.py"
        --exclude="*codex-broken-backup*"
        --exclude="*restore-backup*"
        --exclude=".DS_Store"
        --exclude="full_mismatch_*"
        --exclude="udo netstat*"
    )
}

bmi30_add_project_rsync_excludes() {
    local array_name="$1"
    local active_bundle_id="${2:-}"
    local -n _rsync_args="$array_name"

    _rsync_args+=(
        --exclude='/.git/'
        --exclude='/.venv/'
        --exclude='/.usbvenv/'
        --exclude='/.codex/'
        --exclude='/.agents/'
        --exclude='/.vscode/'
        --exclude='/.pytest_cache/'
        --exclude='/.mypy_cache/'
        --exclude='/__pycache__/'
        --exclude='/backups/'
        --exclude='/.bmi30_cloud_sync/'
        --exclude='/secrets/'
        --exclude='/History/'
        --exclude='/host/player_recordings/'
        --exclude='/host/bmi30_active_runtime/'
        --exclude='/host/.bmi30_active_runtime.stage.*/'
        --exclude='/host/.bmi30_active_runtime.rollback.*/'
        --exclude='/captures/'
        --exclude='/noise_calibration_data/'
        --exclude='/adaptive_data/'
        --exclude='/adaptive_data_real/'
        --exclude='/adaptive_data_test/'
        --exclude='/adaptive_data_test_30min/'
        --exclude='/learn_test/'
        --exclude='/learn_test_final/'
        --exclude='/test5min/'
        --exclude='/test_5min_data/'
        --exclude='/test_adaptive_data/'
        --exclude='/test_persistent_data/'
        --exclude='/utilities/backup_to_cloud.conf'
        --exclude='/host/bmi30_config.json'
        --exclude='/host/bmi30_sel.json'
        --exclude='/host/plot_config.json'
        --exclude='/host/dc_offset_samples.npz'
        --exclude='/host/dc_offset_samples.npz.bak'
        --exclude='/host/usb_vendor/usb_stream_demo'
        --exclude='/backup_output.txt'
        --exclude='/status.json'
        --exclude='*.log'
        --exclude='*.log.*'
        --exclude='*.pyc'
        --exclude='*.pyo'
        --exclude='*.npz'
        --exclude='*.npy'
        --exclude='*.bak'
        --exclude='*.old'
        --exclude='*.broken'
        --exclude='*.tmp'
        --exclude='*.swp'
        --exclude='*.swo'
        --exclude='*.o'
        --exclude='test_*.py'
        --exclude='*_test.py'
        --exclude='*codex-broken-backup*'
        --exclude='*restore-backup*'
        --exclude='.DS_Store'
        --exclude='/full_mismatch_*'
        --exclude='/udo netstat*'
    )

    if [[ "$active_bundle_id" =~ ^[A-Za-z0-9._-]+$ ]]; then
        _rsync_args=(
            --include='/host/bmi30_split_bundles/'
            --include="/host/bmi30_split_bundles/$active_bundle_id/"
            --include="/host/bmi30_split_bundles/$active_bundle_id/***"
            --exclude='/host/bmi30_split_bundles/***'
            "${_rsync_args[@]}"
        )
    else
        _rsync_args=(--exclude='/host/bmi30_split_bundles/' "${_rsync_args[@]}")
    fi
}
