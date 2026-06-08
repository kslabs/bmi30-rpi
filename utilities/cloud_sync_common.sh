#!/usr/bin/env bash

# Shared rules for BMI30 cloud sync.
# "Project content" means files that should make a device publish a new build.
# Runtime state, local device settings, logs, caches, captures, and learned data
# are intentionally ignored so running devices do not become false leaders.

BMI30_PROJECT_SIGNATURE_VERSION="2"

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
        -o -path "$source_abs/docs" \
        -o -path "$source_abs/History" \
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
        ! -path "$source_abs/host/bmi30_config.json" \
        ! -path "$source_abs/host/bmi30_sel.json" \
        ! -path "$source_abs/host/plot_config.json" \
        ! -path "$source_abs/host/dc_offset_samples.npz" \
        ! -path "$source_abs/host/dc_offset_samples.npz.bak" \
        ! -path "$source_abs/host/usb_vendor/usb_stream_demo" \
        ! -name "backup_output.txt" \
        ! -name "status.json" \
        ! -name "*.conf" \
        ! -name "*.env" \
        ! -name "*.json" \
        ! -name "*.log" \
        ! -name "*.md" \
        ! -name "*.txt" \
        ! -name "*.pdf" \
        ! -name "*.rst" \
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
        -o -name "__pycache__" \) -prune \
        -o -type f \
        ! -path "$source_abs/utilities/backup_to_cloud.conf" \
        ! -name "backup_output.txt" \
        ! -name "status.json" \
        ! -name "*.log" \
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
    bmi30_signature_from_find0 "$source_abs" bmi30_project_find_files0
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

    if IFS= read -r -d '' first_file < <(bmi30_project_find_files0 "$source_abs" -newermt "$today_start"); then
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
        --exclude-vcs
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
        --exclude="$source_name/docs"
        --exclude="$source_name/History"
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
        --exclude="*.conf"
        --exclude="*.env"
        --exclude="*.json"
        --exclude="*.log"
        --exclude="*.md"
        --exclude="*.txt"
        --exclude="*.pdf"
        --exclude="*.rst"
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
        --exclude='/docs/'
        --exclude='/History/'
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
        --exclude='*.conf'
        --exclude='*.env'
        --exclude='*.json'
        --exclude='*.log'
        --exclude='*.md'
        --exclude='*.txt'
        --exclude='*.pdf'
        --exclude='*.rst'
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
}
